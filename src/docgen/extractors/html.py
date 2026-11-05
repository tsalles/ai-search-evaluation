import re
from html.parser import HTMLParser
from pathlib import Path

from docgen.errors import IntegrityError
from docgen.extractors.models import Readback, TableGrid


class DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self.tables: list[TableGrid] = []
        self.tags: list[str] = []
        self.frames: list[tuple[str, list[str]]] = []
        self.cell: list[str] | None = None
        self.row: list[str] = []
        self.rows: list[tuple[str, ...]] = []
        self.headers: tuple[str, ...] = ()
        self.in_table = False
        self.in_header = False
        self.in_head = False
        self.heading_levels: list[int] = []
        self.list_levels: list[int] = []
        self.section_count = 0

    def flush(self) -> None:
        if self.frames and self.frames[-1][1]:
            self.paragraphs.append("".join(self.frames[-1][1]))
            self.frames[-1][1].clear()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        allowed = {
            "html",
            "head",
            "meta",
            "title",
            "style",
            "body",
            "main",
            "section",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "p",
            "ol",
            "ul",
            "li",
            "aside",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
            "br",
        }
        if tag not in allowed or any(
            name.startswith("on")
            or name
            in {
                "src",
                "href",
                "srcdoc",
                "hidden",
                "style",
                "colspan",
                "rowspan",
                "http-equiv",
            }
            for name, _ in attrs
        ):
            raise IntegrityError("Active, hidden, external, or unsupported HTML content.")
        if tag == "br":
            if self.cell is not None:
                self.cell.append("\n")
            elif self.frames:
                self.frames[-1][1].append("\n")
            return
        if tag == "meta":
            return
        self.tags.append(tag)
        if tag in {"h2", "h3", "h4"}:
            self.heading_levels.append(int(tag[1:]) - 1)
        elif tag == "li":
            self.list_levels.append(sum(name in {"ol", "ul"} for name in self.tags))
        elif tag == "section":
            self.section_count += 1
        if tag == "head":
            self.in_head = True
        elif tag == "table":
            if self.in_table:
                raise IntegrityError("Nested HTML tables are not supported.")
            self.in_table = True
            self.headers, self.rows = (), []
        elif tag == "thead":
            self.in_header = True
        elif tag == "tr":
            self.row = []
        elif tag in {"th", "td"}:
            self.cell = []
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li"}:
            self.flush()
            self.frames.append((tag, []))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"br", "meta"}:
            return
        if not self.tags or self.tags.pop() != tag:
            raise IntegrityError("HTML artifact has mismatched tags.")
        if tag == "head":
            self.in_head = False
        elif tag in {"th", "td"}:
            self.row.append("".join(self.cell or ()))
            self.cell = None
        elif tag == "tr":
            if self.in_header:
                self.headers = tuple(self.row)
            else:
                self.rows.append(tuple(self.row))
        elif tag == "thead":
            self.in_header = False
        elif tag == "table":
            self.tables.append(
                TableGrid(
                    headers=self.headers,
                    rows=tuple(self.rows),
                    location=f"table-{len(self.tables)}",
                )
            )
            self.in_table = False
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li"}:
            self.flush()
            self.frames.pop()

    def handle_data(self, data: str) -> None:
        if self.in_head:
            if (
                self.tags
                and self.tags[-1] == "style"
                and re.search(
                    r"url\s*\(|@import|expression\s*\(|display\s*:\s*none|visibility\s*:\s*hidden",
                    data,
                    re.I,
                )
            ):
                raise IntegrityError("Active, hidden, or external CSS in HTML artifact.")
            return
        if self.cell is not None:
            self.cell.append(data)
        elif self.frames:
            self.frames[-1][1].append(data)
        elif data.strip():
            raise IntegrityError("Unstructured visible text in HTML artifact.")


def read_html(path: Path) -> Readback:
    parser = DocumentParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    if parser.tags:
        raise IntegrityError("HTML artifact is truncated.")
    return Readback(
        paragraphs=tuple(parser.paragraphs), tables=tuple(parser.tables),
        heading_levels=tuple(parser.heading_levels), list_levels=tuple(parser.list_levels),
        layout_features={"sections": parser.section_count},
    )
