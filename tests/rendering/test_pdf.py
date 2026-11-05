import copy
from pathlib import Path

import pytest
from pypdf import PdfReader

from docgen.errors import InputError
from docgen.extractors.pdf import read_pdf
from docgen.facts import normalized
from docgen.models import Content
from docgen.renderers.base import render_document
from docgen.renderers.layout import font_assets
from docgen.text import business_units
from tests.fixtures.factories import quality_content
from tests.rendering.test_markdown import assignment
from tests.test_content_contract import example_content


def test_pdf_has_portable_embedded_fonts_native_unicode_text_and_tables(tmp_path: Path) -> None:
    content = Content.model_validate(example_content())
    artifact = render_document(content, assignment(content, "pdf"), tmp_path)
    path = tmp_path / artifact.filename
    readback = read_pdf(path)
    assert normalized(content.title) in normalized(" ".join(readback.paragraphs))
    assert readback.native_text
    assert readback.tables[0].rows[0][1] == "1,25"
    assert readback.tables[0].rows[0][2] == "23/10/2026"
    document = PdfReader(path)
    assert document.trailer["/Root"]["/Lang"] == "pt-BR"
    assert any(
        font.get_object().get("/FontDescriptor") is not None
        and "/FontFile2" in font.get_object()["/FontDescriptor"].get_object()
        for page in document.pages
        for font in page["/Resources"]["/Font"].values()
    )
    font, license_file = font_assets()
    assert font.is_file()
    assert "Bitstream" in license_file.read_text(encoding="utf-8")


def test_pdf_paginates_long_tables_and_reads_complex_columns_in_logical_order(
    tmp_path: Path,
) -> None:
    content = quality_content("comparison", words=1600, profile="complex")
    artifact = render_document(content, assignment(content, "pdf", "complex"), tmp_path)
    readback = read_pdf(tmp_path / artifact.filename, layout_profile="complex")
    body = normalized(" ".join(readback.paragraphs))
    table_text = normalized(
        " ".join(
            cell
            for table in readback.tables
            for row in (table.headers, *table.rows)
            for cell in row
        )
    )
    for unit in business_units(content):
        assert normalized(unit) in body or normalized(unit) in table_text
    data = example_content()
    row = data["blocks"][-1]["table"]["rows"][0]
    data["blocks"][-1]["table"]["rows"] = [copy.deepcopy(row) for _ in range(70)]
    content = Content.model_validate(data)
    other = tmp_path / "long"
    other.mkdir()
    artifact = render_document(content, assignment(content, "pdf"), other)
    readback = read_pdf(other / artifact.filename)
    assert len(readback.tables) > 1
    assert sum(len(table.rows) for table in readback.tables) == 70


@pytest.mark.parametrize(
    "text",
    ["W" * 2048, "Unsupported \U0001f680 glyph"],
    ids=["overlong-token", "unsupported-glyph"],
)
def test_pdf_fails_explicitly_on_unrenderable_tokens_or_glyphs(tmp_path: Path, text: str) -> None:
    data = example_content()
    data["blocks"][1]["text"] = text
    content = Content.model_validate(data)
    with pytest.raises(InputError, match="width|glyph"):
        render_document(content, assignment(content, "pdf"), tmp_path)
    assert list(tmp_path.iterdir()) == []
