import json
import os
import socket
from collections import Counter
from pathlib import Path

import pytest

from docgen.budgets import BudgetOverride
from docgen.config import load_config
from docgen.models import content_hash
from docgen.pipeline import generate, render, resume, validate
from docgen.store import RunStore

pytestmark = pytest.mark.live


def test_twelve_document_live_pilot_preserves_content_and_renders_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Path(__file__).resolve().parents[2]
    config = load_config(project / "examples" / "banking.yaml")
    output = Path(os.environ.get("DOCGEN_PILOT_OUTPUT", str(project / "runs")))
    existing = os.environ.get("DOCGEN_PILOT_RUN")
    if existing:
        directory = Path(existing)
        value = os.environ.get("DOCGEN_PILOT_MAX_CANDIDATES")
        override = BudgetOverride(max_candidates_per_item=int(value)) if value else None
        generated = resume(directory, budget_override=override)
    else:
        generated = generate(config, output)
        directory = output / generated.run_id
    print(generated.model_dump_json())
    assert generated.status in {"content_ready", "complete"}, generated
    with RunStore.open(directory) as store:
        before = {item.blueprint.content_id: content_hash(item) for item in store.contents()}

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Phase 2 and validation must not call Azure or the network.")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("docgen.providers.azure.DefaultAzureCredential", forbidden)
    assert config.rendering is not None
    rendered = render(directory, config.rendering)
    print(rendered.model_dump_json())
    assert rendered.status == "complete", rendered
    assert rendered.corpus_path is not None
    assert Counter(file.suffix for file in rendered.corpus_path.iterdir()) == {
        ".pdf": 3,
        ".docx": 3,
        ".xlsx": 2,
        ".pptx": 2,
        ".html": 1,
        ".md": 1,
    }
    assert len(list(rendered.corpus_path.iterdir())) == 12
    assert validate(directory).status == "valid"
    with RunStore.open(directory) as store:
        assert {
            item.blueprint.content_id: content_hash(item) for item in store.contents()
        } == before
    (output / "pilot-latest.json").write_text(
        json.dumps(
            {
                "run_id": rendered.run_id,
                "run_directory": str(directory),
                "corpus": str(rendered.corpus_path),
                "usage": generated.usage,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
