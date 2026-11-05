import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from docgen.errors import IntegrityError
from docgen.extractors.models import Readback, TableGrid
from docgen.extractors.ooxml import check_office, part_target, xml_part
from docgen.text import value_text

S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def coordinate(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Z]+)([1-9]\d*)", text)
    if match is None:
        raise IntegrityError("Invalid spreadsheet cell coordinate.")
    column = 0
    for letter in match[1]:
        column = column * 26 + ord(letter) - ord("A") + 1
    return int(match[2]), column


def read_workbook(archive: ZipFile) -> Readback:
    check_office(archive)
    workbook = xml_part(archive, "xl/workbook.xml")
    core = xml_part(archive, "docProps/core.xml")
    language = core.find("{http://purl.org/dc/elements/1.1/}language")
    locale = language.text if language is not None else None
    if locale not in {"pt-BR", "en-US"}:
        raise IntegrityError("Spreadsheet locale is missing or unsupported.")
    style_root = xml_part(archive, "xl/styles.xml")
    names = {
        int(node.attrib["xfId"]): node.attrib["name"]
        for node in style_root.findall(S + "cellStyles/" + S + "cellStyle")
    }
    formats = {0: "General", 1: "0", 2: "0.00"}
    formats.update(
        {
            int(node.attrib["numFmtId"]): node.attrib["formatCode"]
            for node in style_root.findall(S + "numFmts/" + S + "numFmt")
        }
    )
    style_names, style_formats = [], []
    for style in style_root.findall(S + "cellXfs/" + S + "xf"):
        style_names.append(names.get(int(style.get("xfId", "0")), "Normal"))
        style_formats.append(formats.get(int(style.get("numFmtId", "0")), "unsupported"))
    shared = []
    if "xl/sharedStrings.xml" in archive.namelist():
        shared = [
            "".join(node.text or "" for node in item.iter(S + "t"))
            for item in xml_part(archive, "xl/sharedStrings.xml")
        ]
    relationship_root = xml_part(archive, "xl/_rels/workbook.xml.rels")
    relationships = {node.attrib["Id"]: node.attrib["Target"] for node in relationship_root}
    paragraphs: list[str] = []
    tables: list[TableGrid] = []
    heading_levels: list[int] = []
    list_levels: list[int] = []
    sheet_count = 0
    narrative_sheets = 0
    for sheet in workbook.findall(S + "sheets/" + S + "sheet"):
        sheet_count += 1
        if sheet.get("state", "visible") != "visible":
            raise IntegrityError("Spreadsheet has a hidden worksheet.")
        sheet_part = part_target("xl/workbook.xml", relationships[sheet.attrib[R + "id"]])
        root = xml_part(archive, sheet_part)
        if root.find(S + "mergeCells") is not None:
            raise IntegrityError("Merged spreadsheet cells are not supported.")
        if any(node.get("hidden") in {"1", "true"} for node in root.iter()):
            raise IntegrityError("Spreadsheet has hidden rows or columns.")
        cells: dict[tuple[int, int], tuple[str, str, str]] = {}
        for cell in root.findall(S + "sheetData/" + S + "row/" + S + "c"):
            if cell.find(S + "f") is not None:
                raise IntegrityError("Spreadsheet formulas are forbidden in this corpus.")
            position = coordinate(cell.attrib["r"])
            style_index = int(cell.get("s", "0"))
            if not 0 <= style_index < len(style_names):
                raise IntegrityError("Unknown spreadsheet cell style.")
            role = style_names[style_index]
            kind = cell.get("t", "n")
            value_node = cell.find(S + "v")
            raw = value_node.text if value_node is not None else None
            if kind == "inlineStr":
                text = "".join(node.text or "" for node in cell.iter(S + "t"))
                semantic_kind = "text"
            elif kind == "s":
                if raw is None or not 0 <= int(raw) < len(shared):
                    raise IntegrityError("Invalid shared-string reference.")
                text, semantic_kind = shared[int(raw)], "text"
            elif kind == "str":
                text, semantic_kind = raw or "", "text"
            elif kind == "b":
                if raw not in {"0", "1"}:
                    raise IntegrityError("Invalid spreadsheet Boolean.")
                text, semantic_kind = value_text(raw == "1", locale), "boolean"
            elif kind == "d":
                if raw is None or style_formats[style_index] not in {"dd/mm/yyyy", "yyyy-mm-dd"}:
                    raise IntegrityError("Invalid or ambiguous spreadsheet date formatting.")
                text = value_text(date.fromisoformat(raw.split("T")[0]), locale)
                semantic_kind = "date"
            elif kind == "n":
                if raw is None:
                    continue
                number = Decimal(raw)
                number_format = style_formats[style_index]
                if number_format != "General" and not re.fullmatch(r"0(?:\.0+)?", number_format):
                    raise IntegrityError("Spreadsheet numeric formatting changes value semantics.")
                if not number.is_finite():
                    raise IntegrityError("Spreadsheet numeric cell is not finite.")
                if "." in number_format:
                    places = len(number_format.split(".")[1])
                    number = Decimal(format(number, f".{places}f"))
                text, semantic_kind = value_text(number, locale), "decimal"
            else:
                raise IntegrityError("Unsupported or erroneous spreadsheet cell type.")
            cells[position] = (text, semantic_kind, role)
        excluded: set[tuple[int, int]] = set()
        table_parts = root.findall(S + "tableParts/" + S + "tablePart")
        if table_parts:
            base, leaf = sheet_part.rsplit("/", 1)
            links = xml_part(archive, f"{base}/_rels/{leaf}.rels")
            targets = {node.attrib["Id"]: node.attrib["Target"] for node in links}
            for table_part in table_parts:
                table = xml_part(
                    archive, part_target(sheet_part, targets[table_part.attrib[R + "id"]])
                )
                start, end = table.attrib["ref"].split(":")
                r1, c1 = coordinate(start)
                r2, c2 = coordinate(end)
                rows = []
                kinds = []
                for row in range(r1, r2 + 1):
                    values, row_kinds = [], []
                    for column in range(c1, c2 + 1):
                        if (row, column) not in cells:
                            raise IntegrityError("Native table range contains a missing cell.")
                        text, kind, _ = cells[row, column]
                        values.append(text)
                        row_kinds.append(kind)
                        excluded.add((row, column))
                    rows.append(tuple(values))
                    kinds.append(tuple(row_kinds))
                tables.append(
                    TableGrid(
                        headers=rows[0],
                        rows=tuple(rows[1:]),
                        cell_kinds=tuple(kinds[1:]),
                        location=f"{sheet.attrib['name']}!{table.attrib['ref']}",
                    )
                )
        narrative = False
        for position, (text, _, role) in sorted(cells.items()):
            if position in excluded:
                continue
            narrative = True
            if role in {"DocgenHeading1", "DocgenHeading2", "DocgenHeading3"}:
                heading_levels.append(int(role[-1]))
            elif role == "DocgenHeading":
                heading_levels.append(1)
            elif role in {"DocgenList1", "DocgenList2"}:
                list_levels.append(int(role[-1]))
            if role == "DocgenContinuation" and paragraphs:
                paragraphs[-1] += text
            else:
                paragraphs.append(text)
        narrative_sheets += int(narrative)
    return Readback(
        paragraphs=tuple(paragraphs), tables=tuple(tables),
        heading_levels=tuple(heading_levels), list_levels=tuple(list_levels),
        layout_features={"worksheets": sheet_count, "narrative_sheets": narrative_sheets},
    )


def read_xlsx(path: Path) -> Readback:
    try:
        with ZipFile(path) as archive:
            return read_workbook(archive)
    except (BadZipFile, OSError, ValueError, KeyError, InvalidOperation) as exc:
        raise IntegrityError("Invalid native spreadsheet package or cell data.") from exc
