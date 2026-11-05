import json
from pathlib import Path

import pytest

from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.corpus import generate_sources, sources
from docgen.evaluation.models import ExperimentConfig, Reference
from docgen.evaluation.reference import (
    build_reference,
    load_record,
    release_reference,
    review_intent,
    validate_reference,
)
from docgen.evaluation.state import RemoteValue, Workspace, new_protocol
from tests.evaluation.fixtures import FamilyProvider, experiment_config, fresh_workspace


def approve_reference(workspace):
    reference = load_record(workspace.path / "reference-draft.json", Reference)
    changed = reference.model_copy(
        update={
            "intents": tuple(
                intent.model_copy(
                    update={
                        "queries": tuple(
                            query.model_copy(
                                update={
                                    "text": query.text + " Por favor.",
                                    "authorship": "human",
                                }
                            )
                            for query in intent.queries
                        ),
                    }
                )
                for intent in reference.intents
            ),
        }
    )
    (workspace.path / "reference-draft.json").write_text(
        changed.model_dump_json(), encoding="utf-8"
    )
    for intent in changed.intents:
        for reviewer in ("Reviewer One", "Reviewer Two"):
            review_intent(workspace, intent_id=intent.id, reviewer=reviewer, certify_scope=True)
    return release_reference(workspace)


@pytest.mark.parametrize(
    ("language", "locale", "expected"),
    [
        (
            "pt",
            "pt-BR",
            {
                "fee": (
                    "Qual e o valor em BRL informado para a {first}?",
                    "Que valor monetario o documento apresenta para a {first}?",
                ),
                "age": (
                    "Qual e o requisito de idade informado para a {first}?",
                    "Que idade o documento informa para solicitar a {first}?",
                ),
                "comparison": (
                    "Compare os valores em BRL informados para a {first} e a {second}.",
                    "Qual valor monetario e apresentado para cada uma: {first} e {second}?",
                ),
            },
        ),
        (
            "en",
            "en-US",
            {
                "fee": (
                    "What amount in BRL is stated for {first}?",
                    "What monetary amount does the document give for {first}?",
                ),
                "age": (
                    "What age requirement is stated for {first}?",
                    "What age does the document give for requesting {first}?",
                ),
                "comparison": (
                    "Compare the stated amounts in BRL for {first} and {second}.",
                    "What monetary amount is given for each: {first} and {second}?",
                ),
            },
        ),
    ],
)
def test_draft_queries_do_not_add_unspecified_fee_cadence_or_age_threshold(
    tmp_path, language, locale, expected
):
    data = json.loads(experiment_config().model_dump_json())
    data["generation"].update(language=language, locale=locale)
    protocol = new_protocol(ExperimentConfig.model_validate_json(json.dumps(data)))
    with Workspace.create(tmp_path, protocol) as workspace:
        result = generate_sources(workspace, provider=FamilyProvider())
        assert result.status == "complete", result.failures
        draft = build_reference(workspace)
        for intent in draft.intents:
            kind = intent.id.removeprefix(intent.family_id + "-")
            if kind in expected:
                first, *remaining = intent.entities
                assert tuple(query.text for query in intent.queries) == tuple(
                    text.format(first=first, second=remaining[0] if remaining else "")
                    for text in expected[kind]
                )
            assert not intent.reviews
            assert all(query.authorship == "template" for query in intent.queries)
        validate_reference(workspace, draft, release=False)
        with pytest.raises(InputError, match="Human review"):
            validate_reference(workspace, draft, release=True)


