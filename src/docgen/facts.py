import re
import unicodedata
from datetime import date
from decimal import Decimal

from docgen.models import Content, Fact
from docgen.text import business_units, value_text
from docgen.units import unit_identity


def normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def display_decimal(token: str, locale: str) -> Decimal:
    if locale == "pt-BR":
        if re.fullmatch(r"[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?", token):
            return Decimal(token.replace(".", "").replace(",", "."))
        if re.fullmatch(r"[+-]?\d+\.\d+", token):
            return Decimal(token)
    elif locale == "en-US":
        if re.fullmatch(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", token):
            return Decimal(token.replace(",", ""))
        if re.fullmatch(r"[+-]?\d+,\d+", token):
            return Decimal(token.replace(",", "."))
    raise ValueError("Unsupported or ambiguous localized numeric display.")


def canonical_fact(fact: Fact, locale: str) -> Fact:
    if any(
        "{{" in text or "}}" in text
        for text in (
            fact.entity,
            fact.display,
            fact.unit or "",
            str(fact.value),
        )
    ):
        raise ValueError("Fact metadata cannot contain unresolved references.")
    display = fact.display.strip()
    value = fact.value
    if isinstance(value, bool):
        truth = {
            "true": True,
            "false": False,
            "sim": True,
            "nao": False,
            "n\u00e3o": False,
            "yes": True,
            "no": False,
        }
        if normalized(display) not in truth or truth[normalized(display)] != value:
            raise ValueError(f"Fact display contradicts its Boolean value: {fact.id}.")
    elif isinstance(value, Decimal):
        numbers = re.findall(r"[+-]?\d(?:[\d.,]*\d)?", display)
        if len(numbers) != 1 or display_decimal(numbers[0], locale) != value:
            raise ValueError(f"Fact display contradicts its numeric value: {fact.id}.")
    elif isinstance(value, date):
        if display not in {value.isoformat(), value.strftime("%d/%m/%Y")}:
            raise ValueError(f"Fact display contradicts its date value: {fact.id}.")
    elif normalized(display) != normalized(value):
        raise ValueError(f"Fact display contradicts its text value: {fact.id}.")
    canonical = value_text(value, locale) + (f" {fact.unit}" if fact.unit else "")
    return fact.model_copy(update={"display": canonical})


class FactRegistry:
    def __init__(self) -> None:
        self._facts: dict[tuple[str, str], list[Fact]] = {}

    def accept(self, content: Content) -> None:
        visible = normalized(" ".join(business_units(content)))
        pending = []
        for fact in content.facts:
            if normalized(fact.entity) not in visible:
                raise ValueError(f"Fact entity must be visible: {fact.id}.")
            if fact.valid_from or fact.valid_until:
                for bound in (fact.valid_from, fact.valid_until):
                    if bound is None or not any(
                        normalized(text) in visible
                        for text in (bound.isoformat(), value_text(bound, content.blueprint.locale))
                    ):
                        raise ValueError(f"Fact validity context must be visible: {fact.id}.")
            key = (normalized(fact.entity), fact.id)
            for previous in self._facts.get(key, []):
                if (previous.kind, previous.value, unit_identity(previous.unit)) == (
                    fact.kind,
                    fact.value,
                    unit_identity(fact.unit),
                ):
                    continue
                disjoint = (
                    previous.valid_from
                    and previous.valid_until
                    and fact.valid_from
                    and fact.valid_until
                    and (
                        previous.valid_until < fact.valid_from
                        or fact.valid_until < previous.valid_from
                    )
                )
                if not disjoint:
                    raise ValueError(f"Visible entity fact conflict: {fact.entity}/{fact.id}.")
            pending.append((key, fact))
        for key, fact in pending:
            self._facts.setdefault(key, []).append(fact)
