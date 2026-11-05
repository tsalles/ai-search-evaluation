from collections.abc import Callable
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def rewrite_zip(path: Path, part: str, transform: Callable[[bytes], bytes]) -> None:
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries[part] = transform(entries[part])
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
