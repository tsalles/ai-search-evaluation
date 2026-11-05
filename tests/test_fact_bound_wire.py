import copy
import json
import math

import pytest
from jsonschema import Draft202012Validator

from docgen.composition import DraftBlock
from docgen.evaluation.state import new_protocol
from docgen.models import Fact
from docgen.planning import create_plan
from docgen.wire import DRAFT_SCHEMA, fact_bound_draft_schema
from tests.evaluation.test_saas_families import saas_config


def frozen_facts():
    return (
        Fact(
            id="price-a",
            entity="Plano Alfa",
            kind="decimal",
            value="6629",
            unit="BRL",
            display="6629 BRL",
        ),
        Fact(
            id="activation-a",
            entity="Plano Alfa",
            kind="text",
            value="dominio verificado",
            display="dominio verificado",
        ),
    )


def payload():
    return {
        "title": "Plano Alfa: Planos",
        "blocks": [],
        "list_items": [],
        "columns": [
            {
                "table_id": "table-one",
                "id": "text-1",
                "name": "Plano",
                "kind": "text",
                "unit": None,
            },
            {
                "table_id": "table-one",
                "id": "number-1",
                "name": "Mensalidade",
                "kind": "decimal",
                "unit": "BRL",
            },
        ],
        "cells": [
            {
                "table_id": "table-one",
                "row": 0,
                "column_id": "text-1",
                "value": "Plano Alfa",
                "fact_id": None,
            },
            {
                "table_id": "table-one",
                "row": 0,
                "column_id": "number-1",
                "value": "6629",
                "fact_id": "price-a",
            },
        ],
        "facts": [
            {
                "id": "price-a",
                "entity": "Plano Alfa",
                "kind": "decimal",
                "value": "6629",
                "unit": "BRL",
                "display": "6629 BRL",
                "valid_from": None,
                "valid_until": None,
            },
        ],
    }


def test_fact_bound_schema_accepts_consistent_quantities_without_changing_the_legacy_schema():
    original = copy.deepcopy(DRAFT_SCHEMA)
    schema = fact_bound_draft_schema(frozen_facts())
    Draft202012Validator.check_schema(schema)
    assert Draft202012Validator(schema).is_valid(payload())
    assert DRAFT_SCHEMA == original


def test_fact_bound_schema_rejects_the_live_price_in_text_column_failure():
    value = payload()
    value["cells"][1]["column_id"] = "text-1"
    assert Draft202012Validator(DRAFT_SCHEMA).is_valid(value)
    assert not Draft202012Validator(fact_bound_draft_schema(frozen_facts())).is_valid(value)


def test_fact_bound_schema_rejects_changed_units_values_and_unbound_numeric_text():
    validator = Draft202012Validator(fact_bound_draft_schema(frozen_facts()))
    value = payload()
    value["columns"][1]["unit"] = "BRL/mes"
    assert not validator.is_valid(value)
    value = payload()
    value["cells"][1]["value"] = "6.629"
    assert not validator.is_valid(value)
    value = payload()
    value["cells"][0]["value"] = "Plano Alfa 6629"
    assert not validator.is_valid(value)
    value = payload()
    value["facts"][0]["entity"] = "Outro Plano"
    assert not validator.is_valid(value)


def test_fact_bound_schema_requires_explicit_fact_placeholders_in_quantitative_prose():
    validator = Draft202012Validator(fact_bound_draft_schema(frozen_facts()))
    value = payload()
    value["blocks"] = [
        {
            "id": "block-one",
            "kind": "paragraph",
            "text": "Plano Alfa custa 6629 BRL.",
            "level": None,
            "table_id": None,
        }
    ]
    assert not validator.is_valid(value)
    value["blocks"][0]["text"] = "Plano Alfa custa {{fact:price-a}}."
    assert validator.is_valid(value)


@pytest.mark.parametrize("text", ["texto\u5929", "texto\u200d", "texto\ufffc", "texto\ufeff"])
def test_fact_bound_schema_rejects_nonportable_text_in_every_free_business_field(text):
    validator = Draft202012Validator(fact_bound_draft_schema(frozen_facts()))
    for collection, field in ((None, "title"), ("columns", "name"), ("cells", "value")):
        value = payload()
        if collection is None:
            value[field] = text
        else:
            value[collection][0][field] = text
        assert not validator.is_valid(value)


