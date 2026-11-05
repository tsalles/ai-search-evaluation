from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    FrameBreak,
    LongTable,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    TableStyle,
)
from reportlab.platypus.doctemplate import LayoutError

from docgen.errors import InputError
from docgen.models import Content, Profile
from docgen.renderers.layout import (
    FONT_NAME,
    column_minimums,
    layout_text,
    portable_font,
    wrap_lines,
)
from docgen.structure_models import LayoutPlan
from docgen.text import synthetic_notice, value_text

MARGIN = 54.0
GAP = 18.0


def render_pdf(
    content: Content, destination: Path, layout_profile: Profile = "baseline",
    layout_plan: LayoutPlan | None = None,
) -> None:
    if layout_plan is not None:
        layout_profile = layout_plan.profile
    portable_font()
    widest = max(
        (
            sum(column_minimums(block.table, content.blueprint.locale))
            for block in content.blocks
            if block.table
        ),
        default=0,
    )
    page_size = landscape(A4) if widest > A4[0] - 2 * MARGIN else A4
    width, height = page_size
    usable = width - 2 * MARGIN
    frame_width = (usable - GAP) / 2 if layout_profile == "complex" else usable
    body = ParagraphStyle(
        "Body",
        fontName=FONT_NAME,
        fontSize=10,
        leading=14,
        spaceAfter=8,
        splitLongWords=False,
    )
    cell_style = ParagraphStyle(
        "Cell",
        parent=body,
        leading=13,
        spaceAfter=0,
        spaceBefore=0,
    )
    header_style = ParagraphStyle(
        "Header",
        parent=cell_style,
        fontName=FONT_NAME + "Bold",
        textColor=colors.white,
    )

    def paragraph(text: str, style: ParagraphStyle, label: str, available: float) -> Paragraph:
        wrap_lines(text, available, style.fontSize, label)
        return Paragraph(escape(layout_text(text)).replace("\n", "<br/>"), style)

    story: list[Flowable] = [
        paragraph(
            content.title,
            ParagraphStyle(
                "Title",
                parent=body,
                fontName=FONT_NAME + "Bold",
                fontSize=20,
                leading=26,
            ),
            "title",
            frame_width,
        ),
        paragraph(synthetic_notice(content.blueprint.language), body, "notice", frame_width),
    ]
    prose_count = sum(
        len(block.items or ()) or int(block.kind in {"paragraph", "callout"})
        for block in content.blocks
    )
    prose_seen = 0
    column_break = False

    def next_prose() -> None:
        nonlocal prose_seen, column_break
        if (
            layout_plan is not None and layout_plan.recipe == "two-column"
            and not column_break and prose_seen >= max(1, prose_count // 2)
        ):
            position = len(story)
            while (
                position > 0 and isinstance(story[position - 1], Paragraph)
                and getattr(story[position - 1], "keepWithNext", False)
            ):
                position -= 1
            story.insert(position, FrameBreak())
            column_break = True
        prose_seen += 1

    for block in content.blocks:
        if block.kind == "heading" and block.text is not None:
            style = ParagraphStyle(
                "Heading",
                parent=body,
                fontName=FONT_NAME + "Bold",
                fontSize=14 if block.level == 1 else 12,
                leading=18,
                spaceBefore=10,
                keepWithNext=True,
            )
            story.append(paragraph(block.text, style, block.id, frame_width))
        elif block.items:
            counters = [0, 0]
            for item in block.items:
                next_prose()
                if item.level == 1:
                    counters[1] = 0
                counters[item.level - 1] += 1
                style = ParagraphStyle(
                    "List",
                    parent=body,
                    leftIndent=14 * item.level,
                    bulletIndent=14 * (item.level - 1),
                    bulletFontName=FONT_NAME,
                    bulletFontSize=10,
                )
                text = paragraph(item.text, style, block.id, frame_width - 14 * item.level)
                text.bulletText = (
                    str(counters[item.level - 1]) + "."
                    if block.kind == "ordered_list"
                    else "\u2022"
                )
                story.append(text)
        elif block.table:
            source = block.table
            minimums = column_minimums(source, content.blueprint.locale)
            wide = sum(minimums) > frame_width
            available = usable if wide else frame_width
            if sum(minimums) > available:
                raise InputError(f"PDF table cannot fit its available width: {block.id}.")
            widths = [minimum + (available - sum(minimums)) / len(minimums) for minimum in minimums]
            rows = [
                [
                    paragraph(
                        column.name + (f" ({column.unit})" if column.unit else ""),
                        header_style,
                        block.id,
                        column_width - 12,
                    )
                    for column, column_width in zip(source.columns, widths, strict=True)
                ]
            ]
            for row in source.rows:
                rows.append(
                    [
                        paragraph(
                            value_text(cell.value, content.blueprint.locale),
                            cell_style,
                            block.id,
                            column_width - 12,
                        )
                        for cell, column_width in zip(row, widths, strict=True)
                    ]
                )
            table = LongTable(rows, colWidths=widths, repeatRows=1, splitByRow=1, splitInRow=0)
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#777777")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#36454F")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            if wide and layout_profile == "complex":
                story.extend([NextPageTemplate("wide"), PageBreak()])
            story.extend([table, Spacer(1, 10)])
            if wide and layout_profile == "complex":
                story.extend([NextPageTemplate("normal"), PageBreak()])
        elif block.text is not None:
            next_prose()
            style = (
                ParagraphStyle(
                    "Callout",
                    parent=body,
                    leftIndent=12,
                    rightIndent=12,
                    fontName=FONT_NAME + "Bold",
                )
                if block.kind == "callout"
                else body
            )
            story.append(
                paragraph(
                    block.text, style, block.id, frame_width - style.leftIndent - style.rightIndent
                )
            )
    with destination.open("xb") as stream:
        document = BaseDocTemplate(
            stream,
            pagesize=page_size,
            title=content.title,
            author="Synthetic Document Generator",
            subject="Fictional retrieval corpus",
            lang=content.blueprint.locale,
        )
        frames = [
            Frame(
                MARGIN,
                MARGIN,
                frame_width,
                height - 2 * MARGIN,
                id="left",
                leftPadding=0,
                rightPadding=0,
                topPadding=0,
                bottomPadding=0,
            )
        ]
        if layout_profile == "complex":
            frames.append(
                Frame(
                    MARGIN + frame_width + GAP,
                    MARGIN,
                    frame_width,
                    height - 2 * MARGIN,
                    id="right",
                    leftPadding=0,
                    rightPadding=0,
                    topPadding=0,
                    bottomPadding=0,
                )
            )
        document.addPageTemplates(
            [
                PageTemplate(id="normal", frames=frames, pagesize=page_size),
                PageTemplate(
                    id="wide",
                    frames=[
                        Frame(
                            MARGIN,
                            MARGIN,
                            usable,
                            height - 2 * MARGIN,
                            id="full",
                            leftPadding=0,
                            rightPadding=0,
                            topPadding=0,
                            bottomPadding=0,
                        )
                    ],
                    pagesize=page_size,
                ),
            ]
        )
        try:
            document.build(story)
        except LayoutError as exc:
            raise InputError(
                "PDF block cannot fit native page flow; no content was truncated."
            ) from exc
