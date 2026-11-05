import hashlib
import json
from collections import Counter
from datetime import date
from decimal import Decimal
from fractions import Fraction

from pydantic import JsonValue

from docgen.facts import normalized
from docgen.models import Content
from docgen.text import business_units


def shingles(text: str) -> set[str]:
    words = normalized(text).split()
    if not words:
        raise ValueError("Cannot compare empty business content.")
    return {" ".join(words[index:index + 5]) for index in range(max(1, len(words) - 4))}


def payload_fingerprint(content: Content) -> str:
    body: list[JsonValue] = []
    for block in content.blocks:
        table: JsonValue = None
        if block.table:
            rows: list[JsonValue] = []
            for row in block.table.rows:
                cells: list[JsonValue] = []
                for cell in row:
                    value: JsonValue
                    if isinstance(cell.value, Decimal):
                        value = format(cell.value.normalize(), "f")
                    elif isinstance(cell.value, date):
                        value = cell.value.isoformat()
                    elif isinstance(cell.value, str):
                        value = normalized(cell.value)
                    else:
                        value = cell.value
                    cells.append({"kind": cell.kind, "value": value})
                rows.append(cells)
            table = {
                "columns": [
                    {"name": normalized(column.name), "kind": column.kind,
                     "unit": normalized(column.unit) if column.unit else None}
                    for column in block.table.columns
                ],
                "rows": rows,
            }
        body.append({
            "kind": block.kind, "text": normalized(block.text) if block.text else None,
            "level": block.level,
            "items": [{"text": normalized(item.text), "level": item.level}
                      for item in block.items or ()],
            "table": table,
        })
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


class UniquenessIndex:
    def __init__(self, threshold: Decimal = Decimal("0.85")) -> None:
        if not threshold.is_finite() or not 0 < threshold <= 1:
            raise ValueError("Near-duplicate threshold must be in (0, 1].")
        self.threshold = Fraction(threshold)
        self._fingerprints: set[str] = set()
        self._sizes: list[int] = []
        self._postings: dict[str, set[int]] = {}

    def _similarity(self, values: set[str]) -> Fraction:
        counts: Counter[int] = Counter()
        for value in values:
            counts.update(self._postings.get(value, ()))
        return max((
            Fraction(overlap, len(values) + self._sizes[index] - overlap)
            for index, overlap in counts.items()
        ), default=Fraction(0))

    def check(self, content: Content) -> str:
        fingerprint = payload_fingerprint(content)
        if fingerprint in self._fingerprints:
            raise ValueError("Rejected exact normalized content duplicate.")
        if self.similarity(content) >= self.threshold:
            raise ValueError("Rejected lexical near duplicate.")
        return fingerprint

    def accept(self, content: Content) -> str:
        fingerprint = self.check(content)
        values = shingles(" ".join(business_units(content)[1:]))
        index = len(self._sizes)
        self._sizes.append(len(values))
        self._fingerprints.add(fingerprint)
        for value in values:
            self._postings.setdefault(value, set()).add(index)
        return fingerprint

    def similarity(self, content: Content) -> Fraction:
        return self._similarity(shingles(" ".join(business_units(content)[1:])))