def test_fact_bound_schema_keeps_prose_word_targets_as_guidance_without_padding_outputs():
    protocol = new_protocol(saas_config())
    blueprint = next(
        row
        for row in create_plan(
            protocol.generation_config,
            run_id=protocol.source_run_id,
        ).blueprints
        if row.length_band == "long"
    )
    structure = blueprint.structure_plan
    slot = next(row for row in structure.slots if row.kind == "paragraph")
    schema = fact_bound_draft_schema(frozen_facts(), structure=structure)
    alternatives = schema["properties"]["blocks"]["items"]["anyOf"]
    block_schema = next(row for row in alternatives if row["properties"]["id"]["enum"] == [slot.id])
    validator = Draft202012Validator(block_schema)
    block = {
        "id": slot.id,
        "kind": slot.kind,
        "text": "Texto curto.",
        "level": None,
        "table_id": None,
    }
    assert validator.is_valid(block)
    block["text"] = " ".join(["texto"] * math.ceil(slot.word_budget * 0.9))
    assert validator.is_valid(block)


def planned_structure():
    protocol = new_protocol(saas_config())
    return next(
        row.structure_plan
        for row in create_plan(
            protocol.generation_config,
            run_id=protocol.source_run_id,
        ).blueprints
        if row.genre == "comparison"
    )


def test_heading_and_title_budgets_allow_natural_short_text_without_serialized_filler():
    structure = planned_structure()
    schema = fact_bound_draft_schema(frozen_facts(), structure=structure)
    heading = next(slot for slot in structure.slots if slot.kind == "heading")
    block_schema = next(
        row for row in schema["properties"]["blocks"]["items"]["anyOf"]
        if row["properties"]["id"]["enum"] == [heading.id]
    )
    block = {
        "id": heading.id, "kind": "heading",
        "text": "Crit\u00e9rios de compara\u00e7\u00e3o?",
        "level": heading.level, "table_id": None,
    }
    assert Draft202012Validator(block_schema).is_valid(block)
    assert Draft202012Validator(schema["properties"]["title"]).is_valid("Plano Alfa: Planos SaaS")


def test_prose_word_budgets_do_not_force_joined_words_at_the_provider_boundary():
    structure = planned_structure()
    schema = fact_bound_draft_schema(frozen_facts(), structure=structure)
    slot = next(slot for slot in structure.slots if slot.kind == "paragraph")
    block_schema = next(
        row for row in schema["properties"]["blocks"]["items"]["anyOf"]
        if row["properties"]["id"]["enum"] == [slot.id]
    )
    block = {
        "id": slot.id, "kind": slot.kind, "text": "Contexto breve.",
        "level": None, "table_id": None,
    }
    assert Draft202012Validator(block_schema).is_valid(block)
    block["text"] = " ".join(["contexto"] * (math.ceil(slot.word_budget * 1.1) + 1))
    assert Draft202012Validator(block_schema).is_valid(block)


def test_final_bounded_candidate_recovery_preserves_the_global_budgets():
    from docgen.budgets import BudgetOverride, apply_budget

    original = saas_config().generation
    increased = apply_budget(original, BudgetOverride(max_candidates_per_item=40))
    assert increased.quality.max_candidates_per_item == 40
    assert increased.request_limit == original.request_limit
    assert increased.limits.max_observed_total_tokens == original.limits.max_observed_total_tokens
    with pytest.raises(ValueError):
        BudgetOverride(max_candidates_per_item=41)


def test_fact_bound_titles_preserve_literal_entity_names_before_free_prose():
    schema = fact_bound_draft_schema(frozen_facts())
    validator = Draft202012Validator(schema["properties"]["title"])
    assert validator.is_valid("Plano Alfa: Orientacao comercial")
    assert not validator.is_valid("Plano \u00c1lfa: Orientacao comercial")
    assert not validator.is_valid("Plano Alfabetico: Orientacao comercial")
    assert not validator.is_valid("Orientacao comercial")
    second = frozen_facts()[0].model_copy(update={"id": "price-b", "entity": "Plano Beta"})
    paired = fact_bound_draft_schema((*frozen_facts(), second))["properties"]["title"]
    assert Draft202012Validator(paired).is_valid("Plano Alfa e Plano Beta: Comparacao")
    assert not Draft202012Validator(paired).is_valid("Plano Alfa: Comparacao")


def test_plan_bound_lists_keep_their_frozen_count_without_optional_word_budgets():
    config = saas_config()
    structure_config = config.generation.structure.model_copy(update={"length_aware": False})
    generation = config.generation.model_copy(update={"structure": structure_config})
    protocol = new_protocol(config.model_copy(update={"generation": generation}))
    structure = next(
        blueprint.structure_plan
        for blueprint in create_plan(
            protocol.generation_config, run_id=protocol.source_run_id,
        ).blueprints
        if any(slot.item_levels for slot in blueprint.structure_plan.slots)
    )
    assert all(slot.word_budget is None for slot in structure.slots)
    schema = fact_bound_draft_schema(frozen_facts(), structure=structure)
    expected = sum(len(slot.item_levels) for slot in structure.slots)
    assert schema["properties"]["list_items"]["minItems"] == expected
    assert schema["properties"]["list_items"]["maxItems"] == expected


