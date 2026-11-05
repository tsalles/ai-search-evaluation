import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Literal, Self
from uuid import uuid4

from filelock import FileLock, Timeout
from pydantic import ValidationError

from docgen.errors import IntegrityError
from docgen.models import Content, Identifier, Record, Usage, content_hash, serialize
from docgen.persistence import atomic_write, safe_child, temporary_path
from docgen.planning import RunPlan, create_plan, semantic_fingerprint
from docgen.prompts import READABLE_PROMPT_VERSIONS

if TYPE_CHECKING:
    from docgen.allocation import AllocationPlan
    from docgen.renderers.base import Artifact
    from docgen.validation import ArtifactValidation

RunStatus = Literal[
    "planned", "generating", "content_ready", "allocated", "rendering",
    "validating", "complete", "incomplete", "cancelled",
]


class ItemState(Record):
    id: Identifier
    ordinal: int
    status: Literal["pending", "writing", "accepted"]
    hash: str | None


class Attempt(Record):
    attempt_id: Identifier
    content_id: Identifier
    status: Literal["in_flight", "unknown", "succeeded", "failed"]
    usage: Usage | None = None
    error_code: str | None = None
    created_at: datetime


class RenderedState(Record):
    id: Identifier
    status: Literal["rendering", "verified"]
    hash: str | None
    byte_count: int | None
    validation: bytes | None


