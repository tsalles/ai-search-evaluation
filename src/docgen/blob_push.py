from __future__ import annotations

import hashlib
import os
import re
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from azure.core.credentials import TokenCredential
from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.core.pipeline.transport import HttpRequest, HttpResponse, HttpTransport
from azure.identity import AzureCliCredential, CredentialUnavailableError
from azure.storage.blob import BlobServiceClient, ContentSettings
from dotenv import dotenv_values
from pydantic import JsonValue, ValidationError

from docgen.errors import InputError, IntegrityError
from docgen.planning import RunPlan, base_result
from docgen.publication import ReadyManifest

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".html": "text/html; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}
CONNECTION_VARIABLE = "AZURE_STORAGE_CONNECTION_STRING"
ENTRA_BLOB_SUFFIXES = (".blob.core.windows.net", ".blob.storage.azure.net")
STORAGE_ERROR_CODES = {
    "AuthenticationFailed", "AuthorizationFailure", "AuthorizationPermissionMismatch",
    "AuthorizationSourceIPMismatch", "AuthorizationProtocolMismatch",
    "AuthorizationServiceMismatch", "AuthorizationResourceTypeMismatch",
    "KeyBasedAuthenticationNotPermitted", "PublicNetworkAccessDisabled",
    "BlobAlreadyExists", "ContainerAlreadyExists", "ContainerNotFound", "ServerBusy",
}


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    name: str
    size: int
    sha256: str
    signature: tuple[int, int, int, int]


def file_signature(stat: os.stat_result) -> tuple[int, int, int, int]:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_documents(corpus: Path) -> tuple[Path, tuple[SourceDocument, ...], str]:
    try:
        if corpus.is_symlink() or corpus.is_junction() or not corpus.is_dir():
            raise InputError("Corpus must be an existing directory, not a filesystem link.")
        root = corpus.resolve()
        pending = [root]
        documents = []
        while pending:
            for path in sorted(pending.pop().iterdir()):
                if path.is_symlink() or path.is_junction():
                    raise InputError("Corpus directories cannot contain filesystem links.")
                if path.is_dir():
                    pending.append(path)
                elif path.is_file() and path.suffix.lower() in CONTENT_TYPES:
                    stat = path.stat()
                    if stat.st_size == 0:
                        raise InputError("Corpus documents must not be empty.")
                    digest = file_hash(path)
                    if file_signature(path.stat()) != file_signature(stat):
                        raise IntegrityError("A corpus document changed during upload preflight.")
                    documents.append(SourceDocument(
                        path=path, name=path.relative_to(root).as_posix(), size=stat.st_size,
                        sha256=digest, signature=file_signature(stat),
                    ))
                else:
                    raise InputError(
                        "Corpus contains a non-document file. Use the corpus directory, "
                        "not a run directory, reports, configuration, or credentials."
                    )
        if not documents:
            raise InputError("Corpus contains no supported documents.")
        ordered = tuple(sorted(documents, key=lambda document: document.name))
        markers = ("plan.json", "state.sqlite3", "ready-manifest.json")
        managed = any((root.parent / name).exists() for name in markers)
        if not managed:
            return root, ordered, "document_directory"
        required = ("plan.json", "allocation.json", "ready-manifest.json")
        if root.name != "corpus" or any(
            not (root.parent / name).is_file()
            or (root.parent / name).is_symlink()
            or (root.parent / name).is_junction()
            for name in required
        ):
            raise InputError("Only a complete published corpus can be pushed from a generator run.")
        try:
            plan = RunPlan.model_validate_json((root.parent / "plan.json").read_bytes())
            ready = ReadyManifest.model_validate_json(
                (root.parent / "ready-manifest.json").read_bytes()
            )
        except ValidationError:
            raise IntegrityError("Published corpus metadata is invalid.") from None
        expected = {artifact.filename: artifact for artifact in ready.artifacts}
        if (
            ready.run_id != plan.run_id
            or len(ready.artifacts) != len(plan.blueprints)
            or len(expected) != len(ready.artifacts)
            or set(expected) != {document.name for document in ordered}
            or ready.allocation_hash != file_hash(root.parent / "allocation.json")
            or any(
                expected[document.name].sha256 != document.sha256
                or expected[document.name].byte_count != document.size
                for document in ordered
            )
        ):
            raise IntegrityError("Corpus files differ from their complete publication manifest.")
        return root, ordered, "published_manifest"
    except OSError:
        raise InputError("Cannot inspect or read the requested corpus directory.") from None


