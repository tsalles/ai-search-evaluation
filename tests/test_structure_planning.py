from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from docgen.config import Config
from docgen.errors import InputError
from docgen.pipeline import generate
from docgen.planning import create_plan, preview
from tests.test_planning import configuration


def structured_config(count: int = 100) -> Config:
    data = configuration(count)
    data["generation"]["structure"] = {
        "complexity_weights": {"simple": 0.30, "moderate": 0.45, "complex": 0.25},
    }
    return Config.model_validate(data)


def test_structure_mix_has_exact_quotas_and_reproducible_resolved_slots() -> None:
    config = structured_config()
    first = create_plan(config, run_id="run-structure", operation="generate")
    assert first == create_plan(config, run_id="run-structure", operation="generate")
    assert Counter(
        blueprint.structure_plan.complexity for blueprint in first.blueprints
    ) == {"simple": 30, "moderate": 45, "complex": 25}
    assert all(blueprint.structure_plan.slots for blueprint in first.blueprints)
    assert len({blueprint.structure_plan.signature for blueprint in first.blueprints}) > 6
    assert preview(config, operation="generate")["details"]["structure"]["complexity_quotas"] == {
        "simple": 30, "moderate": 45, "complex": 25,
    }


def test_layout_changes_do_not_change_content_plans_or_fingerprint() -> None:
    config = structured_config(12)
    first = create_plan(config, run_id="run-structure")
    data = config.model_dump(mode="python")
    data["rendering"] = {
        "weights": {"pdf": 1},
        "layout_weights": {"pdf": {"single-column": 0.5, "two-column": 0.5}},
    }
    second = create_plan(Config.model_validate(data), run_id="run-structure")
    assert first.blueprints == second.blueprints
    assert first.semantic_fingerprint == second.semantic_fingerprint


def test_explicit_legacy_and_recipe_controls_cannot_be_combined() -> None:
    data = configuration()
    data["generation"].update(structure_profile="complex", structure={})
    with pytest.raises(ValidationError, match="structure_profile"):
        Config.model_validate(data)
    data = configuration()
    data["rendering"].update(
        layout_profile="complex", layout_weights={"md": {"semantic": 1}},
    )
    with pytest.raises(ValidationError, match="layout_profile"):
        Config.model_validate(data)


def test_unsupported_native_layout_is_rejected_without_output(tmp_path: Path) -> None:
    data = configuration(1)
    data["rendering"]["layout_weights"] = {"md": {"two-column": 1}}
    with pytest.raises(ValidationError, match="not supported"):
        Config.model_validate(data)
    assert list(tmp_path.iterdir()) == []


def test_unknown_recipe_fails_before_creating_a_run(tmp_path: Path) -> None:
    data = configuration(1)
    data["generation"].update(
        genre_weights={"procedure": 1},
        structure={
            "complexity_weights": {"simple": 1},
            "recipe_weights": {"procedure": {"simple": {"missing-recipe": 1}}},
        },
    )
    config = Config.model_validate(data)
    with pytest.raises(InputError, match="recipe"):
        generate(config, tmp_path, provider=object())
    assert list(tmp_path.iterdir()) == []
