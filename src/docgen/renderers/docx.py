from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.enum.section import WD_SECTION_START
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.section import Section
from docx.shared import Mm, Pt, RGBColor, Twips
from docx.styles.style import ParagraphStyle

from docgen.errors import IntegrityError
from docgen.models import Content, Profile
from docgen.structure_models import LayoutPlan
from docgen.text import synthetic_notice, value_text


def set_columns(section: Section, count: int) -> None:
    columns = section._sectPr.find(qn("w:cols"))
    if columns is None:
        raise IntegrityError("Word template is missing native column settings.")
    columns.set(qn("w:num"), str(count))
    columns.set(qn("w:space"), "360")


def numbering(document: DocumentObject, ordered: bool) -> int:
    root = document.part.numbering_part.element
    numbers = root.findall(qn("w:num"))
    abstracts = root.findall(qn("w:abstractNum"))
    number_id = max((int(node.attrib[qn("w:numId")]) for node in numbers), default=0) + 1
    abstract_id = (
        max((int(node.attrib[qn("w:abstractNumId")]) for node in abstracts), default=0) + 1
    )
    abstract = OxmlElement("w:abstractNum", {qn("w:abstractNumId"): str(abstract_id)})
    abstract.append(OxmlElement("w:multiLevelType", {qn("w:val"): "multilevel"}))
    for level in (0, 1):
        entry = OxmlElement("w:lvl", {qn("w:ilvl"): str(level)})
        entry.append(OxmlElement("w:start", {qn("w:val"): "1"}))
        entry.append(OxmlElement("w:numFmt", {qn("w:val"): "decimal" if ordered else "bullet"}))
        entry.append(
            OxmlElement("w:lvlText", {qn("w:val"): f"%{level + 1}." if ordered else "\u2022"})
        )
        properties = OxmlElement("w:pPr")
        properties.append(
            OxmlElement("w:ind", {qn("w:left"): str(360 * (level + 1)), qn("w:hanging"): "180"})
        )
        entry.append(properties)
        abstract.append(entry)
    if numbers:
        numbers[0].addprevious(abstract)
    else:
        root.append(abstract)
    number = OxmlElement("w:num", {qn("w:numId"): str(number_id)})
    number.append(OxmlElement("w:abstractNumId", {qn("w:val"): str(abstract_id)}))
    root.append(number)
    return number_id


def render_docx(
    content: Content, destination: Path, layout_profile: Profile = "baseline",
    layout_plan: LayoutPlan | None = None,
) -> None:
    if layout_plan is not None:
        layout_profile = layout_plan.profile
    document = Document()
    zoom = document.settings.element.find(qn("w:zoom"))
    if zoom is not None:
        zoom.set(qn("w:percent"), "100")
    section = document.sections[0]
    page_width, margin = Mm(210), Mm(19)
    section.page_width, section.page_height = page_width, Mm(297)
    section.left_margin = section.right_margin = margin
    section.top_margin = section.bottom_margin = margin
    full_twips = page_width.twips - 2 * margin.twips
    usable_twips = full_twips
    if layout_profile == "complex":
        set_columns(section, 2)
        usable_twips = (usable_twips - 360) // 2
    for name, size in (
        ("Normal", 11),
        ("Title", 20),
        ("Heading 1", 16),
        ("Heading 2", 14),
        ("Heading 3", 12),
        ("Quote", 11),
    ):
        style = document.styles[name]
        if not isinstance(style, ParagraphStyle):
            raise IntegrityError(f"Default Word template is missing paragraph style: {name}.")
        style.font.name = "Arial"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(0, 0, 0)
        style_properties = style._element.get_or_add_rPr()
        language = style_properties.find(qn("w:lang"))
        if language is None:
            language = OxmlElement("w:lang")
            style_properties.append(language)
        language.set(qn("w:val"), content.blueprint.locale)
        style.paragraph_format.space_after = Pt(6)
    document.core_properties.title = content.title
    document.core_properties.author = "Synthetic Document Generator"
    document.core_properties.last_modified_by = "docgen"
    document.core_properties.language = content.blueprint.locale
    document.add_paragraph(content.title, style="Title")
    document.add_paragraph(synthetic_notice(content.blueprint.language))
    for block in content.blocks:
        if block.kind == "heading":
            assert block.text is not None and block.level is not None
            document.add_heading(block.text, level=block.level)
        elif block.items:
            number_id = numbering(document, block.kind == "ordered_list")
            for item in block.items:
                paragraph = document.add_paragraph(item.text)
                number_properties = paragraph._p.get_or_add_pPr().get_or_add_numPr()
                number_properties.get_or_add_ilvl().val = item.level - 1
                number_properties.get_or_add_numId().val = number_id
        elif block.table:
            source = block.table
            wide = layout_profile == "complex" and len(source.columns) > 4
            if wide:
                set_columns(document.add_section(WD_SECTION_START.CONTINUOUS), 1)
            table_width = full_twips if wide else usable_twips
            table = document.add_table(rows=1, cols=len(source.columns))
            table.style = "Table Grid"
            table.autofit = False
            widths = [table_width // len(source.columns)] * len(source.columns)
            widths[-1] += table_width - sum(widths)
            width = table._tbl.tblPr.find(qn("w:tblW"))
            if width is None:
                raise IntegrityError("Word table is missing its width definition.")
            width.set(qn("w:type"), "dxa")
            width.set(qn("w:w"), str(table_width))
            margins = OxmlElement("w:tblCellMar")
            for side, amount in (("top", 80), ("start", 100), ("bottom", 80), ("end", 100)):
                margins.append(
                    OxmlElement(f"w:{side}", {qn("w:w"): str(amount), qn("w:type"): "dxa"})
                )
            look = table._tbl.tblPr.find(qn("w:tblLook"))
            if look is None:
                table._tbl.tblPr.append(margins)
            else:
                look.addprevious(margins)
            for index, column in enumerate(source.columns):
                table.columns[index].width = Twips(widths[index])
                cell = table.rows[0].cells[index]
                cell.width = Twips(widths[index])
                cell.text = column.name + (f" ({column.unit})" if column.unit else "")
                for run in cell.paragraphs[0].runs:
                    run.bold = True
            table.rows[0]._tr.get_or_add_trPr().append(
                OxmlElement("w:tblHeader", {qn("w:val"): "true"})
            )
            for row in source.rows:
                cells = table.add_row().cells
                for index, cell in enumerate(row):
                    cells[index].width = Twips(widths[index])
                    cells[index].text = value_text(cell.value, content.blueprint.locale)
            if wide:
                set_columns(document.add_section(WD_SECTION_START.CONTINUOUS), 2)
        elif block.text is not None:
            paragraph = document.add_paragraph(
                block.text, style="Quote" if block.kind == "callout" else "Normal"
            )
            paragraph.paragraph_format.keep_together = False
    with destination.open("xb") as stream:
        document.save(stream)
