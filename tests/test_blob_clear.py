import hashlib
import json
import time
from urllib.parse import parse_qs, unquote, urlsplit
from xml.etree import ElementTree as ET

import httpx
import pytest
from azure.core.exceptions import ServiceRequestError
from azure.core.pipeline.transport import HttpTransport

from docgen.cli import main
from docgen.errors import InputError, IntegrityError
from docgen.pipeline import clear
from tests.evaluation.azure_double import Credential
from tests.test_blob_push import StorageResponse, connection_string


class ClearTransport(HttpTransport):
    def __init__(self, names=(), *, page_size=2):
        self.blobs = {
            name: {
                "body": name.encode(),
                "etag": '"' + hashlib.sha256(name.encode()).hexdigest() + '"',
            }
            for name in names
        }
        self.page_size = page_size
        self.requests = []
        self.fail_list = None
        self.fail_delete = {}
        self.before_delete = None
        self.after_delete = None
        self.ignore_prefix = False
        self.closed = False

    def open(self):
        pass

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def send(self, request, **kwargs):
        parsed = urlsplit(request.url)
        query = parse_qs(parsed.query)
        self.requests.append(request)
        if request.method == "GET":
            assert query["comp"] == ["list"]
            if self.fail_list:
                if isinstance(self.fail_list, BaseException):
                    raise self.fail_list
                status, code = self.fail_list
                return StorageResponse(request, status, code, message="sentinel-secret")
            names = sorted(
                name
                for name in self.blobs
                if self.ignore_prefix or name.startswith(query.get("prefix", [""])[0])
            )
            offset = int(query.get("marker", ["0"])[0])
            limit = min(int(query.get("maxresults", ["5000"])[0]), self.page_size)
            selected = names[offset : offset + limit]
            root = ET.Element("EnumerationResults")
            rows = ET.SubElement(root, "Blobs")
            for name in selected:
                item = ET.SubElement(rows, "Blob")
                ET.SubElement(item, "Name").text = name
                properties = ET.SubElement(item, "Properties")
                ET.SubElement(properties, "Content-Length").text = str(
                    len(self.blobs[name]["body"])
                )
                ET.SubElement(properties, "Etag").text = self.blobs[name]["etag"]
                ET.SubElement(properties, "BlobType").text = "BlockBlob"
                ET.SubElement(properties, "Last-Modified").text = "Thu, 29 Oct 2026 10:00:00 GMT"
            ET.SubElement(root, "NextMarker").text = (
                str(offset + limit) if offset + limit < len(names) else ""
            )
            response = StorageResponse(request, 200)
            response.payload = ET.tostring(root)
            return response
        assert request.method == "DELETE", "Clear must never create or modify blobs."
        assert query.get("restype") != ["container"], "The container must never be deleted."
        parts = unquote(parsed.path).split("/", 2)
        assert len(parts) == 3 and parts[2], "A deletion must target a single named blob."
        name = parts[2]
        if self.before_delete:
            self.before_delete(name)
        failure = self.fail_delete.get(name)
        if isinstance(failure, BaseException):
            raise failure
        if failure is not None:
            status, code = failure
            return StorageResponse(request, status, code, message="sentinel-secret")
        if name not in self.blobs:
            return StorageResponse(request, 404, "BlobNotFound")
        headers = httpx.Headers(request.headers)
        assert "if-match" in headers
        if headers["if-match"] != self.blobs[name]["etag"]:
            return StorageResponse(request, 412, "ConditionNotMet")
        if self.blobs[name].get("snapshots") and headers.get("x-ms-delete-snapshots") != "include":
            return StorageResponse(request, 409, "SnapshotsPresent")
        self.blobs.pop(name)
        if self.after_delete:
            self.after_delete(name)
        return StorageResponse(request, 202)


@pytest.fixture(autouse=True)
def isolate_clear_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.setattr(time, "sleep", lambda _: None)


def invoke(transport, **kwargs):
    return clear(
        container="documents",
        connection_string=connection_string(),
        transport=transport,
        **kwargs,
    )


