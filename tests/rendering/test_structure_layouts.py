from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from docgen.allocation import allocate
from docgen.config import Config, RenderConfig
from docgen.extractors import read_document
from docgen.models import content_hash
from docgen.planning import create_plan
from docgen.renderers.base import render_document
from docgen.validation import validate_artifact
from tests.fixtures.factories import structured_content
from tests.test_planning import configuration

LAYOUTS = [
    ("pdf", "single-column"), ("pdf", "two-column"),
    ("docx", "single-column"), ("docx", "two-column"),
    ("pptx", "flow"), ("pptx", "section-led"),
    ("xlsx", "compact"), ("xlsx", "sectioned"),
    ("html", "linear"), ("html", "sectioned"), ("md", "semantic"),
]


def planned_content(
    genre: str = "procedure", complexity: str = "complex", band: str = "medium",
):
    data = configuration(1)
    data["generation"].update(
        genre_weights={genre: 1}, length_weights={band: 1},
        structure={"complexity_weights": {complexity: 1}},
    )
    plan = create_plan(Config.model_validate(data), run_id="run-native")
    return structured_content(plan.blueprints[0])


@pytest.mark.parametrize(("format", "layout"), LAYOUTS)
@pytest.mark.parametrize("complexity", ["simple", "moderate", "complex"])
def test_native_layouts_preserve_and_realize_frozen_structures(
    tmp_path: Path, format: str, layout: str, complexity: str,
) -> None:
    content = planned_content(complexity=complexity)
    original = content_hash(content)
    config = RenderConfig.model_validate({
        "weights": {format: 1}, "layout_weights": {format: {layout: 1}},
    })
    allocation = allocate((content,), config, seed=1729)
    assignment = allocation.items[0]
    assert assignment.layout_plan.recipe == layout
    artifact = render_document(content, assignment, tmp_path)
    check = validate_artifact(content, assignment, tmp_path)
    assert check.valid, check.issues
    assert check.layout_features
    assert content_hash(content) == original
    readback = read_document(tmp_path / artifact.filename, format, assignment.layout_profile)
    if format != "pdf":
        assert readback.heading_levels == tuple(
            block.level for block in content.blocks if block.kind == "heading"
        )
        assert readback.list_levels == tuple(
            item.level for block in content.blocks for item in block.items or ()
        )


@pytest.mark.parametrize("genre", ["explainer", "faq", "comparison"])
@pytest.mark.parametrize(("format", "layout"), LAYOUTS)
def test_other_genres_preserve_frozen_structure_in_every_native_layout(
    tmp_path: Path, genre: str, format: str, layout: str,
) -> None:
    content = planned_content(genre=genre)
    config = RenderConfig.model_validate({
        "weights": {format: 1}, "layout_weights": {format: {layout: 1}},
    })
    assignment = allocate((content,), config).items[0]
    render_document(content, assignment, tmp_path)
    report = validate_artifact(content, assignment, tmp_path)
    assert report.valid, report.issues


def test_layout_recipe_quotas_are_exact_and_independently_reproducible() -> None:
    data = configuration(10)
    data["generation"]["structure"] = {}
    plan = create_plan(Config.model_validate(data), run_id="run-layout-quota")
    contents = tuple(structured_content(blueprint) for blueprint in plan.blueprints)
    config = RenderConfig.model_validate({
        "weights": {"docx": 1},
        "layout_weights": {"docx": {"single-column": 0.3, "two-column": 0.7}},
    })
    first = allocate(contents, config, seed=1729)
    assert first == allocate(tuple(reversed(contents)), config, seed=1729)
    assert Counter(item.layout_plan.recipe for item in first.items) == {
        "single-column": 3, "two-column": 7,
    }


def test_native_readback_rejects_a_layout_label_without_actual_columns(tmp_path: Path) -> None:
    content = planned_content()
    config = RenderConfig.model_validate({
        "weights": {"docx": 1}, "layout_weights": {"docx": {"two-column": 1}},
    })
    assignment = allocate((content,), config).items[0]
    artifact = render_document(content, assignment, tmp_path)
    path = tmp_path / artifact.filename
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries["word/document.xml"] = entries["word/document.xml"].replace(
        b'w:num="2"', b'w:num="1"',
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    report = validate_artifact(content, assignment, tmp_path)
    assert not report.valid
    assert "native_layout" in {issue.code for issue in report.issues}


@pytest.mark.parametrize(("element", "attribute", "value"), [
    ("cols", "num", "invalid"),
    ("cols", "num", "0"),
    ("ilvl", "val", "invalid"),
    ("ilvl", "val", "-1"),
])
def test_malformed_native_structure_returns_a_validation_failure(
    tmp_path: Path, element: str, attribute: str, value: str,
) -> None:
    content = planned_content()
    config = RenderConfig.model_validate({
        "weights": {"docx": 1}, "layout_weights": {"docx": {"two-column": 1}},
    })
    assignment = allocate((content,), config).items[0]
    artifact = render_document(content, assignment, tmp_path)
    path = tmp_path / artifact.filename
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ET.fromstring(entries["word/document.xml"])
    node = next(root.iter(namespace + element))
    node.set(namespace + attribute, value)
    entries["word/document.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    report = validate_artifact(content, assignment, tmp_path)
    assert not report.valid
    assert "readback_failed" in {issue.code for issue in report.issues}


@pytest.mark.parametrize("band", ["short", "long"])
@pytest.mark.parametrize("genre", ["explainer", "procedure", "faq", "comparison"])
@pytest.mark.parametrize("complexity", ["simple", "moderate", "complex"])
@pytest.mark.parametrize(("format", "layout"), [
    ("pdf", "two-column"), ("docx", "two-column"), ("pptx", "section-led"),
    ("xlsx", "sectioned"), ("html", "sectioned"), ("md", "semantic"),
])
def test_short_and_long_complex_content_preserves_every_native_structure(
    tmp_path: Path, band: str, genre: str, complexity: str, format: str, layout: str,
) -> None:
    content = planned_content(genre=genre, complexity=complexity, band=band)
    config = RenderConfig.model_validate({
        "weights": {format: 1}, "layout_weights": {format: {layout: 1}},
    })
    assignment = allocate((content,), config).items[0]
    render_document(content, assignment, tmp_path)
    report = validate_artifact(content, assignment, tmp_path)
    assert report.valid, report.issues
