import copy
import json
from itertools import count
from types import SimpleNamespace

import httpx
import pytest

from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.azure import Azure
from docgen.evaluation.ingestion import ingest, prepare
from docgen.evaluation.models import ARMS, IngestionAudit, MissingSource
from docgen.evaluation.reference import released_reference
from docgen.evaluation.reports import paired_estimates, percentile, score
from docgen.evaluation.runner import collect, parse_hits, queries, query_vector
from docgen.evaluation.snapshots import take_snapshot
from docgen.evaluation.state import Workspace, digest
from tests.evaluation.azure_double import Credential
from tests.evaluation.test_azure import azure_fixture


def prepare_snapshots(workspace, azure):
    prepare(workspace, azure, live=True)
    ingest(workspace, azure, live=True)
    for arm in ARMS:
        take_snapshot(workspace, azure, arm, live=True)


def test_fresh_corpus_to_paired_report_uses_same_hybrid_vectors_and_gold(staged_workspace):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    reference = released_reference(workspace)
    doc_ids = {index: document.id for index, document in enumerate(reference.documents)}
    for arm in ARMS:
        duplicate = copy.deepcopy(backend.chunks[arm][0])
        duplicate["id"] = "chunk-9999"
        backend.chunks[arm].append(duplicate)
    for intent in reference.intents:
        grades = {judgment.doc_id: judgment.grade for judgment in intent.judgments}
        for arm in ARMS:
            ordered = sorted(
                backend.chunks[arm],
                key=lambda chunk: grades.get(
                    doc_ids[int(chunk["id"].split("-")[-1])]
                    if chunk["id"] != "chunk-9999"
                    else reference.documents[0].id,
                    0,
                ),
                reverse=arm == "content_understanding",
            )
            for query in intent.queries:
                backend.query_rankings[(arm, query.text)] = ordered
    with azure:
        prepare_snapshots(workspace, azure)
        with pytest.raises((InputError, IntegrityError)):
            score(workspace)
        rankings = collect(workspace, azure, live=True, count_tokens=lambda _: 25)
        assert len(rankings) == 48
        assert backend.query_count == 48
        embeddings = [request for request in backend.requests if "/embeddings" in str(request.url)]
        assert len(embeddings) == 24
        search_bodies = [
            json.loads(request.content)
            for request in backend.requests
            if request.method == "POST"
            and "/docs/search" in str(request.url)
            and json.loads(request.content)["search"] != "*"
        ]
        assert len(search_bodies) == 48
        for text in {body["search"] for body in search_bodies}:
            paired = [body for body in search_bodies if body["search"] == text]
            assert len(paired) == 2 and paired[0] == paired[1]
            assert paired[0]["queryType"] == "simple"
            assert paired[0]["searchFields"] == "content"
            assert paired[0]["vectorQueries"][0]["weight"] == 1
        report = score(workspace)
        assert report["status"] == "complete"
        assert report["paired"]["ndcg_at_10"]["content_understanding"] == pytest.approx(1.0)
        assert report["paired"]["ndcg_at_10"]["cu_minus_de"] > 0
        assert report["denominators"]["arm_query_responses"] == 48
        assert report["denominators"]["answerable_intents"] == 10
        assert report["denominators"]["unanswerable_intents"] == 2
        assert all(row["metrics"] is None for row in report["per_query"] if not row["answerable"])
        assert report["evidence_metrics"]["status"] == "not_evaluated"
        assert report["usage"]["evaluation"]["observed_embedding_tokens"] == 24 * 25
        assert all(row["returned_parents"] == 12 for row in report["per_query"])
        assert all(row["returned_chunks"] == 13 for row in report["per_query"])
        assert (workspace.path / "report-test.json").is_file()
        assert (workspace.path / "run-de_split-test.trec").is_file()
        assert score(workspace) == report
        assert collect(workspace, azure, live=True, count_tokens=lambda _: 25) == rankings
        assert backend.query_count == 48
        assert score(workspace) == report
        assert (
            len([request for request in backend.requests if "/embeddings" in str(request.url)])
            == 24
        )


