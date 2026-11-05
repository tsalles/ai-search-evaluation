import copy
import json

import pytest
from pydantic import ValidationError

from docgen.errors import InputError, ProviderError
from docgen.evaluation.models import (
    ARMS,
    ExperimentLimits,
    IndexTuning,
    Query,
    QueryCohort,
    QueryTuning,
    SearchVariant,
)
from docgen.evaluation.profiles import retrieval_request
from docgen.evaluation.reference import released_reference
from docgen.evaluation.reports import score
from docgen.evaluation.resources import definitions
from docgen.evaluation.runner import collect, collection_plan
from docgen.evaluation.state import Protocol, RemoteValue, Workspace, new_protocol
from docgen.evaluation.variants import fork_experiment
from tests.evaluation.fixtures import experiment_config
from tests.evaluation.test_azure import azure_fixture
from tests.evaluation.test_tuning_variants import freeze, variant_config


def test_absent_index_query_and_semantic_extensions_preserve_historical_serialization():
    settings = experiment_config()
    assert "max_semantic_attempts" not in json.loads(settings.model_dump_json())["limits"]
    variant = json.loads(SearchVariant().model_dump_json())
    assert "index_tuning" not in variant and "query_tuning" not in variant
    protocol = new_protocol(settings)
    encoded = protocol.model_dump_json()
    assert Protocol.model_validate_json(encoded).model_dump_json() == encoded


@pytest.mark.parametrize(
    "values",
    [
        {"bm25_k1": True}, {"bm25_k1": "1.2"}, {"bm25_k1": -0.1}, {"bm25_k1": 3.1},
        {"bm25_b": True}, {"bm25_b": -0.1}, {"bm25_b": 1.1}, {"bm25_b": float("nan")},
        {"analyzer": "keyword"}, {"hnsw_m": True}, {"hnsw_m": 3}, {"hnsw_m": 11},
        {"hnsw_ef_construction": 99}, {"hnsw_ef_construction": 1001},
        {"hnsw_ef_search": 99}, {"hnsw_ef_search": 1001},
    ],
)
def test_index_tuning_rejects_unsupported_or_nonfinite_controls(values):
    with pytest.raises(ValidationError):
        IndexTuning.model_validate(values)


@pytest.mark.parametrize(
    "values",
    [
        {"vector_k": True}, {"vector_k": 49}, {"vector_k": 1001},
        {"vector_weight": True}, {"vector_weight": "0.5"}, {"vector_weight": 0},
        {"vector_weight": float("inf")}, {"vector_weight": 10.1},
        {"vector_exhaustive": "yes"}, {"search_mode": "automatic"},
        {"query_rewrites": 3}, {"max_text_recall_size": 100},
    ],
)
def test_query_tuning_keeps_supported_stable_api_controls_strict_and_bounded(values):
    with pytest.raises(ValidationError):
        QueryTuning.model_validate(values)


@pytest.mark.parametrize("value", [True, -1, "100"])
def test_semantic_dispatch_limits_reject_boolean_negative_and_string_values(value):
    with pytest.raises(ValidationError):
        ExperimentLimits(max_semantic_attempts=value)


@pytest.mark.parametrize(("choice", "expected"), [
    ("microsoft", "en.microsoft"), ("lucene", "en.lucene"), ("standard", "standard.lucene"),
])
def test_content_analyzer_follows_the_frozen_english_language(choice, expected):
    config = experiment_config()
    config = config.model_copy(update={
        "generation": config.generation.model_copy(update={"language": "en", "locale": "en-US"}),
        "search": config.search.model_copy(update={
            "variant": SearchVariant(index_tuning=IndexTuning(analyzer=choice)),
        }),
    })
    for arm in ARMS:
        fields = definitions(new_protocol(config), arm)["indexes"]["fields"]
        assert next(field for field in fields if field["name"] == "content")["analyzer"] == expected


