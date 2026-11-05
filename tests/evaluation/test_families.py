import copy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from docgen.errors import InputError
from docgen.evaluation.models import ExperimentConfig
from docgen.evaluation.state import new_protocol
from docgen.families import create_families, family_for, scoped_facts
from docgen.models import Fact
from docgen.planning import create_plan
from docgen.quality import Acceptance
from tests.evaluation.fixtures import FamilyProvider, experiment_config


def test_frozen_family_preset_is_seeded_split_safe_and_covers_all_roles():
    first = create_families(
        60,
        seed=3,
        language="en",
        split_weights={
            "calibration": 0.2,
            "development": 0.2,
            "test": 0.6,
        },
    )
    assert first == create_families(
        60,
        seed=3,
        language="en",
        split_weights={
            "calibration": 0.2,
            "development": 0.2,
            "test": 0.6,
        },
    )
    assert len({entity for family in first for entity in family.entities}) == 120
    assert sum(family.split == "calibration" for family in first) == 12
    assert sum(family.split == "development" for family in first) == 12
    assert sum(family.split == "test" for family in first) == 36
    protocol = new_protocol(experiment_config())
    plan = create_plan(protocol.generation_config, run_id=protocol.source_run_id)
    assert plan.algorithm_version == "4"
    assert all(blueprint.family_id and blueprint.required_fact_ids for blueprint in plan.blueprints)
    assert len({blueprint.family_id for blueprint in plan.blueprints[:6]}) == 1
    assert plan.blueprints[0].family_id != plan.blueprints[6].family_id


def test_family_acceptance_rejects_unscoped_or_missing_facts_through_public_gate():
    protocol = new_protocol(experiment_config())
    generation = protocol.generation_config.generation
    blueprint = create_plan(
        protocol.generation_config,
        run_id=protocol.source_run_id,
    ).blueprints[0]
    original = FamilyProvider().generate(blueprint, generation)
    assert Acceptance(generation).accept(original).quality.word_count > 0
    extra = Fact(
        id="invented",
        entity=original.facts[0].entity,
        kind="text",
        value="unsupported attribute",
        display="unsupported attribute",
    )
    with pytest.raises(ValueError, match="only their scoped"):
        Acceptance(generation).accept(
            original.model_copy(update={"facts": (*original.facts, extra)})
        )
    changed = original.facts[0].model_copy(update={"value": Decimal("99.90")})
    with pytest.raises(ValueError):
        Acceptance(generation).accept(
            original.model_copy(update={"facts": (changed, *original.facts[1:])}),
        )
    with pytest.raises(InputError, match="unknown experiment family"):
        family_for(blueprint.model_copy(update={"family_id": "missing-family"}), generation)
    with pytest.raises(InputError, match="unknown family fact"):
        scoped_facts(blueprint.model_copy(update={"required_fact_ids": ("missing",)}), generation)


@pytest.mark.parametrize(
    "change",
    [
        lambda data: data.update(family_count=3),
        lambda data: data["generation"].update(
            shared_facts=[
                {
                    "id": "extra",
                    "entity": "global",
                    "kind": "text",
                    "value": "value",
                    "display": "value",
                }
            ]
        ),
        lambda data: data["search"].update(endpoint="http://offline.search.windows.net"),
        lambda data: data["search"].update(
            endpoint="https://offline.search.windows.net/?key=secret"
        ),
        lambda data: data["search"].update(ai_services_endpoint="https://untrusted.example"),
        lambda data: data["search"].update(model_name="text-embedding-3-small", dimensions=3072),
        lambda data: data["search"]["embedding"].update(api="responses"),
        lambda data: data["storage"].update(resource_id="/subscriptions/not-an-account"),
        lambda data: data["storage"].update(
            resource_id=data["storage"]["resource_id"].replace(
                "resourceGroups/offline/",
                "resourceGroups/offline;AccountKey=not-a-key/",
            )
        ),
        lambda data: data["storage"].update(container="invalid--container"),
        lambda data: data.update(split_weights={"test": 0.4}),
        lambda data: data.update(
            split_weights={
                "test": -0.1,
                "calibration": 0.2,
                "development": 0.9,
            }
        ),
        lambda data: data.update(split_weights={"test": True}),
        lambda data: data.update(split_weights={"test": "1"}),
        lambda data: data["limits"].update(max_search_attempts=0),
    ],
)
def test_experiment_config_rejects_mismatched_families_unsafe_endpoints_and_incoherent_budgets(
    change,
):
    data = copy.deepcopy(experiment_config().model_dump(mode="python"))
    change(data)
    with pytest.raises(ValidationError):
        ExperimentConfig.model_validate(data)


def test_embedding_and_document_provider_contracts_keep_their_actual_api_kinds():
    config = experiment_config()
    assert config.search.embedding.api == "embeddings"
    assert config.generation.provider.api == "responses"
    assert ExperimentConfig.model_validate_json(config.model_dump_json()) == config
