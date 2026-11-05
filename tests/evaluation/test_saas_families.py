import json
import re

from docgen.evaluation.corpus import generate_sources
from docgen.evaluation.models import ExperimentConfig
from docgen.evaluation.reference import build_reference
from docgen.evaluation.state import Workspace, new_protocol
from docgen.planning import create_plan
from docgen.prompts import author_prompt
from tests.evaluation.fixtures import FamilyProvider, experiment_config


def saas_config():
    values = experiment_config().model_dump(mode="python")
    values["family_domain"] = "saas"
    values["seed"] = 20261104
    return ExperimentConfig.model_validate(values)


def test_saas_preset_uses_new_family_names_facts_and_document_roles():
    config = saas_config()
    protocol = new_protocol(config)
    repeat = new_protocol(config)
    generation = protocol.generation_config.generation
    families = generation.families
    assert families == repeat.generation_config.generation.families
    another = new_protocol(config.model_copy(update={"seed": config.seed + 1}))
    assert not {entity for family in families for entity in family.entities} & {
        entity for family in another.generation_config.generation.families
        for entity in family.entities
    }
    legacy = new_protocol(experiment_config()).generation_config.generation.families
    assert not {entity for family in families for entity in family.entities} & {
        entity for family in legacy for entity in family.entities
    }
    assert all(
        family.domain == "saas" and family.id.startswith("saas-family-")
        for family in families
    )
    assert all(
        {"price-a", "sla-a", "activation-a", "restriction-a", "workflow-a"}
        <= {fact.id for fact in family.facts}
        for family in families
    )
    assert all(not fact.id.startswith("age-") for family in families for fact in family.facts)
    plan = create_plan(protocol.generation_config, run_id=protocol.source_run_id)
    assert plan.blueprints[1].required_fact_ids == ("sla-a", "workflow-a")
    assert plan.blueprints[3].required_fact_ids == ("price-a", "price-b", "sla-a", "sla-b")
    prompt = author_prompt(plan.blueprints[1], generation)
    assert "first account" not in prompt
    assert "two accounts" not in prompt
    assert "opening deposit" not in prompt
    assert "SaaS" in prompt


def test_absent_domain_extensions_preserve_legacy_json_and_banking_families():
    config = experiment_config()
    assert "family_domain" not in json.loads(config.model_dump_json())
    protocol = new_protocol(config)
    families = protocol.generation_config.generation.families
    assert all("domain" not in json.loads(family.model_dump_json()) for family in families)
    assert all(family.id.startswith("family-") for family in families)
    assert all("Conta Aurora" in entity for family in families for entity in family.entities)
    assert ExperimentConfig.model_validate_json(config.model_dump_json()) == config


def test_saas_native_sources_build_fresh_domain_specific_queries_and_qrels(tmp_path):
    with Workspace.create(tmp_path, new_protocol(saas_config())) as workspace:
        assert generate_sources(workspace, provider=FamilyProvider()).status == "complete"
        reference = build_reference(workspace)
        assert len(reference.documents) == 12
        assert len(reference.intents) == 12
        assert {intent.task_type for intent in reference.intents} == {
            "subscription-price", "response-sla", "service-exclusion",
            "plan-comparison", "activation-and-ownership", "unanswerable",
        }
        assert all(
            claim.id.startswith("saas-family-") for claim in reference.claims
        )
        questions = " ".join(query.text for intent in reference.intents for query in intent.queries)
        assert "emprestimo" not in questions.lower()
        assert re.search(r"\bidade\b", questions, re.IGNORECASE) is None
        assert "primeira resposta" in questions.lower()
        comparison = next(
            intent for intent in reference.intents if intent.task_type == "plan-comparison"
        )
        assert len(comparison.required_claims) == 4
        assert any(judgment.grade == 3 for judgment in comparison.judgments)
        assert all(
            not intent.required_claims for intent in reference.intents if not intent.answerable
        )
