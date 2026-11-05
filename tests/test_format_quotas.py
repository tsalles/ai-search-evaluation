from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from docgen.allocation import format_quotas
from docgen.config import Config, RenderConfig
from docgen.errors import InputError
from docgen.planning import preview
from tests.test_planning import configuration

FORMATS = ("docx", "html", "md", "pdf", "pptx", "xlsx")


@pytest.mark.parametrize(("count", "weights", "expected"), [
    (7, {"pdf": 0.5, "docx": 0.3, "md": 0.2}, {"pdf": 4, "docx": 2, "md": 1}),
    (1, {"pdf": 0.6, "docx": 0.4}, {"pdf": 1, "docx": 0}),
    (1, {"pdf": 0.5, "docx": 0.5}, {"pdf": 0, "docx": 1}),
    (1, {"md": 1, "pdf": 0}, {"md": 1, "pdf": 0}),
    (1000, {"md": 1}, {"md": 1000}),
])
def test_exact_worked_quotas(count: int, weights: dict, expected: dict) -> None:
    assert format_quotas(count, RenderConfig.model_validate({"weights": weights})) == expected


@pytest.mark.parametrize("count", [0, -1, 1001, True, 1.5, "7"])
def test_invalid_format_allocation_count_is_not_silently_coerced(count: object) -> None:
    with pytest.raises(InputError):
        format_quotas(count, RenderConfig(weights={"md": 1}))


@given(
    st.integers(min_value=1, max_value=1000),
    st.lists(st.integers(min_value=0, max_value=1000), min_size=6, max_size=6)
    .map(lambda values: values if any(values) else [1, 0, 0, 0, 0, 0]),
)
@settings(max_examples=150, deadline=None)
def test_quotas_match_an_independent_exact_rational_oracle(count: int, weights: list[int]) -> None:
    total = Decimal(sum(weights))
    shares = {key: Decimal(weight) / total for key, weight in zip(FORMATS, weights, strict=True)}
    cfg = RenderConfig(weights=shares)
    actual = format_quotas(count, cfg)
    rational_total = sum(Fraction(share) for share in shares.values())
    ideals = {
        key: Fraction(count) * Fraction(share) / rational_total for key, share in shares.items()
    }
    oracle = {key: value.numerator // value.denominator for key, value in ideals.items()}
    ranked = sorted(ideals, key=lambda key: (-(ideals[key] - oracle[key]), key))
    for key in ranked[:count - sum(oracle.values())]:
        oracle[key] += 1
    assert actual == oracle
    assert sum(actual.values()) == count
    assert all(value >= 0 for value in actual.values())
    for key, share in shares.items():
        if share == 0:
            assert actual[key] == 0
        ideal = Decimal(count) * share / sum(shares.values())
        assert actual[key] in {
            int(ideal.to_integral_value(rounding=ROUND_FLOOR)),
            int(ideal.to_integral_value(rounding=ROUND_CEILING)),
        }


def test_preview_and_public_allocation_share_the_exact_result() -> None:
    data = configuration(7)
    data["rendering"]["weights"] = {"pdf": 0.5, "docx": 0.3, "md": 0.2}
    cfg = Config.model_validate(data)
    result = preview(cfg)
    quotas = format_quotas(7, cfg.rendering)
    actual = {key: counts["allocated_count"] for key, counts in result["format_counts"].items()}
    assert actual == quotas


def test_public_allocator_revalidates_mutated_share_containers() -> None:
    config = RenderConfig(weights={"md": 1})
    config.weights["md"] = Decimal("0.9")
    with pytest.raises(InputError, match="Invalid format"):
        format_quotas(7, config)
