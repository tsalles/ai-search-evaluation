from pydantic import Field

from docgen.models import Record


class TableGrid(Record):
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    location: str = ""
    cell_kinds: tuple[tuple[str, ...], ...] | None = None


class Readback(Record):
    paragraphs: tuple[str, ...]
    tables: tuple[TableGrid, ...]
    native_text: bool = True
    structural_issues: tuple[str, ...] = ()
    heading_levels: tuple[int, ...] | None = None
    list_levels: tuple[int, ...] | None = None
    layout_features: dict[str, int] = Field(default_factory=dict)
    section_starts: tuple[str, ...] = ()
