import json
import re
import shutil
import subprocess
from collections import Counter
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
        Path("evaluations") / "example" / "report.json",
        Path("evaluations") / "local-notes.md",
        Path("study-assets") / "producers" / "study.py",
        Path("study-assets") / "frozen-evidence" / "report.json",
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
        Path("evaluations") / "README.md",
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


def test_evaluations_index_matches_the_cleared_release_manifest() -> None:
    project = Path(__file__).resolve().parents[1]
    manifest = json.loads((project / "results" / "asset-manifest.json").read_text(encoding="utf-8"))
    document = (project / "evaluations" / "README.md").read_text(encoding="utf-8")
    counts: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    archives: dict[str, set[str]] = {}
    for entry in manifest["files"]:
        parts = entry["path"].split("/")
        if parts[0] != "evaluations":
            continue
        group = parts[1] if len(parts) > 2 else "(root configurations)"
        counts[group] += 1
        sizes[group] += entry["bytes"]
        archives.setdefault(group, set()).add(entry["archive"])
    expected = {group: (counts[group], sizes[group], archives[group]) for group in counts}
    rows = re.findall(
        r"^\| `([^`]+)` \| ([\d,]+) \| ([\d,]+) \| (.+) \|$", document, flags=re.MULTILINE,
    )
    actual = {
        group: (
            int(count.replace(",", "")),
            int(size.replace(",", "")),
            {
                f"experiments-{number}.zip"
                for number in re.findall(r"\[(\d{3})\]\[archive-\d{3}\]", links)
            },
        )
        for group, count, size, links in rows
    }
    assert len(rows) == len(expected)
    assert actual == expected
    for archive in manifest["archives"]:
        number = archive["name"].removeprefix("experiments-").removesuffix(".zip")
        assert f"[archive-{number}]: {archive['url']}" in document
