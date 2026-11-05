from collections import Counter
from pathlib import Path

import pytest

from docgen.config import Config, RenderConfig
from docgen.errors import InputError
from docgen.models import Content, content_hash, serialize
from docgen.pipeline import generate, render, resume, run, validate
from docgen.planning import create_plan
from docgen.store import RunStore
from tests.fixtures.factories import diverse_content, structured_content
from tests.test_planning import configuration


def varied_config(count: int = 24) -> Config:
    data = configuration(count)
    data["generation"]["structure"] = {}
    data["rendering"] = {
        "weights": {"pdf": 0.25, "docx": 0.25, "xlsx": 0.15, "pptx": 0.15, "html": 0.1, "md": 0.1},
        "layout_weights": {
            "pdf": {"single-column": 0.5, "two-column": 0.5},
            "docx": {"single-column": 0.5, "two-column": 0.5},
            "pptx": {"flow": 0.5, "section-led": 0.5},
            "xlsx": {"compact": 0.5, "sectioned": 0.5},
            "html": {"linear": 0.5, "sectioned": 0.5},
            "md": {"semantic": 1},
        },
    }
    return Config.model_validate(data)


class PlannedProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate(self, blueprint, config):
        self.calls.append(blueprint.content_id)
        return structured_content(blueprint)


def test_varied_corpus_runs_validates_and_resumes_without_reauthoring(tmp_path: Path) -> None:
    source = PlannedProvider()
    result = run(varied_config(), tmp_path, provider=source)
    assert result.status == "complete", result.failures
    assert result.verified_document_count == 24
    assert len(source.calls) == 24
    directory = tmp_path / result.run_id
    before = {file.name: file.read_bytes() for file in result.corpus_path.iterdir()}
    assert len(before) == 24
    with RunStore.open(directory) as store:
        allocation = store.read_allocation()
        assert allocation.algorithm_version == "transport-v2-structure"
        assert all(stratum.complexity is not None for stratum in allocation.strata)
        contents = store.contents()
        assert Counter(content.blueprint.structure_plan.complexity for content in contents) == {
            "simple": 7, "moderate": 11, "complex": 6,
        }
        assert result.details["structure"]["accepted"] == result.details["structure"]["verified"]
        assert result.details["structure"]["layouts_by_format"] == (
            result.details["structure"]["verified_layouts_by_format"]
        )
        by_id = {content.blueprint.content_id: content for content in contents}
        assignments = {item.content_id: item for item in allocation.items}
        def group(content_id):
            item = assignments[content_id]
            return (
                item.format, by_id[content_id].blueprint.structure_plan.complexity,
                item.layout_plan.recipe,
            )
        assert {
            group(item["content_id"]) for item in result.details["review"]["sample"]
        } == {group(item.content_id) for item in allocation.items}
    assert validate(directory).status == "valid"
    assert resume(directory, provider=source).status == "complete"
    assert len(source.calls) == 24
    assert {file.name: file.read_bytes() for file in result.corpus_path.iterdir()} == before
    with pytest.raises(InputError, match="immutable"):
        render(directory, RenderConfig(weights={"md": 1}))


def test_render_crash_keeps_frozen_layouts_and_adopts_verified_native_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import docgen.rendering as rendering

    config = varied_config(6)
    source = PlannedProvider()
    generated = generate(config, tmp_path, provider=source)
    assert generated.status == "content_ready", generated.failures
    directory = tmp_path / generated.run_id
    with RunStore.open(directory) as store:
        before = {
            content.blueprint.content_id: content_hash(content) for content in store.contents()
        }
    original = rendering.render_document
    with monkeypatch.context() as fault:
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise KeyboardInterrupt
        fault.setattr(rendering, "render_document", interrupted)
        first = render(directory, config.rendering)
    assert first.status == "cancelled"
    allocation = (directory / "allocation.json").read_bytes()
    artifact = next((directory / "artifacts.pending").iterdir())
    retained = artifact.read_bytes()
    completed = resume(directory, provider=source)
    assert completed.status == "complete", completed.failures
    assert len(source.calls) == 6
    assert (directory / "allocation.json").read_bytes() == allocation
    assert (completed.corpus_path / artifact.name).read_bytes() == retained
    with RunStore.open(directory) as store:
        after = {
            content.blueprint.content_id: content_hash(content) for content in store.contents()
        }
        assert after == before


def test_legacy_serialization_does_not_acquire_opt_in_extension_fields() -> None:
    config = Config.model_validate(configuration(1))
    plan = create_plan(config, run_id="run-legacy")
    content = diverse_content(plan.blueprints[0])
    raw = serialize(content)
    assert b"structure_plan" not in raw
    assert b'"structure":' not in serialize(plan)
    assert b"layout_weights" not in serialize(plan)
    assert content_hash(Content.model_validate_json(raw)) == content_hash(content)


def test_invalid_library_profile_overrides_are_not_erased_by_snapshot_serialization(
    tmp_path: Path,
) -> None:
    config = varied_config(1)
    invalid = config.model_copy(update={
        "generation": config.generation.model_copy(update={"structure_profile": "complex"}),
    })
    source = PlannedProvider()
    with pytest.raises(InputError, match="Invalid generation"):
        generate(invalid, tmp_path, provider=source)
    assert source.calls == [] and list(tmp_path.iterdir()) == []
    generated = generate(config, tmp_path, provider=source)
    assert generated.status == "content_ready", generated.failures
    directory = tmp_path / generated.run_id
    invalid_render = config.rendering.model_copy(update={"layout_profile": "complex"})
    with pytest.raises(InputError, match="Invalid render"):
        render(directory, invalid_render)
    assert not (directory / "allocation.json").exists()
