"""Verify or explicitly download and safely extract the experimental release."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Any

from public_asset_release import MAX_ARCHIVE_BYTES, ReleaseError, file_hash, safe_name

RELEASE_BASE = (
    "https://github.com/tsalles/ai-search-evaluation/releases/download/v0.1.0-experiments/"
)


def verify_archive(path: Path, archive: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    if path.stat().st_size != archive["bytes"] or file_hash(path) != archive["sha256"]:
        raise ReleaseError("archive checksum mismatch")
    expected = {entry["path"]: entry for entry in entries}
    if len(expected) != len(entries):
        raise ReleaseError("duplicate manifest path")
    with zipfile.ZipFile(path) as source:
        seen: set[str] = set()
        for member in source.infolist():
            name = safe_name(member.filename)
            if member.is_dir() or stat.S_ISLNK(member.external_attr >> 16) or member.flag_bits & 1:
                raise ReleaseError("nonregular/encrypted archive member")
            if name not in expected or name.casefold() in seen:
                raise ReleaseError("unexpected or duplicate archive member")
            seen.add(name.casefold())
            entry = expected[name]
            if member.file_size != entry["bytes"]:
                raise ReleaseError("member size mismatch")
            digest = hashlib.sha256()
            with source.open(member) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != entry["sha256"]:
                raise ReleaseError("member checksum mismatch")
        if seen != {name.casefold() for name in expected}:
            raise ReleaseError("missing archive member")


def extract_archive(path: Path, root: Path, entries: list[dict[str, Any]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or root.is_junction():
        raise ReleaseError("linked extraction root")
    root = root.resolve()
    with zipfile.ZipFile(path) as archive:
        for entry in entries:
            name = safe_name(entry["path"])
            target = root.joinpath(*PurePosixPath(name).parts)
            parent = target.parent
            while parent != root:
                if parent.exists() and (
                    parent.is_symlink() or parent.is_junction() or parent.resolve() != parent
                ):
                    raise ReleaseError("linked extraction parent")
                parent = parent.parent
            if target.exists():
                raise ReleaseError("refusing to overwrite existing extraction member")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
            if file_hash(target) != entry["sha256"]:
                raise ReleaseError("extracted checksum mismatch")


def release_assets(
    manifest: Path, cache: Path, *, download: bool, extract: Path | None, workers: int = 1
) -> None:
    if not 1 <= workers <= 4:
        raise ReleaseError("archive workers must be between one and four")
    value = json.loads(manifest.read_text(encoding="utf-8"))
    if value.get("status") != "verified_local_derivative":
        raise ReleaseError("manifest is not cleared for release")
    files = value["files"]
    archive_names = {archive["name"] for archive in value["archives"]}
    if not files or not archive_names:
        raise ReleaseError("empty release manifest")
    if len({name.casefold() for name in archive_names}) != len(value["archives"]):
        raise ReleaseError("duplicate release archive")
    if any(entry["archive"] not in archive_names for entry in files):
        raise ReleaseError("inaccurate archive mapping")
    seen_paths: set[str] = set()
    for entry in files:
        name = safe_name(entry["path"]).casefold()
        if name in seen_paths:
            raise ReleaseError("duplicate global manifest path")
        seen_paths.add(name)
    cache.mkdir(parents=True, exist_ok=True)
    if cache.is_symlink() or cache.is_junction():
        raise ReleaseError("linked archive cache")
    selected: list[tuple[Path, dict[str, Any], list[dict[str, Any]]]] = []
    for archive in value["archives"]:
        name = safe_name(archive["name"])
        if (
            not re.fullmatch(r"experiments-\d{3}\.zip", name)
            or archive["url"] != RELEASE_BASE + name
        ):
            raise ReleaseError("unexpected release URL")
        if (
            not isinstance(archive["bytes"], int)
            or not 0 < archive["bytes"] < MAX_ARCHIVE_BYTES
            or not re.fullmatch(r"[0-9a-f]{64}", archive["sha256"])
        ):
            raise ReleaseError("invalid release archive size/checksum")
        path = cache / name
        if path.is_symlink() or path.is_junction():
            raise ReleaseError("linked cached archive")
        if not path.exists() and download:
            partial = cache / (name + ".partial")
            if partial.exists() or partial.is_symlink() or partial.is_junction():
                raise ReleaseError("refusing to replace existing partial download")
            try:
                with urllib.request.urlopen(archive["url"], timeout=60) as source:
                    with partial.open("xb") as destination:
                        total = 0
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            total += len(block)
                            if total > archive["bytes"]:
                                raise ReleaseError("download exceeds declared size")
                            destination.write(block)
                if partial.stat().st_size != archive["bytes"]:
                    raise ReleaseError("incomplete download")
                if file_hash(partial) != archive["sha256"]:
                    raise ReleaseError("download checksum mismatch")
                partial.rename(path)
            finally:
                partial.unlink(missing_ok=True)
        if not path.exists():
            raise ReleaseError("archive unavailable locally; download requires --download")
        entries = [entry for entry in files if entry["archive"] == name]
        if len(entries) != archive["files"]:
            raise ReleaseError("archive file count mismatch")
        selected.append((path, archive, entries))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(verify_archive, path, archive, entries)
            for path, archive, entries in selected
        ]
        for future in futures:
            future.result()
    if extract is not None:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(extract_archive, path, extract, entries)
                for path, _, entries in selected
            ]
            for future in futures:
                future.result()
    print(
        json.dumps(
            {
                "verified_archives": len(selected),
                "verified_files": len(files),
                "extracted": extract is not None,
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("results") / "asset-manifest.json")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument(
        "--download", action="store_true", help="Explicitly opt into network download"
    )
    parser.add_argument("--extract", type=Path)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=1)
    args = parser.parse_args()
    release_assets(
        args.manifest,
        args.cache,
        download=args.download,
        extract=args.extract,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
