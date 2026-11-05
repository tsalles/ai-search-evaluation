import math
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pptx import Presentation
from pptx.dml.color import ColorFormat, RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.oxml.xmlchemy import OxmlElement
from pptx.slide import Slide
from pptx.text.text import TextFrame
from pptx.util import Pt

from docgen.errors import InputError, IntegrityError
from docgen.models import Content, Profile
from docgen.renderers.layout import column_minimums, layout_text, wrap_lines
from docgen.structure_models import LayoutPlan
from docgen.text import synthetic_notice, value_text

SLIDE_W, SLIDE_H = 960.0, 540.0
BODY_X, BODY_Y, BODY_W, BODY_BOTTOM = 48.0, 112.0, 864.0, 460.0
_rgb: Callable[[int, int, int], RGBColor] = RGBColor
INK = _rgb(33, 33, 33)
WHITE = _rgb(255, 255, 255)
PAPER = _rgb(242, 242, 242)
CHARCOAL = _rgb(54, 69, 79)


class SolidFill(Protocol):
    def solid(self) -> None: ...

    @property
    def fore_color(self) -> ColorFormat: ...


def paint(fill: SolidFill, color: RGBColor) -> None:
    fill.solid()
    fill.fore_color.rgb = color


def style_text(
    frame: TextFrame,
    text: str,
    size: float,
    *,
    bold: bool = False,
    color: RGBColor = INK,
    bullet: str | None = None,
    number: int = 1,
    level: int = 1,
) -> None:
    frame.text = layout_text(text)
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    frame.vertical_anchor = MSO_ANCHOR.TOP
    frame.margin_top = frame.margin_bottom = Pt(4)
    frame.margin_left = frame.margin_right = Pt(6)
    for index, paragraph in enumerate(frame.paragraphs):
        paragraph.level = level - 1
        paragraph.font.name = "Arial"
        paragraph.font.size = Pt(size)
        paragraph.font.bold = bold
        paragraph.font.color.rgb = color
        paragraph.space_before = paragraph.space_after = Pt(0)
        paragraph.line_spacing = Pt(size * 1.35)
        properties = paragraph._p.get_or_add_pPr()
        element = OxmlElement("a:buNone")
        if bullet is not None and index == 0:
            paragraph.level = level - 1
            properties.set("marL", str(int(Pt(18 * level))))
            properties.set("indent", str(int(Pt(-10))))
            if bullet == "ordered_list":
                element = OxmlElement("a:buAutoNum")
                element.set("type", "arabicPeriod")
                element.set("startAt", str(number))
            else:
                element = OxmlElement("a:buChar")
                element.set("char", "\u2022")
        properties.insert_element_before(element, "a:tabLst", "a:defRPr", "a:extLst")


