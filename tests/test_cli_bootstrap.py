import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("option", ["--help", "--version"])
def test_cli_information_requires_no_credentials_or_output(option: str, tmp_path: Path) -> None:
    env = {key: value for key, value in os.environ.items() if not key.startswith("AZURE")}
    result = subprocess.run(
        [sys.executable, "-m", "docgen", option],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "docgen" in result.stdout.lower()
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_unknown_command_is_input_error(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "docgen", "unknown-command"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_offline_suite_blocks_network() -> None:
    with pytest.raises(AssertionError, match="forbidden"):
        socket.create_connection(("example.invalid", 443))


def test_paid_test_cannot_run_without_explicit_authorization() -> None:
    project = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTEST_ADDOPTS": ""}
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", str(project / "tests" / "live"),
            "-m", "live", "-q", "--tb=short",
        ],
        cwd=project, env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "Paid live tests require explicit --allow-live authorization." in result.stdout
