import json

import pytest
from pydantic import ValidationError

from docgen.cli import main
from docgen.errors import InputError, IntegrityError
from docgen.evaluation.models import Query, QueryCohort
from docgen.evaluation.profiles import retrieval_request, scope
from docgen.evaluation.reference import released_reference
from docgen.evaluation.reports import score
from docgen.evaluation.runner import collect, collection_plan, queries
from tests.evaluation.test_azure import azure_fixture
from tests.evaluation.test_runner import prepare_snapshots


@pytest.mark.parametrize(
    "changes",
    [{"intent_ids": []}, {"intent_ids": ["one", "one"]}, {"name": "../scope"}],
)
def test_query_cohort_rejects_empty_duplicate_or_unsafe_selections(changes):
    data = {"name": "selected", "split": "test", "intent_ids": ["one"]}
    with pytest.raises(ValidationError):
        QueryCohort.model_validate({**data, **changes})


@pytest.mark.parametrize(
    ("profile", "weight", "k"),
    [
        ("semantic-hybrid-lexical", 0.5, 50),
        ("semantic-hybrid-vector", 2.0, 50),
        ("semantic-hybrid-wide", 1.0, 100),
        ("hybrid-wide", 1.0, 100),
    ],
)
def test_weighted_and_wider_profiles_keep_original_question_and_bounded_raw_depth(
    profile, weight, k,
):
    query = Query(id="sample", text="Quanto custa a Conta Aurora?")
    body = retrieval_request(query, [0.1], profile=profile)
    assert body["search"] == query.text
    assert body["searchFields"] == "content"
    assert body["top"] == 50
    assert body["vectorQueries"][0]["weight"] == weight
    assert body["vectorQueries"][0]["k"] == k
    if profile.startswith("semantic-"):
        assert body["semanticQuery"] == query.text
        assert body["semanticConfiguration"] == "content-only"
        assert body["semanticErrorHandling"] == "fail"


def test_cohort_preserves_complete_intents_without_releasing_new_truth(staged_workspace):
    reference = released_reference(staged_workspace)
    cohort = QueryCohort(
        name="selected", split="test",
        intent_ids=(reference.intents[0].id, reference.intents[1].id),
    )
    selected = queries(reference, "test", cohort=cohort)
    assert selected == reference.intents[0].queries + reference.intents[1].queries
    assert queries(reference, "test") != selected
    assert scope("test", "hybrid") == "test"
    assert scope("test", "hybrid", cohort=cohort) == "test:cohort-selected"
    assert released_reference(staged_workspace) == reference


@pytest.mark.parametrize("foreign", [False, True])
def test_invalid_cohort_fails_before_live_requests_or_registration(staged_workspace, foreign):
    reference = released_reference(staged_workspace)
    cohort = QueryCohort(
        name="selected", split="development" if foreign else "test",
        intent_ids=(reference.intents[0].id if foreign else "missing-intent",),
    )
    azure, backend, _, _ = azure_fixture(staged_workspace)
    with azure, pytest.raises(InputError, match="cohort"):
        collect(
            staged_workspace, azure, live=True, split=cohort.split, cohort=cohort,
            count_tokens=lambda _: 25,
        )
    assert backend.requests == []
    assert staged_workspace.get("query-cohort:selected") is None


def test_complete_cohort_has_independent_seals_reports_and_no_false_full_split_completion(
    staged_workspace, capsys,
):
    workspace = staged_workspace
    reference = released_reference(workspace)
    cohort = QueryCohort(name="selected", split="test", intent_ids=(reference.intents[0].id,))
    original_qrels = (workspace.path / "qrels.trec").read_bytes()
    azure, backend, _, _ = azure_fixture(workspace)
    with azure:
        prepare_snapshots(workspace, azure)
        plan = collection_plan(workspace, "test", profile="semantic-hybrid-wide", cohort=cohort)
        assert plan["vector_k"] == 100 and len(plan["order"]) == 4
        outcomes = collect(
            workspace, azure, live=True, cohort=cohort, profile="semantic-hybrid-wide",
            count_tokens=lambda _: 25,
        )
        assert len(outcomes) == 4
        report = score(workspace, cohort=cohort, profile="semantic-hybrid-wide")
        assert report["denominators"]["intents"] == 1
        assert report["denominators"]["utterances"] == 2
        assert report["denominators"]["arm_query_responses"] == 4
        assert report["denominators"]["source_documents"] == 12
        assert report["query_cohort"] == cohort.model_dump(mode="json")
        assert workspace.get("collection-complete:test") is None
        assert workspace.get("collection-complete:test:semantic-hybrid-wide") is None
        assert workspace.get("collection-complete:test:semantic-hybrid-wide:cohort-selected")
        assert (workspace.path / "report-test-semantic-hybrid-wide-cohort-selected.json").is_file()
        assert (workspace.path / "qrels.trec").read_bytes() == original_qrels
        assert collect(
            workspace, azure, live=True, cohort=cohort, profile="semantic-hybrid-wide",
            count_tokens=lambda _: 25,
        ) == outcomes
        assert backend.query_count == 4
        changed = cohort.model_copy(update={"intent_ids": (reference.intents[1].id,)})
        with pytest.raises(IntegrityError, match="Immutable"):
            collect(
                workspace, azure, live=True, cohort=changed, profile="semantic-hybrid-wide",
                count_tokens=lambda _: 25,
            )
    cohort_path = workspace.export("selected-cohort.json", cohort)
    directory = workspace.path
    workspace.close()
    assert main([
        "experiment", "score", "--experiment", str(directory),
        "--profile", "semantic-hybrid-wide", "--cohort", str(cohort_path), "--json",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["details"]["denominators"]["arm_query_responses"] == 4
    assert result["reports"]["evaluation"].endswith(
        "report-test-semantic-hybrid-wide-cohort-selected.json",
    )
    assert main(["experiment", "status", "--experiment", str(directory), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["details"]["completed_cohorts"] == {
        "selected": {"split": "test", "profiles": ["semantic-hybrid-wide"]},
    }
    assert status["details"]["completed_profiles"]["test"] == []
