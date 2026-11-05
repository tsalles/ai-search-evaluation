import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from docgen.budgets import BudgetOverride, apply_budget
from docgen.composition import materialize
from docgen.config import Config
from docgen.errors import InputError
from docgen.facts import FactRegistry
from docgen.models import Block, Content, Fact
from docgen.pipeline import generate, resume, run, validate
from docgen.planning import create_plan, preview, semantic_fingerprint
from docgen.profiles import acceptance_word_band
from docgen.prompts import author_prompt
from docgen.quality import assess
from docgen.store import RunStore
from docgen.structure_models import StructurePlan
from docgen.text import word_count
from tests.fixtures.factories import diverse_content, quality_content
from tests.test_planning import configuration
from tests.test_structure_pipeline import PlannedProvider, varied_config


def controls_config(count: int = 1) -> Config:
    data = configuration(count)
    data["generation"].update(
        quality={"word_band_tolerance": 0.05},
        structure={"length_aware": True},
    )
    return Config.model_validate(data)


@pytest.mark.parametrize(
    ("band", "low", "high"),
    [
        ("short", 190, 420),
        ("medium", 475, 945),
        ("long", 950, 1680),
    ],
)
def test_word_tolerance_has_exact_inclusive_integer_boundaries(
    band: str,
    low: int,
    high: int,
) -> None:
    config = controls_config()
    for words, valid in ((low - 1, False), (low, True), (high, True), (high + 1, False)):
        content = quality_content(words=words)
        content = Content.model_validate(
            {
                **content.model_dump(),
                "blueprint": {**content.blueprint.model_dump(), "length_band": band},
            }
        )
        if valid:
            accepted = assess(content, config.generation, detector=lambda *_: 1)
            assert accepted.quality.word_count == words
            assert "length_tolerance" in accepted.quality.checks
        else:
            with pytest.raises(ValueError, match="length"):
                assess(content, config.generation, detector=lambda *_: 1)


def test_tolerance_does_not_change_nominal_targets_or_accept_large_overruns() -> None:
    config = controls_config()
    accepted = assess(quality_content(words=417), config.generation, detector=lambda *_: 1)
    assert accepted.quality.word_count == 417
    with pytest.raises(ValueError, match="length"):
        assess(quality_content(words=530), config.generation, detector=lambda *_: 1)
    result = preview(config)
    assert result["details"]["length_policy"]["bands"]["short"] == {
        "nominal_min": 200,
        "nominal_max": 400,
        "accepted_min": 190,
        "accepted_max": 420,
        "target_words": 300,
    }


@pytest.mark.parametrize("tolerance", [-0.01, 0.051, True, "0.05", float("nan"), float("inf")])
def test_invalid_word_tolerances_are_rejected(tolerance) -> None:
    data = configuration()
    data["generation"]["quality"] = {"word_band_tolerance": tolerance}
    with pytest.raises(ValidationError):
        Config.model_validate(data)


@pytest.mark.parametrize("limit", [10, 20])
def test_bounded_candidate_retries_preserve_overall_request_and_token_caps(limit) -> None:
    data = controls_config().model_dump()
    data["generation"]["limits"].update(max_requests=7, max_observed_total_tokens=1000)
    config = Config.model_validate(data).generation
    updated = apply_budget(config, BudgetOverride(max_candidates_per_item=limit))
    assert updated.quality.max_candidates_per_item == limit
    assert updated.request_limit == config.request_limit == 7
    assert updated.limits.max_observed_total_tokens == 1000
    assert updated.limits == config.limits
    assert updated.quality.model_dump(exclude={"max_candidates_per_item"}) == (
        config.quality.model_dump(exclude={"max_candidates_per_item"})
    )


