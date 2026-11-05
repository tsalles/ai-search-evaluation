import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from docgen.cli import main
from docgen.errors import InputError
from docgen.evaluation.azure import Azure
from docgen.evaluation.corpus import generate_sources, source_run
from docgen.evaluation.state import Workspace
from tests.evaluation.azure_double import Credential
from tests.evaluation.fixtures import experiment_config, fresh_workspace
from tests.evaluation.test_azure import azure_fixture


def test_example_plan_is_no_write_and_init_creates_exclusive_fresh_state(
    tmp_path,
    monkeypatch,
    capsys,
):
    root = Path(__file__).parents[2]
    monkeypatch.chdir(tmp_path)
    config = root / "examples" / "retrieval-experiment.yaml"
    assert main(["experiment", "plan", "--config", str(config), "--json"]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["operation"] == "experiment:plan" and planned["status"] == "planned"
    assert planned["details"]["expected_primary_query_requests"] == 48
    assert planned["details"]["expected_shared_test_embeddings"] == 24
    assert planned["details"]["human_review_required"]
    assert not list(tmp_path.iterdir())
    output = tmp_path / "evaluations"
    assert (
        main(
            [
                "experiment",
                "init",
                "--config",
                str(config),
                "--output",
                str(output),
                "--json",
            ]
        )
        == 0
    )
    initialized = json.loads(capsys.readouterr().out)
    directory = Path(initialized["details"]["experiment_path"])
    with Workspace(directory) as workspace:
        assert workspace.protocol.config.family_count == 2
        assert not source_run(workspace).exists()
    assert main(["experiment", "status", "--experiment", str(directory), "--json"]) == 0
    assert not json.loads(capsys.readouterr().out)["details"]["reference_released"]


@pytest.mark.parametrize(
    "phase,extra",
    [
        ("generate", []),
        ("prepare", []),
        ("ingest", []),
        ("snapshot", ["--arm", "de_split"]),
        ("collect", []),
    ],
)
def test_every_paid_or_cloud_phase_requires_live_before_credentials(
    phase,
    extra,
    staged_workspace,
    monkeypatch,
    capsys,
):
    import docgen.evaluation.cli as cli

    directory = staged_workspace.path
    staged_workspace.close()

    def forbidden(*args, **kwargs):
        raise AssertionError("Credentials/network clients must not be constructed without --live.")

    monkeypatch.setattr(cli, "Azure", forbidden)
    monkeypatch.setattr(cli, "AzureCliCredential", forbidden)
    assert main(["experiment", phase, "--experiment", str(directory), *extra, "--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "invalid_input"
    assert "--live" in result["failures"][0]["message"]


def test_library_generation_cannot_implicitly_make_paid_requests(tmp_path):
    with fresh_workspace(tmp_path) as workspace:
        with pytest.raises(InputError, match="--live"):
            generate_sources(workspace)
        assert not source_run(workspace).exists()


def test_explicit_generation_credential_is_wired_to_the_existing_provider(tmp_path, monkeypatch):
    import docgen.generation as generation

    observed = []
    credential = Credential()

    def stopped_provider(config, **kwargs):
        observed.append(kwargs["credential"])
        raise InputError("Offline provider-construction checkpoint.")

    monkeypatch.setattr(generation, "AzureProvider", stopped_provider)
    with fresh_workspace(tmp_path) as workspace:
        config = workspace.protocol.generation_config.generation
        if config.provider is None:
            pytest.fail("The configured provider fixture is required for credential wiring.")
        with pytest.raises(InputError, match="checkpoint"):
            generate_sources(workspace, credential=credential, live=True)
    assert observed == [credential]


def test_cli_cloud_to_offline_report_uses_real_boundaries_without_live_services(
    staged_workspace,
    monkeypatch,
    capsys,
):
    import tiktoken

    import docgen.evaluation.cli as cli

    workspace = staged_workspace
    directory = workspace.path
    unused, backend, blobs, _ = azure_fixture(workspace)
    unused.close()
    protocol = workspace.protocol
    workspace.close()

    def client_factory(selected):
        assert selected == protocol
        return Azure(
            selected,
            credential=Credential(),
            blob_transport=blobs,
            http_client=httpx.Client(transport=httpx.MockTransport(backend)),
        )

    monkeypatch.setattr(cli, "Azure", client_factory)
    monkeypatch.setattr(
        tiktoken,
        "get_encoding",
        lambda _: SimpleNamespace(
            encode=lambda text, **kwargs: list(range(25)),
        ),
    )
    for phase, extra in (
        ("reference-build", []),
        ("reference-validate", ["--for-release"]),
        ("release", []),
        ("prepare", ["--live"]),
        ("ingest", ["--live"]),
        ("snapshot", ["--arm", "de_split", "--live"]),
        ("snapshot", ["--arm", "content_understanding", "--live"]),
        ("collect", ["--live"]),
        ("score", []),
        ("status", []),
    ):
        code = main(["experiment", phase, "--experiment", str(directory), *extra, "--json"])
        result = json.loads(capsys.readouterr().out)
        assert code == 0, (phase, result)
        assert result["status"] in {"ready", "valid", "complete"}
    report = json.loads((directory / "report-test.json").read_text(encoding="utf-8"))
    assert report["denominators"]["arm_query_responses"] == 48
    assert report["paired"]["ndcg_at_10"]["cu_minus_de"] == 0


def test_cli_reports_provider_failure_without_leaking_remote_body(
    staged_workspace,
    monkeypatch,
    capsys,
):
    import docgen.evaluation.cli as cli

    workspace = staged_workspace
    unused, backend, blobs, _ = azure_fixture(workspace)
    unused.close()
    directory, protocol = workspace.path, workspace.protocol
    workspace.close()
    backend.failures["datasources/" + protocol.resource_name("de_split", "source")] = 403
    monkeypatch.setattr(
        cli,
        "Azure",
        lambda selected: Azure(
            selected,
            credential=Credential(),
            blob_transport=blobs,
            http_client=httpx.Client(transport=httpx.MockTransport(backend)),
        ),
    )
    assert (
        main(
            [
                "experiment",
                "prepare",
                "--experiment",
                str(directory),
                "--live",
                "--json",
            ]
        )
        == 3
    )
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "incomplete" and result["failures"][0]["code"] == "authorization"
    assert "sentinel-sensitive" not in captured.out + captured.err


def test_invalid_config_and_incomplete_review_are_explicit_json_errors(tmp_path, capsys):
    path = tmp_path / "bad.yaml"
    path.write_text("family_count: 2\nfamily_count: 3\n", encoding="utf-8")
    assert main(["experiment", "plan", "--config", str(path), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid_input"
    config = experiment_config()
    assert config.family_count == 2
    assert (
        main(
            [
                "experiment",
                "review",
                "--experiment",
                str(tmp_path),
                "--intent",
                "family-0001-fee",
                "--reviewer",
                "Name",
                "--json",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["failures"][0]["code"] == "invalid_arguments"
