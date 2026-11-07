"""Offline, fail-closed experimental asset derivative exporter.

The policy is a local private input. It must never be included in the release.
No study producer is executed, and no network request is made.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import plistlib
import re
import shutil
import sqlite3
import stat
import struct
import tarfile
import unicodedata
import zipfile
from collections import Counter, OrderedDict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, cast
from xml.etree import ElementTree as ET

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    ContentStream,
    DictionaryObject,
    IndirectObject,
    StreamObject,
)

TEXT_SUFFIXES = {
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".html",
    ".trec",
    ".py",
    ".ps1",
    ".log",
    ".txt",
    ".toml",
    ".lock",
    ".cfg",
    ".typed",
    ".example",
    ".csv",
    ".xml",
    ".rels",
}
TEXT_NAMES = {"METADATA", "WHEEL", "RECORD", "PKG-INFO", "LICENSE", "NOTICE", ".gitignore"}
OFFICE_SUFFIXES = {".docx", ".pptx", ".xlsx"}
MAX_ARCHIVE_BYTES = 1_800_000_000
UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
AZURE_HOST = re.compile(
    r"(?<![\w-])([\w-]{1,63})\.(search\.windows\.net|openai\.azure\.com|"
    r"cognitiveservices\.azure\.com|"
    r"services\.ai\.azure\.com|blob\.core\.windows\.net|azurewebsites\.net)",
    re.I,
)
IDENTITY = re.compile(
    rf"(?:subscriptions[/\\]+|(?:subscription|tenant|principal|operator|caller|"
    rf"object|search_object|searchCallerObject|operator_object|searchCaller|"
    rf"operatorObject)[_\w-]{{0,64}}[\"'\s:=/\\]{{1,16}})({UUID})",
    re.I,
)
RESOURCE_NAME = re.compile(
    r"/(?:resourceGroups|accounts|searchServices|sites|storageAccounts)/([\w.-]{1,90})", re.I
)
ARM_ID = re.compile(rf"/subscriptions/{UUID}/[^\s\"'\\]+", re.I)
SENSITIVE_KEYS = re.compile(
    r"(?:subscription|tenant|principal|caller|operator|object)[_-]?(?:id)?$|"
    r"(?:search|operator|caller)[_\w-]*(?:object|principal)[_\w-]*id$",
    re.I,
)
SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b|"
    r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b|"
    r"(?i:\b[A-Za-z0-9_]{0,96}(?:AccountKey|SharedAccessSignature|api[_-]?key|"
    r"client[_-]?secret|subscription[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"password)[\"']?\s*[=:]\s*[\"']?[A-Za-z0-9+/=_-]{24,})|"
    r"(?i:\bBearer\s+)[A-Za-z0-9._-]{32,}|"
    r"(?i:[?&]sig=)[A-Za-z0-9%+/=_-]{20,}"
)
QUOTED_CREDENTIAL = re.compile(
    r"""(?i:\b[A-Za-z0-9_]{0,96}(?:AccountKey|api[_-]?key|client[_-]?secret|"""
    r"""subscription[_-]?key|access[_-]?token|refresh[_-]?token|password))"""
    r"""["']?\s*[=:]\s*(["'])([^"'\r\n]*)\1"""
)
SECRET_HINT = re.compile(
    r"(?i:PRIVATE KEY|gh[pousr]_|github_pat_|eyJ|AccountKey|SharedAccessSignature|"
    r"api[_-]?key|client[_-]?secret|subscription[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|password|Bearer|[?&]sig=)"
)
DIACRITICS = {point: None for point in range(0x110000) if unicodedata.combining(chr(point))}


def is_credential_placeholder(value: str) -> bool:
    return value.casefold() in {
        "",
        "redacted",
        "removed",
        "none",
        "null",
        "unset",
        "placeholder",
        "your-api-key",
        "your_api_key",
        "example",
        "changeme",
    } or bool(re.fullmatch(r"<[\w -]+>|\$\{[\w]+\}", value))


class ReleaseError(ValueError):
    """A candidate cannot safely be classified or released."""


def sqlite_overflow_pages(data: bytes, roots: list[int]) -> tuple[int, set[int]]:
    """Classify overflow pages through validated SQLite B-tree payload pointers."""
    if data[:16] != b"SQLite format 3\x00":
        raise ReleaseError("invalid SQLite header")
    page_size = int.from_bytes(data[16:18], "big")
    page_size = 65536 if page_size == 1 else page_size
    if page_size < 512 or page_size & (page_size - 1) or len(data) % page_size:
        raise ReleaseError("invalid SQLite page framing")
    usable = page_size - data[20]
    pages = len(data) // page_size
    overflow: set[int] = set()
    visited: set[int] = set()
    pending = list(roots)

    def varint(offset: int, limit: int) -> tuple[int, int]:
        value = 0
        for index in range(9):
            if offset >= limit:
                raise ReleaseError("truncated SQLite varint")
            byte = data[offset]
            offset += 1
            value = (value << (8 if index == 8 else 7)) | (
                byte if index == 8 else byte & 127
            )
            if index == 8 or byte < 128:
                return value, offset
        raise ReleaseError("invalid SQLite varint")

    while pending:
        number = pending.pop()
        if not 1 <= number <= pages or number in visited or number in overflow:
            raise ReleaseError("invalid SQLite B-tree page pointer")
        visited.add(number)
        start = (number - 1) * page_size
        header = start + (100 if number == 1 else 0)
        kind = data[header]
        if kind not in {2, 5, 10, 13}:
            raise ReleaseError("unsupported SQLite B-tree page")
        interior = kind in {2, 5}
        header_size = 12 if interior else 8
        cells = int.from_bytes(data[header + 3 : header + 5], "big")
        if header + header_size + 2 * cells > start + usable:
            raise ReleaseError("invalid SQLite cell pointer array")
        if interior:
            pending.append(int.from_bytes(data[header + 8 : header + 12], "big"))
        for index in range(cells):
            pointer = header + header_size + 2 * index
            cursor = start + int.from_bytes(data[pointer : pointer + 2], "big")
            limit = start + usable
            if not header + header_size + 2 * cells <= cursor < limit:
                raise ReleaseError("invalid SQLite cell offset")
            if interior:
                if cursor + 4 > limit:
                    raise ReleaseError("truncated SQLite child pointer")
                pending.append(int.from_bytes(data[cursor : cursor + 4], "big"))
                cursor += 4
            payload, cursor = varint(cursor, limit)
            if kind == 5:
                continue
            if kind == 13:
                _, cursor = varint(cursor, limit)
            maximum = usable - 35 if kind == 13 else ((usable - 12) * 64 // 255) - 23
            minimum = ((usable - 12) * 32 // 255) - 23
            local = payload
            if payload > maximum:
                local = minimum + (payload - minimum) % (usable - 4)
                if local > maximum:
                    local = minimum
            if cursor + local > limit:
                raise ReleaseError("SQLite local payload exceeds page")
            remaining = payload - local
            if not remaining:
                continue
            if cursor + local + 4 > limit:
                raise ReleaseError("truncated SQLite overflow pointer")
            next_page = int.from_bytes(data[cursor + local : cursor + local + 4], "big")
            while remaining:
                if (
                    not 1 <= next_page <= pages
                    or next_page in overflow
                    or next_page in visited
                ):
                    raise ReleaseError("invalid SQLite overflow chain")
                overflow.add(next_page)
                page_start = (next_page - 1) * page_size
                next_page = int.from_bytes(data[page_start : page_start + 4], "big")
                remaining -= min(remaining, usable - 4)
            if next_page:
                raise ReleaseError("unexpected SQLite overflow-chain trailer")
    return page_size, overflow


def audit_sqlite_residue(
    data: bytes, policy: Policy, roots: list[int], public_hosts: set[str]
) -> int:
    page_size, overflow = sqlite_overflow_pages(data, roots)
    classified = 0
    for run in re.finditer(rb"[\x20-\x7e]{4,}", data):
        text = run[0].decode("ascii")
        run_start = run.start()
        number = run_start // page_size + 1
        page_start = (number - 1) * page_size
        if number in overflow and run_start < page_start + 4:
            prefix = page_start + 4 - run_start
            text = text[prefix:]
            run_start += prefix
        edits = []
        for host in AZURE_HOST.finditer(text):
            if host[1].casefold().startswith("example"):
                continue
            offset = run_start + host.start()
            number = offset // page_size + 1
            payload_start = (number - 1) * page_size + 4
            if number not in overflow or not payload_start - 4 <= offset <= payload_start:
                continue
            fragment = data[payload_start : run_start + host.end()].decode("ascii").casefold()
            if fragment and any(approved.endswith(fragment) for approved in public_hosts):
                edits.append((host.start(), host.end()))
        for start, end in reversed(edits):
            text = text[:start] + "example-framed-endpoint.search.windows.net" + text[end:]
            classified += 1
        policy.audit(text)
    return classified


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_name(name: str) -> str:
    if "\\" in name or "\x00" in name or ":" in name:
        raise ReleaseError("unsafe archive member")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ReleaseError("unsafe archive member")
    if any(part.rstrip(". ") != part for part in path.parts):
        raise ReleaseError("ambiguous Windows archive member")
    if any(
        part.rstrip(". ").upper().split(".")[0]
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
        for part in path.parts
    ):
        raise ReleaseError("reserved archive member")
    return path.as_posix()


def read_text(data: bytes) -> tuple[str, str]:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError as error:
        raise ReleaseError("unclassified non-UTF text") from error


def parse_json(text: str) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReleaseError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=unique_object)


def xml_root(data: bytes) -> ET.Element:
    from defusedxml.ElementTree import fromstring  # type: ignore[import-untyped]

    return cast(ET.Element, fromstring(data))


def serialize_xml(root: ET.Element, source: bytes) -> bytes:
    from defusedxml.ElementTree import iterparse

    bindings: dict[str, str] = {}
    for _, declaration in iterparse(io.BytesIO(source), events=("start-ns",)):
        prefix, namespace = declaration
        if prefix in bindings and bindings[prefix] != namespace:
            raise ReleaseError("XML namespace prefix rebinding requires a verified editor")
        bindings[prefix] = namespace
        if not re.fullmatch(r"ns\d+", prefix):
            ET.register_namespace(prefix, namespace)
    result = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    emitted = dict(
        declaration for _, declaration in iterparse(io.BytesIO(result), events=("start-ns",))
    )
    missing: list[str] = []
    from xml.sax.saxutils import quoteattr

    for prefix, namespace in bindings.items():
        if prefix in emitted:
            if emitted[prefix] != namespace:
                raise ReleaseError("XML namespace binding changed")
        else:
            attribute = "xmlns:" + prefix if prefix else "xmlns"
            missing.append(f" {attribute}={quoteattr(namespace)}")
    # ElementTree otherwise drops declarations referenced only by mc:Ignorable/QName values.
    opening = re.search(rb"<[\w:.-]+", result)
    if opening is None:
        raise ReleaseError("missing serialized XML root")
    result = result[: opening.end()] + "".join(missing).encode() + result[opening.end() :]
    xml_root(result)
    return cast(bytes, result)


def validate_xml_qnames(data: bytes) -> None:
    from defusedxml.ElementTree import iterparse

    compatibility = "http://schemas.openxmlformats.org/markup-compatibility/2006"
    schema = "http://www.w3.org/2001/XMLSchema-instance"
    scopes: list[dict[str, str]] = []
    pending: dict[str, str] = {}
    for event, value in iterparse(io.BytesIO(data), events=("start-ns", "start", "end")):
        if event == "start-ns":
            prefix, namespace = value
            pending[prefix] = namespace
        elif event == "start":
            bindings = (
                dict(scopes[-1]) if scopes else {"xml": "http://www.w3.org/XML/1998/namespace"}
            )
            bindings.update(pending)
            pending.clear()
            scopes.append(bindings)
            for key, text in value.attrib.items():
                prefixes: list[str] = []
                if key in {f"{{{compatibility}}}Ignorable", f"{{{compatibility}}}MustUnderstand"}:
                    prefixes = text.split()
                elif key in {
                    f"{{{compatibility}}}ProcessContent",
                    f"{{{compatibility}}}PreserveAttributes",
                    f"{{{compatibility}}}PreserveElements",
                    f"{{{schema}}}type",
                }:
                    prefixes = [token.split(":", 1)[0] for token in text.split() if ":" in token]
                elif value.tag == f"{{{compatibility}}}Choice" and key == "Requires":
                    prefixes = text.split()
                if any(prefix not in bindings for prefix in prefixes):
                    raise ReleaseError("unbound Office/XML compatibility namespace")
        else:
            scopes.pop()


def numeric_shape(value: Any) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0

    def visit(item: Any) -> None:
        nonlocal count
        if isinstance(item, dict):
            digest.update(b"{")
            for child in item.values():
                visit(child)
            digest.update(b"}")
        elif isinstance(item, list):
            digest.update(b"[")
            for child in item:
                visit(child)
            digest.update(b"]")
        elif isinstance(item, (int, float, bool)) or item is None:
            digest.update((type(item).__name__ + ":" + repr(item) + ";").encode())
            count += 1
        elif isinstance(item, str):
            digest.update(b"s;")
        else:
            raise ReleaseError("unsupported structured value")

    visit(value)
    return digest.hexdigest(), count


@dataclass
class Policy:
    replacements: dict[str, str]
    clients: list[str]
    private_terms: list[str]
    approved_images: set[str] = field(default_factory=set)
    identities: dict[str, str] = field(default_factory=dict)
    resources: dict[str, str] = field(default_factory=dict)
    approved_identity_values: set[str] = field(default_factory=set)
    _substitution: re.Pattern[str] | None = field(default=None, init=False)
    _substitution_values: dict[str, str] = field(default_factory=dict, init=False)
    _mapping_size: tuple[int, int, int] = field(default=(0, 0, 0), init=False)
    _client_pattern: re.Pattern[str] | None = field(default=None, init=False)
    _text_cache: OrderedDict[str, str] = field(default_factory=OrderedDict, init=False)
    _text_cache_bytes: int = field(default=0, init=False)
    _audit_cache: OrderedDict[str, None] = field(default_factory=OrderedDict, init=False)
    _audit_cache_bytes: int = field(default=0, init=False)
    _audit_signature: tuple[Any, ...] = field(default=(), init=False)

    @classmethod
    def load(cls, path: Path) -> Policy:
        value = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            value["replacements"],
            value["clients"],
            value["private_terms"],
            set(value.get("approved_images", [])),
        )

    @staticmethod
    def anonymous_id(value: str) -> str:
        raw = hashlib.sha256(("public-identity:" + value.lower()).encode()).hexdigest()[:32]
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"

    def learn(self, text: str) -> None:
        folded = text.casefold()
        if "-" in text and any(
            word in folded
            for word in ("subscription", "tenant", "principal", "operator", "caller", "object")
        ):
            for match in IDENTITY.finditer(text):
                value = match[1].lower()
                if (
                    value not in self.identities.values()
                    and value not in self.approved_identity_values
                ):
                    self.identities[value] = self.anonymous_id(value)
        if "/subscriptions/" in folded:
            for identifier in ARM_ID.finditer(text):
                for match in RESOURCE_NAME.finditer(identifier[0]):
                    value = match[1].lower()
                    if not value.startswith("example"):
                        self.resources.setdefault(
                            value, "example-resource-" + sha256(value.encode())[:10]
                        )
        if any(suffix in folded for suffix in (".windows.net", ".azure.com", ".azurewebsites.net")):
            for match in AZURE_HOST.finditer(text):
                value = match[1].lower()
                if not value.startswith("example"):
                    self.resources.setdefault(
                        value, "example-resource-" + sha256(value.encode())[:10]
                    )

    def text(self, text: str, *, python_source: bool = False) -> str:
        if python_source:
            return self.python_text(text)
        original_text = text
        size = (len(self.replacements), len(self.resources), len(self.identities))
        if not python_source and size == self._mapping_size and text in self._text_cache:
            return self._text_cache[text]
        self.learn(text)
        size = (len(self.replacements), len(self.resources), len(self.identities))
        if size != self._mapping_size:
            values = dict(self.identities)
            values.update(self.resources)
            values.update({key.casefold(): value for key, value in self.replacements.items()})
            patterns = []
            for original in sorted(values, key=len, reverse=True):
                pattern = re.escape(original)
                if original in self.resources and original not in self.replacements:
                    pattern = rf"(?<![\w-]){pattern}(?![\w-])"
                patterns.append(pattern)
            self._substitution = re.compile("|".join(patterns), re.I) if patterns else None
            self._substitution_values = values
            self._mapping_size = size
            self._text_cache.clear()
            self._text_cache_bytes = 0
        if self._substitution is not None:
            text = self._substitution.sub(
                lambda match: self._substitution_values[match[0].casefold()], text
            )
        self.audit(text, python_source=python_source)
        if not python_source and len(original_text) <= 1024 * 1024:
            estimate = (len(original_text) + len(text)) * 4 + 256
            while self._text_cache and self._text_cache_bytes + estimate > 128 * 1024 * 1024:
                key, value = self._text_cache.popitem(last=False)
                self._text_cache_bytes -= (len(key) + len(value)) * 4 + 256
            self._text_cache[original_text] = text
            self._text_cache_bytes += estimate
        return text

    def python_text(self, text: str) -> str:
        import ast
        import tokenize

        before = ast.parse(text)
        self.learn(text)
        aliases = {
            key: value
            for key, value in self.replacements.items()
            if key.isidentifier()
            and any(term.casefold() == key.casefold() for term in self.private_terms)
        }
        alias_pattern = (
            re.compile(
                "|".join(re.escape(key) for key in sorted(aliases, key=len, reverse=True)), re.I
            )
            if aliases
            else None
        )
        tokens = []
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            public = token.string
            if token.type == tokenize.STRING:
                literal = ast.literal_eval(token.string)
                if isinstance(literal, str):
                    transformed = self.text(literal)
                    if transformed != literal:
                        public = repr(transformed)
                elif isinstance(literal, bytes):
                    try:
                        decoded, encoding = read_text(literal)
                    except UnicodeDecodeError:
                        if len(literal) > 16 or literal.startswith(
                            (b"PK", b"%PDF", b"\x89PNG", b"\xff\xd8", b"GIF8")
                        ):
                            raise ReleaseError("unclassified Python binary literal") from None
                        self.audit(literal.decode("latin-1").replace("\x00", ""))
                        for start in range(len(literal)):
                            for end in range(start + 4, len(literal) + 1):
                                try:
                                    fragment = literal[start:end].decode("utf-8")
                                except UnicodeDecodeError:
                                    continue
                                self.audit(fragment)
                    else:
                        transformed = self.text(decoded)
                        if transformed != decoded:
                            public = repr(transformed.encode(encoding))
                else:
                    raise ReleaseError("unclassified Python literal")
            elif token.type in {tokenize.COMMENT, tokenize.FSTRING_MIDDLE}:
                public = self.text(token.string)
                if token.type == tokenize.FSTRING_MIDDLE and any(
                    public.count(brace) != token.string.count(brace) for brace in "{}"
                ):
                    raise ReleaseError("Python interpolation shape changed")
            elif token.type == tokenize.NAME and alias_pattern is not None:
                public = alias_pattern.sub(
                    lambda match: next(
                        re.sub(r"\W", "_", value)
                        for key, value in aliases.items()
                        if key.casefold() == match[0].casefold()
                    ),
                    token.string,
                )
                if not public.isidentifier():
                    raise ReleaseError("invalid public Python identifier")
            tokens.append(token._replace(string=public))
        public = tokenize.untokenize(tokens)
        after = ast.parse(public)
        numeric_before = [
            node.value
            for node in ast.walk(before)
            if isinstance(node, ast.Constant)
            and (isinstance(node.value, (int, float, bool)) or node.value is None)
        ]
        numeric_after = [
            node.value
            for node in ast.walk(after)
            if isinstance(node, ast.Constant)
            and (isinstance(node.value, (int, float, bool)) or node.value is None)
        ]
        if numeric_shape(numeric_before) != numeric_shape(numeric_after):
            raise ReleaseError("Python numeric literal invariant changed")
        self.audit(public, python_source=True)
        return public

    def audit(self, text: str, *, python_source: bool = False, filename: bool = False) -> None:
        import html

        original_text = text
        if not python_source and not filename:
            signature = (
                tuple(self.identities.items()),
                tuple(self.resources.items()),
                tuple(self.replacements.items()),
                tuple(self.clients),
                tuple(self.private_terms),
                frozenset(self.approved_identity_values),
            )
            if signature != self._audit_signature:
                self._audit_cache.clear()
                self._audit_cache_bytes = 0
                self._client_pattern = None
                self._audit_signature = signature
            if text in self._audit_cache:
                self._audit_cache.move_to_end(text)
                return
        references: set[str] = set()
        literals: list[str] = []
        if python_source:
            import ast

            nodes = list(ast.walk(ast.parse(text)))
            references = {node.id for node in nodes if isinstance(node, ast.Name)}
            literals = [
                node.value
                for node in nodes
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            ]
            credential_values: list[tuple[str, ast.AST]] = []
            for node in nodes:
                if isinstance(node, ast.keyword) and node.arg is not None:
                    credential_values.append((node.arg, node.value))
                elif isinstance(node, ast.Assign):
                    credential_values.extend(
                        (target.id, node.value)
                        for target in node.targets
                        if isinstance(target, ast.Name)
                    )
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    if node.value is not None:
                        credential_values.append((node.target.id, node.value))
                elif isinstance(node, ast.Dict):
                    credential_values.extend(
                        (key.value, value)
                        for key, value in zip(node.keys, node.values, strict=True)
                        if isinstance(key, ast.Constant) and isinstance(key.value, str)
                    )
                elif isinstance(node, ast.arguments):
                    if node.defaults:
                        arguments = (node.posonlyargs + node.args)[-len(node.defaults) :]
                        credential_values.extend(
                            (argument.arg, default)
                            for argument, default in zip(arguments, node.defaults, strict=True)
                        )
                    credential_values.extend(
                        (argument.arg, default)
                        for argument, default in zip(node.kwonlyargs, node.kw_defaults, strict=True)
                        if default is not None
                    )
            for key, credential_node in credential_values:
                if (
                    re.search(
                        r"(?i:api[_-]?key|client[_-]?secret|password|accountkey|"
                        r"sharedaccesssignature|subscription[_-]?key|access[_-]?token|"
                        r"refresh[_-]?token)$",
                        key,
                    )
                    and isinstance(credential_node, ast.Constant)
                    and isinstance(credential_node.value, (str, bytes))
                ):
                    literal = credential_node.value
                    if isinstance(literal, bytes):
                        try:
                            literal = literal.decode("ascii")
                        except UnicodeDecodeError:
                            raise ReleaseError("Python credential literal") from None
                    if not is_credential_placeholder(literal):
                        raise ReleaseError("Python credential literal")
        if "\\u" in text or "\\x" in text:
            text = re.sub(
                r"\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})",
                lambda match: chr(int(match[1] or match[2], 16)),
                text,
            )
        if "&" in text:
            text = html.unescape(text)
        normalized = (
            text if text.isascii() else unicodedata.normalize("NFKD", text).translate(DIACRITICS)
        )
        folded = normalized.casefold()
        if self._client_pattern is None:
            terms = [
                unicodedata.normalize("NFKD", term).translate(DIACRITICS).casefold()
                for term in self.clients
            ]
            self._client_pattern = re.compile(
                "|".join(re.escape(term) for term in terms) if terms else r"(?!)", re.I
            )
        for match in self._client_pattern.finditer(normalized):
            start, end = match.span()
            previous = normalized[start - 1] if start else ""
            following = normalized[end : end + 1]
            left = not previous.isalpha() or previous.islower() and normalized[start].isupper()
            right = (
                not following.isalpha()
                or normalized[end - 1].islower()
                and following.isupper()
                or normalized[end - 1].isupper()
                and (
                    following.islower()
                    or following.isupper()
                    and normalized[end + 1 : end + 2].islower()
                )
            )
            if filename or left and right:
                raise ReleaseError("client identifying term")
        if any(term.casefold() in folded for term in self.private_terms):
            raise ReleaseError("private identifying term")
        if re.search(r"(?i:[a-z]:[\\/]+Users[\\/]+|/home/[^/\s]+/)", text):
            raise ReleaseError("private home path")
        credential_candidates = bool(SECRET_HINT.search(text))
        for match in SECRET.finditer(text) if credential_candidates else ():
            reference = re.fullmatch(r"""[\w]+["']?\s*[=:]\s*([A-Za-z_]\w*)""", match[0])
            if (
                python_source
                and reference
                and reference[1] in references
                and not any(reference[1] in literal for literal in literals)
            ):
                continue
            raise ReleaseError("credential candidate")
        if credential_candidates and any(
            not is_credential_placeholder(match[2]) for match in QUOTED_CREDENTIAL.finditer(text)
        ):
            raise ReleaseError("literal credential candidate")
        if any(suffix in folded for suffix in (".windows.net", ".azure.com", ".azurewebsites.net")):
            for match in AZURE_HOST.finditer(text):
                if not match[1].lower().startswith("example"):
                    raise ReleaseError("unmapped resource endpoint")
        if re.search(r"(?i:data:image/[\w.+-]+;base64,)[A-Za-z0-9+/=\s]{30,}", text):
            raise ReleaseError("unreviewed inline image")
        if re.search(r"(?:iVBORw0KGgo|/9j/|R0lGOD[dlh])[A-Za-z0-9+/=\s]{64,}", text):
            raise ReleaseError("unreviewed base64 image")
        if "-" in text:
            for value in self.identities:
                if value in folded:
                    raise ReleaseError("unmapped private identity")
            if any(
                term in folded
                for term in ("subscription", "tenant", "principal", "operator", "caller", "object")
            ):
                for match in IDENTITY.finditer(text):
                    if (
                        match[1].lower() not in self.identities.values()
                        and match[1].lower() not in self.approved_identity_values
                    ):
                        raise ReleaseError("unmapped categorized identity")
        if not python_source and not filename and len(original_text) <= 1024 * 1024:
            estimate = len(original_text) * 4 + 128
            while self._audit_cache and self._audit_cache_bytes + estimate > 64 * 1024 * 1024:
                key, _ = self._audit_cache.popitem(last=False)
                self._audit_cache_bytes -= len(key) * 4 + 128
            self._audit_cache[original_text] = None
            self._audit_cache_bytes += estimate

    def structured(self, value: Any, key: str = "") -> Any:
        if isinstance(value, str):
            credential = re.search(
                r"(?i:api[_-]?key|client[_-]?secret|password|accountkey|"
                r"subscription[_-]?key|access[_-]?token|refresh[_-]?token)$",
                key,
            )
            if credential and not is_credential_placeholder(value):
                raise ReleaseError("credential field candidate")
            if (
                SENSITIVE_KEYS.search(key)
                and re.fullmatch(UUID, value)
                and value.lower() not in self.identities.values()
                and value.lower() not in self.approved_identity_values
            ):
                self.identities[value.lower()] = self.anonymous_id(value)
            return self.text(value)
        if isinstance(value, dict):
            # Learn all identity fields before transforming sibling references.
            for name, child in value.items():
                if isinstance(child, str) and SENSITIVE_KEYS.search(name):
                    if (
                        re.fullmatch(UUID, child)
                        and child.lower() not in self.identities.values()
                        and child.lower() not in self.approved_identity_values
                    ):
                        self.identities[child.lower()] = self.anonymous_id(child)
            result = {
                self.text(name): self.structured(child, name) for name, child in value.items()
            }
            if len(result) != len(value):
                raise ReleaseError("anonymization key collision")
            return result
        if isinstance(value, list):
            return [self.structured(child, key) for child in value]
        return value


