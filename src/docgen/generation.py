from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial

from azure.core.credentials import TokenCredential
from pydantic import JsonValue, ValidationError

from docgen.budgets import effective_generation
from docgen.composition import compose
from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.execution import Execution
from docgen.families import family_for, scoped_facts
from docgen.models import Blueprint, Content, serialize
from docgen.persistence import atomic_write, safe_child
from docgen.planning import semantic_fingerprint
from docgen.prompts import author_prompt
from docgen.providers.azure import AzureProvider, DraftResponse
from docgen.providers.base import ContentProvider
from docgen.quality import Acceptance
from docgen.results import Result
from docgen.store import RunStatus, RunStore
from docgen.structures import structure_details
from docgen.wire import fact_bound_draft_schema
from docgen.word_budgets import content_length_details


@dataclass(frozen=True)
class CandidateOutcome:
    content_id: str
    content: Content | None
    failure: dict[str, JsonValue] | None = None
    terminal: bool = False


def _tracked[T: (Content, DraftResponse)](
    store: RunStore,
    content_id: str,
    call: Callable[[], T],
    attempts: list[str],
) -> T:
    attempt_id = store.begin_attempt(content_id)
    attempts.append(attempt_id)
    try:
        result = call()
    except ProviderError as error:
        store.finish_attempt(attempt_id, status="failed", usage=error.usage, error_code=error.code)
        raise
    except ValueError:
        store.finish_attempt(attempt_id, status="failed", error_code="invalid_candidate")
        raise ProviderError(
            "invalid_candidate", "Provider returned an invalid canonical candidate."
        ) from None
    atomic_write(
        safe_child(safe_child(store.directory, "attempts"), f"{attempt_id}.json"), serialize(result)
    )
    store.finish_attempt(attempt_id, status="succeeded", usage=result.usage)
    return result


def _message(error: ValueError) -> str:
    if isinstance(error, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in entry['loc'])}: {entry['msg']}"
            for entry in error.errors(include_input=False, include_url=False)
        )
    return str(error)


def _prior_rejections(
    store: RunStore, accepted: set[str],
) -> dict[str, dict[str, JsonValue]]:
    path = safe_child(safe_child(store.directory, "reports"), "content-quality.json")
    if not path.exists():
        return {}
    try:
        previous = Result.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise IntegrityError("Persisted generation rejection report is invalid.") from error
    if (
        previous.run_id != store.plan.run_id
        or previous.requested_count != len(store.plan.blueprints)
    ):
        raise IntegrityError("Persisted rejection report belongs to another generation plan.")
    planned = {blueprint.content_id for blueprint in store.plan.blueprints}
    result: dict[str, dict[str, JsonValue]] = {}
    for failure in previous.failures:
        if failure.get("code") not in (
            "quality_candidate", "quality_rejected", "invalid_json",
            "invalid_candidate", "schema_violation", "truncated",
        ):
            continue
        identifier, message = failure.get("content_id"), failure.get("message")
        if (
            not isinstance(identifier, str)
            or identifier not in planned
            or not isinstance(message, str)
            or not message
            or identifier in result
        ):
            raise IntegrityError("Persisted generation rejection context is invalid.")
        if identifier not in accepted:
            result[identifier] = failure
    return result


