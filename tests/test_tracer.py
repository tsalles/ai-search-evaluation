import json
import subprocess
import sys
from pathlib import Path

import pytest

from docgen.config import Config, GenerationConfig, RenderConfig
from docgen.errors import InputError, IntegrityError
from docgen.extractors.markdown import read_markdown
from docgen.models import Blueprint, Content, content_hash
from docgen.pipeline import generate, render, run
from docgen.store import RunStore
from tests.fixtures.factories import diverse_content
from tests.test_content_contract import example_content
from tests.test_planning import configuration


class FixtureProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate(self, blueprint: Blueprint, config: GenerationConfig) -> Content:
        self.calls.append(blueprint.content_id)
        data = example_content()
        base = diverse_content(blueprint)
        for fact in data["facts"]:
            fact.update(valid_from=None, valid_until=None)
        for item in data["blocks"][2]["items"]:
            item["level"] = 1
        data["blocks"] = [*base.blocks, *data["blocks"]]
        data["blueprint"] = blueprint.model_dump(mode="python")
        return Content.model_validate(data)


def single_config() -> Config:
    data = configuration(1)
    data["generation"]["genre_weights"] = {"comparison": 1}
    data["generation"]["length_weights"] = {"short": 1}
    return Config.model_validate(data)


def test_generation_persists_and_fresh_process_can_render_offline(tmp_path: Path) -> None:
    provider = FixtureProvider()
    result = generate(single_config(), tmp_path, provider=provider)
    assert result.status == "content_ready"
    assert result.accepted_count == 1
    assert result.corpus_path is None
    assert len(provider.calls) == 1
    directory = tmp_path / result.run_id
    assert not (directory / "corpus").exists()
    with RunStore.open(directory) as store:
        content = store.contents()[0]
        original_hash = content_hash(content)
        assert content.blueprint == store.plan.blueprints[0]
    script = (
        "import json,sys; from pathlib import Path; "
        "from docgen.pipeline import render; from docgen.config import RenderConfig; "
        "result=render(Path(sys.argv[1]), RenderConfig(weights={'md':1})); "
        "print(result.model_dump_json())"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script, str(directory)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    output = json.loads(completed.stdout)
    assert output["status"] == "complete"
    (artifact,) = Path(output["corpus_path"]).glob("*.md")
    text = artifact.read_text(encoding="utf-8")
    assert "Cr\u00e9dito Aurora" in text
    assert "1,25" in text
    assert "| Produto |" in text
    assert "Solicite avalia\u00e7\u00e3o." in read_markdown(artifact).paragraphs
    with RunStore.open(directory) as store:
        assert content_hash(store.contents()[0]) == original_hash


def test_combined_tracer_matches_separate_semantics(tmp_path: Path) -> None:
    cfg = single_config()
    separate = generate(cfg, tmp_path / "separate", provider=FixtureProvider())
    separate = render(tmp_path / "separate" / separate.run_id, cfg.rendering)
    combined = run(cfg, tmp_path / "combined", provider=FixtureProvider())
    assert combined.status == "complete"
    assert combined.verified_document_count == 1
    (a,) = separate.corpus_path.glob("*.md")
    (b,) = combined.corpus_path.glob("*.md")
    assert a.read_bytes() == b.read_bytes()
    assert len(list(combined.corpus_path.iterdir())) == 1


def test_missing_real_provider_fails_without_creating_output(tmp_path: Path) -> None:
    output = tmp_path / "not-created"
    with pytest.raises(InputError, match="provider"):
        generate(single_config(), output)
    assert not output.exists()


def test_provider_cannot_replace_planned_identity_or_return_invalid_content(tmp_path: Path) -> None:
    class WrongIdentity(FixtureProvider):
        def generate(self, blueprint: Blueprint, config: GenerationConfig) -> Content:
            data = example_content()
            data["blueprint"]["content_id"] = "different-item"
            return Content.model_validate(data)

    with pytest.raises(IntegrityError, match="blueprint"):
        generate(single_config(), tmp_path, provider=WrongIdentity())
    (directory,) = tmp_path.iterdir()
    with RunStore.open(directory) as store:
        assert store.contents() == ()
    assert not (directory / "corpus").exists()


def test_invalid_candidate_is_not_accepted_or_rendered(tmp_path: Path) -> None:
    class InvalidCandidate(FixtureProvider):
        def generate(self, blueprint: Blueprint, config: GenerationConfig) -> Content:
            valid = super().generate(blueprint, config)
            return valid.model_copy(update={"title": " "})

    result = run(single_config(), tmp_path, provider=InvalidCandidate())
    assert result.status == "incomplete"
    assert result.accepted_count == 0
    assert result.failures[0]["code"] == "quality_candidate"
    (directory,) = tmp_path.iterdir()
    with RunStore.open(directory) as store:
        assert store.contents() == ()
    assert not (directory / "corpus").exists()


def test_saved_content_renders_to_native_pdf_without_regeneration(tmp_path: Path) -> None:
    result = generate(single_config(), tmp_path, provider=FixtureProvider())
    rendered = render(tmp_path / result.run_id, RenderConfig(weights={"pdf": 1}))
    assert rendered.status == "complete"
    assert len(list(rendered.corpus_path.glob("*.pdf"))) == 1
