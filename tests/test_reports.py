import math

import pytest

from docgen import reports
from docgen.allocation import allocate
from docgen.config import RenderConfig
from tests.test_stratified_assignment import contents


@pytest.mark.parametrize("count", [1, 12, 51, 1000])
def test_review_sample_is_seeded_unique_and_covers_every_present_format(count: int) -> None:
    config = RenderConfig(
        weights={"pdf": 0.25, "docx": 0.25, "xlsx": 0.15, "pptx": 0.15, "html": 0.1, "md": 0.1}
    )
    allocation = allocate(contents(count), config, seed=1729)
    review = reports.review_details(allocation)
    assert review["status"] == "human_review_pending"
    assert review["reviewer"] is None
    samples = review["sample"]
    present = {item.format for item in allocation.items}
    assert (
        review["sample_count"]
        == len(samples)
        == min(count, max(len(present), math.ceil(0.02 * count)))
    )
    assert {item["format"] for item in samples} == present
    assert len({item["content_id"] for item in samples}) == len(samples)
    assert all(
        any(
            selected.content_id == sample["content_id"]
            and selected.filename == sample["filename"]
            and selected.format == sample["format"]
            for selected in allocation.items
        )
        for sample in samples
    )
    assert review == reports.review_details(allocation)
    assert review == reports.review_details(
        allocation.model_copy(update={"items": tuple(reversed(allocation.items))})
    )


def test_review_seed_changes_only_the_advisory_sample_not_the_assignment() -> None:
    allocation = allocate(contents(100), RenderConfig(weights={"md": 1}), seed=1729)
    before = allocation.model_dump_json()
    first = reports.review_details(allocation)
    different = reports.review_details(allocation.model_copy(update={"seed": 1730}))
    assert first["sample"] != different["sample"]
    assert allocation.model_dump_json() == before
