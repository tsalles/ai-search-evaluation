import shutil
from pathlib import Path

from pydantic import JsonValue

from docgen.errors import InputError, IntegrityError
from docgen.evaluation.azure import object_value, vector_value
from docgen.evaluation.corpus import source_run, sources
from docgen.evaluation.models import ExperimentConfig
from docgen.evaluation.reference import (
    build_reference,
    provisional_policy,
    release_reference,
    released_reference,
    validate_reference,
)
from docgen.evaluation.state import RemoteValue, Workspace, digest, new_protocol
from docgen.store import RunStore


def inherit_query_vectors(source: Workspace, target: Workspace) -> int:
    source.require_valid()
    target.require_valid()
    if source.path == target.path:
        raise InputError("Query-vector inheritance requires separate experiment workspaces.")
    original, destination = source.protocol.config.search, target.protocol.config.search
    if (
        original.embedding != destination.embedding
        or original.model_name != destination.model_name
        or original.dimensions != destination.dimensions
    ):
        raise InputError("Query-vector inheritance requires the identical embedding space.")
    inherited = 0
    for (name,) in source.database.execute(
        "SELECT name FROM records WHERE name LIKE 'remote:vector:%' ORDER BY name"
    ):
        cached = object_value(source.get(name))
        fingerprint = cached.get("fingerprint")
        value = RemoteValue.model_validate(cached.get("result"))
        response = object_value(value.data)
        request_key = name.removeprefix("remote:")
        request = source.get("request:" + request_key)
        if (
            not isinstance(fingerprint, str)
            or fingerprint != name.removeprefix("remote:vector:")
            or request != {"kind": "embedding", "fingerprint": fingerprint}
            or response.get("reported_model") != destination.model_name
            or value.tokens is None
        ):
            raise IntegrityError("Inherited query embedding cache is not fully validated.")
        vector_value(response.get("vector"), destination.dimensions)
        target.put("request:" + request_key, request)
        target.put(name, cached)
        inherited += 1
    return inherited


def fork_experiment(source: Workspace, config: ExperimentConfig, output: Path) -> Path:
    source.require_valid()
    if config.search.variant is None:
        raise InputError("A fork requires explicit search.variant settings.")
    if source.path == output.absolute() or source.path in output.absolute().parents:
        raise InputError("Place variant workspaces outside the source experiment directory.")
    original_config = source.protocol.config
    expected = original_config.model_dump(mode="json", exclude={"search", "limits"})
    observed = config.model_dump(mode="json", exclude={"search", "limits"})
    if expected != observed or (
        original_config.search.model_dump(mode="json", exclude={"variant"})
        != config.search.model_dump(mode="json", exclude={"variant"})
    ):
        raise InputError(
            "Variants may change only explicit ingestion settings and operational limits; "
            "source generation, splits, storage and embedding space must remain identical."
        )
    reference = released_reference(source)
    original_documents, _ = sources(source)
    proposal = new_protocol(config)
    if proposal.generation_config != source.protocol.generation_config:
        raise IntegrityError("The derived variant changed the frozen source-generation contract.")
    protocol = proposal.model_copy(update={"source_run_id": source.protocol.source_run_id})
    with Workspace.create(output, protocol) as target:
        target.put("source-fork-origin", {
            "protocol": source.protocol.id,
            "path": str(source.path),
            "reference_hash": digest(reference),
            "source_hash": reference.source_hash,
            "authoring_forbidden": True,
        })
        origin = source_run(source)
        if any(path.is_symlink() or path.is_junction() for path in origin.rglob("*")):
            raise IntegrityError("A source run containing filesystem links cannot be forked.")
        with RunStore.open(origin):
            shutil.copytree(origin, source_run(target))
        copied_documents, _ = sources(target)
        if copied_documents != original_documents:
            raise IntegrityError("Copied native or canonical source hashes differ.")
        baseline = build_reference(target)
        if (baseline.documents, baseline.claims, baseline.evidence) != (
            reference.documents, reference.claims, reference.evidence,
        ):
            raise IntegrityError("Source-derived reference evidence changed in the variant.")
        draft = reference.model_copy(update={"protocol_id": protocol.id, "status": "draft"})
        validate_reference(target, draft, release=False)
        target.replace_draft("reference-draft.json", draft.model_dump_json(indent=2).encode())
        if reference.status == "provisional":
            policy = provisional_policy(source, reference)
            released = release_reference(
                target, provisional=policy == "automated_smoke",
                provisional_pilot=policy == "automated_pilot",
                provisional_study=policy == "automated_study",
            )
        else:
            for intent in reference.intents:
                for review in intent.reviews:
                    key = f"review:{intent.id}:{digest(review)}"
                    event = source.get(key)
                    if event != review.model_dump(mode="json"):
                        raise IntegrityError("An inherited human review lacks its original event.")
                    target.put(key, event)
            released = release_reference(target)
        if (
            released.intents != reference.intents
            or released.source_hash != reference.source_hash
            or (target.path / "qrels.trec").read_bytes()
            != (source.path / "qrels.trec").read_bytes()
        ):
            raise IntegrityError("Variant qrels or query intent semantics differ.")
        inherited = inherit_query_vectors(source, target)
        lineage: dict[str, JsonValue] = {
            "origin_protocol": source.protocol.id,
            "origin_path": str(source.path),
            "origin_reference_hash": digest(reference),
            "source_hash": reference.source_hash,
            "same_fresh_source_run": source.protocol.source_run_id,
            "new_authoring_calls": 0,
            "native_and_canonical_sources_unchanged": True,
            "qrels_and_queries_unchanged": True,
            "new_independent_corpus_or_replication": False,
            "inherited_query_embedding_cache_entries": inherited,
            "inherited_embedding_usage_billed_in_origin_not_again_here": True,
            "human_review_certified": reference.status == "released",
            "variant": config.search.variant.model_dump(mode="json"),
            "enrichment_policy": protocol.enrichment_policy,
            "external_document_metadata": False,
        }
        target.put("source-lineage", lineage)
        target.export("source-lineage.json", lineage)
        target.export("experiment-plan.json", {
            "experiment_id": protocol.id,
            "experiment_path": str(target.path),
            "document_count": len(copied_documents),
            "source_lineage": lineage,
            "limits": config.limits.model_dump(mode="json"),
            "arms": {
                arm: {"index": protocol.resource_name(arm, "index")}
                for arm in ("de_split", "content_understanding")
            },
        })
        return target.path
