import hashlib
import json
import time
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Annotated, Literal, Self

import httpx
from azure.core.credentials import TokenCredential
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential, get_bearer_token_provider
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from docgen.config import ProviderConfig
from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.sectioning import (
    SectionPlan,
    SectionSource,
    chunk_sections,
    heading_plan,
    literal_label,
    markdown_source,
    materialize_sections,
    parse_section_plan,
    planner_request,
    single_section_plan,
)
from docgen.models import Record, Text
from docgen.persistence import atomic_write, safe_child
from docgen.providers.azure import reject_constant, unique_pairs
from docgen.tokenization import token_count


class SectionTrialSettings(Record):
    base_url: Text | None = None
    deployment: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")] | None = None
    subscription: Annotated[str, Field(
        pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
    )] | None = None
    sample_size: Annotated[StrictInt, Field(ge=1, le=24)] = 12
    seed: StrictInt = 42
    max_input_tokens: Annotated[StrictInt, Field(ge=1024, le=32000)] = 12000
    max_completion_tokens: Annotated[StrictInt, Field(ge=256, le=4096)] = 2048
    max_observed_total_tokens: Annotated[StrictInt, Field(ge=1, le=1000000)] = 100000
    max_chunk_characters: Annotated[StrictInt, Field(ge=128, le=20000)] = 2000
    timeout_seconds: Annotated[StrictInt, Field(ge=1, le=120)] = 30

    @field_validator("base_url")
    @classmethod
    def safe_endpoint(cls, value: str | None) -> str | None:
        return ProviderConfig.azure_https_only(value) if value is not None else None


class ChatUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt_tokens: Annotated[StrictInt, Field(ge=0)]
    completion_tokens: Annotated[StrictInt, Field(ge=0)]
    total_tokens: Annotated[StrictInt, Field(ge=0)]

    @model_validator(mode="after")
    def consistent_totals(self) -> Self:
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError("Provider token totals are inconsistent.")
        return self


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Literal["assistant"]
    content: StrictStr | None
    refusal: StrictStr | None = None


class ChatChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: ChatMessage
    finish_reason: StrictStr


class ChatEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Text
    model: Text
    choices: Annotated[tuple[ChatChoice, ...], Field(min_length=1, max_length=1)]
    usage: ChatUsage


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _save(path: Path, value: object) -> None:
    atomic_write(path, _json_bytes(value))


def _plain_path(path: Path) -> None:
    if any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)):
        raise IntegrityError("Filesystem links are forbidden in local section-trial inputs/output.")


def select_markdown_sources(
    source: Path, *, sample_size: int, seed: int,
) -> tuple[Path, ...]:
    if type(sample_size) is not int or not 1 <= sample_size <= 24 or type(seed) is not int:
        raise InputError("Local section trials require an integer sample size in [1, 24] and seed.")
    source = source.absolute()
    _plain_path(source)
    if source.is_file():
        candidates = [source] if source.suffix.lower() == ".md" else []
    elif source.is_dir():
        candidates = [path for path in source.iterdir() if path.suffix.lower() == ".md"]
    else:
        raise InputError("The local section-trial source does not exist.")
    for path in candidates:
        _plain_path(path)
        if not path.is_file():
            raise InputError("A Markdown source selector is not a regular file.")
    if len(candidates) < sample_size:
        raise InputError("The source has fewer raw Markdown files than the requested sample size.")
    return tuple(sorted(candidates, key=lambda path: (
        hashlib.sha256(f"{seed}\0{path.name}".encode()).hexdigest(), path.name,
    ))[:sample_size])


def _treatment(
    source: SectionSource, plan: SectionPlan, *, settings: SectionTrialSettings,
    include_metadata: bool,
) -> dict[str, object]:
    sections = materialize_sections(source, plan)
    chunks = chunk_sections(source, plan, max_characters=settings.max_chunk_characters)
    return {
        "title": (
            literal_label(source, plan.title_block)
            if include_metadata and plan.title_block is not None else None
        ),
        "section_metadata_enabled": include_metadata,
        "sections": [section.model_dump(mode="json") for section in sections],
        "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
        "section_count": len(sections), "chunk_count": len(chunks),
        "max_chunk_characters": max(len(chunk.text) for chunk in chunks),
        "exact_source_coverage": "".join(chunk.text for chunk in chunks) == source.text,
        "overlap_characters": 0,
    }


def _model_response(
    response: httpx.Response,
) -> ChatEnvelope:
    if response.status_code != 200:
        code = {
            401: "authentication", 403: "authorization", 404: "deployment_not_found",
            429: "rate_limited",
        }.get(response.status_code, "provider_unavailable")
        raise ProviderError(
            code, f"Azure section planning failed (HTTP {response.status_code}).",
            retryable=False,
        )
    try:
        decoded = json.loads(
            response.content, object_pairs_hook=unique_pairs, parse_constant=reject_constant,
        )
        return ChatEnvelope.model_validate(decoded)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ProviderError(
            "invalid_response", "Azure returned an invalid section-planner response or usage."
        ) from exc


