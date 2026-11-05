"""Readback parsers independent of document writers."""

from collections.abc import Callable
from pathlib import Path

from docgen.errors import InputError
from docgen.extractors.docx import read_docx
from docgen.extractors.html import read_html
from docgen.extractors.markdown import read_markdown
from docgen.extractors.models import Readback
from docgen.extractors.pdf import read_pdf
from docgen.extractors.pptx import read_pptx
from docgen.extractors.xlsx import read_xlsx
from docgen.models import Profile

READERS: dict[str, Callable[[Path], Readback]] = {
    "md": read_markdown,
    "html": read_html,
    "docx": read_docx,
    "xlsx": read_xlsx,
    "pptx": read_pptx,
}


def read_document(path: Path, format: str, layout_profile: Profile = "baseline") -> Readback:
    if layout_profile not in {"baseline", "complex"}:
        raise InputError("Unsupported layout profile for readback.")
    if format == "pdf":
        return read_pdf(path, layout_profile)
    if format not in READERS:
        raise InputError(f"Unsupported document format for readback: {format}.")
    return READERS[format](path)
