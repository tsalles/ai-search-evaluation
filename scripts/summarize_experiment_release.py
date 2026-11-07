"""Create a small numerical review projection from a verified local release archive."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path

from public_asset_release import ReleaseError, safe_name, sha256

SOURCE = "evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/decision-analysis.json"


def create_review_report(manifest: Path, cache: Path, output: Path) -> None:
    if output.exists() or output.is_symlink() or output.is_junction():
        raise ReleaseError("review report must use a new destination")
    release = json.loads(manifest.read_text(encoding="utf-8"))
    if release.get("status") != "verified_local_derivative":
        raise ReleaseError("review source release has not been verified")
    matches = [entry for entry in release["files"] if entry["path"] == SOURCE]
    if len(matches) != 1:
        raise ReleaseError("review source must have exactly one manifest entry")
    entry = matches[0]
    name = safe_name(entry["archive"])
    if not re.fullmatch(r"experiments-\d{3}\.zip", name):
        raise ReleaseError("unexpected review archive name")
    if cache.is_symlink() or cache.is_junction():
        raise ReleaseError("linked review cache")
    archive_path = cache / name
    if archive_path.is_symlink() or archive_path.is_junction():
        raise ReleaseError("linked review archive")
    with zipfile.ZipFile(archive_path) as archive:
        data = archive.read(safe_name(SOURCE))
    if len(data) != entry["bytes"] or sha256(data) != entry["sha256"]:
        raise ReleaseError("review source checksum mismatch")
    results = json.loads(data)
    if not isinstance(results, dict) or not isinstance(results.get("source_readback"), dict):
        raise ReleaseError("unexpected numerical summary structure")
    omitted = ("cases", "document_feature_donor")
    if any(key not in results["source_readback"] for key in omitted):
        raise ReleaseError("unexpected source-readback structure")
    results["source_readback"] = {
        key: value for key, value in results["source_readback"].items() if key not in omitted
    }
    report = {
        "schema_version": 1,
        "status": "verified_local_review_projection",
        "source_path": SOURCE,
        "public_source_sha256": entry["sha256"],
        "archive": name,
        "scope": "Aggregate study results copied without recomputing numerical values. "
        "Bulky source-readback records are omitted only from this review projection; "
        "the complete original public artifact remains in the release archive.",
        "omitted_fields": ["source_readback/" + key for key in omitted],
        "historical_seal_semantics": release["historical_seal_semantics"],
        "producer_version_caveat": release["producer_version_caveat"],
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("results") / "asset-manifest.json")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("results") / "decision-study-summary.json"
    )
    args = parser.parse_args()
    create_review_report(args.manifest, args.cache, args.output)


if __name__ == "__main__":
    main()