def test_failure_resume_reuses_confirmed_queries_and_only_scores_complete_pairs(staged_workspace):
    workspace = staged_workspace
    azure, backend, blobs, _ = azure_fixture(workspace)
    directory = workspace.path
    with azure:
        prepare_snapshots(workspace, azure)
        backend.fail_after_queries = 1
        with pytest.raises(ProviderError, match="HTTP 403"):
            collect(workspace, azure, live=True, count_tokens=lambda _: 25)
        assert workspace.get("collection-complete:test") is None
        with pytest.raises(InputError, match="every arm/query"):
            score(workspace)
        assert (
            len(
                workspace.database.execute(
                    "SELECT name FROM records WHERE name LIKE 'ranking:%'"
                ).fetchall()
            )
            == 1
        )
    workspace.close()
    backend.fail_after_queries = None
    with (
        Workspace(directory) as resumed,
        Azure(
            workspace.protocol,
            credential=Credential(),
            blob_transport=blobs,
            http_client=httpx.Client(transport=httpx.MockTransport(backend)),
        ) as azure,
    ):
        assert len(collect(resumed, azure, live=True, count_tokens=lambda _: 25)) == 48
        assert backend.query_count == 49
        assert score(resumed)["status"] == "complete"


def test_interrupt_after_confirmed_search_cache_does_not_repeat_the_request(
    staged_workspace,
    monkeypatch,
):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    ticks = count(0.0, 0.001)
    # Windows' coarse monotonic clock can time a mocked request as zero milliseconds.
    monkeypatch.setattr(
        "docgen.evaluation.state.time",
        SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _: None),
    )
    with azure:
        prepare_snapshots(workspace, azure)
        original = workspace.record

        def interrupt(name, value):
            if name.startswith("ranking:"):
                raise KeyboardInterrupt
            return original(name, value)

        monkeypatch.setattr(workspace, "record", interrupt)
        with pytest.raises(KeyboardInterrupt):
            collect(workspace, azure, live=True, count_tokens=lambda _: 25)
        assert backend.query_count == 1
        monkeypatch.setattr(workspace, "record", original)
        assert len(collect(workspace, azure, live=True, count_tokens=lambda _: 25)) == 48
        assert backend.query_count == 48
        assert score(workspace)["latency"]["arms"]["de_split"]["mean_ms"] == pytest.approx(1.0)


def test_partial_response_is_not_cached_as_a_success_or_silently_scored(staged_workspace):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    with azure:
        prepare_snapshots(workspace, azure)
        backend.query_coverage = 80
        with pytest.raises(ProviderError, match="partial"):
            collect(workspace, azure, live=True, count_tokens=lambda _: 25)
        assert workspace.get("collection-complete:test") is None
        assert not workspace.database.execute(
            "SELECT name FROM records WHERE name LIKE 'remote:ranking:%'"
        ).fetchall()
        backend.query_coverage = 100
        collect(workspace, azure, live=True, count_tokens=lambda _: 25)
        assert score(workspace)["status"] == "complete"


