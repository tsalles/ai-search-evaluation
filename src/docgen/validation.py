import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Literal

from docgen.allocation import AllocationPlan, Assignment
from docgen.errors import InputError, IntegrityError
from docgen.extractors import read_document
from docgen.models import Content, Record, content_hash
from docgen.persistence import safe_child
from docgen.text import synthetic_notice, value_text


def layout_normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


class ValidationIssue(Record):
    code: str
    message: str
    block_id: str | None = None


class BlockLocation(Record):
    block_id: str
    kind: Literal["title", "text", "table"]
    locations: tuple[str, ...]


class ArtifactValidation(Record):
    legacy_optional_fields = ("layout_features",)
    schema_version: Literal["1"] = "1"
    content_id: str
    filename: str
    format: str
    source_hash: str
    artifact_sha256: str | None
    valid: bool
    native_text: bool | None
    issues: tuple[ValidationIssue, ...]
    locations: tuple[BlockLocation, ...]
    layout_features: dict[str, int] | None = None


class CorpusValidation(Record):
    schema_version: Literal["1"] = "1"
    valid: bool
    requested_count: int
    document_count: int
    verified_count: int
    issues: tuple[ValidationIssue, ...]
    artifacts: tuple[ArtifactValidation, ...]


def validate_artifact(
    content: Content,
    assignment: Assignment,
    directory: Path,
    *,
    expected_sha256: str | None = None,
) -> ArtifactValidation:
    issues: list[ValidationIssue] = []
    locations: list[BlockLocation] = []
    checksum = None
    native = None
    layout_features = None

    def result() -> ArtifactValidation:
        return ArtifactValidation(
            content_id=content.blueprint.content_id,
            filename=assignment.filename,
            format=assignment.format,
            source_hash=content_hash(content),
            artifact_sha256=checksum,
            valid=not issues,
            native_text=native,
            issues=tuple(issues),
            locations=tuple(locations),
            layout_features=layout_features,
        )

    if assignment.content_id != content.blueprint.content_id or (
        assignment.source_hash != content_hash(content)
    ):
        issues.append(
            ValidationIssue(code="source_hash", message="Canonical source identity/hash differs.")
        )
        return result()
    try:
        path = safe_child(directory, assignment.filename)
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected_sha256 is not None and checksum != expected_sha256:
            issues.append(
                ValidationIssue(code="artifact_hash", message="Artifact checksum differs.")
            )
            return result()
        readback = read_document(path, assignment.format, assignment.layout_profile)
    except (OSError, UnicodeError, IntegrityError, InputError) as error:
        issues.append(ValidationIssue(code="readback_failed", message=str(error)))
        return result()
    native = readback.native_text
    layout_features = readback.layout_features
    if content.blueprint.structure_plan is not None:
        expected_headings = tuple(
            block.level for block in content.blocks if block.kind == "heading"
        )
        expected_lists = tuple(item.level for block in content.blocks for item in block.items or ())
        if (
            readback.heading_levels is not None and readback.heading_levels != expected_headings
        ) or (readback.list_levels is not None and readback.list_levels != expected_lists):
            issues.append(ValidationIssue(
                code="planned_structure",
                message="Native heading or list levels differ from the frozen structure plan.",
            ))
    if assignment.layout_plan is not None:
        recipe = assignment.layout_plan.recipe
        primary = [block.id for block in content.blocks if block.level == 1]
        expected_features = {}
        if recipe in {"single-column", "two-column"}:
            expected_features["columns"] = 2 if recipe == "two-column" else 1
        elif assignment.format == "html":
            expected_features["sections"] = len(primary) if recipe == "sectioned" else 0
        elif assignment.format == "xlsx":
            expected_features["narrative_sheets"] = 1 + (
                len(primary) if recipe == "sectioned" else 0
            )
        elif recipe == "semantic":
            expected_features["semantic_flow"] = 1
        if (
            any(layout_features.get(key) != value for key, value in expected_features.items())
            or recipe == "section-led" and not set(primary).issubset(readback.section_starts)
        ):
            issues.append(ValidationIssue(
                code="native_layout",
                message="Saved artifact does not realize its frozen native layout plan.",
            ))
    if not native:
        issues.append(
            ValidationIssue(code="native_text", message="Native business text is missing.")
        )
    issues.extend(
        ValidationIssue(code="structure", message=message) for message in readback.structural_issues
    )
    body = layout_normalized(" ".join(readback.paragraphs))
    units = [("__title__", "title", content.title)]
    for block in content.blocks:
        if block.text is not None:
            units.append((block.id, "text", block.text))
        units.extend((block.id, "text", item.text) for item in block.items or ())
    position = 0
    residual = []
    for block_id, kind, text in units:
        expected = layout_normalized(text)
        found = body.find(expected, position)
        if found < 0:
            issues.append(
                ValidationIssue(
                    code="missing_block",
                    block_id=block_id,
                    message="Canonical business text is missing, changed, or out of order.",
                )
            )
        else:
            residual.append(body[position:found])
            position = found + len(expected)
            locations.append(
                BlockLocation(
                    block_id=block_id,
                    kind="title" if kind == "title" else "text",
                    locations=(f"body-offset:{found}",),
                )
            )
    residual.append(body[position:])
    extra = " ".join(residual).replace(
        layout_normalized(synthetic_notice(content.blueprint.language)), "", 1
    )
    if assignment.format == "pdf":
        extra = re.sub(r"(?<!\w)\d+\.(?!\w)", "", extra).replace("\u2022", "")
    if extra.strip():
        issues.append(
            ValidationIssue(
                code="unexpected_text",
                message="Text exceeds the canonical units and declared decoration.",
            )
        )
    cursor = 0
    for block in content.blocks:
        if block.table is None:
            continue
        source = block.table
        headers = tuple(
            layout_normalized(column.name + (f" ({column.unit})" if column.unit else ""))
            for column in source.columns
        )
        expected_rows = tuple(
            tuple(
                layout_normalized(value_text(cell.value, content.blueprint.locale)) for cell in row
            )
            for row in source.rows
        )
        rows: list[tuple[str, ...]] = []
        cell_kinds: list[tuple[str, ...]] = []
        found_at = []
        while cursor < len(readback.tables) and len(rows) < len(expected_rows):
            fragment = readback.tables[cursor]
            cursor += 1
            if tuple(layout_normalized(text) for text in fragment.headers) != headers:
                issues.append(
                    ValidationIssue(
                        code="table_headers",
                        block_id=block.id,
                        message="Table column labels/units or table order differ.",
                    )
                )
                break
            rows.extend(tuple(layout_normalized(cell) for cell in row) for row in fragment.rows)
            if fragment.cell_kinds is not None:
                cell_kinds.extend(fragment.cell_kinds)
            found_at.append(fragment.location)
        if tuple(rows) != expected_rows:
            issues.append(
                ValidationIssue(
                    code="table_values",
                    block_id=block.id,
                    message="Ordered row/column associations or native cell values differ.",
                )
            )
        if assignment.format == "xlsx" and tuple(cell_kinds) != tuple(
            tuple(cell.kind for cell in row) for row in source.rows
        ):
            issues.append(
                ValidationIssue(
                    code="cell_types",
                    block_id=block.id,
                    message="Native spreadsheet cell types differ.",
                )
            )
        locations.append(
            BlockLocation(
                block_id=block.id,
                kind="table",
                locations=tuple(found_at),
            )
        )
    if cursor != len(readback.tables):
        issues.append(
            ValidationIssue(code="unexpected_table", message="Unplanned native tables exist.")
        )
    return result()


