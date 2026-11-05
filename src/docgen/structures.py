import hashlib
import random
from collections import Counter, defaultdict
from decimal import Decimal
from functools import lru_cache

import networkx as nx
from pydantic import JsonValue, StrictInt, TypeAdapter, ValidationError

from docgen.config import StructureConfig
from docgen.errors import InputError, IntegrityError
from docgen.models import Blueprint, Content, Genre, LengthBand, serialize
from docgen.profiles import WORD_BANDS
from docgen.sampling import derived_seed, expand, quotas
from docgen.structure_models import (
    Complexity,
    CountRange,
    RecipeBlock,
    RecipeGroup,
    StructurePlan,
    StructureRecipe,
    StructureSlot,
    shape_metrics,
)
from docgen.word_budgets import allocate_word_budgets


@lru_cache(maxsize=1)
def builtin_recipes() -> dict[str, StructureRecipe]:
    def paragraph(role: str) -> RecipeBlock:
        return RecipeBlock(kind="paragraph", role=role)

    def heading(role: str, level: int = 1, *, question: bool = False) -> RecipeBlock:
        return RecipeBlock(kind="heading", role=role, level=level, question=question)

    def group(*blocks: RecipeBlock, minimum: int = 1, maximum: int = 1) -> RecipeGroup:
        return RecipeGroup(blocks=blocks, repeat=CountRange(min=minimum, max=maximum))

    def listing(*, ordered: bool = False, nested: bool = False) -> RecipeBlock:
        return RecipeBlock(
            kind="ordered_list" if ordered else "unordered_list",
            role="procedure steps and responsibilities" if ordered else "supporting considerations",
            items=CountRange(min=5 if ordered else 2, max=8 if ordered else 4),
            subitems=CountRange(min=1, max=3) if nested else None,
        )

    def table(*, wide: bool = False) -> RecipeBlock:
        return RecipeBlock(
            kind="table", role="criteria and reference data",
            columns=CountRange(min=5 if wide else 3, max=6 if wide else 4),
            rows=CountRange(min=3, max=5),
        )

    result: dict[str, StructureRecipe] = {}
    genres: tuple[Genre, ...] = ("explainer", "procedure", "faq", "comparison")
    levels: tuple[Complexity, ...] = ("simple", "moderate", "complex")
    for genre in genres:
        for complexity in levels:
            depth = 1 if complexity == "simple" else 2
            intro = group(heading("scope and purpose"), paragraph("overview and context"))
            if genre == "explainer":
                body = group(
                    heading("a distinct explanatory aspect", depth),
                    paragraph("explanation with conditions"),
                    minimum=3, maximum=5,
                )
            elif genre == "procedure":
                body = group(
                    heading("procedure", depth),
                    listing(ordered=True, nested=complexity == "complex"),
                    paragraph("completion and responsibilities"),
                )
            elif genre == "faq":
                body = group(
                    heading("a distinct reader question", depth, question=True),
                    paragraph("direct answer and relevant conditions"),
                    minimum=4, maximum=6,
                )
            else:
                body = group(
                    heading("comparison criteria", depth), table(wide=complexity == "complex"),
                )
            extras: tuple[RecipeGroup, ...] = (
                (
                    group(
                        paragraph("a distinct interpretation, condition, or trade-off"),
                        minimum=3, maximum=5,
                    ),
                )
                if genre == "comparison" else ()
            )
            if complexity == "complex":
                extras += (
                    group(
                        heading("detailed exceptions", 3),
                        paragraph("explanation of exceptions"),
                        RecipeBlock(kind="callout", role="important exception or caution"),
                    ),
                )
                if genre != "procedure":
                    extras += (group(listing(nested=True)),)
            closing = RecipeGroup(
                blocks=(paragraph("closing guidance"),), optional=True,
            )
            result[f"{genre}-{complexity}-a"] = StructureRecipe(
                genre=genre, complexity=complexity, groups=(intro, body, *extras, closing),
            )
            reference = group(listing(), paragraph("reference context before the main content"))
            result[f"{genre}-{complexity}-b"] = StructureRecipe(
                genre=genre, complexity=complexity,
                groups=(intro, reference, body, *extras, closing),
            )
    return result


