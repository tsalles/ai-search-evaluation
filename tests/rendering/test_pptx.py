import copy
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from docgen.errors import InputError, IntegrityError
from docgen.extractors.pptx import read_pptx
from docgen.models import Content
from docgen.renderers.base import render_document
from docgen.text import business_units
from tests.fixtures.corrupt import rewrite_zip
from tests.fixtures.factories import quality_content
from tests.rendering.test_markdown import assignment
from tests.test_content_contract import example_content

P = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


def test_pptx_keeps_all_text_editable_and_tables_native_with_bounded_geometry(
    tmp_path: Path,
) -> None:
    content = Content.model_validate(example_content())
    artifact = render_document(content, assignment(content, "pptx"), tmp_path)
    path = tmp_path / artifact.filename
    readback = read_pptx(path)
    assert content.title in readback.paragraphs
    assert "Solicite avalia\u00e7\u00e3o." in readback.paragraphs
    assert readback.tables[0].rows[0][1] == "1,25"
    assert readback.structural_issues == ()
    with ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                root = ET.fromstring(archive.read(name))
                assert root.find(".//p:pic", P) is None
                assert root.find(".//p:oleObj", P) is None
                assert all(
                    int(node.attrib["sz"]) >= 1400 for node in root.iter() if "sz" in node.attrib
                )


def test_pptx_continuation_preserves_long_prose_and_every_table_row(tmp_path: Path) -> None:
    content = quality_content("comparison", words=1600, profile="complex")
    artifact = render_document(content, assignment(content, "pptx", "complex"), tmp_path)
    readback = read_pptx(tmp_path / artifact.filename)
    for unit in business_units(content):
        assert unit in readback.paragraphs or any(
            unit in cell
            for table in readback.tables
            for row in (table.headers, *table.rows)
            for cell in row
        )
    data = example_content()
    row = data["blocks"][-1]["table"]["rows"][0]
    data["blocks"][-1]["table"]["rows"] = [copy.deepcopy(row) for _ in range(40)]
    table_content = Content.model_validate(data)
    other = tmp_path / "other"
    other.mkdir()
    artifact = render_document(table_content, assignment(table_content, "pptx"), other)
    extracted = read_pptx(other / artifact.filename)
    assert len(extracted.tables) > 1
    assert sum(len(table.rows) for table in extracted.tables) == 40
    assert extracted.structural_issues == ()


def test_pptx_table_columns_expand_for_long_words_without_shrinking_or_changing_text(
    tmp_path: Path,
) -> None:
    data = quality_content("comparison").model_dump(mode="json")
    table = next(block["table"] for block in data["blocks"] if block["table"])
    headers = (
        "Conta", "Momento", "Mensalidade", "O que conferir",
        "Responsabilidade do cliente", "Leitura comparativa",
    )
    table["columns"] = [
        {"id": f"column-{index}", "name": header, "kind": "text", "unit": None}
        for index, header in enumerate(headers)
    ]
    table["rows"] = [
        [
            {"kind": "text", "value": value, "fact_id": None}
            for value in (
                "Conta Aurora", "Solicitacao", "Valor informado",
                "Conferir as condicoes.", "Confirmar os documentos.", "Ler as diferencas.",
            )
        ]
        for _ in range(3)
    ]
    content = Content.model_validate(data)
    artifact = render_document(content, assignment(content, "pptx"), tmp_path)
    path = tmp_path / artifact.filename
    extracted = read_pptx(path)
    assert extracted.tables[0].headers == headers
    assert extracted.structural_issues == ()
    assert sum(len(table.rows) for table in extracted.tables) == 3
    with ZipFile(path) as archive:
        grids = []
        for name in archive.namelist():
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                root = ET.fromstring(archive.read(name))
                grids.extend(root.findall(".//a:tblGrid", P))
                assert all(
                    int(node.attrib["sz"]) >= 1400 for node in root.iter() if "sz" in node.attrib
                )
        assert grids
        assert all(
            int(grid[4].attrib["w"]) > sum(int(column.attrib["w"]) for column in grid) / 6
            for grid in grids
        )


