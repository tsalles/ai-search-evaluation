from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token

from docgen.errors import IntegrityError
from docgen.extractors.models import Readback, TableGrid


def inline_text(token: Token) -> str:
    parts = []
    for child in token.children or ():
        if child.type in {"text", "code_inline"}:
            parts.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
        elif child.type == "html_inline":
            if child.content.lower() not in {"<br>", "<br/>", "<br />"}:
                raise IntegrityError("Unsafe inline HTML in Markdown artifact.")
            parts.append("\n")
    return "".join(parts)


def read_markdown(path: Path) -> Readback:
    tokens = MarkdownIt("commonmark").enable("table").parse(path.read_text(encoding="utf-8"))
    paragraphs = []
    tables: list[TableGrid] = []
    in_table = False
    in_header = False
    headers: tuple[str, ...] = ()
    rows: list[tuple[str, ...]] = []
    row: list[str] = []
    heading_levels = []
    list_levels = []
    list_depth = 0
    for token in tokens:
        if token.type == "heading_open" and token.tag != "h1":
            heading_levels.append(int(token.tag[1:]) - 1)
        elif token.type in {"ordered_list_open", "bullet_list_open"}:
            list_depth += 1
        elif token.type in {"ordered_list_close", "bullet_list_close"}:
            list_depth -= 1
        elif token.type == "list_item_open":
            list_levels.append(list_depth)
        if token.type == "html_block":
            raise IntegrityError("Raw HTML blocks are not permitted in Markdown artifacts.")
        if token.type == "table_open":
            in_table = True
            headers, rows = (), []
        elif token.type == "thead_open":
            in_header = True
        elif token.type == "thead_close":
            in_header = False
        elif token.type == "tr_open":
            row = []
        elif token.type == "inline":
            text = inline_text(token)
            if in_table:
                row.append(text)
            else:
                paragraphs.append(text)
        elif token.type == "tr_close":
            if in_header:
                headers = tuple(row)
            else:
                rows.append(tuple(row))
        elif token.type == "table_close":
            in_table = False
            tables.append(TableGrid(
                headers=headers, rows=tuple(rows), location=f"table-{len(tables)}",
            ))
    return Readback(
        paragraphs=tuple(paragraphs), tables=tuple(tables),
        heading_levels=tuple(heading_levels), list_levels=tuple(list_levels),
        layout_features={"semantic_flow": 1},
    )
