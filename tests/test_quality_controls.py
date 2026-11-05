import json
from typing import Any

import pytest

from docgen.config import Config
from docgen.models import Content
from docgen.prompts import author_prompt
from docgen.quality import assess, language_probability
from docgen.text import word_count
from tests.fixtures.factories import quality_content
from tests.test_planning import configuration


def config() -> Config:
    return Config.model_validate(configuration(1))


@pytest.mark.parametrize("genre", ["explainer", "procedure", "faq", "comparison"])
@pytest.mark.parametrize("profile", ["baseline", "complex"])
def test_all_genres_and_profiles_pass_the_measurable_controls(genre: str, profile: str) -> None:
    content = quality_content(genre, profile=profile)
    accepted = assess(content, config().generation, detector=lambda text, language: 0.9)
    assert accepted.quality.word_count == 200
    assert {"length", "language", "genre", "profile"}.issubset(accepted.quality.checks)


@pytest.mark.parametrize(("band", "minimum", "maximum"), [
    ("short", 200, 400), ("medium", 500, 900), ("long", 1000, 1600),
])
def test_exact_inclusive_word_band_boundaries(band: str, minimum: int, maximum: int) -> None:
    cases = ((minimum - 1, False), (minimum, True), (maximum, True), (maximum + 1, False))
    for words, valid in cases:
        content = quality_content(words=words)
        content = Content.model_validate({
            **content.model_dump(), "blueprint": {
                **content.blueprint.model_dump(), "length_band": band,
            },
        })
        assert word_count(content) == words
        if valid:
            accepted = assess(content, config().generation, detector=lambda *_: 1)
            assert accepted.quality.word_count == words
        else:
            with pytest.raises(ValueError, match="length"):
                assess(content, config().generation, detector=lambda *_: 1)


@pytest.mark.parametrize(("genre", "mutate"), [
    ("explainer", lambda d: d["blocks"].pop(2)),
    ("procedure", lambda d: d["blocks"][1]["items"].pop()),
    ("faq", lambda d: d["blocks"].pop(7)),
    ("comparison", lambda d: d["blocks"][1]["table"]["rows"].pop()),
])
def test_genre_minimums_are_enforced(genre: str, mutate: Any) -> None:
    data = json.loads(quality_content(genre).model_dump_json())
    mutate(data)
    with pytest.raises(ValueError, match="genre"):
        assess(Content.model_validate(data), config().generation, detector=lambda *_: 1)


def test_profile_and_required_terms_are_not_silently_relaxed() -> None:
    content = quality_content(profile="complex")
    content = Content.model_validate({
        **content.model_dump(), "blueprint": {
            **content.blueprint.model_dump(), "structure_profile": "baseline",
        },
    })
    with pytest.raises(ValueError, match="profile"):
        assess(content, config().generation, detector=lambda *_: 1)
    content = quality_content(profile="complex")
    data = content.model_dump()
    data["blocks"] = [b for b in data["blocks"] if b["kind"] != "table"]
    with pytest.raises(ValueError, match="profile"):
        assess(Content.model_validate(data), config().generation, detector=lambda *_: 1)
    data = configuration(1)
    data["generation"]["required_terms"] = ["conta"]
    with pytest.raises(ValueError, match="term"):
        assess(quality_content(), Config.model_validate(data).generation, detector=lambda *_: 1)
    data["generation"]["required_terms"] = ["apoio"]
    assess(quality_content(), Config.model_validate(data).generation, detector=lambda *_: 1)


@pytest.mark.parametrize("score", [0.899, -1, 1.1, float("nan")])
def test_language_confidence_cannot_bypass_the_threshold(score: float) -> None:
    with pytest.raises(ValueError, match="language"):
        assess(quality_content(), config().generation, detector=lambda *_: score)


def test_real_local_language_detector_is_deterministic_for_portuguese_and_english() -> None:
    portuguese = (
        "Este documento descreve procedimentos de atendimento ao cliente "
        "e explica as condi\u00e7\u00f5es para contratar produtos banc\u00e1rios fict\u00edcios. "
        "A equipe deve esclarecer d\u00favidas e manter "
        "os registros atualizados durante todo o processo de solicita\u00e7\u00e3o. "
    ) * 10
    english = (
        "This document describes customer service procedures and explains the conditions for "
        "requesting fictional banking products. The team should answer questions and keep the "
        "records updated throughout the entire application process. "
    ) * 10
    first = language_probability(portuguese, "pt")
    assert first >= 0.9
    assert language_probability(portuguese, "pt") == first
    assert language_probability(english, "en") >= 0.9
    assert language_probability(english, "pt") < 0.9
    with pytest.raises(ValueError, match="language"):
        language_probability("123456", "pt")


def test_prompt_is_versioned_specific_and_preserves_the_wire_contract() -> None:
    cfg = config().generation
    content = quality_content("procedure", profile="complex")
    prompt = author_prompt(content.blueprint, cfg, feedback=("length rejected",))
    assert "200" in prompt and "400" in prompt
    assert "pt-BR" in prompt
    assert "{{fact:" in prompt
    assert "length rejected" in prompt
    assert content.blueprint.topic_id in prompt
    assert "complex" in prompt
    assert "untrusted" in prompt.lower()
    assert "hyphens" in prompt.lower()
    assert "verbatim" in prompt.lower()
    assert "full value and unit" in prompt.lower()
    assert "singular/plural" in prompt.lower()
    assert "label each distinct fact" in prompt.lower()
