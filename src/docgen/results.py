from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue

from docgen.models import Record


class Result(Record):
    schema_version: Literal["1"] = "1"
    run_id: str
    operation: str
    status: str
    requested_count: int
    accepted_count: int
    verified_document_count: int = 0
    format_counts: dict[str, JsonValue] = Field(default_factory=dict)
    failures: tuple[dict[str, JsonValue], ...] = ()
    usage: dict[str, JsonValue] | None = None
    reports: dict[str, str] = Field(default_factory=dict)
    corpus_path: Path | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)