@pytest.mark.parametrize(
    ("choice", "expected"), [
        ("microsoft", "pt-Br.microsoft"), ("lucene", "pt-Br.lucene"),
        ("standard", "standard.lucene"),
    ],
)
def test_index_tuning_changes_search_configuration_without_changing_pipeline_inputs(
    choice, expected,
):
    config = experiment_config()
    original_search = config.search.model_copy(update={"variant": SearchVariant()})
    protocol = new_protocol(config.model_copy(update={"search": original_search}))
    tuning = IndexTuning(
        analyzer=choice, bm25_k1=0.6, bm25_b=0.25,
        hnsw_m=8, hnsw_ef_construction=800, hnsw_ef_search=1000,
    )
    updated_search = original_search.model_copy(update={
        "variant": SearchVariant(index_tuning=tuning),
    })
    updated = protocol.model_copy(update={"config": config.model_copy(update={
        "search": updated_search,
    })})
    for arm in ARMS:
        before, after = definitions(protocol, arm), definitions(updated, arm)
        assert {k: v for k, v in before.items() if k != "indexes"} == {
            k: v for k, v in after.items() if k != "indexes"
        }
        observed = copy.deepcopy(after["indexes"])
        assert observed.pop("similarity") == {
            "@odata.type": "#Microsoft.Azure.Search.BM25Similarity", "k1": 0.6, "b": 0.25,
        }
        assert observed["vectorSearch"]["algorithms"][0]["hnswParameters"] == {
            "metric": "cosine", "m": 8, "efConstruction": 800, "efSearch": 1000,
        }
        observed["vectorSearch"] = before["indexes"]["vectorSearch"]
        fields = {field["name"]: field for field in observed["fields"]}
        assert set(fields) == {"id", "parent_id", "content", "content_path", "embedding"}
        assert fields["id"]["analyzer"] == "keyword"
        assert fields["content"]["analyzer"] == expected
        fields["content"]["analyzer"] = "pt-Br.microsoft"
        assert observed == before["indexes"]


@pytest.mark.parametrize("profile", ["hybrid", "semantic-hybrid", "semantic-hybrid-wide"])
def test_query_tuning_wires_the_same_bounded_candidates_into_hybrid_and_semantic(profile):
    query = Query(id="one", text="Quanto custa a Conta Aurora?")
    body = retrieval_request(
        query, [0.1, 0.2], profile=profile,
        tuning=QueryTuning(
            vector_k=200, vector_weight=0.25, vector_exhaustive=True, search_mode="all",
        ),
    )
    assert body["search"] == query.text and body["searchFields"] == "content"
    assert body["searchMode"] == "all"
    assert body["top"] == 50 and body["minimumCoverage"] == 100
    assert body["vectorQueries"] == [{
        "kind": "vector", "vector": [0.1, 0.2], "fields": "embedding",
        "k": 200, "weight": 0.25, "exhaustive": True,
    }]
    assert "filter" not in body and "orderby" not in body
    if profile.startswith("semantic-"):
        assert body["semanticQuery"] == query.text
        assert body["semanticErrorHandling"] == "fail"
    else:
        assert "semanticQuery" not in body


def test_semantic_bm25_reranks_text_without_requiring_or_sending_query_vectors():
    query = Query(id="one", text="Qual e a tarifa?")
    body = retrieval_request(query, None, profile="semantic-bm25")
    assert body == {
        "search": query.text, "queryType": "simple", "searchMode": "any",
        "searchFields": "content", "select": "id", "top": 50, "minimumCoverage": 100,
        "semanticQuery": query.text, "semanticConfiguration": "content-only",
        "semanticErrorHandling": "fail",
    }


