import os
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from docgen.config import RenderConfig
from docgen.errors import InputError, IntegrityError
from docgen.models import content_hash
from docgen.pipeline import generate, render
from docgen.rendering import render_content
from docgen.store import RunStore
from tests.test_generate_phase import BatchProvider, batch_config


def mix() -> RenderConfig:
    return RenderConfig.model_validate(
        {
            "weights": {
                "pdf": 0.25,
                "docx": 0.25,
                "xlsx": 0.15,
                "pptx": 0.15,
                "html": 0.1,
                "md": 0.1,
            }
        }
    )


def test_offline_phase_two_publishes_exactly_n_unique_native_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = BatchProvider()
    generated = generate(batch_config(12), tmp_path, provider=source)
    assert generated.status == "content_ready"
    path = tmp_path / generated.run_id
    with RunStore.open(path) as store:
        hashes = {item.blueprint.content_id: content_hash(item) for item in store.contents()}
    monkeypatch.setattr(
        "docgen.providers.azure.DefaultAzureCredential",
        lambda **kwargs: pytest.fail("Rendering must not acquire Azure credentials."),
    )
    result = render(path, mix())
    assert result.status == "complete", result
    assert result.verified_document_count == 12
    review = result.details["review"]
    assert review["status"] == "human_review_pending"
    assert review["reviewer"] is None
    assert review["sample_count"] == 6
    assert {item["format"] for item in review["sample"]} == {
        "pdf", "docx", "xlsx", "pptx", "html", "md",
    }
    assert len(source.calls) == 12
    assert Counter(file.suffix for file in result.corpus_path.iterdir()) == {
        ".pdf": 3,
        ".docx": 3,
        ".xlsx": 2,
        ".pptx": 2,
        ".html": 1,
        ".md": 1,
    }
    assert not (path / "artifacts.pending").exists()
    assert (path / "ready-manifest.json").is_file()
    with RunStore.open(path) as store:
        assert {
            item.blueprint.content_id: content_hash(item) for item in store.contents()
        } == hashes


@pytest.mark.parametrize("after", [False, True])
def test_atomic_publication_interruptions_resume_without_regenerating_verified_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    after: bool,
) -> None:
    generated = generate(batch_config(2), tmp_path, provider=BatchProvider())
    path = tmp_path / generated.run_id
    rename = os.rename

    def interrupt(source, target, **kwargs) -> None:
        if after:
            rename(source, target)
        raise KeyboardInterrupt("publication boundary")

    with monkeypatch.context() as fault:
        fault.setattr(os, "rename", interrupt)
        result = render(path, RenderConfig(weights={"md": 1}))
        assert result.status == "cancelled"
    directory = path / ("corpus" if after else "artifacts.pending")
    before = {file.name: file.read_bytes() for file in directory.iterdir()}
    result = render(path, RenderConfig(weights={"md": 1}))
    assert result.status == "complete"
    assert {file.name: file.read_bytes() for file in result.corpus_path.iterdir()} == before


def test_verified_corruption_and_changed_mix_are_never_silently_replaced(tmp_path: Path) -> None:
    generated = generate(batch_config(1), tmp_path, provider=BatchProvider())
    path = tmp_path / generated.run_id
    result = render(path, RenderConfig(weights={"md": 1}))
    with pytest.raises(InputError, match="immutable"):
        render(path, RenderConfig(weights={"pdf": 1}))
    (artifact,) = result.corpus_path.iterdir()
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(IntegrityError):
        render(path, RenderConfig(weights={"md": 1}))
    assert artifact.read_bytes().endswith(b"tampered")


def test_uncheckpointed_extra_files_block_publication(tmp_path: Path) -> None:
    generated = generate(batch_config(1), tmp_path, provider=BatchProvider())
    path = tmp_path / generated.run_id
    pending = path / "artifacts.pending"
    pending.mkdir()
    unexpected = pending / "answer-key.json"
    unexpected.write_text("{}", encoding="utf-8")
    with pytest.raises(IntegrityError, match="unexpected"):
        render(path, RenderConfig(weights={"md": 1}))
    assert unexpected.exists()
    assert not (path / "corpus").exists()


def test_valid_artifact_between_file_and_database_commit_is_adopted_on_resume(
    tmp_path: Path,
) -> None:
    generated = generate(batch_config(1), tmp_path, provider=BatchProvider())
    path = tmp_path / generated.run_id

    def authorize(action: int, table: str, column: str, *_: object) -> int:
        if action == sqlite3.SQLITE_UPDATE and table == "rendered_artifacts" and column == "status":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    with RunStore.open(path) as store:
        store.connection.set_authorizer(authorize)
        with pytest.raises(IntegrityError):
            render_content(store, RenderConfig(weights={"md": 1}))
        store.connection.set_authorizer(None)
    (artifact,) = (path / "artifacts.pending").iterdir()
    raw = artifact.read_bytes()
    result = render(path, RenderConfig(weights={"md": 1}))
    assert result.status == "complete"
    assert (result.corpus_path / artifact.name).read_bytes() == raw


def test_artifact_ledger_and_ready_manifest_are_integrity_checked(tmp_path: Path) -> None:
    generated = generate(batch_config(1), tmp_path, provider=BatchProvider())
    path = tmp_path / generated.run_id
    render(path, RenderConfig(weights={"md": 1}))
    with RunStore.open(path) as store:
        with pytest.raises(IntegrityError, match="unallocated"):
            store.start_artifact("unknown-item")
        with pytest.raises(IntegrityError, match="immutable"):
            store.start_artifact("item-000001")
        with store.connection:
            store.connection.execute("UPDATE rendered_artifacts SET validation=NULL")
        with pytest.raises(IntegrityError, match="checkpoints"):
            store.rendered_states()
    with pytest.raises(IntegrityError):
        render(path, RenderConfig(weights={"md": 1}))


def test_corrupted_ready_manifest_is_not_rebuilt_over_evidence(tmp_path: Path) -> None:
    generated = generate(batch_config(1), tmp_path, provider=BatchProvider())
    path = tmp_path / generated.run_id
    render(path, RenderConfig(weights={"md": 1}))
    ready = path / "ready-manifest.json"
    ready.write_bytes(ready.read_bytes() + b"bad")
    with pytest.raises(IntegrityError, match="manifest"):
        render(path, RenderConfig(weights={"md": 1}))
    assert ready.read_bytes().endswith(b"bad")
