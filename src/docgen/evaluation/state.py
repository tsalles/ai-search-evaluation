import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Literal, Self
from uuid import uuid4

from filelock import FileLock, Timeout
from pydantic import Field, JsonValue, RootModel, ValidationError, model_validator

from docgen.config import Config
from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.models import ARMS, EntityExtractionSettings, ExperimentConfig
from docgen.models import Identifier, Record, serialize
from docgen.persistence import atomic_write, safe_child, temporary_path

Kind = Literal["search", "embedding", "admin", "blob"]


class StoredJson(RootModel[JsonValue]):
    pass


def json_bytes(value: JsonValue) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(value: Record | JsonValue) -> str:
    return hashlib.sha256(
        serialize(value) if isinstance(value, Record) else json_bytes(value)
    ).hexdigest()


class Protocol(Record):
    legacy_optional_fields = ("enrichment_policy",)
    schema_version: Literal["1", "2"] = "1"
    enrichment_policy: Literal["search-pipeline-only"] | None = None
    id: Identifier
    created_at: datetime
    config: ExperimentConfig
    generation_config: Config
    source_run_id: Identifier
    source_prefix: str

    @property
    def pipeline_only(self) -> bool:
        return self.schema_version == "2"

    @property
    def source_context_enabled(self) -> bool:
        return not self.pipeline_only and self.config.search.variant is not None

    @property
    def entity_extraction(self) -> EntityExtractionSettings | None:
        variant = self.config.search.variant
        return variant.entity_extraction if variant is not None else None

    @model_validator(mode="after")
    def valid_enrichment_policy(self) -> Self:
        if self.pipeline_only != (self.enrichment_policy is not None):
            raise ValueError("The protocol version and enrichment policy must agree.")
        variant = self.config.search.variant
        if self.pipeline_only and variant is not None and variant.embedding_context:
            raise ValueError("Document embedding enrichment must run in the Search pipeline.")
        if self.entity_extraction is not None and not self.pipeline_only:
            raise ValueError("Pipeline entity treatments require a pipeline-only protocol.")
        return self

    def require_pipeline_only(self) -> None:
        if not self.pipeline_only:
            raise InputError(
                "Version 1 experiments are historical and read-only; "
                "fork a new raw-only experiment before live work."
            )

    def resource_name(self, arm: str, kind: str) -> str:
        if arm not in ARMS or kind not in {"index", "skills", "source", "indexer"}:
            raise InputError("Unsupported experiment arm or resource kind.")
        suffix = "de" if arm == "de_split" else "cu"
        return f"{self.config.search.name_prefix}-{self.id[-12:]}-{suffix}-{kind}"


class RemoteValue(Record):
    data: JsonValue
    tokens: int | None = Field(default=None, strict=True, ge=0)
    elapsed_ms: float | None = Field(default=None, ge=0)


