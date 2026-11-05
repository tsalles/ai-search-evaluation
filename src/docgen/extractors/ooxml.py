import posixpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from docgen.errors import IntegrityError

REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def part_target(source: str, target: str) -> str:
    if ":" in target or target.startswith("//"):
        raise IntegrityError("Office relationship is not an internal package part.")
    resolved = (
        posixpath.normpath(target.lstrip("/"))
        if target.startswith("/")
        else posixpath.normpath(posixpath.join(posixpath.dirname(source), target))
    )
    if resolved == ".." or resolved.startswith("../"):
        raise IntegrityError("Office relationship escapes its package.")
    return resolved


def xml_part(archive: ZipFile, name: str) -> ET.Element:
    try:
        if archive.getinfo(name).file_size > 64 * 1024 * 1024:
            raise IntegrityError(f"Office XML part exceeds the safe readback limit: {name}.")
        raw = archive.read(name)
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise IntegrityError("Office XML cannot contain document type/entity declarations.")
        return ET.fromstring(raw)
    except (KeyError, ET.ParseError) as exc:
        raise IntegrityError(f"Missing or invalid Office XML part: {name}.") from exc


def check_office(archive: ZipFile) -> None:
    for name in archive.namelist():
        if "vbaproject" in name.lower() or "/embeddings/" in name.lower():
            raise IntegrityError("Macros or embedded executable objects are not allowed.")
        if name.endswith(".rels"):
            root = xml_part(archive, name)
            if any(node.get("TargetMode", "").lower() == "external" for node in root):
                raise IntegrityError("Office artifact contains an external relationship.")
