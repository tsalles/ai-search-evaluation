from collections import Counter
from decimal import Decimal

from pydantic import JsonValue

from docgen.config import RenderConfig
from docgen.errors import InputError
from docgen.models import Blueprint, Content, Format
from docgen.sampling import derived_seed, expand, quotas
from docgen.structure_models import LAYOUT_CAPABILITIES, LayoutName, LayoutPlan

DEFAULT_LAYOUTS: dict[Format, LayoutName] = {
    "pdf": "single-column", "docx": "single-column", "pptx": "flow",
    "xlsx": "sectioned", "html": "linear", "md": "semantic",
}


def layout_pool(config: RenderConfig, format: Format) -> dict[LayoutName, Decimal]:
    return (config.layout_weights or {}).get(format, {DEFAULT_LAYOUTS[format]: Decimal(1)})


def check_layout_shape(
    recipe: LayoutName, *, primary_headings: int, prose_units: int, label: str,
) -> None:
    if recipe in {"section-led", "sectioned"} and primary_headings == 0:
        raise InputError(f"Native layout {recipe} requires primary headings: {label}.")
    if recipe == "two-column" and prose_units < 2:
        raise InputError(
            f"Native two-column layout requires at least two prose/list units: {label}."
        )


def preflight_layouts(blueprints: tuple[Blueprint, ...], config: RenderConfig) -> None:
    if config.layout_weights is None:
        return
    for blueprint in blueprints:
        plan = blueprint.structure_plan
        if plan is None:
            continue
        for format, count in quotas(len(blueprints), config.weights).items():
            if count == 0:
                continue
            for recipe, size in quotas(count, layout_pool(config, format)).items():
                if size > 0:
                    check_layout_shape(
                        recipe,
                        primary_headings=sum(slot.level == 1 for slot in plan.slots),
                        prose_units=sum(
                            len(slot.item_levels) or int(slot.kind in {"paragraph", "callout"})
                            for slot in plan.slots
                        ),
                        label=blueprint.content_id,
                    )


def plan_layouts(
    contents: dict[Format, tuple[Content, ...]], config: RenderConfig, *, seed: int,
) -> dict[str, LayoutPlan]:
    if config.layout_weights is None:
        return {}
    result = {}
    for format, items in sorted(contents.items()):
        names = expand(
            quotas(len(items), layout_pool(config, format)),
            derived_seed(seed, f"native-layouts-v1:{format}"),
        )
        for content, recipe in zip(
            sorted(items, key=lambda item: item.blueprint.content_id), names, strict=True,
        ):
            check_layout_shape(
                recipe,
                primary_headings=sum(block.level == 1 for block in content.blocks),
                prose_units=sum(
                    len(block.items or ()) or int(block.kind in {"paragraph", "callout"})
                    for block in content.blocks
                ),
                label=content.blueprint.content_id,
            )
            result[content.blueprint.content_id] = LayoutPlan(recipe=recipe)
    return result


def layout_preview(counts: dict[Format, int], config: RenderConfig) -> dict[str, JsonValue]:
    return {
        format: {
            "quotas": {
                name: count for name, count in quotas(size, layout_pool(config, format)).items()
            },
            "supported": list(LAYOUT_CAPABILITIES[format]),
        }
        for format, size in counts.items()
    }


def layout_counts(plans: tuple[LayoutPlan, ...]) -> dict[str, int]:
    return dict(Counter(plan.recipe for plan in plans))
