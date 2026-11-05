import hashlib
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from docgen.allocation import Assignment
from docgen.errors import InputError, IntegrityError
from docgen.models import Content, Format, Profile, Record, content_hash
from docgen.persistence import safe_child
from docgen.renderers.docx import render_docx
from docgen.renderers.html import render_html
from docgen.renderers.markdown import render_markdown
from docgen.renderers.pdf import render_pdf
from docgen.renderers.pptx import render_pptx
from docgen.renderers.xlsx import render_xlsx
from docgen.structure_models import LayoutPlan
from docgen.structures import validate_structure


class Artifact(Record):
    content_id: str
    format: Format
    filename: str
    source_hash: str
    sha256: str
    byte_count: int
    renderer_version: str = "1"


Writer = Callable[[Content, Path, Profile, LayoutPlan | None], None]
WRITERS: dict[Format, Writer] = {
    "md": render_markdown, "html": render_html, "docx": render_docx, "xlsx": render_xlsx,
    "pptx": render_pptx,
    "pdf": render_pdf,
}
SUPPORTED_BLOCKS = {"heading", "paragraph", "ordered_list", "unordered_list", "table", "callout"}


def render_document(content: Content, assignment: Assignment, directory: Path) -> Artifact:
    unsupported = [block.id for block in content.blocks if block.kind not in SUPPORTED_BLOCKS]
    if unsupported:
        raise InputError("Unsupported canonical blocks: " + ", ".join(unsupported))
    try:
        content = Content.model_validate_json(content.model_dump_json())
        assignment = Assignment.model_validate_json(assignment.model_dump_json())
        validate_structure(content)
    except ValidationError as exc:
        raise InputError(
            "Cannot render invalid canonical content or an invalid assignment."
        ) from exc
    if (
        assignment.content_id != content.blueprint.content_id
        or assignment.source_hash != content_hash(content)
    ):
        raise IntegrityError(
            "Renderer source identity or source checksum does not match allocation."
        )
    if assignment.format not in WRITERS:
        raise InputError(f"Renderer is not registered: {assignment.format}.")
    destination = safe_child(directory, assignment.filename)
    if destination.exists():
        raise IntegrityError("Assigned artifact already exists; verify it before any reuse.")
    try:
        WRITERS[assignment.format](
            content, destination, assignment.layout_profile, assignment.layout_plan,
        )
        raw = destination.read_bytes()
    except OSError as exc:
        raise IntegrityError(f"Cannot write the assigned {assignment.format} artifact.") from exc
    return Artifact(
        content_id=assignment.content_id, format=assignment.format,
        filename=assignment.filename, source_hash=assignment.source_hash,
        sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw),
    )
