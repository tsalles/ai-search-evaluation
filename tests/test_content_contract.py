import copy
import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from docgen.models import Blueprint, Content, content_hash, serialize
from docgen.wire import DRAFT_SCHEMA


def example_content() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "blueprint": {
            "content_id": "item-000001", "ordinal": 1, "topic_id": "produtos",
            "genre": "comparison", "length_band": "short", "language": "pt",
            "locale": "pt-BR", "audience": "clientes",
            "scenario_id": "scenario-000001", "structure_profile": "baseline",
        },
        "title": "Cr\u00e9dito Aurora",
        "blocks": [
            {"id": "h1", "kind": "heading", "text": "Condi\u00e7\u00f5es", "level": 1},
            {"id": "p1", "kind": "paragraph", "text": "A taxa \u00e9 1,25% ao m\u00eas.",
             "fact_refs": ["rate"]},
            {"id": "l1", "kind": "ordered_list", "items": [
                {"text": "Confira a documenta\u00e7\u00e3o.", "level": 1},
                {"text": "Solicite avalia\u00e7\u00e3o.", "level": 2},
            ]},
            {"id": "t1", "kind": "table", "table": {
                "id": "rates",
                "columns": [
                    {"id": "product", "name": "Produto", "kind": "text"},
                    {"id": "rate", "name": "Taxa", "kind": "decimal", "unit": "% ao m\u00eas"},
                    {"id": "valid", "name": "Vig\u00eancia", "kind": "date"},
                    {"id": "active", "name": "Ativo", "kind": "boolean"},
                ],
                "rows": [[
                    {"kind": "text", "value": "Aurora"},
                    {"kind": "decimal", "value": "1.25", "fact_id": "rate"},
                    {"kind": "date", "value": "2026-10-23"},
                    {"kind": "boolean", "value": True},
                ]],
            }},
        ],
        "facts": [
            {"id": "rate", "entity": "Cr\u00e9dito Aurora", "kind": "decimal",
             "value": "1.25", "unit": "% ao m\u00eas", "display": "1,25%",
             "valid_from": "2026-10-01", "valid_until": "2026-12-31"},
        ],
        "provenance": {
            "deployment": "test-deployment", "prompt_version": "1",
            "wire_version": "1", "request_id": "test-request",
            "attempt_id": "attempt-000001", "created_at": "2026-10-23T10:00:00Z",
        },
        "quality": {"checks": ["schema"], "word_count": 20},
    }


def test_canonical_round_trip_preserves_values_accents_and_hash() -> None:
    content = Content.model_validate(example_content())
    encoded = serialize(content)
    decoded = Content.model_validate_json(encoded)
    assert decoded == content
    assert decoded.blocks[-1].table.rows[0][1].value == Decimal("1.25")
    assert decoded.blocks[-1].table.rows[0][2].value == date(2026, 10, 23)
    assert decoded.blocks[-1].table.rows[0][3].value is True
    assert "Cr\u00e9dito" in encoded.decode("utf-8")
    assert content_hash(decoded) == content_hash(content)
    assert serialize(decoded) == encoded
    assert len(content_hash(content)) == 64
    with pytest.raises(ValidationError):
        content.title = "mutation"


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(schema_version="2"),
    lambda d: d.update(unknown=True),
    lambda d: d["blueprint"].update(ordinal=True),
    lambda d: d["blueprint"].update(content_id="..\\escape"),
    lambda d: d["blueprint"].update(locale="en-US"),
    lambda d: d["blocks"][1].update(id="h1"),
    lambda d: d["blocks"][1].update(fact_refs=["absent"]),
    lambda d: d["blocks"][0].update(level=4),
    lambda d: d["blocks"][1].update(text=" "),
    lambda d: d["blocks"][1].update(items=[{"text": "unexpected"}]),
    lambda d: d["blocks"][-1]["table"]["rows"][0].pop(),
    lambda d: d["blocks"][-1]["table"]["rows"][0][1].update(kind="text"),
    lambda d: d["blocks"][-1]["table"]["rows"][0][1].update(value="2.50"),
    lambda d: d["blocks"][-1]["table"]["rows"][0][1].update(value=True),
    lambda d: d["blocks"][-1]["table"]["rows"][0][1].update(value="NaN"),
    lambda d: d["blocks"][-1]["table"]["rows"][0][1].update(value="1234567890123456"),
    lambda d: d["blocks"][-1]["table"]["rows"][0][0].update(value="x" * 2049),
    lambda d: d["blocks"][-1]["table"]["columns"][1].update(id="product"),
    lambda d: d["facts"][0].update(valid_until="2026-09-30"),
    lambda d: d["facts"].append(copy.deepcopy(d["facts"][0])),
    lambda d: d["provenance"].update(created_at="2026-10-23T10:00:00"),
    lambda d: d["provenance"].update(usage={"total_tokens": -1}),
])
def test_rejects_invalid_canonical_content(mutation: Any) -> None:
    data = example_content()
    mutation(data)
    with pytest.raises(ValidationError):
        Content.model_validate(data)


def test_blueprint_rejects_locale_mismatch_and_blank_fields() -> None:
    data = example_content()["blueprint"]
    data["audience"] = " "
    with pytest.raises(ValidationError):
        Blueprint.model_validate(data)


def test_wire_schema_is_strict_shallow_and_without_unsupported_constraints() -> None:
    Draft202012Validator.check_schema(DRAFT_SCHEMA)
    properties = 0
    max_depth = 0
    forbidden = {"$ref", "minLength", "maxLength", "minimum", "maximum", "discriminator"}

    def inspect(node: Any, depth: int = 0) -> None:
        nonlocal properties, max_depth
        if not isinstance(node, dict):
            return
        assert not forbidden.intersection(node)
        if node.get("type") == "object":
            depth += 1
            properties += len(node["properties"])
            max_depth = max(max_depth, depth)
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
        for value in node.values():
            if isinstance(value, dict):
                inspect(value, depth)
            elif isinstance(value, list):
                for item in value:
                    inspect(item, depth)

    inspect(DRAFT_SCHEMA)
    assert properties <= 100
    assert max_depth <= 5
    json.dumps(DRAFT_SCHEMA, allow_nan=False)
    validator = Draft202012Validator(DRAFT_SCHEMA)
    assert not validator.is_valid({"title": "missing required draft fields"})
