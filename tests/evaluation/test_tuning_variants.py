import copy
import json
from pathlib import Path

import pytest

from docgen.cli import main
from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.context import source_contexts
from docgen.evaluation.corpus import generate_sources, sources
from docgen.evaluation.ingestion import ingest, prepare
from docgen.evaluation.models import ARMS, ExperimentConfig, load_experiment_config
from docgen.evaluation.profiles import PROFILES
from docgen.evaluation.reference import released_reference
from docgen.evaluation.reports import score
from docgen.evaluation.resources import definitions
from docgen.evaluation.runner import collect, parse_hits, query_vector
from docgen.evaluation.snapshots import assert_stable, take_snapshot
from docgen.evaluation.state import RemoteValue, Workspace, new_protocol
from docgen.evaluation.variants import fork_experiment, inherit_query_vectors
from tests.evaluation.fixtures import experiment_config
from tests.evaluation.test_azure import azure_fixture


def variant_config(workspace, **settings):
    data = json.loads(workspace.protocol.config.model_dump_json())
    data["search"]["variant"] = settings
    return ExperimentConfig.model_validate_json(json.dumps(data))


def fork(source, output, **settings):
    return fork_experiment(source, variant_config(source, **settings), output)


def freeze(workspace, azure):
    prepare(workspace, azure, live=True)
    ingest(workspace, azure, live=True)
    for arm in ARMS:
        take_snapshot(workspace, azure, arm, live=True)


def test_fork_preserves_sources_labels_and_existing_release_without_authoring(
    staged_workspace, tmp_path,
):
    source = staged_workspace
    before_documents, _ = sources(source)
    before_reference = released_reference(source)
    protected = {name: (source.path / name).read_bytes() for name in (
        "protocol.json", "reference.json", "qrels.trec",
    )}
    child_path = fork(source, tmp_path / "variants")
    with Workspace(child_path) as child:
        after_documents, _ = sources(child)
        after_reference = released_reference(child)
        assert after_documents == before_documents
        assert after_reference.intents == before_reference.intents
        assert after_reference.source_hash == before_reference.source_hash
        assert child.protocol.source_run_id == source.protocol.source_run_id
        assert child.protocol.source_prefix != source.protocol.source_prefix
        assert child.protocol.id != source.protocol.id
        assert child.usage()["attempts"] == dict.fromkeys(
            ("admin", "blob", "embedding", "search"), 0,
        )
        assert child.get("source-lineage")["new_authoring_calls"] == 0
        with pytest.raises(InputError, match="authoring"):
            generate_sources(child)
        assert child.protocol.enrichment_policy == "search-pipeline-only"
        with pytest.raises(InputError, match="historical"):
            source_contexts(child)
    assert protected == {name: (source.path / name).read_bytes() for name in protected}