def test_fresh_families_generate_and_release_reviewed_evidence_without_old_runs(tmp_path):
    with fresh_workspace(tmp_path) as workspace:
        source = FamilyProvider()
        result = generate_sources(workspace, provider=source)
        assert result.status == "complete", result.failures
        assert result.usage is not None and result.usage["requests"] == 12
        assert (
            json.loads(Path(result.reports["run_summary"]).read_bytes())["usage"] == result.usage
        )
        documents, contents = sources(workspace)
        assert len(documents) == len(contents) == len(source.calls) == 12
        assert {document.format for document in documents} == {
            "pdf",
            "docx",
            "xlsx",
            "pptx",
            "html",
            "md",
        }
        assert len({document.family_id for document in documents}) == 2
        assert all(content.blueprint.required_fact_ids for content in contents)
        draft = build_reference(workspace)
        assert len(draft.intents) == 12
        assert sum(len(intent.queries) for intent in draft.intents) == 24
        assert len(draft.evidence) >= 24
        assert any(item.item_index is not None for item in draft.evidence)
        assert any(item.table_row is not None and item.column_id for item in draft.evidence)
        assert {claim.id for claim in draft.claims} == {item.claim_id for item in draft.evidence}
        fee_intent = draft.intents[0]
        second_only = documents[4]
        assert (
            next(item.grade for item in fee_intent.judgments if item.doc_id == second_only.id) == 0
        )
        with pytest.raises(InputError, match="review"):
            release_reference(workspace)
        released = approve_reference(workspace)
        forged = released.model_copy(
            update={
                "intents": tuple(
                    intent.model_copy(
                        update={
                            "reviews": tuple(
                                review.model_copy(update={"reviewer": "Forged " + review.reviewer})
                                for review in intent.reviews
                            )
                        }
                    )
                    for intent in released.intents
                )
            }
        )
        with pytest.raises(InputError, match="unaudited"):
            validate_reference(workspace, forged, release=True)
        assert released.status == "released"
        assert len((workspace.path / "qrels.trec").read_text().splitlines()) == 24 * 12
        resumed = generate_sources(workspace, provider=source)
        assert resumed.status == "complete"
        assert resumed.usage == result.usage
        assert (
            json.loads(Path(resumed.reports["run_summary"]).read_bytes())["usage"] == resumed.usage
        )
        assert len(source.calls) == 12


def test_stale_review_and_fabricated_evidence_are_rejected(tmp_path):
    with fresh_workspace(tmp_path) as workspace:
        assert generate_sources(workspace, provider=FamilyProvider()).status == "complete"
        draft = build_reference(workspace)
        changed = draft.model_copy(update={"evidence": draft.evidence[:-1]})
        with pytest.raises(IntegrityError, match="evidence"):
            validate_reference(workspace, changed, release=False)
        released = approve_reference(workspace)
        intent = released.intents[0]
        altered = intent.model_copy(
            update={
                "queries": (
                    intent.queries[0].model_copy(
                        update={"text": intent.queries[0].text + " Extra."}
                    ),
                    *intent.queries[1:],
                ),
            }
        )
        changed = released.model_copy(update={"intents": (altered, *released.intents[1:])})
        with pytest.raises(InputError, match="stale"):
            validate_reference(workspace, changed, release=True)


def test_state_reuses_confirmed_requests_and_preserves_budget_counters(tmp_path):
    with fresh_workspace(tmp_path) as workspace:
        calls = []

        def request():
            calls.append(1)
            return RemoteValue(data={"vector": [1, 2, 3]}, tokens=10)

        first = workspace.invoke("embedding", "q-one", request, fingerprint="same")
        assert workspace.invoke("embedding", "q-one", request, fingerprint="same") == first
        assert calls == [1]
        assert workspace.usage()["observed_embedding_tokens"] == 10
        with pytest.raises(IntegrityError, match="fingerprint"):
            workspace.invoke("embedding", "q-one", request, fingerprint="changed")
        directory = workspace.path
        with workspace.database:
            workspace.database.execute(
                "INSERT INTO attempts(kind,tag,status) VALUES ('embedding','unknown','in_flight')"
            )
    with Workspace(directory) as workspace:
        assert workspace.usage()["embedding_usage_unknown"] == 1
        assert (
            workspace.database.execute(
                "SELECT status FROM attempts WHERE tag='unknown'"
            ).fetchone()[0]
            == "unknown"
        )
        assert json.loads((directory / "protocol.json").read_text())["id"] == workspace.protocol.id


def test_nonretryable_remote_error_is_recorded_without_success_cache(tmp_path):
    with fresh_workspace(tmp_path) as workspace:

        def denied():
            raise ProviderError("authorization", "Access denied.")

        with pytest.raises(ProviderError, match="denied"):
            workspace.invoke("search", "denied", denied, fingerprint="fixed")
        assert workspace.get("remote:denied") is None
        assert workspace.usage()["attempts"]["search"] == 1
