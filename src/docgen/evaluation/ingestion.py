import time
from functools import partial

from pydantic import JsonValue

from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.azure import Azure, object_value
from docgen.evaluation.corpus import source_run, sources
from docgen.evaluation.models import ARMS, Arm, Document, Reference
from docgen.evaluation.reference import released_reference
from docgen.evaluation.resources import contains, definitions
from docgen.evaluation.state import Workspace, digest, require_live
from docgen.persistence import safe_child


def resource_path(workspace: Workspace, arm: Arm, kind: str) -> str:
    value = definitions(workspace.protocol, arm)[kind]["name"]
    if not isinstance(value, str):
        raise IntegrityError("Resource name is not a string.")
    return kind + "/" + value


def inspect_resource(
    workspace: Workspace,
    azure: Azure,
    arm: Arm,
    kind: str,
) -> dict[str, JsonValue] | None:
    result = workspace.invoke(
        "admin",
        f"inspect:{arm}:{kind}",
        partial(
            azure.search,
            "GET",
            resource_path(workspace, arm, kind),
            preview=kind == "skillsets",
            allow_missing=True,
        ),
    )
    return None if result.data is None else object_value(result.data)


def _resource_version(
    workspace: Workspace, arm: Arm, kind: str,
) -> dict[str, JsonValue] | None:
    initial = workspace.get(f"resource:{arm}:{kind}")
    terminal = workspace.get("ingested-resources:" + arm)
    if initial is None:
        if terminal is not None:
            raise IntegrityError("Post-ingestion resource versions lack creation ownership.")
        return None
    if terminal is None:
        value: JsonValue = initial
    elif isinstance(terminal, dict) and kind in terminal:
        value = terminal[kind]
    else:
        raise IntegrityError("Post-ingestion resource versions are incomplete.")
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("@odata.etag"), str)
        or not value["@odata.etag"]
    ):
        raise IntegrityError("Owned Azure resource version is invalid.")
    return value


def _resource_matches(
    workspace: Workspace,
    arm: Arm,
    kind: str,
    actual: dict[str, JsonValue] | None,
) -> bool:
    saved = _resource_version(workspace, arm, kind)
    if saved is None or actual is None:
        return False
    if actual == saved:
        return True
    return (
        kind in {"datasources", "indexers"}
        and workspace.get("ingested-resources:" + arm) is None
        and workspace.get("snapshot:" + arm) is None
        and isinstance(actual.get("@odata.etag"), str)
        and bool(actual["@odata.etag"])
        and {key: value for key, value in actual.items() if key != "@odata.etag"}
        == {key: value for key, value in saved.items() if key != "@odata.etag"}
    )


def ensure_resource(workspace: Workspace, azure: Azure, arm: Arm, kind: str) -> None:
    definition = definitions(workspace.protocol, arm)[kind]
    key = f"resource:{arm}:{kind}"
    saved = _resource_version(workspace, arm, kind)
    actual = inspect_resource(workspace, azure, arm, kind)
    if saved is not None:
        if not _resource_matches(workspace, arm, kind, actual):
            raise IntegrityError("A protocol-owned Azure resource was removed or changed.")
        return
    intent = workspace.get("create:" + key)
    if actual is not None and intent is None:
        raise IntegrityError("Refusing to adopt a pre-existing, unowned Search resource.")
    workspace.put("create:" + key, definition)
    if actual is None:
        workspace.invoke(
            "admin",
            f"create:{arm}:{kind}",
            partial(
                azure.search,
                "PUT",
                resource_path(workspace, arm, kind),
                body=definition,
                preview=kind == "skillsets",
                create_only=True,
            ),
        )
        actual = inspect_resource(workspace, azure, arm, kind)
    expected = dict(definition)
    if kind == "datasources" and actual is not None:
        credentials = actual.get("credentials")
        if isinstance(credentials, dict) and credentials.get("connectionString") is None:
            expected["credentials"] = {"connectionString": None}
    if actual is None or not contains(actual, expected) or not actual.get("@odata.etag"):
        raise IntegrityError("Azure resource readback differs or has no auditable version.")
    workspace.put(key, actual)


