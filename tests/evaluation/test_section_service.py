import hashlib
import json

import pytest

from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.ingestion import ingest, prepare
from docgen.evaluation.models import ExperimentConfig
from docgen.evaluation.resources import definitions
from docgen.evaluation.section_service import (
    ModelResult,
    canonical_request,
    checked_section_row,
    handle_skill_request,
)
from docgen.evaluation.sectioning import (
    markdown_source,
    single_section_plan,
)
from docgen.evaluation.state import new_protocol
from tests.evaluation.fixtures import experiment_config
from tests.evaluation.test_azure import azure_fixture

TEXT = "A literal title\nA paragraph with the applicable rule.\nA second paragraph.\n"


def successful_model(request):
    exposed = json.loads(request["messages"][1]["content"])
    text = "".join(block["text"] for block in exposed["blocks"])
    source = markdown_source(text, split_extracted_paragraphs=True)
    plan = single_section_plan(source).model_dump(mode="json")
    plan["title_block"] = "b0000"
    return ModelResult(
        content=json.dumps(plan), model="gpt-5.4-mini-test",
        request_key=hashlib.sha256(canonical_request(request)).hexdigest(),
    )


def payload(text=TEXT):
    return {"values": [{
        "recordId": "source-opaque",
        "data": {"text": text, "source_path": "https://storage.example/raw/input.pdf"},
    }]}


def test_plain_extracted_text_exposes_ordered_lines_without_rewriting():
    source = markdown_source(TEXT, split_extracted_paragraphs=True)
    assert len(source.blocks) == 3
    assert source.blocks[0].label == "A literal title"
    assert "".join(source.text[b.start:b.end] for b in source.blocks) == TEXT
    assert markdown_source(TEXT).sha256 == source.sha256


def test_long_extracted_lines_have_bounded_reference_units_and_complete_coverage():
    text = "Long line without paragraph separators. " * 120
    source = markdown_source(text, split_extracted_paragraphs=True)
    assert len(source.blocks) > 1
    assert max(block.end - block.start for block in source.blocks) <= 800
    assert "".join(text[block.start:block.end] for block in source.blocks) == text


def test_web_api_preserves_record_id_and_returns_only_original_text_sections():
    result = handle_skill_request(payload(), deployment="gpt-5.4-mini", model_call=successful_model)
    record = result["values"][0]
    assert record["recordId"] == "source-opaque"
    assert record["errors"] == record["warnings"] == []
    enriched = record["data"]["enrichment"]
    assert enriched["source_text"] == TEXT
    assert "".join(section["text"] for section in enriched["sections"]) == TEXT
    metadata = enriched["sections"][0]["metadata"]
    assert metadata["title"] == "A literal title"
    checked = checked_section_row({
        "source_text": TEXT, "content": TEXT, "section_metadata": metadata,
    })
    assert checked["source_sha256"] == hashlib.sha256(TEXT.encode()).hexdigest()


def test_source_uri_is_not_a_model_feature():
    def model(request):
        assert "storage.example" not in json.dumps(request)
        assert "source-opaque" not in json.dumps(request)
        return successful_model(request)

    assert handle_skill_request(payload(), deployment="gpt-5.4-mini", model_call=model)[
        "values"
    ][0]["errors"] == []


@pytest.mark.parametrize("bad", [
    None, {}, {"values": []}, {"values": [payload()["values"][0]] * 2},
    {"values": [{"recordId": "x", "data": {"text": TEXT}}]},
])
def test_invalid_web_api_batches_are_rejected_before_model_dispatch(bad):
    def forbidden(request):
        pytest.fail("Malformed inputs must not dispatch a model request.")

    with pytest.raises(InputError):
        handle_skill_request(bad, deployment="gpt-5.4-mini", model_call=forbidden)


def test_model_failures_are_explicit_record_errors_not_empty_successes():
    def failed(request):
        raise ProviderError("quota", "The model quota was rejected.")

    record = handle_skill_request(
        payload(), deployment="gpt-5.4-mini", model_call=failed,
    )["values"][0]
    assert record["data"] == {}
    assert record["errors"] == [{"message": "The model quota was rejected."}]


def test_model_response_must_bind_to_the_exact_request():
    def unbound(request):
        result = successful_model(request).model_dump()
        result["request_key"] = "0" * 64
        return ModelResult.model_validate(result)

    result = handle_skill_request(payload(), deployment="gpt-5.4-mini", model_call=unbound)
    assert result["values"][0]["errors"]
    assert result["values"][0]["data"] == {}


@pytest.mark.parametrize("field,value", [
    ("source_start", 1), ("source_end", 1), ("source_sha256", "0" * 64),
    ("title", "invented title"), ("heading", "invented heading"), ("ordinal", True),
])
def test_indexed_metadata_cannot_change_source_spans_or_invent_labels(field, value):
    result = handle_skill_request(payload(), deployment="gpt-5.4-mini", model_call=successful_model)
    metadata = result["values"][0]["data"]["enrichment"]["sections"][0]["metadata"]
    metadata[field] = value
    with pytest.raises(IntegrityError):
        checked_section_row({"source_text": TEXT, "content": TEXT, "section_metadata": metadata})


def test_pipeline_places_sectioning_after_extraction_and_before_native_split_embedding():
    config = experiment_config().model_dump(mode="json")
    config["search"]["variant"] = {"section_enrichment": {
        "uri": "https://owned.azurewebsites.net/api/sections",
        "auth_resource_id": "api://00000000-0000-0000-0000-000000000001",
    }}
    protocol = new_protocol(ExperimentConfig.model_validate_json(json.dumps(config)))
    resources = definitions(protocol, "de_split")
    skills = resources["skillsets"]["skills"]
    assert [skill["name"] for skill in skills] == [
        "document-extraction", "grounded-section-planning", "text-split", "embeddings",
    ]
    assert skills[1]["inputs"][0]["source"] == "/document/extracted_content"
    assert skills[2]["inputs"][0]["source"] == (
        "/document/section_enrichment/sections/*/text"
    )
    assert skills[2]["maximumPageLength"] == 2000
    assert skills[2]["pageOverlapLength"] == 200
    assert skills[3]["inputs"][0]["source"] == (
        "/document/section_enrichment/sections/*/pages/*"
    )
    assert "apiKey" not in json.dumps(resources)
    assert skills[1]["batchSize"] == skills[1]["degreeOfParallelism"] == 1
    assert "section_metadata" in {field["name"] for field in resources["indexes"]["fields"]}
    for field in resources["indexes"]["fields"]:
        if field["name"] in {"source_text", "model_audit_payload"}:
            assert field["searchable"] is False
            assert field["filterable"] is field["sortable"] is field["facetable"] is False
    assert len(resources["indexes"]["semantic"]["configurations"]) == 2
    assert [skill["name"] for skill in definitions(protocol, "content_understanding")[
        "skillsets"
    ]["skills"]] == ["content-understanding", "embeddings"]


def test_single_arm_preparation_and_ingestion_leave_the_other_index_slot_unused(staged_workspace):
    azure, _, _, _ = azure_fixture(staged_workspace)
    with azure:
        prepare(staged_workspace, azure, live=True, arms=("de_split",))
        statuses = ingest(staged_workspace, azure, live=True, arms=("de_split",))
    assert set(statuses) == {"de_split"}
    assert staged_workspace.get("resource:de_split:indexes") is not None
    assert staged_workspace.get("resource:content_understanding:indexes") is None