@dataclass
class Exporter:
    policy: Policy
    counts: Counter[str] = field(default_factory=Counter)
    entries: list[dict[str, Any]] = field(default_factory=list)
    content_cache: dict[
        tuple[str, str, int, int, int],
        tuple[bytes, Counter[str], Counter[str], tuple[int, ...]],
    ] = field(default_factory=dict)
    content_cache_bytes: int = 0
    emitted_cache: dict[
        tuple[str, str, int, int, int],
        tuple[Path, str, Counter[str], Counter[str], tuple[int, ...]],
    ] = field(default_factory=dict)
    exclusions: list[dict[str, str]] = field(default_factory=list)
    images: Counter[str] = field(default_factory=Counter)
    pdf_cache: dict[str, bytes] = field(default_factory=dict)
    numeric_values: int = 0
    json_documents: int = 0
    database_rows: int = 0
    xml_numeric_nodes: int = 0
    xml_numeric_attributes: int = 0
    verification_path: str | None = None

    def json_data(self, data: bytes) -> bytes:
        text, encoding = read_text(data)
        original = parse_json(text)
        public = self.policy.structured(original)
        before = numeric_shape(original)
        if before != numeric_shape(public):
            raise ReleaseError("structured numeric/shape invariant changed")
        self.numeric_values += before[1]
        self.json_documents += 1
        if original == public:
            return data
        return (json.dumps(public, ensure_ascii=False, indent=2) + "\n").encode(encoding)

    def xml_data(self, data: bytes, name: str, *, office: bool) -> bytes:
        original = xml_root(data)
        validate_xml_qnames(data)
        self.counts["xml_documents"] += 1
        if office:
            self.counts["office_xml_parts"] += 1
        numeric = [
            node.text
            for node in original.iter()
            if node.text and re.fullmatch(r"-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?", node.text)
        ]
        numeric_attributes = [
            value
            for node in original.iter()
            for key, value in node.attrib.items()
            if key.split("}")[-1] not in {"author", "initials", "userId"}
            and re.fullmatch(r"-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?", value)
        ]
        changed = False
        for node in original.iter():
            local = node.tag.split("}")[-1]
            comment_author = (
                office
                and name.startswith("xl/")
                and "comment" in name.lower()
                and local == "author"
            )
            if office and (local in {"creator", "lastModifiedBy"} or comment_author):
                if node.text not in {
                    None,
                    "",
                    "python-docx",
                    "python-pptx",
                    "openpyxl",
                    "Synthetic Generator",
                    "Public Study",
                }:
                    node.text = "Public Study"
                    changed = True
            if node.text:
                public = self.policy.text(node.text)
                changed |= public != node.text
                node.text = public
            if node.tail:
                public = self.policy.text(node.tail)
                changed |= public != node.tail
                node.tail = public
            for key, value in node.attrib.items():
                public = self.policy.text(value)
                author_attribute = key.split("}")[-1]
                if office and (
                    author_attribute in {"author", "initials", "userId"}
                    or (local == "cmAuthor" and author_attribute == "name")
                    or (local == "person" and author_attribute in {"displayName", "providerId"})
                ):
                    public = "Public Study"
                changed |= public != value
                node.set(key, public)
        after = [
            node.text
            for node in original.iter()
            if node.text and re.fullmatch(r"-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?", node.text)
        ]
        if numeric != after:
            raise ReleaseError("XML numeric invariant changed")
        after_attributes = [
            value
            for node in original.iter()
            for key, value in node.attrib.items()
            if key.split("}")[-1] not in {"author", "initials", "userId"}
            and re.fullmatch(r"-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?", value)
        ]
        if numeric_attributes != after_attributes:
            raise ReleaseError("XML numeric attribute invariant changed")
        self.xml_numeric_nodes += len(numeric)
        self.xml_numeric_attributes += len(numeric_attributes)
        self.policy.audit("".join(original.itertext()))
        if changed:
            public_data = serialize_xml(original, data)
            validate_xml_qnames(public_data)
            if self.policy.text(public_data.decode("utf-8")) != public_data.decode("utf-8"):
                raise ReleaseError("XML namespace requires a verified editor")
            return public_data
        return data

    def zip_data(self, data: bytes, name: str, *, office: bool) -> bytes:
        with zipfile.ZipFile(io.BytesIO(data)) as source:
            if source.testzip() is not None:
                raise ReleaseError("invalid ZIP CRC")
            footer = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
            if footer < 0 or footer + 22 + len(source.comment) != len(data):
                raise ReleaseError("unclassified ZIP trailer")
            archive_comment = (
                self.policy.text(read_text(source.comment)[0]).encode("utf-8")
                if source.comment
                else b""
            )
            changed_headers = archive_comment != source.comment
            cursor = 0
            for info in sorted(source.infolist(), key=lambda item: item.header_offset):
                if info.orig_filename != info.filename or info.header_offset != cursor:
                    raise ReleaseError("unclassified ZIP prefix, gap or filename")
                if info.extra or data[cursor : cursor + 4] != b"PK\x03\x04":
                    raise ReleaseError("unclassified ZIP extra field or header")
                filename_length, extra_length = struct.unpack_from("<HH", data, cursor + 26)
                if extra_length:
                    raise ReleaseError("unclassified local ZIP extra field")
                cursor += 30 + filename_length + info.compress_size
                if info.flag_bits & 8:
                    cursor += 16 if data[cursor : cursor + 4] == b"PK\x07\x08" else 12
            if cursor != source.start_dir:
                raise ReleaseError("unclassified ZIP interstitial data")
            if office:
                for info in source.infolist():
                    if "person" in info.filename.lower() and info.filename.endswith(".xml"):
                        for node in xml_root(source.read(info)).iter():
                            if node.tag.split("}")[-1] == "person":
                                for key, value in node.attrib.items():
                                    if key.split("}")[-1] == "id" and re.fullmatch(
                                        UUID, value.strip("{}")
                                    ):
                                        identifier = value.strip("{}").lower()
                                        if identifier not in self.policy.identities.values():
                                            self.policy.identities[identifier] = (
                                                self.policy.anonymous_id(identifier)
                                            )
            names: set[str] = set()
            members: dict[str, bytes] = {}
            comments: dict[str, bytes] = {}
            removed: set[str] = set()
            for info in source.infolist():
                original_member = safe_name(info.filename.rstrip("/"))
                member = safe_name(self.policy.text(original_member))
                self.policy.audit(member, filename=True)
                comment = (
                    self.policy.text(read_text(info.comment)[0]).encode("utf-8")
                    if info.comment
                    else b""
                )
                changed_headers |= member != original_member or comment != info.comment
                if info.is_dir():
                    continue
                if info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16):
                    raise ReleaseError("encrypted or linked archive member")
                if member.lower() in names:
                    raise ReleaseError("duplicate archive member")
                names.add(member.lower())
                comments[member] = comment
                if re.search(r"(?i:vbaProject|activeX|embeddings/|_xmlsignatures/)", member):
                    raise ReleaseError("active or opaque Office payload")
                content = source.read(info)
                suffix = ".rels" if member.endswith(".rels") else Path(member).suffix.lower()
                if suffix in {".png", ".jpeg", ".jpg", ".gif", ".bmp", ".wmf", ".emf"}:
                    digest = sha256(content)
                    self.images[digest] += 1
                    if digest not in self.policy.approved_images:
                        raise ReleaseError("unreviewed embedded image")
                    if member.startswith("docProps/thumbnail."):
                        removed.add(member)
                        self.counts["removed_standard_thumbnails"] += 1
                        continue
                    raise ReleaseError("approved thumbnail bytes used as unreviewed content image")
                elif suffix in {".xml", ".rels"}:
                    if (
                        office
                        and suffix == ".xml"
                        and re.search(r"(?i:comment|/persons?/)", member)
                    ):
                        self.counts["office_comment_or_person_parts"] += 1
                    members[member] = self.xml_data(content, member, office=office)
                else:
                    members[member] = self.transform(content, member)
            if removed:
                for member in ("_rels/.rels", "[Content_Types].xml"):
                    root = xml_root(members[member])
                    for node in list(root):
                        target = node.get("Target", "").lstrip("/")
                        part = node.get("PartName", "").lstrip("/")
                        if target in removed or part in removed:
                            root.remove(node)
                    members[member] = serialize_xml(root, members[member])
                self.validate_office_relationships(members)
            elif office:
                self.validate_office_relationships(members)
            unchanged = (
                not changed_headers
                and not removed
                and all(source.read(n) == v for n, v in members.items())
            )
            if unchanged:
                return data
            output = io.BytesIO()
            with zipfile.ZipFile(
                output, "w", zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive_target:
                archive_target.comment = archive_comment
                for member, content in members.items():
                    public_info = zipfile.ZipInfo(member)
                    public_info.comment = comments[member]
                    archive_target.writestr(
                        public_info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6
                    )
            return output.getvalue()

    @staticmethod
    def validate_office_relationships(members: dict[str, bytes]) -> None:
        import posixpath

        if "[Content_Types].xml" not in members:
            raise ReleaseError("Office package has no content types")
        for member, content in members.items():
            if not member.endswith(".rels"):
                continue
            root = xml_root(content)
            base = posixpath.dirname(posixpath.dirname(member)) if member != "_rels/.rels" else ""
            for node in root:
                if node.get("TargetMode") == "External":
                    raise ReleaseError("external Office relationship")
                target = node.get("Target", "").split("#", 1)[0]
                resolved = posixpath.normpath(
                    target.lstrip("/") if target.startswith("/") else posixpath.join(base, target)
                )
                if resolved not in members:
                    raise ReleaseError("broken Office relationship")

    def pdf_data(self, data: bytes) -> bytes:
        digest = sha256(data)
        if digest in self.pdf_cache:
            return self.pdf_cache[digest]
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ReleaseError("encrypted PDF")
        root = cast(DictionaryObject, reader.trailer["/Root"])
        if any(key in root for key in ("/OpenAction", "/AA")) or "/Names" in root:
            raise ReleaseError("PDF action or attachment candidate")
        metadata = {key: str(value) for key, value in (reader.metadata or {}).items()}
        if reader.xmp_metadata is not None:
            raise ReleaseError("unclassified PDF XMP metadata")
        self.audit_pdf_objects(reader)
        changed = False
        for key, value in metadata.items():
            if value is not None:
                text = str(value)
                public = self.policy.text(text)
                if key in {"/Author", "/Creator"} and text not in {
                    "",
                    "anonymous",
                    "Public Study",
                    "ReportLab PDF Library - www.reportlab.com",
                }:
                    public = "Public Study"
                changed |= public != text
                metadata[key] = public
        for page in reader.pages:
            if "/Annots" in page:
                raise ReleaseError("unclassified PDF annotations")
            text = page.extract_text() or ""
            if self.policy.text(text) != text:
                raise ReleaseError("PDF content requires a verified content editor")
            for image in page.images:
                image_hash = sha256(image.data)
                self.images[image_hash] += 1
                raise ReleaseError("unreviewed PDF image")
            if not text.strip():
                raise ReleaseError("opaque PDF page")
        if changed:
            writer = PdfWriter()
            writer.clone_document_from_reader(reader)
            writer.add_metadata(metadata)
            output = io.BytesIO()
            writer.write(output)
            public_data = output.getvalue()
            again = PdfReader(io.BytesIO(public_data), strict=True)
            if [p.extract_text() for p in reader.pages] != [p.extract_text() for p in again.pages]:
                raise ReleaseError("PDF text invariant changed")
        else:
            public_data = data
        self.pdf_cache[digest] = public_data
        self.counts["distinct_pdf_contents"] += 1
        return public_data

    def audit_pdf_objects(self, reader: PdfReader) -> None:
        content_objects: set[int] = set()
        unicode_maps: set[int] = set()
        font_programs: set[int] = set()
        for page in reader.pages:
            contents = page.get("/Contents")
            if contents is not None:
                contents = contents.get_object()
                streams = contents if isinstance(contents, ArrayObject) else [contents]
                content_objects.update(id(stream.get_object()) for stream in streams)
            resources = page.get("/Resources")
            if resources is not None:
                fonts = resources.get_object().get("/Font", {})
                for reference in (
                    fonts.get_object().values() if hasattr(fonts, "get_object") else fonts.values()
                ):
                    font = reference.get_object()
                    if "/ToUnicode" in font:
                        unicode_maps.add(id(font["/ToUnicode"].get_object()))
                    descriptor = font.get("/FontDescriptor")
                    if descriptor is not None:
                        descriptor = descriptor.get_object()
                        if "/FontFile2" in descriptor:
                            font_programs.add(id(descriptor["/FontFile2"].get_object()))
        metadata = reader.trailer.get("/Info")
        metadata_object = id(metadata.get_object()) if metadata is not None else None
        visited: set[int] = set()
        forbidden = {
            "/AA",
            "/OpenAction",
            "/JS",
            "/JavaScript",
            "/Launch",
            "/EmbeddedFiles",
            "/EmbeddedFile",
            "/Filespec",
            "/RichMedia",
            "/XFA",
            "/URI",
            "/GoToR",
            "/SubmitForm",
            "/AcroForm",
        }

        def visit(value: Any, key: str = "") -> None:
            if isinstance(value, IndirectObject):
                visit(value.get_object(), key)
                return
            if isinstance(value, (DictionaryObject, ArrayObject)):
                if id(value) in visited:
                    return
                visited.add(id(value))
            if isinstance(value, DictionaryObject):
                if forbidden.intersection(value):
                    raise ReleaseError("active or attached PDF object")
                is_metadata = id(value) == metadata_object
                for child_key, child in value.items():
                    if self.policy.text(str(child_key)) != str(child_key):
                        raise ReleaseError("private PDF dictionary name")
                    if not is_metadata:
                        visit(child, str(child_key))
                if isinstance(value, StreamObject):
                    if id(value) in unicode_maps:
                        self.audit_pdf_unicode_map(value.get_data())
                        self.counts["pdf_unicode_maps"] += 1
                        return
                    if id(value) in font_programs:
                        self.audit_truetype_font(value.get_data())
                        self.counts["pdf_truetype_fonts"] += 1
                        return
                    if id(value) not in content_objects:
                        raise ReleaseError("unclassified opaque PDF stream")
                    self.policy.audit(value.get_data().decode("latin-1"))
                    content = ContentStream(value, reader)
                    for operands, operator in content.operations:
                        if operator == b"INLINE IMAGE":
                            raise ReleaseError("unreviewed inline PDF image")
                        if self.policy.text(operator.decode("ascii")) != operator.decode("ascii"):
                            raise ReleaseError("private PDF operator")
                        visit(operands)
                    self.counts["pdf_content_streams"] += 1
            elif isinstance(value, (list, ArrayObject)):
                for child in value:
                    visit(child, key)
            elif isinstance(value, ByteStringObject):
                if key == "/ID" and len(value) == 16:
                    return
                try:
                    decoded = bytes(value).decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ReleaseError("unclassified binary PDF string") from error
                if not decoded.isprintable() or self.policy.text(decoded) != decoded:
                    raise ReleaseError("unclassified or private PDF byte string")
            elif isinstance(value, str) and self.policy.text(value) != value:
                raise ReleaseError("PDF object content requires a verified editor")

        visit(reader.trailer)
        for generation, offsets in reader.xref.items():
            for object_id in offsets:
                if object_id:
                    visit(IndirectObject(object_id, generation, reader))
                    self.counts["pdf_indirect_objects"] += 1
        for object_id in reader.xref_objStm:
            visit(IndirectObject(object_id, 0, reader))
            self.counts["pdf_compressed_objects"] += 1

    def audit_pdf_unicode_map(self, data: bytes) -> None:
        text = data.decode("ascii")
        if self.policy.text(text) != text:
            raise ReleaseError("private PDF Unicode map")
        # Only the declarative Adobe ToUnicode subset is classified; no arbitrary
        # PostScript program or external resource loading is accepted.
        allowed = {
            "CIDInit",
            "ProcSet",
            "findresource",
            "begin",
            "dict",
            "begincmap",
            "CIDSystemInfo",
            "Registry",
            "Adobe",
            "Ordering",
            "UCS",
            "Supplement",
            "def",
            "CMapName",
            "CMapType",
            "begincodespacerange",
            "endcodespacerange",
            "beginbfchar",
            "endbfchar",
            "beginbfrange",
            "endbfrange",
            "endcmap",
            "CMap",
            "currentdict",
            "defineresource",
            "pop",
            "end",
        }
        without_hex = re.sub(r"<[0-9a-fA-F\s]+>", "", text)
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_.+-]*", without_hex):
            if word not in allowed and not re.fullmatch(r"[A-Z]{6}\+[\w.-]+", word):
                raise ReleaseError("unclassified PDF Unicode-map operator/name")
        for block in re.findall(r"\d+\s+beginbf(?:char|range)(.*?)endbf(?:char|range)", text, re.S):
            for value in re.findall(r"<([0-9a-fA-F]+)>", block):
                if len(value) >= 4 and len(value) % 4 == 0:
                    self.policy.audit(bytes.fromhex(value).decode("utf-16-be"))

    def audit_truetype_font(self, data: bytes) -> None:
        if len(data) < 12 or data[:4] != b"\x00\x01\x00\x00":
            raise ReleaseError("unclassified PDF font program")
        count = struct.unpack_from(">H", data, 4)[0]
        if not 1 <= count <= 32 or 12 + count * 16 > len(data):
            raise ReleaseError("invalid TrueType table directory")
        allowed = {
            b"OS/2",
            b"cmap",
            b"cvt ",
            b"fpgm",
            b"gasp",
            b"glyf",
            b"head",
            b"hhea",
            b"hmtx",
            b"loca",
            b"maxp",
            b"name",
            b"post",
            b"prep",
        }
        tables: dict[bytes, bytes] = {}
        intervals: list[tuple[int, int]] = [(0, 12 + count * 16)]
        for index in range(count):
            tag, _, offset, length = struct.unpack_from(">4sIII", data, 12 + index * 16)
            if tag not in allowed or tag in tables or offset + length > len(data):
                raise ReleaseError("unclassified or invalid TrueType table")
            tables[tag] = data[offset : offset + length]
            intervals.append((offset, offset + length))
        end = 0
        for start, stop in sorted(intervals):
            if start < end or any(data[end:start]):
                raise ReleaseError("overlapping or unexplained TrueType bytes")
            end = stop
        if any(data[end:]):
            raise ReleaseError("unexplained trailing TrueType bytes")
        required = {b"head", b"hhea", b"hmtx", b"maxp", b"loca", b"glyf", b"name", b"cmap", b"post"}
        if not required.issubset(tables):
            raise ReleaseError("incomplete TrueType font")
        head, maxp, hhea = tables[b"head"], tables[b"maxp"], tables[b"hhea"]
        if len(head) != 54 or len(maxp) < 6 or len(hhea) != 36:
            raise ReleaseError("invalid TrueType numeric header")
        if struct.unpack_from(">I", head, 12)[0] != 0x5F0F3CF5:
            raise ReleaseError("invalid TrueType signature")
        glyphs = struct.unpack_from(">H", maxp, 4)[0]
        metrics = struct.unpack_from(">H", hhea, 34)[0]
        format_ = struct.unpack_from(">h", head, 50)[0]
        if format_ not in (0, 1) or not 1 <= metrics <= glyphs:
            raise ReleaseError("invalid TrueType glyph metrics")
        width = 2 if format_ == 0 else 4
        loca = tables[b"loca"]
        if len(loca) != (glyphs + 1) * width:
            raise ReleaseError("invalid TrueType glyph index")
        offsets = [
            struct.unpack_from(">H" if width == 2 else ">I", loca, i * width)[0]
            * (2 if width == 2 else 1)
            for i in range(glyphs + 1)
        ]
        if offsets != sorted(offsets) or offsets[-1] > len(tables[b"glyf"]):
            raise ReleaseError("invalid TrueType glyph boundaries")
        if len(tables[b"hmtx"]) != metrics * 4 + (glyphs - metrics) * 2:
            raise ReleaseError("invalid TrueType metric length")
        names = tables[b"name"]
        if len(names) < 6:
            raise ReleaseError("invalid TrueType names")
        name_format, records, strings = struct.unpack_from(">HHH", names)
        if name_format != 0 or strings < 6 + records * 12 or strings > len(names):
            raise ReleaseError("unclassified TrueType name-table layout")
        for index in range(records):
            platform, encoding, _, _, length, offset = struct.unpack_from(
                ">HHHHHH", names, 6 + index * 12
            )
            if strings + offset + length > len(names):
                raise ReleaseError("invalid TrueType name record")
            value = names[strings + offset : strings + offset + length]
            if platform in (0, 3):
                text = value.decode("utf-16-be")
            elif platform == 1 and encoding == 0:
                text = value.decode("mac_roman")
            else:
                raise ReleaseError("unclassified TrueType name encoding")
            if self.policy.text(text) != text:
                raise ReleaseError("private TrueType font name requires a verified editor")
        for value in re.findall(rb"[\x20-\x7e]{4,}", data):
            self.policy.audit(value.decode("ascii"))
        self.counts["validated_truetype_tables"] += len(tables)

    def transform(self, data: bytes, name: str) -> bytes:
        self.policy.audit(self.policy.text(name), filename=True)
        suffix = ".rels" if name.endswith(".rels") else Path(name).suffix.lower()
        self.counts["format:" + (suffix or Path(name).name)] += 1
        if suffix == ".json":
            return self.json_data(data)
        if suffix in OFFICE_SUFFIXES or suffix == ".zip":
            return self.zip_data(data, name, office=suffix in OFFICE_SUFFIXES)
        if suffix == ".pdf":
            return self.pdf_data(data)
        if suffix == ".bin" and re.fullmatch(r"(?:ppt|word|xl)/printerSettings/[^/]+\.bin", name):
            return self.printer_data(data, name)
        if suffix in TEXT_SUFFIXES or Path(name).name in TEXT_NAMES:
            if suffix in {".xml", ".rels"}:
                return self.xml_data(data, name, office=False)
            text, encoding = read_text(data)
            public = self.policy.text(text, python_source=suffix == ".py")
            if suffix in {".trec", ".csv", ".ps1"}:
                number = re.compile(
                    r"(?<![\w.-])[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?![\w.-])"
                )
                numeric_tokens = number.findall(text)
                if numeric_tokens != number.findall(public):
                    raise ReleaseError("plain-text numeric token invariant changed")
                self.counts["validated_numeric_text_files"] += 1
                self.counts["plain_text_numeric_tokens"] += len(numeric_tokens)
            if suffix == ".html" and re.search(
                r"(?i:<\s*(?:img|svg|script|iframe|object|embed)\b)", public
            ):
                raise ReleaseError("unclassified active/image HTML payload")
            if suffix == ".py":
                import ast

                parsed = ast.parse(public, filename="public-producer.py")
                self.counts["validated_python_sources"] += 1
                self.counts["python_numeric_and_null_constants"] += sum(
                    isinstance(node, ast.Constant)
                    and (isinstance(node.value, (int, float, bool)) or node.value is None)
                    for node in ast.walk(parsed)
                )
            if public == text:
                return data
            return public.encode(encoding)
        raise ReleaseError("unsupported/unclassified file format")

    def printer_data(self, data: bytes, name: str) -> bytes:
        if len(data) < 4 or struct.unpack_from("<I", data)[0] != 2:
            raise ReleaseError("unclassified printer metadata framing")
        offset = 4
        sections: list[bytes] = []
        for expected_kind in (1, 2):
            if offset + 8 > len(data):
                raise ReleaseError("truncated printer metadata header")
            kind, size = struct.unpack_from("<II", data, offset)
            offset += 8
            if kind != expected_kind or size > 1024 * 1024 or offset + size > len(data):
                raise ReleaseError("unclassified printer metadata section")
            original_data = data[offset : offset + size]
            offset += size
            if not original_data.startswith(b"<?xml"):
                raise ReleaseError("non-XML printer metadata section")
            original = plistlib.loads(original_data)
            public = self.policy.structured(original)
            numeric = numeric_shape(original)
            if numeric != numeric_shape(public):
                raise ReleaseError("printer metadata numeric/shape invariant changed")
            public_data = (
                original_data
                if original == public
                else plistlib.dumps(public, fmt=plistlib.FMT_XML, sort_keys=False)
            )
            public_data = self.xml_data(public_data, name, office=False)
            if numeric != numeric_shape(plistlib.loads(public_data)):
                raise ReleaseError("serialized printer metadata invariant changed")
            sections.append(struct.pack("<II", kind, len(public_data)) + public_data)
            self.counts["printer_metadata_sections"] += 1
            self.counts["printer_metadata_numeric_values"] += numeric[1]
        if offset != len(data):
            raise ReleaseError("unclassified printer metadata trailing bytes")
        self.counts["validated_printer_metadata"] += 1
        return struct.pack("<I", 2) + b"".join(sections)

    def database(self, source: Path, target: Path) -> None:
        original = sqlite3.connect(source.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        public = sqlite3.connect(target)
        try:
            original.execute("PRAGMA temp_store=MEMORY")
            public.execute("PRAGMA temp_store=MEMORY")
            schemas = original.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL "
                "AND name NOT LIKE 'sqlite_%' ORDER BY type='table' DESC"
            ).fetchall()
            for kind, name, sql in schemas:
                if kind not in {"table", "index", "view"} or "VIRTUAL TABLE" in sql.upper():
                    raise ReleaseError("unsupported SQLite schema")
                if self.policy.text(sql) != sql:
                    raise ReleaseError("private identifier in SQLite schema")
                if kind != "table":
                    continue
                public.execute(sql)
                quoted = '"' + name.replace('"', '""') + '"'
                columns = [r[1] for r in original.execute(f"PRAGMA table_info({quoted})")]
                rows = original.execute(f"SELECT * FROM {quoted}")
                insert = f"INSERT INTO {quoted} VALUES ({','.join('?' for _ in columns)})"
                numeric_before = hashlib.sha256()
                numeric_after = hashlib.sha256()
                for row in rows:
                    values: list[Any] = []
                    for key, value in zip(columns, row, strict=True):
                        if isinstance(value, str):
                            values.append(self.policy.structured(value, key))
                            self.counts["database_text_cells"] += 1
                        elif isinstance(value, bytes):
                            # Existing ledger BLOBs are UTF JSON; no opaque-byte replacement.
                            values.append(self.json_data(value))
                            self.counts["database_json_blobs"] += 1
                        else:
                            values.append(value)
                            numeric_before.update(repr(value).encode())
                            self.counts["database_numeric_or_null_cells"] += 1
                    for value in values:
                        if not isinstance(value, (str, bytes)):
                            numeric_after.update(repr(value).encode())
                    public.execute(insert, values)
                    self.database_rows += 1
                if numeric_before.digest() != numeric_after.digest():
                    raise ReleaseError("database numeric invariant changed")
                count = public.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
                original_count = original.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
                if count != original_count:
                    raise ReleaseError("database row invariant changed")
            for kind, _, sql in schemas:
                if kind != "table":
                    public.execute(sql)
            sequence = original.execute(
                "SELECT name FROM sqlite_master WHERE name='sqlite_sequence'"
            ).fetchone()
            if sequence:
                for name, value in original.execute("SELECT name,seq FROM sqlite_sequence"):
                    public.execute("DELETE FROM sqlite_sequence WHERE name=?", (name,))
                    public.execute("INSERT INTO sqlite_sequence VALUES (?,?)", (name, value))
            version = original.execute("PRAGMA user_version").fetchone()[0]
            public.execute(f"PRAGMA user_version={version}")
            public.commit()
            if public.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ReleaseError("rebuilt database integrity failure")
            self.counts["database_integrity_checks"] += 1
            public.execute("VACUUM")
        finally:
            original.close()
            public.close()
        self.counts["format:.sqlite3"] += 1
        self.counts["rebuilt_databases"] += 1

    def emit(self, source: Path, relative: str, root: Path) -> None:
        if (
            source.is_symlink()
            or source.stat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ReleaseError("linked source candidate")
        relative = safe_name(self.policy.text(relative))
        self.policy.audit(relative, filename=True)
        if any(
            term in relative.lower()
            for term in (
                ".git/",
                "__pycache__/",
                "example_layout_exec_presentation",
                "executive-presentation",
            )
        ):
            raise ReleaseError("excluded source candidate reached exporter")
        target = root.joinpath(*PurePosixPath(relative).parts)
        if target.exists():
            raise ReleaseError("output path collision")
        target.parent.mkdir(parents=True, exist_ok=True)
        database = source.suffix.lower() == ".sqlite3"
        data = b"" if database else source.read_bytes()
        before = file_hash(source) if database else sha256(data)
        signature = (
            before,
            source.suffix.lower() or source.name,
            len(self.policy.identities),
            len(self.policy.resources),
            len(self.policy.replacements),
        )
        dimensions = (
            "json_documents",
            "numeric_values",
            "database_rows",
            "xml_numeric_nodes",
            "xml_numeric_attributes",
        )
        if signature in self.emitted_cache:
            previous, after, counts, images, values = self.emitted_cache[signature]
            if previous.is_symlink() or previous.is_junction():
                raise ReleaseError("linked public reuse candidate")
            shutil.copyfile(previous, target)
            self.counts.update(counts)
            self.images.update(images)
            for attribute, value in zip(dimensions, values, strict=True):
                setattr(self, attribute, getattr(self, attribute) + value)
            self.counts["reused_emitted_source_contents"] += 1
        else:
            previous_counts = self.counts.copy()
            previous_images = self.images.copy()
            previous_values = tuple(getattr(self, attribute) for attribute in dimensions)
            if database:
                self.database(source, target)
                after = file_hash(target)
            else:
                public = self.cached_transform(data, relative)
                after = sha256(public)
                target.write_bytes(public)
            if signature[2:] == (
                len(self.policy.identities),
                len(self.policy.resources),
                len(self.policy.replacements),
            ):
                self.emitted_cache[signature] = (
                    target,
                    after,
                    Counter(
                        {
                            key: value
                            for key, value in (self.counts - previous_counts).items()
                            if not key.startswith("distinct_")
                        }
                    ),
                    self.images - previous_images,
                    tuple(
                        getattr(self, attribute) - value
                        for attribute, value in zip(dimensions, previous_values, strict=True)
                    ),
                )
            self.counts["distinct_transformed_source_contents"] += 1
        self.entries.append(
            {
                "path": relative,
                "bytes": target.stat().st_size,
                "sha256": after,
                "status": "unchanged" if before == after else "public_derivative",
                "historical_source_sha256": before,
            }
        )
        self.counts["source_files"] += 1

    def frozen_distribution(self, source: Path, relative: str, root: Path) -> None:
        if (
            source.is_symlink()
            or source.is_junction()
            or source.stat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or not source.is_file()
        ):
            raise ReleaseError("nonregular frozen distribution source")
        self.exclusions.append(
            {
                "path": relative,
                "reason": "Original built distribution excluded; "
                "sanitized frozen source and dependency declarations expanded separately.",
            }
        )
        if source.suffix == ".whl":
            # The matching sdist supplies all sources; wheel metadata is retained separately.
            with zipfile.ZipFile(source) as archive:
                for info in archive.infolist():
                    if info.is_dir() or ".dist-info/" not in info.filename:
                        continue
                    if info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16):
                        raise ReleaseError("linked or encrypted wheel member")
                    self.emit_bytes(
                        archive.read(info), safe_name(relative + ".expanded/" + info.filename), root
                    )
            return
        with tarfile.open(source, "r:gz") as archive:
            for tar_info in archive:
                if not tar_info.isfile():
                    if tar_info.isdir():
                        continue
                    raise ReleaseError("nonregular frozen distribution member")
                name = safe_name(tar_info.name)
                parts = PurePosixPath(name).parts[1:]
                if not parts:
                    raise ReleaseError("invalid source distribution layout")
                member = "/".join(parts)
                stream = archive.extractfile(tar_info)
                if stream is None:
                    raise ReleaseError("missing source distribution member")
                self.emit_bytes(stream.read(), relative + ".expanded/" + member, root)

    def emit_bytes(self, data: bytes, relative: str, root: Path) -> None:
        relative = safe_name(self.policy.text(relative))
        self.policy.audit(relative, filename=True)
        if "example_layout_exec_presentation" in relative.lower():
            raise ReleaseError("forbidden historical customer deck")
        public = self.cached_transform(data, relative)
        target = root.joinpath(*PurePosixPath(relative).parts)
        if target.exists():
            raise ReleaseError("output member collision")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(public)
        self.entries.append(
            {
                "path": relative,
                "bytes": len(public),
                "sha256": sha256(public),
                "status": "unchanged" if public == data else "public_derivative",
                "historical_source_sha256": sha256(data),
            }
        )
        self.counts["expanded_distribution_members"] += 1

    def cached_transform(self, data: bytes, name: str) -> bytes:
        suffix = Path(name).suffix.lower()
        if suffix not in TEXT_SUFFIXES | OFFICE_SUFFIXES or len(data) > 32 * 1024 * 1024:
            return self.transform(data, name)
        self.policy.audit(self.policy.text(name))
        signature = (
            sha256(data),
            suffix,
            len(self.policy.identities),
            len(self.policy.resources),
            len(self.policy.replacements),
        )
        dimensions = (
            "json_documents",
            "numeric_values",
            "database_rows",
            "xml_numeric_nodes",
            "xml_numeric_attributes",
        )
        if signature in self.content_cache:
            public, counts, images, values = self.content_cache[signature]
            self.counts.update(counts)
            self.images.update(images)
            for attribute, value in zip(dimensions, values, strict=True):
                setattr(self, attribute, getattr(self, attribute) + value)
            self.counts["reused_identical_source_contents"] += 1
            return public
        previous_counts = self.counts.copy()
        previous_images = self.images.copy()
        previous_values = tuple(getattr(self, attribute) for attribute in dimensions)
        public = self.transform(data, name)
        if signature[2:] != (
            len(self.policy.identities),
            len(self.policy.resources),
            len(self.policy.replacements),
        ):
            return public
        limit = 256 * 1024 * 1024
        while self.content_cache and self.content_cache_bytes + len(public) > limit:
            oldest = next(iter(self.content_cache))
            self.content_cache_bytes -= len(self.content_cache.pop(oldest)[0])
        self.content_cache[signature] = (
            public,
            self.counts - previous_counts,
            self.images - previous_images,
            tuple(
                getattr(self, attribute) - previous
                for attribute, previous in zip(dimensions, previous_values, strict=True)
            ),
        )
        self.content_cache_bytes += len(public)
        self.counts["distinct_cached_source_contents"] += 1
        return public

    def verify(self, root: Path, archive_directory: Path | None = None) -> None:
        verifier = Exporter(self.policy)
        with ExitStack() as stack:
            archives = (
                {
                    name: stack.enter_context(zipfile.ZipFile(archive_directory / name))
                    for name in {entry["archive"] for entry in self.entries}
                }
                if archive_directory is not None
                else {}
            )
            for index, entry in enumerate(self.entries, 1):
                self.verification_path = entry["path"]
                path = root.joinpath(*PurePosixPath(entry["path"]).parts)
                public = (
                    archives[entry["archive"]].read(safe_name(entry["path"]))
                    if archives
                    else path.read_bytes()
                )
                if sha256(public) != entry["sha256"] or len(public) != entry["bytes"]:
                    raise ReleaseError("public checksum verification failed")
                self.policy.audit(entry["path"], filename=True)
                if path.suffix == ".sqlite3":
                    # SQL reads the reconstructed payload only after proving byte identity
                    # with the member actually decompressed from the final archive.
                    if archive_directory is not None and file_hash(path) != sha256(public):
                        raise ReleaseError("archived database/payload identity failure")
                    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
                    try:
                        connection.execute("PRAGMA temp_store=MEMORY")
                        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise ReleaseError("public database integrity failed")
                        public_hosts: set[str] = set()
                        roots = [1] + [
                            row[0]
                            for row in connection.execute(
                                "SELECT rootpage FROM sqlite_master WHERE rootpage > 1"
                            )
                        ]
                        for (name,) in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ):
                            quoted = '"' + name.replace('"', '""') + '"'
                            for row in connection.execute(f"SELECT * FROM {quoted}"):
                                for value in row:
                                    if isinstance(value, str):
                                        self.policy.audit(value)
                                    elif isinstance(value, bytes):
                                        original = parse_json(read_text(value)[0])
                                        if verifier.policy.structured(original) != original:
                                            raise ReleaseError("database BLOB was not idempotent")
                                    if isinstance(value, (str, bytes)):
                                        text = (
                                            value
                                            if isinstance(value, str)
                                            else read_text(value)[0]
                                        )
                                        if any(
                                            suffix in text.casefold()
                                            for suffix in (
                                                ".windows.net",
                                                ".azure.com",
                                                ".azurewebsites.net",
                                            )
                                        ):
                                            public_hosts.update(
                                                host[0].casefold()
                                                for host in AZURE_HOST.finditer(text)
                                                if host[1].casefold().startswith("example")
                                            )
                        self.counts["classified_sqlite_overflow_endpoint_fragments"] += (
                            audit_sqlite_residue(public, self.policy, roots, public_hosts)
                        )
                        self.counts["verified_database_files"] += 1
                        print(
                            json.dumps(
                                {
                                    "phase": "final_database_validation",
                                    "verified_databases": self.counts["verified_database_files"],
                                }
                            ),
                            flush=True,
                        )
                    finally:
                        connection.close()
                elif verifier.transform(public, entry["path"]) != public:
                    raise ReleaseError("sanitization was not idempotent")
                if index % 1000 == 0:
                    print(
                        json.dumps({"phase": "final_validation", "verified_files": index}),
                        flush=True,
                    )
        self.counts["verified_export_files"] = len(self.entries)
        if archive_directory is not None:
            self.counts["verified_final_archive_files"] = len(self.entries)

    def pack(self, root: Path, output: Path) -> list[dict[str, Any]]:
        archives: list[dict[str, Any]] = []
        groups: list[list[dict[str, Any]]] = []
        group: list[dict[str, Any]] = []
        size = 0
        for entry in sorted(self.entries, key=lambda item: item["path"]):
            # ZIP overhead and potentially incompressible bytes count toward the cap.
            estimated = entry["bytes"] + len(entry["path"].encode()) * 2 + 2048
            if estimated >= MAX_ARCHIVE_BYTES:
                raise ReleaseError("single member exceeds release size limit")
            if size + estimated >= MAX_ARCHIVE_BYTES and group:
                groups.append(group)
                group, size = [], 0
            group.append(entry)
            size += estimated
        if group:
            groups.append(group)
        for index, entries in enumerate(groups, 1):
            name = f"experiments-{index:03d}.zip"
            target = output / name
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for entry in entries:
                    path = root.joinpath(*PurePosixPath(entry["path"]).parts)
                    archive.write(path, entry["path"])
                    entry["archive"] = name
            if target.stat().st_size >= MAX_ARCHIVE_BYTES:
                raise ReleaseError("compressed archive exceeds release size limit")
            with zipfile.ZipFile(target) as archive:
                if len(archive.infolist()) != len(entries):
                    raise ReleaseError("final archive membership failure")
            archives.append(
                {
                    "name": name,
                    "bytes": target.stat().st_size,
                    "sha256": file_hash(target),
                    "files": len(entries),
                    "url": "https://github.com/tsalles/ai-search-evaluation/releases/download/"
                    f"v0.1.0-experiments/{name}",
                }
            )
        return archives


