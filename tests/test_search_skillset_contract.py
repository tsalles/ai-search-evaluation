import json
from pathlib import Path

import pytest

RESOURCES = Path(__file__).resolve().parents[1] / "ai_search_resources"


@pytest.fixture
def extraction_skillset() -> dict:
    return json.loads((RESOURCES / "skillset_de.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["generate-embeddings", "extract-keywords"])
def test_text_consumers_read_each_text_split_string(extraction_skillset: dict, name: str) -> None:
    split = next(
        skill for skill in extraction_skillset["skills"]
        if skill["@odata.type"] == "#Microsoft.Skills.Text.SplitSkill"
    )
    output = next(output for output in split["outputs"] if output["name"] == "textItems")
    chunk_path = f"{split['context']}/{output['targetName']}/*"
    consumer = next(skill for skill in extraction_skillset["skills"] if skill["name"] == name)
    text_input = next(item for item in consumer["inputs"] if item["name"] == "text")
    assert consumer["context"] == chunk_path
    assert text_input["source"] == chunk_path


def test_content_projection_reads_chunk_text_not_a_nonexistent_child(
    extraction_skillset: dict,
) -> None:
    for selector in extraction_skillset["indexProjections"]["selectors"]:
        content = next(mapping for mapping in selector["mappings"] if mapping["name"] == "content")
        assert content["source"] == selector["sourceContext"]
    assert extraction_skillset["indexProjections"]["parameters"] == {
        "projectionMode": "skipIndexingParentDocuments",
    }


def test_extraction_output_and_file_data_are_wired_to_the_chunker(
    extraction_skillset: dict,
) -> None:
    indexer = json.loads((RESOURCES / "indexer.json").read_text(encoding="utf-8"))
    assert indexer["skillsetName"] == extraction_skillset["name"]
    assert indexer["parameters"]["configuration"]["allowSkillsetToReadFileData"] is True
    extraction = next(
        skill for skill in extraction_skillset["skills"]
        if skill["@odata.type"] == "#Microsoft.Skills.Util.DocumentExtractionSkill"
    )
    output = next(output for output in extraction["outputs"] if output["name"] == "content")
    split = next(
        skill for skill in extraction_skillset["skills"]
        if skill["@odata.type"] == "#Microsoft.Skills.Text.SplitSkill"
    )
    text_input = next(item for item in split["inputs"] if item["name"] == "text")
    assert text_input["source"] == f"{extraction['context']}/{output['targetName']}"


def test_chunk_annotations_and_vector_dimensions_match_the_keywords_index(
    extraction_skillset: dict,
) -> None:
    index = json.loads((RESOURCES / "index-kw.json").read_text(encoding="utf-8"))
    fields = {field["name"]: field for field in index["fields"]}
    selector = extraction_skillset["indexProjections"]["selectors"][0]
    assert selector["targetIndexName"] == index["name"]
    assert fields[selector["parentKeyFieldName"]]["filterable"] is True
    mappings = {mapping["name"]: mapping for mapping in selector["mappings"]}
    for name in ("embedding", "keywords"):
        producer = next(
            skill for skill in extraction_skillset["skills"]
            if any(output["targetName"] == name for output in skill["outputs"])
        )
        path = f"{producer['context']}/{name}"
        assert mappings[name]["source"] == path + ("/*" if name == "keywords" else "")
    embedding = next(
        skill for skill in extraction_skillset["skills"]
        if skill["@odata.type"] == "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill"
    )
    assert fields["embedding"]["dimensions"] == embedding["dimensions"] == 3072
    assert fields["keywords"]["type"] == "Collection(Edm.String)"