def test_missing_source_retains_full_positive_recall_denominator(staged_workspace):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    reference = released_reference(workspace)
    with azure:
        prepare(workspace, azure, live=True)
        ingest(workspace, azure, live=True)
        take_snapshot(workspace, azure, "de_split", live=True)
        backend.chunks["content_understanding"].pop(0)
        audit = IngestionAudit(
            arm="content_understanding",
            execution_hash=digest(backend.statuses["content_understanding"]["lastResult"]),
            reviewer="Source Reviewer",
            source_failures_only=True,
            missing=(
                MissingSource(
                    doc_id=reference.documents[0].id,
                    reviewer="Source Reviewer",
                    reason="Exact source had no chunks after reviewed terminal ingestion.",
                ),
            ),
        )
        take_snapshot(workspace, azure, "content_understanding", live=True, audit=audit)
        collect(workspace, azure, live=True, count_tokens=lambda _: 25)
        report = score(workspace)
    first_query = reference.intents[0].queries[0].id
    observed = {row["arm"]: row for row in report["per_query"] if row["query_id"] == first_query}
    assert observed["de_split"]["metrics"]["recall_at_20"] == 1
    assert observed["content_understanding"]["metrics"]["recall_at_20"] == pytest.approx(2 / 3)
    assert report["ingestion"]["content_understanding"]["missing_sources"][0]["doc_id"] == (
        reference.documents[0].id
    )
    assert report["denominators"]["source_documents"] == 12


def test_empty_successful_results_are_zero_while_unanswerable_metrics_are_na(staged_workspace):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    backend.rankings = {arm: [] for arm in ARMS}
    with azure:
        prepare_snapshots(workspace, azure)
        collect(workspace, azure, live=True, count_tokens=lambda _: 25)
        report = score(workspace)
    assert report["paired"]["ndcg_at_10"]["de_split"] == 0
    assert report["paired"]["ndcg_at_10"]["content_understanding"] == 0
    assert all(
        set(row["metrics"].values()) == {0.0} for row in report["per_query"] if row["answerable"]
    )


def test_long_queries_are_rejected_without_truncation_or_embedding_requests(staged_workspace):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    query = queries(released_reference(workspace), "test")[0]
    with azure, pytest.raises(InputError, match="truncation"):
        query_vector(workspace, azure, query, count_tokens=lambda _: 10000)
    assert not backend.requests


def test_drift_permanently_blocks_reuse_of_previously_sealed_rankings(staged_workspace):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    with azure:
        prepare_snapshots(workspace, azure)
        collect(workspace, azure, live=True, count_tokens=lambda _: 25)
        backend.chunks["de_split"][0]["embedding"] = [0.2, 0.3, 0.4]
        with pytest.raises(IntegrityError, match="drift"):
            collect(workspace, azure, live=True, count_tokens=lambda _: 25)
        backend.chunks["de_split"][0]["embedding"] = [0.1, 0.2, 0.3]
        with pytest.raises(IntegrityError, match="permanently"):
            score(workspace)


def test_paired_family_bootstrap_uses_clustered_differences_and_reproducible_percentiles():
    families = {
        "first": {"de_split": {"ndcg_at_10": 0.0}, "content_understanding": {"ndcg_at_10": 1.0}},
        "second": {"de_split": {"ndcg_at_10": 1.0}, "content_understanding": {"ndcg_at_10": 0.0}},
    }
    result = paired_estimates(families, seed=3, resamples=1000)
    assert result["ndcg_at_10"] == {
        "de_split": 0.5,
        "content_understanding": 0.5,
        "cu_minus_de": 0.0,
        "ci95": [-1.0, 1.0],
        "family_count": 2,
    }
    assert paired_estimates(families, seed=3, resamples=1000) == result
    assert (
        paired_estimates({"first": families["first"]}, seed=3, resamples=100)["ndcg_at_10"]["ci95"]
        is None
    )
    assert percentile([0, 10, 20, 30], 0.25) == 7.5


@pytest.mark.parametrize(
    "payload",
    [
        {"value": [], "@search.coverage": 20},
        {"value": [{"id": "other", "@search.score": 1}], "@search.coverage": 100},
        {"value": [{"id": "known", "@search.score": float("inf")}], "@search.coverage": 100},
        {"value": [{"id": "known", "@search.score": 10**400}], "@search.coverage": 100},
    ],
)
def test_partial_unknown_and_nonfinite_results_are_rejected(payload):
    with pytest.raises((ProviderError, IntegrityError)):
        parse_hits(payload, {"known"})