def run_section_trial(
    source_path: Path, output_path: Path, settings: SectionTrialSettings, *, live: bool = False,
    credential: TokenCredential | None = None, http_client: httpx.Client | None = None,
) -> dict[str, object]:
    settings = SectionTrialSettings.model_validate(settings.model_dump())
    if type(live) is not bool:
        raise InputError("Live section planning requires an explicit Boolean authorization.")
    if live and any(value is None for value in (
        settings.base_url, settings.deployment, settings.subscription,
    )):
        raise InputError(
            "Live trials require an explicit Azure endpoint, deployment and subscription."
        )
    if http_client is not None and http_client.follow_redirects:
        raise InputError("Section-planner HTTP clients must not follow redirects.")
    selected = select_markdown_sources(
        source_path, sample_size=settings.sample_size, seed=settings.seed,
    )
    prepared: list[tuple[Path, bytes, SectionSource, dict[str, object], dict[str, object]]] = []
    for path in selected:
        if path.stat().st_size > 800000:
            raise InputError("A selected raw Markdown source exceeds the 800000-byte trial limit.")
        raw = path.read_bytes()
        try:
            source = markdown_source(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise InputError("Raw Markdown trial inputs must be valid UTF-8.") from exc
        baseline = _treatment(
            source, single_section_plan(source), settings=settings, include_metadata=False,
        )
        native = _treatment(
            source, heading_plan(source), settings=settings, include_metadata=True,
        )
        prepared.append((path, raw, source, baseline, native))
    output_path = output_path.absolute()
    _plain_path(output_path)
    if output_path == source_path.absolute() or output_path.is_relative_to(source_path.absolute()):
        raise InputError("Local trial output must be outside the raw source directory.")
    output_path.mkdir(parents=True, exist_ok=True)
    trial_path = safe_child(output_path, "section-trial-" + uuid.uuid4().hex)
    trial_path.mkdir()
    manifest = {
        "schema_version": 1, "scope": "local-only-raw-markdown-prototype",
        "planner_contract_version": 2,
        "treatment_contract_version": 2,
        "live_model_authorized": live, "settings": settings.model_dump(mode="json"),
        "search_pipeline_integration": "not_executed", "retrieval_quality": "not_measured",
        "azure_resources_created": False, "source_metadata_uploaded": False,
        "input_feature_policy": "raw_source_text_and_native_markdown_structure_only",
        "input_token_estimate": "cl100k_base_of_full_request_plus_1024_reservation",
        "attempt_cap": len(selected), "automatic_retries": 0,
        "sources": [{
            "ordinal": index, "original_path": str(path),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "text_sha256": source.sha256, "raw_byte_count": len(raw),
        } for index, (path, raw, source, _, _) in enumerate(prepared)],
    }
    _save(safe_child(trial_path, "trial.json"), manifest)
    outcomes: list[dict[str, object]] = []
    attempts = 0
    observed_tokens = 0
    unknown_usage_attempts = 0
    blocked_reason: str | None = None
    model_identity: tuple[str, str | None] | None = None
    with ExitStack() as stack:
        token: Callable[[], str] | None = None
        client = http_client
        if live:
            selected_credential = credential
            if selected_credential is None:
                selected_credential = stack.enter_context(AzureCliCredential(
                    subscription=settings.subscription, process_timeout=60,
                ))
            token = get_bearer_token_provider(
                selected_credential, "https://cognitiveservices.azure.com/.default",
            )
            if client is None:
                client = stack.enter_context(httpx.Client(follow_redirects=False))
        for index, (path, raw, source, baseline, native) in enumerate(prepared):
            document_path = safe_child(trial_path, f"document-{index:04d}")
            document_path.mkdir()
            atomic_write(safe_child(document_path, "source.md"), raw)
            _save(safe_child(document_path, "source.json"), source.model_dump(mode="json"))
            _save(safe_child(document_path, "controls.json"), {
                "baseline": baseline, "native_headings": native,
            })
            request = planner_request(
                source, deployment=settings.deployment or "not-configured",
                max_completion_tokens=settings.max_completion_tokens,
            )
            _save(safe_child(document_path, "planner-request.json"), request)
            outcome: dict[str, object] = {
                "ordinal": index, "source_sha256": source.sha256, "source_name": path.name,
                "baseline_chunks": baseline["chunk_count"],
                "native_sections": native["section_count"],
                "native_chunks": native["chunk_count"], "status": "not_dispatched",
                "reason": "offline_control" if not live else blocked_reason,
            }
            outcomes.append(outcome)
            if not live or blocked_reason is not None:
                _save(safe_child(document_path, "outcome.json"), outcome)
                continue
            estimated_tokens = token_count(_json_bytes(request).decode("utf-8")) + 1024
            if estimated_tokens > settings.max_input_tokens:
                outcome.update(status="rejected_input", reason="input_token_limit")
                _save(safe_child(document_path, "outcome.json"), outcome)
                continue
            if (
                observed_tokens + estimated_tokens + settings.max_completion_tokens
                > settings.max_observed_total_tokens
            ):
                blocked_reason = "token_budget"
                outcome["reason"] = blocked_reason
                _save(safe_child(document_path, "outcome.json"), outcome)
                continue
            if client is None or token is None or settings.base_url is None:
                raise IntegrityError("The authorized local planner has no HTTP/token binding.")
            try:
                bearer = token()
            except ClientAuthenticationError:
                outcome.update(status="failed", reason="authentication")
                blocked_reason = "authentication"
                _save(safe_child(document_path, "outcome.json"), outcome)
                continue
            attempts += 1
            _save(safe_child(document_path, "attempt-intent.json"), {
                "attempt": attempts, "endpoint": settings.base_url + "chat/completions",
                "request_sha256": hashlib.sha256(_json_bytes(request)).hexdigest(),
                "estimated_input_tokens_with_reservation": estimated_tokens,
                "max_completion_tokens": settings.max_completion_tokens,
                "status_if_no_outcome": "unknown_do_not_retry_automatically",
            })
            outcome.update(status="in_flight", reason=None)
            started = time.monotonic()
            usage_recorded = False
            try:
                response = client.post(
                    settings.base_url + "chat/completions", json=request,
                    headers={"Authorization": "Bearer " + bearer},
                    timeout=settings.timeout_seconds,
                )
                atomic_write(safe_child(document_path, "response-body.json"), response.content)
                _save(safe_child(document_path, "response-metadata.json"), {
                    "status_code": response.status_code,
                    "request_id": (
                        response.headers.get("x-request-id")
                        or response.headers.get("apim-request-id")
                    ),
                    "model_version": response.headers.get("x-ms-model-version"),
                })
                envelope = _model_response(response)
                observed_tokens += envelope.usage.total_tokens
                usage_recorded = True
                outcome["usage"] = envelope.usage.model_dump(mode="json")
                outcome["reported_model"] = envelope.model
                identity = (envelope.model, response.headers.get("x-ms-model-version"))
                if model_identity is not None and model_identity != identity:
                    raise ProviderError(
                        "model_drift", "The planner model/version changed mid-trial."
                    )
                model_identity = identity
                if observed_tokens > settings.max_observed_total_tokens:
                    raise ProviderError(
                        "token_budget", "Observed planner tokens exceed the trial cap."
                    )
                choice = envelope.choices[0]
                if choice.message.refusal is not None:
                    raise ProviderError("refusal", "The planner refused the supplied source.")
                if choice.finish_reason != "stop" or not choice.message.content:
                    raise ProviderError(
                        "incomplete_response", "The planner did not complete its structured output."
                    )
                plan = parse_section_plan(choice.message.content, source)
                llm_sections = _treatment(
                    source, plan, settings=settings, include_metadata=False,
                )
                combined = _treatment(source, plan, settings=settings, include_metadata=True)
                metadata = dict(baseline)
                metadata["title"] = combined["title"]
                _save(safe_child(document_path, "accepted-plan.json"), plan.model_dump(mode="json"))
                _save(safe_child(document_path, "llm-treatments.json"), {
                    "metadata_only": metadata, "sections_only": llm_sections,
                    "metadata_and_sections": combined,
                })
                outcome.update(
                    status="accepted", reason=None, llm_sections=len(plan.sections),
                    llm_chunks=combined["chunk_count"], title=combined["title"],
                    exact_source_coverage=combined["exact_source_coverage"],
                )
            except httpx.TransportError:
                outcome.update(status="failed", reason="transport_unknown_outcome")
                blocked_reason = "transport_unknown_outcome"
            except ProviderError as exc:
                outcome.update(status="failed", reason=exc.code)
                blocked_reason = exc.code
            except (IntegrityError, InputError) as exc:
                outcome.update(status="rejected_output", reason=str(exc))
            finally:
                if outcome["status"] == "in_flight":
                    outcome.update(status="unknown", reason="interrupted_after_dispatch")
                if not usage_recorded:
                    unknown_usage_attempts += 1
                    blocked_reason = blocked_reason or "unknown_provider_usage"
                outcome["elapsed_seconds"] = time.monotonic() - started
                _save(safe_child(document_path, "outcome.json"), outcome)
    accepted = sum(outcome["status"] == "accepted" for outcome in outcomes)
    summary: dict[str, object] = {
        "schema_version": 1, "scope": manifest["scope"], "trial_path": str(trial_path),
        "status": "complete" if live and accepted == len(selected) else (
            "ready" if not live else "incomplete"
        ),
        "source_count": len(selected), "accepted_model_plans": accepted,
        "attempts": attempts, "observed_total_tokens": observed_tokens,
        "unknown_usage_attempts": unknown_usage_attempts, "blocked_reason": blocked_reason,
        "search_pipeline_integration": "not_executed", "retrieval_quality": "not_measured",
        "human_review_certified": False, "outcomes": outcomes,
    }
    _save(safe_child(trial_path, "summary.json"), summary)
    return summary
