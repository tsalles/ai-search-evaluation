import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, StrictInt, field_validator

from docgen.config import GenerationConfig
from docgen.facts import canonical_fact
from docgen.families import scoped_facts
from docgen.models import (
    Block,
    Blueprint,
    Cell,
    Column,
    Content,
    Fact,
    Identifier,
    ListItem,
    Provenance,
    Quality,
    Record,
    Table,
    Text,
    ValueKind,
)
from docgen.prompts import PROMPT_VERSION
from docgen.providers.azure import DraftResponse
from docgen.text import word_count
from docgen.units import unit_variants


class DraftBlock(Record):
    id: Identifier
    kind: Literal["heading", "paragraph", "ordered_list", "unordered_list", "table", "callout"]
    text: Text | None
    level: StrictInt | None
    table_id: Identifier | None


class DraftItem(Record):
    block_id: Identifier
    text: Text
    level: StrictInt


class DraftColumn(Column):
    table_id: Identifier


class DraftCell(Record):
    table_id: Identifier
    row: StrictInt = Field(ge=0, le=199)
    column_id: Identifier
    value: Text
    fact_id: Identifier | None

    @field_validator("value", mode="before")
    @classmethod
    def non_empty_value(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError(
                "Table cells must be non-empty. Do not use blank or inapplicable typed cells; "
                "use complete all-text qualitative rows for mixed-kind tables, without numeric "
                "fact_id cells, and put quantitative facts in paragraph/list prose placeholders."
            )
        return value


class DraftFact(Record):
    id: Identifier
    entity: Text
    kind: ValueKind
    value: Text
    unit: Text | None
    display: Text
    valid_from: str | None
    valid_until: str | None


class Draft(Record):
    title: Text
    blocks: tuple[DraftBlock, ...]
    list_items: tuple[DraftItem, ...]
    columns: tuple[DraftColumn, ...]
    cells: tuple[DraftCell, ...]
    facts: tuple[DraftFact, ...]


def scalar(kind: ValueKind, value: str) -> str | bool:
    if kind == "boolean":
        if value not in {"true", "false"}:
            raise ValueError("Wire Boolean values must be true or false.")
        return value == "true"
    return value


def materialize(text: str, facts: dict[str, Fact]) -> tuple[str, tuple[str, ...]]:
    references = re.findall(r"\{\{fact:([a-z][a-z0-9-]*)}}", text)
    without = re.sub(r"\{\{fact:[a-z][a-z0-9-]*}}", "", text)
    if re.search(r"\d", without):
        raise ValueError("Quantitative prose must use explicit fact references.")
    if "{{" in without or "}}" in without:
        raise ValueError("Unknown or unresolved content placeholder.")
    for reference in references:
        if reference not in facts:
            raise ValueError(f"Unknown fact reference: {reference}.")
        fact = facts[reference]
        placeholder = "{{fact:" + reference + "}}"
        for variant in unit_variants(fact.unit):
            words = variant.split()
            for index in range(len(words)):
                suffix = r"\s+".join(re.escape(word) for word in words[index:])
                if re.search(re.escape(placeholder) + r"\s+" + suffix + r"(?!\w)", text, re.I):
                    raise ValueError(f"Fact reference already includes its unit: {reference}.")
        text = text.replace(placeholder, fact.display)
    return text, tuple(dict.fromkeys(references))


def compose(
    response: DraftResponse, blueprint: Blueprint, config: GenerationConfig, *,
    attempt_id: str, created_at: datetime | None = None,
    shared_facts: tuple[Fact, ...] | None = None,
) -> Content:
    draft = Draft.model_validate(response.payload)
    shared_facts = scoped_facts(blueprint, config) if shared_facts is None else shared_facts
    ledger = {fact.id: canonical_fact(fact, blueprint.locale) for fact in shared_facts}
    if len(ledger) != len(shared_facts):
        raise ValueError("Duplicate shared fact IDs.")
    seen = set()
    for raw in draft.facts:
        if raw.id in seen:
            raise ValueError("Duplicate draft fact IDs.")
        seen.add(raw.id)
        fact = canonical_fact(Fact.model_validate({
            **raw.model_dump(), "value": scalar(raw.kind, raw.value),
        }), blueprint.locale)
        if fact.id in ledger and fact != ledger[fact.id]:
            raise ValueError(f"Draft contradicts a frozen shared fact: {fact.id}.")
        ledger[fact.id] = fact
    table_ids = {block.table_id for block in draft.blocks if block.kind == "table"}
    list_ids = {block.id for block in draft.blocks if block.kind.endswith("_list")}
    if any(column.table_id not in table_ids for column in draft.columns):
        raise ValueError(
            "Orphan table column. Each column.table_id must match an existing table block's "
            "table_id, not a column ID."
        )
    if any(cell.table_id not in table_ids for cell in draft.cells):
        raise ValueError("Orphan table cell.")
    if any(item.block_id not in list_ids for item in draft.list_items):
        raise ValueError("Orphan list item.")
    blocks = []
    used: set[str] = set()
    title, refs = materialize(draft.title, ledger)
    used.update(refs)
    for raw_block in draft.blocks:
        text = None
        refs = ()
        if raw_block.text is not None:
            text, refs = materialize(raw_block.text, ledger)
            used.update(refs)
        items = None
        table = None
        if raw_block.kind.endswith("_list"):
            built_items = []
            for item in draft.list_items:
                if item.block_id == raw_block.id:
                    item_text, item_refs = materialize(item.text, ledger)
                    used.update(item_refs)
                    built_items.append(ListItem(
                        text=item_text, level=item.level, fact_refs=item_refs
                    ))
            items = tuple(built_items)
        if raw_block.kind == "table":
            if raw_block.table_id is None:
                raise ValueError("Table block requires a table ID.")
            built_columns = []
            for raw_column in draft.columns:
                if raw_column.table_id != raw_block.table_id:
                    continue
                name, column_refs = materialize(raw_column.name, ledger)
                used.update(column_refs)
                refs = tuple(dict.fromkeys((*refs, *column_refs)))
                if raw_column.unit and ("{{" in raw_column.unit or "}}" in raw_column.unit):
                    raise ValueError("Column units cannot contain unresolved references.")
                built_columns.append(Column(
                    id=raw_column.id, name=name, kind=raw_column.kind, unit=raw_column.unit
                ))
            columns = tuple(built_columns)
            cells = [cell for cell in draft.cells if cell.table_id == raw_block.table_id]
            indexed = {(cell.row, cell.column_id): cell for cell in cells}
            if len(indexed) != len(cells):
                raise ValueError("Duplicate table cell coordinates.")
            rows = []
            row_count = max((cell.row for cell in cells), default=-1) + 1
            for row_index in range(row_count):
                row = []
                for column in columns:
                    cell = indexed.pop((row_index, column.id), None)
                    if cell is None:
                        raise ValueError("Table rows must be contiguous and rectangular.")
                    if cell.fact_id is None and column.kind != "text":
                        raise ValueError("Typed table values require a fact reference.")
                    if cell.fact_id:
                        used.add(cell.fact_id)
                    else:
                        _, cell_refs = materialize(cell.value, ledger)
                        if cell_refs:
                            raise ValueError("Table cells must use explicit fact_id references.")
                    row.append(Cell(
                        kind=column.kind, value=scalar(column.kind, cell.value),
                        fact_id=cell.fact_id,
                    ))
                rows.append(tuple(row))
            if indexed:
                raise ValueError("Table cells reference an unknown column.")
            table = Table(id=raw_block.table_id, columns=columns, rows=tuple(rows))
        blocks.append(Block(
            id=raw_block.id, kind=raw_block.kind, text=text, level=raw_block.level,
            items=items, table=table, fact_refs=refs,
        ))
    if not used.issubset(ledger):
        raise ValueError("Table references an unknown fact.")
    content = Content(
        blueprint=blueprint, title=title, blocks=tuple(blocks),
        facts=tuple(fact for fact in ledger.values() if fact.id in used),
        quality=Quality(checks=("schema", "facts"), word_count=0),
        provenance=Provenance(
            deployment=config.provider.deployment if config.provider else response.reported_model,
            reported_model=response.reported_model,
            model_version=response.model_version, prompt_version=PROMPT_VERSION,
            request_id=response.request_id, attempt_id=attempt_id,
            created_at=created_at or datetime.now(UTC), usage=response.usage,
        ),
    )
    return content.model_copy(update={
        "quality": Quality(checks=("schema", "facts"), word_count=word_count(content)),
    })
