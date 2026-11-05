import hashlib

import pytest

from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.state import RemoteValue, Workspace
from docgen.persistence import temporary_path
from tests.evaluation.fixtures import fresh_workspace


def test_exclusive_lock_immutable_records_exports_and_closed_workspace_are_guarded(tmp_path):
    with fresh_workspace(tmp_path) as workspace:
        directory = workspace.path
        with pytest.raises(IntegrityError, match="locked"):
            Workspace(directory)
        workspace.put("immutable", {"value": 1})
        with pytest.raises(IntegrityError, match="Immutable"):
            workspace.put("immutable", {"value": 2})
        workspace.export("export.json", {"value": 1})
        with pytest.raises(IntegrityError, match="export differs"):
            workspace.export("export.json", {"value": 2})
        with pytest.raises(InputError, match="Unsupported"):
            workspace.protocol.resource_name("unsupported", "index")
        with pytest.raises(InputError, match="Unsupported"):
            workspace.protocol.resource_name("de_split", "../index")
    with pytest.raises(IntegrityError, match="closed"):
        workspace.get("immutable")


def test_protocol_and_record_corruption_close_windows_database_handles(tmp_path):
    with fresh_workspace(tmp_path) as workspace:
        directory = workspace.path
        workspace.put("corrupt", {"value": 1})
        workspace.database.execute("UPDATE records SET hash='wrong' WHERE name='corrupt'")
        workspace.database.commit()
        with pytest.raises(IntegrityError, match="checksum"):
            workspace.get("corrupt")
        raw = b"not-json"
        workspace.database.execute(
            "UPDATE records SET payload=?,hash=? WHERE name='corrupt'",
            (raw, hashlib.sha256(raw).hexdigest()),
        )
        workspace.database.commit()
        with pytest.raises(IntegrityError, match="JSON"):
            workspace.get("corrupt")
    protocol = directory / "protocol.json"
    protocol.write_bytes(protocol.read_bytes() + b"\n")
    with pytest.raises(IntegrityError, match="checksum"):
        Workspace(directory)
    database = directory / "evaluation.sqlite3"
    renamed = directory / "renamed.sqlite3"
    database.rename(renamed)
    renamed.rename(database)
    with pytest.raises(IntegrityError, match="missing"):
        Workspace(tmp_path / "does-not-exist")


def test_unsupported_schema_rejects_reopening_and_releases_the_lock(tmp_path):
    with fresh_workspace(tmp_path) as workspace:
        directory = workspace.path
        workspace.database.execute("PRAGMA user_version=9")
    with pytest.raises(IntegrityError, match="Unsupported"):
        Workspace(directory)
    database = directory / "evaluation.sqlite3"
    renamed = directory / "old-version.sqlite3"
    database.rename(renamed)


def test_retry_budgets_are_persistent_and_only_confirmed_responses_are_reused(
    tmp_path,
    monkeypatch,
):
    import docgen.evaluation.state as state

    delays = []
    monkeypatch.setattr(state.time, "sleep", delays.append)
    with fresh_workspace(tmp_path) as workspace:
        count = 0

        def eventually():
            nonlocal count
            count += 1
            if count == 1:
                raise ProviderError(
                    "throttled", "Retry later.", retryable=True, retry_after_seconds=2
                )
            return RemoteValue(data={"result": "confirmed"}, tokens=3)

        result = workspace.invoke("embedding", "retry", eventually, fingerprint="original")
        assert count == 2 and result.tokens == 3 and result.elapsed_ms is not None
        assert delays == [2]
        assert workspace.invoke("embedding", "retry", eventually, fingerprint="original") == result
        assert count == 2
        with pytest.raises(IntegrityError, match="fingerprint"):
            workspace.invoke("embedding", "retry", eventually, fingerprint="changed")
        assert workspace.usage()["embedding_usage_unknown"] == 1
        directory = workspace.path
        workspace.database.executemany(
            "INSERT INTO attempts(kind,tag,status) VALUES ('search',?,'failed')",
            [
                (str(index),)
                for index in range(workspace.protocol.config.limits.max_search_attempts)
            ],
        )
        workspace.database.commit()
    with Workspace(directory) as workspace, pytest.raises(ProviderError, match="budget"):
        workspace.invoke("search", "exhausted", lambda: RemoteValue(data={}))


def test_token_budget_deadline_and_unknown_cancellation_are_explicit(tmp_path, monkeypatch):
    import docgen.evaluation.state as state

    with fresh_workspace(tmp_path) as workspace:
        cap = workspace.protocol.config.limits.max_observed_embedding_tokens
        workspace.database.execute(
            "INSERT INTO attempts(kind,tag,status,tokens) "
            "VALUES ('embedding','spent','succeeded',?)",
            (cap,),
        )
        workspace.database.commit()
        with pytest.raises(ProviderError, match="budget"):
            workspace.invoke("embedding", "exhausted", lambda: RemoteValue(data={}))
        ticks = iter((0, 1000))
        with monkeypatch.context() as patch:
            patch.setattr(state.time, "monotonic", lambda: next(ticks))
            with pytest.raises(ProviderError, match="deadline"):
                workspace.invoke("search", "late", lambda: RemoteValue(data={}))

        def cancel():
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            workspace.invoke("search", "cancel", cancel)
        assert (
            workspace.database.execute("SELECT status FROM attempts WHERE tag='cancel'").fetchone()[
                0
            ]
            == "unknown"
        )


def test_retry_after_cannot_extend_the_frozen_deadline(tmp_path, monkeypatch):
    import docgen.evaluation.state as state

    monkeypatch.setattr(
        state.time, "sleep", lambda _: pytest.fail("Must stop instead of sleeping.")
    )
    with fresh_workspace(tmp_path) as workspace:

        def too_late():
            raise ProviderError(
                "throttled", "Retry later.", retryable=True, retry_after_seconds=1000
            )

        with pytest.raises(ProviderError, match="Retry later"):
            workspace.invoke("search", "late", too_late)
        assert workspace.usage()["attempts"]["search"] == 1


def test_state_database_missing_or_invalid_is_not_recreated_as_success(tmp_path):
    with fresh_workspace(tmp_path) as workspace:
        directory = workspace.path
    database = directory / "evaluation.sqlite3"
    database.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(IntegrityError, match="corrupt"):
        Workspace(directory)
    replacement = directory / "corrupt.sqlite3"
    database.rename(replacement)
    with pytest.raises(IntegrityError, match="missing"):
        Workspace(directory)
    assert not database.exists()


def test_interrupted_export_staging_is_replaced_from_confirmed_state(tmp_path):
    with fresh_workspace(tmp_path) as workspace:
        destination = workspace.path / "confirmed.json"
        temporary = temporary_path(destination)
        temporary.write_bytes(b'{"partial":')
        exported = workspace.export("confirmed.json", {"value": "confirmed"})
        assert exported.read_text(encoding="utf-8") == '{"value":"confirmed"}'
        assert not temporary.exists()
