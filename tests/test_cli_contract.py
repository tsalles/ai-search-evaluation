import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from docgen.cli import main
from docgen.models import Blueprint
from tests.fixtures.factories import content_wire, diverse_content
from tests.test_azure_provider import SETTINGS, ExpiringCredential, response
from tests.test_generate_phase import batch_config


def install_transport(monkeypatch: pytest.MonkeyPatch, *, fail: bool = False) -> list:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if fail:
            return httpx.Response(401, json={"error": {"message": "sentinel-secret"}})
        context = json.loads(json.loads(request.content)["input"].split("Context:\n", 1)[1])
        blueprint = Blueprint.model_validate(context["blueprint"])
        payload = response()
        payload["output"][0]["content"][0]["text"] = json.dumps(
            content_wire(diverse_content(blueprint))
        )
        return httpx.Response(200, json=payload)

    class SimulatedClient(httpx.Client):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(
        "docgen.providers.azure.DefaultAzureCredential", lambda **kwargs: ExpiringCredential()
    )
    monkeypatch.setattr("docgen.providers.azure.httpx.Client", SimulatedClient)
    return calls


def configuration_file(tmp_path: Path) -> Path:
    data = batch_config(2, concurrency=1).model_dump(mode="json")
    data["generation"]["provider"] = SETTINGS.model_dump(mode="json")
    path = tmp_path / "config.json"
    # User configuration uses numeric shares, unlike canonical persisted Decimal strings.
    for name in ("genre_weights", "length_weights"):
        data["generation"][name] = {
            key: float(value) for key, value in data["generation"][name].items()
        }
    data["generation"]["quality"]["near_duplicate_jaccard"] = 0.85
    data["generation"]["quality"]["language_confidence_min"] = 0.9
    data["rendering"]["weights"] = {"md": 1}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_all_cli_phases_use_real_sdk_boundary_and_persistent_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = install_transport(monkeypatch)
    config = configuration_file(tmp_path)
    output = tmp_path / "runs"
    assert main(["generate", "--config", str(config), "--output", str(output), "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "content_ready"
    directory = output / first["run_id"]
    assert len(calls) == 2
    assert (
        main(
            [
                "plan",
                "--config",
                str(config),
                "--phase",
                "render",
                "--run",
                str(directory),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "planned"
    assert not (directory / "allocation.json").exists()
    assert main(["render", "--config", str(config), "--run", str(directory), "--json"]) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["status"] == "complete"
    assert rendered["details"]["review"]["status"] == "human_review_pending"
    assert main(["resume", "--run", str(directory), "--json"]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["status"] == "complete"
    assert resumed["details"]["review"] == rendered["details"]["review"]
    assert main(["validate", "--run", str(directory), "--json"]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["status"] == "valid"
    assert validated["details"]["review"] == rendered["details"]["review"]
    assert len(calls) == 2
    assert main(["run", "--config", str(config), "--output", str(output), "--json"]) == 0
    combined = json.loads(capsys.readouterr().out)
    assert combined["status"] == "complete"
    saved = json.loads(Path(combined["reports"]["run_summary"]).read_text(encoding="utf-8"))
    assert saved["operation"] == combined["operation"] == "run"
    assert saved["usage"] == combined["usage"]
    assert set(combined) >= {
        "schema_version",
        "run_id",
        "operation",
        "status",
        "requested_count",
        "accepted_count",
        "verified_document_count",
        "format_counts",
        "failures",
        "usage",
        "reports",
        "corpus_path",
        "details",
    }


@pytest.mark.parametrize(
    "arguments",
    [
        ["unknown-command", "--json"],
        ["generate", "--json"],
        ["resume", "--run", "missing", "--max-requests", "-1", "--json"],
        ["plan", "--config", "missing", "--json"],
        ["generate", "--api-key", "sentinel-secret", "--json"],
    ],
)
def test_cli_input_errors_are_one_safe_json_object(
    arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(arguments) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "invalid_input"
    assert "sentinel-secret" not in captured.out + captured.err
    assert "Traceback" not in captured.err


def test_cli_provider_failure_and_integrity_have_distinct_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_transport(monkeypatch, fail=True)
    config = configuration_file(tmp_path)
    assert (
        main(["generate", "--config", str(config), "--output", str(tmp_path / "runs"), "--json"])
        == 3
    )
    failed = capsys.readouterr()
    assert json.loads(failed.out)["status"] == "incomplete"
    assert "sentinel-secret" not in failed.out + failed.err
    assert main(["validate", "--run", str(tmp_path / "absent"), "--json"]) == 4
    assert json.loads(capsys.readouterr().out)["status"] == "integrity_error"