@pytest.mark.parametrize("limit", [0, 41, True, "10"])
def test_candidate_retries_remain_strictly_typed_and_bounded(limit) -> None:
    with pytest.raises(ValidationError):
        BudgetOverride(max_candidates_per_item=limit)
    data = controls_config().model_dump()
    data["generation"]["quality"]["max_candidates_per_item"] = limit
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def unit_content(unit: str, *, column_unit: str = "dias \u00fateis", value: str = "1") -> dict:
    data = json.loads(quality_content("comparison").model_dump_json())
    table = next(block["table"] for block in data["blocks"] if block["table"])
    table["columns"][0].update(kind="decimal", unit=column_unit)
    for row in table["rows"]:
        row[0] = {"kind": "decimal", "value": value, "fact_id": "duration"}
    data["facts"] = [
        {
            "id": "duration",
            "entity": data["title"],
            "kind": "decimal",
            "value": "1",
            "unit": unit,
            "display": "1 " + unit,
        }
    ]
    return data


@pytest.mark.parametrize(
    ("unit", "column_unit"),
    [
        ("dia \u00fatil", "dias \u00fateis"),
        ("dia util", "dias uteis"),
        ("business day", "business days"),
        ("dia corrido", "dias corridos"),
        ("day", "days"),
    ],
)
def test_unit_grammar_does_not_create_a_false_fact_contradiction(
    unit: str,
    column_unit: str,
) -> None:
    content = Content.model_validate(unit_content(unit, column_unit=column_unit))
    assert content.facts[0].unit == unit
    table = next(block.table for block in content.blocks if block.table)
    assert table.columns[0].unit == column_unit
    registry = FactRegistry()
    registry.accept(content)
    registry.accept(Content.model_validate(unit_content(column_unit, column_unit=unit)))


@pytest.mark.parametrize(
    ("unit", "column_unit", "value"),
    [
        ("dia \u00fatil", "dias corridos", "1"),
        ("dia \u00fatil", "dias", "1"),
        ("dia \u00fatil", "dias \u00fateis", "2"),
        ("% ao mes", "% ao ano", "1"),
        ("R$", "USD", "1"),
        ("ms", "Ms", "1"),
    ],
)
def test_unit_equivalence_keeps_values_dimensions_and_periods_strict(
    unit: str,
    column_unit: str,
    value: str,
) -> None:
    with pytest.raises(ValidationError, match="contradicts"):
        Content.model_validate(unit_content(unit, column_unit=column_unit, value=value))


@pytest.mark.parametrize("genre", ["explainer", "procedure", "faq", "comparison"])
@pytest.mark.parametrize("complexity", ["simple", "moderate", "complex"])
@pytest.mark.parametrize(("band", "target"), [("short", 300), ("medium", 700), ("long", 1300)])
def test_length_aware_shapes_have_frozen_centered_word_budgets(
    genre: str,
    complexity: str,
    band: str,
    target: int,
) -> None:
    data = controls_config(2).model_dump()
    data["generation"].update(
        genre_weights={genre: 1},
        length_weights={band: 1},
        structure={"length_aware": True, "complexity_weights": {complexity: 1}},
    )
    config = Config.model_validate(data)
    plan = create_plan(config, run_id="run-word-budget")
    assert plan.algorithm_version == "3"
    assert plan == create_plan(config, run_id="run-word-budget")
    for blueprint in plan.blueprints:
        structure = blueprint.structure_plan
        assert structure.version == "2"
        assert structure.target_words == target
        assert structure.title_words + sum(slot.word_budget for slot in structure.slots) == target
        assert all(slot.word_budget > 0 for slot in structure.slots)
        if band == "short" and genre == "comparison" and complexity == "complex":
            table = next(slot for slot in structure.slots if slot.kind == "table")
            assert (table.columns, table.rows) == (5, 3)
        prompt = author_prompt(blueprint, config.generation)
        context = json.loads(prompt.split("Context:\n", 1)[1])
        assert context["word_target"] == target
        assert context["length_policy"]["target_words"] == target
        assert "bands" not in context["length_policy"]
        assert "after fact placeholders are expanded" in prompt


