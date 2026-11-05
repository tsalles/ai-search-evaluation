from decimal import Decimal

from pydantic import JsonValue

from docgen.errors import InputError
from docgen.models import Content
from docgen.profiles import WORD_BANDS, acceptance_word_band
from docgen.records import LengthBand
from docgen.structure_models import StructureSlot
from docgen.text import word_count


def band_policy(band: LengthBand, tolerance: Decimal | None) -> dict[str, int]:
    low, high = WORD_BANDS[band]
    accepted_low, accepted_high = acceptance_word_band(band, tolerance)
    return {
        "nominal_min": low, "nominal_max": high,
        "accepted_min": accepted_low, "accepted_max": accepted_high,
        "target_words": (low + high) // 2,
    }


def length_policy(tolerance: Decimal | None) -> dict[str, JsonValue]:
    return {
        "tolerance": float(tolerance or 0),
        "bands": {
            band: {key: value for key, value in band_policy(band, tolerance).items()}
            for band in WORD_BANDS
        },
    }


def content_length_details(
    contents: tuple[Content, ...], tolerance: Decimal | None,
) -> dict[str, JsonValue]:
    items: list[JsonValue] = []
    for content in contents:
        band = content.blueprint.length_band
        count = word_count(content)
        low, high = WORD_BANDS[band]
        accepted_low, accepted_high = acceptance_word_band(band, tolerance)
        accepted = accepted_low <= count <= accepted_high
        items.append({
            "content_id": content.blueprint.content_id,
            "length_band": band, "word_count": count,
            "in_accepted_range": accepted,
            "used_tolerance": accepted and not low <= count <= high,
        })
    return {
        **length_policy(tolerance),
        "items": items,
    }


def allocate_word_budgets(
    slots: tuple[StructureSlot, ...], band: LengthBand,
) -> tuple[int, int, tuple[StructureSlot, ...]]:
    low, high = WORD_BANDS[band]
    target, title = (low + high) // 2, 6
    budgets, ceilings = [], []
    for slot in slots:
        if slot.kind == "heading":
            base = ceiling = 4
        elif slot.kind == "table":
            base = ceiling = (
                (slot.columns or 0) * ((slot.rows or 0) + 1) * (2 if band == "short" else 3)
            )
        elif slot.item_levels:
            base, ceiling = 6 * len(slot.item_levels), 90 * len(slot.item_levels)
        elif slot.kind == "callout":
            base, ceiling = 10, 140
        else:
            base, ceiling = 8, 220
        budgets.append(base)
        ceilings.append(ceiling)
    remaining = target - title - sum(budgets)
    if remaining < 0 or target > title + sum(ceilings):
        raise InputError(
            f"Length-aware structure is infeasible for {band}: its text/cell budgets "
            f"cannot accommodate the {target}-word target."
        )
    active = [index for index in range(len(slots)) if budgets[index] < ceilings[index]]
    while remaining and active:
        share = max(1, remaining // len(active))
        for index in active:
            addition = min(share, ceilings[index] - budgets[index], remaining)
            budgets[index] += addition
            remaining -= addition
        active = [index for index in active if budgets[index] < ceilings[index]]
    if remaining:
        raise InputError("Length-aware word allocation cannot satisfy its frozen target.")
    return target, title, tuple(
        slot.model_copy(update={"word_budget": budget})
        for slot, budget in zip(slots, budgets, strict=True)
    )
