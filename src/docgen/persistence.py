import os
import re
from pathlib import Path, PureWindowsPath

from docgen.errors import IntegrityError


def safe_child(root: Path, name: str) -> Path:
    if (
        not name or name in {".", ".."} or name[-1] in ". "
        or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
        or PureWindowsPath(name).is_reserved()
    ):
        raise IntegrityError("Unsafe generated file or directory name.")
    child = root / name
    if child.is_symlink() or child.is_junction():
        raise IntegrityError("Symlinks and junctions are not permitted in run state.")
    if not child.resolve().is_relative_to(root.resolve()):
        raise IntegrityError("Generated destination escapes the run directory.")
    return child


def temporary_path(destination: Path) -> Path:
    return safe_child(destination.parent, f".{destination.name}.docgen.tmp")


def atomic_write(destination: Path, data: bytes, *, overwrite: bool = False) -> None:
    destination = safe_child(destination.parent, destination.name)
    temporary = temporary_path(destination)
    created = False
    try:
        with temporary.open("xb") as stream:
            created = True
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, destination)
        else:
            # Hard-link publication is an atomic create-if-absent on local NTFS/POSIX filesystems.
            os.link(temporary, destination)
    except OSError as exc:
        raise IntegrityError(
            f"Atomic write failed ({type(exc).__name__}, errno={exc.errno})."
        ) from exc
    finally:
        if created:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                raise IntegrityError("Failed to remove the owned temporary file.") from exc
