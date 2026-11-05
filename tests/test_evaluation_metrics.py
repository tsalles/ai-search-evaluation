import math

import pytest

from docgen.evaluation.metrics import parent_metrics


@pytest.mark.parametrize("grade", [None, "3", True, float("nan")])
def test_invalid_grade_types_fail_as_validated_inputs(grade):
    with pytest.raises(ValueError):
        parent_metrics(["A"], {"A": grade}, cutoffs=(1,))


def test_parent_metrics_use_graded_gain_once_and_deduplicate_before_cutoff() -> None:
    result = parent_metrics(["c", "c", "a"], {"a": 3, "b": 2, "c": 0}, cutoffs=(2,))
    assert result["precision_at_2"] == result["recall_at_2"] == result["mrr_at_2"] == 0.5
    expected = (7 / math.log2(3)) / (7 + 3 / math.log2(3))
    assert result["ndcg_at_2"] == pytest.approx(expected, abs=1e-12)


def test_parent_metrics_pad_empty_rankings_and_retain_missing_positives() -> None:
    result = parent_metrics([], {"a": 3, "b": 2}, cutoffs=(5, 10))
    assert all(value == 0 for value in result.values())
    assert parent_metrics(["a"], {"a": 3, "b": 2}, cutoffs=(5,))["recall_at_5"] == 0.5
    assert parent_metrics(["a"], {"a": 3}, cutoffs=(10,))["precision_at_10"] == 0.1


def test_unjudged_and_no_positive_truth_are_not_silent_zero_labels() -> None:
    with pytest.raises(ValueError, match="Unjudged"):
        parent_metrics(["unknown"], {"a": 3})
    with pytest.raises(ValueError, match="positive"):
        parent_metrics(["a"], {"a": 1})