def test_overcrowded_length_aware_recipe_fails_before_inference(tmp_path: Path) -> None:
    data = controls_config().model_dump()
    data["generation"].update(
        genre_weights={"comparison": 1},
        length_weights={"short": 1},
        structure={
            "length_aware": True,
            "complexity_weights": {"complex": 1},
            "recipes": {
                "dense": {
                    "genre": "comparison",
                    "complexity": "complex",
                    "groups": [
                        {
                            "blocks": [
                                {"kind": "heading", "role": "scope", "level": 1},
                                {
                                    "kind": "table",
                                    "role": "comparison",
                                    "columns": {"min": 5, "max": 5},
                                    "rows": {"min": 10, "max": 10},
                                },
                                {
                                    "kind": "unordered_list",
                                    "role": "conditions",
                                    "items": {"min": 30, "max": 30},
                                    "subitems": {"min": 10, "max": 10},
                                },
                            ]
                        }
                    ],
                }
            },
            "recipe_weights": {"comparison": {"complex": {"dense": 1}}},
        },
    )
    source = PlannedProvider()
    with pytest.raises(InputError, match="infeasible"):
        generate(Config.model_validate(data), tmp_path, provider=source)
    assert source.calls == [] and list(tmp_path.iterdir()) == []


def test_legacy_controls_keep_their_original_serialized_shape() -> None:
    config = Config.model_validate(configuration())
    encoded = config.model_dump_json()
    assert "word_band_tolerance" not in encoded and "length_aware" not in encoded
    plan = create_plan(config, run_id="run-legacy-controls")
    assert plan.algorithm_version == "1"
    assert all(blueprint.structure_plan is None for blueprint in plan.blueprints)
    assert config.generation.quality.word_band_tolerance in (None, Decimal(0))


def test_unit_inflection_cannot_duplicate_an_expanded_fact_unit() -> None:
    fact = Fact(
        id="duration",
        entity="Aurora",
        kind="decimal",
        value=Decimal(1),
        unit="dia \u00fatil",
        display="1 dia \u00fatil",
    )
    with pytest.raises(ValueError, match="already includes"):
        materialize("Retorno em {{fact:duration}} dias \u00fateis.", {"duration": fact})
    assert materialize("Retorno em {{fact:duration}}.", {"duration": fact}) == (
        "Retorno em 1 dia \u00fatil.",
        ("duration",),
    )


@pytest.mark.parametrize("mutation", ["target", "title", "slot", "sum", "version"])
def test_word_budget_plans_cannot_be_incomplete_or_inconsistent(mutation: str) -> None:
    plan = create_plan(controls_config(), run_id="run-budget-check")
    raw = json.loads(plan.blueprints[0].structure_plan.model_dump_json())
    if mutation == "target":
        raw["target_words"] = None
    elif mutation == "title":
        raw["title_words"] = None
    elif mutation == "slot":
        raw["slots"][0]["word_budget"] = None
    elif mutation == "sum":
        raw["target_words"] += 1
    else:
        raw["version"] = "1"
    with pytest.raises(ValidationError, match="budget"):
        StructurePlan.model_validate(raw)


def test_word_budgets_are_not_counted_as_structural_diversity() -> None:
    plan = create_plan(controls_config(), run_id="run-signature").blueprints[0].structure_plan
    raw = json.loads(plan.model_dump_json())
    raw["slots"][0]["word_budget"] += 1
    raw["slots"][1]["word_budget"] -= 1
    other = StructurePlan.model_validate(raw)
    assert other.signature == plan.signature


def test_tolerance_is_explicit_in_reports_and_does_not_relabel_length_bands(tmp_path: Path) -> None:
    class BorderlineProvider:
        def generate(self, blueprint, config):
            content = diverse_content(blueprint)
            words = [
                word
                for block in content.blocks
                if block.kind == "paragraph"
                for word in (block.text or "").split()
            ]
            extra = Block(
                id="length-extra",
                kind="paragraph",
                text=" ".join((words * 2)[: 417 - word_count(content)]),
            )
            return Content.model_validate(
                {
                    **content.model_dump(),
                    "blocks": (*content.blocks, extra),
                }
            )

    data = configuration(1)
    data["generation"].update(
        genre_weights={"explainer": 1},
        length_weights={"short": 1},
        quality={"word_band_tolerance": 0.05},
    )
    config = Config.model_validate(data)
    result = run(config, tmp_path, provider=BorderlineProvider())
    assert result.status == "complete", result.failures
    assert result.details["length"]["items"][0] == {
        "content_id": "item-000001",
        "length_band": "short",
        "word_count": 417,
        "in_accepted_range": True,
        "used_tolerance": True,
    }
    with RunStore.open(tmp_path / result.run_id) as store:
        content = store.contents()[0]
        assert content.blueprint.length_band == "short"
        assert "length_tolerance" in content.quality.checks
    assert validate(tmp_path / result.run_id).status == "valid"


