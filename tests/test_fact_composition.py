from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from docgen.composition import compose
from docgen.config import Config
from docgen.facts import FactRegistry, canonical_fact
from docgen.models import Content, Fact, serialize
from docgen.planning import create_plan
from docgen.providers.azure import DraftResponse
from tests.test_planning import configuration


def wire_draft() -> dict[str, Any]:
    return {
        "title": "Conta Aurora",
        "blocks": [
            {"id": "intro", "kind": "heading", "level": 1, "text": "Condicoes", "table_id": None},
            {
                "id": "body",
                "kind": "paragraph",
                "level": None,
                "text": "A Conta Aurora cobra {{fact:fee}}. Confira a tarifa de {{fact:fee}}.",
                "table_id": None,
            },
            {"id": "steps", "kind": "ordered_list", "level": None, "text": None, "table_id": None},
            {"id": "table-block", "kind": "table", "level": None, "text": None, "table_id": "fees"},
        ],
        "list_items": [{"block_id": "steps", "text": "Confira o contrato.", "level": 1}],
        "columns": [
            {"table_id": "fees", "id": "product", "name": "Produto", "kind": "text", "unit": None},
            {"table_id": "fees", "id": "fee", "name": "Tarifa", "kind": "decimal", "unit": "BRL"},
        ],
        "cells": [
            {
                "table_id": "fees",
                "row": 0,
                "column_id": "product",
                "value": "Conta Aurora",
                "fact_id": None,
            },
            {"table_id": "fees", "row": 0, "column_id": "fee", "value": "12.50", "fact_id": "fee"},
        ],
        "facts": [
            {
                "id": "fee",
                "entity": "Conta Aurora",
                "kind": "decimal",
                "value": "12.50",
                "unit": "BRL",
                "display": "12,50 BRL",
                "valid_from": None,
                "valid_until": None,
            }
        ],
    }


def composed(payload: dict[str, Any] | None = None, **kwargs: Any) -> Content:
    cfg = Config.model_validate(configuration(1)).generation
    blueprint = create_plan(
        Config(generation=cfg), run_id="run-fixed", operation="generate"
    ).blueprints[0]
    response = DraftResponse(
        payload=payload or wire_draft(),
        response_id="resp-test",
        request_id="request-test",
        reported_model="test-model",
        model_version=None,
        usage=None,
    )
    return compose(
        response,
        blueprint,
        cfg,
        attempt_id="attempt-test",
        created_at=datetime(2026, 10, 23, tzinfo=UTC),
        **kwargs,
    )


def test_fact_references_materialize_consistent_text_and_native_cells() -> None:
    content = composed()
    assert content.blocks[1].text.count("12,50 BRL") == 2
    assert content.blocks[1].fact_refs == ("fee",)
    assert content.blocks[-1].table.rows[0][1].value == Decimal("12.50")
    assert "{{" not in serialize(content).decode()
    assert Content.model_validate_json(serialize(content)) == content
    FactRegistry().accept(content)


def test_table_fact_failure_identifies_the_required_column_kind_and_unit() -> None:
    data = wire_draft()
    data["columns"][1].update(kind="text", unit=None)
    data["cells"][1]["value"] = "12.50 BRL"
    with pytest.raises(ValueError, match="decimal.*12.50.*BRL"):
        composed(data)


def test_empty_table_cell_failure_explains_the_non_empty_contract() -> None:
    data = wire_draft()
    data["cells"][0]["value"] = ""
    with pytest.raises(ValueError, match="non-empty"):
        composed(data)


def test_orphan_column_failure_explains_table_identity_binding() -> None:
    data = wire_draft()
    data["columns"][0]["table_id"] = "product"
    with pytest.raises(ValueError, match="table_id"):
        composed(data)


@pytest.mark.parametrize(("unit", "suffix"), [
    ("BRL", "BRL"),
    ("% ao ano", "ao ano"),
    ("% ao ano", "% ao ano"),
    ("% per year", "per year"),
])
def test_materialization_rejects_an_adjacent_repeated_unit_instead_of_rewriting_prose(
    unit: str, suffix: str,
) -> None:
    data = wire_draft()
    data["facts"][0].update(unit=unit, display=f"12,50 {unit}")
    data["columns"][1]["unit"] = unit
    data["blocks"][1]["text"] = "A Conta Aurora informa {{fact:fee}} " + suffix + "."
    with pytest.raises(ValueError, match="unit"):
        composed(data)


