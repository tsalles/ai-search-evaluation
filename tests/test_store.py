import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from docgen.errors import IntegrityError
from docgen.models import Usage, content_hash, serialize
from docgen.persistence import atomic_write, safe_child, temporary_path
from docgen.planning import create_plan
from docgen.store import RunStore
from tests.test_tracer import FixtureProvider, single_config


def plan_and_content() -> tuple:
    config = single_config()
    plan = create_plan(config, run_id="run-fixed", operation="generate")
    content = FixtureProvider().generate(plan.blueprints[0], config.generation)
    return plan, content


def test_accepted_content_is_immutable_and_survives_reopening(tmp_path: Path) -> None:
    plan, content = plan_and_content()
    directory = tmp_path / plan.run_id
    with RunStore.create(directory, plan) as store:
        store.accept(content)
        with pytest.raises(IntegrityError, match="immutable"):
            store.accept(content)
        store.set_status("content_ready")
    with RunStore.open(directory) as store:
        assert store.contents() == (content,)
        assert store.current_status == "content_ready"
        assert content_hash(store.contents()[0]) == content_hash(content)
    directory.rename(tmp_path / "renamed")


def test_two_processes_cannot_own_the_same_run(tmp_path: Path) -> None:
    plan, _ = plan_and_content()
    directory = tmp_path / plan.run_id
    script = (
        "import sys; from pathlib import Path; from docgen.store import RunStore; "
        "from docgen.errors import IntegrityError\n"
        "try:\n with RunStore.open(Path(sys.argv[1])): pass\n"
        "except IntegrityError:\n sys.exit(4)\n"
    )
    with RunStore.create(directory, plan):
        result = subprocess.run(
            [sys.executable, "-I", "-c", script, str(directory)],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 4, result.stderr
    with RunStore.open(directory):
        pass


@pytest.mark.parametrize("name", [
    "..", "..\\outside", "../outside", "C:\\outside", "/absolute", "con.json",
    "nul", "a:b", "trailing.", "back\\slash", "fwd/slash", "space ",
])
def test_unsafe_child_names_are_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(IntegrityError):
        safe_child(tmp_path, name)


def test_tampered_content_missing_files_and_unknown_versions_fail(tmp_path: Path) -> None:
    plan, content = plan_and_content()
    directory = tmp_path / plan.run_id
    with RunStore.create(directory, plan) as store:
        store.accept(content)
    content_path = directory / "content" / f"{content.blueprint.content_id}.json"
    original = content_path.read_bytes()
    content_path.write_bytes(original.replace(b"test-deployment", b"other-provider"))
    with pytest.raises(IntegrityError, match="checksum"):
        RunStore.open(directory)
    content_path.write_bytes(original)
    with sqlite3.connect(directory / "state.sqlite3") as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(IntegrityError, match="version"):
        RunStore.open(directory)
    with sqlite3.connect(directory / "state.sqlite3") as connection:
        connection.execute("PRAGMA user_version = 1")
    content_path.unlink()
    with pytest.raises(IntegrityError, match="missing"):
        RunStore.open(directory)


def test_tampered_plan_and_unexpected_content_are_not_adopted(tmp_path: Path) -> None:
    plan, content = plan_and_content()
    directory = tmp_path / plan.run_id
    with RunStore.create(directory, plan):
        pass
    path = directory / "content" / "unexpected.json"
    path.write_text(content.model_dump_json(), encoding="utf-8")
    with pytest.raises(IntegrityError, match="unexpected"):
        RunStore.open(directory)
    path.unlink()
    plan_path = directory / "plan.json"
    data = json.loads(plan_path.read_bytes())
    data["effective_config"]["seed"] += 1
    plan_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(IntegrityError, match="plan"):
        RunStore.open(directory)


@pytest.mark.parametrize("operation", ["fsync", "link"])
def test_failed_atomic_write_never_accepts_partial_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    plan, content = plan_and_content()
    directory = tmp_path / plan.run_id
    with RunStore.create(directory, plan) as store:
        with monkeypatch.context() as fault:
            fault.setattr(os, operation, Mock(side_effect=OSError("injected disk/access failure")))
            with pytest.raises(IntegrityError):
                store.accept(content)
        assert store.contents() == ()
    with RunStore.open(directory) as store:
        assert store.contents() == ()
        store.accept(content)
        assert store.contents() == (content,)
    assert not list((directory / "content").glob("*.tmp"))


def test_crash_after_durable_content_write_reconciles_only_expected_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, content = plan_and_content()
    directory = tmp_path / plan.run_id
    link = os.link

    def publish_then_interrupt(source: str, destination: str, **kwargs: object) -> None:
        link(source, destination)
        raise KeyboardInterrupt("simulated process interruption after publication")

    with RunStore.create(directory, plan) as store:
        with monkeypatch.context() as fault:
            fault.setattr(os, "link", publish_then_interrupt)
            with pytest.raises(KeyboardInterrupt):
                store.accept(content)
    with RunStore.open(directory) as store:
        assert store.contents() == (content,)
        assert store.item_states() == {content.blueprint.content_id: "accepted"}


def test_unresolved_attempts_become_unknown_and_remain_auditable(tmp_path: Path) -> None:
    plan, _ = plan_and_content()
    directory = tmp_path / plan.run_id
    with RunStore.create(directory, plan) as store:
        attempt = store.begin_attempt(plan.blueprints[0].content_id)
    with RunStore.open(directory) as store:
        attempts = store.attempts()
        assert len(attempts) == 1
        assert attempts[0].attempt_id == attempt
        assert attempts[0].status == "unknown"
        assert attempts[0].usage is None
        second = store.begin_attempt(plan.blueprints[0].content_id)
        store.finish_attempt(second, status="failed", error_code="timeout")
        with pytest.raises(IntegrityError):
            store.finish_attempt(second, status="succeeded")
    with RunStore.open(directory) as store:
        assert [a.status for a in store.attempts()] == ["unknown", "failed"]


def test_atomic_write_does_not_replace_an_existing_immutable_file(tmp_path: Path) -> None:
    path = tmp_path / "value.json"
    atomic_write(path, b"first")
    with pytest.raises(IntegrityError):
        atomic_write(path, b"second")
    assert path.read_bytes() == b"first"
    atomic_write(path, b"changed", overwrite=True)
    assert path.read_bytes() == b"changed"


def test_existing_run_is_not_overwritten(tmp_path: Path) -> None:
    plan, _ = plan_and_content()
    path = tmp_path / plan.run_id
    with RunStore.create(path, plan):
        pass
    original = (path / "plan.json").read_bytes()
    with pytest.raises(IntegrityError):
        RunStore.create(path, plan)
    assert (path / "plan.json").read_bytes() == original


def test_incomplete_sqlite_transaction_is_not_treated_as_accepted(tmp_path: Path) -> None:
    plan, content = plan_and_content()
    path = tmp_path / plan.run_id
    with RunStore.create(path, plan):
        pass
    with sqlite3.connect(path / "state.sqlite3") as connection:
        connection.execute("UPDATE items SET status='writing', hash=?", (content_hash(content),))
        connection.rollback()
    with RunStore.open(path) as store:
        assert store.contents() == ()


def test_closed_store_cannot_be_used_and_releases_all_handles(tmp_path: Path) -> None:
    plan, _ = plan_and_content()
    with RunStore.create(tmp_path / plan.run_id, plan) as store:
        pass
    with pytest.raises(IntegrityError, match="closed"):
        store.contents()
    with RunStore.open(tmp_path / plan.run_id) as reopened:
        assert reopened.contents() == ()


@pytest.mark.parametrize("complete", [False, True])
def test_reconcile_known_temporary_after_a_real_child_process_exit(
    tmp_path: Path, complete: bool,
) -> None:
    plan, content = plan_and_content()
    directory = tmp_path / plan.run_id
    with RunStore.create(directory, plan):
        pass
    script = (
        "import sqlite3,sys,os; from pathlib import Path; "
        "from docgen.models import Content,content_hash,serialize; "
        "from docgen.persistence import temporary_path; "
        "from tests.test_store import plan_and_content; "
        "plan,content=plan_and_content(); root=Path(sys.argv[1]); "
        "db=sqlite3.connect(root/'state.sqlite3'); "
        "db.execute(\"UPDATE items SET status='writing',hash=?\",(content_hash(content),)); "
        "db.commit(); "
        "raw=serialize(content); raw=raw if sys.argv[2]=='True' else raw[:15]; "
        "temporary_path(root/'content'/(content.blueprint.content_id+'.json')).write_bytes(raw); "
        "os._exit(19)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(directory), str(complete)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 19, result.stderr
    with RunStore.open(directory) as store:
        assert store.contents() == ((content,) if complete else ())
        if not complete:
            assert "partial_temporary_discarded" in store.events()
            store.accept(content)
        assert store.contents() == (content,)
    saved = directory / "content" / f"{content.blueprint.content_id}.json"
    assert not temporary_path(saved).exists()


@pytest.mark.parametrize("denied_update", [1, 2])
def test_sqlite_transaction_failures_reconcile_before_or_after_file_publication(
    tmp_path: Path, denied_update: int,
) -> None:
    plan, content = plan_and_content()
    directory = tmp_path / plan.run_id
    count = 0

    def authorize(action: int, table: str, column: str, *_: object) -> int:
        nonlocal count
        if action == sqlite3.SQLITE_UPDATE and table == "items" and column == "status":
            count += 1
            if count == denied_update:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    with RunStore.create(directory, plan) as store:
        store.connection.set_authorizer(authorize)
        with pytest.raises(IntegrityError, match="transaction"):
            store.accept(content)
        store.connection.set_authorizer(None)
    with RunStore.open(directory) as store:
        if denied_update == 1:
            assert store.contents() == ()
            store.accept(content)
        assert store.contents() == (content,)


def test_corrupt_expected_writing_file_is_not_adopted(tmp_path: Path) -> None:
    plan, content = plan_and_content()
    directory = tmp_path / plan.run_id
    with RunStore.create(directory, plan):
        pass
    with sqlite3.connect(directory / "state.sqlite3") as connection:
        connection.execute(
            "UPDATE items SET status='writing',hash=?", (content_hash(content),)
        )
    path = directory / "content" / f"{content.blueprint.content_id}.json"
    path.write_bytes(serialize(content) + b"tampered")
    with pytest.raises(IntegrityError, match="checksum"):
        RunStore.open(directory)
    assert path.read_bytes().endswith(b"tampered")


def test_known_attempt_usage_and_immutable_assignment(tmp_path: Path) -> None:
    plan, content = plan_and_content()
    with RunStore.create(tmp_path / plan.run_id, plan) as store:
        with pytest.raises(IntegrityError, match="incomplete"):
            store.assign_markdown()
        attempt = store.begin_attempt(content.blueprint.content_id)
        usage = Usage(input_tokens=2, output_tokens=3, total_tokens=5, reasoning_tokens=1)
        store.finish_attempt(attempt, status="succeeded", usage=usage)
        assert store.attempts()[0].usage == usage
        store.accept(content)
        with pytest.raises(IntegrityError, match="pending"):
            store.begin_attempt(content.blueprint.content_id)
        store.assign_markdown()
        store.assign_markdown()
        with store.connection:
            store.connection.execute("UPDATE assignments SET format='pdf'")
        with pytest.raises(IntegrityError, match="immutable"):
            store.assign_markdown()
    store.close()


def test_corrupt_metadata_and_unsupported_directories(tmp_path: Path) -> None:
    with pytest.raises(IntegrityError, match="missing"):
        RunStore.open(tmp_path / "missing")
    plan, _ = plan_and_content()
    path = tmp_path / plan.run_id
    with RunStore.create(path, plan) as store:
        with pytest.raises(IntegrityError, match="locked"):
            RunStore.open(path)
        with store.connection:
            store.connection.execute("DELETE FROM state")
        with pytest.raises(IntegrityError, match="status"):
            _ = store.current_status
    with pytest.raises(IntegrityError, match="plan"):
        RunStore.open(path)
    (path / "state.sqlite3").unlink()
    with pytest.raises(IntegrityError, match="missing"):
        RunStore.open(path)


@pytest.mark.parametrize("sql", [
    "UPDATE items SET status='invalid'",
    "DELETE FROM items",
    "UPDATE items SET status='writing',hash=NULL",
])
def test_corrupt_item_checkpoints_are_explicit_errors(tmp_path: Path, sql: str) -> None:
    plan, _ = plan_and_content()
    path = tmp_path / plan.run_id
    with RunStore.create(path, plan) as store:
        with store.connection:
            store.connection.execute(sql)
    with pytest.raises(IntegrityError):
        RunStore.open(path)


def test_uncheckpointed_or_invalid_canonical_file_is_not_accepted(tmp_path: Path) -> None:
    plan, content = plan_and_content()
    path = tmp_path / plan.run_id
    with RunStore.create(path, plan):
        pass
    saved = path / "content" / f"{content.blueprint.content_id}.json"
    saved.write_bytes(serialize(content))
    with pytest.raises(IntegrityError, match="Uncheckpointed"):
        RunStore.open(path)
    saved.write_bytes(b"{}")
    import hashlib

    with sqlite3.connect(path / "state.sqlite3") as connection:
        connection.execute(
            "UPDATE items SET status='accepted',hash=?", (hashlib.sha256(b"{}").hexdigest(),)
        )
    with pytest.raises(IntegrityError, match="canonical"):
        RunStore.open(path)


def test_invalid_plan_schema_and_database_are_reported(tmp_path: Path) -> None:
    plan, _ = plan_and_content()
    path = tmp_path / plan.run_id
    with RunStore.create(path, plan):
        pass
    original = (path / "plan.json").read_bytes()
    (path / "plan.json").write_bytes(b"{}")
    with pytest.raises(IntegrityError, match="schema"):
        RunStore.open(path)
    (path / "plan.json").write_bytes(original)
    (path / "state.sqlite3").write_bytes(b"not a database")
    with pytest.raises(IntegrityError, match="corrupt"):
        RunStore.open(path)
    (path / "state.sqlite3").rename(path / "corrupt.sqlite3")


def test_initialization_failure_releases_lock_and_preserves_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _ = plan_and_content()
    directory = tmp_path / plan.run_id
    with monkeypatch.context() as fault:
        fault.setattr(sqlite3, "connect", Mock(side_effect=sqlite3.OperationalError("no disk")))
        with pytest.raises(IntegrityError, match="initialize"):
            RunStore.create(directory, plan)
    assert (directory / "plan.json").is_file()
    with pytest.raises(IntegrityError, match="missing"):
        RunStore.open(directory)


def test_temporary_cleanup_failures_and_collisions_are_not_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "value.json"
    temporary = temporary_path(path)
    temporary.write_bytes(b"do not delete")
    with pytest.raises(IntegrityError):
        atomic_write(path, b"new")
    assert temporary.read_bytes() == b"do not delete"
    temporary.unlink()
    original_unlink = Path.unlink

    def deny_owned_cleanup(candidate: Path, **kwargs: object) -> None:
        if candidate == temporary:
            raise PermissionError("injected cleanup failure")
        original_unlink(candidate)

    with monkeypatch.context() as fault:
        fault.setattr(Path, "unlink", deny_owned_cleanup)
        with pytest.raises(IntegrityError, match="remove"):
            atomic_write(path, b"complete")
    assert path.read_bytes() == b"complete"
    temporary.unlink()


def test_safe_child_rejects_link_metadata_and_resolved_path_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = tmp_path / "child"
    original_is_symlink = Path.is_symlink
    with monkeypatch.context() as fault:
        fault.setattr(
            Path, "is_symlink",
            lambda path: path == child or original_is_symlink(path),
        )
        with pytest.raises(IntegrityError, match="Symlinks"):
            safe_child(tmp_path, "child")
    original_resolve = Path.resolve
    with monkeypatch.context() as fault:
        fault.setattr(
            Path, "resolve",
            lambda path, **kwargs: tmp_path.parent / "escaped" if path == child
            else original_resolve(path, **kwargs),
        )
        with pytest.raises(IntegrityError, match="escapes"):
            safe_child(tmp_path, "child")


def test_initialization_failure_after_connect_closes_windows_database_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _ = plan_and_content()
    directory = tmp_path / plan.run_id
    original_connect = sqlite3.connect

    class FailingConnection(sqlite3.Connection):
        def executescript(self, script: str) -> sqlite3.Cursor:
            super().executescript(script)
            raise sqlite3.OperationalError("injected initialization failure")

    def connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        return original_connect(*args, **kwargs, factory=FailingConnection)

    with monkeypatch.context() as fault:
        fault.setattr(sqlite3, "connect", connect)
        with pytest.raises(IntegrityError, match="initialize"):
            RunStore.create(directory, plan)
    (directory / "state.sqlite3").rename(directory / "failed.sqlite3")


def test_semantically_invalid_plan_is_rejected_even_with_a_matching_file_hash(
    tmp_path: Path,
) -> None:
    import hashlib

    plan, _ = plan_and_content()
    directory = tmp_path / plan.run_id
    with RunStore.create(directory, plan):
        pass
    path = directory / "plan.json"
    data = json.loads(path.read_bytes())
    data["semantic_fingerprint"] = "0" * 64
    raw = json.dumps(data).encode()
    path.write_bytes(raw)
    with sqlite3.connect(directory / "state.sqlite3") as connection:
        connection.execute(
            "UPDATE state SET plan_hash=?", (hashlib.sha256(raw).hexdigest(),)
        )
    with pytest.raises(IntegrityError, match="semantic"):
        RunStore.open(directory)


def test_accepted_blueprint_mismatch_is_rejected_even_with_matching_content_hash(
    tmp_path: Path,
) -> None:
    plan, content = plan_and_content()
    directory = tmp_path / plan.run_id
    with RunStore.create(directory, plan) as store:
        store.accept(content)
    data = content.model_dump()
    data["blueprint"]["audience"] = "different audience"
    from docgen.models import Content

    changed = Content.model_validate(data)
    (directory / "content" / f"{content.blueprint.content_id}.json").write_bytes(serialize(changed))
    with sqlite3.connect(directory / "state.sqlite3") as connection:
        connection.execute("UPDATE items SET hash=?", (content_hash(changed),))
    with pytest.raises(IntegrityError, match="blueprint"):
        RunStore.open(directory)


def test_unknown_temporary_content_is_preserved_instead_of_deleted(tmp_path: Path) -> None:
    plan, content = plan_and_content()
    directory = tmp_path / plan.run_id
    with RunStore.create(directory, plan) as store:
        store.accept(content)
    temporary = temporary_path(directory / "content" / f"{content.blueprint.content_id}.json")
    temporary.write_bytes(b"unexpected bytes")
    with pytest.raises(IntegrityError, match="temporary checksum"):
        RunStore.open(directory)
    assert temporary.read_bytes() == b"unexpected bytes"


def test_store_rejects_a_canonical_candidate_with_the_wrong_planned_topic(tmp_path: Path) -> None:
    plan, content = plan_and_content()
    incorrect = content.model_copy(update={
        "blueprint": content.blueprint.model_copy(update={"topic_id": "unplanned-topic"}),
    })
    with RunStore.create(tmp_path / plan.run_id, plan) as store:
        with pytest.raises(IntegrityError, match="blueprint"):
            store.accept(incorrect)
        assert store.contents() == ()
        assert list((store.directory / "content").iterdir()) == []
