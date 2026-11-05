import json

import pytest
from pydantic import ValidationError

from docgen.errors import InputError, IntegrityError
from docgen.evaluation.entities import checked_entity_data
from docgen.evaluation.ingestion import ingest, prepare
from docgen.evaluation.models import ARMS, ExperimentConfig, Query
from docgen.evaluation.profiles import retrieval_request
from docgen.evaluation.reports import score
from docgen.evaluation.resources import definitions
from docgen.evaluation.runner import collect
from docgen.evaluation.snapshots import assert_stable, take_snapshot
from docgen.evaluation.state import Workspace, new_protocol
from docgen.evaluation.variants import fork_experiment
from tests.evaluation.fixtures import experiment_config
from tests.evaluation.test_azure import azure_fixture


def entity_config(source=None):
    settings = source.protocol.config if source is not None else experiment_config()
    data = json.loads(settings.model_dump_json())
    data["search"]["variant"] = {
        "entity_extraction": {
            "deployment": "gpt-5.4-mini",
            "base_url": "https://offline.openai.azure.com/openai/v1/",
        },
    }
    return ExperimentConfig.model_validate_json(json.dumps(data))


def test_entity_skill_uses_only_each_arms_native_text_and_keeps_native_embeddings():
    protocol = new_protocol(entity_config())
    for arm in ARMS:
        resources = definitions(protocol, arm)
        skills = resources["skillsets"]["skills"]
        entity = next(skill for skill in skills if skill["name"] == "pipeline-entities")
        embedding = next(skill for skill in skills if skill["name"] == "embeddings")
        expected = "/document/pages/*" if arm == "de_split" else "/document/text_sections/*/content"
        assert entity["inputs"][-1] == {"name": "text", "source": expected}
        assert embedding["inputs"] == [{"name": "text", "source": expected}]
        assert "apiKey" not in entity
        assert entity["extraParameters"]["max_completion_tokens"] == 1024
        assert "maxTokens" not in entity["commonModelParameters"]
        assert entity["uri"] == "https://offline.openai.azure.com/openai/v1/chat/completions"
        assert type(entity["commonModelParameters"]["temperature"]) is int
        assert entity["responseFormat"]["type"] == "jsonSchema"
        schema = entity["responseFormat"]["jsonSchemaProperties"]["schema"]
        assert json.loads(schema["properties"]) == {
            "entities": {"type": "array", "items": {"type": "string"}},
        }
        assert {field["name"] for field in resources["indexes"]["fields"]} == {
            "id", "parent_id", "content", "content_path", "embedding", "entity_data",
        }
        selector = resources["skillsets"]["indexProjections"]["selectors"][0]
        assert selector["mappings"][-1]["source"].endswith("/entity_extraction")
        assert resources["indexers"]["parameters"]["batchSize"] == 1


def test_pipeline_entity_profile_uses_original_query_without_a_name_catalog():
    query = Query(id="q-one", text="Quanto custa o produto mencionado?")
    body = retrieval_request(query, [0.1], profile="pipeline-entity-hybrid")
    assert body["search"] == query.text
    assert body["queryType"] == "simple"
    assert body["searchFields"] == "content,entity_data/entities"
    assert body["scoringProfile"] == "pipeline-entities"
    assert "filter" not in body
    assert "semanticQuery" not in body


def test_entities_are_pipeline_outputs_not_external_annotations(
    staged_workspace, tmp_path, monkeypatch,
):
    def forbidden(*args, **kwargs):
        pytest.fail("A pipeline treatment accessed canonical entity metadata.")

    monkeypatch.setattr("docgen.evaluation.context.source_contexts", forbidden)
    path = fork_experiment(staged_workspace, entity_config(staged_workspace), tmp_path / "entity")
    with Workspace(path) as workspace:
        azure, backend, _, _ = azure_fixture(workspace)
        backend.normalize_resources = True
        for arm in ARMS:
            backend.chunks[arm][0]["content"] = "Conta Teste Vento Plus custa dez unidades."
            backend.chunks[arm][0]["entity_data"] = {"entities": ["Conta Teste Vento Plus"]}
        with azure:
            prepare(workspace, azure, live=True)
            ingest(workspace, azure, live=True)
            for arm in ARMS:
                observed = take_snapshot(workspace, azure, arm, live=True)
                assert observed.chunks[0].entities == ("Conta Teste Vento Plus",)
                assert all(chunk.source_context is None for chunk in observed.chunks)
            for profile in ("hybrid", "pipeline-entity-hybrid"):
                assert len(collect(
                    workspace, azure, live=True, profile=profile, count_tokens=lambda _: 25,
                )) == 48
                report = score(workspace, profile=profile)
                assert report["pipeline_entity_coverage"]["de_split"]["chunks_with_entities"] == 1
            assert not any(
                request.url.path.endswith("/docs/index")
                or "/embeddings" in str(request.url) and
                "Conta Teste Vento Plus" in request.content.decode()
                for request in backend.requests
            )
            backend.chunks["de_split"][0]["entity_data"] = {"entities": ["Conta Teste Vento"]}
            with pytest.raises(IntegrityError, match="drift"):
                assert_stable(workspace, azure, "de_split")


