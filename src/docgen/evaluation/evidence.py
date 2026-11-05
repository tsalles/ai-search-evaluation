import unicodedata
from collections.abc import Callable, Collection
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, model_validator

from docgen.errors import InputError, IntegrityError
from docgen.evaluation.models import Chunk, Digest, Ranking, Snapshot
from docgen.evaluation.runner import token_count
from docgen.models import Identifier, Record, Text


class EvidenceContext(Record):
    text: str
    chunk_ids: tuple[Text, ...]
    snapshot_hash: Digest
    tokens: Annotated[StrictInt, Field(ge=0)]
    token_budget: Annotated[StrictInt, Field(ge=1, le=65536)]
    stopped_before_chunk: Text | None


class ContextCitation(Record):
    chunk_id: Text
    quote: Annotated[str, Field(strict=True, min_length=1, max_length=20000)]


class ClaimAssessment(Record):
    claim_id: Identifier
    status: Literal["supported", "not_supported", "uncertain"]
    citations: Annotated[tuple[ContextCitation, ...], Field(max_length=8)]
    reason: Text

    @model_validator(mode="after")
    def supported_claim_has_evidence(self) -> Self:
        if self.status == "supported" and not self.citations:
            raise ValueError("A supported claim requires a literal context citation.")
        return self


class EvidenceAssessment(Record):
    claims: Annotated[tuple[ClaimAssessment, ...], Field(min_length=1, max_length=10)]
    answer_status: Literal["correct", "incorrect", "abstained", "uncertain"]
    answer_reason: Text
    human_review_certified: Literal[False]


class ContextAnswer(Record):
    answer: Annotated[str, Field(strict=True, min_length=1, max_length=20000)]
    abstained: StrictBool


class ClaimChunkSupport(Record):
    claim_id: Identifier
    status: Literal["supported", "not_supported", "uncertain"]
    supporting_chunks: Annotated[tuple[Identifier, ...], Field(max_length=8)]
    reason: Text

    @model_validator(mode="after")
    def valid_supporting_chunks(self) -> Self:
        if self.status == "supported" and not self.supporting_chunks:
            raise ValueError("A supported claim requires an exposed chunk identifier.")
        if len(set(self.supporting_chunks)) != len(self.supporting_chunks):
            raise ValueError("Supporting chunk identifiers cannot repeat.")
        return self


class ChunkSupportAssessment(Record):
    claims: Annotated[tuple[ClaimChunkSupport, ...], Field(min_length=1, max_length=10)]
    answer_status: Literal["correct", "incorrect", "abstained", "uncertain"]
    answer_reason: Text
    human_review_certified: Literal[False]


