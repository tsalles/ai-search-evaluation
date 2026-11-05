import hashlib

import pytest

from docgen.allocation import allocate
from docgen.errors import InputError, IntegrityError
from docgen.evaluation.corpus import generate_sources, source_run, sources
from docgen.evaluation.revisions import create_quality_revision, create_source_revision
from docgen.evaluation.state import RemoteValue, Workspace, new_protocol
from docgen.generation import generate_content
from docgen.models import Usage, content_hash
from docgen.planning import create_plan
from docgen.store import RunStore
from tests.evaluation.fixtures import FamilyProvider
from tests.evaluation.test_saas_families import saas_config


class RevisionProvider(FamilyProvider):
    def __init__(self, failing=None):
        super().__init__()
        self.failing = failing

    def generate(self, blueprint, config):
        content = super().generate(blueprint, config)
        return content.model_copy(update={
            "title": "A" * 200 if blueprint.content_id == self.failing else content.title,
            "provenance": content.provenance.model_copy(update={"usage": Usage(total_tokens=5)}),
        })


def unpublished_source(tmp_path, *, max_requests=None):
    config = saas_config()
    if max_requests is not None:
        generation = config.generation.model_copy(update={
            "limits": config.generation.limits.model_copy(update={"max_requests": max_requests}),
        })
        config = config.model_copy(update={"generation": generation})
    protocol = new_protocol(config)
    plan = create_plan(protocol.generation_config, run_id=protocol.source_run_id)
    provider = RevisionProvider()
    contents = tuple(
        provider.generate(blueprint, protocol.generation_config.generation)
        for blueprint in plan.blueprints
    )
    allocation = allocate(contents, protocol.config.rendering, seed=protocol.config.seed)
    failing = next(item.content_id for item in allocation.items if item.format == "pdf")
    workspace = Workspace.create(tmp_path / "source", protocol)
    result = generate_sources(workspace, provider=RevisionProvider(failing))
    assert result.status == "incomplete", result
    assert result.accepted_count == 12
    assert result.verified_document_count == 11
    return workspace, failing


def file_hashes(directory):
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file() and not path.name.endswith(".lock")
    }


def test_unpublished_revision_retains_clean_bytes_usage_and_native_assignments(tmp_path):
    original, rejected = unpublished_source(tmp_path)
    with original:
        before = file_hashes(original.path)
        with RunStore.open(source_run(original)) as store:
            original_contents = {
                row.blueprint.content_id: content_hash(row) for row in store.contents()
            }
            allocation = store.read_allocation()
            attempts = store.attempts()
        target = create_source_revision(
            original, tmp_path / "corrected",
            rejected={rejected: ("Native title cannot fit the frozen PDF layout.",)},
        )
        assert file_hashes(original.path) == before
        with Workspace(target) as revision:
            provider = RevisionProvider()
            result = generate_sources(revision, provider=provider)
            assert result.status == "complete", result.failures
            assert provider.calls == [rejected]
            assert result.usage["requests"] == 13
            assert result.usage["observed_total_tokens"] == 65
            documents, contents = sources(revision)
            assert len(documents) == len(contents) == 12
            for content in contents:
                identifier = content.blueprint.content_id
                assert (content_hash(content) == original_contents[identifier]) == (
                    identifier != rejected
                )
            with RunStore.open(source_run(revision)) as store:
                revised = store.read_allocation()
                assert store.attempts()[:12] == attempts
                assert store.candidate_count(rejected) == 2
                assert [row.model_dump(exclude={"source_hash"}) for row in revised.items] == [
                    row.model_dump(exclude={"source_hash"}) for row in allocation.items
                ]
            resumed = generate_sources(revision, provider=provider)
            assert resumed.usage == result.usage
            assert provider.calls == [rejected]
        assert file_hashes(original.path) == before


def test_source_revision_refuses_published_sources_and_foreign_rejections(tmp_path):
    with Workspace.create(tmp_path / "source", new_protocol(saas_config())) as workspace:
        assert generate_sources(workspace, provider=RevisionProvider()).status == "complete"
        with pytest.raises(InputError, match="unpublished"):
            create_source_revision(
                workspace, tmp_path / "corrected", rejected={"item-000001": ("Reason",)},
            )
    original, _ = unpublished_source(tmp_path / "other")
    with original, pytest.raises(InputError, match="planned"):
        create_source_revision(
            original, tmp_path / "corrected", rejected={"foreign-item": ("Reason",)},
        )


