import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Self

from pydantic import (
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from docgen.records import Format as Format
from docgen.records import Genre as Genre
from docgen.records import Identifier as Identifier
from docgen.records import LengthBand as LengthBand
from docgen.records import Profile as Profile
from docgen.records import Record as Record
from docgen.records import Text as Text
from docgen.structure_models import StructurePlan, validate_shape
from docgen.units import unit_identity

ValueKind = Literal["text", "decimal", "date", "boolean"]


class Blueprint(Record):
    legacy_optional_fields = ("structure_plan", "family_id", "required_fact_ids")
    content_id: Identifier
    ordinal: Annotated[StrictInt, Field(ge=1, le=1000)]
    topic_id: Identifier
    genre: Genre
    length_band: LengthBand
    language: Literal["pt", "en"] = "pt"
    locale: Literal["pt-BR", "en-US"] = "pt-BR"
    audience: Text = "general readers"
    scenario_id: Identifier
    structure_profile: Profile = "baseline"
    structure_plan: StructurePlan | None = None
    family_id: Identifier | None = None
    required_fact_ids: tuple[Identifier, ...] | None = None

    @model_validator(mode="after")
    def locale_matches_language(self) -> Self:
        if (self.language, self.locale) not in {("pt", "pt-BR"), ("en", "en-US")}:
            raise ValueError("Language and locale must match a supported profile.")
        if self.structure_plan is not None:
            validate_shape(self.structure_plan.slots, self.genre, self.structure_plan.complexity)
        return self


class TypedValue(Record):
    kind: ValueKind
    value: str | Decimal | date | bool

    @model_validator(mode="before")
    @classmethod
    def parse_typed_value(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        result = dict(data)
        value = result.get("value")
        kind = result.get("kind")
        if kind == "decimal":
            if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
                raise ValueError("Decimal cells require a finite numeric value.")
            try:
                number = Decimal(str(value))
            except InvalidOperation as exc:
                raise ValueError("Invalid decimal.") from exc
            if not number.is_finite() or len(number.normalize().as_tuple().digits) > 15:
                raise ValueError("Decimal precision must not exceed 15 significant digits.")
            if number != 0 and not -12 <= number.adjusted() <= 12:
                raise ValueError("Decimal magnitude is outside the portable range.")
            result["value"] = number
        elif kind == "date":
            if isinstance(value, str):
                try:
                    value = date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError("Date values must be ISO dates.") from exc
            if type(value) is not date:
                raise ValueError("Date cells require a date without time.")
            result["value"] = value
        elif kind == "boolean" and type(value) is not bool:
            raise ValueError("Boolean values must be actual Booleans.")
        elif kind == "text":
            if not isinstance(value, str) or not value.strip() or len(value) > 2048:
                raise ValueError("Text values require 1 to 2048 nonblank characters.")
        return result


class Cell(TypedValue):
    fact_id: Identifier | None = None


class Column(Record):
    id: Identifier
    name: Text
    kind: ValueKind
    unit: Text | None = None


class Table(Record):
    id: Identifier
    columns: Annotated[tuple[Column, ...], Field(min_length=1, max_length=8)]
    rows: Annotated[tuple[tuple[Cell, ...], ...], Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def rectangular_typed_table(self) -> Self:
        if len({column.id for column in self.columns}) != len(self.columns):
            raise ValueError("Table column IDs must be unique.")
        for row in self.rows:
            if len(row) != len(self.columns):
                raise ValueError("Table rows must match their column count.")
            if any(cell.kind != col.kind for cell, col in zip(row, self.columns, strict=True)):
                raise ValueError("Table cell kinds must match their columns.")
        return self


class Fact(TypedValue):
    id: Identifier
    entity: Text
    unit: Text | None = None
    display: Text
    valid_from: date | None = None
    valid_until: date | None = None

    @model_validator(mode="after")
    def valid_interval(self) -> Self:
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise ValueError("Fact validity interval is reversed.")
        return self


class ScenarioFamily(Record):
    legacy_optional_fields = ("domain",)
    id: Identifier
    domain: Literal["saas"] | None = None
    entities: Annotated[tuple[Text, ...], Field(min_length=2, max_length=2)]
    facts: Annotated[tuple[Fact, ...], Field(min_length=1, max_length=100)]
    split: Literal["calibration", "development", "test"]

    @model_validator(mode="after")
    def scoped_facts(self) -> Self:
        if len(set(self.entities)) != 2 or len({fact.id for fact in self.facts}) != len(self.facts):
            raise ValueError("Family entities and fact IDs must be unique.")
        if any(fact.entity not in self.entities for fact in self.facts):
            raise ValueError("Family facts must belong to a declared visible entity.")
        return self


class ListItem(Record):
    text: Text
    level: Annotated[StrictInt, Field(ge=1, le=2)] = 1
    fact_refs: tuple[Identifier, ...] = ()


class Block(Record):
    id: Identifier
    kind: Literal["heading", "paragraph", "ordered_list", "unordered_list", "table", "callout"]
    text: Text | None = None
    level: Annotated[StrictInt, Field(ge=1, le=3)] | None = None
    items: Annotated[tuple[ListItem, ...], Field(min_length=1, max_length=100)] | None = None
    table: Table | None = None
    fact_refs: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def valid_payload(self) -> Self:
        if self.kind == "heading":
            valid = self.text is not None and self.level is not None
            valid = valid and self.items is None and self.table is None
        elif self.kind in {"ordered_list", "unordered_list"}:
            valid = self.items is not None and self.level is None
            valid = valid and self.text is None and self.table is None
            if self.items and self.items[0].level != 1:
                raise ValueError("Lists must start at level one.")
        elif self.kind == "table":
            valid = self.table is not None and self.text is None
            valid = valid and self.level is None and self.items is None
        else:
            valid = self.text is not None and self.level is None
            valid = valid and self.items is None and self.table is None
        if not valid:
            raise ValueError(f"Invalid payload for {self.kind} block {self.id}.")
        return self


class Usage(Record):
    input_tokens: Annotated[StrictInt, Field(ge=0)] | None = None
    output_tokens: Annotated[StrictInt, Field(ge=0)] | None = None
    total_tokens: Annotated[StrictInt, Field(ge=0)] | None = None
    reasoning_tokens: Annotated[StrictInt, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def token_accounting(self) -> Self:
        if self.input_tokens is not None and self.output_tokens is not None:
            if self.total_tokens != self.input_tokens + self.output_tokens:
                raise ValueError("Total usage must equal input plus output tokens.")
        if self.reasoning_tokens is not None and self.output_tokens is not None:
            if self.reasoning_tokens > self.output_tokens:
                raise ValueError("Reasoning tokens cannot exceed output tokens.")
        return self


class Provenance(Record):
    deployment: Text
    reported_model: Text | None = None
    model_version: Text | None = None
    prompt_version: Text
    wire_version: Literal["1"] = "1"
    request_id: Text | None = None
    attempt_id: Identifier
    created_at: datetime
    usage: Usage | None = None

    @field_validator("created_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Provenance timestamp requires a timezone.")
        return value


class Quality(Record):
    checks: Annotated[tuple[Text, ...], Field(min_length=1)]
    word_count: Annotated[StrictInt, Field(ge=0)]


class Content(Record):
    schema_version: Literal["1"] = "1"
    normalized_fingerprint: Annotated[
        str, StringConstraints(pattern=r"^[0-9a-f]{64}$")
    ] | None = None
    blueprint: Blueprint
    title: Text
    blocks: Annotated[tuple[Block, ...], Field(min_length=1, max_length=100)]
    facts: tuple[Fact, ...] = ()
    provenance: Provenance
    quality: Quality

    @property
    def usage(self) -> Usage | None:
        return self.provenance.usage

    @model_validator(mode="after")
    def validate_relationships(self) -> Self:
        if len({b.id for b in self.blocks}) != len(self.blocks):
            raise ValueError("Block IDs must be unique.")
        tables = [b.table for b in self.blocks if b.table is not None]
        if len({table.id for table in tables}) != len(tables):
            raise ValueError("Table IDs must be unique.")
        facts = {fact.id: fact for fact in self.facts}
        if len(facts) != len(self.facts):
            raise ValueError("Fact IDs must be unique.")
        last_heading = 0
        for block in self.blocks:
            if block.level is not None:
                if block.level > last_heading + 1:
                    raise ValueError("Heading levels cannot skip a level.")
                last_heading = block.level
            refs = list(block.fact_refs)
            for item in block.items or ():
                refs.extend(item.fact_refs)
            if block.table:
                for row in block.table.rows:
                    for cell, column in zip(row, block.table.columns, strict=True):
                        if cell.fact_id:
                            refs.append(cell.fact_id)
                            fact = facts.get(cell.fact_id)
                            if fact and (fact.kind, fact.value, unit_identity(fact.unit)) != (
                                cell.kind, cell.value, unit_identity(column.unit)
                            ):
                                raise ValueError(
                                    "Table cell contradicts its referenced fact: "
                                    f"{block.table.id}/{column.id}/{fact.id}. "
                                    f"Expected column kind {fact.kind}, literal value "
                                    f"{json.dumps(fact.model_dump(mode='json')['value'])} "
                                    f"and unit {fact.unit!r}. "
                                    "Use the fact's literal value in that typed column; "
                                    "move facts to paragraph/list prose if a column mixes kinds."
                                )
            if not set(refs).issubset(facts):
                raise ValueError("Content references an unknown fact.")
        return self


def serialize(record: Record) -> bytes:
    return json.dumps(
        record.model_dump(mode="json"), sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(",", ":"),
    ).encode("utf-8")


def content_hash(content: Content) -> str:
    return hashlib.sha256(serialize(content)).hexdigest()
