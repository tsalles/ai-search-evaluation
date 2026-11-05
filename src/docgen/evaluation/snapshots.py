from collections.abc import Iterator
from functools import partial

from pydantic import JsonValue, ValidationError

from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.azure import Azure, object_value, vector_value
from docgen.evaluation.entities import checked_entities, checked_entity_data
from docgen.evaluation.ingestion import (
    blob_inventory,
    indexer_status,
    resources,
    source_uri,
    uploaded_blobs,
)
from docgen.evaluation.models import (
    Arm,
    Chunk,
    IngestionAudit,
    Reference,
    SectionMetadata,
    Snapshot,
    SourceContext,
)
from docgen.evaluation.reference import released_reference
from docgen.evaluation.sectioning import checked_section_row
from docgen.evaluation.state import Workspace, digest, require_live
from docgen.persistence import safe_child


def index_rows(
    workspace: Workspace,
    azure: Azure,
    arm: Arm,
    *,
    select: str,
) -> Iterator[dict[str, JsonValue]]:
    index = workspace.protocol.resource_name(arm, "index")
    seen: set[str] = set()
    last = None
    while True:
        body: dict[str, JsonValue] = {
            "search": "*",
            "top": 250,
            "orderby": "id asc",
            "select": select,
            "minimumCoverage": 100,
        }
        if last is not None:
            body["filter"] = "id gt '" + last.replace("'", "''") + "'"
        response = workspace.invoke(
            "search",
            "scan:" + arm,
            partial(azure.search, "POST", f"indexes/{index}/docs/search", body=body),
        )
        page = object_value(response.data)
        values = page.get("value")
        if not isinstance(values, list) or page.get("@search.coverage") != 100:
            raise ProviderError("invalid_scan", "Search snapshot page is missing its documents.")
        if not values:
            break
        for raw in values:
            item = object_value(raw)
            identifier = item.get("id")
            if (
                not isinstance(identifier, str)
                or not identifier
                or identifier in seen
                or last is not None
                and identifier <= last
            ):
                raise IntegrityError("Snapshot has invalid chunk identities or ordering.")
            seen.add(identifier)
            last = identifier
            if len(seen) > workspace.protocol.config.limits.max_chunks:
                raise InputError("The frozen maximum snapshot chunk budget was exceeded.")
            yield item