class RunStore:
    def __init__(
        self, directory: Path, plan: RunPlan, connection: sqlite3.Connection, lock: FileLock
    ) -> None:
        self.directory = directory
        self.plan = plan
        self._connection = connection
        self._lock = lock
        self._closed = False

    @property
    def connection(self) -> sqlite3.Connection:
        if self._closed:
            raise IntegrityError("Run store is closed.")
        return self._connection

    @staticmethod
    def _acquire(directory: Path) -> FileLock:
        lock = FileLock(safe_child(directory, ".run.lock"), timeout=0)
        try:
            lock.acquire()
        except (Timeout, OSError) as exc:
            raise IntegrityError("Run is locked by another writer or is not accessible.") from exc
        return lock

    @staticmethod
    def _connect(directory: Path, *, creating: bool = False) -> sqlite3.Connection:
        database = safe_child(directory, "state.sqlite3")
        if not creating and not database.is_file():
            raise IntegrityError("Run state database is missing.")
        connection = sqlite3.connect(
            database.as_uri() + ("?mode=rwc" if creating else "?mode=rw"), uri=True
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
        except sqlite3.Error:
            connection.close()
            raise
        return connection

    @classmethod
    def create(cls, directory: Path, plan: RunPlan) -> Self:
        directory = directory.absolute()
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise IntegrityError("Cannot create a new exclusive run directory.") from exc
        lock = cls._acquire(directory)
        connection = None
        succeeded = False
        try:
            for name in ("content", "attempts", "reports"):
                safe_child(directory, name).mkdir()
            plan_bytes = serialize(plan)
            atomic_write(safe_child(directory, "plan.json"), plan_bytes)
            connection = cls._connect(directory, creating=True)
            connection.executescript("""
                PRAGMA user_version = 1;
                CREATE TABLE items (
                    id TEXT PRIMARY KEY, ordinal INTEGER UNIQUE NOT NULL,
                    status TEXT NOT NULL, hash TEXT
                );
                CREATE TABLE assignments (
                    id TEXT PRIMARY KEY REFERENCES items(id), format TEXT NOT NULL
                );
                CREATE TABLE state (
                    id INTEGER PRIMARY KEY CHECK(id=1), status TEXT NOT NULL,
                    plan_hash TEXT NOT NULL
                );
                CREATE TABLE attempts (
                    attempt_id TEXT PRIMARY KEY, content_id TEXT NOT NULL REFERENCES items(id),
                    status TEXT NOT NULL, usage TEXT, error_code TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE events (
                    ordinal INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                    content_id TEXT, created_at TEXT NOT NULL
                );
            """)
            connection.execute(
                "INSERT INTO state VALUES (1, 'planned', ?)",
                (hashlib.sha256(plan_bytes).hexdigest(),),
            )
            connection.executemany(
                "INSERT INTO items VALUES (?, ?, 'pending', NULL)",
                [(b.content_id, b.ordinal) for b in plan.blueprints],
            )
            connection.commit()
            result = cls(directory, plan, connection, lock)
            succeeded = True
            return result
        except (OSError, sqlite3.Error) as exc:
            raise IntegrityError("Cannot initialize durable run state.") from exc
        finally:
            if not succeeded:
                if connection is not None:
                    connection.close()
                lock.release()

    @classmethod
    def open(cls, directory: Path, *, recover: bool = True) -> Self:
        directory = directory.absolute()
        if not directory.is_dir() or directory.is_symlink() or directory.is_junction():
            raise IntegrityError("Run directory is missing or is an unsupported link.")
        lock = cls._acquire(directory)
        connection = None
        succeeded = False
        try:
            raw_plan = safe_child(directory, "plan.json").read_bytes()
            plan = RunPlan.model_validate_json(raw_plan)
            connection = cls._connect(directory)
            if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise IntegrityError("Unsupported state database version.")
            metadata = connection.execute("SELECT plan_hash FROM state WHERE id=1").fetchone()
            if metadata is None or metadata["plan_hash"] != hashlib.sha256(raw_plan).hexdigest():
                raise IntegrityError("Saved plan checksum mismatch.")
            expected = create_plan(
                plan.effective_config, run_id=plan.run_id, operation=plan.operation
            )
            if expected != plan:
                historical = expected.model_copy(
                    update={"semantic_fingerprint": plan.semantic_fingerprint}
                )
                if historical != plan or not any(
                    semantic_fingerprint(plan.effective_config, prompt_version=version)
                    == plan.semantic_fingerprint
                    for version in READABLE_PROMPT_VERSIONS
                ):
                    raise IntegrityError("Saved plan does not match its semantic configuration.")
            store = cls(directory, plan, connection, lock)
            if recover:
                store.reconcile()
            else:
                if (
                    any(item.status != "accepted" for item in store._items())
                    or any(attempt.status == "in_flight" for attempt in store.attempts())
                    or not safe_child(directory, "allocation.json").is_file()
                    or any(safe_child(directory, "content").glob("*.tmp"))
                ):
                    raise IntegrityError(
                        "A preserved source must have complete, quiescent checkpoints; "
                        "automatic recovery is forbidden."
                    )
                store.contents()
                store.read_allocation()
            succeeded = True
            return store
        except (OSError, sqlite3.Error, ValidationError) as exc:
            raise IntegrityError(
                "Run state is missing, corrupt, or has an invalid schema."
            ) from exc
        finally:
            if not succeeded:
                if connection is not None:
                    connection.close()
                lock.release()

    def __enter__(self) -> Self:
        _ = self.connection
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            try:
                self._connection.close()
            finally:
                self._closed = True
                self._lock.release()

    def _items(self) -> tuple[ItemState, ...]:
        try:
            items = tuple(
                ItemState.model_validate(dict(row))
                for row in self.connection.execute("SELECT * FROM items ORDER BY ordinal")
            )
        except (sqlite3.Error, ValidationError) as exc:
            raise IntegrityError("Invalid content checkpoint state.") from exc
        if [(i.id, i.ordinal) for i in items] != [
            (b.content_id, b.ordinal) for b in self.plan.blueprints
        ]:
            raise IntegrityError("Item checkpoints do not match the immutable plan.")
        return items

    def _event(self, kind: str, content_id: str | None = None) -> None:
        self.connection.execute(
            "INSERT INTO events (kind, content_id, created_at) VALUES (?, ?, ?)",
            (kind, content_id, datetime.now(UTC).isoformat()),
        )

    def events(self) -> tuple[str, ...]:
        return tuple(row["kind"] for row in self.connection.execute(
            "SELECT kind FROM events ORDER BY ordinal"
        ))

    def item_states(self) -> dict[str, str]:
        return {item.id: item.status for item in self._items()}

    @property
    def current_status(self) -> str:
        row = self.connection.execute("SELECT status FROM state WHERE id=1").fetchone()
        if row is None:
            raise IntegrityError("Run status is missing.")
        return str(row["status"])

    def set_status(self, value: RunStatus) -> None:
        with self.connection:
            self.connection.execute("UPDATE state SET status=? WHERE id=1", (value,))
            self._event(f"status:{value}")

    def _content_path(self, content_id: str) -> Path:
        return safe_child(safe_child(self.directory, "content"), f"{content_id}.json")

    def _read_content(self, item: ItemState) -> Content:
        path = self._content_path(item.id)
        if not path.is_file():
            raise IntegrityError(f"Accepted content file is missing: {item.id}.")
        try:
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != item.hash:
                raise IntegrityError(f"Content checksum mismatch: {item.id}.")
            content = Content.model_validate_json(raw)
        except (OSError, ValidationError) as exc:
            raise IntegrityError(f"Cannot read canonical content: {item.id}.") from exc
        expected = {b.content_id: b for b in self.plan.blueprints}
        if content.blueprint != expected[item.id]:
            raise IntegrityError("Saved content blueprint does not match its plan.")
        return content

    def contents(self) -> tuple[Content, ...]:
        return tuple(self._read_content(item) for item in self._items()
                     if item.status == "accepted")

    def accept(self, content: Content) -> None:
        content = Content.model_validate_json(content.model_dump_json())
        expected = {blueprint.content_id: blueprint for blueprint in self.plan.blueprints}
        content_id = content.blueprint.content_id
        if expected.get(content_id) != content.blueprint:
            raise IntegrityError("Candidate blueprint does not match the planned blueprint.")
        item = next(item for item in self._items() if item.id == content_id)
        if item.status != "pending":
            raise IntegrityError("Accepted or writing content identity is immutable.")
        digest = content_hash(content)
        try:
            with self.connection:
                self.connection.execute(
                    "UPDATE items SET status='writing', hash=? WHERE id=?", (digest, content_id)
                )
            atomic_write(self._content_path(content_id), serialize(content))
            with self.connection:
                self.connection.execute(
                    "UPDATE items SET status='accepted' WHERE id=?", (content_id,)
                )
                self._event("content_accepted", content_id)
        except sqlite3.Error as exc:
            raise IntegrityError("Content checkpoint transaction failed.") from exc

    def reconcile(self) -> None:
        items = self._items()
        directory = safe_child(self.directory, "content")
        expected_names = {f"{item.id}.json" for item in items}
        expected_temporary = {temporary_path(self._content_path(item.id)).name for item in items}
        allowed_names = expected_names | expected_temporary
        if any(path.name not in allowed_names for path in directory.iterdir()):
            raise IntegrityError("Run contains an unexpected content file; nothing was deleted.")
        for item in items:
            path = self._content_path(item.id)
            temporary = temporary_path(path)
            if item.status == "pending" and (path.exists() or temporary.exists()):
                raise IntegrityError("Uncheckpointed content file cannot be adopted.")
            if item.status == "writing":
                if not item.hash:
                    raise IntegrityError("Writing checkpoint is missing its expected hash.")
                if not path.exists() and temporary.exists():
                    if hashlib.sha256(temporary.read_bytes()).hexdigest() == item.hash:
                        os.link(temporary, path)
                    else:
                        temporary.unlink()
                        with self.connection:
                            self._event("partial_temporary_discarded", item.id)
                if path.exists():
                    self._read_content(item)
                    with self.connection:
                        self.connection.execute(
                            "UPDATE items SET status='accepted' WHERE id=?", (item.id,)
                        )
                        self._event("content_reconciled", item.id)
                else:
                    with self.connection:
                        self.connection.execute(
                            "UPDATE items SET status='pending', hash=NULL WHERE id=?", (item.id,)
                        )
                        self._event("interrupted_write_restarted", item.id)
            if item.status == "accepted":
                self._read_content(item)
            if temporary.exists():
                if hashlib.sha256(temporary.read_bytes()).hexdigest() != item.hash:
                    raise IntegrityError("Owned temporary checksum mismatch.")
                temporary.unlink()
                with self.connection:
                    self._event("temporary_reconciled", item.id)
        with self.connection:
            for row in self.connection.execute(
                "SELECT attempt_id, content_id FROM attempts WHERE status='in_flight'"
            ).fetchall():
                self.connection.execute(
                    "UPDATE attempts SET status='unknown' WHERE attempt_id=?", (row["attempt_id"],)
                )
                self._event("attempt_outcome_unknown", row["content_id"])
        self.read_allocation()

    def begin_attempt(self, content_id: str) -> str:
        _ = self.connection
        attempt_id = f"attempt-{uuid4().hex}"
        try:
            with closing(self._connect(self.directory)) as database, database:
                cursor = database.execute(
                    "INSERT INTO attempts SELECT ?, id, 'in_flight', NULL, NULL, ? "
                    "FROM items WHERE id=? AND status='pending'",
                    (attempt_id, datetime.now(UTC).isoformat(), content_id),
                )
                if cursor.rowcount != 1:
                    raise IntegrityError("Only a pending planned item may start a model attempt.")
        except sqlite3.Error as exc:
            raise IntegrityError("Cannot persist the model attempt checkpoint.") from exc
        return attempt_id

    def finish_attempt(
        self, attempt_id: str, *, status: Literal["succeeded", "failed"],
        usage: Usage | None = None, error_code: str | None = None,
    ) -> None:
        _ = self.connection
        try:
            with closing(self._connect(self.directory)) as database, database:
                cursor = database.execute(
                    "UPDATE attempts SET status=?, usage=?, error_code=? "
                    "WHERE attempt_id=? AND status='in_flight'",
                    (status, usage.model_dump_json() if usage else None, error_code, attempt_id),
                )
                if cursor.rowcount != 1:
                    raise IntegrityError("Attempt outcome is immutable or attempt is unknown.")
        except sqlite3.Error as exc:
            raise IntegrityError("Cannot persist the model attempt outcome.") from exc

    def candidate_count(self, content_id: str) -> int:
        return int(self.connection.execute(
            "SELECT COUNT(*) FROM events WHERE kind='candidate_started' AND content_id=?",
            (content_id,),
        ).fetchone()[0])

    def begin_candidate(self, content_id: str) -> None:
        _ = self.connection
        try:
            with closing(self._connect(self.directory)) as database, database:
                cursor = database.execute(
                    "INSERT INTO events (kind,content_id,created_at) "
                    "SELECT 'candidate_started',id,? FROM items WHERE id=? AND status='pending'",
                    (datetime.now(UTC).isoformat(), content_id),
                )
                if cursor.rowcount != 1:
                    raise IntegrityError("Only a pending item may start a quality candidate.")
        except sqlite3.Error as exc:
            raise IntegrityError("Cannot persist the candidate checkpoint.") from exc

    def record_rejection(self, content_id: str) -> None:
        with self.connection:
            self._event("candidate_rejected", content_id)

    def attempts(self) -> tuple[Attempt, ...]:
        result = []
        for row in self.connection.execute("SELECT * FROM attempts ORDER BY rowid"):
            data = dict(row)
            if data["usage"] is not None:
                data["usage"] = Usage.model_validate_json(data["usage"])
            result.append(Attempt.model_validate(data))
        return tuple(result)

    def inherit_authoring(self, source: "RunStore") -> None:
        if (
            self.directory == source.directory
            or self.plan.effective_config != source.plan.effective_config
            or self.plan.blueprints != source.plan.blueprints
            or self.current_status != "planned"
            or self.contents() or self.attempts() or self.events()
        ):
            raise IntegrityError(
                "Authoring inheritance requires a fresh run with identical frozen blueprints."
            )
        attempts = source.attempts()
        if any(attempt.status == "in_flight" for attempt in attempts):
            raise IntegrityError("Cannot inherit authoring with an in-flight model request.")
        events = source.connection.execute(
            "SELECT kind,content_id,created_at FROM events "
            "WHERE kind IN ('candidate_started','candidate_rejected') ORDER BY ordinal"
        ).fetchall()
        response_hashes = {}
        for attempt in attempts:
            filename = f"{attempt.attempt_id}.json"
            path = safe_child(safe_child(source.directory, "attempts"), filename)
            if path.exists():
                raw = path.read_bytes()
                response_hashes[filename] = hashlib.sha256(raw).hexdigest()
                atomic_write(safe_child(safe_child(self.directory, "attempts"), filename), raw)
            elif attempt.status == "succeeded":
                raise IntegrityError("A successful inherited attempt is missing its raw response.")
        history = {
            "origin_run_id": source.plan.run_id,
            "origin_path": str(source.directory),
            "attempts": [attempt.model_dump(mode="json") for attempt in attempts],
            "candidate_events": [dict(row) for row in events],
            "response_hashes": response_hashes,
            "usage_included_in_destination_limits": True,
        }
        raw = json.dumps(history, sort_keys=True, ensure_ascii=False).encode("utf-8")
        try:
            with self.connection:
                self.connection.executemany(
                    "INSERT INTO attempts VALUES (?,?,?,?,?,?)",
                    [
                        (
                            row.attempt_id, row.content_id, row.status,
                            row.usage.model_dump_json() if row.usage else None,
                            row.error_code, row.created_at.isoformat(),
                        )
                        for row in attempts
                    ],
                )
                self.connection.executemany(
                    "INSERT INTO events(kind,content_id,created_at) VALUES (?,?,?)",
                    [tuple(row) for row in events],
                )
                self.connection.execute(
                    "CREATE TABLE inherited_authoring(payload BLOB NOT NULL,hash TEXT NOT NULL)"
                )
                self.connection.execute(
                    "INSERT INTO inherited_authoring VALUES (?,?)",
                    (raw, hashlib.sha256(raw).hexdigest()),
                )
                self._event("authoring_inherited")
        except sqlite3.Error as exc:
            raise IntegrityError("Cannot checkpoint inherited authoring history.") from exc
        atomic_write(
            safe_child(safe_child(self.directory, "reports"), "inherited-authoring.json"), raw,
        )

    def assign_markdown(self) -> None:
        if len(self.contents()) != len(self.plan.blueprints):
            raise IntegrityError("Cannot allocate incomplete content.")
        from docgen.allocation import allocate
        from docgen.config import RenderConfig

        self.freeze_allocation(allocate(
            self.contents(), RenderConfig(weights={"md": Decimal(1)}),
            seed=self.plan.effective_config.seed,
        ))

    def _check_allocation(self, allocation: "AllocationPlan") -> None:
        contents = {content.blueprint.content_id: content for content in self.contents()}
        if (
            len(contents) != len(self.plan.blueprints)
            or set(contents) != {item.content_id for item in allocation.items}
        ):
            raise IntegrityError("Allocation requires every accepted planned content item.")
        actual: dict[tuple[str, str, str | None], dict[str, int]] = {}
        for assignment in allocation.items:
            content = contents[assignment.content_id]
            if assignment.source_hash != content_hash(content):
                raise IntegrityError("Allocation source checksum does not match accepted content.")
            key = (
                content.blueprint.topic_id, content.blueprint.length_band,
                content.blueprint.structure_plan.complexity
                if content.blueprint.structure_plan is not None else None,
            )
            counts = actual.setdefault(key, {fmt: 0 for fmt in allocation.config.weights})
            counts[assignment.format] += 1
        reported = {
            (stratum.topic_id, stratum.length_band, stratum.complexity): dict(stratum.counts)
            for stratum in allocation.strata
        }
        if len(reported) != len(allocation.strata) or actual != reported:
            raise IntegrityError("Allocation strata do not match accepted content metadata.")

    def read_allocation(self) -> "AllocationPlan | None":
        from docgen.allocation import AllocationPlan

        artifact = safe_child(self.directory, "allocation.json")
        table = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='allocation'"
        ).fetchone()
        row = self.connection.execute(
            "SELECT payload,hash FROM allocation WHERE id=1"
        ).fetchone() if table is not None else None
        if row is None:
            if artifact.exists():
                raise IntegrityError("Uncheckpointed allocation file cannot be adopted.")
            return None
        raw = row["payload"]
        if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != row["hash"]:
            raise IntegrityError("Stored allocation checkpoint checksum mismatch.")
        try:
            allocation = AllocationPlan.model_validate_json(raw)
        except ValidationError as exc:
            raise IntegrityError("Invalid allocation checkpoint schema.") from exc
        self._check_allocation(allocation)
        mapping = dict(self.connection.execute("SELECT id,format FROM assignments").fetchall())
        if mapping != {item.content_id: item.format for item in allocation.items}:
            raise IntegrityError("Format assignment is immutable; stored mapping differs.")
        if artifact.exists():
            if artifact.read_bytes() != raw:
                raise IntegrityError("Published allocation checksum mismatch.")
        else:
            atomic_write(artifact, raw)
        return allocation

    def freeze_allocation(self, allocation: "AllocationPlan") -> None:
        from docgen.allocation import AllocationPlan

        try:
            allocation = AllocationPlan.model_validate_json(serialize(allocation))
        except ValueError as exc:
            raise IntegrityError("Invalid allocation plan; nothing was frozen.") from exc
        existing = self.read_allocation()
        if existing is not None:
            if existing != allocation:
                raise IntegrityError("Allocation configuration and assignments are immutable.")
            return
        self._check_allocation(allocation)
        previous = dict(self.connection.execute("SELECT id,format FROM assignments").fetchall())
        proposed = {item.content_id: item.format for item in allocation.items}
        if previous and previous != proposed:
            raise IntegrityError("Format assignment is immutable.")
        raw = serialize(allocation)
        try:
            with self.connection:
                self.connection.execute(
                    "CREATE TABLE IF NOT EXISTS allocation "
                    "(id INTEGER PRIMARY KEY CHECK(id=1),payload BLOB NOT NULL,hash TEXT NOT NULL)"
                )
                self.connection.execute(
                    "INSERT INTO allocation VALUES (1,?,?)",
                    (raw, hashlib.sha256(raw).hexdigest()),
                )
                self.connection.executemany(
                    "INSERT INTO assignments VALUES (?,?) ON CONFLICT(id) DO NOTHING",
                    proposed.items(),
                )
                self.connection.execute(
                    "UPDATE state SET status='allocated' WHERE status!='complete'"
                )
                self._event("allocation_frozen")
        except sqlite3.Error as exc:
            raise IntegrityError("Cannot persist the immutable format allocation.") from exc
        atomic_write(safe_child(self.directory, "allocation.json"), raw)

    def rendered_states(self) -> dict[str, RenderedState]:
        table = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rendered_artifacts'"
        ).fetchone()
        if table is None:
            return {}
        try:
            states = {
                row["id"]: RenderedState.model_validate(dict(row))
                for row in self.connection.execute("SELECT * FROM rendered_artifacts")
            }
        except (sqlite3.Error, ValidationError) as exc:
            raise IntegrityError("Invalid artifact checkpoint schema.") from exc
        assigned = {row["id"] for row in self.connection.execute("SELECT id FROM assignments")}
        if not set(states).issubset(assigned) or any(
            (
                state.status == "verified" and (
                    state.hash is None or state.byte_count is None or state.validation is None
                )
            ) or (
                state.status == "rendering" and any(
                    value is not None for value in (state.hash, state.byte_count, state.validation)
                )
            )
            for state in states.values()
        ):
            raise IntegrityError("Artifact checkpoints differ from the immutable allocation.")
        return states

    def start_artifact(self, content_id: str) -> None:
        if self.connection.execute(
            "SELECT 1 FROM assignments WHERE id=?", (content_id,)
        ).fetchone() is None:
            raise IntegrityError("Cannot render an unallocated content item.")
        try:
            with self.connection:
                self.connection.execute(
                    "CREATE TABLE IF NOT EXISTS rendered_artifacts "
                    "(id TEXT PRIMARY KEY REFERENCES assignments(id), status TEXT NOT NULL, "
                    "hash TEXT,byte_count INTEGER,validation BLOB)"
                )
                existing = self.connection.execute(
                    "SELECT * FROM rendered_artifacts WHERE id=?", (content_id,)
                ).fetchone()
                if existing is not None:
                    if existing["status"] != "rendering":
                        raise IntegrityError("Verified artifact checkpoint is immutable.")
                    return
                self.connection.execute(
                    "INSERT INTO rendered_artifacts VALUES (?,'rendering',NULL,NULL,NULL)",
                    (content_id,),
                )
                self._event("artifact_started", content_id)
        except sqlite3.Error as exc:
            raise IntegrityError("Cannot persist the artifact-start checkpoint.") from exc

    def verify_artifact(self, artifact: "Artifact", report: "ArtifactValidation") -> RenderedState:
        source = self.connection.execute(
            "SELECT items.hash,assignments.format FROM items JOIN assignments "
            "ON items.id=assignments.id WHERE items.id=?", (artifact.content_id,)
        ).fetchone()
        if (
            source is None or source["hash"] != artifact.source_hash
            or source["format"] != artifact.format or not report.valid
            or report.content_id != artifact.content_id or report.filename != artifact.filename
            or report.artifact_sha256 != artifact.sha256
            or report.source_hash != artifact.source_hash
        ):
            raise IntegrityError("Artifact validation does not match its assigned source/checksum.")
        state = RenderedState(
            id=artifact.content_id, status="verified", hash=artifact.sha256,
            byte_count=artifact.byte_count, validation=serialize(report),
        )
        try:
            with self.connection:
                cursor = self.connection.execute(
                    "UPDATE rendered_artifacts SET "
                    "status='verified',hash=?,byte_count=?,validation=? "
                    "WHERE id=? AND status='rendering'",
                    (state.hash, state.byte_count, state.validation, state.id),
                )
                if cursor.rowcount != 1:
                    raise IntegrityError("Artifact checkpoint is missing or already immutable.")
                self._event("artifact_verified", state.id)
        except sqlite3.Error as exc:
            raise IntegrityError("Cannot persist the verified artifact checkpoint.") from exc
        return state