class Workspace:
    def __init__(self, path: Path) -> None:
        self.path = path.absolute()
        if self.path.is_symlink() or self.path.is_junction() or not self.path.is_dir():
            raise IntegrityError("Experiment directory is missing or is a filesystem link.")
        self.lock = FileLock(safe_child(self.path, ".experiment.lock"), timeout=0)
        try:
            self.lock.acquire()
        except (Timeout, OSError):
            raise IntegrityError("Experiment is locked by another writer.") from None
        self.connection: sqlite3.Connection | None = None
        try:
            raw = safe_child(self.path, "protocol.json").read_bytes()
            self.protocol = Protocol.model_validate_json(raw)
            database = safe_child(self.path, "evaluation.sqlite3")
            self.connection = sqlite3.connect(database.as_uri() + "?mode=rw", uri=True)
            saved = self.connection.execute("SELECT hash FROM protocol").fetchone()
            if saved is None or saved[0] != hashlib.sha256(raw).hexdigest():
                raise IntegrityError("Experiment protocol checksum differs.")
            if self.connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise IntegrityError("Unsupported evaluation state version.")
            with self.connection:
                self.connection.execute(
                    "UPDATE attempts SET status='unknown' WHERE status='in_flight'"
                )
        except (OSError, sqlite3.Error, ValidationError):
            self.close()
            raise IntegrityError("Experiment state is missing, corrupt or invalid.") from None
        except IntegrityError:
            self.close()
            raise

    @classmethod
    def create(cls, output: Path, protocol: Protocol) -> Self:
        protocol = Protocol.model_validate_json(protocol.model_dump_json())
        path = safe_child(output.absolute(), protocol.id)
        try:
            path.mkdir(parents=True, exist_ok=False)
            raw = serialize(protocol)
            atomic_write(safe_child(path, "protocol.json"), raw)
            database = safe_child(path, "evaluation.sqlite3")
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.executescript("""
                    PRAGMA user_version=1;
                    PRAGMA synchronous=FULL;
                    CREATE TABLE protocol(hash TEXT NOT NULL);
                    CREATE TABLE records(name TEXT PRIMARY KEY,payload BLOB NOT NULL,
                                         hash TEXT NOT NULL);
                    CREATE TABLE attempts(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,
                        tag TEXT NOT NULL,status TEXT NOT NULL,tokens INTEGER,
                        error TEXT,elapsed_ms REAL);
                """)
                connection.execute(
                    "INSERT INTO protocol VALUES (?)",
                    (hashlib.sha256(raw).hexdigest(),),
                )
        except (OSError, sqlite3.Error):
            raise IntegrityError("Cannot create exclusive durable experiment state.") from None
        return cls(path)

    @property
    def database(self) -> sqlite3.Connection:
        if self.connection is None:
            raise IntegrityError("Experiment workspace is closed.")
        return self.connection

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self.lock.release()

    def get(self, name: str) -> JsonValue | None:
        row = self.database.execute(
            "SELECT payload,hash FROM records WHERE name=?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        raw, expected = row
        if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != expected:
            raise IntegrityError("Evaluation record checksum differs.")
        try:
            return StoredJson.model_validate_json(raw).root
        except (ValueError, UnicodeError):
            raise IntegrityError("Evaluation record JSON is invalid.") from None

    def put(self, name: str, value: JsonValue) -> None:
        existing = self.get(name)
        if existing is not None:
            if existing != value:
                raise IntegrityError(f"Immutable evaluation record differs: {name}.")
            return
        raw = json_bytes(value)
        self.database.execute(
            "INSERT INTO records VALUES (?,?,?)",
            (name, raw, hashlib.sha256(raw).hexdigest()),
        )
        self.database.commit()

    def record(self, name: str, value: Record) -> None:
        self.put(name, value.model_dump(mode="json"))

    def require_valid(self) -> None:
        if self.get("invalidated") is not None:
            raise IntegrityError(
                "Detected source/index drift permanently invalidated this experiment."
            )

    def export(self, filename: str, value: Record | JsonValue) -> Path:
        raw = serialize(value) if isinstance(value, Record) else json_bytes(value)
        return self.export_bytes(filename, raw)

    def export_bytes(self, filename: str, raw: bytes) -> Path:
        path = safe_child(self.path, filename)
        if path.exists():
            if path.read_bytes() != raw:
                raise IntegrityError(
                    "Existing experiment export differs from its immutable record."
                )
        self._clear_staging(path)
        if not path.exists():
            atomic_write(path, raw)
        return path

    def replace_draft(self, filename: str, raw: bytes) -> None:
        if not filename.endswith("-draft.json"):
            raise InputError("Only explicitly editable draft files can be replaced.")
        path = safe_child(self.path, filename)
        self._clear_staging(path)
        atomic_write(path, raw, overwrite=True)

    def _clear_staging(self, destination: Path) -> None:
        if not self.lock.is_locked:
            raise IntegrityError("Experiment workspace is not locked for writing.")
        temporary_path(destination).unlink(missing_ok=True)

    def invoke(
        self,
        kind: Kind,
        tag: str,
        call: Callable[[], RemoteValue],
        *,
        fingerprint: str | None = None,
        semantic: bool = False,
    ) -> RemoteValue:
        if semantic and kind != "search":
            raise InputError("Semantic request accounting requires a Search request.")
        cache_key = f"remote:{tag}"
        if fingerprint is not None:
            identity: dict[str, JsonValue] = {"kind": kind, "fingerprint": fingerprint}
            existing = self.get(f"request:{tag}")
            if existing is not None and existing != identity:
                raise IntegrityError("Request fingerprint differs from its original attempt.")
            self.put(f"request:{tag}", identity)
            saved = self.get(cache_key)
            if saved is not None:
                if not isinstance(saved, dict) or saved.get("fingerprint") != fingerprint:
                    raise IntegrityError("Cached request fingerprint differs.")
                return RemoteValue.model_validate(saved["result"])
        limits = self.protocol.config.limits
        cap = {
            "search": limits.max_search_attempts,
            "embedding": limits.max_embedding_attempts,
            "admin": limits.max_admin_attempts,
            "blob": limits.max_blob_attempts,
        }[kind]
        deadline = time.monotonic() + limits.request_timeout_seconds
        for retry in range(limits.transport_attempts):
            count = self.database.execute(
                "SELECT COUNT(*) FROM attempts WHERE kind=?",
                (kind,),
            ).fetchone()[0]
            tokens = self.database.execute(
                "SELECT COALESCE(SUM(tokens),0) FROM attempts WHERE kind='embedding'"
            ).fetchone()[0]
            if count >= cap or (
                kind == "embedding" and tokens >= limits.max_observed_embedding_tokens
            ):
                raise ProviderError(
                    "evaluation_budget", "The experiment request/token budget is exhausted."
                )
            if semantic and limits.max_semantic_attempts is not None:
                used = self.database.execute(
                    "SELECT COUNT(*) FROM records WHERE name LIKE 'semantic-attempt:%'"
                ).fetchone()[0]
                if used >= limits.max_semantic_attempts:
                    raise ProviderError(
                        "semantic_budget", "The experiment semantic request budget is exhausted."
                    )
            if time.monotonic() >= deadline:
                raise ProviderError(
                    "evaluation_deadline", "The experiment request deadline is exhausted."
                )
            with self.database:
                cursor = self.database.execute(
                    "INSERT INTO attempts(kind,tag,status) VALUES (?,?,'in_flight')",
                    (kind, tag),
                )
                attempt = cursor.lastrowid
                if semantic and limits.max_semantic_attempts is not None:
                    raw = json_bytes({"attempt_id": attempt, "tag": tag})
                    self.database.execute(
                        "INSERT INTO records VALUES (?,?,?)",
                        (
                            f"semantic-attempt:{attempt}",
                            raw,
                            hashlib.sha256(raw).hexdigest(),
                        ),
                    )
            started = time.monotonic()
            try:
                value = call()
            except ProviderError as error:
                with self.database:
                    self.database.execute(
                        "UPDATE attempts SET status='failed',error=?,tokens=?,elapsed_ms=? "
                        "WHERE id=?",
                        (
                            error.code,
                            error.usage.total_tokens
                            if kind == "embedding" and error.usage
                            else None,
                            (time.monotonic() - started) * 1000,
                            attempt,
                        ),
                    )
                delay = (
                    error.retry_after_seconds if error.retry_after_seconds is not None else 2**retry
                )
                if (
                    not error.retryable
                    or retry + 1 == limits.transport_attempts
                    or delay >= deadline - time.monotonic()
                ):
                    raise
                time.sleep(delay)
            except (InputError, IntegrityError) as error:
                with self.database:
                    self.database.execute(
                        "UPDATE attempts SET status='failed',error=?,elapsed_ms=? WHERE id=?",
                        (
                            "integrity_error"
                            if isinstance(error, IntegrityError)
                            else "invalid_input",
                            (time.monotonic() - started) * 1000,
                            attempt,
                        ),
                    )
                raise
            except KeyboardInterrupt:
                with self.database:
                    self.database.execute(
                        "UPDATE attempts SET status='unknown' WHERE id=?",
                        (attempt,),
                    )
                raise
            else:
                value = value.model_copy(
                    update={
                        "elapsed_ms": (time.monotonic() - started) * 1000,
                    }
                )
                with self.database:
                    self.database.execute(
                        "UPDATE attempts SET status='succeeded',tokens=?,elapsed_ms=? WHERE id=?",
                        (value.tokens, (time.monotonic() - started) * 1000, attempt),
                    )
                    if fingerprint is not None:
                        raw = json_bytes(
                            {
                                "fingerprint": fingerprint,
                                "result": value.model_dump(mode="json"),
                            }
                        )
                        self.database.execute(
                            "INSERT INTO records VALUES (?,?,?)",
                            (cache_key, raw, hashlib.sha256(raw).hexdigest()),
                        )
                return value
        raise AssertionError("Validated request attempts must be positive.")

    def usage(self) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {
            "attempts": {
                kind: self.database.execute(
                    "SELECT COUNT(*) FROM attempts WHERE kind=?",
                    (kind,),
                ).fetchone()[0]
                for kind in ("search", "embedding", "admin", "blob")
            },
            "observed_embedding_tokens": self.database.execute(
                "SELECT COALESCE(SUM(tokens),0) FROM attempts WHERE kind='embedding'"
            ).fetchone()[0],
            "embedding_usage_unknown": self.database.execute(
                "SELECT COUNT(*) FROM attempts WHERE kind='embedding' AND tokens IS NULL"
            ).fetchone()[0],
        }
        semantic_limit = self.protocol.config.limits.max_semantic_attempts
        if semantic_limit is not None:
            result["semantic_attempts"] = self.database.execute(
                "SELECT COUNT(*) FROM records WHERE name LIKE 'semantic-attempt:%'"
            ).fetchone()[0]
            result["semantic_attempt_limit"] = semantic_limit
        return result


def new_protocol(config: ExperimentConfig) -> Protocol:
    from docgen.families import create_families

    if config.search.variant is not None and config.search.variant.embedding_context:
        raise InputError(
            "External document embedding context is forbidden; "
            "all document enrichment must run in the Search pipeline."
        )
    if (
        config.search.variant is not None
        and config.search.variant.entity_extraction is not None
        and config.search.variant.entity_extraction.method != "ner"
        and config.search.variant.entity_extraction.base_url is None
    ):
        raise InputError("Pipeline entity extraction requires its actual Azure OpenAI v1 base URL.")
    identifier = "experiment-" + uuid4().hex
    generation = config.generation.model_copy(
        update={
            "families": create_families(
                config.family_count,
                seed=config.seed,
                language=config.generation.language,
                split_weights={key: value for key, value in config.split_weights.items()},
                domain="saas" if config.family_domain == "saas" else "banking",
            ),
        }
    )
    return Protocol(
        schema_version="2",
        enrichment_policy="search-pipeline-only",
        id=identifier,
        created_at=datetime.now(UTC),
        config=config,
        generation_config=Config(
            seed=config.seed, generation=generation, rendering=config.rendering
        ),
        source_run_id="run-" + uuid4().hex,
        source_prefix=f"{config.storage.prefix_root}/{identifier}",
    )


def require_live(live: bool) -> None:
    if not live:
        raise InputError(
            "This operation requires --live to authorize Azure requests or billable work."
        )