class SlideFlow:
    def __init__(self, content: Content) -> None:
        self.presentation = Presentation()
        self.presentation.slide_width, self.presentation.slide_height = Pt(SLIDE_W), Pt(SLIDE_H)
        self.presentation.core_properties.title = content.title
        self.presentation.core_properties.author = "Synthetic Document Generator"
        self.presentation.core_properties.last_modified_by = "docgen"
        self.presentation.core_properties.language = content.blueprint.locale
        self.language = content.blueprint.language
        self.headings: list[tuple[str, str]] = []
        self.heading_levels = {
            block.id: block.level or 1 for block in content.blocks if block.kind == "heading"
        }
        self.slide = self.new_slide()
        self.y = BODY_Y

    def new_slide(self) -> Slide:
        slide = self.presentation.slides.add_slide(self.presentation.slide_layouts[6])
        if not isinstance(slide, Slide):
            raise IntegrityError("PowerPoint template did not create a native slide.")
        paint(slide.background.fill, PAPER)
        for x, y, width, height, color in (
            (36, 36, 888, 48, CHARCOAL),
            (36, 100, 888, 368, WHITE),
        ):
            panel = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Pt(x), Pt(y), Pt(width), Pt(height))
            paint(panel.fill, color)
            panel.line.color.rgb = color
            panel.line.width = Pt(0)
            panel.name = "docgen-decoration"
        header = slide.shapes.add_textbox(Pt(48), Pt(45), Pt(850), Pt(30))
        header.name = "docgen-decoration"
        style_text(
            header.text_frame,
            "Documento sintetico" if self.language == "pt" else "Synthetic document",
            18,
            bold=True,
            color=WHITE,
        )
        header.text_frame.margin_top = header.text_frame.margin_bottom = Pt(0)
        footer = slide.shapes.add_textbox(Pt(850), Pt(484), Pt(74), Pt(20))
        footer.name = "docgen-decoration"
        style_text(footer.text_frame, str(len(self.presentation.slides)), 14)
        footer.text_frame.margin_top = footer.text_frame.margin_bottom = Pt(0)
        self.y = BODY_Y
        return slide

    def flush_headings(self, following_height: float) -> None:
        if not self.headings:
            return
        required = following_height + sum(
            (len(wrap_lines(text, BODY_W - 12, 24, key)) + 1) * 24 * 1.35 + 8 + 22
            for text, key in self.headings
        )
        if required > BODY_BOTTOM - BODY_Y:
            raise InputError(
                f"Heading and following content cannot fit a PPTX slide: {self.headings[0][1]}."
            )
        if self.y + required > BODY_BOTTOM:
            self.slide = self.new_slide()
        headings, self.headings = self.headings, []
        for text, key in headings:
            self.text(text, key, 24, bold=True, level=self.heading_levels[key])

    def text(
        self,
        text: str,
        key: str,
        size: float = 16,
        *,
        bold: bool = False,
        bullet: str | None = None,
        number: int = 1,
        level: int = 1,
    ) -> None:
        lines = wrap_lines(text, BODY_W - 12 - (36 if bullet else 0), size, key)
        self.flush_headings((min(1, len(lines)) + 1) * size * 1.35 + 8)
        chunk = 0
        while lines:
            lead = size * 1.35
            available = math.floor((BODY_BOTTOM - self.y - 8) / lead) - 1
            if available < 1:
                self.slide = self.new_slide()
                continue
            take = min(len(lines), available)
            piece = "".join(lines[:take])
            height = (take + 1) * lead + 8
            shape = self.slide.shapes.add_textbox(Pt(BODY_X), Pt(self.y), Pt(BODY_W), Pt(height))
            shape.name = f"docgen-body:{key}:{chunk}"
            style_text(
                shape.text_frame,
                piece,
                size,
                bold=bold,
                bullet=bullet if chunk == 0 else None,
                number=number,
                level=level,
            )
            self.y += height + 22
            lines = lines[take:]
            chunk += 1

    def table(self, content: Content, block_index: int) -> None:
        block = content.blocks[block_index]
        source = block.table
        assert source is not None
        headers = tuple(
            column.name + (f" ({column.unit})" if column.unit else "") for column in source.columns
        )
        data = [
            tuple(value_text(cell.value, content.blueprint.locale) for cell in row)
            for row in source.rows
        ]
        widths = [BODY_W / len(headers)] * len(headers)
        minimums = column_minimums(source, content.blueprint.locale, size=14)
        if any(minimum > width for minimum, width in zip(minimums, widths, strict=True)):
            if sum(minimums) > BODY_W:
                raise InputError(f"PPTX table cannot fit its available width: {block.id}.")
            spare = (BODY_W - sum(minimums)) / len(minimums)
            widths = [minimum + spare for minimum in minimums]

        def height(row: tuple[str, ...]) -> float:
            return max(
                (len(wrap_lines(text, column_width - 12, 14, block.id)) + 1) * 18.9 + 8
                for text, column_width in zip(row, widths, strict=True)
            )

        header_height = height(headers)
        heights = [height(row) for row in data]
        if any(header_height + row > BODY_BOTTOM - BODY_Y for row in heights):
            raise InputError(f"Table row cannot fit at the minimum PPTX font size: {block.id}.")
        self.flush_headings(header_height + heights[0])
        start = 0
        while start < len(data):
            used = header_height
            end = start
            while end < len(data) and used + heights[end] <= BODY_BOTTOM - self.y:
                used += heights[end]
                end += 1
            if end == start:
                self.slide = self.new_slide()
                continue
            frame = self.slide.shapes.add_table(
                end - start + 1, len(headers), Pt(BODY_X), Pt(self.y), Pt(BODY_W), Pt(used)
            )
            frame.name = f"docgen-table:{source.id}:{start}"
            table = frame.table
            table.first_row = True
            for index, column_width in enumerate(widths):
                table.columns[index].width = Pt(column_width)
            for row_index, row in enumerate((headers, *data[start:end])):
                table.rows[row_index].height = Pt(
                    header_height if row_index == 0 else heights[start + row_index - 1]
                )
                for column_index, text in enumerate(row):
                    cell = table.cell(row_index, column_index)
                    cell.margin_left = cell.margin_right = Pt(6)
                    cell.margin_top = cell.margin_bottom = Pt(4)
                    paint(
                        cell.fill, CHARCOAL if row_index == 0 else WHITE if row_index % 2 else PAPER
                    )
                    style_text(
                        cell.text_frame,
                        text,
                        14,
                        bold=row_index == 0,
                        color=WHITE if row_index == 0 else INK,
                    )
                    cell.text_frame.margin_left = cell.text_frame.margin_right = Pt(0)
                    cell.text_frame.margin_top = cell.text_frame.margin_bottom = Pt(0)
            self.y += used + 22
            start = end


def render_pptx(
    content: Content, destination: Path, layout_profile: Profile = "baseline",
    layout_plan: LayoutPlan | None = None,
) -> None:
    flow = SlideFlow(content)
    flow.text(content.title, "title", 36, bold=True)
    flow.text(synthetic_notice(content.blueprint.language), "notice", 14)
    for index, block in enumerate(content.blocks):
        if block.kind == "heading" and block.text is not None:
            if (
                layout_plan is not None and layout_plan.recipe == "section-led"
                and block.level == 1 and not flow.headings
            ):
                flow.slide = flow.new_slide()
            flow.headings.append((block.text, block.id))
        elif block.items:
            counters = [0, 0]
            for item_index, item in enumerate(block.items):
                if item.level == 1:
                    counters[1] = 0
                counters[item.level - 1] += 1
                flow.text(
                    item.text,
                    f"{block.id}-{item_index}",
                    bullet=block.kind,
                    level=item.level,
                    number=counters[item.level - 1],
                )
        elif block.table:
            flow.table(content, index)
        elif block.text is not None:
            flow.text(block.text, block.id, bold=block.kind == "callout")
    if flow.headings:
        raise InputError(f"A final heading has no following PPTX content: {flow.headings[0][1]}.")
    with destination.open("xb") as stream:
        flow.presentation.save(stream)
