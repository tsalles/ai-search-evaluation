import random
from collections import defaultdict
from pathlib import Path

from pydantic import JsonValue

from docgen.allocation import AllocationPlan, Assignment
from docgen.models import Content, serialize
from docgen.persistence import atomic_write, safe_child
from docgen.planning import derived_seed
from docgen.results import Result
from docgen.structures import structure_details


def review_details(
    allocation: AllocationPlan, contents: tuple[Content, ...] = (),
) -> dict[str, JsonValue]:
    blueprints = {content.blueprint.content_id: content.blueprint for content in contents}
    varied = allocation.recipe_counts is not None or allocation.layout_counts is not None
    groups: dict[str, list[Assignment]] = defaultdict(list)
    for item in sorted(allocation.items, key=lambda selected: selected.content_id):
        blueprint = blueprints.get(item.content_id)
        complexity = (
            blueprint.structure_plan.complexity
            if blueprint is not None and blueprint.structure_plan is not None else "legacy"
        )
        layout = item.layout_plan.recipe if item.layout_plan is not None else item.layout_profile
        key = f"{item.format}/{complexity}/{layout}" if varied else item.format
        groups[key].append(item)
    randomizer = random.Random(derived_seed(
        allocation.seed, "review-sample-v2" if varied else "review-sample-v1",
    ))
    selected = []
    for name in sorted(groups):
        randomizer.shuffle(groups[name])
        selected.append(groups[name].pop())
    count = min(len(allocation.items), max(len(groups), (len(allocation.items) + 49) // 50))
    remaining = [item for name in sorted(groups) for item in groups[name]]
    randomizer.shuffle(remaining)
    selected.extend(remaining[:count - len(selected)])
    sample: list[JsonValue] = [
        {"content_id": item.content_id, "format": item.format, "filename": item.filename}
        for item in sorted(selected, key=lambda chosen: chosen.content_id)
    ]
    return {
        "status": "human_review_pending",
        "reviewer": None,
        "method": (
            "seeded-format-structure-layout-v1" if varied else "seeded-format-stratified-v1"
        ),
        "sample_count": count,
        "sample": sample,
    }


def corpus_structure_details(
    allocation: AllocationPlan, contents: tuple[Content, ...], verified: set[str],
) -> dict[str, JsonValue]:
    return {
        "accepted": structure_details(tuple(content.blueprint for content in contents)),
        "verified": structure_details(tuple(
            content.blueprint for content in contents if content.blueprint.content_id in verified
        )),
        "complexity_by_format": {
            fmt: {name: count for name, count in counts.items()}
            for fmt, counts in allocation.structure_counts.items()
        },
        "recipes_by_format": {
            fmt: {name: count for name, count in counts.items()}
            for fmt, counts in (allocation.recipe_counts or {}).items()
        },
        "layouts_by_format": {
            fmt: {name: count for name, count in counts.items()}
            for fmt, counts in (allocation.layout_counts or {}).items()
        },
        "verified_layouts_by_format": {
            fmt: {
                name: sum(
                    item.format == fmt and item.content_id in verified
                    and item.layout_plan is not None and item.layout_plan.recipe == name
                    for item in allocation.items
                )
                for name in counts
            }
            for fmt, counts in (allocation.layout_counts or {}).items()
        },
        "warnings": list(allocation.warnings),
    }


def save_summary(directory: Path, result: Result) -> Result:
    path = safe_child(safe_child(directory, "reports"), "run-summary.json")
    updated = result.model_copy(
        update={
            "reports": {**result.reports, "run_summary": str(path)},
        }
    )
    atomic_write(path, serialize(updated), overwrite=True)
    return updated