def scan_chunks(
    workspace: Workspace,
    azure: Azure,
    arm: Arm,
    *,
    reference: Reference | None = None,
) -> tuple[Chunk, ...]:
    if reference is None:
        reference = released_reference(workspace)
    identities = {source_uri(workspace, document): document.id for document in reference.documents}
    contexts: dict[str, SourceContext] = {}
    select = "id,parent_id,content_path,content,embedding"
    variant = workspace.protocol.config.search.variant
    sectioning = (
        variant is not None and variant.section_enrichment is not None and arm == "de_split"
    )
    section_parts: dict[str, dict[int, SectionMetadata]] = {}
    source_signatures: dict[str, tuple[str, str | None, str, str, int, int]] = {}
    if sectioning:
        select += ",section_metadata,source_text"
    compare_analyzers = (
        variant is not None and variant.index_tuning is not None
        and variant.index_tuning.analyzer_comparison_fields
    )
    if compare_analyzers:
        select += ",content_lucene,content_standard"
    if workspace.protocol.entity_extraction is not None:
        select += ",entity_data"
    if workspace.protocol.source_context_enabled:
        from docgen.evaluation.context import source_contexts

        if workspace.get("snapshot:" + arm) is None:
            contexts = source_contexts(workspace)
        else:
            saved = snapshot(workspace, arm, reference=reference)
            for chunk in saved.chunks:
                context = chunk.source_context
                if context is None or (
                    chunk.doc_id in contexts and contexts[chunk.doc_id] != context
                ):
                    raise IntegrityError(
                        "Sealed variant source context is missing or inconsistent."
                    )
                contexts[chunk.doc_id] = context
        select += ",title,account_names,source_context_hash"
    chunks: list[Chunk] = []
    parents: dict[str, str] = {}
    source_parents: dict[str, str] = {}
    for item in index_rows(workspace, azure, arm, select=select):
        identifier, parent = item.get("id"), item.get("parent_id")
        uri, content = item.get("content_path"), item.get("content")
        if (
            not isinstance(identifier, str)
            or not isinstance(parent, str)
            or not parent
            or not isinstance(uri, str)
            or uri not in identities
            or not isinstance(content, str)
            or not content.strip()
        ):
            raise IntegrityError("Snapshot has foreign/unmapped parents or invalid chunks.")
        if compare_analyzers and any(
            item.get(field) != content for field in ("content_lucene", "content_standard")
        ):
            raise IntegrityError("Analyzer comparison fields differ from native chunk text.")
        doc_id = identities[uri]
        section_metadata = None
        if sectioning:
            try:
                section_metadata = SectionMetadata.model_validate(checked_section_row(item))
            except ValidationError as exc:
                raise IntegrityError(
                    "Indexed section metadata is not a valid structured record."
                ) from exc
            native_source = item.get("source_text")
            if not isinstance(native_source, str):
                raise IntegrityError("Indexed section source is missing.")
            signature = (
                section_metadata.source_sha256, section_metadata.title, section_metadata.model,
                section_metadata.request_key, section_metadata.section_count, len(native_source),
            )
            if source_signatures.setdefault(doc_id, signature) != signature:
                raise IntegrityError("A document has conflicting section source/model metadata.")
            parts = section_parts.setdefault(doc_id, {})
            if parts.setdefault(section_metadata.ordinal, section_metadata) != section_metadata:
                raise IntegrityError("An indexed section maps to conflicting original-text spans.")
        if parents.get(parent, doc_id) != doc_id or source_parents.get(doc_id, parent) != parent:
            raise IntegrityError("A Search parent maps to conflicting source identities.")
        parents[parent], source_parents[doc_id] = doc_id, parent
        try:
            vector = vector_value(
                item.get("embedding"), workspace.protocol.config.search.dimensions,
            )
        except ProviderError:
            raise IntegrityError(
                "Snapshot has a missing or invalid vector; index drift is possible."
            ) from None
        context = contexts.get(doc_id)
        if context is not None and (
            item.get("title") != context.title
            or item.get("account_names") != list(context.account_names)
            or item.get("source_context_hash") != digest(context)
        ):
            raise IntegrityError("Indexed source context differs from visible source metadata.")
        chunks.append(
            Chunk(
                id=identifier, parent_id=parent, doc_id=doc_id, content=content,
                text_hash=digest(content), vector_hash=digest([number for number in vector]),
                source_context=context,
                entities=checked_entity_data(
                    item.get("entity_data"), content,
                    version=workspace.protocol.entity_extraction.version,
                )
                if workspace.protocol.entity_extraction is not None else None,
                section_metadata=section_metadata,
            )
        )
    for doc_id, parts in section_parts.items():
        count, length = source_signatures[doc_id][-2:]
        if set(parts) != set(range(count)):
            raise IntegrityError("Indexed sections do not cover every declared source section.")
        cursor = 0
        for ordinal in range(count):
            part = parts[ordinal]
            if part.source_start != cursor or part.source_end <= cursor:
                raise IntegrityError("Indexed sections have a gap, overlap or reordered source.")
            cursor = part.source_end
        if cursor != length:
            raise IntegrityError("Indexed sections omit the original source suffix.")
    return tuple(chunks)


