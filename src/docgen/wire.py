from copy import deepcopy
from re import escape

from pydantic import JsonValue

from docgen.errors import InputError
from docgen.models import Fact
from docgen.renderers.layout import portable_latin_characters
from docgen.structure_models import StructurePlan
from docgen.units import unit_identity


def strict_object(properties: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def array(item: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {"type": "array", "items": item}


TEXT: dict[str, JsonValue] = {"type": "string"}
NULLABLE_TEXT: dict[str, JsonValue] = {"type": ["string", "null"]}
KIND: dict[str, JsonValue] = {"type": "string", "enum": ["text", "decimal", "date", "boolean"]}

# Flatten table rows into indexed cells to keep the provider schema shallow.
DRAFT_SCHEMA = strict_object(
    {
        "title": TEXT,
        "blocks": array(
            strict_object(
                {
                    "id": TEXT,
                    "kind": {
                        "type": "string",
                        "enum": [
                            "heading",
                            "paragraph",
                            "ordered_list",
                            "unordered_list",
                            "table",
                            "callout",
                        ],
                    },
                    "text": NULLABLE_TEXT,
                    "level": {"type": ["integer", "null"]},
                    "table_id": NULLABLE_TEXT,
                }
            )
        ),
        "list_items": array(
            strict_object(
                {
                    "block_id": TEXT,
                    "text": TEXT,
                    "level": {"type": "integer"},
                }
            )
        ),
        "columns": array(
            strict_object(
                {
                    "table_id": TEXT,
                    "id": TEXT,
                    "name": TEXT,
                    "kind": KIND,
                    "unit": NULLABLE_TEXT,
                }
            )
        ),
        "cells": array(
            strict_object(
                {
                    "table_id": TEXT,
                    "row": {"type": "integer"},
                    "column_id": TEXT,
                    "value": TEXT,
                    "fact_id": NULLABLE_TEXT,
                }
            )
        ),
        "facts": array(
            strict_object(
                {
                    "id": TEXT,
                    "entity": TEXT,
                    "kind": KIND,
                    "value": TEXT,
                    "unit": NULLABLE_TEXT,
                    "display": TEXT,
                    "valid_from": NULLABLE_TEXT,
                    "valid_until": NULLABLE_TEXT,
                }
            )
        ),
    }
)


def fact_bound_draft_schema(
    facts: tuple[Fact, ...],
    *,
    structure: StructurePlan | None = None,
) -> dict[str, JsonValue]:
    if not facts or any(fact.kind not in {"text", "decimal"} for fact in facts):
        raise InputError("The fact-bound authoring schema requires text or decimal facts.")
    # Character limits stay at composition; length/pattern intersections fail model decoding.
    schema = deepcopy(DRAFT_SCHEMA)
    properties = schema["properties"]
    if not isinstance(properties, dict):
        raise InputError("The base authoring schema has invalid properties.")
    characters = portable_latin_characters()
    free_text: dict[str, JsonValue] = {
        "type": "string", "pattern": "^[" + escape(characters) + "]*$",
    }
    prose_characters = escape("".join(char for char in characters if not char.isdigit()))
    references = r"\{\{fact:(?:" + "|".join(escape(fact.id) for fact in facts) + r")\}\}"
    prose_pattern = r"^(?:[" + prose_characters + "]|" + references + r")*$"
    title_entities = " e ".join(dict.fromkeys(fact.entity for fact in facts))
    properties["title"] = {
        "type": "string",
        "pattern": (
            "^" + escape(title_entities) + r": (?:["
            + prose_characters + "]|" + references + r")+$"
        ),
    }
    for collection in ("blocks", "list_items"):
        entries = properties[collection]
        if not isinstance(entries, dict):
            raise InputError("The base authoring schema has invalid text entries.")
        item = entries.get("items")
        if not isinstance(item, dict):
            raise InputError("The base authoring schema has invalid text items.")
        fields = item.get("properties")
        if not isinstance(fields, dict):
            raise InputError("The base authoring schema has invalid text properties.")
        fields["text"] = {
            "type": ["string", "null"] if collection == "blocks" else "string",
            "pattern": prose_pattern,
        }
    text_ids: list[JsonValue] = [f"text-{index}" for index in range(1, 9)]
    columns: list[JsonValue] = [
        strict_object(
            {
                "table_id": TEXT,
                "id": {"type": "string", "enum": text_ids},
                "name": free_text,
                "kind": {"type": "string", "enum": ["text"]},
                "unit": {"type": "null"},
            }
        )
    ]
    cells: list[JsonValue] = [
        strict_object(
            {
                "table_id": TEXT,
                "row": {"type": "integer"},
                "column_id": {"type": "string", "enum": text_ids},
                "value": {"type": "string", "pattern": "^[" + prose_characters + "]+$"},
                "fact_id": {"type": "null"},
            }
        )
    ]
    numbers: dict[tuple[str, str] | None, str] = {}
    declared: list[JsonValue] = []
    for fact in facts:
        raw = fact.model_dump(mode="json")
        value = raw["value"]
        if (
            not isinstance(value, str)
            or fact.valid_from is not None
            or fact.valid_until is not None
        ):
            raise InputError("The fact-bound authoring schema requires undated scalar facts.")
        if fact.kind == "decimal":
            identity = unit_identity(fact.unit)
            if identity not in numbers:
                identifier = f"number-{len(numbers) + 1}"
                numbers[identity] = identifier
                columns.append(
                    strict_object(
                        {
                            "table_id": TEXT,
                            "id": {"type": "string", "enum": [identifier]},
                            "name": free_text,
                            "kind": {"type": "string", "enum": ["decimal"]},
                            "unit": {"type": ["string", "null"], "enum": [fact.unit]},
                        }
                    )
                )
            column: dict[str, JsonValue] = {
                "type": "string",
                "enum": [numbers[identity]],
            }
        else:
            column = {"type": "string", "enum": text_ids}
        cells.append(
            strict_object(
                {
                    "table_id": TEXT,
                    "row": {"type": "integer"},
                    "column_id": column,
                    "value": {"type": "string", "enum": [value]},
                    "fact_id": {"type": "string", "enum": [fact.id]},
                }
            )
        )
        declared.append(
            strict_object(
                {
                    "id": {"type": "string", "enum": [fact.id]},
                    "entity": {"type": "string", "enum": [fact.entity]},
                    "kind": {"type": "string", "enum": [fact.kind]},
                    "value": {"type": "string", "enum": [value]},
                    "unit": {"type": ["string", "null"], "enum": [fact.unit]},
                    "display": free_text,
                    "valid_from": {"type": "null"},
                    "valid_until": {"type": "null"},
                }
            )
        )
    properties["columns"] = array({"anyOf": columns})
    properties["cells"] = array({"anyOf": cells})
    properties["facts"] = array({"anyOf": declared})
    if structure is not None:
        blocks: list[JsonValue] = []
        lists: list[JsonValue] = []
        for slot in structure.slots:
            block = strict_object(
                {
                    "id": {"type": "string", "enum": [slot.id]},
                    "kind": {"type": "string", "enum": [slot.kind]},
                    "text": (
                        {"type": "string", "pattern": prose_pattern}
                        if slot.kind in {"heading", "paragraph", "callout"}
                        else {"type": "null"}
                    ),
                    "level": (
                        {"type": "integer", "enum": [slot.level]}
                        if slot.kind == "heading"
                        else {"type": "null"}
                    ),
                    "table_id": (
                        {"type": "string", "enum": [slot.id]}
                        if slot.kind == "table"
                        else {"type": "null"}
                    ),
                }
            )
            blocks.append(block)
            if slot.item_levels:
                lists.append(
                    strict_object(
                        {
                            "block_id": {"type": "string", "enum": [slot.id]},
                            "level": {
                                "type": "integer",
                                "enum": [level for level in sorted(set(slot.item_levels))],
                            },
                            "text": {"type": "string", "pattern": prose_pattern},
                        }
                    )
                )
        properties["blocks"] = {
            "type": "array",
            "items": {"anyOf": blocks},
            "minItems": len(structure.slots),
            "maxItems": len(structure.slots),
        }
        if lists:
            count = sum(len(slot.item_levels) for slot in structure.slots)
            properties["list_items"] = {
                "type": "array",
                "items": {"anyOf": lists},
                "minItems": count,
                "maxItems": count,
            }
        else:
            properties["list_items"] = {
                "type": "array",
                "items": TEXT,
                "minItems": 0,
                "maxItems": 0,
            }
        tables = [slot for slot in structure.slots if slot.kind == "table"]
        for name, entries in (("columns", columns), ("cells", cells)):
            bound: list[JsonValue] = []
            total = 0
            for slot in tables:
                if slot.rows is None or slot.columns is None:
                    raise InputError("The frozen table shape is incomplete.")
                total += slot.columns if name == "columns" else slot.rows * slot.columns
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise InputError("The fact-bound table entry is invalid.")
                    item = deepcopy(entry)
                    fields = item.get("properties")
                    if not isinstance(fields, dict):
                        raise InputError("The fact-bound table properties are invalid.")
                    fields["table_id"] = {"type": "string", "enum": [slot.id]}
                    if name == "columns":
                        fields["name"] = {
                            "type": "string",
                            "pattern": prose_pattern,
                        }
                    else:
                        fields["row"] = {
                            "type": "integer",
                            "enum": [row for row in range(slot.rows)],
                        }
                    bound.append(item)
            properties[name] = {
                "type": "array",
                "items": {"anyOf": bound} if bound else TEXT,
                "minItems": total,
                "maxItems": total,
            }
    return schema
