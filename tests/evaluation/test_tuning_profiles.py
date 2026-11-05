import json

import pytest
from pydantic import ValidationError

from docgen.errors import InputError
from docgen.evaluation.models import Query, SearchVariant
from docgen.evaluation.profiles import PROFILES, retrieval_request, scope
from docgen.evaluation.resources import definitions
from docgen.evaluation.runner import hybrid_request
from docgen.evaluation.state import new_protocol
from tests.evaluation.fixtures import experiment_config


def test_original_request_and_optional_config_serialization_are_unchanged():
    query = Query(id="q-one", text="Qual e o valor da Conta Aurora?")
    assert retrieval_request(query, [0.1, 0.2], profile="hybrid") == hybrid_request(
        query, [0.1, 0.2]
    )
    assert "variant" not in experiment_config().search.model_dump(mode="json")
    assert "variant" not in json.loads(experiment_config().model_dump_json())["search"]


def test_profiles_separate_bm25_vectors_and_hybrid_weights():
    query = Query(id="q-one", text="Conta Aurora")
    bm25 = retrieval_request(query, None, profile="bm25")
    assert "vectorQueries" not in bm25
    vector = retrieval_request(query, [0.1], profile="vector")
    assert "search" not in vector and "searchFields" not in vector
    for profile, weight in (("hybrid-lexical", 0.5), ("hybrid-vector", 2.0)):
        body = retrieval_request(query, [0.1], profile=profile)
        assert body["vectorQueries"][0]["weight"] == weight
        assert body["search"] == query.text
    with pytest.raises(InputError, match="vector"):
        retrieval_request(query, None, profile="vector")
    assert len({scope("development", profile) for profile in PROFILES}) == len(PROFILES)
    with pytest.raises(InputError, match="profile"):
        scope("development", "unknown")


def test_entity_profile_only_boosts_names_observed_in_query_and_keeps_scope_soft():
    base = "Conta Aurora Bosque"
    plus = base + " Plus"
    query = Query(id="q-plus", text=f"Quanto custa {plus}?")
    body = retrieval_request(
        query, [0.1], profile="entity-semantic", account_names=(base, plus, "Conta Estranha")
    )
    assert '"' + plus + '"^4' in body["search"]
    assert '"' + base + '"^4' not in body["search"]
    assert "Conta Estranha" not in body["search"]
    assert "filter" not in body
    assert body["semanticQuery"] == query.text
    assert body["semanticConfiguration"] == "source-context"
    assert body["semanticErrorHandling"] == "fail"
    plain = retrieval_request(query, [0.1], profile="semantic-hybrid")
    assert plain["semanticConfiguration"] == "content-only"


@pytest.mark.parametrize(
    "settings",
    [
        {"de_tokens": True}, {"de_tokens": 127}, {"de_tokens": 2049},
        {"de_tokens": 512, "de_overlap_tokens": 512},
        {"cu_tokens": 99}, {"cu_tokens": 8001}, {"embedding_context": "yes"},
    ],
)
def test_native_variant_controls_are_strict_and_bounded(settings):
    with pytest.raises(ValidationError):
        SearchVariant.model_validate(settings)


def test_historical_scoring_profile_weights_keep_the_azure_double_contract():
    settings = experiment_config()
    search = settings.search.model_copy(update={"variant": SearchVariant()})
    protocol = new_protocol(settings.model_copy(update={"search": search})).model_copy(
        update={"schema_version": "1", "enrichment_policy": None},
    )
    for arm in ("de_split", "content_understanding"):
        weights = definitions(protocol, arm)["indexes"]["scoringProfiles"][0]["text"]["weights"]
        assert weights == {"title": 2.0, "account_names": 4.0, "content": 1.0}
        assert all(type(value) is float for value in weights.values())