def test_fork_cli_accepts_exported_json_configuration(staged_workspace, tmp_path, capsys):
    source_path = staged_workspace.path
    config = variant_config(staged_workspace)
    config_path = tmp_path / "variant.json"
    config_path.write_text(config.model_dump_json(), encoding="utf-8")
    staged_workspace.close()
    assert main([
        "experiment", "fork", "--experiment", str(source_path),
        "--config", str(config_path), "--output", str(tmp_path / "variants"), "--json",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ready"
    with Workspace(Path(result["details"]["variant_path"])) as variant:
        assert variant.protocol.config == config
        assert variant.get("source-lineage")["new_authoring_calls"] == 0
    assert main([
        "experiment", "status", "--experiment", result["details"]["variant_path"], "--json",
    ]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["details"]["sources_prepared"] is False
    assert status["details"]["enrichment_policy"] == "search-pipeline-only"
    assert "context_ready" not in status["details"]


def test_json_variant_config_keeps_duplicate_key_rejection(staged_workspace, tmp_path):
    config = variant_config(staged_workspace)
    path = tmp_path / "duplicate.json"
    path.write_text('{"seed": 1,' + config.model_dump_json()[1:], encoding="utf-8")
    with pytest.raises(InputError, match="Invalid"):
        load_experiment_config(path)


def test_fork_reuses_validated_query_embeddings_without_rebilling(staged_workspace, tmp_path):
    source = staged_workspace
    query = released_reference(source).intents[0].queries[0]
    original, _, _, _ = azure_fixture(source)
    with original:
        expected = query_vector(source, original, query, count_tokens=lambda _: 25)
    child_path = fork(source, tmp_path / "variants")
    with Workspace(child_path) as child:
        azure, backend, _, _ = azure_fixture(child)
        with azure:
            assert query_vector(child, azure, query, count_tokens=lambda _: 25) == expected
        assert not backend.requests
        assert child.usage()["attempts"]["embedding"] == 0
        assert child.get("source-lineage")["inherited_query_embedding_cache_entries"] == 1


def test_query_vectors_created_after_fork_can_be_shared_before_a_new_cohort(
    staged_workspace, tmp_path,
):
    source = staged_workspace
    child_path = fork(source, tmp_path / "variants")
    query = released_reference(source).intents[0].queries[0]
    original, _, _, _ = azure_fixture(source)
    with original:
        expected = query_vector(source, original, query, count_tokens=lambda _: 25)
    with Workspace(child_path) as child:
        assert inherit_query_vectors(source, child) == 1
        assert inherit_query_vectors(source, child) == 1
        azure, backend, _, _ = azure_fixture(child)
        with azure:
            assert query_vector(child, azure, query, count_tokens=lambda _: 25) == expected
        assert backend.requests == []
        assert child.usage()["attempts"]["embedding"] == 0


def test_query_vector_inheritance_never_overwrites_a_conflicting_confirmed_vector(
    staged_workspace, tmp_path,
):
    source = staged_workspace
    child_path = fork(source, tmp_path / "variants")
    query = released_reference(source).intents[0].queries[0]
    original, _, _, _ = azure_fixture(source)
    with original:
        query_vector(source, original, query, count_tokens=lambda _: 25)
    with Workspace(child_path) as child:
        azure, backend, _, _ = azure_fixture(child)
        backend.embedding_vector = [0.3, 0.2, 0.1]
        with azure:
            expected = query_vector(child, azure, query, count_tokens=lambda _: 25)
            with pytest.raises(IntegrityError, match="Immutable"):
                inherit_query_vectors(source, child)
            assert query_vector(child, azure, query, count_tokens=lambda _: 25) == expected
        assert len(backend.requests) == 1


@pytest.mark.parametrize("change", ["usage", "model", "dimensions", "fingerprint"])
def test_query_vector_inheritance_rejects_unvalidated_cache_without_copying(tmp_path, change):
    protocol = new_protocol(experiment_config())
    with (
        Workspace.create(tmp_path / "source", protocol) as source,
        Workspace.create(tmp_path / "target", new_protocol(experiment_config())) as target,
    ):
        fingerprint = "a" * 64
        value = RemoteValue(
            data={"vector": [0.1, 0.2, 0.3], "reported_model": "text-embedding-3-large"},
            tokens=None if change == "usage" else 25,
        ).model_dump(mode="json")
        if change == "model":
            value["data"]["reported_model"] = "other-model"
        elif change == "dimensions":
            value["data"]["vector"] = [0.1]
        cache_fingerprint = "b" * 64 if change == "fingerprint" else fingerprint
        source.put("request:vector:" + fingerprint, {
            "kind": "embedding", "fingerprint": cache_fingerprint,
        })
        source.put("remote:vector:" + fingerprint, {
            "fingerprint": cache_fingerprint, "result": value,
        })
        with pytest.raises((IntegrityError, ProviderError)):
            inherit_query_vectors(source, target)
        assert target.get("remote:vector:" + fingerprint) is None


def test_query_vector_inheritance_requires_matching_space_and_separate_workspaces(tmp_path):
    config = experiment_config()
    with Workspace.create(tmp_path / "source", new_protocol(config)) as source:
        with pytest.raises(InputError, match="separate"):
            inherit_query_vectors(source, source)
        data = json.loads(config.model_dump_json())
        data["search"]["embedding"]["deployment"] = "different-model-deployment"
        other = ExperimentConfig.model_validate_json(json.dumps(data))
        with Workspace.create(tmp_path / "target", new_protocol(other)) as target:
            with pytest.raises(InputError, match="identical"):
                inherit_query_vectors(source, target)


def test_interrupted_source_copy_cannot_be_restarted_as_new_authoring(
    staged_workspace, tmp_path, monkeypatch,
):
    def failed_copy(*args, **kwargs):
        raise OSError("Simulated copy boundary failure.")

    monkeypatch.setattr("docgen.evaluation.variants.shutil.copytree", failed_copy)
    output = tmp_path / "variants"
    with pytest.raises(OSError, match="copy boundary"):
        fork(staged_workspace, output)
    child_path = next(output.iterdir())
    with Workspace(child_path) as child:
        assert child.get("source-fork-origin")["authoring_forbidden"] is True
        assert child.get("source-lineage") is None
        with pytest.raises(InputError, match="authoring"):
            generate_sources(child)


@pytest.mark.parametrize("change", ["seed", "split", "embedding", "storage"])
def test_fork_rejects_source_or_embedding_contract_changes(staged_workspace, tmp_path, change):
    data = json.loads(variant_config(staged_workspace).model_dump_json())
    if change == "seed":
        data["seed"] += 1
    elif change == "split":
        data["split_weights"] = {"calibration": 1, "development": 0, "test": 0}
    elif change == "embedding":
        data["search"]["embedding"]["deployment"] = "other-embedding-deployment"
    else:
        data["storage"]["container"] = "other-container"
    config = ExperimentConfig.model_validate_json(json.dumps(data))
    with pytest.raises(InputError, match="identical"):
        fork_experiment(staged_workspace, config, tmp_path / "variants")
    assert not (tmp_path / "variants").exists()


def test_all_profiles_share_vectors_keep_independent_seals_and_score_early_cutoffs(
    staged_workspace, tmp_path,
):
    child_path = fork(staged_workspace, tmp_path / "variants")
    with Workspace(child_path) as workspace:
        azure, backend, _, _ = azure_fixture(workspace)
        with azure:
            freeze(workspace, azure)
            profiles = tuple(
                profile for profile in PROFILES
                if not profile.startswith(("entity-", "pipeline-entity-"))
            )
            for profile in profiles:
                rankings = collect(
                    workspace, azure, live=True, profile=profile, count_tokens=lambda _: 25,
                )
                assert len(rankings) == 48
                report = score(workspace, profile=profile)
                assert report["method"] == profile
                assert report["metric_implementation"]["cutoffs"] == [1, 3, 5, 10, 20]
                assert "precision_at_1" in report["paired"]
                assert "ndcg_at_3" in report["paired"]
                assert report["source_lineage"]["new_independent_corpus_or_replication"] is False
                if "semantic" in profile:
                    assert all(ranking.reranker_scores for ranking in rankings)
                before_queries = backend.query_count
                assert collect(
                    workspace, azure, live=True, profile=profile, count_tokens=lambda _: 25,
                ) == rankings
                assert score(workspace, profile=profile) == report
                assert backend.query_count == before_queries
            assert backend.query_count == 48 * len(profiles)
            assert len([
                request for request in backend.requests if "/embeddings" in str(request.url)
            ]) == 24
            requests = [
                json.loads(request.content)
                for request in backend.requests
                if request.url.path.endswith("/docs/search")
                and json.loads(request.content).get("search") != "*"
            ]
            assert requests
            assert all("scoringProfile" not in request for request in requests)
            assert all("filter" not in request for request in requests)
            assert all(
                request.get("searchFields") in (None, "content") for request in requests
            )


@pytest.mark.parametrize("damage", ["partial", "missing"])
@pytest.mark.parametrize("profile", ["semantic-hybrid", "semantic-bm25"])
def test_semantic_fallback_is_not_cached_as_success(staged_workspace, tmp_path, damage, profile):
    child_path = fork(staged_workspace, tmp_path / "variants")
    with Workspace(child_path) as workspace:
        azure, backend, _, _ = azure_fixture(workspace)
        with azure:
            freeze(workspace, azure)
            backend.semantic_failure = damage
            with pytest.raises(ProviderError, match="Semantic"):
                collect(
                    workspace, azure, live=True, profile=profile,
                    count_tokens=lambda _: 25,
                )
            assert workspace.get("collection-complete:test:" + profile) is None
            assert workspace.get("invalidated") is None
            backend.semantic_failure = None
            assert len(collect(
                workspace, azure, live=True, profile=profile,
                count_tokens=lambda _: 25,
            )) == 48


def test_native_variants_preserve_pipeline_text_vectors_and_boundaries(
    staged_workspace, tmp_path,
):
    child_path = fork(
        staged_workspace, tmp_path / "variants",
        de_tokens=512, de_overlap_tokens=64, cu_tokens=1024,
    )
    with Workspace(child_path) as workspace:
        azure, backend, _, _ = azure_fixture(workspace)
        original_chunks = copy.deepcopy(backend.chunks)
        with azure:
            prepare(workspace, azure, live=True)
            ingest(workspace, azure, live=True)
            for arm in ARMS:
                assert backend.chunks[arm] == original_chunks[arm]
                observed = take_snapshot(workspace, azure, arm, live=True)
                assert all(chunk.source_context is None for chunk in observed.chunks)
                assert workspace.get("context-complete:" + arm) is None
            embedding_inputs = [
                text
                for request in backend.requests if "/embeddings" in str(request.url)
                for text in json.loads(request.content)["input"]
            ]
            assert not embedding_inputs
            assert not any(
                request.url.path.endswith("/docs/index") for request in backend.requests
            )
            backend.chunks["de_split"][0]["embedding"][0] += 0.5
            with pytest.raises(IntegrityError, match="drift"):
                assert_stable(workspace, azure, "de_split")
            assert workspace.get("invalidated") is not None
        de, cu = (definitions(workspace.protocol, arm) for arm in ARMS)
        split = de["skillsets"]["skills"][1]
        assert (split["unit"], split["maximumPageLength"], split["pageOverlapLength"]) == (
            "azureOpenAITokens", 512, 64,
        )
        assert cu["skillsets"]["skills"][0]["chunkingProperties"] == {
            "method": "semantic", "unit": "tokens", "maximumLength": 1024, "overlapLength": 0,
        }


def test_fork_rejects_external_context_before_creating_a_workspace(staged_workspace, tmp_path):
    with pytest.raises(InputError, match="pipeline"):
        fork(staged_workspace, tmp_path / "variants", embedding_context=True)
    assert not (tmp_path / "variants").exists()


def test_native_snapshot_keeps_exact_observed_vectors_and_rejects_later_drift(
    staged_workspace, tmp_path,
):
    child_path = fork(staged_workspace, tmp_path / "variants")
    with Workspace(child_path) as workspace:
        azure, backend, _, _ = azure_fixture(workspace)
        vector = [0.12345679104328156, -0.23456789553165436, -0.0]
        for rows in backend.chunks.values():
            for row in rows:
                row["embedding"] = list(vector)
        with azure:
            prepare(workspace, azure, live=True)
            ingest(workspace, azure, live=True)
            frozen = take_snapshot(workspace, azure, "de_split", live=True)
            assert len(frozen.chunks) == 12
            assert_stable(workspace, azure, "de_split")
            backend.chunks["de_split"][0]["embedding"][0] += 0.0001
            with pytest.raises(IntegrityError, match="drift"):
                assert_stable(workspace, azure, "de_split")


@pytest.mark.parametrize("scores", [[1, 2], [4, None], [4, True], [4, 5]])
def test_semantic_ordering_and_score_types_are_checked(scores):
    response = {
        "@search.coverage": 100,
        "value": [
            {"id": key, "@search.score": 1, "@search.rerankerScore": value}
            for key, value in zip(("first", "second"), scores, strict=True)
        ],
    }
    with pytest.raises(ProviderError, match="Semantic"):
        parse_hits(response, ("first", "second"), semantic=True)
