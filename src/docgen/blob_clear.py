from contextlib import ExitStack
from pathlib import Path

from azure.core import MatchConditions
from azure.core.credentials import TokenCredential
from azure.core.exceptions import AzureError, HttpResponseError, ResourceNotFoundError
from azure.core.pipeline.transport import HttpRequest, HttpResponse, HttpTransport
from pydantic import JsonValue

from docgen.blob_push import azure_failure, blob_service, destination
from docgen.errors import InputError, IntegrityError
from docgen.planning import base_result


def clear_failure(error: AzureError, phase: str) -> dict[str, JsonValue]:
    failure = azure_failure(error)
    failure["phase"] = phase
    code = getattr(error, "error_code", None)
    if isinstance(error, ResourceNotFoundError):
        failure["code"] = "container_not_found"
        failure["message"] = "The specified Blob container was not found."
    elif isinstance(error, HttpResponseError) and error.status_code == 412:
        failure["code"] = "blob_changed"
        failure["message"] = "A selected Blob version changed; no replacement was deleted."
    elif code == "SnapshotsPresent":
        failure["code"] = "blob_has_snapshots"
        failure["message"] = (
            "The Blob has snapshots; use --include-snapshots only if you intend to delete them."
        )
    elif isinstance(error, HttpResponseError) and error.status_code == 409:
        failure["code"] = "storage_conflict"
        failure["message"] = (
            "Azure blocked deletion due to protection, a lease or conflicting Blob state."
        )
    return failure