def generate_content(
    store: RunStore, *, provider: ContentProvider | None = None,
    credential: TokenCredential | None = None,
    candidate_validator: Callable[[Content], None] | None = None,
) -> Result:
    config = effective_generation(store)
    previous = store.contents()
    if (
        len(previous) != len(store.plan.blueprints)
        and candidate_validator is None
        and "authoring_inherited" in store.events()
    ):
        raise InputError(
            "Corrective authoring requires its experiment workspace and native acceptance gate."
        )
    if (
        len(previous) != len(store.plan.blueprints)
        and semantic_fingerprint(store.plan.effective_config) != store.plan.semantic_fingerprint
    ):
        raise InputError(
            "The authoring contract changed; start a new run instead of mixing prompt versions."
        )
    if provider is None and config.provider is None:
        raise InputError(
            "An Azure provider configuration or explicit content provider is required."
        )
    reported_models = {
        content.provenance.reported_model
        for content in previous
        if content.provenance.reported_model
    }
    model_versions = {
        content.provenance.model_version for content in previous if content.provenance.model_version
    }
    if len(reported_models) > 1 or len(model_versions) > 1:
        raise IntegrityError("Accepted content contains incompatible reported model versions.")
    gate = Acceptance(config, validator=candidate_validator)
    accepted = {content.blueprint.content_id for content in previous}
    for content in previous:
        gate.accept(content)
    attempts = store.attempts()
    execution = Execution(
        config,
        seed=store.plan.effective_config.seed,
        previous_requests=len(attempts),
        previous_tokens=sum(
            attempt.usage.total_tokens or 0 for attempt in attempts if attempt.usage
        ),
        previous_unknown=sum(
            attempt.usage is None or attempt.usage.total_tokens is None for attempt in attempts
        ),
    )
    failures = _prior_rejections(store, accepted)
    terminal: set[str] = set()
    cancelled = False
    store.set_status("generating")
    with ExitStack() as stack:
        azure = (
            stack.enter_context(
                AzureProvider(
                    config.provider,
                    limits=config.limits,
                    credential=credential,
                    expected_reported_model=next(iter(reported_models), None),
                    expected_model_version=next(iter(model_versions), None),
                )
            )
            if provider is None and config.provider is not None
            else None
        )

        def produce(blueprint: Blueprint) -> CandidateOutcome:
            attempt_ids: list[str] = []
            store.begin_candidate(blueprint.content_id)
            try:
                if azure is not None:
                    family = family_for(blueprint, config)
                    prompt = author_prompt(
                        blueprint,
                        config,
                        feedback=tuple(
                            str(failures[blueprint.content_id]["message"])
                            for _ in (0,)
                            if blueprint.content_id in failures
                        ),
                    )
                    request = (
                        partial(
                            azure.request, prompt,
                            schema=fact_bound_draft_schema(
                                scoped_facts(blueprint, config), structure=blueprint.structure_plan,
                            ),
                        )
                        if family is not None and family.domain == "saas"
                        else partial(azure.request, prompt)
                    )
                    response = execution.invoke(
                        lambda: _tracked(
                            store,
                            blueprint.content_id,
                            request,
                            attempt_ids,
                        )
                    )
                    candidate = compose(response, blueprint, config, attempt_id=attempt_ids[-1])
                else:
                    if provider is None:
                        raise InputError("A content provider is required.")
                    candidate = execution.invoke(
                        lambda: _tracked(
                            store,
                            blueprint.content_id,
                            lambda: provider.generate(blueprint, config),
                            attempt_ids,
                        )
                    )
                    candidate = Content.model_validate_json(candidate.model_dump_json())
                    candidate = candidate.model_copy(
                        update={
                            "provenance": candidate.provenance.model_copy(
                                update={"attempt_id": attempt_ids[-1]}
                            ),
                        }
                    )
                if candidate.blueprint != blueprint:
                    raise IntegrityError(
                        "Candidate blueprint does not match its planned blueprint."
                    )
                return CandidateOutcome(blueprint.content_id, candidate)
            except ProviderError as error:
                if error.code in {
                    "request_budget",
                    "token_budget",
                    "cancelled",
                    "authentication",
                    "authorization",
                    "deployment_not_found",
                    "unsupported_request",
                    "model_drift",
                    "connection",
                    "timeout",
                    "rate_limited",
                    "provider_unavailable",
                }:
                    execution.cancel()
                return CandidateOutcome(
                    blueprint.content_id,
                    None,
                    {
                        "code": error.code,
                        "phase": "generation",
                        "content_id": blueprint.content_id,
                        "retryable": error.retryable,
                        "message": str(error),
                    },
                    terminal=error.code
                    not in {
                        "truncated",
                        "invalid_json",
                        "invalid_candidate",
                        "schema_violation",
                    },
                )
            except ValueError as error:
                return CandidateOutcome(
                    blueprint.content_id,
                    None,
                    {
                        "code": "quality_candidate",
                        "phase": "generation",
                        "content_id": blueprint.content_id,
                        "retryable": True,
                        "message": _message(error),
                    },
                )

        try:
            while True:
                pending = [
                    blueprint
                    for blueprint in store.plan.blueprints
                    if blueprint.content_id not in accepted | terminal
                    and store.candidate_count(blueprint.content_id)
                    < config.quality.max_candidates_per_item
                ]
                if not pending:
                    break
                for outcome in execution.ordered(
                    partial(produce, blueprint) for blueprint in pending
                ):
                    if outcome.content is not None:
                        try:
                            verified = gate.accept(outcome.content)
                        except ValueError as error:
                            failures[outcome.content_id] = {
                                "code": "quality_rejected",
                                "phase": "generation",
                                "content_id": outcome.content_id,
                                "retryable": True,
                                "message": _message(error),
                            }
                            store.record_rejection(outcome.content_id)
                        else:
                            store.accept(verified)
                            accepted.add(outcome.content_id)
                            failures.pop(outcome.content_id, None)
                    elif outcome.failure is not None:
                        failures[outcome.content_id] = outcome.failure
                        store.record_rejection(outcome.content_id)
                        if outcome.terminal:
                            terminal.add(outcome.content_id)
                if execution.stopped or execution.request_count >= config.request_limit:
                    break
        except KeyboardInterrupt:
            execution.cancel()
            cancelled = True
        except IntegrityError:
            store.set_status("incomplete")
            raise
    for blueprint in store.plan.blueprints:
        if blueprint.content_id not in accepted and blueprint.content_id not in failures:
            failures[blueprint.content_id] = {
                "code": "cancelled" if cancelled else "candidate_limit",
                "phase": "generation",
                "content_id": blueprint.content_id,
                "retryable": False,
                "message": "Slot unfinished; inspect candidate and request budgets.",
            }
    status: RunStatus = (
        "cancelled"
        if cancelled
        else ("content_ready" if len(accepted) == config.count else "incomplete")
    )
    store.set_status(status)
    result = Result(
        run_id=store.plan.run_id,
        operation=store.plan.operation,
        status=status,
        requested_count=config.count,
        accepted_count=len(accepted),
        failures=tuple(failures[key] for key in sorted(failures)),
        usage=execution.summary(),
        reports={"content_quality": str(store.directory / "reports" / "content-quality.json")},
        details={
            "candidate_counts": {
                blueprint.content_id: store.candidate_count(blueprint.content_id)
                for blueprint in store.plan.blueprints
            },
            "candidate_limit": config.quality.max_candidates_per_item,
            "exhausted_content_ids": [
                blueprint.content_id for blueprint in store.plan.blueprints
                if blueprint.content_id not in accepted
                and store.candidate_count(blueprint.content_id)
                >= config.quality.max_candidates_per_item
            ],
            **(
                {"length": content_length_details(
                    store.contents(), config.quality.word_band_tolerance,
                )}
                if config.quality.word_band_tolerance is not None
                or config.structure is not None and config.structure.length_aware else {}
            ),
            **(
                {
                    "structure": {
                        "planned": structure_details(store.plan.blueprints),
                        "accepted": structure_details(tuple(
                            content.blueprint for content in store.contents()
                        )),
                    },
                }
                if config.structure is not None else {}
            ),
        },
    )
    atomic_write(
        safe_child(safe_child(store.directory, "reports"), "content-quality.json"),
        serialize(result),
        overwrite=True,
    )
    return result
