import math
import re
from collections.abc import Callable
from functools import lru_cache

from langdetect.detector_factory import PROFILES_DIRECTORY, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException

from docgen.config import GenerationConfig
from docgen.facts import FactRegistry, normalized
from docgen.families import family_for, validate_family
from docgen.models import Content, Quality
from docgen.profiles import WORD_BANDS, acceptance_word_band, validate_profile
from docgen.renderers.layout import layout_text, portable_latin_characters
from docgen.structures import validate_structure
from docgen.text import business_units, word_count
from docgen.uniqueness import UniquenessIndex


@lru_cache(maxsize=1)
def language_factory() -> DetectorFactory:
    factory = DetectorFactory()
    factory.load_profile(PROFILES_DIRECTORY)
    factory.set_seed(0)
    return factory


def language_probability(text: str, language: str) -> float:
    detector = language_factory().create()
    detector.append(text)
    try:
        results = detector.get_probabilities()
    except LangDetectException:
        raise ValueError("Cannot measure language in text without sufficient letters.") from None
    for result in results:
        if result.lang == language:
            return float(result.prob)
    return 0.0


def validate_source_text(content: Content) -> None:
    supported = frozenset(portable_latin_characters())
    for text in business_units(content):
        text = layout_text(text)
        invalid = sorted({ord(char) for char in text if char not in supported})
        if invalid:
            points = ", ".join(f"U+{point:04X}" for point in invalid[:8])
            raise ValueError(
                f"SaaS source text contains unsupported or reserved characters: {points}."
            )
        if re.search(
            r'"(?:blocks|kind|level|table_id|fact_id|list_items|columns|cells)"\s*:'
            r"|(?:[^\w\s]){8,}"
            r"|\b(?:Wait JSON invalid|Need fix|Let's craft correctly)\b",
            text,
        ):
            raise ValueError(
                "SaaS source text contains serialized output or model-control residue."
            )
        if re.search(
            r"@(?:price|sla|activation|restriction|workflow)-[ab]\b"
            r"|(?<!\w)[^\W\d_]+(?:,[^\W\d_]+){2,}(?!\w)"
            r"|,\s*porque[.!?]?\s*$",
            text,
            flags=re.IGNORECASE,
        ):
            raise ValueError(
                "SaaS source text contains unresolved fact markers, comma-joined prose "
                "or an unfinished clause."
            )


def assess(
    content: Content, config: GenerationConfig, *,
    detector: Callable[[str, str], float] | None = None,
) -> Content:
    content = Content.model_validate_json(content.model_dump_json())
    validate_family(content, config)
    family = family_for(content.blueprint, config)
    source_text = family is not None and family.domain == "saas"
    if source_text:
        validate_source_text(content)
    if content.blueprint.structure_plan is None:
        validate_profile(content)
    else:
        validate_structure(content)
    genre = content.blueprint.genre
    valid = True
    if genre == "explainer":
        valid = sum(block.kind == "heading" for block in content.blocks) >= 3
    elif genre == "procedure":
        valid = sum(
            item.level == 1 for block in content.blocks if block.kind == "ordered_list"
            for item in block.items or ()
        ) >= 5
    elif genre == "faq":
        valid = sum(
            block.kind == "heading" and bool(block.text and block.text.endswith("?"))
            and following.kind == "paragraph"
            for block, following in zip(content.blocks, content.blocks[1:], strict=False)
        ) >= 4
    elif genre == "comparison":
        valid = any(
            block.table and len(block.table.columns) >= 3 and len(block.table.rows) >= 3
            for block in content.blocks
        )
    if not valid:
        raise ValueError(f"Content does not satisfy the {genre} genre minimums.")
    count = word_count(content)
    nominal_low, nominal_high = WORD_BANDS[content.blueprint.length_band]
    low, high = acceptance_word_band(
        content.blueprint.length_band, config.quality.word_band_tolerance,
    )
    if not low <= count <= high:
        policy = (
            f" Nominal band [{nominal_low}, {nominal_high}], "
            f"tolerance {config.quality.word_band_tolerance:%}."
            if config.quality.word_band_tolerance else ""
        )
        raise ValueError(
            f"Content length {count} is outside the required [{low}, {high}] word band.{policy}"
        )
    text = " ".join(business_units(content))
    for term in config.required_terms:
        if not re.search(rf"(?<!\w){re.escape(normalized(term))}(?!\w)", normalized(text)):
            raise ValueError(f"Required term is missing: {term}.")
    score = (detector or language_probability)(text, content.blueprint.language)
    if (
        isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score)
        or not float(config.quality.language_confidence_min) <= score <= 1
    ):
        raise ValueError("Content language probability is below the required threshold or invalid.")
    return content.model_copy(update={
        "quality": Quality(
            checks=tuple(dict.fromkeys((
                *content.quality.checks,
                "structure_plan" if content.blueprint.structure_plan is not None else "profile",
                "genre", "length", "terms", "language",
                *(("source_text",) if source_text else ()),
                *(("length_tolerance",) if not nominal_low <= count <= nominal_high else ()),
            ))),
            word_count=count,
        ),
    })


class Acceptance:
    def __init__(
        self, config: GenerationConfig, *, detector: Callable[[str, str], float] | None = None,
        validator: Callable[[Content], None] | None = None,
    ) -> None:
        self._config = config
        self._detector = detector
        self._validator = validator
        self._facts = FactRegistry()
        self._uniqueness = UniquenessIndex(config.quality.near_duplicate_jaccard)

    def accept(self, content: Content) -> Content:
        verified = assess(content, self._config, detector=self._detector)
        if self._validator is not None:
            self._validator(verified)
        self._uniqueness.check(verified)
        self._facts.accept(verified)
        fingerprint = self._uniqueness.accept(verified)
        return verified.model_copy(update={
            "normalized_fingerprint": fingerprint,
            "quality": Quality(
                checks=(*verified.quality.checks, "fact_consistency", "uniqueness"),
                word_count=verified.quality.word_count,
            ),
        })
