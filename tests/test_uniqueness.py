import json
from decimal import Decimal
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from docgen.config import Config
from docgen.models import Content
from docgen.quality import Acceptance
from docgen.uniqueness import UniquenessIndex, payload_fingerprint, shingles
from tests.fixtures.factories import quality_content
from tests.test_content_contract import example_content
from tests.test_planning import configuration


def text_content(text: str, title: str = "Title") -> Content:
    data = example_content()
    data["title"] = title
    data["facts"] = []
    data["blocks"] = [{"id": "body", "kind": "paragraph", "text": text}]
    return Content.model_validate(data)


def test_normalized_payload_ignores_titles_ids_provenance_and_whitespace() -> None:
    first = text_content("Conteudo bancario 12 BRL com \u00e7 e nomes.")
    other = text_content("  CONTEUDO   BANCARIO 12 BRL COM \u00c7 E NOMES. ", "Another title")
    assert payload_fingerprint(first) == payload_fingerprint(other)
    changed = text_content("Conteudo bancario 13 BRL com \u00e7 e nomes.")
    assert payload_fingerprint(first) != payload_fingerprint(changed)
    index = UniquenessIndex()
    index.accept(first)
    with pytest.raises(ValueError, match="exact"):
        index.accept(other)


@pytest.mark.parametrize(("length", "duplicate"), [(20, False), (21, True), (22, True)])
def test_near_duplicate_threshold_is_inclusive_at_exactly_point_eighty_five(
    length: int, duplicate: bool,
) -> None:
    words = [f"word-{index}" for index in range(24)]
    index = UniquenessIndex(Decimal("0.85"))
    index.accept(text_content(" ".join(words)))
    item = text_content(" ".join(words[:length]))
    assert index.similarity(item) == Fraction(length - 4, 20)
    if duplicate:
        with pytest.raises(ValueError, match="near"):
            index.accept(item)
    else:
        index.accept(item)


@given(
    st.lists(st.sampled_from(["a", "b", "c", "d", "e", "f", "g", "h"]), min_size=1, max_size=35),
    st.lists(st.sampled_from(["a", "b", "c", "d", "e", "f", "g", "h"]), min_size=1, max_size=35),
)
@settings(max_examples=80)
def test_index_matches_an_independent_pairwise_shingle_oracle(a: list[str], b: list[str]) -> None:
    left = {" ".join(a[i:i + 5]) for i in range(max(1, len(a) - 4))}
    right = {" ".join(b[i:i + 5]) for i in range(max(1, len(b) - 4))}
    oracle = Fraction(len(left & right), len(left | right))
    index = UniquenessIndex()
    index.accept(text_content(" ".join(a)))
    assert index.similarity(text_content(" ".join(b))) == oracle


def test_short_text_is_not_exempt_and_invalid_thresholds_fail() -> None:
    index = UniquenessIndex()
    index.accept(text_content("short"))
    with pytest.raises(ValueError):
        index.accept(text_content("short"))
    for value in (Decimal(0), Decimal("1.01"), Decimal("NaN")):
        with pytest.raises(ValueError):
            UniquenessIndex(value)
    with pytest.raises(ValueError):
        shingles(" ")


def test_fingerprints_preserve_typed_tables_units_and_cell_associations() -> None:
    original = Content.model_validate(example_content())
    assert len(payload_fingerprint(original)) == 64
    metadata = json.loads(original.model_dump_json())
    metadata["blocks"][-1]["id"] = "other-block"
    metadata["blocks"][-1]["table"]["id"] = "other-table"
    metadata["blocks"][-1]["table"]["columns"][0]["id"] = "other-column"
    assert payload_fingerprint(Content.model_validate(metadata)) == payload_fingerprint(original)
    changed = json.loads(original.model_dump_json())
    changed["blocks"][-1]["table"]["rows"][0][1]["value"] = "1.50"
    changed["facts"][0].update(value="1.50", display="1,50%")
    assert payload_fingerprint(Content.model_validate(changed)) != payload_fingerprint(original)
    original = quality_content("comparison")
    changed = json.loads(original.model_dump_json())
    row = changed["blocks"][1]["table"]["rows"][0]
    row[1], row[2] = row[2], row[1]
    assert payload_fingerprint(Content.model_validate(changed)) != payload_fingerprint(original)


def test_acceptance_checks_quality_before_committing_uniqueness() -> None:
    cfg = Config.model_validate(configuration(1)).generation
    gate = Acceptance(cfg, detector=lambda *_: 1)
    content = quality_content()
    accepted = gate.accept(content)
    assert len(accepted.normalized_fingerprint) == 64
    assert "uniqueness" in accepted.quality.checks
    with pytest.raises(ValueError, match="exact"):
        gate.accept(content)
    invalid = text_content("too short")
    with pytest.raises(ValueError):
        gate.accept(invalid)
    assert payload_fingerprint(accepted) == payload_fingerprint(content)
