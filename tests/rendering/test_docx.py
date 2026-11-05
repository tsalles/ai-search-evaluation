import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

from docgen.extractors.docx import read_docx
from docgen.models import Content
from docgen.renderers.base import render_document
from docgen.text import business_units
from tests.fixtures.factories import quality_content
from tests.rendering.test_markdown import assignment
from tests.test_content_contract import example_content

W = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def test_docx_contains_editable_native_styles_numbering_and_typed_table_text(
    tmp_path: Path,
) -> None:
    content = Content.model_validate(example_content())
    artifact = render_document(content, assignment(content, "docx"), tmp_path)
    path = tmp_path / artifact.filename
    readback = read_docx(path)
    assert content.title in readback.paragraphs
    assert "Solicite avalia\u00e7\u00e3o." in readback.paragraphs
    assert readback.tables[0].rows[0][1] == "1,25"
    assert readback.tables[0].rows[0][2] == "23/10/2026"
    assert readback.structural_issues == ()
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        assert root.find(".//w:numPr/w:ilvl[@w:val='1']", W) is not None
        assert root.find(".//w:tblHeader", W) is not None
        assert root.find(".//w:trHeight", W) is None
        assert root.find(".//w:drawing", W) is None
        assert "word/vbaProject.bin" not in archive.namelist()
        numbering = ET.fromstring(archive.read("word/numbering.xml"))
        assert numbering.findall("w:num", W)
        assert root.find(".//w:tblW[@w:type='dxa']", W) is not None
        assert root.find(".//w:tblCellMar/w:start", W) is not None
        settings = ET.fromstring(archive.read("word/settings.xml"))
        assert settings.find("w:zoom[@w:percent='100']", W) is not None


def test_docx_long_content_and_complex_columns_preserve_every_unit(tmp_path: Path) -> None:
    content = quality_content("comparison", words=1600, profile="complex")
    artifact = render_document(content, assignment(content, "docx", "complex"), tmp_path)
    path = tmp_path / artifact.filename
    readback = read_docx(path)
    for unit in business_units(content):
        assert unit in readback.paragraphs or any(
            unit in cell
            for table in readback.tables
            for row in (table.headers, *table.rows)
            for cell in row
        )
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        assert root.find(".//w:cols[@w:num='2']", W) is not None
