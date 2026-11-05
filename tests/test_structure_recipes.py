import copy
import itertools
import json
from collections import Counter
from fractions import Fraction
from pathlib import Path

import networkx as nx
import pytest
from pydantic import ValidationError

from docgen.allocation import AllocationPlan, allocate
from docgen.config import Config, RenderConfig
from docgen.errors import InputError, IntegrityError
from docgen.pipeline import generate, render, run
from docgen.planning import create_plan, preview
from tests.fixtures.factories import structured_content
from tests.test_planning import configuration
from tests.test_structure_pipeline import PlannedProvider


def custom_recipe() -> dict:
    return {
        "genre": "explainer", "complexity": "simple",
        "groups": [
            {
                "blocks": [
                    {"kind": "heading", "role": "a distinct section", "level": 1},
                    {"kind": "paragraph", "role": "explanation"},
                ],
                "repeat": {"min": 3, "max": 5},
            },
            {"blocks": [{"kind": "paragraph", "role": "closing"}], "optional": True},
        ],
    }


def custom_config(recipe: dict, count: int = 8) -> Config:
    data = configuration(count)
    data["generation"].update(
        genre_weights={recipe["genre"]: 1},
        structure={
            "complexity_weights": {recipe["complexity"]: 1},
            "recipes": {"custom-shape": recipe},
            "recipe_weights": {
                recipe["genre"]: {recipe["complexity"]: {"custom-shape": 1}},
            },
        },
    )
    return Config.model_validate(data)


def test_custom_recipe_samples_repetitions_and_optional_groups_without_shape_drift() -> None:
    config = custom_config(custom_recipe(), 20)
    plan = create_plan(config, run_id="run-custom")
    assert plan == create_plan(config, run_id="run-custom")
    assert plan.algorithm_version == "2"
    assert {blueprint.structure_plan.recipe_id for blueprint in plan.blueprints} == {"custom-shape"}
    assert len({blueprint.structure_plan.signature for blueprint in plan.blueprints}) >= 3
    for blueprint in plan.blueprints:
        slots = blueprint.structure_plan.slots
        assert 3 <= sum(slot.kind == "heading" for slot in slots) <= 5
        assert [slot.id for slot in slots] == [
            f"block-{index + 1:03}" for index in range(len(slots))
        ]
    data = config.model_dump()
    data["seed"] += 1
    other = create_plan(Config.model_validate(data), run_id="run-custom")
    assert [item.structure_plan for item in plan.blueprints] != [
        item.structure_plan for item in other.blueprints
    ]


@pytest.mark.parametrize("mutation", [
    lambda r: r["groups"][0]["repeat"].update(min=6, max=3),
    lambda r: r["groups"][0]["repeat"].update(min=True),
    lambda r: r["groups"][0]["repeat"].update(min=0),
    lambda r: r["groups"][0]["repeat"].update(max=21),
    lambda r: r["groups"][0].update(optional="yes"),
    lambda r: r["groups"][0]["blocks"][0].update(level=3),
    lambda r: r["groups"][0]["blocks"][0].update(level=None),
    lambda r: r["groups"][0]["blocks"][1].update(question=True),
    lambda r: r["groups"][0]["blocks"][1].update(items={"min": 1, "max": 2}),
    lambda r: r["groups"][0]["blocks"][1].update(subitems={"min": 1, "max": 2}),
    lambda r: r["groups"][0]["blocks"][1].update(columns={"min": 1, "max": 9}),
    lambda r: r["groups"][0]["blocks"][1].update(rows={"min": 0, "max": 2}),
    lambda r: r["groups"][0]["repeat"].update(min=1, max=2),
    lambda r: r.update(complexity="moderate"),
    lambda r: r.update(complexity="complex"),
    lambda r: r.update(genre="procedure"),
    lambda r: r.update(genre="faq"),
    lambda r: r.update(genre="comparison"),
    lambda r: r["groups"][0].update(optional=True),
    lambda r: r["groups"][0]["repeat"].update(min=3, max=20),
])
def test_invalid_or_unguaranteed_recipe_shapes_are_rejected(mutation) -> None:
    recipe = custom_recipe()
    mutation(recipe)
    if recipe["groups"][0]["repeat"]["max"] == 20:
        recipe["groups"][0]["blocks"] *= 4
    with pytest.raises(ValidationError):
        custom_config(recipe)