@pytest.mark.parametrize("following", ["paragraph", "callout", "list", "table", "heading-chain"])
def test_section_headings_stay_with_the_first_following_content(
    tmp_path: Path, following: str,
) -> None:
    data = example_content()
    table = data["blocks"][-1]
    data["blocks"] = [
        {"id": "preface", "kind": "paragraph", "text": "Contexto claro.\n" * 12 + "Fim."},
        {"id": "section", "kind": "heading", "level": 1, "text": "Condicoes especiais"},
    ]
    if following == "table":
        data["blocks"].append(table)
        prefix = "docgen-table:rates:"
    else:
        data["facts"] = []
        if following == "heading-chain":
            data["blocks"].append(
                {"id": "subsection", "kind": "heading", "level": 2, "text": "Detalhes"}
            )
        if following == "list":
            data["blocks"].append(
                {"id": "details", "kind": "ordered_list", "items": [
                    {"text": "Confira as condicoes antes de continuar.", "level": 1},
                ]}
            )
            prefix = "docgen-body:details-0:"
        else:
            data["blocks"].append(
                {"id": "details", "kind": "callout" if following == "callout" else "paragraph",
                 "text": "Confira as condicoes antes de continuar. Leia todos os detalhes."}
            )
            prefix = "docgen-body:details:"
    content = Content.model_validate(data)
    artifact = render_document(content, assignment(content, "pptx"), tmp_path)
    with ZipFile(tmp_path / artifact.filename) as archive:
        positions = {}
        for name in archive.namelist():
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                root = ET.fromstring(archive.read(name))
                for node in root.findall(".//p:cNvPr", P):
                    positions[node.get("name", "")] = name
    heading = positions["docgen-body:section:0"]
    first_body = next(value for key, value in positions.items() if key.startswith(prefix))
    assert heading == first_body
    if following == "heading-chain":
        assert positions["docgen-body:subsection:0"] == first_body
    assert read_pptx(tmp_path / artifact.filename).structural_issues == ()


def test_a_trailing_heading_is_not_silently_dropped(tmp_path: Path) -> None:
    data = example_content()
    data["blocks"].append(
        {"id": "unfinished", "kind": "heading", "level": 2, "text": "Sem conteudo"}
    )
    content = Content.model_validate(data)
    with pytest.raises(InputError, match="heading|Heading"):
        render_document(content, assignment(content, "pptx"), tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("location", ["paragraph", "cell"])
def test_pptx_rejects_unfit_blocks_without_shrinking_or_cutting(
    tmp_path: Path, location: str
) -> None:
    data = example_content()
    if location == "paragraph":
        data["blocks"][1]["text"] = "W" * 2048
    else:
        data["blocks"][-1]["table"]["rows"][0][0]["value"] = "line\n" * 40
    content = Content.model_validate(data)
    with pytest.raises(InputError, match="fit|width"):
        render_document(content, assignment(content, "pptx"), tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("damage", ["overflow", "small-font", "hidden"])
def test_pptx_saved_geometry_fonts_and_hidden_shapes_are_independently_checked(
    tmp_path: Path,
    damage: str,
) -> None:
    content = Content.model_validate(example_content())
    path = tmp_path / render_document(content, assignment(content, "pptx"), tmp_path).filename

    def alter(raw: bytes) -> bytes:
        root = ET.fromstring(raw)
        if damage == "overflow":
            root.find(".//p:sp/p:spPr/a:xfrm/a:off", P).set("x", "-10000")
        elif damage == "hidden":
            root.find(".//p:sp/p:nvSpPr/p:cNvPr", P).set("hidden", "1")
        else:
            root.find(".//a:defRPr", P).set("sz", "1000")
        return ET.tostring(root)

    rewrite_zip(path, "ppt/slides/slide1.xml", alter)
    if damage == "hidden":
        with pytest.raises(IntegrityError, match="hidden"):
            read_pptx(path)
    else:
        assert read_pptx(path).structural_issues