@pytest.mark.parametrize("damage", [None, "bad", [12], [""], ["not in native text"]])
def test_invalid_or_ungrounded_entity_outputs_cannot_enter_snapshots(
    staged_workspace, tmp_path, damage,
):
    path = fork_experiment(staged_workspace, entity_config(staged_workspace), tmp_path / "entity")
    with Workspace(path) as workspace:
        azure, backend, _, _ = azure_fixture(workspace)
        backend.chunks["de_split"][0]["entity_data"] = {"entities": damage}
        with azure:
            prepare(workspace, azure, live=True)
            ingest(workspace, azure, live=True)
            with pytest.raises(IntegrityError, match="entit"):
                take_snapshot(workspace, azure, "de_split", live=True)
        assert workspace.get("snapshot:de_split") is None


def test_entity_profile_requires_an_explicit_pipeline_extractor(staged_workspace):
    azure, backend, _, _ = azure_fixture(staged_workspace)
    with azure, pytest.raises(InputError, match="entity extractor"):
        collect(staged_workspace, azure, live=True, profile="pipeline-entity-hybrid")
    assert not backend.requests


@pytest.mark.parametrize("base_url", [
    "http://offline.openai.azure.com/openai/v1/",
    "https://example.com/openai/v1/",
    "https://offline.openai.azure.com/openai/v1/?key=secret",
    "https://offline.cognitiveservices.azure.com/openai/v1/",
])
def test_entity_endpoint_is_an_explicit_secret_free_model_endpoint(base_url):
    data = json.loads(entity_config().model_dump_json())
    data["search"]["variant"]["entity_extraction"]["base_url"] = base_url
    with pytest.raises(ValidationError):
        ExperimentConfig.model_validate_json(json.dumps(data))


def test_missing_entity_endpoint_is_rejected_before_protocol_creation():
    data = json.loads(entity_config().model_dump_json())
    data["search"]["variant"]["entity_extraction"].pop("base_url")
    with pytest.raises(InputError, match="base URL"):
        new_protocol(ExperimentConfig.model_validate_json(json.dumps(data)))


@pytest.mark.parametrize("value", [None, {}, {"entities": [], "extra": "data"}])
def test_missing_or_extra_entity_object_fields_are_not_silently_defaulted(value):
    with pytest.raises(IntegrityError, match="structured"):
        checked_entity_data(value, "Native document text")


def test_whitespace_policy_preserves_source_words_and_keeps_v1_character_exact():
    value = {"entities": ["Conta Vento Claro"]}
    assert checked_entity_data(value, "Conta Vento\nClaro", version="2") == ("Conta Vento Claro",)
    with pytest.raises(IntegrityError, match="source-grounded"):
        checked_entity_data(value, "Conta Vento\nClaro", version="1")


@pytest.mark.parametrize("name,source", [
    ("a conta", "à conta"),
    ("Conta Vento", "conta Vento"),
    ("Conta Solar", "ContaSolar"),
])
def test_whitespace_policy_does_not_allow_other_repairs(name, source):
    with pytest.raises(IntegrityError, match="source-grounded"):
        checked_entity_data({"entities": [name]}, source, version="2")


def test_entity_indexers_are_started_sequentially(staged_workspace, tmp_path):
    path = fork_experiment(staged_workspace, entity_config(staged_workspace), tmp_path / "entity")
    with Workspace(path) as workspace:
        azure, backend, _, _ = azure_fixture(workspace)
        backend.statuses["de_split"]["lastResult"]["status"] = "inProgress"
        with azure:
            prepare(workspace, azure, live=True)
            statuses = ingest(workspace, azure, live=True)
            assert statuses["content_understanding"]["status"] == "notStarted"
            assert not any(
                key.startswith("indexers/") and "-cu-" in key for key in backend.resources
            )
            backend.statuses["de_split"]["lastResult"]["status"] = "success"
            statuses = ingest(workspace, azure, live=True)
            assert all(status["status"] == "success" for status in statuses.values())


def test_native_ner_treatment_uses_source_spans_and_a_structured_empty_safe_shape():
    data = json.loads(entity_config().model_dump_json())
    data["search"]["variant"]["entity_extraction"] = {"version": "3", "method": "ner"}
    protocol = new_protocol(ExperimentConfig.model_validate_json(json.dumps(data)))
    for arm in ARMS:
        resources = definitions(protocol, arm)
        skills = resources["skillsets"]["skills"]
        ner = next(skill for skill in skills if skill["name"] == "pipeline-entities")
        shaper = next(skill for skill in skills if skill["name"] == "shape-pipeline-entities")
        assert ner["@odata.type"] == "#Microsoft.Skills.Text.V3.EntityRecognitionSkill"
        assert ner["categories"] == ["Product", "Organization"]
        assert ner["defaultLanguageCode"] == "pt"
        assert "uri" not in ner and "apiKey" not in ner
        assert shaper["inputs"][0]["source"].endswith("/recognized_entities/*/text")
        assert shaper["outputs"] == [{"name": "output", "targetName": "entity_extraction"}]
        assert resources["indexers"]["parameters"]["batchSize"] == 1
    with pytest.raises(IntegrityError):
        checked_entity_data({"entities": ["Conta Vento Claro"]}, "Conta Vento\nClaro", version="3")
    assert checked_entity_data(
        {"entities": ["Banco", "Banco"]}, "Banco e Banco", version="3",
    ) == ("Banco", "Banco")
