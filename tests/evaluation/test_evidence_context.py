import pytest
from pydantic import ValidationError

from docgen.errors import InputError, IntegrityError
from docgen.evaluation.evidence import (
    ChunkSupportAssessment,
    EvidenceAssessment,
    citation_aliases,
    evidence_context,
    exposed_chunk_texts,
    resolve_assessment_citations,
    resolve_chunk_support,
    validate_assessment,
)
from docgen.evaluation.models import Chunk, Ranking, Snapshot


def example_snapshot():
    digest = "a" * 64
    texts = ("Conta A custa\n10 BRL.", "Conta B custa 20 BRL.", "Fim.")
    return Snapshot(
        protocol_id="experiment-one", arm="de_split", source_hash=digest,
        resource_hash=digest, reference_hash=digest, execution_hash=digest, blob_hash=digest,
        chunks=tuple(
            Chunk(
                id=f"chunk-{index}", parent_id=f"parent-{index}", doc_id=f"item-{index}",
                content=text, text_hash=digest, vector_hash=digest,
            )
            for index, text in enumerate(texts)
        ),
    )


def example_ranking():
    return Ranking(
        arm="de_split", query_id="query-one", status="succeeded",
        chunk_ids=("chunk-0", "chunk-1", "chunk-2"), scores=(3, 2, 1), elapsed_ms=1,
    )


def assessment(citation):
    return EvidenceAssessment(
        claims=({
            "claim_id": "fee-a", "status": "supported",
            "citations": [citation], "reason": "Literal source price.",
        },),
        answer_status="correct", answer_reason="Price matches.", human_review_certified=False,
    )


def test_context_uses_only_a_ranked_whole_chunk_prefix_and_counts_wrappers():
    snapshot = example_snapshot()
    context = evidence_context(
        example_ranking(), snapshot, token_budget=45, count_tokens=len,
    )
    assert context.chunk_ids == ("chunk-0",)
    assert context.stopped_before_chunk == "chunk-1"
    assert context.text == "[chunk:chunk-0]\nConta A custa\n10 BRL."
    assert context.tokens == len(context.text) <= 45
    assert "Fim." not in context.text


def test_first_chunk_overflow_is_explicit_and_does_not_skip_to_a_shorter_chunk():
    context = evidence_context(
        example_ranking(), example_snapshot(), token_budget=10, count_tokens=len,
    )
    assert context.text == "" and context.chunk_ids == () and context.tokens == 0
    assert context.stopped_before_chunk == "chunk-0"


@pytest.mark.parametrize("budget", [True, 0, 65537])
def test_invalid_context_budgets_fail_explicitly(budget):
    with pytest.raises(InputError, match="budget"):
        evidence_context(example_ranking(), example_snapshot(), token_budget=budget)


def test_foreign_chunk_ids_and_invalid_tokenizer_values_fail_explicitly():
    ranking = example_ranking().model_copy(update={"chunk_ids": ("missing",)})
    with pytest.raises(IntegrityError, match="unknown"):
        evidence_context(ranking, example_snapshot())
    with pytest.raises(InputError, match="tokenizer"):
        evidence_context(example_ranking(), example_snapshot(), count_tokens=lambda _: True)


def test_assessment_accepts_whitespace_only_grounding_and_requires_every_claim():
    snapshot = example_snapshot()
    context = evidence_context(example_ranking(), snapshot, count_tokens=len)
    result = assessment({"chunk_id": "chunk-0", "quote": "Conta A custa 10 BRL."})
    validate_assessment(result, context, snapshot, ("fee-a",))
    with pytest.raises(IntegrityError, match="every required"):
        validate_assessment(result, context, snapshot, ("fee-a", "fee-b"))


@pytest.mark.parametrize(
    "citation",
    [
        {"chunk_id": "chunk-0", "quote": "Conta A custa 30 BRL."},
        {"chunk_id": "chunk-1", "quote": "Conta B custa 20 BRL."},
        {"chunk_id": "missing", "quote": "Conta A custa 10 BRL."},
    ],
)
def test_assessment_rejects_inferred_quotes_and_unexposed_chunk_citations(citation):
    snapshot = example_snapshot()
    context = evidence_context(
        example_ranking(), snapshot, token_budget=45, count_tokens=len,
    )
    with pytest.raises(IntegrityError, match="literal exposed"):
        validate_assessment(assessment(citation), context, snapshot, ("fee-a",))