def test_updated_controls_run_real_renderers_and_resume_without_authoring(tmp_path: Path) -> None:
    data = varied_config(12).model_dump()
    data["generation"]["quality"]["word_band_tolerance"] = 0.05
    data["generation"]["structure"]["length_aware"] = True
    config = Config.model_validate(data)
    source = PlannedProvider()
    result = run(config, tmp_path, provider=source)
    assert result.status == "complete", result.failures
    directory = tmp_path / result.run_id
    before = {path.name: path.read_bytes() for path in result.corpus_path.iterdir()}
    assert len(before) == 12 and len(source.calls) == 12
    assert validate(directory).status == "valid"
    assert resume(directory, provider=source).status == "complete"
    assert len(source.calls) == 12
    assert {path.name: path.read_bytes() for path in result.corpus_path.iterdir()} == before


def test_new_authoring_contract_preserves_old_plans_and_blocks_mixed_resume(tmp_path: Path) -> None:
    data = configuration(1)
    data["generation"]["structure"] = {}
    config = Config.model_validate(data)
    current = create_plan(config, run_id="run-prompt-four", operation="generate")
    historical = current.model_copy(
        update={
            "semantic_fingerprint": semantic_fingerprint(config, prompt_version="4"),
        }
    )
    directory = tmp_path / historical.run_id
    with RunStore.create(directory, historical):
        pass
    before = (directory / "plan.json").read_bytes()
    with RunStore.open(directory) as store:
        assert store.plan == historical
    source = PlannedProvider()
    with pytest.raises(InputError, match="authoring contract"):
        resume(directory, provider=source)
    assert source.calls == [] and (directory / "plan.json").read_bytes() == before


@pytest.mark.parametrize(
    ("band", "expected"),
    [
        ("short", (200, 400)),
        ("medium", (500, 900)),
        ("long", (999, 1601)),
    ],
)
def test_fractional_tolerance_rounds_inward_to_whole_words(band, expected) -> None:
    assert acceptance_word_band(band, Decimal("0.001")) == expected


@pytest.mark.parametrize(
    ("band", "expected"),
    [
        ("short", (191, 419)),
        ("medium", (476, 944)),
        ("long", (951, 1679)),
    ],
)
def test_tolerance_rounding_does_not_depend_on_decimal_context_precision(band, expected) -> None:
    tolerance = Decimal("0.049999999999999999999999999999999999")
    assert acceptance_word_band(band, tolerance) == expected


def test_maximum_tolerance_keeps_length_bands_disjoint() -> None:
    short = acceptance_word_band("short", Decimal("0.05"))
    medium = acceptance_word_band("medium", Decimal("0.05"))
    long = acceptance_word_band("long", Decimal("0.05"))
    assert short[1] < medium[0] and medium[1] < long[0]


@pytest.mark.parametrize("control", ["tolerance", "budget"])
def test_length_controls_can_be_enabled_independently(tmp_path: Path, control: str) -> None:
    data = configuration(1)
    if control == "tolerance":
        data["generation"]["quality"] = {"word_band_tolerance": 0.05}
    else:
        data["generation"]["structure"] = {"length_aware": True}
    result = run(Config.model_validate(data), tmp_path, provider=PlannedProvider())
    assert result.status == "complete", result.failures
    expected = 0.05 if control == "tolerance" else 0
    assert result.details["length"]["tolerance"] == expected
    assert validate(tmp_path / result.run_id).details["length"]["tolerance"] == expected


def test_word_tolerance_is_semantic_configuration_not_a_resume_budget() -> None:
    with pytest.raises(ValidationError):
        BudgetOverride.model_validate({"word_band_tolerance": 0.05})
    config = controls_config()
    data = config.model_dump()
    data["generation"]["quality"]["word_band_tolerance"] = 0
    assert semantic_fingerprint(config) != semantic_fingerprint(Config.model_validate(data))
