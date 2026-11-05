from pathlib import Path

import pytest

from docgen.allocation import Assignment
from docgen.errors import InputError, IntegrityError
from docgen.extractors.markdown import read_markdown
from docgen.models import Content, content_hash
from docgen.renderers.base import render_document
from tests.test_content_contract import example_content


def assignment(content: Content, fmt: str = "md", profile: str = "baseline") -> Assignment:
    return Assignment(
        content_id=content.blueprint.content_id, source_hash=content_hash(content),
        format=fmt, filename=f"{content.blueprint.content_id}.{fmt}", layout_profile=profile,
    )


def test_markdown_preserves_literal_markup_nested_lists_and_native_tables(tmp_path: Path) -> None:
    data = example_content()
    tricky = "1. <script>alert('x')</script>\npipe | slash \\ and `code` * literal [link](uri)"
    data["blocks"][1]["text"] = tricky
    data["blocks"][-1]["table"]["rows"][0][0]["value"] = "A | B\n<br> literal"
    content = Content.model_validate(data)
    artifact = render_document(content, assignment(content), tmp_path)
    readback = read_markdown(tmp_path / artifact.filename)
    assert artifact.format == "md"
    assert artifact.byte_count > 0
    assert artifact.source_hash == content_hash(content)
    assert len(artifact.sha256) == 64
    assert tricky in readback.paragraphs
    assert "Solicite avalia\u00e7\u00e3o." in readback.paragraphs
    assert readback.tables[0].rows[0][0] == "A | B\n<br> literal"
    assert readback.tables[0].rows[0][1] == "1,25"
    assert readback.tables[0].rows[0][2] == "23/10/2026"
    assert readback.tables[0].rows[0][3] == "Sim"
    assert "<script>" not in (tmp_path / artifact.filename).read_text(encoding="utf-8")


def test_renderer_rejects_bad_identity_hash_and_unsupported_blocks(tmp_path: Path) -> None:
    content = Content.model_validate(example_content())
    selected = assignment(content)
    with pytest.raises(IntegrityError, match="source"):
        render_document(content, selected.model_copy(update={"source_hash": "0" * 64}), tmp_path)
    block = content.blocks[0].model_copy(update={"kind": "unsupported", "id": "bad-block"})
    invalid = content.model_copy(update={"blocks": (block,)})
    with pytest.raises(InputError, match="bad-block"):
        render_document(invalid, selected, tmp_path)
    render_document(content, selected, tmp_path)
    original = (tmp_path / selected.filename).read_bytes()
    with pytest.raises(IntegrityError):
        render_document(content, selected, tmp_path)
    assert (tmp_path / selected.filename).read_bytes() == original


def test_markdown_readback_rejects_raw_active_html(tmp_path: Path) -> None:
    artifact = tmp_path / "unsafe.md"
    artifact.write_text("<script>alert('unsafe')</script>", encoding="utf-8")
    with pytest.raises(IntegrityError, match="HTML"):
        read_markdown(artifact)