def test_supported_claims_cannot_omit_evidence_or_certify_human_review():
    data = assessment({"chunk_id": "chunk-0", "quote": "10 BRL."}).model_dump(mode="json")
    data["claims"][0]["citations"] = []
    with pytest.raises(ValidationError, match="literal"):
        EvidenceAssessment.model_validate(data)
    data = assessment({"chunk_id": "chunk-0", "quote": "10 BRL."}).model_dump(mode="json")
    data["human_review_certified"] = True
    with pytest.raises(ValidationError):
        EvidenceAssessment.model_validate(data)


def test_assessment_rejects_text_that_does_not_match_the_declared_exposed_chunks():
    snapshot = example_snapshot()
    context = evidence_context(example_ranking(), snapshot, count_tokens=len)
    changed = context.model_copy(update={"text": "A different context was exposed."})
    result = assessment({"chunk_id": "chunk-0", "quote": "Conta A custa 10 BRL."})
    with pytest.raises(IntegrityError, match="exposed context"):
        validate_assessment(result, changed, snapshot, ("fee-a",))


def test_short_citation_aliases_preserve_exact_exposure_and_literal_quotes():
    snapshot = example_snapshot()
    context = evidence_context(
        example_ranking(), snapshot, token_budget=45, count_tokens=len,
    )
    assert citation_aliases(context) == {"c1": "chunk-0"}
    original = assessment({"chunk_id": "c1", "quote": "Conta A custa 10 BRL."})
    resolved = resolve_assessment_citations(original, context)
    assert resolved.claims[0].citations[0].chunk_id == "chunk-0"
    assert resolved.claims[0].citations[0].quote == original.claims[0].citations[0].quote
    assert original.claims[0].citations[0].chunk_id == "c1"
    validate_assessment(resolved, context, snapshot, ("fee-a",))


@pytest.mark.parametrize("identifier", ["c2", "chunk-0", "inferred-citation"])
def test_unknown_or_unexposed_aliases_cannot_be_fuzzily_repaired(identifier):
    context = evidence_context(
        example_ranking(), example_snapshot(), token_budget=45, count_tokens=len,
    )
    result = assessment({"chunk_id": identifier, "quote": "Conta A custa 10 BRL."})
    with pytest.raises(IntegrityError, match="unknown citation alias"):
        resolve_assessment_citations(result, context)


def test_alias_resolution_does_not_relax_quote_grounding():
    snapshot = example_snapshot()
    context = evidence_context(example_ranking(), snapshot, count_tokens=len)
    result = resolve_assessment_citations(
        assessment({"chunk_id": "c1", "quote": "Conta A custa 30 BRL."}), context,
    )
    with pytest.raises(IntegrityError, match="literal exposed"):
        validate_assessment(result, context, snapshot, ("fee-a",))


def chunk_assessment(identifiers):
    return ChunkSupportAssessment(
        claims=({
            "claim_id": "fee-a", "status": "supported", "supporting_chunks": identifiers,
            "reason": "The exposed chunk binds the account to its price.",
        },),
        answer_status="correct", answer_reason="Price matches.", human_review_certified=False,
    )


def test_chunk_support_uses_only_exact_complete_exposed_source_text():
    snapshot = example_snapshot()
    context = evidence_context(
        example_ranking(), snapshot, token_budget=45, count_tokens=len,
    )
    assert exposed_chunk_texts(context, snapshot) == {"c1": "Conta A custa\n10 BRL."}
    result = resolve_chunk_support(chunk_assessment(("c1",)), context, snapshot)
    assert result.claims[0].citations[0].quote == snapshot.chunks[0].content
    assert result.claims[0].citations[0].chunk_id == "chunk-0"
    validate_assessment(result, context, snapshot, ("fee-a",))


@pytest.mark.parametrize("identifiers", [(), ("c1", "c1")])
def test_supported_chunk_assessments_require_unique_nonempty_identifiers(identifiers):
    with pytest.raises(ValidationError):
        chunk_assessment(identifiers)


def test_chunk_support_never_maps_unknown_or_unexposed_chunk_ids():
    snapshot = example_snapshot()
    context = evidence_context(
        example_ranking(), snapshot, token_budget=45, count_tokens=len,
    )
    with pytest.raises(IntegrityError, match="unknown supporting"):
        resolve_chunk_support(chunk_assessment(("c2",)), context, snapshot)
