import html
from pathlib import Path

from docgen.models import Content, ListItem, Profile
from docgen.structure_models import LayoutPlan
from docgen.text import synthetic_notice, value_text


def list_markup(items: tuple[ListItem, ...], ordered: bool) -> str:
    tag = "ol" if ordered else "ul"
    parts = [f"<{tag}>"]
    index = 0
    while index < len(items):
        parts.append("<li>" + html.escape(items[index].text))
        index += 1
        if index < len(items) and items[index].level == 2:
            parts.append(f"<{tag}>")
            while index < len(items) and items[index].level == 2:
                parts.append("<li>" + html.escape(items[index].text) + "</li>")
                index += 1
            parts.append(f"</{tag}>")
        parts.append("</li>")
    parts.append(f"</{tag}>")
    return "".join(parts)


def render_html(
    content: Content, destination: Path, layout_profile: Profile = "baseline",
    layout_plan: LayoutPlan | None = None,
) -> None:
    parts = [
        "<!doctype html>",
        f'<html lang="{content.blueprint.locale}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>" + html.escape(content.title) + "</title>",
        "<style>body{font:11pt sans-serif;max-width:1000px;margin:2em auto;padding:1em;}"
        "p,li,th,td{white-space:pre-wrap;overflow-wrap:anywhere;}"
        "table{border-collapse:collapse;width:100%;table-layout:fixed;margin:1em 0;}"
        "td,th{border:1px solid #777;padding:.5em;text-align:left;vertical-align:top;}"
        "aside{border-left:3px solid #666;padding-left:1em;}</style>",
        "</head><body><main>",
        "<h1>" + html.escape(content.title) + "</h1>",
        "<p>" + html.escape(synthetic_notice(content.blueprint.language)) + "</p>",
    ]
    section_open = False
    for block in content.blocks:
        if layout_plan is not None and layout_plan.recipe == "sectioned" and block.level == 1:
            if section_open:
                parts.append("</section>")
            parts.append("<section>")
            section_open = True
        if block.kind == "heading" and block.level is not None:
            tag = f"h{block.level + 1}"
            parts.append(f"<{tag}>" + html.escape(block.text or "") + f"</{tag}>")
        elif block.items:
            parts.append(list_markup(block.items, block.kind == "ordered_list"))
        elif block.table:
            parts.append("<table><thead><tr>")
            for column in block.table.columns:
                label = column.name + (f" ({column.unit})" if column.unit else "")
                parts.append("<th>" + html.escape(label) + "</th>")
            parts.append("</tr></thead><tbody>")
            for row in block.table.rows:
                parts.append("<tr>")
                for cell in row:
                    parts.append(
                        "<td>"
                        + html.escape(value_text(cell.value, content.blueprint.locale))
                        + "</td>"
                    )
                parts.append("</tr>")
            parts.append("</tbody></table>")
        elif block.text is not None:
            paragraph = "<p>" + html.escape(block.text) + "</p>"
            parts.append(
                "<aside>" + paragraph + "</aside>" if block.kind == "callout" else paragraph
            )
    if section_open:
        parts.append("</section>")
    parts.append("</main></body></html>")
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(parts))