def recipe_catalog(config: StructureConfig) -> dict[str, StructureRecipe]:
    catalog = dict(builtin_recipes())
    if set(config.recipes) & catalog.keys():
        raise InputError("Custom recipe IDs cannot replace versioned built-in recipes.")
    catalog.update(config.recipes)
    for genre, levels in config.recipe_weights.items():
        for complexity, weights in levels.items():
            for name in weights:
                recipe = catalog.get(name)
                if recipe is None or (recipe.genre, recipe.complexity) != (genre, complexity):
                    raise InputError(
                        f"Unknown or incompatible structure recipe: {name} "
                        f"for {genre}/{complexity}."
                    )
    return catalog


def recipe_pool(
    config: StructureConfig, genre: Genre, complexity: Complexity,
) -> dict[str, Decimal]:
    configured = config.recipe_weights.get(genre, {}).get(complexity)
    if configured is not None:
        return dict(configured)
    return {
        f"{genre}-{complexity}-a": Decimal("0.5"),
        f"{genre}-{complexity}-b": Decimal("0.5"),
    }


def minimum_word_capacity(recipe: StructureRecipe) -> int:
    return sum(
        (slot.columns or 0) * ((slot.rows or 0) + 1)
        if slot.kind == "table" else len(slot.item_levels) or 1
        for slot in recipe.envelope(maximum=True)
    ) + 1


def resolve_recipe(
    name: str, recipe: StructureRecipe, seed: int, *, length_band: LengthBand | None = None,
) -> StructurePlan:
    randomizer = random.Random(seed)
    slots: list[StructureSlot] = []
    for group in recipe.groups:
        if group.optional and (length_band == "short" or not randomizer.getrandbits(1)):
            continue
        repeats = (
            group.repeat.min if length_band == "short" else
            group.repeat.max if length_band == "long" else
            randomizer.randint(group.repeat.min, group.repeat.max)
        )
        for _ in range(repeats):
            for block in group.blocks:
                def sample(value: CountRange | None) -> int | None:
                    if value is None:
                        return None
                    if length_band == "short":
                        return value.min
                    maximum = (
                        min(value.max, value.min + 1) if length_band == "medium" else value.max
                    )
                    return randomizer.randint(value.min, maximum)

                items, subitems = sample(block.items) or 0, sample(block.subitems) or 0
                parent = randomizer.randrange(items) if items else 0
                item_levels = tuple(
                    level for index in range(items)
                    for level in ((1,) + (2,) * subitems if index == parent else (1,))
                )
                slots.append(StructureSlot(
                    id=f"block-{len(slots) + 1:03}", role=block.role, kind=block.kind,
                    level=block.level, question=block.question, item_levels=item_levels,
                    columns=sample(block.columns), rows=sample(block.rows),
                ))
    if length_band is not None:
        target, title, budgeted = allocate_word_budgets(tuple(slots), length_band)
        return StructurePlan(
            version="2", recipe_id=name, recipe_hash=hashlib.sha256(serialize(recipe)).hexdigest(),
            complexity=recipe.complexity, slots=budgeted, target_words=target, title_words=title,
        )
    return StructurePlan(
        recipe_id=name, recipe_hash=hashlib.sha256(serialize(recipe)).hexdigest(),
        complexity=recipe.complexity, slots=tuple(slots),
    )


