import pytest

from docgen.evaluation.state import new_protocol
from docgen.models import Content
from docgen.planning import create_plan
from docgen.quality import Acceptance, assess
from tests.evaluation.fixtures import FamilyProvider
from tests.evaluation.test_saas_families import saas_config


def source():
    protocol = new_protocol(saas_config())
    config = protocol.generation_config.generation
    blueprint = create_plan(
        protocol.generation_config, run_id=protocol.source_run_id,
    ).blueprints[0]
    return FamilyProvider().generate(blueprint, config), config


def append_prose(content, text):
    data = content.model_dump(mode="python")
    paragraph = next(block for block in data["blocks"] if block["kind"] == "paragraph")
    paragraph["text"] += " " + text
    return Content.model_validate(data)


@pytest.mark.parametrize(
    "text",
    [
        "\u5929\u5f69\u7968",
        "aten\u200d\u200bcao",
        "texto\ufffc",
        "texto\ufeff",
        "texto\u0627",
        'comparativos?","level":null,"table_id":null}]}]',
        "<|endoftext|>",
        "```json",
        "@price-a",
        "implantacao,planejamento,equipe",
        "A contratacao deve esperar,porque",
    ],
)
def test_saas_rejects_foreign_glyphs_and_serialized_output_even_with_high_language_score(text):
    content, config = source()
    candidate = append_prose(content, text)
    with pytest.raises(ValueError, match="source text"):
        assess(candidate, config, detector=lambda *_: 1.0)


def test_saas_accepts_portable_portuguese_accents_without_rewriting_source_text():
    content, config = source()
    candidate = append_prose(content, "Ativa\u00e7\u00e3o, decis\u00e3o e servi\u00e7os.")
    verified = assess(candidate, config, detector=lambda *_: 1.0)
    assert verified.title == candidate.title
    assert verified.blocks == candidate.blocks
    assert "source_text" in verified.quality.checks


def test_failed_native_preflight_does_not_reserve_the_candidates_uniqueness():
    content, config = source()
    rejected = False

    def preflight(candidate):
        nonlocal rejected
        if not rejected:
            rejected = True
            raise ValueError("Assigned native layout cannot fit this candidate.")

    gate = Acceptance(config, detector=lambda *_: 1.0, validator=preflight)
    with pytest.raises(ValueError, match="native layout"):
        gate.accept(content)
    assert gate.accept(content).normalized_fingerprint


def test_advisory_prose_budgets_do_not_relax_the_canonical_document_word_band():
    content, config = source()
    data = content.model_dump(mode="python")
    facts = {fact.id: fact for fact in content.facts}

    def brief(refs):
        return (
            " ".join(facts[ref].entity + ": " + facts[ref].display + "." for ref in refs)
            or "Apoio."
        )

    for block in data["blocks"]:
        if block["kind"] in {"paragraph", "callout"}:
            block["text"] = brief(block["fact_refs"])
        for item in block["items"] or ():
            item["text"] = brief(item["fact_refs"])
    candidate = Content.model_validate(data)
    with pytest.raises(ValueError, match="word band"):
        assess(candidate, config, detector=lambda *_: 1.0)