def test_source_revision_refuses_measured_sources(tmp_path):
    original, rejected = unpublished_source(tmp_path)
    with original:
        original.invoke("admin", "measured", lambda: RemoteValue(data={}))
        with pytest.raises(InputError, match="remote"):
            create_source_revision(
                original, tmp_path / "corrected", rejected={rejected: ("Reason",)},
            )


def test_source_revision_cannot_reset_the_global_request_ceiling(tmp_path):
    original, rejected = unpublished_source(tmp_path, max_requests=12)
    with original:
        target = create_source_revision(
            original, tmp_path / "corrected", rejected={rejected: ("Native failure",)},
        )
        with Workspace(target) as revision:
            provider = RevisionProvider()
            result = generate_sources(revision, provider=provider)
            assert result.status == "incomplete"
            assert result.accepted_count == 11
            assert result.usage["requests"] == 12
            assert result.usage["observed_total_tokens"] == 60
            assert not provider.calls


def test_native_infeasible_replacement_is_retried_before_acceptance(tmp_path):
    original, rejected = unpublished_source(tmp_path)
    with original:
        target = create_source_revision(
            original, tmp_path / "corrected", rejected={rejected: ("Native failure",)},
        )
        with Workspace(target) as revision:
            class RetryProvider(RevisionProvider):
                def generate(self, blueprint, config):
                    self.failing = rejected if not self.calls else None
                    return super().generate(blueprint, config)

            provider = RetryProvider()
            result = generate_sources(revision, provider=provider)
            assert result.status == "complete", result.failures
            assert provider.calls == [rejected, rejected]
            assert result.usage["requests"] == 14
            with RunStore.open(source_run(revision)) as store:
                assert store.candidate_count(rejected) == 3


def test_revision_stops_if_preserved_original_evidence_changes(tmp_path):
    original, rejected = unpublished_source(tmp_path)
    with original:
        target = create_source_revision(
            original, tmp_path / "corrected", rejected={rejected: ("Native failure",)},
        )
        path = original.path / "protocol.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with (
            Workspace(target) as revision,
            pytest.raises(IntegrityError, match="preserved original"),
        ):
            generate_sources(revision, provider=RevisionProvider())


def test_correction_does_not_reconcile_an_interrupted_original_request(tmp_path):
    original, rejected = unpublished_source(tmp_path)
    with original:
        with RunStore.open(source_run(original)) as store, store.connection:
            store.connection.execute(
                "UPDATE attempts SET status='in_flight' WHERE rowid=1"
            )
        before = file_hashes(original.path)
        with pytest.raises(IntegrityError, match="quiescent"):
            create_source_revision(
                original, tmp_path / "corrected", rejected={rejected: ("Native failure",)},
            )
        assert file_hashes(original.path) == before


def test_published_quality_revision_preserves_measurements_but_never_inherits_them(tmp_path):
    from docgen.evaluation.reference import build_reference, release_reference

    with Workspace.create(tmp_path / "source", new_protocol(saas_config())) as source:
        assert generate_sources(source, provider=RevisionProvider()).status == "complete"
        build_reference(source)
        release_reference(source, provisional=True)
        source.put("ranking:historical-result", {"scores": [0.5]})
        source.invoke("search", "previous-measurement", lambda: RemoteValue(data={}))
        before = file_hashes(source.path)
        target = create_quality_revision(
            source, tmp_path / "corrected",
            rejected={"item-000001": ("Visible unresolved source marker.",)},
        )
        assert file_hashes(source.path) == before
        with Workspace(target) as revision:
            assert revision.get("ranking:historical-result") is None
            assert revision.get("reference") is None
            assert revision.database.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
            policy = revision.get("quality-correction-policy")
            assert policy["new_indexing_and_measurement_required"]

            class Replacement(RevisionProvider):
                def generate(self, blueprint, config):
                    content = super().generate(blueprint, config)
                    return content.model_copy(update={"title": "Procedimento de ativacao revisado"})

            provider = Replacement()
            result = generate_sources(revision, provider=provider)
            assert result.status == "complete", result.failures
            assert provider.calls == ["item-000001"]
            assert result.usage["requests"] == 13
        assert file_hashes(source.path) == before


def test_generic_resume_cannot_skip_the_corrective_native_acceptance_gate(tmp_path):
    source, rejected = unpublished_source(tmp_path)
    with source:
        target = create_source_revision(
            source, tmp_path / "corrected", rejected={rejected: ("Native failure",)},
        )
        with Workspace(target) as workspace, RunStore.open(source_run(workspace)) as store:
            provider = RevisionProvider(failing=rejected)
            before = len(store.attempts())
            with pytest.raises(InputError, match="experiment workspace"):
                generate_content(store, provider=provider)
            assert not provider.calls
            assert len(store.attempts()) == before
