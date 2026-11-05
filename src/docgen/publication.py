import hashlib
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from docgen.allocation import AllocationPlan
from docgen.errors import IntegrityError
from docgen.models import Record, serialize
from docgen.persistence import atomic_write, safe_child
from docgen.renderers.base import Artifact
from docgen.store import RunStore


class ReadyManifest(Record):
    schema_version: Literal["1"] = "1"
    run_id: str
    allocation_hash: str
    artifacts: tuple[Artifact, ...]


def load_ready(store: RunStore, allocation: AllocationPlan) -> ReadyManifest | None:
    path = safe_child(store.directory, "ready-manifest.json")
    table = store.connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication'"
    ).fetchone()
    row = (
        store.connection.execute("SELECT payload,hash FROM publication WHERE id=1").fetchone()
        if table is not None
        else None
    )
    if row is None:
        if path.exists():
            raise IntegrityError("Uncheckpointed ready manifest cannot authorize publication.")
        return None
    raw = row["payload"]
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != row["hash"]:
        raise IntegrityError("Publication checkpoint checksum differs.")
    try:
        ready = ReadyManifest.model_validate_json(raw)
    except ValidationError as exc:
        raise IntegrityError("Publication checkpoint schema is invalid.") from exc
    expected = {item.content_id: item for item in allocation.items}
    states = store.rendered_states()
    if (
        ready.run_id != store.plan.run_id
        or ready.allocation_hash != hashlib.sha256(serialize(allocation)).hexdigest()
        or {item.content_id for item in ready.artifacts} != set(expected)
        or len(ready.artifacts) != len(expected)
        or any(
            item.filename != expected[item.content_id].filename
            or item.source_hash != expected[item.content_id].source_hash
            or item.content_id not in states
            or states[item.content_id].status != "verified"
            or states[item.content_id].hash != item.sha256
            for item in ready.artifacts
        )
    ):
        raise IntegrityError("Ready manifest differs from verified immutable assignments.")
    if path.exists():
        if path.read_bytes() != raw:
            raise IntegrityError("Ready manifest file checksum differs.")
    else:
        atomic_write(path, raw)
    return ready


def publish(
    store: RunStore,
    allocation: AllocationPlan,
    artifacts: tuple[Artifact, ...],
    staging: Path,
) -> Path:
    ready = ReadyManifest(
        run_id=store.plan.run_id,
        allocation_hash=hashlib.sha256(serialize(allocation)).hexdigest(),
        artifacts=artifacts,
    )
    existing = load_ready(store, allocation)
    if existing is not None:
        if existing != ready:
            raise IntegrityError("Publication plan and verified artifact hashes are immutable.")
    else:
        raw = serialize(ready)
        try:
            with store.connection:
                store.connection.execute(
                    "CREATE TABLE IF NOT EXISTS publication "
                    "(id INTEGER PRIMARY KEY CHECK(id=1),payload BLOB NOT NULL,hash TEXT NOT NULL)"
                )
                store.connection.execute(
                    "INSERT INTO publication VALUES (1,?,?)",
                    (raw, hashlib.sha256(raw).hexdigest()),
                )
        except sqlite3.Error as exc:
            raise IntegrityError(
                "Cannot persist the complete-corpus publication checkpoint."
            ) from exc
        atomic_write(safe_child(store.directory, "ready-manifest.json"), raw)
    destination = safe_child(store.directory, "corpus")
    if destination.exists():
        raise IntegrityError("Publication destination already exists; nothing was overwritten.")
    try:
        staging.rename(destination)
    except OSError as exc:
        raise IntegrityError(
            "Atomic corpus publication failed; verified staging files were retained."
        ) from exc
    return destination
