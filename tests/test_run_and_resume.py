from pathlib import Path

import pytest

from docgen.budgets import BudgetOverride
from docgen.config import Config
from docgen.errors import InputError
from docgen.models import Content, content_hash
from docgen.pipeline import generate, resume, run, validate
from docgen.planning import create_plan
from docgen.store import RunStore
from tests.test_content_contract import example_content
from tests.test_generate_phase import BatchProvider, batch_config


def test_combined_failure_resumes_only_unfinished_content_then_publishes(tmp_path: Path) -> None:
    first = run(batch_config(3), tmp_path, provider=BatchProvider(fail="item-000001"))
    assert first.status == "incomplete"
    path = tmp_path / first.run_id
    with RunStore.open(path) as store:
        before = {item.blueprint.content_id: content_hash(item) for item in store.contents()}
    source = BatchProvider()
    result = resume(path, provider=source)
    assert result.status == "complete"
    assert source.calls == ["item-000001"]
    with RunStore.open(path) as store:
        after = {item.blueprint.content_id: content_hash(item) for item in store.contents()}
        assert all(after[key] == value for key, value in before.items())
    assert validate(path).status == "valid"
    assert resume(path).status == "complete"


def test_generation_only_resume_never_silently_runs_phase_two(tmp_path: Path) -> None:
    source = BatchProvider()
    first = generate(batch_config(2), tmp_path, provider=source)
    path = tmp_path / first.run_id
    result = resume(path)
    assert result.status == "content_ready"
    assert len(source.calls) == 2
    assert result.corpus_path is None
    assert not (path / "corpus").exists()
    assert validate(path).details["scope"] == "content"


def test_changed_authoring_contract_blocks_unfinished_generation_before_another_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = run(batch_config(2), tmp_path, provider=BatchProvider(fail="item-000001"))
    directory = tmp_path / first.run_id
    before = {file.name: file.read_bytes() for file in (directory / "content").iterdir()}
    monkeypatch.setattr("docgen.planning.PROMPT_VERSION", "future-authoring-version")
    source = BatchProvider()
    with pytest.raises(InputError, match="authoring|Authoring"):
        resume(directory, provider=source)
    assert source.calls == []
    assert {file.name: file.read_bytes() for file in (directory / "content").iterdir()} == before


def test_changed_authoring_contract_does_not_prevent_offline_reuse_of_completed_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = run(batch_config(2), tmp_path, provider=BatchProvider())
    directory = tmp_path / first.run_id
    before = {file.name: file.read_bytes() for file in first.corpus_path.iterdir()}
    monkeypatch.setattr("docgen.planning.PROMPT_VERSION", "future-authoring-version")
    source = BatchProvider()
    assert resume(directory, provider=source).status == "complete"
    assert source.calls == []
    assert {file.name: file.read_bytes() for file in first.corpus_path.iterdir()} == before


def test_resume_budget_increases_are_monotonic_audited_and_do_not_modify_the_plan(
    tmp_path: Path,
) -> None:
    source = BatchProvider()
    first = generate(batch_config(2, max_requests=1, concurrency=1), tmp_path, provider=source)
    assert first.status == "incomplete"
    path = tmp_path / first.run_id
    original = (path / "plan.json").read_bytes()
    result = resume(path, provider=source, budget_override=BudgetOverride(max_requests=3))
    assert result.status == "content_ready"
    assert len(source.calls) == 2
    assert (path / "plan.json").read_bytes() == original
    assert (path / "reports" / "budget-history.json").is_file()
    with pytest.raises(InputError, match="increase"):
        resume(path, provider=source, budget_override=BudgetOverride(max_requests=2))


def test_candidate_budget_exhaustion_requires_explicit_audited_increase(tmp_path: Path) -> None:
    class BadProvider(BatchProvider):
        def generate(self, blueprint, config):
            return super().generate(blueprint, config).model_copy(update={"title": ""})

    data = batch_config(1).model_dump()
    data["generation"]["quality"]["max_candidates_per_item"] = 1
    first = generate(Config.model_validate(data), tmp_path, provider=BadProvider())
    path = tmp_path / first.run_id
    source = BatchProvider()
    assert resume(path, provider=source).status == "incomplete"
    assert source.calls == []
    result = resume(
        path, provider=source, budget_override=BudgetOverride(max_candidates_per_item=2)
    )
    assert result.status == "content_ready"
    assert source.calls == ["item-000001"]


def test_validate_reports_partial_and_semantically_invalid_content_explicitly(
    tmp_path: Path,
) -> None:
    partial = generate(batch_config(2), tmp_path, provider=BatchProvider(fail="item-000001"))
    assert validate(tmp_path / partial.run_id).status == "incomplete"
    cfg = batch_config(1)
    plan = create_plan(cfg, run_id="run-invalid-quality", operation="generate")
    data = example_content()
    data["blueprint"] = plan.blueprints[0]
    with RunStore.create(tmp_path / plan.run_id, plan) as store:
        store.accept(Content.model_validate(data))
    report = validate(tmp_path / plan.run_id)
    assert report.status == "incomplete"
    assert report.failures[0]["code"] == "content_quality"


def test_validate_detects_published_corruption_and_resume_does_not_hide_exhaustion(
    tmp_path: Path,
) -> None:
    first = run(batch_config(1), tmp_path, provider=BatchProvider())
    (artifact,) = first.corpus_path.iterdir()
    artifact.write_bytes(artifact.read_bytes() + b"unexpected")
    assert validate(tmp_path / first.run_id).status == "incomplete"
    failed = run(
        batch_config(1, max_requests=1), tmp_path, provider=BatchProvider(fail="item-000001")
    )
    assert resume(tmp_path / failed.run_id, provider=BatchProvider()).status == "incomplete"


def test_empty_budget_override_is_a_noop(tmp_path: Path) -> None:
    first = generate(batch_config(1), tmp_path, provider=BatchProvider())
    directory = tmp_path / first.run_id
    assert resume(directory, budget_override=BudgetOverride()).status == "content_ready"
    assert not (directory / "reports" / "budget-history.json").exists()
