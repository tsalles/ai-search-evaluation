from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from docgen.allocation import allocate
from docgen.config import RenderConfig
from docgen.models import Content
from docgen.renderers.base import render_document
from docgen.validation import validate_artifact, validate_set
from tests.fixtures.corrupt import rewrite_zip
from tests.rendering.test_complex_profiles import complex_reference
from tests.rendering.test_markdown import assignment
from tests.test_content_contract import example_content


@pytest.mark.parametrize("fmt", ["md", "html", "docx", "xlsx", "pptx", "pdf"])
@pytest.mark.parametrize("complex", [False, True])
def test_saved_artifact_validation_checks_all_source_blocks_and_tables(
    tmp_path: Path,
    fmt: str,
    complex: bool,
) -> None:
    content = complex_reference() if complex else Content.model_validate(example_content())
    selected = assignment(content, fmt, "complex" if complex else "baseline")
    artifact = render_document(content, selected, tmp_path)
    report = validate_artifact(content, selected, tmp_path, expected_sha256=artifact.sha256)
    assert report.valid, report
    assert report.issues == ()
    assert report.filename == artifact.filename
    assert all(
        block.id in {location.block_id for location in report.locations} for block in content.blocks
    )


@pytest.mark.parametrize("damage", ["fact", "swap-cells", "hidden", "broken"])
def test_validation_rejects_missing_facts_and_swapped_cells_even_with_tokens_present(
    tmp_path: Path,
    damage: str,
) -> None:
    content = Content.model_validate(example_content())
    selected = assignment(content, "docx")
    artifact = render_document(content, selected, tmp_path)
    path = tmp_path / artifact.filename
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    def alter(raw: bytes) -> bytes:
        if damage == "broken":
            return b"<broken"
        root = ET.fromstring(raw)
        if damage == "fact":
            for node in root.iter(namespace + "t"):
                if node.text and "1,25%" in node.text:
                    node.text = node.text.replace("1,25%", "9,99%")
        elif damage == "swap-cells":
            row = root.find(".//" + namespace + "tbl").findall(namespace + "tr")[1]
            cells = list(row)
            row.remove(cells[0])
            row.insert(1, cells[0])
        else:
            run = next(root.iter(namespace + "r"))
            properties = ET.SubElement(run, namespace + "rPr")
            ET.SubElement(properties, namespace + "vanish")
        return ET.tostring(root)

    rewrite_zip(path, "word/document.xml", alter)
    report = validate_artifact(content, selected, tmp_path)
    assert not report.valid
    assert report.issues
    if damage == "fact":
        assert any(issue.block_id == "p1" for issue in report.issues)
    if damage == "swap-cells":
        assert any(issue.block_id == "t1" for issue in report.issues)


def test_checksum_unexpected_text_and_extra_files_are_not_successes(tmp_path: Path) -> None:
    content = Content.model_validate(example_content())
    selected = assignment(content, "html")
    artifact = render_document(content, selected, tmp_path)
    path = tmp_path / artifact.filename
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "</main>", "<p>Unapproved extra business assertion.</p></main>"
        ),
        encoding="utf-8",
    )
    assert not validate_artifact(content, selected, tmp_path, expected_sha256=artifact.sha256).valid
    semantic = validate_artifact(content, selected, tmp_path)
    assert not semantic.valid
    assert any(issue.code == "unexpected_text" for issue in semantic.issues)
    plan = allocate((content,), RenderConfig(weights={"html": 1}))
    assert not validate_set(tmp_path, (content,), plan).valid
    path.unlink()
    render_document(content, plan.items[0], tmp_path)
    assert validate_set(tmp_path, (content,), plan).valid
    (tmp_path / "answer-key.json").write_text("{}", encoding="utf-8")
    assert not validate_set(tmp_path, (content,), plan).valid


def test_source_missing_file_and_native_geometry_fail_the_public_validation_gate(
    tmp_path: Path,
) -> None:
    content = Content.model_validate(example_content())
    selected = assignment(content, "pptx")
    assert not validate_artifact(content, selected, tmp_path).valid
    invalid_source = selected.model_copy(update={"source_hash": "0" * 64})
    assert validate_artifact(content, invalid_source, tmp_path).issues[0].code == "source_hash"
    path = tmp_path / render_document(content, selected, tmp_path).filename

    def small_font(raw: bytes) -> bytes:
        root = ET.fromstring(raw)
        element = root.find(".//{http://schemas.openxmlformats.org/drawingml/2006/main}defRPr")
        element.set("sz", "900")
        return ET.tostring(root)

    rewrite_zip(path, "ppt/slides/slide1.xml", small_font)
    report = validate_artifact(content, selected, tmp_path)
    assert not report.valid
    assert any(issue.code == "structure" for issue in report.issues)


@pytest.mark.parametrize("damage", ["header", "extra-table"])
def test_table_headers_and_unplanned_tables_cannot_be_hidden_by_text_presence(
    tmp_path: Path,
    damage: str,
) -> None:
    content = Content.model_validate(example_content())
    selected = assignment(content, "docx")
    path = tmp_path / render_document(content, selected, tmp_path).filename

    def alter(raw: bytes) -> bytes:
        root = ET.fromstring(raw)
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        table = root.find(".//" + namespace + "tbl")
        if damage == "header":
            next(table.iter(namespace + "t")).text = "Different column"
        else:
            root.find(namespace + "body").insert(0, ET.fromstring(ET.tostring(table)))
        return ET.tostring(root)

    rewrite_zip(path, "word/document.xml", alter)
    report = validate_artifact(content, selected, tmp_path)
    assert not report.valid
    expected = "table_headers" if damage == "header" else "unexpected_table"
    assert any(issue.code == expected for issue in report.issues)
