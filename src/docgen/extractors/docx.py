from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from docgen.errors import IntegrityError
from docgen.extractors.models import Readback, TableGrid
from docgen.extractors.ooxml import check_office, xml_part

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def paragraph_text(element: ET.Element) -> str:
    return "".join(
        node.text or "" if node.tag == W + "t" else "\n" if node.tag == W + "br" else "\t"
        for node in element.iter()
        if node.tag in {W + "t", W + "br", W + "tab"}
    )


def native_integer(value: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise IntegrityError("DOCX native structure has a noninteger level/count.") from exc
    if not minimum <= number <= maximum:
        raise IntegrityError("DOCX native structure has an unsupported level/count.")
    return number


def read_docx(path: Path) -> Readback:
    try:
        with ZipFile(path) as archive:
            check_office(archive)
            root = xml_part(archive, "word/document.xml")
    except (BadZipFile, OSError) as exc:
        raise IntegrityError("DOCX is not a readable Office package.") from exc
    body = root.find(W + "body")
    if body is None:
        raise IntegrityError("DOCX body is missing.")
    if any(
        node.tag in {W + "drawing", W + "object", W + "pict", W + "instrText"}
        or node.tag == W + "vanish"
        and node.get(W + "val", "true") not in {"false", "0"}
        for node in body.iter()
    ):
        raise IntegrityError("DOCX body contains hidden, rasterized, or active business content.")
    paragraphs = []
    tables: list[TableGrid] = []
    issues = []
    heading_levels = []
    list_levels = []
    for node in body:
        if node.tag == W + "p":
            style = node.find(W + "pPr/" + W + "pStyle")
            style_name = style.get(W + "val", "") if style is not None else ""
            if style_name in {"Heading1", "Heading2", "Heading3"}:
                heading_levels.append(int(style_name[-1]))
            numbering = node.find(W + "pPr/" + W + "numPr")
            if numbering is not None:
                level = numbering.find(W + "ilvl")
                list_levels.append(
                    native_integer(level.get(W + "val", "0"), 0, 1) + 1
                    if level is not None else 1
                )
            text = paragraph_text(node)
            if text:
                paragraphs.append(text)
        elif node.tag == W + "tbl":
            if node.find(".//" + W + "gridSpan") is not None or (
                node.find(".//" + W + "vMerge") is not None
            ):
                raise IntegrityError("Merged DOCX data cells are not supported.")
            rows = []
            native_rows = node.findall(W + "tr")
            for row in native_rows:
                rows.append(
                    tuple(
                        "\n".join(paragraph_text(p) for p in cell.findall(W + "p"))
                        for cell in row.findall(W + "tc")
                    )
                )
            if not rows or not rows[0]:
                raise IntegrityError("DOCX table has no header row.")
            if native_rows[0].find(".//" + W + "tblHeader") is None:
                issues.append("DOCX table header does not repeat across pages.")
            tables.append(
                TableGrid(
                    headers=rows[0],
                    rows=tuple(rows[1:]),
                    location=f"table-{len(tables)}",
                )
            )
    return Readback(
        paragraphs=tuple(paragraphs), tables=tuple(tables), structural_issues=tuple(issues),
        heading_levels=tuple(heading_levels), list_levels=tuple(list_levels),
        layout_features={
            "columns": max(
                (
                    native_integer(node.get(W + "num", "1"), 1, 2)
                    for node in body.iter(W + "cols")
                ),
                default=1,
            ),
            "sections": sum(1 for _ in body.iter(W + "sectPr")),
        },
    )
