from pydantic import JsonValue

from docgen.budgets import BudgetOverride, budget_history, increase_budget
from docgen.errors import IntegrityError
from docgen.generation import generate_content
from docgen.persistence import safe_child
from docgen.providers.base import ContentProvider
from docgen.publication import load_ready
from docgen.quality import Acceptance
from docgen.rendering import render_content
from docgen.reports import corpus_structure_details, review_details
from docgen.results import Result
from docgen.store import RunStore
from docgen.validation import validate_set
from docgen.word_budgets import content_length_details


def stored_usage(store: RunStore) -> dict[str, JsonValue]:
    attempts = store.attempts()
    observed = sum(attempt.usage.total_tokens or 0 for attempt in attempts if attempt.usage)
    unknown = sum(
        attempt.usage is None or attempt.usage.total_tokens is None for attempt in attempts
    )
    return {
        "requests": len(attempts),
        "observed_total_tokens": observed,
        "total_tokens": None if unknown else observed,
        "unknown_outcomes": unknown,
    }


def resume_run(
    store: RunStore,
    *,
    provider: ContentProvider | None = None,
    budget_override: BudgetOverride | None = None,
) -> Result:
    if budget_override is not None:
        increase_budget(store, budget_override)
    allocation = store.read_allocation()
    operation = store.plan.operation
    if allocation is not None:
        result = render_content(store, allocation.config)
    else:
        accepted = len(store.contents())
        if accepted == len(store.plan.blueprints):
            result = Result(
                run_id=store.plan.run_id,
                operation=operation,
                status="content_ready",
                requested_count=accepted,
                accepted_count=accepted,
                usage=stored_usage(store),
            )
        else:
            result = generate_content(store, provider=provider)
        if operation == "run" and result.status == "content_ready":
            rendering = store.plan.effective_config.rendering
            if rendering is None:
                raise IntegrityError(
                    "Combined run is missing its original rendering configuration."
                )
            result = render_content(store, rendering)
    return Result.model_validate(
        {
            **result.model_dump(),
            "operation": "run" if operation == "run" else result.operation,
            "usage": stored_usage(store),
            "details": {
                **result.details,
                "budget_history": [
                    entry.model_dump(mode="json") for entry in budget_history(store)
                ],
            },
        }
    )


def validate_run(store: RunStore) -> Result:
    contents = store.contents()
    corpus = safe_child(store.directory, "corpus")
    allocation = store.read_allocation()
    failures: list[dict[str, JsonValue]] = []
    scope = "content"
    verified = 0
    verified_ids: set[str] = set()
    generation = store.plan.effective_config.generation
    if corpus.exists():
        if allocation is None or load_ready(store, allocation) is None:
            raise IntegrityError("Published corpus is missing its immutable ready metadata.")
        scope = "corpus"
        states = store.rendered_states()
        report = validate_set(
            corpus,
            contents,
            allocation,
            expected_hashes={
                key: value.hash for key, value in states.items() if value.hash is not None
            },
        )
        verified = report.verified_count
        verified_ids = {item.content_id for item in report.artifacts if item.valid}
        if not report.valid:
            failures.append(
                {
                    "code": "corpus_validation",
                    "phase": "validate",
                    "retryable": False,
                    "message": (
                        "Published corpus differs from source, native structure, or checksums."
                    ),
                }
            )
    else:
        config = store.plan.effective_config.generation
        if config is None:
            raise IntegrityError("Content validation requires the saved generation configuration.")
        gate = Acceptance(config)
        try:
            for content in contents:
                gate.accept(content)
        except ValueError as error:
            failures.append(
                {
                    "code": "content_quality",
                    "phase": "validate",
                    "retryable": False,
                    "message": str(error),
                }
            )
        if len(contents) != len(store.plan.blueprints):
            failures.append(
                {
                    "code": "content_incomplete",
                    "phase": "validate",
                    "retryable": True,
                    "message": "Not every planned content slot is accepted.",
                }
            )
    return Result(
        run_id=store.plan.run_id,
        operation="validate",
        status="valid" if not failures else "incomplete",
        requested_count=len(store.plan.blueprints),
        accepted_count=len(contents),
        verified_document_count=verified,
        failures=tuple(failures),
        corpus_path=corpus.resolve() if scope == "corpus" and not failures else None,
        details={
            "scope": scope,
            **(
                {"length": content_length_details(
                    contents, generation.quality.word_band_tolerance,
                )}
                if generation is not None and (
                    generation.quality.word_band_tolerance is not None
                    or generation.structure is not None and generation.structure.length_aware
                ) else {}
            ),
            **({"review": review_details(allocation, contents)} if allocation is not None else {}),
            **(
                {
                    "structure": corpus_structure_details(
                        allocation, contents, verified_ids,
                    ),
                }
                if allocation is not None
                and (allocation.recipe_counts is not None or allocation.layout_counts is not None)
                else {}
            ),
        },
        usage=None,
    )
