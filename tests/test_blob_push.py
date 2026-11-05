import base64
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from xml.etree import ElementTree as ET

import httpx
import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ServiceRequestError
from azure.core.pipeline.transport import HttpResponse, HttpTransport
from azure.identity import CredentialUnavailableError
from azure.storage.blob import BlobServiceClient

from docgen.cli import main
from docgen.errors import InputError, IntegrityError
from docgen.pipeline import push, run
from tests.test_generate_phase import BatchProvider, batch_config


@pytest.fixture(autouse=True)
def isolate_storage_test_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.setattr(time, "sleep", lambda _: None)


def connection_string(account="docgentest") -> str:
    key = base64.b64encode(b"offline-only-test-key").decode()
    return (
        f"DefaultEndpointsProtocol=https;AccountName={account};AccountKey={key};"
        "EndpointSuffix=core.windows.net"
    )


class StorageResponse(HttpResponse):
    def __init__(self, request, status=201, code=None, message="offline"):
        super().__init__(request, None)
        self.status_code = status
        self.reason = "Created" if status == 201 else "Failure"
        self.headers = httpx.Headers({
            "etag": '"offline-etag"', "last-modified": "Mon, 26 Oct 2026 12:00:00 GMT",
            "x-ms-request-id": "offline-request", "content-type": "application/xml",
            "x-ms-request-server-encrypted": "true",
        })
        if code:
            self.headers["x-ms-error-code"] = code
        self.content_type = "application/xml"
        self.payload = (
            f"<Error><Code>{code}</Code><Message>{message}</Message></Error>".encode()
            if code else b""
        )

    def body(self):
        return self.payload


class StorageTransport(HttpTransport):
    def __init__(self, failures=None, callback=None):
        self.requests = []
        self.blobs = {}
        self.blocks = {}
        self.failures = failures or {}
        self.callback = callback
        self.closed = False

    def open(self):
        pass

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def sleep(self, duration):
        pass

    def send(self, request, **kwargs):
        body = request.body
        if hasattr(body, "read"):
            body = body.read()
        body = body.encode() if isinstance(body, str) else bytes(body or b"")
        parsed = urlsplit(request.url)
        query = parse_qs(parsed.query)
        name = unquote(parsed.path).split("/", 2)[-1]
        self.requests.append({
            "url": request.url, "headers": dict(request.headers), "body": body, "name": name,
        })
        if self.callback:
            self.callback()
        failure = self.failures.get(name)
        if failure is not None:
            if isinstance(failure, BaseException):
                raise failure
            status, code = failure
            return StorageResponse(request, status, code, message="sentinel-secret")
        if query.get("comp") == ["block"]:
            self.blocks[query["blockid"][0]] = body
        elif query.get("comp") == ["blocklist"]:
            block_ids = [node.text for node in ET.fromstring(body).findall("Latest")]
            self.blobs[name] = b"".join(self.blocks[identifier] for identifier in block_ids)
        elif query.get("restype") != ["container"]:
            self.blobs[name] = body
        return StorageResponse(request)


def corpus_directory(tmp_path: Path, *, six_formats=False) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    extensions = ("pdf", "docx", "xlsx", "pptx", "html", "md") if six_formats else ("md",)
    for extension in extensions:
        (root / f"document.{extension}").write_bytes(f"Native {extension} bytes".encode())
    return root


def test_push_help_has_corpus_destination_and_credential_controls(capsys) -> None:
    with pytest.raises(SystemExit) as result:
        main(["push", "--help"])
    assert result.value.code == 0
    help_text = capsys.readouterr().out
    for option in (
        "--corpus", "--container", "--connection-string", "--env-file",
        "--prefix", "--overwrite", "--create-container",
    ):
        assert option in help_text


def test_push_missing_credentials_is_one_safe_json_error(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "document.md").write_text("# Test document\n\nBody.", encoding="utf-8")
    assert main(["push", "--corpus", str(corpus), "--container", "documents", "--json"]) == 2
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["operation"] == "push" and output["status"] == "invalid_input"
    assert "connection string" in output["failures"][0]["message"].lower()
    assert "Traceback" not in captured.err