def clear(
    *,
    container: str,
    connection_string: str | None = None,
    account_url: str | None = None,
    credential: TokenCredential | None = None,
    env_file: Path | None = None,
    prefix: str = "",
    confirm: bool = False,
    include_snapshots: bool = False,
    max_blobs: int = 10000,
    transport: HttpTransport[HttpRequest, HttpResponse] | None = None,
) -> dict[str, JsonValue]:
    prefix = destination(container, prefix)
    if type(confirm) is not bool or type(include_snapshots) is not bool:
        raise InputError("Clear confirmation and snapshot controls must be Booleans.")
    if type(max_blobs) is not int or not 1 <= max_blobs <= 100000:
        raise InputError("Clear --max-blobs must be an integer between 1 and 100000.")
    scoped_prefix = prefix + "/" if prefix else ""
    rows: list[dict[str, JsonValue]] = []
    failures: list[JsonValue] = []
    endpoint = None
    credential_source = None
    phase = "clear.select"
    selection_complete = False
    verification = "not_performed"
    remaining_blob: str | None = None
    cancelled = False
    try:
        with ExitStack() as resources:
            service, credential_source, endpoint = blob_service(
                resources,
                connection_string=connection_string,
                account_url=account_url,
                credential=credential,
                env_file=env_file,
                transport=transport,
            )
            target = service.get_container_client(container)
            seen: set[str] = set()
            for item in target.list_blobs(
                name_starts_with=scoped_prefix,
                results_per_page=min(max_blobs + 1, 1000),
                logging_enable=False,
            ):
                if (
                    not isinstance(item.name, str)
                    or not item.name
                    or item.name in seen
                    or not item.name.startswith(scoped_prefix)
                    or any(part in {".", ".."} for part in item.name.split("/"))
                    or not isinstance(item.etag, str)
                    or not item.etag
                    or type(item.size) is not int
                    or item.size < 0
                ):
                    raise IntegrityError(
                        "Blob selection has invalid, duplicate or unscoped entries."
                    )
                if len(rows) == max_blobs:
                    raise InputError(
                        "Selection exceeds --max-blobs; no blobs were deleted. "
                        "Narrow --prefix or explicitly raise the limit."
                    )
                seen.add(item.name)
                rows.append(
                    {
                        "blob_name": item.name,
                        "etag": item.etag,
                        "byte_count": item.size,
                        "status": "pending" if confirm else "planned",
                    }
                )
            selection_complete = True
            if confirm:
                phase = "clear.delete"
                for row in rows:
                    name, etag = row["blob_name"], row["etag"]
                    if not isinstance(name, str) or not isinstance(etag, str):
                        raise IntegrityError("A selected Blob identity changed before deletion.")
                    try:
                        blob = target.get_blob_client(name)
                        if include_snapshots:
                            blob.delete_blob(
                                etag=etag,
                                match_condition=MatchConditions.IfNotModified,
                                delete_snapshots="include",
                                logging_enable=False,
                            )
                        else:
                            blob.delete_blob(
                                etag=etag,
                                match_condition=MatchConditions.IfNotModified,
                                logging_enable=False,
                            )
                    except ResourceNotFoundError as error:
                        if getattr(error, "error_code", None) == "BlobNotFound":
                            row["status"] = "already_absent"
                            continue
                        row["status"] = "failed"
                        failures.append(
                            {
                                **clear_failure(error, phase),
                                "blob_name": name,
                                "remote_delete_may_have_occurred": True,
                            }
                        )
                        break
                    except AzureError as error:
                        row["status"] = "failed"
                        failures.append(
                            {
                                **clear_failure(error, phase),
                                "blob_name": name,
                                "remote_delete_may_have_occurred": True,
                            }
                        )
                        break
                    except KeyboardInterrupt:
                        row["status"] = "unknown"
                        raise
                    row["status"] = "deleted"
                if not failures:
                    phase = "clear.verify"
                    remaining = next(
                        iter(
                            target.list_blobs(
                                name_starts_with=scoped_prefix,
                                results_per_page=1,
                                logging_enable=False,
                            )
                        ),
                        None,
                    )
                    if remaining is None:
                        verification = "empty"
                    else:
                        if not isinstance(remaining.name, str) or not remaining.name.startswith(
                            scoped_prefix,
                        ):
                            raise IntegrityError(
                                "Post-clear verification returned an unscoped Blob."
                            )
                        remaining_blob = remaining.name
                        verification = "not_empty"
                        failures.append(
                            {
                                "code": "clear_scope_not_empty",
                                "phase": phase,
                                "retryable": False,
                                "message": (
                                    "Blobs remain in scope, possibly from new writes. "
                                    "They were not added to the deletion selection."
                                ),
                            }
                        )
    except AzureError as error:
        if phase == "clear.verify":
            verification = "failed"
        failures.append(
            {
                **clear_failure(error, phase),
                "remote_delete_may_have_occurred": phase != "clear.select",
            }
        )
    except IntegrityError as error:
        if phase == "clear.select":
            raise
        if phase == "clear.verify":
            verification = "failed"
        failures.append(
            {
                "code": "clear_integrity",
                "phase": phase,
                "retryable": False,
                "message": str(error),
                "remote_delete_may_have_occurred": True,
            }
        )
    except KeyboardInterrupt:
        cancelled = True
        if phase == "clear.verify":
            verification = "failed"
        failures.append(
            {
                "code": "cancelled",
                "phase": phase,
                "retryable": True,
                "message": "Clear cancelled; completed deletions were retained.",
                "remote_delete_may_have_occurred": phase != "clear.select",
            }
        )
    result = base_result(
        "clear",
        "cancelled"
        if cancelled
        else "incomplete"
        if failures
        else "complete"
        if confirm
        else "planned",
    )
    result.update(
        requested_count=len(rows) if selection_complete else None,
        failures=failures,
        details={
            "container": container,
            "prefix": prefix,
            "effective_prefix": scoped_prefix,
            "endpoint": endpoint,
            "credential_source": credential_source,
            "auth_mode": "entra" if account_url is not None else "connection_string",
            "dry_run": not confirm,
            "include_snapshots": include_snapshots,
            "max_blobs": max_blobs,
            "selection_complete": selection_complete,
            "matched_count": len(rows),
            "deleted_count": sum(row["status"] == "deleted" for row in rows),
            "already_absent_count": sum(row["status"] == "already_absent" for row in rows),
            "failed_count": sum(row["status"] == "failed" for row in rows),
            "pending_count": sum(row["status"] == "pending" for row in rows),
            "unknown_count": sum(row["status"] == "unknown" for row in rows),
            "verification": verification,
            "remaining_blob": remaining_blob,
            "files": [dict(row) for row in rows],
            "retention_note": (
                "Only current selected blobs are deleted. Versions, soft-deleted data and "
                "retention/immutability policies are not purged or bypassed."
            ),
        },
    )
    return result