def test_semantic_bm25_is_collected_scored_cached_and_budgeted_without_embeddings(
    staged_workspace, tmp_path,
):
    config = variant_config(
        staged_workspace,
        index_tuning={"analyzer": "lucene", "bm25_k1": 0.6, "bm25_b": 0.25},
        query_tuning={"vector_k": 200, "vector_weight": 0.25},
    )
    config = config.model_copy(update={"limits": config.limits.model_copy(update={
        "max_semantic_attempts": 4,
    })})
    path = fork_experiment(staged_workspace, config, tmp_path / "variant")
    with Workspace(path) as workspace:
        azure, backend, _, _ = azure_fixture(workspace)
        intent = released_reference(workspace).intents[0]
        cohort = QueryCohort(name="one-intent", split="test", intent_ids=(intent.id,))
        with azure:
            freeze(workspace, azure)
            plan = collection_plan(workspace, "test", profile="semantic-bm25", cohort=cohort)
            assert plan["semantic_reranking"] is True and plan["vector_k"] is None
            assert plan["query_tuning"]["vector_k"] == 200
            results = collect(workspace, azure, live=True, profile="semantic-bm25", cohort=cohort)
            assert len(results) == 4 and all(result.reranker_scores for result in results)
            report = score(workspace, profile="semantic-bm25", cohort=cohort)
            assert report["method"] == "semantic-bm25"
            assert report["variant"]["index_tuning"]["analyzer"] == "lucene"
            assert report["usage"]["evaluation"]["semantic_attempts"] == 4
            assert workspace.usage()["attempts"]["embedding"] == 0
            assert workspace.usage()["semantic_attempts"] == 4
            assert not any("/embeddings" in str(request.url) for request in backend.requests)
            assert collect(
                workspace, azure, live=True, profile="semantic-bm25", cohort=cohort,
            ) == results
            assert backend.query_count == 4


@pytest.mark.parametrize("failure", ["retryable", "interrupted"])
def test_semantic_attempt_limit_includes_failed_and_unknown_dispatches_and_survives_reopen(
    tmp_path, failure,
):
    config = experiment_config()
    config = config.model_copy(update={"limits": config.limits.model_copy(update={
        "max_semantic_attempts": 1,
    })})
    calls = 0

    def failed_call():
        nonlocal calls
        calls += 1
        if failure == "interrupted":
            raise KeyboardInterrupt
        raise ProviderError("transport", "Simulated transport failure.", retryable=True)

    with Workspace.create(tmp_path, new_protocol(config)) as workspace:
        path = workspace.path
        error = KeyboardInterrupt if failure == "interrupted" else ProviderError
        with pytest.raises(error):
            workspace.invoke("search", "one", failed_call, semantic=True)
        assert calls == 1
        assert workspace.usage()["semantic_attempts"] == 1
        assert workspace.usage()["attempts"]["search"] == 1
    with Workspace(path) as workspace:
        with pytest.raises(ProviderError, match="semantic request budget"):
            workspace.invoke("search", "two", failed_call, semantic=True)
        assert calls == 1


def test_semantic_cached_success_can_be_reused_after_its_dispatch_limit(tmp_path):
    config = experiment_config()
    config = config.model_copy(update={"limits": config.limits.model_copy(update={
        "max_semantic_attempts": 1,
    })})
    calls = 0

    def call():
        nonlocal calls
        calls += 1
        return RemoteValue(data={"value": []})

    with Workspace.create(tmp_path, new_protocol(config)) as workspace:
        first = workspace.invoke("search", "one", call, fingerprint="a" * 64, semantic=True)
        assert workspace.invoke(
            "search", "one", call, fingerprint="a" * 64, semantic=True,
        ) == first
        assert workspace.invoke("search", "plain", call).data == {"value": []}
        assert calls == 2 and workspace.usage()["semantic_attempts"] == 1
        assert workspace.usage()["attempts"]["search"] == 2
        with pytest.raises(InputError, match="Search request"):
            workspace.invoke("embedding", "invalid", call, semantic=True)


def test_zero_semantic_limit_blocks_dispatch_without_using_the_search_budget(tmp_path):
    config = experiment_config()
    config = config.model_copy(update={"limits": config.limits.model_copy(update={
        "max_semantic_attempts": 0,
    })})
    with Workspace.create(tmp_path, new_protocol(config)) as workspace:
        with pytest.raises(ProviderError, match="semantic request budget"):
            workspace.invoke(
                "search", "blocked", lambda: pytest.fail("Semantic request was dispatched."),
                semantic=True,
            )
        assert workspace.usage()["attempts"]["search"] == 0
        assert workspace.usage()["semantic_attempts"] == 0