def take_snapshot(
    workspace: Workspace,
    azure: Azure,
    arm: Arm,
    *,
    live: bool,
    audit: IngestionAudit | None = None,
) -> Snapshot:
    require_live(live)
    workspace.require_valid()
    reference = released_reference(workspace)
    actual_resources = resources(workspace, azure, arm)
    inventory = blob_inventory(workspace, azure, documents=reference.documents)
    if inventory != uploaded_blobs(workspace, reference):
        raise IntegrityError("Source Blob inventory changed.")
    execution = indexer_status(workspace, azure, arm)
    chunks = scan_chunks(workspace, azure, arm, reference=reference)
    missing = {document.id for document in reference.documents} - {chunk.doc_id for chunk in chunks}
    needs_review = bool(
        missing or execution["errors"] or execution["warnings"] or execution["itemsFailed"]
    )
    execution_hash = digest(execution)
    workspace.put("execution:" + arm, execution)
    workspace.export(f"ingestion-{arm}.json", execution)
    if needs_review:
        draft: dict[str, JsonValue] = {
            "arm": arm,
            "execution_hash": execution_hash,
            "reviewer": "",
            "source_failures_only": False,
            "missing": [
                {"doc_id": doc_id, "reviewer": "", "reason": ""} for doc_id in sorted(missing)
            ],
        }
        path = safe_child(workspace.path, f"ingestion-audit-{arm}-draft.json")
        if not path.exists():
            from docgen.evaluation.state import json_bytes

            workspace.replace_draft(path.name, json_bytes(draft))
        if (
            audit is None
            or audit.arm != arm
            or audit.execution_hash != execution_hash
            or {item.doc_id for item in audit.missing} != missing
            or len(audit.missing) != len(missing)
        ):
            raise InputError(
                "Missing sources or indexer diagnostics need a source-loss-only human audit; "
                "review the exported ingestion status and audit draft before snapshotting."
            )
        workspace.record("ingestion-audit:" + arm, audit)
    elif audit is not None:
        raise InputError("An ingestion audit was supplied for an execution without source losses.")
    snapshot = Snapshot(
        protocol_id=workspace.protocol.id,
        arm=arm,
        source_hash=reference.source_hash,
        resource_hash=digest(actual_resources),
        reference_hash=digest(reference),
        execution_hash=execution_hash,
        blob_hash=digest(inventory),
        chunks=chunks,
        missing=audit.missing if audit is not None else (),
        indexer_errors=len(execution["errors"]) if isinstance(execution["errors"], list) else 0,
        indexer_warnings=len(execution["warnings"])
        if isinstance(execution["warnings"], list)
        else 0,
    )
    if resources(workspace, azure, arm) != actual_resources or (
        blob_inventory(workspace, azure, documents=reference.documents) != inventory
        or digest(indexer_status(workspace, azure, arm)) != execution_hash
    ):
        raise IntegrityError(
            "Sources or Azure settings changed while the snapshot was being frozen."
        )
    workspace.record("snapshot:" + arm, snapshot)
    workspace.export(f"snapshot-{arm}.json", snapshot)
    return snapshot


def snapshot(
    workspace: Workspace,
    arm: Arm,
    *,
    reference: Reference | None = None,
) -> Snapshot:
    value = workspace.get("snapshot:" + arm)
    if value is None:
        raise InputError("Both arm snapshots are required before collection or scoring.")
    result = Snapshot.model_validate(value)
    if workspace.protocol.pipeline_only and any(
        chunk.source_context is not None for chunk in result.chunks
    ):
        raise IntegrityError("A pipeline-only snapshot contains external source context.")
    for chunk in result.chunks:
        if workspace.protocol.entity_extraction is not None:
            if chunk.entities is None:
                raise IntegrityError("A pipeline entity snapshot is missing extracted entities.")
            checked_entities(
                list(chunk.entities), chunk.content,
                version=workspace.protocol.entity_extraction.version,
            )
        elif chunk.entities is not None:
            raise IntegrityError("A snapshot contains an unconfigured entity treatment.")
    if reference is None:
        reference = released_reference(workspace)
    if (
        result.protocol_id != workspace.protocol.id
        or result.arm != arm
        or result.reference_hash != digest(reference)
        or result.source_hash != reference.source_hash
        or result.blob_hash != digest(uploaded_blobs(workspace, reference))
    ):
        raise IntegrityError("Snapshot lineage differs from this reference/source release.")
    execution = workspace.get("execution:" + arm)
    if execution is None or digest(execution) != result.execution_hash:
        raise IntegrityError("Snapshot execution audit is missing or differs.")
    workspace.export(f"ingestion-{arm}.json", execution)
    workspace.export(f"snapshot-{arm}.json", result)
    return result


def assert_stable(
    workspace: Workspace,
    azure: Azure,
    arm: Arm,
    *,
    reference: Reference | None = None,
) -> None:
    if reference is None:
        reference = released_reference(workspace)
    saved = snapshot(workspace, arm, reference=reference)
    try:
        changed = (
            saved.resource_hash != digest(resources(workspace, azure, arm))
            or saved.blob_hash
            != digest(blob_inventory(workspace, azure, documents=reference.documents))
            or saved.execution_hash != digest(indexer_status(workspace, azure, arm))
            or saved.chunks != scan_chunks(workspace, azure, arm, reference=reference)
        )
    except IntegrityError:
        workspace.put("invalidated", {"reason": "snapshot_drift"})
        raise
    if changed:
        workspace.put("invalidated", {"reason": "snapshot_drift"})
        raise IntegrityError("Index/source drift invalidates paired retrieval collection.")