def test_clear_previews_all_pages_without_deleting_by_default():
    names = ("first.pdf", "second.docx", "third.xlsx", "fourth.pptx", "fifth.md")
    transport = ClearTransport(names)
    result = invoke(transport)
    assert result["operation"] == "clear" and result["status"] == "planned"
    assert result["requested_count"] == 5
    assert result["details"]["dry_run"] is True
    assert result["details"]["deleted_count"] == 0
    assert result["details"]["matched_count"] == 5
    assert set(transport.blobs) == set(names)
    assert all(request.method == "GET" for request in transport.requests)
    assert len(transport.requests) == 3
    assert transport.closed


def test_confirmed_clear_deletes_selected_versions_and_verifies_empty_scope():
    transport = ClearTransport(("file.pdf", "nested/with spaces.md", "outro/documento.xlsx"))
    result = invoke(transport, confirm=True)
    assert result["status"] == "complete", result
    assert result["details"]["deleted_count"] == 3
    assert result["details"]["pending_count"] == 0
    assert result["details"]["verification"] == "empty"
    assert not transport.blobs
    methods = [request.method for request in transport.requests]
    assert methods[:2] == ["GET", "GET"]
    assert methods[-1] == "GET"
    assert methods.count("DELETE") == 3


def test_prefix_is_a_folder_boundary_not_a_similar_neighbor_prefix():
    names = (
        "run-one/one.pdf",
        "run-one/nested/two.md",
        "run-one-more/keep.pdf",
        "run-one",
        "keep.pdf",
    )
    transport = ClearTransport(names)
    result = invoke(transport, prefix="run-one/", confirm=True)
    assert result["status"] == "complete"
    assert result["details"]["effective_prefix"] == "run-one/"
    assert set(transport.blobs) == {"run-one-more/keep.pdf", "run-one", "keep.pdf"}


def test_selection_limit_is_enforced_before_any_delete():
    transport = ClearTransport(("one", "two", "three"))
    with pytest.raises(InputError, match="no blobs were deleted"):
        invoke(transport, confirm=True, max_blobs=2)
    assert len(transport.blobs) == 3
    assert all(request.method == "GET" for request in transport.requests)


def test_changed_blob_is_not_deleted_and_later_files_remain_pending():
    transport = ClearTransport(("a", "b", "c"))
    transport.before_delete = lambda name: transport.blobs[name].update(etag='"new-version"')
    result = invoke(transport, confirm=True)
    assert result["status"] == "incomplete"
    assert result["failures"][0]["code"] == "blob_changed"
    assert result["details"]["deleted_count"] == 0
    assert result["details"]["failed_count"] == 1
    assert result["details"]["pending_count"] == 2
    assert set(transport.blobs) == {"a", "b", "c"}


def test_snapshots_are_preserved_unless_explicitly_included():
    transport = ClearTransport(("a",))
    transport.blobs["a"]["snapshots"] = True
    result = invoke(transport, confirm=True)
    assert result["status"] == "incomplete"
    assert result["failures"][0]["code"] == "blob_has_snapshots"
    assert "a" in transport.blobs
    result = invoke(transport, confirm=True, include_snapshots=True)
    assert result["status"] == "complete"
    assert not transport.blobs


def test_new_blobs_are_reported_but_not_swept_into_the_deletion_plan():
    transport = ClearTransport(("a",))
    transport.after_delete = lambda _: transport.blobs.update(
        {
            "new-during-clear": {"body": b"new", "etag": '"new"'},
        }
    )
    result = invoke(transport, confirm=True)
    assert result["status"] == "incomplete"
    assert result["failures"][0]["code"] == "clear_scope_not_empty"
    assert result["details"]["deleted_count"] == 1
    assert result["details"]["verification"] == "not_empty"
    assert set(transport.blobs) == {"new-during-clear"}


def test_already_absent_blob_is_distinguished_from_a_confirmed_delete():
    transport = ClearTransport(("a",))
    transport.before_delete = lambda name: transport.blobs.pop(name)
    result = invoke(transport, confirm=True)
    assert result["status"] == "complete"
    assert result["details"]["deleted_count"] == 0
    assert result["details"]["already_absent_count"] == 1
    assert result["details"]["verification"] == "empty"