def resources(workspace: Workspace, azure: Azure, arm: Arm) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for kind in ("datasources", "indexes", "skillsets", "indexers"):
        if _resource_version(workspace, arm, kind) is None:
            raise InputError("Prepare and ingest both protocol-owned arms before snapshotting.")
    seal_terminal = (
        workspace.get("ingested-resources:" + arm) is None
        and workspace.get("snapshot:" + arm) is None
    )
    if seal_terminal:
        indexer_status(workspace, azure, arm)
    for kind in ("datasources", "indexes", "skillsets", "indexers"):
        actual = inspect_resource(workspace, azure, arm, kind)
        if not _resource_matches(workspace, arm, kind, actual):
            raise IntegrityError("Azure resource drift invalidates this experiment.")
        result[kind] = actual
    if seal_terminal:
        workspace.put("ingested-resources:" + arm, result)
    return result


def blob_name(workspace: Workspace, document: Document) -> str:
    return workspace.protocol.source_prefix + "/" + document.filename


def source_uri(workspace: Workspace, document: Document) -> str:
    settings = workspace.protocol.config.storage
    return settings.account_url + "/" + settings.container + "/" + blob_name(workspace, document)


def blob_inventory(
    workspace: Workspace,
    azure: Azure,
    *,
    documents: tuple[Document, ...] | None = None,
) -> list[JsonValue]:
    if documents is None:
        documents, _ = sources(workspace)
    expected = {blob_name(workspace, document): document for document in documents}
    observed: dict[str, JsonValue] = {}
    marker = None
    seen: set[str] = set()
    while True:
        page = object_value(
            workspace.invoke(
                "blob",
                "inventory",
                partial(azure.list_blobs, marker),
            ).data
        )
        values = page.get("values")
        if not isinstance(values, list):
            raise ProviderError("invalid_blob_inventory", "Blob listing is incomplete.")
        for raw in values:
            item = object_value(raw)
            name = item.get("name")
            if not isinstance(name, str) or name in observed or name not in expected:
                raise IntegrityError("Blob inventory contains duplicate or foreign sources.")
            if item.get("size") != expected[name].byte_count:
                raise IntegrityError("Blob source size differs from the frozen source manifest.")
            version = item.get("etag")
            verified = workspace.get("blob:" + expected[name].id)
            if (
                not isinstance(version, str)
                or not version
                or not isinstance(verified, dict)
                or not isinstance(verified.get("etag"), str)
                or version.strip('"') != str(verified["etag"]).strip('"')
            ):
                raise IntegrityError("Blob inventory differs from the verified source version.")
            observed[name] = item
        token = page.get("next")
        if token is None:
            break
        if not isinstance(token, str) or not token or token in seen:
            raise IntegrityError("Blob pagination failed to advance.")
        seen.add(token)
        marker = token
    if set(observed) != set(expected):
        raise IntegrityError("The protocol-owned Blob prefix is incomplete.")
    return [observed[name] for name in sorted(observed)]


def uploaded_blobs(workspace: Workspace, reference: Reference) -> list[JsonValue]:
    saved = workspace.get("blobs")
    if not isinstance(saved, list) or workspace.get("blobs-verified") != {
        "inventory_hash": digest(saved),
        "source_hash": reference.source_hash,
    }:
        raise InputError("Prepare the sources to complete version-bound Blob byte verification.")
    return saved


