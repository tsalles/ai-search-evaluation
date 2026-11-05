from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from docgen.errors import InputError, IntegrityError
from docgen.extractors.xlsx import read_xlsx
from docgen.models import Content
from docgen.renderers.base import render_document
from docgen.text import business_units
from tests.fixtures.corrupt import rewrite_zip
from tests.fixtures.factories import quality_content
from tests.rendering.test_markdown import assignment
from tests.test_content_contract import example_content

S = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def test_xlsx_retains_literal_formula_text_native_types_units_and_visible_sheets(
    tmp_path: Path,
) -> None:
    data = example_content()
    data["blocks"][-1]["table"]["rows"][0][0]["value"] = "=SUM(1,2)"
    content = Content.model_validate(data)
    artifact = render_document(content, assignment(content, "xlsx"), tmp_path)
    path = tmp_path / artifact.filename
    readback = read_xlsx(path)
    assert content.title in readback.paragraphs
    assert "Solicite avalia\u00e7\u00e3o." in readback.paragraphs
    table = readback.tables[0]
    assert table.rows[0] == ("=SUM(1,2)", "1,25", "23/10/2026", "Sim")
    assert table.cell_kinds[0] == ("text", "decimal", "date", "boolean")
    assert table.headers[1] == "Taxa (% ao m\u00eas)"
    with ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                root = ET.fromstring(archive.read(name))
                assert root.find(".//s:f", S) is None
                assert root.find(".//s:c[@t='e']", S) is None
                assert root.find(".//s:row[@hidden='1']", S) is None
        assert any(name.startswith("xl/tables/table") for name in archive.namelist())


def test_xlsx_divides_narrative_into_readable_rows_without_changing_business_text(
    tmp_path: Path,
) -> None:
    data = quality_content("comparison", words=1600, profile="complex").model_dump()
    data["blocks"][0]["text"] = "A/B:*?[long section name] " * 3
    content = Content.model_validate(data)
    artifact = render_document(content, assignment(content, "xlsx", "complex"), tmp_path)
    path = tmp_path / artifact.filename
    readback = read_xlsx(path)
    for unit in business_units(content):
        assert unit in readback.paragraphs or any(
            unit in cell
            for table in readback.tables
            for row in (table.headers, *table.rows)
            for cell in row
        )
    with ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        names = [node.attrib["name"] for node in workbook.findall("s:sheets/s:sheet", S)]
        assert all(len(name) <= 31 and not any(c in name for c in "/\\:*?[]") for name in names)
        assert len({name.casefold() for name in names}) == len(names)
        assert len(names) >= 3


@pytest.mark.parametrize("change", ["unfit-cell", "duplicate-header", "old-date", "control"])
def test_xlsx_rejects_unrepresentable_cells_instead_of_clipping_or_executing(
    tmp_path: Path,
    change: str,
) -> None:
    data = example_content()
    table = data["blocks"][-1]["table"]
    if change == "unfit-cell":
        table["rows"][0][0]["value"] = "line\n" * 40
    elif change == "duplicate-header":
        table["columns"][2]["name"] = "Produto"
    elif change == "old-date":
        table["rows"][0][2]["value"] = "1800-01-01"
    else:
        table["rows"][0][0]["value"] = "invalid\u0001text"
    content = Content.model_validate(data)
    expected = {
        "unfit-cell": "cannot fit",
        "duplicate-header": "unique",
        "old-date": "1900",
        "control": "control",
    }
    with pytest.raises(InputError, match=expected[change]):
        render_document(content, assignment(content, "xlsx"), tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "damage",
    [
        "hidden-sheet",
        "hidden-row",
        "formula",
        "error",
        "missing-cell",
        "nonfinite",
        "bad-coordinate",
    ],
)
def test_xlsx_independent_readback_detects_hidden_computed_and_missing_values(
    tmp_path: Path,
    damage: str,
) -> None:
    content = Content.model_validate(example_content())
    path = tmp_path / render_document(content, assignment(content, "xlsx"), tmp_path).filename
    with ZipFile(path) as archive:
        sheets = sorted(
            name
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )

    def alter(raw: bytes) -> bytes:
        root = ET.fromstring(raw)
        if damage == "hidden-sheet":
            root.find("s:sheets/s:sheet", S).set("state", "hidden")
        elif damage == "hidden-row":
            root.find(".//s:row", S).set("hidden", "1")
        else:
            row = root.find(".//s:row[@r='2']", S)
            cell = row.find("s:c", S)
            if damage == "formula":
                ET.SubElement(cell, "{" + S["s"] + "}f").text = "1+1"
            elif damage == "missing-cell":
                row.remove(cell)
            elif damage == "bad-coordinate":
                cell.set("r", "invalid")
            else:
                numeric = root.find(".//s:c[@t='n']", S)
                numeric.find("s:v", S).text = "NaN" if damage == "nonfinite" else "#REF!"
                if damage == "error":
                    numeric.set("t", "e")
        return ET.tostring(root)

    rewrite_zip(path, "xl/workbook.xml" if damage == "hidden-sheet" else sheets[-1], alter)
    with pytest.raises(IntegrityError):
        read_xlsx(path)


@pytest.mark.parametrize("number", ["0.00", "-12.50"])
def test_xlsx_preserves_numeric_sign_zero_and_display_precision(
    tmp_path: Path, number: str
) -> None:
    data = example_content()
    data["facts"][0].update(value=number, display=number.replace(".", ",") + "%")
    data["blocks"][-1]["table"]["rows"][0][1]["value"] = number
    content = Content.model_validate(data)
    artifact = render_document(content, assignment(content, "xlsx"), tmp_path)
    readback = read_xlsx(tmp_path / artifact.filename)
    assert readback.tables[0].rows[0][1] == number.replace(".", ",")
