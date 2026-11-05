import math
import re
import textwrap
from datetime import date
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import Cell as ExcelCell
from openpyxl.styles import Alignment, Font, NamedStyle, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table as ExcelTable
from openpyxl.worksheet.table import TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from docgen.errors import InputError, IntegrityError
from docgen.models import Content, Profile
from docgen.structure_models import LayoutPlan
from docgen.text import synthetic_notice, value_text

NARRATIVE_WIDTH = 100


def editable_cell(sheet: Worksheet, row: int, column: int) -> ExcelCell:
    cell = sheet.cell(row, column)
    if not isinstance(cell, ExcelCell):
        raise IntegrityError("Cannot place business content in a merged spreadsheet cell.")
    return cell


def safe_sheet_name(label: str, used: set[str]) -> str:
    base = re.sub(r"[\\/*?:\[\]]", " ", label).strip(" '")
    base = base[:31] or "Section"
    name = base
    suffix = 1
    while name.casefold() in used or name.casefold() == "history":
        suffix += 1
        tail = f"-{suffix}"
        name = base[: 31 - len(tail)] + tail
    used.add(name.casefold())
    return name


def literal(cell: ExcelCell, text: str) -> None:
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]", text):
        raise InputError("XLSX cannot represent XML control characters.")
    if len(text) > 32767:
        raise InputError("XLSX cell exceeds its text limit.")
    cell.value = text
    cell.data_type = "s"


def row_height(text: str, width: float, *, font: int = 11) -> float:
    characters = max(1, int(width * 0.5 * 11 / font))
    lines = sum(
        max(
            1,
            len(
                textwrap.wrap(
                    line, width=characters, replace_whitespace=False, break_on_hyphens=False
                )
            ),
        )
        for line in text.split("\n")
    )
    height = max(18, lines * (font + 4))
    if height > 409:
        raise InputError("XLSX text cannot fit in a visible row at the minimum font size.")
    return float(height)


def text_chunks(text: str) -> list[str]:
    result = []
    start = 0
    while start < len(text):
        end = min(start + 180, len(text))
        if end < len(text):
            boundary = max(text.rfind(" ", start, end), text.rfind("\n", start, end))
            if boundary > start:
                end = boundary + 1
            else:
                following = re.search(r"\s", text[end:])
                end = end + following.end() if following else len(text)
        breaks = list(re.finditer("\n", text[start:end]))
        if len(breaks) > 8:
            end = start + breaks[7].end()
        result.append(text[start:end])
        start = end
    return result