def storage_credentials(
    connection_string: str | None, env_file: Path | None,
) -> tuple[str, str]:
    value: str | None
    if connection_string is not None:
        value, source = connection_string, "argument"
    elif CONNECTION_VARIABLE in os.environ:
        value, source = os.environ[CONNECTION_VARIABLE], "environment"
    else:
        path = Path(".env") if env_file is None else env_file
        try:
            if not path.is_file():
                if env_file is not None:
                    raise InputError("The specified environment file does not exist.")
                raise InputError(
                    "Storage authentication is required: use --account-url for Azure CLI login, "
                    "or a connection string via --connection-string, "
                    "AZURE_STORAGE_CONNECTION_STRING, or a local .env file."
                )
            value = dotenv_values(path, interpolate=False, encoding="utf-8-sig").get(
                CONNECTION_VARIABLE,
            )
        except (OSError, UnicodeError):
            raise InputError("Cannot read the storage environment file.") from None
        source = "dotenv"
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise InputError("The storage connection string is missing, empty, or invalid.")
    return value.strip(), source


def destination(container: str, prefix: str) -> str:
    if (
        not isinstance(container, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", container) is None
        or "--" in container
    ):
        raise InputError(
            "Container names require 3-63 lowercase letters/digits and single hyphens."
        )
    if not isinstance(prefix, str) or len(prefix) > 512 or any(
        ord(char) < 32 or ord(char) == 127 or char in "\\?#" for char in prefix
    ):
        raise InputError("Blob prefix must be a relative, slash-separated path without query data.")
    normalized = prefix[:-1] if prefix.endswith("/") else prefix
    if normalized and any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise InputError("Blob prefix cannot contain empty or traversal path segments.")
    if prefix and not normalized:
        raise InputError("Blob prefix must not be an absolute path.")
    return normalized


def entra_account_url(value: str) -> str:
    try:
        endpoint = urlsplit(value.strip())
        valid = (
            endpoint.scheme == "https"
            and endpoint.hostname is not None
            and endpoint.hostname.endswith(ENTRA_BLOB_SUFFIXES)
            and endpoint.port in {None, 443}
            and endpoint.username is None and endpoint.password is None
            and endpoint.path in {"", "/"} and not endpoint.query and not endpoint.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise InputError(
            "Entra account URL must be a canonical HTTPS Azure Blob account endpoint, "
            "without credentials, query data, or a container path."
        )
    return urlunsplit((endpoint.scheme, endpoint.netloc, "", "", ""))


def azure_failure(error: AzureError) -> dict[str, JsonValue]:
    code, message, retryable = (
        "storage_error", "Azure Blob Storage operation failed.", False,
    )
    if isinstance(error, CredentialUnavailableError):
        code = "storage_login_required"
        message = (
            "Azure CLI credentials are unavailable; run az login and select the correct account."
        )
    elif isinstance(error, ResourceExistsError):
        code = "blob_exists"
        message = "A destination blob already exists; choose a different prefix or --overwrite."
    elif isinstance(error, ResourceNotFoundError):
        code = "container_not_found"
        message = "The destination container was not found; create it or use --create-container."
    elif isinstance(error, (ServiceRequestError, ServiceResponseError)):
        code, message, retryable = (
            "storage_unavailable", "Cannot reach Azure Blob Storage; check connectivity and retry.",
            True,
        )
    elif isinstance(error, ClientAuthenticationError) or (
        isinstance(error, HttpResponseError) and error.status_code in {401, 403}
    ):
        code, message = (
            "storage_authorization",
            "Azure denied access; check credentials, permissions, and storage network rules.",
        )
    elif isinstance(error, HttpResponseError):
        retryable = error.status_code in {408, 429, 500, 502, 503, 504}
    failure: dict[str, JsonValue] = {
        "code": code, "phase": "push", "retryable": retryable, "message": message,
    }
    if isinstance(error, HttpResponseError) and isinstance(error.status_code, int):
        failure["http_status"] = error.status_code
    raw_code = getattr(error, "error_code", None)
    if isinstance(raw_code, str) and raw_code in STORAGE_ERROR_CODES:
        failure["azure_error_code"] = raw_code
    return failure


def blob_service(
    resources: ExitStack, *, connection_string: str | None = None,
    account_url: str | None = None, credential: TokenCredential | None = None,
    env_file: Path | None = None,
    transport: HttpTransport[HttpRequest, HttpResponse] | None = None,
) -> tuple[BlobServiceClient, str, str]:
    if account_url is not None:
        if connection_string is not None or env_file is not None:
            raise InputError("Do not combine an Entra account URL with connection-string controls.")
        account_url = entra_account_url(account_url)
        token_credential = credential
        if token_credential is None:
            owned_credential = AzureCliCredential(process_timeout=60)
            resources.callback(owned_credential.close)
            token_credential = owned_credential
            credential_source = "azure_cli"
        else:
            credential_source = "provided_token"
        try:
            service = BlobServiceClient(
                account_url, credential=token_credential, retry_total=3,
                connection_timeout=10, read_timeout=60, logging_enable=False,
                max_single_put_size=8 * 1024**2, max_block_size=4 * 1024**2,
                transport=transport,
            )
        except ValueError:
            raise InputError("Invalid Azure Blob Storage account URL.") from None
    else:
        if credential is not None:
            raise InputError("An injected token credential requires an Entra account URL.")
        value, credential_source = storage_credentials(connection_string, env_file)
        try:
            service = BlobServiceClient.from_connection_string(
                value, retry_total=3, connection_timeout=10, read_timeout=60,
                logging_enable=False, max_single_put_size=8 * 1024**2,
                max_block_size=4 * 1024**2, transport=transport,
            )
        except ValueError:
            raise InputError("Invalid Azure Blob Storage connection string.") from None
    resources.enter_context(service)
    try:
        endpoint = urlsplit(service.url)
    except ValueError:
        raise InputError("Invalid Azure Blob Storage endpoint.") from None
    if (
        endpoint.scheme != "https" or not endpoint.hostname
        or endpoint.username is not None or endpoint.password is not None
    ):
        raise InputError(
            "An HTTPS Azure Blob Storage endpoint without URL credentials is required."
        )
    safe_endpoint = urlunsplit((endpoint.scheme, endpoint.netloc, "", "", ""))
    return service, credential_source, safe_endpoint


def push(
    corpus: Path, *, container: str, connection_string: str | None = None,
    account_url: str | None = None, credential: TokenCredential | None = None,
    env_file: Path | None = None, prefix: str = "", overwrite: bool = False,
    create_container: bool = False,
    transport: HttpTransport[HttpRequest, HttpResponse] | None = None,
) -> dict[str, JsonValue]:
    prefix = destination(container, prefix)
    if account_url is not None:
        if connection_string is not None or env_file is not None:
            raise InputError("Do not combine an Entra account URL with connection-string controls.")
        account_url = entra_account_url(account_url)
    elif credential is not None:
        raise InputError("An injected token credential requires an Entra account URL.")
    if type(overwrite) is not bool or type(create_container) is not bool:
        raise InputError("Overwrite and container-creation controls must be Booleans.")
    root, documents, validation = source_documents(corpus)
    names = [f"{prefix}/{document.name}" if prefix else document.name for document in documents]
    if any(len(name) > 1024 for name in names):
        raise InputError("A destination blob name exceeds the 1024-character limit.")
    rows: list[dict[str, JsonValue]] = [
        {
            "filename": document.name, "blob_name": name, "byte_count": document.size,
            "sha256": document.sha256, "status": "pending",
        }
        for document, name in zip(documents, names, strict=True)
    ]
    failures: list[JsonValue] = []
    container_created: bool | None = False
    cancelled = False
    safe_endpoint: str | None = None
    credential_source: str | None = None
    try:
        with ExitStack() as resources:
            service, credential_source, safe_endpoint = blob_service(
                resources, connection_string=connection_string, account_url=account_url,
                credential=credential, env_file=env_file, transport=transport,
            )
            target = service.get_container_client(container)
            if create_container:
                container_created = None
                try:
                    target.create_container()
                    container_created = True
                except ResourceExistsError:
                    container_created = False
            for document, row in zip(documents, rows, strict=True):
                try:
                    if document.path.is_symlink() or document.path.is_junction():
                        raise IntegrityError("Source file changed into a filesystem link.")
                    with document.path.open("rb") as stream:
                        if file_signature(os.fstat(stream.fileno())) != document.signature:
                            raise IntegrityError("Source file changed after upload preflight.")
                        uploaded = target.get_blob_client(str(row["blob_name"])).upload_blob(
                            data=stream, length=document.size,
                            blob_type="BlockBlob", overwrite=overwrite, validate_content=True,
                            metadata={"docgen_sha256": document.sha256},
                            content_settings=ContentSettings(
                                content_type=CONTENT_TYPES[document.path.suffix.lower()],
                            ),
                            max_concurrency=1, logging_enable=False,
                        )
                        if (
                            file_signature(os.fstat(stream.fileno())) != document.signature
                            or file_signature(document.path.stat()) != document.signature
                        ):
                            raise IntegrityError("Source file changed while being uploaded.")
                except AzureError as error:
                    row["status"] = "failed"
                    failures.append({
                        **azure_failure(error), "filename": document.name,
                        "remote_write_may_have_occurred": True,
                    })
                    break
                except (OSError, IntegrityError):
                    row["status"] = "failed"
                    failures.append({
                        "code": "source_changed", "phase": "push", "retryable": False,
                        "filename": document.name,
                        "message": (
                            "A source file changed or became unreadable; remote writes may exist."
                        ),
                        "remote_write_may_have_occurred": True,
                    })
                    break
                row["status"] = "uploaded"
                etag = uploaded.get("etag")
                if isinstance(etag, str):
                    row["etag"] = etag
    except AzureError as error:
        failures.append({**azure_failure(error), "remote_write_may_have_occurred": True})
    except KeyboardInterrupt:
        cancelled = True
        failures.append({
            "code": "cancelled", "phase": "push", "retryable": True,
            "message": "Upload cancelled; already written blobs were retained.",
            "remote_write_may_have_occurred": True,
        })
    uploaded_rows = [row for row in rows if row["status"] == "uploaded"]
    result = base_result(
        "push", "cancelled" if cancelled else "incomplete" if failures else "complete",
    )
    result.update(
        requested_count=len(documents),
        failures=failures,
        details={
            "source_path": str(root), "source_validation": validation,
            "container": container, "prefix": prefix, "endpoint": safe_endpoint,
            "credential_source": credential_source, "container_created": container_created,
            "auth_mode": "entra" if account_url is not None else "connection_string",
            "uploaded_count": len(uploaded_rows),
            "uploaded_bytes": sum(
                document.size for document, row in zip(documents, rows, strict=True)
                if row["status"] == "uploaded"
            ),
            "failed_count": sum(row["status"] == "failed" for row in rows),
            "pending_count": sum(row["status"] == "pending" for row in rows),
            "files": [dict(row) for row in rows],
        },
    )
    return result