@pytest.mark.parametrize("separator", ["\u2028", "\u3000", "\u00a0"])
def test_word_bound_schema_rejects_nonportable_interword_separators(separator):
    structure = planned_structure()
    schema = fact_bound_draft_schema(frozen_facts(), structure=structure)
    slot = next(slot for slot in structure.slots if slot.kind == "paragraph")
    block_schema = next(
        row for row in schema["properties"]["blocks"]["items"]["anyOf"]
        if row["properties"]["id"]["enum"] == [slot.id]
    )
    block = {
        "id": slot.id, "kind": slot.kind,
        "text": separator.join(["texto"] * math.ceil(slot.word_budget * 0.9)),
        "level": None, "table_id": None,
    }
    assert not Draft202012Validator(block_schema).is_valid(block)


def test_plan_bound_schema_rejects_heading_payload_without_clamping_prose_words():
    structure = planned_structure()
    schema = fact_bound_draft_schema(frozen_facts(), structure=structure)
    alternatives = schema["properties"]["blocks"]["items"]["anyOf"]
    heading = next(slot for slot in structure.slots if slot.kind == "heading")
    block_schema = next(
        row for row in alternatives if row["properties"]["id"]["enum"] == [heading.id]
    )
    block = {
        "id": heading.id,
        "kind": "heading",
        "text": " ".join(["texto"] * math.ceil(heading.word_budget * 0.9)),
        "level": heading.level,
        "table_id": None,
    }
    validator = Draft202012Validator(block_schema)
    assert validator.is_valid(block)
    block["level"] = None
    assert not validator.is_valid(block)
    block["level"] = heading.level
    block["table_id"] = "unrelated-table"
    assert not validator.is_valid(block)
    paragraph = next(slot for slot in structure.slots if slot.kind == "paragraph")
    prose_schema = next(
        row for row in alternatives if row["properties"]["id"]["enum"] == [paragraph.id]
    )
    prose = {
        "id": paragraph.id, "kind": "paragraph", "level": None, "table_id": None,
        "text": " ".join(["texto"] * (math.ceil(paragraph.word_budget * 1.1) + 1)),
    }
    assert Draft202012Validator(prose_schema).is_valid(prose)


def test_decoder_word_bounds_keep_character_limits_at_the_canonical_wire_boundary():
    structure = planned_structure()
    schema = fact_bound_draft_schema(frozen_facts(), structure=structure)
    assert "maxLength" not in json.dumps(schema)
    assert "minLength" not in json.dumps(schema)
    heading = next(slot for slot in structure.slots if slot.kind == "heading")
    block_schema = next(
        row
        for row in schema["properties"]["blocks"]["items"]["anyOf"]
        if row["properties"]["id"]["enum"] == [heading.id]
    )
    block = {
        "id": heading.id,
        "kind": "heading",
        "level": heading.level,
        "table_id": None,
        "text": "x" * 2049 + " " + " ".join(["texto"] * (math.ceil(heading.word_budget * 0.9) - 1)),
    }
    assert Draft202012Validator(block_schema).is_valid(block)
    with pytest.raises(ValueError, match="2048"):
        DraftBlock.model_validate(block)


def test_plan_bound_schema_rejects_out_of_range_table_rows_and_oversized_arrays():
    structure = planned_structure()
    table = next(slot for slot in structure.slots if slot.kind == "table")
    schema = fact_bound_draft_schema(frozen_facts(), structure=structure)
    cells = schema["properties"]["cells"]
    cell = {
        "table_id": table.id,
        "row": table.rows,
        "column_id": "text-1",
        "value": "Plano Alfa",
        "fact_id": None,
    }
    assert not Draft202012Validator(cells["items"]).is_valid(cell)
    cell["row"] = 0
    assert Draft202012Validator(cells["items"]).is_valid(cell)
    total_cells = sum(slot.rows * slot.columns for slot in structure.slots if slot.kind == "table")
    assert not Draft202012Validator(cells).is_valid([cell] * (total_cells + 1))


def test_explicit_recovery_candidate_budget_can_increase_without_changing_global_caps():
    from docgen.budgets import BudgetOverride, apply_budget

    original = saas_config().generation
    increased = apply_budget(original, BudgetOverride(max_candidates_per_item=20))
    assert increased.quality.max_candidates_per_item == 20
    assert increased.limits.model_dump(exclude={"max_requests"}) == (
        original.limits.model_dump(exclude={"max_requests"})
    )
    assert increased.request_limit == original.request_limit
    assert original.quality.max_candidates_per_item == 3