def upload_sources(
    workspace: Workspace, azure: Azure, *,
    documents: tuple[Document, ...] | None = None, seal: bool = True,
) -> None:
    workspace.protocol.require_pipeline_only()
    reference = released_reference(workspace)
    selected = reference.documents if documents is None else documents
    if (
        not selected or len({document.id for document in selected}) != len(selected)
        or any(document not in reference.documents for document in selected)
        or seal and selected != reference.documents
    ):
        raise InputError(
            "Upload selection must be a nonempty frozen subset; seals require all sources."
        )
    corpus = safe_child(source_run(workspace), "corpus")
    for document in selected:
        name = blob_name(workspace, document)
        intent: dict[str, JsonValue] = {
            "protocol_id": workspace.protocol.id,
            "sha256": document.artifact_hash,
            "byte_count": document.byte_count,
        }
        properties = workspace.invoke(
            "blob",
            "properties:" + document.id,
            partial(azure.blob_properties, name),
        ).data
        if properties is not None and workspace.get("upload-intent:" + document.id) != intent:
            raise IntegrityError("Refusing to adopt an unowned raw source Blob.")
        if properties is None:
            workspace.put("upload-intent:" + document.id, intent)
            try:
                workspace.invoke(
                    "blob",
                    "upload:" + document.id,
                    partial(azure.upload, document, safe_child(corpus, document.filename)),
                )
            except IntegrityError:
                workspace.put("invalidated", {"reason": "source_changed_during_upload"})
                raise
            properties = workspace.invoke(
                "blob",
                "verify:" + document.id,
                partial(azure.blob_properties, name),
            ).data
        item = object_value(properties)
        version = item.get("etag")
        if (
            item.get("size") != document.byte_count
            or item.get("metadata") != {}
            or not isinstance(version, str)
            or not version
        ):
            raise IntegrityError("Refusing to overwrite or adopt a foreign/mismatched source blob.")
        previous = workspace.get("blob:" + document.id)
        if previous is not None and previous != item:
            raise IntegrityError("A previously verified source Blob version changed.")
        verification: dict[str, JsonValue] = {
            "etag": version,
            "sha256": document.artifact_hash,
            "byte_count": document.byte_count,
        }
        saved_verification = workspace.get("blob-bytes:" + document.id)
        if saved_verification is None:
            workspace.invoke(
                "blob",
                "verify-bytes:" + document.id + ":" + digest(version),
                partial(azure.verify_blob, document, version),
                fingerprint=digest(verification),
            )
            workspace.put("blob-bytes:" + document.id, verification)
        elif saved_verification != verification:
            raise IntegrityError("Source Blob byte verification belongs to another version.")
        workspace.put("blob:" + document.id, item)
    if not seal:
        return
    inventory = blob_inventory(workspace, azure, documents=reference.documents)
    workspace.put("blobs", inventory)
    workspace.put(
        "blobs-verified",
        {
            "inventory_hash": digest(inventory),
            "source_hash": reference.source_hash,
        },
    )


def prepare(
    workspace: Workspace, azure: Azure, *, live: bool, arms: tuple[Arm, ...] = ARMS,
) -> None:
    require_live(live)
    workspace.require_valid()
    workspace.protocol.require_pipeline_only()
    if not arms or len(set(arms)) != len(arms) or any(arm not in ARMS for arm in arms):
        raise InputError("Preparation requires an explicit unique set of supported arms.")
    upload_sources(workspace, azure)
    for arm in arms:
        for kind in ("datasources", "indexes", "skillsets"):
            ensure_resource(workspace, azure, arm, kind)


