import shutil
import subprocess
from pathlib import Path

import pytest


def test_public_git_excludes_local_exports_and_sensitive_artifacts(tmp_path: Path) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git is required to verify public-repository exclusions.")
    project = Path(__file__).resolve().parents[1]
    shutil.copyfile(project / ".gitignore", tmp_path / ".gitignore")
    subprocess.run(
        [git, "init", "--template="], cwd=tmp_path, check=True, capture_output=True, text=True,
    )
    excluded = [
        Path(".azure") / "infrastructure-plan.json",
        Path(".azure") / "deployment-plan.md",
        Path("infra") / "main.json",
        Path("infra") / "saas-confirmation" / "main.json",
        Path("services") / "section-skill" / "infra" / "main.json",
        Path("services") / "section-skill" / "local.settings.json",
        Path("runs") / "example" / "manifest.json",
        Path("evaluations") / "example" / "state.sqlite3",
        Path(".env"),
        Path("secrets.env"),
        Path("private.pem"),
        Path("private.key"),
        Path("private.pfx"),
        Path("private.p12"),
        Path("customer.pptx"),
        Path("customer.docx"),
        Path("customer.xlsx"),
        Path("customer.pdf"),
        Path("local.db"),
    ]
    included = [
        Path("ai_search_resources") / "datasource.json",
        Path("examples") / "storage.env.example",
        Path("infra") / "saas-confirmation" / "main.bicep",
        Path("services") / "section-skill" / "infra" / "abbreviations.json",
        Path("services") / "section-skill" / "infra" / "main.parameters.json",
    ]
    for paths, expected in ((excluded, 0), (included, 1)):
        for path in paths:
            result = subprocess.run(
                [
                    git, "-c", "core.excludesFile=", "check-ignore", "--quiet",
                    "--no-index", "--", str(path),
                ],
                cwd=tmp_path, check=False, capture_output=True, text=True,
            )
            assert result.returncode == expected, f"{path}: {result.stderr}"