@pytest.mark.parametrize("confirm", [False, True])
def test_empty_container_is_a_valid_preview_or_verified_clear(confirm):
    result = invoke(ClearTransport(), confirm=confirm)
    assert result["status"] == ("complete" if confirm else "planned")
    assert result["details"]["matched_count"] == result["details"]["deleted_count"] == 0


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (403, "AuthorizationPermissionMismatch", "storage_authorization"),
        (404, "ContainerNotFound", "container_not_found"),
    ],
)
def test_selection_failures_are_safe_and_cannot_delete(status, code, expected):
    transport = ClearTransport(("a",))
    transport.fail_list = (status, code)
    result = invoke(transport, confirm=True)
    assert result["status"] == "incomplete"
    assert result["failures"][0]["code"] == expected
    assert result["failures"][0]["phase"] == "clear.select"
    assert result["failures"][0]["remote_delete_may_have_occurred"] is False
    assert all(request.method == "GET" for request in transport.requests)
    assert "sentinel-secret" not in json.dumps(result)


def test_partial_delete_failure_preserves_exact_progress_and_redacts_error_bodies():
    transport = ClearTransport(("a", "b", "c"))
    transport.fail_delete["b"] = (403, "AuthorizationPermissionMismatch")
    result = invoke(transport, confirm=True)
    assert result["status"] == "incomplete"
    assert result["details"]["deleted_count"] == 1
    assert result["details"]["failed_count"] == result["details"]["pending_count"] == 1
    assert set(transport.blobs) == {"b", "c"}
    assert "sentinel-secret" not in json.dumps(result)


def test_delete_cancellation_preserves_known_and_unknown_outcomes():
    transport = ClearTransport(("a", "b", "c"))
    transport.fail_delete["b"] = KeyboardInterrupt()
    result = invoke(transport, confirm=True)
    assert result["status"] == "cancelled"
    assert result["details"]["deleted_count"] == 1
    assert result["details"]["unknown_count"] == result["details"]["pending_count"] == 1
    assert set(transport.blobs) == {"b", "c"}


def test_entra_uses_the_provided_credential_and_never_uses_connection_string_sources(monkeypatch):
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "sentinel-invalid-connection")
    credential = Credential()
    transport = ClearTransport(("a",))
    result = clear(
        container="documents",
        account_url="https://offline.blob.core.windows.net",
        credential=credential,
        transport=transport,
        confirm=True,
    )
    assert result["status"] == "complete"
    assert result["details"]["credential_source"] == "provided_token"
    assert credential.scopes == ["https://storage.azure.com/.default"]
    assert all("Bearer " in request.headers["Authorization"] for request in transport.requests)
    assert "sentinel-invalid" not in json.dumps(result)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"confirm": 1},
        {"include_snapshots": 1},
        {"max_blobs": True},
        {"max_blobs": 0},
        {"max_blobs": 100001},
        {"prefix": "../unsafe"},
        {"prefix": "/"},
    ],
)
def test_invalid_clear_controls_are_rejected_before_network(kwargs):
    transport = ClearTransport(("a",))
    with pytest.raises(InputError):
        invoke(transport, **kwargs)
    assert not transport.requests


def test_clear_reads_env_and_dotenv_credentials_without_exposing_them(tmp_path, monkeypatch):
    env_file = tmp_path / "storage.env"
    env_file.write_text("AZURE_STORAGE_CONNECTION_STRING=" + connection_string(), encoding="utf-8")
    transport = ClearTransport(("a",))
    result = clear(container="documents", env_file=env_file, transport=transport)
    assert result["status"] == "planned" and result["details"]["credential_source"] == "dotenv"
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", connection_string())
    result = clear(container="documents", transport=ClearTransport())
    assert result["details"]["credential_source"] == "environment"
    assert "AccountKey" not in json.dumps(result)