def discover_identifiers(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    if (
        path.is_symlink()
        or path.is_junction()
        or path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise ReleaseError("linked discovery candidate")
    learned = Policy({}, [], [])
    with path.open("rb") as header:
        prefix = header.read(4)
    encoding = "utf-16" if prefix.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    with path.open("r", encoding=encoding, errors="strict") as stream:
        previous = ""
        while block := stream.read(1024 * 1024):
            learned.learn(previous + block)
            previous = block[-256:]
    return learned.identities, learned.resources


def discovery_digest(path: Path) -> str:
    if (
        path.is_symlink()
        or path.is_junction()
        or path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise ReleaseError("linked discovery candidate")
    return file_hash(path)


def validate_destinations(config: dict[str, Any], output: Path, manifest_path: Path) -> None:
    selected_sources = {Path(item["source"]).resolve() for item in config["roots"]}
    selected_sources.update(
        parent.resolve()
        for parent in {
            Path(item["source"]).parent
            for category in ("scripts", "files", "distributions")
            for item in config.get(category, [])
        }
    )
    if any(
        destination.resolve().is_relative_to(source)
        for source in selected_sources
        for destination in (output, manifest_path)
    ):
        raise ReleaseError("release output must not modify a selected source directory")


def publish_verified_report(
    exporter: Exporter, report: dict[str, Any], output: Path, manifest_path: Path
) -> None:
    report["status"] = "verified_local_derivative"
    report["counts"] = dict(exporter.counts)
    for key in (
        "config_sha256",
        "policy_sha256",
        "approved_public_identity_values",
        "distribution_source_sha256",
    ):
        report.pop(key, None)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    exporter.policy.audit(serialized)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(serialized, encoding="utf-8")
    (output / "asset-manifest.json").write_text(serialized, encoding="utf-8")
    (output / "BLOCKED.json").unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "status": report["status"],
                "counts": report["counts"],
                "invariants": report["invariants"],
                "archives": [
                    {key: value for key, value in archive.items() if key != "url"}
                    for archive in report["archives"]
                ],
            }
        ),
        flush=True,
    )