def test_optional_heading_ancestors_cannot_make_an_intermediate_instance_invalid() -> None:
    recipe = custom_recipe()
    recipe["complexity"] = "complex"
    recipe["groups"] = [
        {"blocks": [
            {"kind": "heading", "role": "intro", "level": 1},
            {"kind": "paragraph", "role": "context"},
        ], "repeat": {"min": 3, "max": 3}},
        {"blocks": [{"kind": "heading", "role": "parent", "level": 2}], "optional": True},
        {"optional": True, "blocks": [
            {"kind": "heading", "role": "child", "level": 3},
            {"kind": "paragraph", "role": "detail"},
        ]},
        {"blocks": [
            {"kind": "callout", "role": "exception"},
            {
                "kind": "unordered_list", "role": "considerations",
                "items": {"min": 1, "max": 2}, "subitems": {"min": 1, "max": 2},
            },
        ]},
    ]
    with pytest.raises(ValidationError, match="heading"):
        custom_config(recipe)


def oversized_recipe() -> dict:
    return {
        "genre": "comparison", "complexity": "simple",
        "groups": [{"blocks": [
            {"kind": "heading", "role": "reference", "level": 1},
            {"kind": "paragraph", "role": "interpretation"},
            {
                "kind": "table", "role": "data",
                "columns": {"min": 3, "max": 3}, "rows": {"min": 200, "max": 200},
            },
        ]}],
    }


def test_infeasible_shape_fails_before_requests_or_output_mutation(tmp_path: Path) -> None:
    config = custom_config(oversized_recipe(), 1)
    data = config.model_dump()
    data["generation"]["length_weights"] = {"short": 1}
    source = PlannedProvider()
    with pytest.raises(InputError, match="infeasible"):
        generate(Config.model_validate(data), tmp_path, provider=source)
    assert source.calls == [] and list(tmp_path.iterdir()) == []


def test_complexity_assignment_respects_recipe_capacity_without_reshuffling_other_axes() -> None:
    data = custom_config(oversized_recipe(), 2).model_dump()
    data["generation"]["length_weights"] = {"short": 0.5, "long": 0.5}
    data["generation"]["structure"]["complexity_weights"] = {"simple": 0.5, "complex": 0.5}
    config = Config.model_validate(data)
    plan = create_plan(config, run_id="run-capacity")
    assert {
        (item.length_band, item.structure_plan.complexity) for item in plan.blueprints
    } == {("short", "complex"), ("long", "simple")}
    legacy = copy.deepcopy(data)
    del legacy["generation"]["structure"]
    before = create_plan(Config.model_validate(legacy), run_id="run-capacity")
    assert [
        (item.content_id, item.topic_id, item.genre, item.length_band) for item in before.blueprints
    ] == [
        (item.content_id, item.topic_id, item.genre, item.length_band) for item in plan.blueprints
    ]


def test_recipe_pool_references_and_built_in_ids_are_checked_before_generation() -> None:
    data = custom_config(custom_recipe(), 1).model_dump()
    data["generation"]["structure"]["recipe_weights"]["explainer"]["simple"] = {
        "procedure-simple-a": 1,
    }
    with pytest.raises(InputError, match="incompatible"):
        create_plan(Config.model_validate(data), run_id="run-wrong-pool")
    data = custom_config(custom_recipe(), 1).model_dump()
    data["generation"]["structure"]["recipes"]["explainer-simple-a"] = custom_recipe()
    with pytest.raises(InputError, match="replace"):
        create_plan(Config.model_validate(data), run_id="run-shadow")


@pytest.mark.parametrize("raw", [{}, {"item-000001": {"level:simple": "bad"}}])
def test_invalid_structure_solver_output_has_no_random_fallback(monkeypatch, raw) -> None:
    monkeypatch.setattr(nx, "network_simplex", lambda *_: (0, raw))
    with pytest.raises(IntegrityError, match="solver"):
        create_plan(custom_config(custom_recipe(), 1), run_id="run-solver")


def test_structure_solver_error_is_explicit(monkeypatch) -> None:
    def fail(*_):
        raise nx.NetworkXError("injected solver error")
    monkeypatch.setattr(nx, "network_simplex", fail)
    with pytest.raises(IntegrityError, match="fallback"):
        create_plan(custom_config(custom_recipe(), 1), run_id="run-solver")


def test_complexity_stratification_retains_the_optimal_transportation_objective() -> None:
    data = configuration(5)
    data["generation"]["structure"] = {
        "complexity_weights": {"simple": 0.4, "complex": 0.6},
    }
    plan = create_plan(Config.model_validate(data), run_id="run-balance")
    contents = tuple(structured_content(item) for item in plan.blueprints)
    config = RenderConfig(weights={"md": 0.4, "html": 0.6})
    allocation = allocate(contents, config, seed=1729)
    groups = Counter(
        (
            item.blueprint.topic_id, item.blueprint.length_band,
            item.blueprint.structure_plan.complexity,
        )
        for item in contents
    )
    targets = Counter(item.format for item in allocation.items)
    best = None
    for formats in itertools.product(("md", "html"), repeat=len(contents)):
        if Counter(formats) != targets:
            continue
        actual = Counter(
            (
                (
                    item.blueprint.topic_id, item.blueprint.length_band,
                    item.blueprint.structure_plan.complexity,
                ),
                format,
            )
            for item, format in zip(contents, formats, strict=True)
        )
        cost = sum(
            abs(actual[group, format] - size * Fraction(share))
            for group, size in groups.items() for format, share in config.weights.items()
        )
        best = cost if best is None else min(best, cost)
    assert allocation.objective == best


