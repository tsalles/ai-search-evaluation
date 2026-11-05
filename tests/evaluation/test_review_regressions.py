from datetime import date

import pytest

from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.corpus import generate_sources, source_run
from docgen.evaluation.ingestion import blob_name, prepare
from docgen.evaluation.reference import released_reference, validate_reference
from docgen.evaluation.runner import collect, query_vector
from docgen.evaluation.snapshots import assert_stable, snapshot
from docgen.evaluation.state import new_protocol
from docgen.models import Block
from docgen.planning import create_plan
from docgen.quality import Acceptance
from docgen.store import RunStore
from tests.evaluation.fixtures import FamilyProvider, experiment_config, fresh_workspace
from tests.evaluation.test_azure import azure_fixture
from tests.evaluation.test_reference_guards import replace_intent
from tests.evaluation.test_runner import prepare_snapshots


@pytest.mark.parametrize("scope", ["sibling-prefix", "foreign-family"])
def test_query_cannot_silently_change_its_declared_entity_scope(staged_workspace, scope):
    reference = released_reference(staged_workspace)
    intent = reference.intents[0]
    target = intent.entities[0]
    if scope == "sibling-prefix":
        sibling = next(
            claim.fact.entity
            for claim in reference.claims
            if claim.family_id == intent.family_id and claim.fact.entity != target
        )
        text = f"Qual e a mensalidade da {sibling}?"
    else:
        foreign = next(
            claim.fact.entity for claim in reference.claims if claim.family_id != intent.family_id
        )
        text = f"Compare a mensalidade da {target} com a da {foreign}."
    changed = intent.model_copy(
        update={
            "queries": (
                intent.queries[0].model_copy(update={"text": text}),
                *intent.queries[1:],
            )
        }
    )
    with pytest.raises(InputError, match="scope"):
        validate_reference(staged_workspace, replace_intent(reference, changed), release=False)


def test_frozen_family_facts_cannot_gain_unplanned_validity_intervals():
    protocol = new_protocol(experiment_config())
    generation = protocol.generation_config.generation
    blueprint = create_plan(
        protocol.generation_config,
        run_id=protocol.source_run_id,
    ).blueprints[0]
    original = FamilyProvider().generate(blueprint, generation)
    fact = original.facts[0].model_copy(
        update={
            "valid_from": date(2026, 1, 1),
            "valid_until": date(2027, 1, 1),
        }
    )
    paragraph = next(block for block in original.blocks if block.kind == "paragraph")
    replacement = paragraph.model_copy(
        update={
            "text": paragraph.text + " Vigencia entre 2026-01-01 e 2027-01-01.",
        }
    )
    changed = original.model_copy(
        update={
            "facts": (fact, *original.facts[1:]),
            "blocks": tuple(
                replacement if block.id == paragraph.id else block for block in original.blocks
            ),
        }
    )
    with pytest.raises(ValueError, match="frozen"):
        Acceptance(generation).accept(changed)


def test_storage_version_change_before_initial_freeze_is_not_adopted(staged_workspace):
    azure, backend, blobs, _ = azure_fixture(staged_workspace)

    def replace_first_uploaded_blob():
        if len(blobs.blobs) == 2:
            item = next(iter(blobs.blobs.values()))
            item["body"] = b"X" + item["body"][1:]
            item["etag"] = '"replaced-after-verification"'
            blobs.after_upload = None

    blobs.after_upload = replace_first_uploaded_blob
    with azure, pytest.raises(IntegrityError):
        prepare(staged_workspace, azure, live=True)
    assert not backend.resources


def test_owned_raw_blob_requires_actual_bytes_without_checksum_metadata(staged_workspace):
    workspace = staged_workspace
    azure, backend, blobs, _ = azure_fixture(workspace)
    document = released_reference(workspace).documents[0]
    original = (source_run(workspace) / "corpus" / document.filename).read_bytes()
    def corrupt_uploaded_bytes():
        item = blobs.blobs[blob_name(workspace, document)]
        item["body"] = b"X" + original[1:]
        item["etag"] = '"corrupted-after-owned-upload"'
        assert item["metadata"] == {}
        blobs.after_upload = None

    blobs.after_upload = corrupt_uploaded_bytes
    with azure, pytest.raises(IntegrityError, match="checksum|bytes"):
        prepare(workspace, azure, live=True)
    assert not backend.resources


def test_semantically_equal_service_defaults_pass_resource_readback(staged_workspace):
    azure, backend, _, _ = azure_fixture(staged_workspace)
    backend.normalize_resources = True
    with azure:
        prepare(staged_workspace, azure, live=True)
    assert len(backend.resources) == 6