def indexer_status(workspace: Workspace, azure: Azure, arm: Arm) -> dict[str, JsonValue]:
    name = workspace.protocol.resource_name(arm, "indexer")
    response = workspace.invoke(
        "admin",
        "status:" + arm,
        partial(azure.search, "GET", f"indexers('{name}')/search.status"),
    )
    status = object_value(response.data)
    if status.get("status") != "running":
        raise ProviderError("indexer_unhealthy", "Indexer service state is unknown or in error.")
    last = status.get("lastResult")
    if last is None:
        raise ProviderError("ingestion_pending", "Indexer has not started yet.", retryable=True)
    result = object_value(last)
    if result.get("status") == "inProgress":
        raise ProviderError("ingestion_pending", "Indexer is still running.", retryable=True)
    if result.get("status") != "success" or not result.get("endTime") or result.get("errorMessage"):
        raise ProviderError(
            "ingestion_failed",
            "Indexer did not finish successfully; resolve operational errors.",
        )
    generation = workspace.protocol.generation_config.generation
    if generation is None:
        raise IntegrityError("Fresh generation configuration is missing.")
    if (
        type(result.get("itemsProcessed")) is not int
        or result["itemsProcessed"] != generation.count
    ):
        raise IntegrityError("Indexer did not attempt every source exactly once.")
    failed, errors, warnings = (
        result.get("itemsFailed"),
        result.get("errors"),
        result.get("warnings"),
    )
    if (
        type(failed) is not int
        or failed < 0
        or not isinstance(errors, list)
        or not isinstance(
            warnings,
            list,
        )
    ):
        raise ProviderError("invalid_indexer_status", "Indexer accounting is incomplete.")
    for raw in errors:
        item = object_value(raw)
        code = item.get("statusCode")
        error_name = item.get("name")
        if (
            type(code) is not int
            or code in {401, 403, 408, 409, 422, 429}
            or code >= 500
            or isinstance(error_name, str)
            and "embedding" in error_name.casefold()
        ):
            raise ProviderError(
                "ingestion_operational_error",
                "Authentication, configuration or embedding failures invalidate comparison.",
            )
    return result


def ingest(
    workspace: Workspace,
    azure: Azure,
    *,
    live: bool,
    wait_seconds: int = 0,
    arms: tuple[Arm, ...] = ARMS,
) -> dict[str, JsonValue]:
    require_live(live)
    workspace.require_valid()
    workspace.protocol.require_pipeline_only()
    if not 0 <= wait_seconds <= 3600:
        raise InputError("Indexer wait must be between zero and 3600 seconds.")
    if not arms or len(set(arms)) != len(arms) or any(arm not in ARMS for arm in arms):
        raise InputError("Ingestion requires an explicit unique set of supported arms.")
    reference = released_reference(workspace)
    expected_blobs = uploaded_blobs(workspace, reference)
    if blob_inventory(workspace, azure, documents=reference.documents) != expected_blobs:
        raise IntegrityError("Source blobs changed before ingestion.")
    sequential = (
        workspace.protocol.entity_extraction is not None
        and workspace.protocol.entity_extraction.version in {"2", "3"}
        and len(arms) == 2
    )
    if sequential:
        arms = ARMS
    for arm in arms:
        for kind in ("datasources", "indexes", "skillsets"):
            actual = inspect_resource(workspace, azure, arm, kind)
            if not _resource_matches(workspace, arm, kind, actual):
                raise IntegrityError("Prepared resource drift prevents ingestion.")
        if not sequential:
            ensure_resource(workspace, azure, arm, "indexers")
    deadline = time.monotonic() + wait_seconds
    while True:
        statuses: dict[str, JsonValue] = {}
        pending = False
        for arm in arms:
            if sequential:
                if arm == "content_understanding":
                    first = object_value(statuses["de_split"])
                    if first.get("status") != "success":
                        pending = True
                        statuses[arm] = {"status": "notStarted"}
                        continue
                    if first.get("itemsFailed") or first.get("errors") or first.get("warnings"):
                        raise ProviderError(
                            "entity_ingestion",
                            "The first entity arm has diagnostics; do not start the other arm.",
                        )
                ensure_resource(workspace, azure, arm, "indexers")
            try:
                statuses[arm] = indexer_status(workspace, azure, arm)
            except ProviderError as error:
                if error.code != "ingestion_pending":
                    raise
                pending = True
                statuses[arm] = {"status": "inProgress"}
        if not pending:
            for arm in arms:
                resources(workspace, azure, arm)
        if not pending or time.monotonic() >= deadline:
            return statuses
        time.sleep(min(5, max(0, deadline - time.monotonic())))
