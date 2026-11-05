import math
from decimal import Decimal
from fractions import Fraction

from docgen.models import Content, LengthBand

WORD_BANDS: dict[LengthBand, tuple[int, int]] = {
    "short": (200, 400), "medium": (500, 900), "long": (1000, 1600),
}
GENRE_REQUIREMENTS = {
    "explainer": "At least three heading blocks with explanatory paragraphs.",
    "procedure": "At least five top-level ordered steps with explicit responsibilities.",
    "faq": (
        "At least four question headings ending in ? "
        "each immediately followed by an answer paragraph."
    ),
    "comparison": "At least one rectangular table with at least three columns and three data rows.",
}


def acceptance_word_band(
    band: LengthBand, tolerance: Decimal | None = None,
) -> tuple[int, int]:
    if tolerance is None:
        return WORD_BANDS[band]
    if not tolerance.is_finite() or not Decimal(0) <= tolerance <= Decimal("0.05"):
        raise ValueError("Word-band tolerance must be between zero and five percent.")
    low, high = WORD_BANDS[band]
    fraction = Fraction(tolerance)
    return (
        math.ceil(low * (1 - fraction)),
        math.floor(high * (1 + fraction)),
    )


def validate_profile(content: Content) -> None:
    nested = any(item.level == 2 for block in content.blocks for item in block.items or ())
    deep = any(block.level == 3 for block in content.blocks)
    table = any(block.table is not None for block in content.blocks)
    if content.blueprint.structure_profile == "baseline" and (nested or deep):
        raise ValueError("baseline profile permits heading depth two and top-level lists only.")
    if content.blueprint.structure_profile == "complex" and (not nested or not table):
        raise ValueError("complex profile requires a native table and a nested list.")
