import base64
import hashlib
import json
from collections.abc import Callable
from typing import Annotated

from pydantic import Field, JsonValue, TypeAdapter, ValidationError

from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.section_trial import ChatEnvelope
from docgen.evaluation.sectioning import checked_section_row as checked_section_row
from docgen.evaluation.sectioning import (
    literal_label,
    markdown_source,
    materialize_sections,
    parse_section_plan,
    planner_request,
)
from docgen.models import Record, Usage
from docgen.providers.azure import reject_constant, unique_pairs
from docgen.tokenization import token_count


class SkillInput(Record):
    text: Annotated[str, Field(strict=True, min_length=1, max_length=200000)]
    source_path: Annotated[str, Field(strict=True, min_length=1, max_length=2048)]


class SkillRecord(Record):
    recordId: Annotated[str, Field(strict=True, min_length=1, max_length=256)]
    data: SkillInput


class SkillRequest(Record):
    values: Annotated[tuple[SkillRecord, ...], Field(min_length=1, max_length=1)]


class ModelResult(Record):
    content: Annotated[str, Field(strict=True, min_length=1)]
    model: Annotated[str, Field(strict=True, min_length=1, max_length=256)]
    request_key: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    audit_json: str | None = None


ModelCall = Callable[[dict[str, JsonValue]], ModelResult]


def canonical_request(request: dict[str, JsonValue]) -> bytes:
    return json.dumps(
        request, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
    ).encode("utf-8")


def model_result_from_response(
    raw: bytes, *, status_code: int, request_key: str,
) -> tuple[ModelResult, int]:
    if status_code != 200:
        raise ProviderError(
            "model_http_failure", f"Section model returned HTTP {status_code}.",
            retryable=status_code in {401, 403, 429},
        )
    try:
        envelope = ChatEnvelope.model_validate(json.loads(
            raw, object_pairs_hook=unique_pairs, parse_constant=reject_constant,
        ))
    except (ValueError, TypeError, RecursionError) as exc:
        raise ProviderError(
            "invalid_model_envelope", "Section model envelope or token usage is invalid."
        ) from exc
    choice = envelope.choices[0]
    if (
        choice.finish_reason != "stop" or choice.message.refusal is not None
        or not choice.message.content
    ):
        raise ProviderError(
            "incomplete_model_plan", "Section model did not complete its plan.",
            usage=Usage(
                input_tokens=envelope.usage.prompt_tokens,
                output_tokens=envelope.usage.completion_tokens,
                total_tokens=envelope.usage.total_tokens,
            ),
        )
    return ModelResult(
        content=choice.message.content, model=envelope.model, request_key=request_key,
        audit_json=json.dumps({
            "response_base64": base64.b64encode(raw).decode(),
            "prompt_tokens": envelope.usage.prompt_tokens,
            "completion_tokens": envelope.usage.completion_tokens,
            "total_tokens": envelope.usage.total_tokens,
        }, separators=(",", ":")),
    ), envelope.usage.total_tokens


def section_enrichment(
    text: str, *, deployment: str, model_call: ModelCall, max_input_tokens: int = 32000,
) -> dict[str, JsonValue]:
    source = markdown_source(text, split_extracted_paragraphs=True)
    request = TypeAdapter(dict[str, JsonValue]).validate_python(
        planner_request(source, deployment=deployment), strict=True,
    )
    if token_count(canonical_request(request).decode("utf-8")) + 1024 > max_input_tokens:
        raise InputError("Extracted document exceeds the section planner's input-token bound.")
    inferred = model_call(request)
    expected_key = hashlib.sha256(canonical_request(request)).hexdigest()
    if inferred.request_key != expected_key:
        raise IntegrityError("The model response is not bound to this exact planner request.")
    plan = parse_section_plan(inferred.content, source)
    sections = materialize_sections(source, plan)
    title = literal_label(source, plan.title_block) if plan.title_block is not None else None
    result: dict[str, JsonValue] = {
        "source_text": source.text,
        "sections": [{
            "text": section.text,
            "metadata": {
                "title": title, "heading": section.heading, "ordinal": section.ordinal,
                "section_count": len(sections), "source_start": section.start,
                "source_end": section.end, "source_sha256": source.sha256,
                "request_key": inferred.request_key, "model": inferred.model,
            },
        } for section in sections],
    }
    if inferred.audit_json is not None:
        result["model_audit"] = inferred.audit_json
    return result


def handle_skill_request(
    payload: object, *, deployment: str, model_call: ModelCall,
) -> dict[str, JsonValue]:
    try:
        request = SkillRequest.model_validate(payload)
    except ValidationError as exc:
        raise InputError("Custom skill requires one bounded text/source-path record.") from exc
    record = request.values[0]
    try:
        enrichment = section_enrichment(
            record.data.text, deployment=deployment, model_call=model_call,
        )
    except (InputError, IntegrityError, ProviderError) as exc:
        return {"values": [{
            "recordId": record.recordId, "data": {},
            "errors": [{"message": str(exc)}], "warnings": [],
        }]}
    return {"values": [{
        "recordId": record.recordId, "data": {"enrichment": enrichment},
        "errors": [], "warnings": [],
    }]}