def test_push_uses_real_sdk_streams_and_content_types_for_every_format(tmp_path: Path) -> None:
    corpus = corpus_directory(tmp_path, six_formats=True)
    nested = corpus / "nested"
    nested.mkdir()
    (nested / "with spaces.md").write_text("# A nested document", encoding="utf-8")
    transport = StorageTransport()
    result = push(
        corpus, container="documents", prefix="pilot/run-one/",
        connection_string=connection_string(), transport=transport,
    )
    assert result["status"] == "complete" and result["operation"] == "push"
    assert result["requested_count"] == 7
    assert result["accepted_count"] is None and result["verified_document_count"] is None
    details = result["details"]
    assert details["uploaded_count"] == 7
    assert details["failed_count"] == details["pending_count"] == 0
    assert details["credential_source"] == "argument"
    assert details["source_validation"] == "document_directory"
    assert transport.closed
    for path in corpus.rglob("*"):
        if not path.is_file():
            continue
        name = "pilot/run-one/" + path.relative_to(corpus).as_posix()
        assert transport.blobs[name] == path.read_bytes()
        request = next(request for request in transport.requests if request["name"] == name)
        headers = httpx.Headers(request["headers"])
        assert headers["x-ms-blob-type"] == "BlockBlob"
        assert headers["if-none-match"] == "*"
        assert headers["x-ms-meta-docgen_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert "content-md5" in headers
        expected = {
            ".pdf": "application/pdf", ".md": "text/markdown; charset=utf-8",
            ".html": "text/html; charset=utf-8",
        }
        if path.suffix in expected:
            assert headers["x-ms-blob-content-type"] == expected[path.suffix]
        else:
            assert "openxmlformats-officedocument" in headers["x-ms-blob-content-type"]


def test_overwrite_is_an_explicit_sdk_option(tmp_path: Path) -> None:
    transport = StorageTransport()
    result = push(
        corpus_directory(tmp_path), container="documents", overwrite=True,
        connection_string=connection_string(), transport=transport,
    )
    assert result["status"] == "complete"
    assert "if-none-match" not in httpx.Headers(transport.requests[0]["headers"])


@pytest.mark.parametrize(("status", "code", "expected"), [
    (409, "BlobAlreadyExists", "blob_exists"),
    (404, "ContainerNotFound", "container_not_found"),
    (403, "AuthorizationPermissionMismatch", "storage_authorization"),
    (503, "ServerBusy", "storage_error"),
])
def test_storage_failures_report_partial_uploads_without_leaking_server_errors(
    tmp_path: Path, status: int, code: str, expected: str,
) -> None:
    corpus = corpus_directory(tmp_path)
    (corpus / "second.md").write_text("Second", encoding="utf-8")
    (corpus / "third.md").write_text("Third", encoding="utf-8")
    transport = StorageTransport(failures={"second.md": (status, code)})
    result = push(
        corpus, container="documents", connection_string=connection_string(), transport=transport,
    )
    assert result["status"] == "incomplete"
    assert result["details"]["uploaded_count"] == 1
    assert result["details"]["failed_count"] == result["details"]["pending_count"] == 1
    assert result["failures"][0]["code"] == expected
    assert "sentinel-secret" not in json.dumps(result)
    assert "third.md" not in transport.blobs
    assert transport.closed


def test_network_failure_is_explicit_and_bounded(tmp_path: Path) -> None:
    transport = StorageTransport(failures={
        "document.md": ServiceRequestError("sentinel-secret"),
    })
    result = push(
        corpus_directory(tmp_path), container="documents",
        connection_string=connection_string(), transport=transport,
    )
    assert result["status"] == "incomplete"
    assert result["failures"][0]["code"] == "storage_unavailable"
    assert result["failures"][0]["retryable"] is True
    assert 1 <= len(transport.requests) <= 4
    assert "sentinel-secret" not in json.dumps(result)


def test_dotenv_fallback_and_credential_precedence_do_not_mutate_environment(
    tmp_path: Path, monkeypatch,
) -> None:
    corpus = corpus_directory(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.setenv("UNRELATED_SETTING", "original")
    (tmp_path / ".env").write_text(
        f'AZURE_STORAGE_CONNECTION_STRING="{connection_string("dotenvaccount")}"\n'
        "UNRELATED_SETTING=modified\n",
        encoding="utf-8",
    )
    result = push(corpus, container="documents", transport=StorageTransport())
    assert result["details"]["credential_source"] == "dotenv"
    assert result["details"]["endpoint"] == "https://dotenvaccount.blob.core.windows.net"
    assert "AZURE_STORAGE_CONNECTION_STRING" not in os.environ
    assert os.environ["UNRELATED_SETTING"] == "original"
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", connection_string("environmentaccount"))
    result = push(corpus, container="documents", transport=StorageTransport())
    assert result["details"]["credential_source"] == "environment"
    result = push(
        corpus, container="documents", connection_string=connection_string("argumentaccount"),
        env_file=tmp_path / "missing.env", transport=StorageTransport(),
    )
    assert result["details"]["credential_source"] == "argument"


@pytest.mark.parametrize("filename", ["plan.json", ".env", "settings.yaml", "image.png"])
def test_non_document_files_fail_before_any_cloud_request(tmp_path: Path, filename: str) -> None:
    corpus = corpus_directory(tmp_path)
    (corpus / filename).write_text("sentinel-secret", encoding="utf-8")
    transport = StorageTransport()
    with pytest.raises(InputError, match="non-document"):
        push(
            corpus, container="documents",
            connection_string=connection_string(), transport=transport,
        )
    assert transport.requests == []


@pytest.mark.parametrize("container", ["ab", "UPPERCASE", "bad--name", "-invalid"])
def test_invalid_container_is_rejected_locally(tmp_path: Path, container: str) -> None:
    with pytest.raises(InputError, match="Container"):
        push(tmp_path, container=container, connection_string="sentinel-secret")


@pytest.mark.parametrize("prefix", ["/", "/absolute", "../escape", "a//b", "a\\b", "a?sig=secret"])
def test_invalid_blob_prefix_is_rejected_locally(tmp_path: Path, prefix: str) -> None:
    with pytest.raises(InputError, match="prefix"):
        push(tmp_path, container="documents", prefix=prefix, connection_string="sentinel-secret")


def test_managed_corpus_manifest_is_verified_before_upload(tmp_path: Path) -> None:
    generated = run(batch_config(2), tmp_path / "runs", provider=BatchProvider())
    assert generated.status == "complete"
    transport = StorageTransport()
    result = push(
        generated.corpus_path, container="documents",
        connection_string=connection_string(), transport=transport,
    )
    assert result["status"] == "complete"
    assert result["details"]["source_validation"] == "published_manifest"
    file = next(generated.corpus_path.iterdir())
    file.write_bytes(file.read_bytes() + b"changed")
    failed_transport = StorageTransport()
    with pytest.raises(IntegrityError, match="manifest"):
        push(
            generated.corpus_path, container="documents",
            connection_string=connection_string(), transport=failed_transport,
        )
    assert failed_transport.requests == []


@pytest.mark.parametrize("existing", [False, True])
def test_container_creation_is_explicit_private_and_idempotent(
    tmp_path: Path, existing: bool,
) -> None:
    transport = StorageTransport(failures={
        "documents": (409, "ContainerAlreadyExists"),
    } if existing else {})
    result = push(
        corpus_directory(tmp_path), container="documents", create_container=True,
        connection_string=connection_string(), transport=transport,
    )
    assert result["status"] == "complete", result["failures"]
    assert result["details"]["container_created"] is (not existing)
    container_request = transport.requests[0]
    assert parse_qs(urlsplit(container_request["url"]).query)["restype"] == ["container"]
    assert "x-ms-blob-public-access" not in httpx.Headers(container_request["headers"])


def test_container_setup_failure_preserves_pending_files_and_unknown_write_state(
    tmp_path: Path,
) -> None:
    transport = StorageTransport(failures={"documents": (403, "AuthorizationFailure")})
    result = push(
        corpus_directory(tmp_path), container="documents", create_container=True,
        connection_string=connection_string(), transport=transport,
    )
    assert result["status"] == "incomplete"
    assert result["details"]["container_created"] is None
    assert result["details"]["uploaded_count"] == 0
    assert result["details"]["pending_count"] == 1
    assert result["failures"][0]["code"] == "storage_authorization"
    assert "sentinel-secret" not in json.dumps(result)


def test_explicit_utf8_bom_env_file_is_supported(tmp_path: Path) -> None:
    env_file = tmp_path / "storage.env"
    env_file.write_text(
        f'AZURE_STORAGE_CONNECTION_STRING="{connection_string()}"', encoding="utf-8-sig",
    )
    result = push(
        corpus_directory(tmp_path), container="documents", env_file=env_file,
        transport=StorageTransport(),
    )
    assert result["status"] == "complete"
    assert result["details"]["credential_source"] == "dotenv"


@pytest.mark.parametrize("source", ["argument", "environment", "dotenv"])
def test_empty_explicit_credential_source_does_not_fall_back(tmp_path, monkeypatch, source) -> None:
    corpus = corpus_directory(tmp_path)
    (tmp_path / ".env").write_text(
        f'AZURE_STORAGE_CONNECTION_STRING="{connection_string()}"', encoding="utf-8",
    )
    arguments = {}
    if source == "argument":
        arguments["connection_string"] = ""
    elif source == "environment":
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    else:
        (tmp_path / ".env").write_text("AZURE_STORAGE_CONNECTION_STRING=", encoding="utf-8")
    with pytest.raises(InputError, match="missing|empty"):
        push(corpus, container="documents", transport=StorageTransport(), **arguments)


def test_missing_or_unreadable_env_file_reports_a_safe_input_error(tmp_path) -> None:
    corpus = corpus_directory(tmp_path)
    with pytest.raises(InputError, match="does not exist"):
        push(corpus, container="documents", env_file=tmp_path / "missing.env")
    bad = tmp_path / "bad.env"
    bad.write_bytes(b"\xff\xfeinvalid")
    with pytest.raises(InputError, match="Cannot read"):
        push(corpus, container="documents", env_file=bad)


def test_insecure_storage_endpoint_is_rejected_without_a_request(tmp_path) -> None:
    transport = StorageTransport()
    credential = connection_string().replace("Protocol=https", "Protocol=http")
    with pytest.raises(InputError, match="HTTPS"):
        push(
            corpus_directory(tmp_path), container="documents",
            connection_string=credential, transport=transport,
        )
    assert transport.requests == [] and transport.closed


def test_sas_query_and_server_error_details_never_enter_results(tmp_path) -> None:
    credential = (
        "BlobEndpoint=https://docgentest.blob.core.windows.net;"
        "SharedAccessSignature=sv=2026-01-01&sig=sentinel-secret"
    )
    transport = StorageTransport(failures={"document.md": (403, "AuthenticationFailed")})
    result = push(
        corpus_directory(tmp_path), container="documents",
        connection_string=credential, transport=transport,
    )
    assert result["status"] == "incomplete"
    assert result["details"]["endpoint"] == "https://docgentest.blob.core.windows.net"
    assert "sentinel-secret" not in json.dumps(result)
    assert credential not in json.dumps(result)


def test_large_file_uses_bounded_sdk_block_uploads(tmp_path) -> None:
    corpus = corpus_directory(tmp_path)
    body = b"bounded-content-" * (9 * 1024**2 // len(b"bounded-content-") + 1)
    (corpus / "document.md").write_bytes(body)
    transport = StorageTransport()
    result = push(
        corpus, container="documents", connection_string=connection_string(), transport=transport,
    )
    assert result["status"] == "complete"
    assert transport.blobs["document.md"] == body
    block_requests = [
        request for request in transport.requests
        if parse_qs(urlsplit(request["url"]).query).get("comp") == ["block"]
    ]
    assert len(block_requests) == 3
    assert all(len(request["body"]) <= 4 * 1024**2 for request in block_requests)


def test_source_changes_do_not_report_success(tmp_path) -> None:
    corpus = corpus_directory(tmp_path)
    file = corpus / "document.md"
    transport = StorageTransport(callback=lambda: file.write_bytes(b"modified source"))
    result = push(
        corpus, container="documents", connection_string=connection_string(), transport=transport,
    )
    assert result["status"] == "incomplete"
    assert result["details"]["uploaded_count"] == 0
    assert result["failures"][0]["code"] == "source_changed"
    assert result["failures"][0]["remote_write_may_have_occurred"] is True


def test_cancellation_keeps_completed_blob_counts_and_closes_transport(tmp_path) -> None:
    corpus = corpus_directory(tmp_path)
    (corpus / "second.md").write_text("Second", encoding="utf-8")
    count = 0
    def interrupt():
        nonlocal count
        count += 1
        if count == 2:
            raise KeyboardInterrupt
    transport = StorageTransport(callback=interrupt)
    result = push(
        corpus, container="documents", connection_string=connection_string(), transport=transport,
    )
    assert result["status"] == "cancelled"
    assert result["details"]["uploaded_count"] == result["details"]["pending_count"] == 1
    assert transport.closed


def test_cli_push_uses_real_storage_boundary_and_safe_json(tmp_path, monkeypatch, capsys) -> None:
    transport = StorageTransport()
    original = BlobServiceClient.from_connection_string
    def configured(credential, **kwargs):
        kwargs["transport"] = transport
        return original(credential, **kwargs)
    monkeypatch.setattr(BlobServiceClient, "from_connection_string", configured)
    corpus = corpus_directory(tmp_path)
    assert main([
        "push", "--corpus", str(corpus), "--container", "documents",
        "--connection-string", connection_string(), "--prefix", "pilot", "--json",
    ]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "complete"
    assert result["details"]["uploaded_count"] == 1
    assert "pilot/document.md" in transport.blobs
    assert connection_string() not in captured.out + captured.err


def test_cli_invalid_connection_string_never_echoes_the_secret(tmp_path, capsys) -> None:
    corpus = corpus_directory(tmp_path)
    assert main([
        "push", "--corpus", str(corpus), "--container", "documents",
        "--connection-string", "sentinel-secret", "--json",
    ]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "invalid_input"
    assert "sentinel-secret" not in captured.out + captured.err


@pytest.mark.parametrize("kind", ["missing", "empty", "zero-byte", "file"])
def test_invalid_corpus_input_is_rejected_before_credentials(tmp_path, kind) -> None:
    corpus = tmp_path / "input"
    if kind == "file":
        corpus.write_text("Body", encoding="utf-8")
    elif kind != "missing":
        corpus.mkdir()
        if kind == "zero-byte":
            (corpus / "empty.md").touch()
    with pytest.raises(InputError):
        push(corpus, container="documents")


def test_filesystem_links_are_rejected_without_following_them(tmp_path, monkeypatch) -> None:
    corpus = corpus_directory(tmp_path)
    nested = corpus / "linked-directory"
    nested.mkdir()
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda path: path == nested or original(path))
    with pytest.raises(InputError, match="links"):
        push(corpus, container="documents", connection_string=connection_string())


def test_unpublished_run_staging_is_never_uploaded(tmp_path) -> None:
    root = tmp_path / "run-staging"
    root.mkdir()
    (root / "plan.json").write_text("{}", encoding="utf-8")
    staging = root / "artifacts.pending"
    staging.mkdir()
    (staging / "document.md").write_text("Unpublished", encoding="utf-8")
    with pytest.raises(InputError, match="published"):
        push(staging, container="documents", connection_string=connection_string())


def test_invalid_publication_metadata_has_a_safe_integrity_error(tmp_path) -> None:
    generated = run(batch_config(1), tmp_path / "runs", provider=BatchProvider())
    directory = generated.corpus_path.parent
    (directory / "ready-manifest.json").write_text(
        '{"sentinel-secret": "invalid metadata"}', encoding="utf-8",
    )
    with pytest.raises(IntegrityError, match="metadata") as error:
        push(
            generated.corpus_path, container="documents", connection_string=connection_string(),
        )
    assert "sentinel-secret" not in str(error.value)


def test_cli_storage_authorization_error_is_safe_and_nonzero(tmp_path, monkeypatch, capsys) -> None:
    transport = StorageTransport(failures={"document.md": (403, "AuthorizationFailure")})
    original = BlobServiceClient.from_connection_string
    def configured(credential, **kwargs):
        kwargs["transport"] = transport
        return original(credential, **kwargs)
    monkeypatch.setattr(BlobServiceClient, "from_connection_string", configured)
    assert main([
        "push", "--corpus", str(corpus_directory(tmp_path)), "--container", "documents",
        "--connection-string", connection_string(), "--json",
    ]) == 3
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "incomplete"
    assert "sentinel-secret" not in captured.out + captured.err


@pytest.mark.parametrize("option", ["overwrite", "create_container"])
def test_boolean_upload_controls_are_not_coerced(tmp_path, option) -> None:
    with pytest.raises(InputError, match="Booleans"):
        push(tmp_path, container="documents", **{option: 1})


def test_invalid_signing_key_does_not_escape_as_a_secret_bearing_exception(tmp_path) -> None:
    key = base64.b64encode(b"offline-only-test-key").decode()
    credential = connection_string().replace(key, "sentinel-secret")
    transport = StorageTransport()
    result = push(
        corpus_directory(tmp_path), container="documents",
        connection_string=credential, transport=transport,
    )
    assert result["status"] == "incomplete"
    assert result["details"]["uploaded_count"] == 0
    assert "sentinel-secret" not in json.dumps(result)
    assert credential not in json.dumps(result)
    assert transport.requests == [] and transport.closed


class EntraCredential:
    def __init__(self, *, unavailable=False):
        self.scopes = []
        self.closed = False
        self.unavailable = unavailable

    def get_token(self, *scopes, **kwargs):
        self.scopes.append(scopes)
        if self.unavailable:
            raise CredentialUnavailableError("sentinel-secret")
        return AccessToken("offline-entra-token", int(time.time()) + 3600)

    def close(self):
        self.closed = True


def test_entra_uses_storage_bearer_token_and_ignores_connection_string_sources(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "sentinel-secret")
    (tmp_path / ".env").write_text(
        "AZURE_STORAGE_CONNECTION_STRING=another-secret", encoding="utf-8",
    )
    credential = EntraCredential()
    transport = StorageTransport()
    result = push(
        corpus_directory(tmp_path), container="documents",
        account_url="https://docgentest.blob.core.windows.net",
        credential=credential, transport=transport,
    )
    assert result["status"] == "complete", result["failures"]
    assert result["details"]["auth_mode"] == "entra"
    assert result["details"]["credential_source"] == "provided_token"
    assert credential.scopes == [("https://storage.azure.com/.default",)]
    assert credential.closed is False
    assert httpx.Headers(transport.requests[0]["headers"])["authorization"] == (
        "Bearer offline-entra-token"
    )
    assert "offline-entra-token" not in json.dumps(result)
    assert "sentinel-secret" not in json.dumps(result)


def test_entra_defaults_to_logged_in_azure_cli_user_and_closes_owned_credential(
    tmp_path, monkeypatch,
) -> None:
    credential = EntraCredential()
    created = []
    def logged_user(**kwargs):
        created.append(kwargs)
        return credential
    monkeypatch.setattr("docgen.blob_push.AzureCliCredential", logged_user)
    result = push(
        corpus_directory(tmp_path), container="documents",
        account_url="https://docgentest.blob.core.windows.net",
        transport=StorageTransport(),
    )
    assert result["status"] == "complete"
    assert result["details"]["credential_source"] == "azure_cli"
    assert created == [{"process_timeout": 60}]
    assert credential.closed and credential.scopes


def test_unavailable_cli_sign_in_is_a_safe_actionable_failure(tmp_path, monkeypatch) -> None:
    credential = EntraCredential(unavailable=True)
    monkeypatch.setattr("docgen.blob_push.AzureCliCredential", lambda **kwargs: credential)
    result = push(
        corpus_directory(tmp_path), container="documents",
        account_url="https://docgentest.blob.core.windows.net",
        transport=StorageTransport(),
    )
    assert result["status"] == "incomplete"
    assert result["failures"][0]["code"] == "storage_login_required"
    assert "az login" in result["failures"][0]["message"]
    assert "sentinel-secret" not in json.dumps(result)
    assert credential.closed


@pytest.mark.parametrize("account_url", [
    "http://docgentest.blob.core.windows.net",
    "https://example.com",
    "https://docgentest.blob.core.windows.net.attacker.example",
    "https://user:sentinel-secret@docgentest.blob.core.windows.net",
    "https://docgentest.blob.core.windows.net?sig=sentinel-secret",
    "https://docgentest.blob.core.windows.net/container",
])
def test_entra_account_url_cannot_send_tokens_to_an_untrusted_endpoint(
    tmp_path, account_url,
) -> None:
    credential = EntraCredential()
    with pytest.raises(InputError, match="account URL"):
        push(
            corpus_directory(tmp_path), container="documents", account_url=account_url,
            credential=credential, transport=StorageTransport(),
        )
    assert credential.scopes == []


@pytest.mark.parametrize("other", ["connection_string", "env_file"])
def test_entra_and_connection_string_controls_are_not_combined(tmp_path, other) -> None:
    arguments = {
        "connection_string": connection_string(),
    } if other == "connection_string" else {"env_file": tmp_path / "private.env"}
    with pytest.raises(InputError, match="combine"):
        push(
            tmp_path, container="documents",
            account_url="https://docgentest.blob.core.windows.net", **arguments,
        )


def test_cli_entra_mode_uses_logged_user_without_connection_string(
    tmp_path, monkeypatch, capsys,
) -> None:
    transport = StorageTransport()
    credential = EntraCredential()
    monkeypatch.setattr("docgen.blob_push.AzureCliCredential", lambda **kwargs: credential)
    original = BlobServiceClient
    def configured(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)
    monkeypatch.setattr("docgen.blob_push.BlobServiceClient", configured)
    assert main([
        "push", "--corpus", str(corpus_directory(tmp_path)), "--container", "documents",
        "--account-url", "https://docgentest.blob.core.windows.net", "--json",
    ]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["details"]["auth_mode"] == "entra"
    assert result["details"]["credential_source"] == "azure_cli"
    assert credential.closed
    assert "offline-entra-token" not in captured.out + captured.err


def test_cli_authentication_modes_are_mutually_exclusive_and_safe(tmp_path, capsys) -> None:
    assert main([
        "push", "--corpus", str(tmp_path), "--container", "documents",
        "--account-url", "https://docgentest.blob.core.windows.net",
        "--connection-string", "sentinel-secret", "--json",
    ]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "invalid_input"
    assert "sentinel-secret" not in captured.out + captured.err


@pytest.mark.parametrize("error_code", ["AuthorizationFailure", "sentinel-secret"])
def test_only_allowlisted_azure_error_codes_are_exposed(tmp_path, error_code) -> None:
    transport = StorageTransport(failures={"document.md": (403, error_code)})
    result = push(
        corpus_directory(tmp_path), container="documents",
        account_url="https://docgentest.blob.core.windows.net",
        credential=EntraCredential(), transport=transport,
    )
    failure = result["failures"][0]
    if error_code == "AuthorizationFailure":
        assert failure["azure_error_code"] == "AuthorizationFailure"
    else:
        assert "azure_error_code" not in failure
    assert "sentinel-secret" not in json.dumps(result)