def test_invalid_vector_drift_remains_invalid_after_vector_restoration(staged_workspace):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    with azure:
        prepare_snapshots(workspace, azure)
        backend.chunks["de_split"][0]["embedding"] = [0, 0, 0]
        with pytest.raises((IntegrityError, ProviderError)):
            assert_stable(workspace, azure, "de_split")
        backend.chunks["de_split"][0]["embedding"] = [0.1, 0.2, 0.3]
        with pytest.raises(IntegrityError, match="permanently"):
            workspace.require_valid()


def test_foreign_query_hit_permanently_invalidates_cached_collection(staged_workspace):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    with azure:
        prepare_snapshots(workspace, azure)
        backend.rankings["de_split"] = [{"id": "foreign-chunk"}]
        with pytest.raises(IntegrityError, match="unknown"):
            collect(workspace, azure, live=True, count_tokens=lambda _: 25)
        backend.rankings.clear()
        with pytest.raises(IntegrityError, match="permanently"):
            workspace.require_valid()


def test_wrong_embedding_model_is_rejected_before_success_cache(staged_workspace):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    query = released_reference(workspace).intents[0].queries[0]
    with azure:
        backend.embedding_model = "text-embedding-3-small"
        with pytest.raises(ProviderError, match="model"):
            query_vector(workspace, azure, query, count_tokens=lambda _: 25)
        backend.embedding_model = "text-embedding-3-large"
        vector = query_vector(workspace, azure, query, count_tokens=lambda _: 25)
        assert vector == [0.1, 0.2, 0.3]
        assert workspace.usage()["observed_embedding_tokens"] == 50
        assert workspace.usage()["embedding_usage_unknown"] == 0
    assert sum("/embeddings" in str(request.url) for request in backend.requests) == 2


def test_source_resume_checks_the_protocol_before_calling_any_provider(tmp_path):
    with fresh_workspace(tmp_path) as workspace:
        config = workspace.protocol.generation_config.model_copy(
            update={
                "seed": workspace.protocol.config.seed + 1,
            }
        )
        with RunStore.create(
            source_run(workspace),
            create_plan(
                config,
                run_id=workspace.protocol.source_run_id,
            ),
        ):
            pass

        class NeverProvider:
            def generate(self, blueprint, config):
                raise AssertionError("A foreign source plan reached authoring.")

        with pytest.raises(IntegrityError, match="protocol"):
            generate_sources(workspace, provider=NeverProvider())


def test_sibling_name_is_not_evidence_for_the_shorter_fact_entity():
    protocol = new_protocol(experiment_config())
    generation = protocol.generation_config.generation
    blueprint = create_plan(
        protocol.generation_config,
        run_id=protocol.source_run_id,
    ).blueprints[0]
    original = FamilyProvider().generate(blueprint, generation)
    target, sibling = generation.families[0].entities

    def replace_names(value):
        if isinstance(value, str):
            return value.replace(target, sibling)
        if isinstance(value, dict):
            return {key: replace_names(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [replace_names(item) for item in value]
        return value

    changed = original.model_copy(
        update={
            "title": original.title.replace(target, sibling),
            "blocks": tuple(
                Block.model_validate(replace_names(block.model_dump())) for block in original.blocks
            ),
        }
    )
    with pytest.raises(ValueError, match="scoped"):
        Acceptance(generation).accept(changed)


def test_byte_verification_is_conditional_and_reused_for_an_unchanged_blob_version(
    staged_workspace,
):
    azure, _, blobs, _ = azure_fixture(staged_workspace)

    def downloads():
        return [
            request
            for request in blobs.requests
            if request.method == "GET" and "comp=list" not in request.url
        ]

    with azure:
        prepare(staged_workspace, azure, live=True)
        observed = downloads()
        assert len(observed) == 12
        assert all(request.headers.get("If-Match") for request in observed)
        prepare(staged_workspace, azure, live=True)
        assert downloads() == observed


def test_legacy_metadata_only_snapshot_requires_byte_verification_before_reuse(staged_workspace):
    workspace = staged_workspace
    azure, _, _, _ = azure_fixture(workspace)
    with azure:
        prepare_snapshots(workspace, azure)
        with workspace.database:
            workspace.database.execute("DELETE FROM records WHERE name='blobs-verified'")
        with pytest.raises(InputError, match="verification"):
            snapshot(workspace, "de_split")
        prepare(workspace, azure, live=True)
        assert len(snapshot(workspace, "de_split").chunks) == 12
