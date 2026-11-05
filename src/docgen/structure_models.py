import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, model_validator

from docgen.records import Format, Genre, Identifier, Profile, Record, Text

Complexity = Literal["simple", "moderate", "complex"]
BlockKind = Literal["heading", "paragraph", "ordered_list", "unordered_list", "table", "callout"]
LayoutName = Literal[
    "single-column", "two-column", "flow", "section-led",
    "compact", "sectioned", "linear", "semantic",
]
LAYOUT_CAPABILITIES: dict[Format, tuple[LayoutName, ...]] = {
    "pdf": ("single-column", "two-column"),
    "docx": ("single-column", "two-column"),
    "pptx": ("flow", "section-led"),
    "xlsx": ("compact", "sectioned"),
    "html": ("linear", "sectioned"),
    "md": ("semantic",),
}


class CountRange(Record):
    min: Annotated[StrictInt, Field(ge=0, le=200)]
    max: Annotated[StrictInt, Field(ge=0, le=200)]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.min > self.max:
            raise ValueError("Range minimum must not exceed maximum.")
        return self


class StructureSlot(Record):
    legacy_optional_fields = ("word_budget",)
    id: Identifier
    role: Text
    kind: BlockKind
    level: Annotated[StrictInt, Field(ge=1, le=3)] | None = None
    question: StrictBool = False
    item_levels: tuple[Annotated[StrictInt, Field(ge=1, le=2)], ...] = ()
    columns: Annotated[StrictInt, Field(ge=1, le=8)] | None = None
    rows: Annotated[StrictInt, Field(ge=1, le=200)] | None = None
    word_budget: Annotated[StrictInt, Field(ge=1, le=1600)] | None = None

    @model_validator(mode="after")
    def payload(self) -> Self:
        if self.kind == "heading":
            valid = self.level is not None and not self.item_levels and self.columns is None
        elif self.kind in {"ordered_list", "unordered_list"}:
            valid = (
                self.level is None and 1 <= len(self.item_levels) <= 100
                and self.item_levels[0] == 1 and self.columns is None
            )
        elif self.kind == "table":
            valid = (
                self.columns is not None and self.rows is not None
                and self.level is None and not self.item_levels
            )
        else:
            valid = self.level is None and not self.item_levels and self.columns is None
        if not valid or (self.kind != "table" and self.rows is not None):
            raise ValueError("Structure slot has fields incompatible with its block kind.")
        if self.question and self.kind != "heading":
            raise ValueError("Only a heading can be a question.")
        return self


def shape_metrics(slots: tuple[StructureSlot, ...]) -> dict[str, int]:
    tables = [slot for slot in slots if slot.kind == "table"]
    return {
        "blocks": len(slots),
        "headings": sum(slot.kind == "heading" for slot in slots),
        "heading_depth": max((slot.level or 0 for slot in slots), default=0),
        "list_depth": max((level for slot in slots for level in slot.item_levels), default=0),
        "tables": len(tables),
        "table_columns": max((slot.columns or 0 for slot in tables), default=0),
        "table_rows": max((slot.rows or 0 for slot in tables), default=0),
        "callouts": sum(slot.kind == "callout" for slot in slots),
    }


def validate_shape(slots: tuple[StructureSlot, ...], genre: Genre, level: Complexity) -> None:
    metrics = shape_metrics(slots)
    last = 0
    for slot in slots:
        if slot.level is not None:
            if slot.level > last + 1:
                raise ValueError("Recipe heading levels cannot skip a level.")
            last = slot.level
    if genre == "explainer":
        valid = metrics["headings"] >= 3
    elif genre == "procedure":
        valid = sum(
            slot.item_levels.count(1) for slot in slots if slot.kind == "ordered_list"
        ) >= 5
    elif genre == "faq":
        valid = sum(
            slot.question and following.kind == "paragraph"
            for slot, following in zip(slots, slots[1:], strict=False)
        ) >= 4
    else:
        valid = any(
            (slot.columns or 0) >= 3 and (slot.rows or 0) >= 3 for slot in slots
        )
    if not valid:
        raise ValueError(f"Recipe does not guarantee the {genre} genre minimums.")
    features = sum((
        metrics["heading_depth"] >= 2,
        metrics["list_depth"] == 2,
        metrics["tables"] >= 2,
        metrics["table_columns"] >= 5,
        metrics["callouts"] > 0,
    ))
    if level == "simple" and features:
        raise ValueError("Simple recipes require flat headings/lists, at most one narrow table.")
    if level == "moderate" and (features < 1 or metrics["heading_depth"] > 2):
        raise ValueError(
            "Moderate recipes require a structural feature and heading depth at most two."
        )
    if level == "complex" and features < 2:
        raise ValueError("Complex recipes require at least two distinct structural features.")