def plan_structures(
    blueprints: tuple[Blueprint, ...], config: StructureConfig, *, seed: int,
) -> tuple[Blueprint, ...]:
    catalog = recipe_catalog(config)
    targets = quotas(len(blueprints), config.complexity_weights)
    graph: nx.DiGraph[str] = nx.DiGraph()
    resolved: dict[tuple[str, str], StructurePlan] = {}
    infeasible_reasons: list[str] = []
    for complexity, count in targets.items():
        if count:
            graph.add_node(f"level:{complexity}", demand=count)
    randomizer = random.Random(derived_seed(seed, "structure-levels-v1"))
    for blueprint in blueprints:
        key = blueprint.content_id
        graph.add_node(key, demand=-1)
        for complexity, count in targets.items():
            if not count:
                continue
            pool = recipe_pool(config, blueprint.genre, complexity)
            maximum = WORD_BANDS[blueprint.length_band][1]
            eligible = all(
                minimum_word_capacity(catalog[name]) <= maximum
                for name, share in pool.items() if share > 0
            )
            if config.length_aware:
                eligible = True
                for name, share in pool.items():
                    if share == 0:
                        continue
                    try:
                        resolved[key, name] = resolve_recipe(
                            name, catalog[name],
                            derived_seed(seed, f"structure-slots-v1:{key}"),
                            length_band=blueprint.length_band,
                        )
                    except InputError as error:
                        eligible = False
                        if len(infeasible_reasons) < 3:
                            infeasible_reasons.append(f"{key}/{name}: {error}")
            if eligible:
                graph.add_edge(
                    key, f"level:{complexity}", capacity=1,
                    weight=randomizer.randrange(2**31),
                )
    try:
        _, raw = nx.network_simplex(graph)
        flow = TypeAdapter(dict[str, dict[str, StrictInt]]).validate_python(raw, strict=True)
        if any(source not in flow or target not in flow[source] for source, target in graph.edges):
            raise IntegrityError("Structure solver returned an incomplete assignment.")
    except nx.NetworkXUnfeasible as exc:
        raise InputError(
            "Structure complexity quotas are infeasible for the genre/length recipe pools. "
            "Every positive-share recipe in a pool must fit its assigned word bands."
            + (" " + " ".join(infeasible_reasons) if infeasible_reasons else "")
        ) from exc
    except (nx.NetworkXException, ValidationError) as exc:
        raise IntegrityError(
            "Structure planning solver failed; no random fallback was used."
        ) from exc
    groups: dict[tuple[Genre, Complexity], list[Blueprint]] = defaultdict(list)
    for blueprint in blueprints:
        selected = [
            complexity for complexity, count in targets.items()
            if count and flow[blueprint.content_id].get(f"level:{complexity}") == 1
        ]
        if len(selected) != 1:
            raise IntegrityError("Structure solver returned an incomplete assignment.")
        groups[blueprint.genre, selected[0]].append(blueprint)
    planned = {}
    for (genre, complexity), items in sorted(groups.items()):
        names = expand(
            quotas(len(items), recipe_pool(config, genre, complexity)),
            derived_seed(seed, f"structure-recipes-v1:{genre}:{complexity}"),
        )
        for blueprint, name in zip(items, names, strict=True):
            structure = (
                resolved[blueprint.content_id, name] if config.length_aware else
                resolve_recipe(
                    name, catalog[name],
                    derived_seed(seed, f"structure-slots-v1:{blueprint.content_id}"),
                )
            )
            planned[blueprint.content_id] = Blueprint.model_validate({
                **blueprint.model_dump(), "structure_plan": structure,
            })
    return tuple(planned[blueprint.content_id] for blueprint in blueprints)


def validate_structure(content: Content) -> None:
    plan = content.blueprint.structure_plan
    if plan is None:
        return
    if len(content.blocks) != len(plan.slots):
        raise ValueError("Content block count differs from its frozen structure plan.")
    for block, slot in zip(content.blocks, plan.slots, strict=True):
        if (block.id, block.kind, block.level) != (slot.id, slot.kind, slot.level):
            raise ValueError(f"Structure slot ID, kind, level or order differs: {slot.id}.")
        if tuple(item.level for item in block.items or ()) != slot.item_levels:
            raise ValueError(f"List structure differs from its frozen plan: {slot.id}.")
        if slot.question and not (block.text and block.text.endswith("?")):
            raise ValueError(f"Planned question heading must end in ?: {slot.id}.")
        if block.table is not None and (
            len(block.table.columns), len(block.table.rows)
        ) != (slot.columns, slot.rows):
            raise ValueError(
                f"Table dimensions differ from the frozen plan: {slot.id}. "
                f"Expected {slot.rows} data rows and {slot.columns} columns; "
                "the header is separate from the data rows."
            )


def structure_details(blueprints: tuple[Blueprint, ...]) -> dict[str, JsonValue]:
    plans = [item.structure_plan for item in blueprints if item.structure_plan is not None]
    counts: Counter[str] = Counter(plan.complexity for plan in plans)
    return {
        "complexity_quotas": {
            name: counts[name] for name in ("simple", "moderate", "complex")
        },
        "recipe_counts": dict(Counter(plan.recipe_id for plan in plans)),
        "distinct_signatures": len({plan.signature for plan in plans}),
        "items": [
            {
                "content_id": item.content_id,
                "complexity": item.structure_plan.complexity,
                "recipe_id": item.structure_plan.recipe_id,
                "signature": item.structure_plan.signature,
                "metrics": {
                    key: value for key, value in shape_metrics(item.structure_plan.slots).items()
                },
                **(
                    {
                        "word_target": item.structure_plan.target_words,
                        "title_words": item.structure_plan.title_words,
                        "slot_word_budgets": {
                            slot.id: slot.word_budget for slot in item.structure_plan.slots
                        },
                    }
                    if item.structure_plan.version == "2" else {}
                ),
            }
            for item in blueprints if item.structure_plan is not None
        ],
    }