def test_later_mentions_of_a_unit_are_not_mistaken_for_adjacent_repetition() -> None:
    data = wire_draft()
    data["blocks"][1]["text"] = "A Conta Aurora cobra {{fact:fee}}. Valores expressos em BRL."
    assert composed(data).blocks[1].text == (
        "A Conta Aurora cobra 12,50 BRL. Valores expressos em BRL."
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["blocks"][1].update(text="Unknown {{fact:absent}}"),
        lambda d: d["blocks"][1].update(text="Unknown {{broken}}"),
        lambda d: d["blocks"][1].update(text="A Conta Aurora cobra 99 BRL."),
        lambda d: d["facts"][0].update(display="99 BRL"),
        lambda d: d["facts"][0].update(valid_from="2026-12-31", valid_until="2026-01-01"),
        lambda d: d["facts"].append(dict(d["facts"][0])),
        lambda d: d["cells"][1].update(value="99"),
        lambda d: d["cells"][1].update(fact_id="absent"),
        lambda d: d["cells"][1].update(fact_id=None),
        lambda d: d["cells"][1].update(row=2),
        lambda d: d["cells"].append(dict(d["cells"][1])),
        lambda d: d["cells"].pop(),
        lambda d: d["columns"][1].update(table_id="absent"),
        lambda d: d["list_items"][0].update(block_id="absent"),
        lambda d: d["blocks"][0].update(extra=True),
        lambda d: d["cells"][0].update(value="{{fact:fee}}"),
        lambda d: d["columns"][0].update(name="{{broken}}"),
        lambda d: d["facts"][0].update(entity="{{broken}}"),
    ],
)
def test_invalid_facts_or_structure_are_not_silently_repaired(mutation: Any) -> None:
    data = wire_draft()
    mutation(data)
    with pytest.raises(ValueError):
        composed(data)


def test_shared_facts_are_frozen_but_can_be_referenced_without_redefinition() -> None:
    original = composed().facts[0]
    data = wire_draft()
    data["facts"] = []
    assert composed(data, shared_facts=(original,)).facts == (original,)
    data = wire_draft()
    data["facts"][0].update(value="99", display="99 BRL")
    data["cells"][1]["value"] = "99"
    with pytest.raises(ValueError, match="shared"):
        composed(data, shared_facts=(original,))


def test_shared_facts_are_configurable_and_part_of_the_saved_semantic_plan() -> None:
    data = configuration(1)
    data["generation"]["shared_facts"] = [composed().facts[0].model_dump(mode="python")]
    cfg = Config.model_validate(data)
    assert cfg.generation.shared_facts[0].value == Decimal("12.50")
    assert Config.model_validate_json(cfg.model_dump_json()) == cfg
    data["generation"]["shared_facts"].append(data["generation"]["shared_facts"][0])
    with pytest.raises(ValueError):
        Config.model_validate(data)


def test_hidden_scenario_ids_do_not_allow_conflicting_visible_entities() -> None:
    registry = FactRegistry()
    registry.accept(composed())
    data = wire_draft()
    data["facts"][0].update(value="15", display="15 BRL")
    data["cells"][1]["value"] = "15"
    changed = composed(data)
    with pytest.raises(ValueError, match="conflict"):
        registry.accept(changed)
    data["title"] = "Conta Horizonte"
    data["blocks"][1]["text"] = "A Conta Horizonte cobra {{fact:fee}}."
    data["facts"][0]["entity"] = "Conta Horizonte"
    data["cells"][0]["value"] = "Conta Horizonte"
    registry.accept(composed(data))


def test_entity_must_be_visible_and_boolean_date_facts_stay_typed() -> None:
    data = wire_draft()
    data["facts"][0]["entity"] = "invisible entity"
    with pytest.raises(ValueError, match="visible"):
        FactRegistry().accept(composed(data))
    for kind, value, display in [
        ("boolean", "true", "Sim"),
        ("date", "2026-10-23", "23/10/2026"),
        ("text", "permitido", "permitido"),
    ]:
        data = wire_draft()
        data["columns"][1].update(kind=kind, unit=None)
        data["facts"][0].update(kind=kind, value=value, display=display, unit=None)
        data["cells"][1]["value"] = value
        content = composed(data)
        assert display in content.blocks[1].text
        assert content.blocks[-1].table.rows[0][1].kind == kind
    registry = FactRegistry()
    data = wire_draft()
    data["facts"][0].update(valid_from="2026-01-01", valid_until="2026-12-31")
    with pytest.raises(ValueError, match="validity"):
        registry.accept(composed(data))


@pytest.mark.parametrize(
    ("locale", "display"),
    [
        ("pt-BR", "R$ 1.500,25"),
        ("en-US", "$1,500.25"),
    ],
)
def test_valid_localized_thousands_separators_are_not_mistaken_for_extra_facts(
    locale: str,
    display: str,
) -> None:
    fact = Fact(
        id="amount",
        entity="Conta Aurora",
        kind="decimal",
        value="1500.25",
        unit="BRL",
        display=display,
    )
    expected = "1500,25 BRL" if locale == "pt-BR" else "1500.25 BRL"
    assert canonical_fact(fact, locale).display == expected
    invalid = fact.model_copy(update={"display": display.replace("500", "600")})
    with pytest.raises(ValueError, match="contradicts"):
        canonical_fact(invalid, locale)