def render_xlsx(
    content: Content, destination: Path, layout_profile: Profile = "baseline",
    layout_plan: LayoutPlan | None = None,
) -> None:
    workbook = Workbook()
    workbook.iso_dates = True
    workbook.properties.title = content.title
    workbook.properties.creator = "Synthetic Document Generator"
    workbook.properties.lastModifiedBy = "docgen"
    workbook.properties.language = content.blueprint.locale
    for name, size, bold, indent in (
        ("DocgenTitle", 18, True, 0),
        ("DocgenNotice", 11, False, 0),
        ("DocgenHeading", 14, True, 0),
        ("DocgenHeading1", 14, True, 0),
        ("DocgenHeading2", 13, True, 0),
        ("DocgenHeading3", 12, True, 0),
        ("DocgenText", 11, False, 0),
        ("DocgenContinuation", 11, False, 0),
        ("DocgenList1", 11, False, 1),
        ("DocgenList2", 11, False, 2),
        ("DocgenCallout", 11, False, 1),
        ("DocgenTableHeader", 11, True, 0),
        ("DocgenTable", 11, False, 0),
    ):
        style = NamedStyle(
            name=name,
            font=Font(name="Arial", size=size, bold=bold, color="000000"),
            alignment=Alignment(wrap_text=True, vertical="top", indent=indent),
        )
        if name == "DocgenTableHeader":
            style.fill = PatternFill("solid", fgColor="DDEBF7")
        workbook.add_named_style(style)
    current = workbook.active
    if not isinstance(current, Worksheet):
        raise IntegrityError("New workbook is missing its visible worksheet.")
    used: set[str] = set()
    current.title = safe_sheet_name(
        "Visao geral" if content.blueprint.language == "pt" else "Overview", used
    )

    def narrative(sheet: Worksheet, text: str, style: str, *, font: int = 11) -> None:
        sheet.column_dimensions["A"].width = NARRATIVE_WIDTH
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "A2"
        for index, chunk in enumerate(text_chunks(text)):
            row = sheet.max_row + 1 if sheet.cell(1, 1).value is not None else 1
            cell = editable_cell(sheet, row, 1)
            cell.style = style if index == 0 else "DocgenContinuation"
            literal(cell, chunk)
            sheet.row_dimensions[row].height = row_height(
                chunk, NARRATIVE_WIDTH, font=font if index == 0 else 11
            )

    narrative(current, content.title, "DocgenTitle", font=18)
    narrative(current, synthetic_notice(content.blueprint.language), "DocgenNotice")
    table_index = 0
    for block in content.blocks:
        if block.kind == "heading" and block.text is not None:
            if block.level == 1 and (layout_plan is None or layout_plan.recipe != "compact"):
                current = workbook.create_sheet(safe_sheet_name(block.text, used))
            heading_style = (
                f"DocgenHeading{block.level}"
                if content.blueprint.structure_plan is not None else "DocgenHeading"
            )
            narrative(current, block.text, heading_style, font=14)
        elif block.items:
            for item in block.items:
                narrative(current, item.text, f"DocgenList{item.level}")
        elif block.table:
            table_index += 1
            source = block.table
            sheet = workbook.create_sheet(safe_sheet_name(f"Tabela-{table_index}", used))
            sheet.freeze_panes = "A2"
            sheet.print_title_rows = "1:1"
            sheet.sheet_view.showGridLines = False
            headers = [
                column.name + (f" ({column.unit})" if column.unit else "")
                for column in source.columns
            ]
            if len({" ".join(label.casefold().split()) for label in headers}) != len(headers):
                raise InputError(f"XLSX table headers must be unique: {block.id}.")
            widths = []
            for index, column in enumerate(source.columns):
                displays = [
                    headers[index],
                    *(
                        value_text(row[index].value, content.blueprint.locale)
                        for row in source.rows
                    ),
                ]
                longest = max(len(line) for text in displays for line in text.split("\n"))
                width = min(180, max(18, math.ceil(longest / 20) * 2))
                if column.kind != "text":
                    width = min(180, max(18, longest * 2 + 2))
                widths.append(width)
                sheet.column_dimensions[get_column_letter(index + 1)].width = width
                cell = editable_cell(sheet, 1, index + 1)
                cell.style = "DocgenTableHeader"
                literal(cell, headers[index])
            sheet.row_dimensions[1].height = max(
                row_height(header, width) for header, width in zip(headers, widths, strict=True)
            )
            for row_index, row in enumerate(source.rows, 2):
                heights = []
                for column_index, (source_cell, width) in enumerate(
                    zip(row, widths, strict=True), 1
                ):
                    cell = editable_cell(sheet, row_index, column_index)
                    cell.style = "DocgenTable"
                    value = source_cell.value
                    if isinstance(value, Decimal):
                        numeric = float(value)
                        if Decimal(str(numeric)) != value:
                            raise InputError(f"XLSX numeric precision is not portable: {block.id}.")
                        cell.value = numeric
                        exponent = value.as_tuple().exponent
                        assert isinstance(exponent, int)
                        places = max(0, -exponent)
                        cell.number_format = "0" + ("." + "0" * places if places else "")
                    elif isinstance(value, bool):
                        cell.value = value
                    elif isinstance(value, date):
                        if value.year < 1900:
                            raise InputError(
                                "XLSX native dates must be in the 1900 or later calendar."
                            )
                        cell.value = value
                        cell.number_format = (
                            "dd/mm/yyyy" if content.blueprint.locale == "pt-BR" else "yyyy-mm-dd"
                        )
                    else:
                        literal(cell, value)
                    heights.append(row_height(value_text(value, content.blueprint.locale), width))
                sheet.row_dimensions[row_index].height = max(heights)
            table = ExcelTable(
                displayName=f"DocgenTable{table_index}",
                ref=f"A1:{get_column_letter(len(source.columns))}{len(source.rows) + 1}",
            )
            table.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium2", showRowStripes=True, showColumnStripes=False
            )
            sheet.add_table(table)
        elif block.text is not None:
            narrative(
                current, block.text, "DocgenCallout" if block.kind == "callout" else "DocgenText"
            )
    with destination.open("xb") as stream:
        workbook.save(stream)
    workbook.close()
