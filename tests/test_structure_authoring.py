import json
from pathlib import Path

import pytest

from docgen.composition import compose
from docgen.config import Config
from docgen.models import Content
from docgen.pipeline import generate, resume, validate
from docgen.planning import create_plan
from docgen.prompts import author_prompt
from docgen.providers.azure import DraftResponse
from docgen.quality import assess
from docgen.store import RunStore
from tests.fixtures.factories import content_wire, structured_content
from tests.test_planning import configuration
from tests.test_structure_planning import structured_config


@pytest.mark.parametrize("genre", ["explainer", "procedure", "faq", "comparison"])
@pytest.mark.parametrize("complexity", ["simple", "moderate", "complex"])
@pytest.mark.parametrize("band", ["short", "medium", "long"])
def test_every_genre_complexity_and_length_can_author_its_frozen_shape(
    genre: str, complexity: str, band: str,
) -> None:
    data = configuration(2)
    data["generation"].update(
        genre_weights={genre: 1}, length_weights={band: 1},
        structure={"complexity_weights": {complexity: 1}},
    )
    config = Config.model_validate(data)
    plan = create_plan(config, run_id="run-authoring", operation="generate")
    for blueprint in plan.blueprints:
        content = structured_content(blueprint)
        accepted = assess(content, config.generation, detector=lambda *_: 1)
        assert "structure_plan" in accepted.quality.checks
        assert accepted.blueprint.structure_plan == blueprint.structure_plan
        prompt = author_prompt(blueprint, config.generation)
        assert "frozen structure_plan exactly" in prompt
        assert "baseline profile permits" not in prompt


@pytest.mark.parametrize("mutation", ["extra", "order", "kind", "list", "question", "table"])
def test_authored_structure_cannot_drift_from_the_plan(mutation: str) -> None:
    data = configuration(1)
    data["generation"].update(
        genre_weights={"faq" if mutation == "question" else "comparison": 1},
        structure={"complexity_weights": {"complex": 1}},
    )
    config = Config.model_validate(data)
    blueprint = create_plan(config, run_id="run-reject").blueprints[0]
    content = structured_content(blueprint)
    raw = json.loads(content.model_dump_json())
    if mutation == "extra":
        raw["blocks"].append({"id": "extra", "kind": "paragraph", "text": "Texto adicional."})
    elif mutation == "order":
        raw["blocks"][-1], raw["blocks"][-2] = raw["blocks"][-2], raw["blocks"][-1]
    elif mutation == "kind":
        raw["blocks"][1]["kind"] = "callout"
    elif mutation == "list":
        item = next(
            item for block in raw["blocks"] for item in block["items"] or ()
            if item["level"] == 2
        )
        item["level"] = 1
    elif mutation == "question":
        block = next(block for block in raw["blocks"] if (block["text"] or "").endswith("?"))
        block["text"] = "Uma resposta sem pergunta"
    else:
        block = next(block for block in raw["blocks"] if block["table"])
        block["table"]["rows"].pop()
    with pytest.raises(ValueError, match="plan|slot|Structure|structure|question|List|Table"):
        assess(Content.model_validate(raw), config.generation, detector=lambda *_: 1)


def test_wire_composition_preserves_resolved_structure() -> None:
    config = structured_config(1)
    blueprint = create_plan(config, run_id="run-wire").blueprints[0]
    content = structured_content(blueprint)
    response = DraftResponse(
        payload=content_wire(content), reported_model="test",
        model_version=None, response_id="response-test", request_id=None, usage=None,
    )
    composed = compose(response, blueprint, config.generation, attempt_id="attempt-test")
    assert assess(composed, config.generation, detector=lambda *_: 1).blocks == content.blocks


def test_rejected_candidate_retries_and_resumes_the_same_structure(tmp_path: Path) -> None:
    class Provider:
        def __init__(self) -> None:
            self.plans = []

        def generate(self, blueprint, config):
            self.plans.append(blueprint)
            content = structured_content(blueprint)
            if len(self.plans) == 1:
                return content.model_copy(update={"blocks": content.blocks[:-1]})
            return content

    data = structured_config(1).model_dump()
    data["generation"]["limits"].update(max_requests=1, concurrency=1)
    config = Config.model_validate(data)
    source = Provider()
    first = generate(config, tmp_path, provider=source)
    assert first.status == "incomplete"
    directory = tmp_path / first.run_id
    original = (directory / "plan.json").read_bytes()
    from docgen.budgets import BudgetOverride

    result = resume(directory, provider=source, budget_override=BudgetOverride(max_requests=3))
    assert result.status == "content_ready"
    assert len(source.plans) == 2 and source.plans[0] == source.plans[1]
    assert (directory / "plan.json").read_bytes() == original
    assert validate(directory).status == "valid"
    with RunStore.open(directory) as store:
        assert store.contents()[0].blueprint.structure_plan == source.plans[0].structure_plan
