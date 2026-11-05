from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from docgen.extractors import read_document
from docgen.facts import normalized
from docgen.models import Block, Cell, Column, Content, Table
from docgen.renderers.base import render_document
from docgen.text import business_units
from tests.fixtures.factories import quality_content
from tests.rendering.test_markdown import assignment


def complex_reference() -> Content:
    content = quality_content("comparison", words=1100, profile="complex")
    content = content.model_copy(
        update={
            "blueprint": content.blueprint.model_copy(update={"length_band": "long"}),
        }
    )
    columns = tuple(
        Column(id=f"col-{index}", name=f"Campo {label}", kind="text")
        for index, label in enumerate(
            ("Alfa", "Beta", "Gama", "Delta", "Epsilon", "Zeta", "Eta", "Teta")
        )
    )
    table = Table(
        id="wide-data",
        columns=columns,
        rows=tuple(
            tuple(
                Cell(kind="text", value=f"valor {label}")
                for label in ("alfa", "beta", "gama", "delta", "epsilon", "zeta", "eta", "teta")
            )
            for _ in range(12)
        ),
    )
    blocks = (
        *content.blocks,
        Block(id="wide-block", kind="table", table=table),
        Block(id="closing", kind="paragraph", text="Revise todas as condicoes antes de concluir."),
    )
    return Content.model_validate({**content.model_dump(), "blocks": blocks})


@pytest.mark.parametrize("fmt", ["md", "html", "docx", "xlsx", "pptx", "pdf"])
def test_complex_reference_preserves_every_source_unit_and_native_table_row(
    tmp_path: Path,
    fmt: str,
) -> None:
    content = complex_reference()
    artifact = render_document(content, assignment(content, fmt, "complex"), tmp_path)
    readback = read_document(tmp_path / artifact.filename, fmt, "complex")
    body = normalized(" ".join(readback.paragraphs))
    cells = normalized(
        " ".join(
            cell
            for table in readback.tables
            for row in (table.headers, *table.rows)
            for cell in row
        )
    )
    assert readback.native_text
    assert readback.structural_issues == ()
    for unit in business_units(content):
        assert normalized(unit) in body or normalized(unit) in cells
    assert sum(len(table.rows) for table in readback.tables) == 15
    if fmt == "docx":
        with ZipFile(tmp_path / artifact.filename) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        assert root.find(".//w:cols[@w:num='1']", ns) is not None
        assert root.find(".//w:cols[@w:num='2']", ns) is not None