@pytest.mark.parametrize("mutation", ["missing", "mix", "counts", "implicit", "profile", "format"])
def test_frozen_layout_margins_and_capabilities_cannot_be_forged(mutation: str) -> None:
    config = custom_config(custom_recipe(), 4)
    contents = tuple(
        structured_content(item) for item in create_plan(config, run_id="run-layout").blueprints
    )
    render = RenderConfig.model_validate({
        "weights": {"docx": 1},
        "layout_weights": {"docx": {"single-column": 0.5, "two-column": 0.5}},
    })
    raw = json.loads(allocate(contents, render).model_dump_json())
    if mutation == "missing":
        raw["items"][0].pop("layout_plan")
    elif mutation == "mix":
        raw["config"]["layout_weights"]["docx"] = {"single-column": "1"}
    elif mutation == "counts":
        raw["layout_counts"]["docx"] = {}
    elif mutation == "implicit":
        raw["config"].pop("layout_weights")
    elif mutation == "profile":
        raw["items"][0]["layout_profile"] = (
            "complex" if raw["items"][0]["layout_profile"] == "baseline" else "baseline"
        )
    else:
        raw["items"][0]["layout_plan"]["recipe"] = "semantic"
    with pytest.raises(ValidationError, match="layout|Layout"):
        AllocationPlan.model_validate_json(json.dumps(raw))


def test_tiny_corpus_reports_unrepresented_complexity_and_layout_targets() -> None:
    config = custom_config(custom_recipe(), 1)
    data = config.model_dump()
    data["generation"]["structure"]["complexity_weights"] = {"simple": 0.9, "moderate": 0.1}
    data["rendering"] = {
        "weights": {"docx": 1},
        "layout_weights": {"docx": {"single-column": 0.9, "two-column": 0.1}},
    }
    config = Config.model_validate(data)
    result = preview(config)
    assert any("complexity: moderate" in str(warning) for warning in result["details"]["warnings"])
    plan = create_plan(config, run_id="run-tiny")
    allocation = allocate((structured_content(plan.blueprints[0]),), config.rendering)
    assert any("two-column" in warning for warning in allocation.warnings)


def incompatible_layout_config(format: str, layout: str) -> Config:
    block = (
        {
            "kind": "table", "role": "comparison",
            "columns": {"min": 3, "max": 3}, "rows": {"min": 3, "max": 3},
        }
        if layout == "two-column" else
        {"kind": "ordered_list", "role": "steps", "items": {"min": 5, "max": 5}}
    )
    recipe = {
        "genre": "comparison" if layout == "two-column" else "procedure",
        "complexity": "simple", "groups": [{"blocks": [block]}],
    }
    data = custom_config(recipe, 1).model_dump()
    data["generation"]["length_weights"] = {"short": 1}
    data["rendering"] = {"weights": {format: 1}, "layout_weights": {format: {layout: 1}}}
    return Config.model_validate(data)


@pytest.mark.parametrize(("format", "layout"), [
    ("pdf", "two-column"), ("html", "sectioned"),
    ("xlsx", "sectioned"), ("pptx", "section-led"),
])
def test_incompatible_native_shape_fails_before_authoring_or_run_creation(
    tmp_path: Path, format: str, layout: str,
) -> None:
    source = PlannedProvider()
    with pytest.raises(InputError, match="requires"):
        run(incompatible_layout_config(format, layout), tmp_path, provider=source)
    assert source.calls == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(("format", "layout"), [("pdf", "two-column"), ("pptx", "section-led")])
def test_render_only_preflight_checks_actual_content_before_freezing_allocation(
    tmp_path: Path, format: str, layout: str,
) -> None:
    config = incompatible_layout_config(format, layout)
    generated = generate(config, tmp_path, provider=PlannedProvider())
    assert generated.status == "content_ready", generated.failures
    directory = tmp_path / generated.run_id
    with pytest.raises(InputError, match="requires"):
        render(directory, config.rendering)
    assert not (directory / "allocation.json").exists()
    assert not (directory / "artifacts.pending").exists()
