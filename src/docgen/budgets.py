import hashlib
import json
import sqlite3
from datetime import UTC, datetime

from pydantic import Field, StrictInt, ValidationError

from docgen.config import GenerationConfig
from docgen.errors import InputError, IntegrityError
from docgen.models import Record, serialize
from docgen.persistence import atomic_write, safe_child
from docgen.store import RunStore


class BudgetOverride(Record):
    max_requests: StrictInt | None = Field(default=None, ge=1)
    max_observed_total_tokens: StrictInt | None = Field(default=None, ge=1)
    max_candidates_per_item: StrictInt | None = Field(default=None, ge=1, le=40)


class BudgetEntry(Record):
    run_id: str
    created_at: datetime
    override: BudgetOverride


def budget_history(store: RunStore) -> tuple[BudgetEntry, ...]:
    table = store.connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='budget_overrides'"
    ).fetchone()
    if table is None:
        return ()
    entries = []
    try:
        for row in store.connection.execute(
            "SELECT payload,hash FROM budget_overrides ORDER BY ordinal"
        ):
            raw = row["payload"]
            if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != row["hash"]:
                raise IntegrityError("Budget history checksum differs.")
            entry = BudgetEntry.model_validate_json(raw)
            if entry.run_id != store.plan.run_id:
                raise IntegrityError("Budget history belongs to a different run.")
            entries.append(entry)
    except (sqlite3.Error, ValidationError) as exc:
        raise IntegrityError("Invalid audited budget history.") from exc
    return tuple(entries)


def apply_budget(config: GenerationConfig, override: BudgetOverride) -> GenerationConfig:
    old = {
        "max_requests": config.request_limit,
        "max_observed_total_tokens": config.limits.max_observed_total_tokens,
        "max_candidates_per_item": config.quality.max_candidates_per_item,
    }
    if any(
        value is not None and value < old[name] for name, value in override.model_dump().items()
    ):
        raise InputError("Resume budgets may only increase, never decrease.")
    data = config.model_dump()
    data["limits"] = {
        **config.limits.model_dump(),
        "max_requests": override.max_requests or config.request_limit,
        "max_observed_total_tokens": (
            override.max_observed_total_tokens or config.limits.max_observed_total_tokens
        ),
    }
    data["quality"] = {
        **config.quality.model_dump(),
        "max_candidates_per_item": (
            override.max_candidates_per_item or config.quality.max_candidates_per_item
        ),
    }
    return GenerationConfig.model_validate(data)


def effective_generation(store: RunStore) -> GenerationConfig:
    config = store.plan.effective_config.generation
    if config is None:
        raise IntegrityError("Saved run has no generation configuration.")
    for entry in budget_history(store):
        config = apply_budget(config, entry.override)
    return config


def increase_budget(store: RunStore, override: BudgetOverride) -> None:
    if all(value is None for value in override.model_dump().values()):
        return
    current = effective_generation(store)
    updated = apply_budget(current, override)
    if current == updated:
        return
    entry = BudgetEntry(run_id=store.plan.run_id, created_at=datetime.now(UTC), override=override)
    raw = serialize(entry)
    try:
        with store.connection:
            store.connection.execute(
                "CREATE TABLE IF NOT EXISTS budget_overrides "
                "(ordinal INTEGER PRIMARY KEY AUTOINCREMENT,"
                "payload BLOB NOT NULL,hash TEXT NOT NULL)"
            )
            store.connection.execute(
                "INSERT INTO budget_overrides(payload,hash) VALUES (?,?)",
                (raw, hashlib.sha256(raw).hexdigest()),
            )
    except sqlite3.Error as exc:
        raise IntegrityError("Cannot persist the explicit budget increase.") from exc
    atomic_write(
        safe_child(safe_child(store.directory, "reports"), "budget-history.json"),
        json.dumps([item.model_dump(mode="json") for item in budget_history(store)]).encode(),
        overwrite=True,
    )
