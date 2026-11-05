import os
import shutil
import subprocess
import sys
import tarfile
import venv
from pathlib import Path

import pytest


def test_source_distribution_excludes_unrelated_operator_outputs(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[1]
    source = tmp_path / "source"
    source.mkdir()
    for name in ("README.md", "pyproject.toml"):
        shutil.copy2(project / name, source / name)
    shutil.copytree(project / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__"))
    for directory in ("qa-output", "operator-selected-output"):
        target = source / directory
        target.mkdir()
        (target / "private-run-sentinel.txt").write_text(
            "Packaging exclusion fixture.", encoding="utf-8"
        )
    output = tmp_path / "dist"
    built = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--sdist",
            "--no-isolation",
            "--outdir",
            str(output),
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    (archive_path,) = output.glob("*.tar.gz")
    with tarfile.open(archive_path) as archive:
        names = archive.getnames()
    assert any(name.endswith("src/docgen/pipeline.py") for name in names)
    assert not any("private-run-sentinel" in name for name in names)


def test_wheel_installs_and_runs_in_a_clean_environment(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[1]
    wheels = tmp_path / "wheels"
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(wheels),
            str(project),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    (wheel,) = wheels.glob("*.whl")
    environment = tmp_path / "installed"
    venv.EnvBuilder(with_pip=True).create(environment)
    executable = environment / ("Scripts" if os.name == "nt" else "bin") / "python.exe"
    if os.name != "nt":
        executable = executable.with_name("python")
    install = subprocess.run(
        [
            str(executable),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--disable-pip-version-check",
            str(wheel),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert install.returncode == 0, install.stderr
    result = subprocess.run(
        [str(executable), "-I", "-m", "docgen", "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "docgen 0.1.0"
    assert "Traceback" not in result.stderr
    for arguments in (["--help"], ["experiment", "collect", "--help"],
                      ["experiment", "score", "--help"]):
        help_result = subprocess.run(
            [str(executable), "-I", "-m", "docgen", *arguments],
            cwd=tmp_path, capture_output=True, text=True, check=False,
        )
        assert help_result.returncode == 0, help_result.stderr
        assert "usage: docgen" in help_result.stdout
        if len(arguments) > 1:
            assert "semantic-bm25" in help_result.stdout
        assert "Traceback" not in help_result.stderr


@pytest.mark.parametrize("entrypoint", ["docgen"])
def test_console_entrypoint_is_installed(entrypoint: str) -> None:
    scripts = Path(sys.executable).parent
    executable = scripts / (f"{entrypoint}.exe" if os.name == "nt" else entrypoint)
    result = subprocess.run(
        [str(executable), "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "usage: docgen" in result.stdout
