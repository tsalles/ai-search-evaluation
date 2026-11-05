from pathlib import Path
from typing import Literal
from uuid import uuid4

from docgen.blob_clear import clear as clear
from docgen.blob_push import push as push
from docgen.budgets import BudgetOverride
from docgen.config import Config, RenderConfig
from docgen.errors import InputError
from docgen.generation import generate_content
from docgen.planning import create_plan
from docgen.providers.base import ContentProvider
from docgen.recovery import resume_run, validate_run
from docgen.rendering import render_content
from docgen.reports import save_summary
from docgen.results import Result
from docgen.store import RunStore


def _generate(
    config: Config, output: Path, provider: ContentProvider | None,
    operation: Literal["generate", "run"],
) -> Result:
    try:
        config = Config.model_validate_json(config.model_dump_json())
    except ValueError as exc:
        raise InputError("Invalid generation configuration snapshot.") from exc
    config.require_phase(operation)
    generation = config.generation
    if generation is None:
        raise InputError("Generation configuration is required.")
    if provider is None and generation.provider is None:
        raise InputError("A provider configuration or explicit content provider is required.")
    plan = create_plan(config, run_id=f"run-{uuid4().hex}", operation=operation)
    with RunStore.create(output / plan.run_id, plan) as store:
        return save_summary(store.directory, generate_content(store, provider=provider))


def generate(config: Config, output: Path, *, provider: ContentProvider | None = None) -> Result:
    return _generate(config, output, provider, "generate")


def render(directory: Path, config: RenderConfig) -> Result:
    with RunStore.open(directory) as store:
        return save_summary(store.directory, render_content(store, config))


def run(config: Config, output: Path, *, provider: ContentProvider | None = None) -> Result:
    config.require_phase("run")
    if config.rendering is None:
        raise InputError("Rendering configuration is required.")
    generated = _generate(config, output, provider, "run")
    if generated.status != "content_ready":
        return generated
    rendered = render(output / generated.run_id, config.rendering)
    result = Result.model_validate({
        **rendered.model_dump(), "operation": "run", "usage": generated.usage,
    })
    with RunStore.open(output / result.run_id) as store:
        return save_summary(store.directory, result)


def resume(
    directory: Path, *, provider: ContentProvider | None = None,
    budget_override: BudgetOverride | None = None,
) -> Result:
    with RunStore.open(directory) as store:
        return save_summary(
            store.directory, resume_run(store, provider=provider, budget_override=budget_override)
        )


def validate(directory: Path) -> Result:
    with RunStore.open(directory) as store:
        return validate_run(store)