def normalized_span(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def citation_aliases(context: EvidenceContext) -> dict[str, str]:
    return {
        f"c{index}": identifier for index, identifier in enumerate(context.chunk_ids, 1)
    }


def resolve_assessment_citations(
    assessment: EvidenceAssessment, context: EvidenceContext,
) -> EvidenceAssessment:
    aliases = citation_aliases(context)
    claims: list[ClaimAssessment] = []
    for claim in assessment.claims:
        citations: list[ContextCitation] = []
        for citation in claim.citations:
            if citation.chunk_id not in aliases:
                raise IntegrityError("Assessment uses an unknown citation alias.")
            citations.append(ContextCitation(
                chunk_id=aliases[citation.chunk_id], quote=citation.quote,
            ))
        claims.append(claim.model_copy(update={"citations": tuple(citations)}))
    return assessment.model_copy(update={"claims": tuple(claims)})


def evidence_context(
    ranking: Ranking, snapshot: Snapshot, *, token_budget: int = 4096,
    count_tokens: Callable[[str], int] = token_count,
) -> EvidenceContext:
    from docgen.evaluation.state import digest

    if type(token_budget) is not int or not 1 <= token_budget <= 65536:
        raise InputError("Evidence context token budget must be an integer in [1, 65536].")
    if ranking.status != "succeeded" or ranking.arm != snapshot.arm:
        raise InputError("Evidence context requires a successful ranking from this snapshot arm.")
    chunks = {chunk.id: chunk for chunk in snapshot.chunks}
    if len(set(ranking.chunk_ids)) != len(ranking.chunk_ids) or any(
        identifier not in chunks for identifier in ranking.chunk_ids
    ):
        raise IntegrityError("Evidence ranking contains duplicate or unknown chunks.")
    selected: list[str] = []
    frames: list[str] = []
    tokens = 0
    stopped: str | None = None
    for identifier in ranking.chunk_ids:
        frame = f"[chunk:{identifier}]\n{chunks[identifier].content}"
        candidate = "\n\n".join([*frames, frame])
        count = count_tokens(candidate)
        if type(count) is not int or count < 1:
            raise InputError("The tokenizer returned an invalid context length.")
        if count > token_budget:
            stopped = identifier
            break
        frames.append(frame)
        selected.append(identifier)
        tokens = count
    return EvidenceContext(
        text="\n\n".join(frames), chunk_ids=tuple(selected), snapshot_hash=digest(snapshot),
        tokens=tokens, token_budget=token_budget, stopped_before_chunk=stopped,
    )


def _exposed_chunks(context: EvidenceContext, snapshot: Snapshot) -> dict[str, Chunk]:
    from docgen.evaluation.state import digest

    if context.snapshot_hash != digest(snapshot):
        raise IntegrityError("Evidence context belongs to a different frozen snapshot.")
    chunks = {chunk.id: chunk for chunk in snapshot.chunks}
    if len(set(context.chunk_ids)) != len(context.chunk_ids) or any(
        identifier not in chunks for identifier in context.chunk_ids
    ):
        raise IntegrityError("Evidence context contains unknown chunks.")
    expected_text = "\n\n".join(
        f"[chunk:{identifier}]\n{chunks[identifier].content}"
        for identifier in context.chunk_ids
    )
    if context.text != expected_text:
        raise IntegrityError("The exposed context text differs from its declared native chunks.")
    return {identifier: chunks[identifier] for identifier in context.chunk_ids}


def exposed_chunk_texts(context: EvidenceContext, snapshot: Snapshot) -> dict[str, str]:
    chunks = _exposed_chunks(context, snapshot)
    return {
        alias: chunks[identifier].content for alias, identifier in citation_aliases(context).items()
    }


def resolve_chunk_support(
    assessment: ChunkSupportAssessment, context: EvidenceContext, snapshot: Snapshot,
) -> EvidenceAssessment:
    texts = exposed_chunk_texts(context, snapshot)
    aliases = citation_aliases(context)
    claims: list[ClaimAssessment] = []
    for claim in assessment.claims:
        if any(identifier not in aliases for identifier in claim.supporting_chunks):
            raise IntegrityError("Assessment uses an unknown supporting chunk alias.")
        claims.append(ClaimAssessment(
            claim_id=claim.claim_id, status=claim.status, reason=claim.reason,
            citations=tuple(
                ContextCitation(chunk_id=aliases[identifier], quote=texts[identifier])
                for identifier in claim.supporting_chunks
            ),
        ))
    return EvidenceAssessment(
        claims=tuple(claims), answer_status=assessment.answer_status,
        answer_reason=assessment.answer_reason, human_review_certified=False,
    )


def validate_assessment(
    assessment: EvidenceAssessment, context: EvidenceContext, snapshot: Snapshot,
    required_claims: Collection[str],
) -> None:
    chunks = _exposed_chunks(context, snapshot)
    ids = [claim.claim_id for claim in assessment.claims]
    if not required_claims or len(ids) != len(set(ids)) or set(ids) != set(required_claims):
        raise IntegrityError("Assessment must cover every required claim exactly once.")
    for claim in assessment.claims:
        for citation in claim.citations:
            quote = normalized_span(citation.quote)
            if (
                citation.chunk_id not in context.chunk_ids
                or not quote
                or quote not in normalized_span(chunks[citation.chunk_id].content)
            ):
                raise IntegrityError("Assessment citation is not literal exposed chunk evidence.")