def resume_verification(
    config_path: Path,
    policy_path: Path,
    output: Path,
    manifest_path: Path,
    inventory: tuple[dict[str, str], dict[str, str]],
) -> None:
    checkpoint = output / "verification-checkpoint.json"
    if checkpoint.is_symlink() or checkpoint.is_junction():
        raise ReleaseError("linked verification checkpoint")
    report = json.loads(checkpoint.read_text(encoding="utf-8"))
    if (
        report["status"] != "unverified_local_derivative"
        or report["config_sha256"] != file_hash(config_path)
        or report["policy_sha256"] != file_hash(policy_path)
    ):
        raise ReleaseError("verification checkpoint input changed")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if report["distribution_source_sha256"] != [
        file_hash(Path(item["source"])) for item in config.get("distributions", [])
    ]:
        raise ReleaseError("frozen distribution changed after transformation")
    validate_destinations(config, output, manifest_path)
    policy = Policy.load(policy_path)
    policy.identities.update(inventory[0])
    policy.resources.update(inventory[1])
    policy.approved_identity_values.update(report["approved_public_identity_values"])
    exporter = Exporter(policy)
    exporter.entries = report["files"]
    exporter.counts.update(report["counts"])
    for archive in report["archives"]:
        name = safe_name(archive["name"])
        if not re.fullmatch(r"experiments-\d{3}\.zip", name):
            raise ReleaseError("invalid checkpoint archive name")
        path = output / name
        if (
            path.is_symlink()
            or path.is_junction()
            or path.stat().st_size != archive["bytes"]
            or file_hash(path) != archive["sha256"]
        ):
            raise ReleaseError("checkpoint archive changed")
    try:
        exporter.verify(output / "payload", output)
        publish_verified_report(exporter, report, output, manifest_path)
    except (
        ReleaseError,
        UnicodeError,
        json.JSONDecodeError,
        sqlite3.Error,
        zipfile.BadZipFile,
        tarfile.TarError,
        PyPdfError,
        SyntaxError,
        plistlib.InvalidFileException,
        ET.ParseError,
        OSError,
    ) as error:
        failure = {
            "status": "blocked",
            "category": type(error).__name__,
            "reason": str(error) if isinstance(error, ReleaseError) else "parser or IO failure",
            "last_public_path": exporter.verification_path,
            "counts": dict(exporter.counts),
        }
        (output / "BLOCKED.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
        print(json.dumps(failure), flush=True)
        raise ReleaseError("checkpoint verification blocked; see local BLOCKED.json") from None


def run(
    config_path: Path,
    policy_path: Path,
    output: Path,
    manifest_path: Path,
    inventory: tuple[dict[str, str], dict[str, str]] | None = None,
) -> None:
    if output.exists():
        raise ReleaseError("output must be a new named directory")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    validate_destinations(config, output, manifest_path)
    output.mkdir(parents=True)
    root = output / "payload"
    root.mkdir()
    exporter = Exporter(Policy.load(policy_path))
    if inventory is not None:
        exporter.policy.identities.update(inventory[0])
        exporter.policy.resources.update(inventory[1])
    direct_files = config.get("scripts", []) + config.get("files", [])
    try:
        # Discover categorized identifiers before replacing cross-file references. This is
        # a cheap lexical inventory, not a confidentiality clearance pass.
        selected_roots: list[tuple[dict[str, str], list[Path]]] = []
        discovery_files: list[Path] = []
        for item in config["roots"]:
            source = Path(item["source"])
            if source.is_symlink() or source.is_junction():
                raise ReleaseError("linked source root")
            selected: list[Path] = []
            for path in source.rglob("*"):
                if path.is_symlink() or path.is_junction():
                    raise ReleaseError("linked source directory/member")
                if path.is_file():
                    selected.append(path)
                    if path.suffix.lower() in TEXT_SUFFIXES:
                        discovery_files.append(path)
            selected_roots.append((item, sorted(selected)))
        discovery_files.extend(
            Path(item["source"])
            for item in direct_files
            if Path(item["source"]).suffix.lower() in TEXT_SUFFIXES
        )
        discovered_contents: set[str] = set()
        with ThreadPoolExecutor(max_workers=8) as executor:
            for start in range(0, len(discovery_files), 64):
                batch = discovery_files[start : start + 64]
                unique_files = []
                for path, digest in zip(batch, executor.map(discovery_digest, batch), strict=True):
                    if digest not in discovered_contents:
                        discovered_contents.add(digest)
                        unique_files.append(path)
                for identities, resources in executor.map(discover_identifiers, unique_files):
                    exporter.policy.identities.update(identities)
                    exporter.policy.resources.update(resources)
                if (start + 64) // 1000 != start // 1000:
                    print(
                        json.dumps(
                            {"phase": "identifier_inventory", "text_candidates": start + 64}
                        ),
                        flush=True,
                    )
        for item in config.get("distributions", []):
            path = Path(item["source"])
            if path.name.endswith(".tar.gz"):
                with tarfile.open(path, "r:gz") as archive:
                    for member in archive:
                        if member.isfile():
                            binary_stream = archive.extractfile(member)
                            if binary_stream is None:
                                raise ReleaseError("missing frozen discovery member")
                            text, _ = read_text(binary_stream.read())
                            exporter.policy.learn(text)
        print(
            json.dumps(
                {
                    "phase": "categorized_identifiers",
                    "text_candidates": len(discovery_files),
                    "distinct_text_contents": len(discovered_contents),
                    "identities": len(exporter.policy.identities),
                    "resources": len(exporter.policy.resources),
                }
            ),
            flush=True,
        )
        for item, selected in selected_roots:
            source = Path(item["source"])
            for path in selected:
                exporter.emit(
                    path, item["public"] + "/" + path.relative_to(source).as_posix(), root
                )
                if exporter.counts["source_files"] % 1000 == 0:
                    print(
                        json.dumps(
                            {
                                "phase": "transformation",
                                "source_files": exporter.counts["source_files"],
                            }
                        ),
                        flush=True,
                    )
        for item in direct_files:
            exporter.emit(Path(item["source"]), item["public"], root)
            if len(direct_files) < 100 or exporter.counts["source_files"] % 1000 == 0:
                print(
                    json.dumps(
                        {
                            "phase": "transformed_root",
                            "source_files": exporter.counts["source_files"],
                        }
                    ),
                    flush=True,
                )
        for item in config.get("distributions", []):
            exporter.frozen_distribution(Path(item["source"]), item["public"], root)
        archives = exporter.pack(root, output)
        report: dict[str, Any] = {
            "schema_version": 1,
            "status": "unverified_local_derivative",
            "config_sha256": file_hash(config_path),
            "policy_sha256": file_hash(policy_path),
            "approved_public_identity_values": sorted(exporter.policy.identities.values()),
            "distribution_source_sha256": [
                file_hash(Path(item["source"])) for item in config.get("distributions", [])
            ],
            "release_tag": "v0.1.0-experiments",
            "historical_seal_semantics": "All embedded legacy hashes, seals, RECORD entries and "
            "signature claims are historical opaque identifiers, not verification of public bytes. "
            "Only this manifest's sha256 fields verify the public derivative.",
            "producer_version_caveat": {
                "path": "evaluations/saas-confirmation-study/study-0e518aae/"
                "search-validation-proof-v2.json",
                "status": "unresolved_historical_producer_version",
                "description": "The recorded independent_saas_audit.py hash differs from the "
                "available producer. No historical reproducibility claim is made.",
            },
            "counts": dict(exporter.counts),
            "invariants": {
                "json_documents": exporter.json_documents,
                "json_numeric_and_null_values": exporter.numeric_values,
                "sqlite_rows": exporter.database_rows,
                "xml_numeric_nodes": exporter.xml_numeric_nodes,
                "xml_numeric_attributes": exporter.xml_numeric_attributes,
                "unchanged_files": sum(e["status"] == "unchanged" for e in exporter.entries),
                "public_derivatives": sum(
                    e["status"] == "public_derivative" for e in exporter.entries
                ),
            },
            "image_coverage": dict(exporter.images),
            "visual_limitations": "Only explicitly approved image hashes allowed; standard "
            "thumbnail metadata removed. No OCR claim. Unknown images block export.",
            "archives": archives,
            "exclusions": exporter.exclusions,
            "files": exporter.entries,
        }
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        exporter.policy.audit(serialized)
        (output / "verification-checkpoint.json").write_text(serialized, encoding="utf-8")
        print(
            json.dumps(
                {"phase": "transformation_checkpoint", "files": len(exporter.entries)}
            ),
            flush=True,
        )
        exporter.verify(root, output)
        publish_verified_report(exporter, report, output, manifest_path)
    except (
        ReleaseError,
        UnicodeError,
        json.JSONDecodeError,
        sqlite3.Error,
        zipfile.BadZipFile,
        tarfile.TarError,
        PyPdfError,
        SyntaxError,
        plistlib.InvalidFileException,
        ET.ParseError,
        OSError,
    ) as error:
        # Unverified derivatives are quarantined locally, never given a release manifest.
        failure = {
            "status": "blocked",
            "category": type(error).__name__,
            "reason": str(error) if isinstance(error, ReleaseError) else "parser or IO failure",
            "processed_files": len(exporter.entries),
            "counts": dict(exporter.counts),
            "last_public_path": exporter.verification_path
            or (exporter.entries[-1]["path"] if exporter.entries else None),
        }
        (output / "BLOCKED.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
        print(json.dumps(failure))
        raise ReleaseError("export blocked; see local BLOCKED.json") from None


def run_parallel(
    config_path: Path,
    policy_path: Path,
    output: Path,
    manifest_path: Path,
    workers: int,
    *,
    resume: bool = False,
) -> None:
    if not 2 <= workers <= 4:
        raise ReleaseError("parallel workers must be between two and four")
    if output.exists() and not resume:
        raise ReleaseError("output must be a new named directory")
    if resume and (
        not output.is_dir()
        or output.is_symlink()
        or output.is_junction()
        or (output / "asset-manifest.json").exists()
    ):
        raise ReleaseError("resume requires an uncleared regular output directory")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    validate_destinations(config, output, manifest_path)
    policy = Policy.load(policy_path)
    selected: list[tuple[Path, str]] = []
    for item in config["roots"]:
        source = Path(item["source"])
        if source.is_symlink() or source.is_junction():
            raise ReleaseError("linked source root")
        for path in source.rglob("*"):
            if path.is_symlink() or path.is_junction():
                raise ReleaseError("linked source directory/member")
            if path.is_file():
                selected.append((path, item["public"] + "/" + path.relative_to(source).as_posix()))
    selected.extend(
        (Path(item["source"]), item["public"])
        for category in ("scripts", "files")
        for item in config.get(category, [])
    )
    groups: dict[tuple[str, str], list[tuple[Path, str]]] = {}
    source_bytes = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        for start in range(0, len(selected), 64):
            batch = selected[start : start + 64]
            digests = executor.map(discovery_digest, (path for path, _ in batch))
            for index, ((path, relative), digest) in enumerate(
                zip(batch, digests, strict=True), start + 1
            ):
                source_bytes += path.stat().st_size
                signature = (digest, path.suffix.lower() or path.name)
                groups.setdefault(signature, []).append((path, relative))
                if index % 10000 == 0:
                    print(
                        json.dumps({"phase": "source_hash_inventory", "files": index}),
                        flush=True,
                    )
    if not groups:
        raise ReleaseError("empty selected source scope")
    workers = min(workers, len(groups))
    discovery = [
        group[0][0] for group in groups.values() if group[0][0].suffix.lower() in TEXT_SUFFIXES
    ]
    with ThreadPoolExecutor(max_workers=8) as executor:
        for identities, resources in executor.map(discover_identifiers, discovery):
            policy.identities.update(identities)
            policy.resources.update(resources)
    for item in config.get("distributions", []):
        path = Path(item["source"])
        if path.name.endswith(".tar.gz"):
            with tarfile.open(path, "r:gz") as archive:
                for member in archive:
                    if not member.isfile():
                        if member.isdir():
                            continue
                        raise ReleaseError("nonregular frozen discovery member")
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise ReleaseError("missing frozen discovery member")
                    policy.learn(read_text(stream.read())[0])
    print(
        json.dumps(
            {
                "phase": "parallel_inventory",
                "source_files": len(selected),
                "distinct_source_contents_and_formats": len(groups),
                "identities": len(policy.identities),
                "resources": len(policy.resources),
            }
        ),
        flush=True,
    )
    expected: dict[str, str] = {}
    seen: set[str] = set()
    partitions: list[list[dict[str, str]]] = [[] for _ in range(workers)]
    weights = [0] * workers
    weighted_groups = []
    for signature, group in groups.items():
        path = group[0][0]
        multiplier = (
            15 if path.suffix == ".sqlite3" else (6 if path.suffix in OFFICE_SUFFIXES else 2)
        )
        cost = path.stat().st_size * multiplier + len(group) * 16384
        weighted_groups.append((cost, signature, group))
    for cost, signature, group in sorted(weighted_groups, reverse=True):
        partition = min(range(workers), key=lambda index: weights[index])
        weights[partition] += cost
        for path, relative in group:
            public = safe_name(policy.text(relative))
            if public.casefold() in seen:
                raise ReleaseError("duplicate public source path")
            seen.add(public.casefold())
            expected[public] = signature[0]
            partitions[partition].append({"source": str(path), "public": public})
    output.mkdir(parents=True, exist_ok=resume)
    control = output / "control"
    if control.is_symlink() or control.is_junction():
        raise ReleaseError("linked parallel control directory")
    control.mkdir(exist_ok=resume)
    reports = []
    inventory = (policy.identities, policy.resources)
    try:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for index, files in enumerate(partitions, 1):
                part_config = control / f"scope-{index:02d}.json"
                configured = json.dumps(
                    {
                        "roots": [],
                        "files": files,
                        "distributions": config.get("distributions", [])
                        if index == workers
                        else [],
                    }
                )
                if resume:
                    if part_config.read_text(encoding="utf-8") != configured:
                        raise ReleaseError("partition scope changed before resume")
                else:
                    part_config.write_text(configured, encoding="utf-8")
                part_output = output / f"part-{index:02d}"
                part_manifest = control / f"manifest-{index:02d}.json"
                future = executor.submit(
                    resume_verification if resume else run,
                    part_config,
                    policy_path,
                    part_output,
                    part_manifest,
                    inventory,
                )
                futures[future] = (index, part_output, part_manifest)
            for future in as_completed(futures):
                index, part_output, part_manifest = futures[future]
                future.result()
                report = json.loads(part_manifest.read_text(encoding="utf-8"))
                if report["status"] != "verified_local_derivative":
                    raise ReleaseError("uncleared parallel partition")
                reports.append((index, part_output, report))
                print(
                    json.dumps({"phase": "partition_verified", "partitions": len(reports)}),
                    flush=True,
                )
        counts: Counter[str] = Counter()
        invariants: Counter[str] = Counter()
        images: Counter[str] = Counter()
        files = []
        archives: list[dict[str, Any]] = []
        exclusions = []
        for _, part_output, report in sorted(reports):
            renamed = {}
            for archive in report["archives"]:
                name = f"experiments-{len(archives) + 1:03d}.zip"
                target = output / name
                if target.exists():
                    raise ReleaseError("combined archive path collision")
                (part_output / archive["name"]).rename(target)
                renamed[archive["name"]] = name
                updated = dict(archive, name=name)
                updated["url"] = (
                    "https://github.com/tsalles/ai-search-evaluation/releases/download/"
                    f"v0.1.0-experiments/{name}"
                )
                archives.append(updated)
            for entry in report["files"]:
                entry["archive"] = renamed[entry["archive"]]
                files.append(entry)
            counts.update(report["counts"])
            invariants.update(report["invariants"])
            images.update(report["image_coverage"])
            exclusions.extend(report["exclusions"])
        actual = {
            entry["path"]: entry["historical_source_sha256"]
            for entry in files
            if entry["path"] in expected
        }
        if actual != expected or len({entry["path"].casefold() for entry in files}) != len(files):
            raise ReleaseError("parallel source scope/hash or path invariant changed")
        merged = dict(reports[0][2])
        merged.update(
            counts=dict(counts),
            invariants=dict(invariants),
            image_coverage=dict(images),
            archives=archives,
            exclusions=exclusions,
            files=sorted(files, key=lambda e: e["path"]),
            selected_inputs={
                "direct_files": len(selected),
                "direct_bytes": source_bytes,
                "original_distribution_archives": len(config.get("distributions", [])),
                "original_distribution_bytes": sum(
                    Path(item["source"]).stat().st_size for item in config.get("distributions", [])
                ),
            },
            execution={
                "workers": workers,
                "partitioning": "Exact original-byte hash and format; identical contents adjacent.",
                "validation": "Every final archive member read, hash-checked "
                "and recursively assessed.",
            },
        )
        serialized = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
        policy.audit(serialized)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(serialized, encoding="utf-8")
        (output / "asset-manifest.json").write_text(serialized, encoding="utf-8")
        for private_scope in control.glob("scope-*.json"):
            private_scope.unlink()
        for part_manifest in control.glob("manifest-*.json"):
            part_manifest.unlink()
        for _, part_output, _ in reports:
            (part_output / "asset-manifest.json").unlink()
            (part_output / "verification-checkpoint.json").unlink(missing_ok=True)
            (part_output / "BLOCKED.json").unlink(missing_ok=True)
        (output / "BLOCKED.json").unlink(missing_ok=True)
        print(
            json.dumps(
                {
                    "status": merged["status"],
                    "files": len(files),
                    "counts": dict(counts),
                    "invariants": dict(invariants),
                    "archives": [
                        {key: value for key, value in archive.items() if key != "url"}
                        for archive in archives
                    ],
                },
                indent=2,
            ),
            flush=True,
        )
    except (ReleaseError, OSError, UnicodeError, json.JSONDecodeError):
        (output / "BLOCKED.json").write_text(
            json.dumps({"status": "blocked", "reason": "parallel export did not obtain clearance"}),
            encoding="utf-8",
        )
        raise ReleaseError("parallel export blocked; inspect partition BLOCKED.json") from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reverify checkpointed parallel archives without transforming sources again",
    )
    args = parser.parse_args()
    if args.workers == 1:
        if args.resume:
            raise ReleaseError("checkpoint resume requires parallel workers")
        run(args.config, args.policy, args.output, args.manifest)
    else:
        run_parallel(
            args.config,
            args.policy,
            args.output,
            args.manifest,
            args.workers,
            resume=args.resume,
        )


if __name__ == "__main__":
    main()