def validate_set(
    directory: Path,
    contents: tuple[Content, ...],
    allocation: AllocationPlan,
    *,
    expected_hashes: dict[str, str] | None = None,
) -> CorpusValidation:
    issues = []
    expected = {item.filename for item in allocation.items}
    try:
        entries = list(directory.iterdir())
    except OSError as error:
        entries = []
        issues.append(ValidationIssue(code="corpus_access", message=str(error)))
    if {entry.name for entry in entries} != expected or any(
        not entry.is_file() or entry.is_symlink() or entry.is_junction() for entry in entries
    ):
        issues.append(
            ValidationIssue(
                code="corpus_files",
                message="Corpus filenames differ or include sidecars/directories/links.",
            )
        )
    by_id = {content.blueprint.content_id: content for content in contents}
    if len(by_id) != len(contents) or set(by_id) != {item.content_id for item in allocation.items}:
        issues.append(
            ValidationIssue(code="corpus_sources", message="Canonical source set differs.")
        )
    reports = tuple(
        validate_artifact(
            by_id[item.content_id],
            item,
            directory,
            expected_sha256=expected_hashes.get(item.content_id) if expected_hashes else None,
        )
        for item in allocation.items
        if item.content_id in by_id
    )
    verified = sum(report.valid for report in reports)
    return CorpusValidation(
        valid=not issues and verified == len(allocation.items),
        requested_count=len(allocation.items),
        document_count=len(entries),
        verified_count=verified,
        issues=tuple(issues),
        artifacts=reports,
    )