class RecipeBlock(Record):
    kind: BlockKind
    role: Text
    level: Annotated[StrictInt, Field(ge=1, le=3)] | None = None
    question: StrictBool = False
    items: CountRange | None = None
    subitems: CountRange | None = None
    columns: CountRange | None = None
    rows: CountRange | None = None

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.items is not None and (
            self.items.min < 1 or self.items.max + (self.subitems.max if self.subitems else 0) > 100
        ):
            raise ValueError("Recipe lists require one to one hundred total items.")
        if self.subitems is not None and self.items is None:
            raise ValueError("Subitems require top-level list items.")
        if self.columns is not None and (self.columns.min < 1 or self.columns.max > 8):
            raise ValueError("Recipe tables require one to eight columns.")
        if self.rows is not None and self.rows.min < 1:
            raise ValueError("Recipe tables require at least one data row.")
        self.slot("check", maximum=False)
        if self.kind not in {"ordered_list", "unordered_list"} and (
            self.items is not None or self.subitems is not None
        ):
            raise ValueError("Only lists accept item ranges.")
        return self

    def slot(self, identifier: str, *, maximum: bool) -> StructureSlot:
        def bound(value: CountRange | None) -> int | None:
            return (value.max if maximum else value.min) if value is not None else None

        items = bound(self.items) or 0
        subitems = bound(self.subitems) or 0
        levels = (1,) + (2,) * subitems + (1,) * (items - 1) if items else ()
        return StructureSlot(
            id=identifier, role=self.role, kind=self.kind, level=self.level,
            question=self.question, item_levels=levels,
            columns=bound(self.columns), rows=bound(self.rows),
        )


class RecipeGroup(Record):
    blocks: Annotated[tuple[RecipeBlock, ...], Field(min_length=1, max_length=20)]
    repeat: CountRange = CountRange(min=1, max=1)
    optional: StrictBool = False

    @model_validator(mode="after")
    def repetitions(self) -> Self:
        if self.repeat.min < 1 or self.repeat.max > 20:
            raise ValueError("Recipe groups repeat between one and twenty times.")
        return self


class StructureRecipe(Record):
    genre: Genre
    complexity: Complexity
    groups: Annotated[tuple[RecipeGroup, ...], Field(min_length=1, max_length=30)]

    def envelope(self, *, maximum: bool) -> tuple[StructureSlot, ...]:
        blocks = [
            block
            for group in self.groups if maximum or not group.optional
            for _ in range(group.repeat.max if maximum else group.repeat.min)
            for block in group.blocks
        ]
        return tuple(
            block.slot(f"block-{index + 1:03}", maximum=maximum)
            for index, block in enumerate(blocks)
        )

    @model_validator(mode="after")
    def guaranteed_shape(self) -> Self:
        smallest, largest = self.envelope(maximum=False), self.envelope(maximum=True)
        if not smallest or len(largest) > 100:
            raise ValueError(
                "Every recipe instance must contain between one and one hundred blocks."
            )
        validate_shape(smallest, self.genre, self.complexity)
        validate_shape(largest, self.genre, self.complexity)
        states = {0}
        for group in self.groups:
            possible = set(states) if group.optional else set()
            current = set(states)
            for repeat in range(1, group.repeat.max + 1):
                for block in group.blocks:
                    if block.level is not None:
                        if any(block.level > previous + 1 for previous in current):
                            raise ValueError("Optional/repeated groups can skip a heading level.")
                        current = {block.level}
                if repeat >= group.repeat.min:
                    possible.update(current)
            states = possible
        return self


class StructurePlan(Record):
    legacy_optional_fields = ("target_words", "title_words")
    version: Literal["1", "2"] = "1"
    recipe_id: Identifier
    recipe_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    complexity: Complexity
    slots: Annotated[tuple[StructureSlot, ...], Field(min_length=1, max_length=100)]
    target_words: Annotated[StrictInt, Field(ge=1, le=1600)] | None = None
    title_words: Annotated[StrictInt, Field(ge=1, le=20)] | None = None

    @property
    def signature(self) -> str:
        shape = [
            slot.model_dump(mode="json", exclude={"id", "role", "question", "word_budget"})
            for slot in self.slots
        ]
        return hashlib.sha256(
            json.dumps(shape, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @model_validator(mode="after")
    def unique_slots(self) -> Self:
        if len({slot.id for slot in self.slots}) != len(self.slots):
            raise ValueError("Structure slot IDs must be unique.")
        if self.version == "2":
            if self.target_words is None or self.title_words is None or any(
                slot.word_budget is None for slot in self.slots
            ):
                raise ValueError("Version two structure plans require complete word budgets.")
            if self.title_words + sum(
                slot.word_budget for slot in self.slots if slot.word_budget is not None
            ) != self.target_words:
                raise ValueError("Structure word budgets must sum exactly to the target.")
        elif self.target_words is not None or self.title_words is not None or any(
            slot.word_budget is not None for slot in self.slots
        ):
            raise ValueError("Word budgets require structure plan version two.")
        return self


class LayoutPlan(Record):
    version: Literal["1"] = "1"
    recipe: LayoutName

    @property
    def profile(self) -> Profile:
        return "complex" if self.recipe == "two-column" else "baseline"
