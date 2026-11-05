import unicodedata

_GROUPS = (
    ("dia \u00fatil", "dias \u00fateis", "dia util", "dias uteis", "business day", "business days"),
    ("dia corrido", "dias corridos", "calendar day", "calendar days"),
    ("dia", "dias", "day", "days"),
    ("hora", "horas", "hour", "hours"),
    ("m\u00eas", "meses", "mes", "month", "months"),
    ("ano", "anos", "year", "years"),
)
_ALIASES = {alias: group for group in _GROUPS for alias in group}


def unit_variants(unit: str | None) -> tuple[str, ...]:
    if unit is None:
        return ()
    key = " ".join(unicodedata.normalize("NFC", unit).casefold().split())
    return _ALIASES.get(key, (unit,))


def unit_identity(unit: str | None) -> tuple[str, str] | None:
    if unit is None:
        return None
    key = " ".join(unicodedata.normalize("NFC", unit).casefold().split())
    group = _ALIASES.get(key)
    if group is not None:
        return "known", group[0]
    # Unknown units retain case: SI prefixes such as ms and Ms are not equivalent.
    return "literal", unicodedata.normalize("NFC", unit)
