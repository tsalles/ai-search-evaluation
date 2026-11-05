from pathlib import Path

import pytest

from docgen.errors import IntegrityError
from docgen.extractors.html import read_html
from docgen.models import Content
from docgen.renderers.base import render_document
from tests.rendering.test_markdown import assignment
from tests.test_content_contract import example_content


def test_native_html_is_self_contained_escaped_and_preserves_reading_order(tmp_path: Path) -> None:
    data = example_content()
    data["blocks"][1]["text"] = "<script>window.alert('x')</script>\nA & B | C"
    data["blocks"][-1]["table"]["rows"][0][0]["value"] = "<b>Aurora</b>\nConta"
    content = Content.model_validate(data)
    artifact = render_document(content, assignment(content, "html"), tmp_path)
    path = tmp_path / artifact.filename
    raw = path.read_text(encoding="utf-8")
    assert '<html lang="pt-BR">' in raw
    assert "<script>" not in raw
    assert "src=" not in raw
    readback = read_html(path)
    assert data["blocks"][1]["text"] in readback.paragraphs
    assert readback.paragraphs.index("Confira a documenta\u00e7\u00e3o.") < (
        readback.paragraphs.index("Solicite avalia\u00e7\u00e3o.")
    )
    assert readback.tables[0].rows[0][0] == "<b>Aurora</b>\nConta"
    assert readback.tables[0].rows[0][1] == "1,25"
    assert readback.tables[0].rows[0][3] == "Sim"


@pytest.mark.parametrize(
    "markup",
    [
        "<script>alert(1)</script>",
        '<img src="https://example.invalid/image">',
        '<p onclick="alert(1)">text</p>',
        "<p>unclosed",
    ],
)
def test_html_readback_rejects_active_remote_or_truncated_content(
    tmp_path: Path,
    markup: str,
) -> None:
    path = tmp_path / "bad.html"
    path.write_text(markup, encoding="utf-8")
    with pytest.raises(IntegrityError):
        read_html(path)