def test_cli_exposes_safe_modes_and_reports_json_without_implicit_deletion(capsys, monkeypatch):
    import docgen.blob_push as storage

    transport = ClearTransport(("a",))
    real_factory = storage.BlobServiceClient.from_connection_string
    monkeypatch.setattr(
        storage.BlobServiceClient,
        "from_connection_string",
        lambda value, **kwargs: real_factory(value, **{**kwargs, "transport": transport}),
    )
    args = [
        "clear",
        "--container",
        "documents",
        "--connection-string",
        connection_string(),
        "--json",
    ]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "planned"
    assert "a" in transport.blobs
    assert main([*args, "--yes"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "complete"
    assert not transport.blobs
    assert main([*args, "--yes", "--dry-run"]) == 2
    assert json.loads(capsys.readouterr().out)["failures"][0]["code"] == "invalid_arguments"


def test_post_delete_integrity_error_preserves_completed_deletion_report():
    transport = ClearTransport(("run/a", "outside/keep"))

    def malformed_verification(_):
        transport.ignore_prefix = True

    transport.after_delete = malformed_verification
    result = invoke(transport, prefix="run", confirm=True)
    assert result["status"] == "incomplete"
    assert result["details"]["deleted_count"] == 1
    assert result["details"]["verification"] == "failed"
    assert result["failures"][0]["phase"] == "clear.verify"
    assert set(transport.blobs) == {"outside/keep"}


def test_post_delete_authorization_failure_does_not_discard_progress():
    transport = ClearTransport(("a",))
    transport.after_delete = lambda _: setattr(
        transport,
        "fail_list",
        (403, "AuthorizationPermissionMismatch"),
    )
    result = invoke(transport, confirm=True)
    assert result["status"] == "incomplete"
    assert result["details"]["deleted_count"] == 1
    assert result["details"]["verification"] == "failed"
    assert result["failures"][0]["phase"] == "clear.verify"


def test_network_delete_failure_is_explicit_and_never_reported_as_empty_success():
    transport = ClearTransport(("a", "b"))
    transport.fail_delete["a"] = ServiceRequestError("sentinel-network-secret")
    result = invoke(transport, confirm=True)
    assert result["status"] == "incomplete"
    assert result["failures"][0]["code"] == "storage_unavailable"
    assert result["details"]["deleted_count"] == 0
    assert result["details"]["pending_count"] == 1
    assert "sentinel-network-secret" not in json.dumps(result)


def test_cancelled_selection_does_not_issue_delete_requests():
    transport = ClearTransport(("a",))
    transport.fail_list = KeyboardInterrupt()
    result = invoke(transport, confirm=True)
    assert result["status"] == "cancelled"
    assert result["details"]["selection_complete"] is False
    assert all(request.method == "GET" for request in transport.requests)


def test_missing_credentials_and_conflicting_authentication_are_rejected_safely(capsys):
    assert main(["clear", "--container", "documents", "--yes", "--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "invalid_input"
    assert "authentication" in result["failures"][0]["message"]
    transport = ClearTransport(("a",))
    with pytest.raises(InputError, match="Do not combine"):
        clear(
            container="documents",
            account_url="https://offline.blob.core.windows.net",
            connection_string=connection_string(),
            transport=transport,
            confirm=True,
        )
    assert not transport.requests


def test_retention_or_lease_conflict_never_suggests_upload_overwrite():
    transport = ClearTransport(("a",))
    transport.fail_delete["a"] = (409, "BlobImmutableDueToPolicy")
    result = invoke(transport, confirm=True)
    assert result["status"] == "incomplete"
    assert result["failures"][0]["code"] == "storage_conflict"
    assert "--overwrite" not in result["failures"][0]["message"]
    assert set(transport.blobs) == {"a"}


@pytest.mark.parametrize(
    "name,prefix",
    [
        ("../other-container/blob", ""),
        ("run/../../outside/blob", "run"),
    ],
)
def test_dot_segment_blob_names_cannot_escape_the_selected_scope(name, prefix):
    transport = ClearTransport((name, "run/keep"))
    with pytest.raises(IntegrityError, match="selection"):
        invoke(transport, prefix=prefix, confirm=True)
    assert all(request.method == "GET" for request in transport.requests)
    assert set(transport.blobs) == {name, "run/keep"}
