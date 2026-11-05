import html
import re
from pathlib import Path

from docgen.models import Content, Profile
from docgen.structure_models import LayoutPlan
from docgen.text import synthetic_notice, value_text


def escape(text: str) -> str:
    text = html.escape(text, quote=False)
    return re.sub(r"([\\`*_[\]{}#!|().+~\-])", r"\\\1", text).replace("\n", "<br>")


def render_markdown(
    content: Content, destination: Path, layout_profile: Profile = "baseline",
    layout_plan: LayoutPlan | None = None,
) -> None:
    parts = [
        f"# {escape(content.title)}", "",
        synthetic_notice(content.blueprint.language), "",
    ]
    for block in content.blocks:
        if block.kind == "heading" and block.level is not None and block.text is not None:
            parts.append(f"{'#' * (block.level + 1)} {escape(block.text)}")
        elif block.items:
            counters = [0, 0]
            for item in block.items:
                if item.level == 1:
                    counters[1] = 0
                counters[item.level - 1] += 1
                prefix = (
                    f"{counters[item.level - 1]}." if block.kind == "ordered_list" else "-"
                )
                parts.append(f"{'    ' * (item.level - 1)}{prefix} {escape(item.text)}")
        elif block.table:
            table = block.table
            headers = [
                escape(column.name + (f" ({column.unit})" if column.unit else ""))
                for column in table.columns
            ]
            parts.append("| " + " | ".join(headers) + " |")
            parts.append("| " + " | ".join("---" for _ in headers) + " |")
            for row in table.rows:
                parts.append("| " + " | ".join(
                    escape(value_text(cell.value, content.blueprint.locale)) for cell in row
                ) + " |")
        elif block.text is not None:
            prefix = "> " if block.kind == "callout" else ""
            parts.append(prefix + escape(block.text))
        parts.append("")
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(parts))
