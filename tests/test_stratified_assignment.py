import hashlib
import itertools
import json
import os
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import networkx as nx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from docgen.allocation import AllocationPlan, allocate
from docgen.config import RenderConfig
from docgen.errors import InputError, IntegrityError
from docgen.planning import create_plan
from docgen.store import RunStore
from tests.fixtures.factories import diverse_content
from tests.test_generate_phase import batch_config


def contents(count: int) -> tuple:
    plan = create_plan(batch_config(count), run_id="run-fixed", operation="generate")
    return tuple(diverse_content(blueprint) for blueprint in plan.blueprints)


def test_exact_counts_seeded_assignments_and_sparse_diagnostics() -> None:
    items = contents(12)
    cfg = RenderConfig(
        weights={"pdf": 0.25, "docx": 0.25, "xlsx": 0.15, "pptx": 0.15, "html": 0.1, "md": 0.1}
    )
    first = allocate(items, cfg, seed=17)
    assert first == allocate(tuple(reversed(items)), cfg, seed=17)
    assert Counter(item.format for item in first.items) == {
        "pdf": 3,
        "docx": 3,
        "xlsx": 2,
        "pptx": 2,
        "html": 1,
        "md": 1,
    }
    assert len({item.content_id for item in first.items}) == 12
    assert all(item.filename == f"{item.content_id}.{item.format}" for item in first.items)
    sparse = allocate(items[:1], RenderConfig(weights={"pdf": 0.6, "docx": 0.4}), seed=17)
    assert sparse.items[0].format == "pdf"
    assert any("unrepresented" in warning for warning in sparse.warnings)


@given(st.integers(1, 6), st.integers(1, 9), st.integers(0, 999))
@settings(max_examples=30, deadline=None)
def test_balancing_objective_is_globally_optimal_against_exhaustive_enumeration(
    count: int,
    pdf_parts: int,
    seed: int,
) -> None:
    items = contents(count)
    cfg = RenderConfig(weights={"pdf": pdf_parts / 10, "md": (10 - pdf_parts) / 10})
    plan = allocate(items, cfg, seed=seed)
    targets = Counter(assignment.format for assignment in plan.items)
    groups = Counter((item.blueprint.topic_id, item.blueprint.length_band) for item in items)
    shares = {
        key: Fraction(value) / sum(Fraction(v) for v in cfg.weights.values())
        for key, value in cfg.weights.items()
    }
    best = None
    for formats in itertools.product(("pdf", "md"), repeat=count):
        if Counter(formats) != targets:
            continue
        actual = Counter(
            ((item.blueprint.topic_id, item.blueprint.length_band), fmt)
            for item, fmt in zip(items, formats, strict=True)
        )
        cost = sum(
            abs(actual[group, fmt] - size * shares[fmt])
            for group, size in groups.items()
            for fmt in ("pdf", "md")
        )
        best = cost if best is None else min(best, cost)
    assert plan.objective == best
    assert plan.objective == allocate(items, cfg, seed=seed + 1).objective


def test_invalid_sources_and_solver_errors_have_no_random_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = RenderConfig(weights={"md": 1})
    with pytest.raises(InputError):
        allocate((), cfg, seed=1)
    (item,) = contents(1)
    with pytest.raises(InputError):
        allocate((item, item), cfg, seed=1)
    monkeypatch.setattr(
        nx,
        "network_simplex",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            nx.NetworkXUnfeasible("synthetic solver failure")
        ),
    )
    with pytest.raises(IntegrityError, match="solver"):
        allocate((item,), cfg, seed=1)


def test_allocation_is_immutable_and_recovered_from_the_state_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = batch_config(4)
    plan = create_plan(cfg, run_id="run-fixed", operation="generate")
    path = tmp_path / plan.run_id
    with RunStore.create(path, plan) as store:
        for item in contents(4):
            store.accept(item)
        selected = allocate(store.contents(), RenderConfig(weights={"pdf": 0.5, "md": 0.5}), seed=5)
        original_link = os.link
        with monkeypatch.context() as fault:
            fault.setattr(
                os,
                "link",
                lambda *args, **kwargs: (_ for _ in ()).throw(
                    OSError("injected allocation publication failure")
                ),
            )
            with pytest.raises(IntegrityError):
                store.freeze_allocation(selected)
        assert store.read_allocation() == selected
        assert (path / "allocation.json").exists()
        assert os.link == original_link
        alternate = allocate(store.contents(), RenderConfig(weights={"docx": 1}), seed=5)
        with pytest.raises(IntegrityError, match="immutable"):
            store.freeze_allocation(alternate)
    with RunStore.open(path) as store:
        assert store.read_allocation() == selected
    artifact = path / "allocation.json"
    original = artifact.read_bytes()
    artifact.write_bytes(original + b"tampered")
    with pytest.raises(IntegrityError, match="allocation"):
        RunStore.open(path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["items"][0].update(filename="..\\elsewhere.pdf"),
        lambda d: d["items"][0].update(content_id=d["items"][1]["content_id"]),
        lambda d: d["items"][0].update(
            format="docx", filename=d["items"][0]["content_id"] + ".docx"
        ),
        lambda d: d["strata"][0]["counts"].update(pdf=-1),
        lambda d: d["strata"][0].update(size=99),
        lambda d: d.update(objective_numerator=999),
        lambda d: d["strata"].pop(),
    ],
)
def test_invalid_assignment_shapes_and_reported_margins_are_rejected(mutation) -> None:
    plan = allocate(contents(4), RenderConfig(weights={"pdf": 0.5, "md": 0.5}), seed=5)
    data = json.loads(plan.model_dump_json())
    mutation(data)
    with pytest.raises(ValueError):
        AllocationPlan.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("raw", [{}, {"s-0": {"x": "not-an-integer"}}])
def test_incomplete_or_invalid_solver_flow_is_an_explicit_error(
    monkeypatch: pytest.MonkeyPatch,
    raw: dict,
) -> None:
    monkeypatch.setattr(nx, "network_simplex", lambda *args, **kwargs: (0, raw))
    with pytest.raises(IntegrityError, match="solver"):
        allocate(contents(1), RenderConfig(weights={"md": 1}), seed=0)


def test_frozen_allocation_rejects_wrong_sources_uncheckpointed_files_and_bad_state(
    tmp_path: Path,
) -> None:
    plan = create_plan(batch_config(2), run_id="run-fixed", operation="generate")
    path = tmp_path / plan.run_id
    items = contents(2)
    selected = allocate(items, RenderConfig(weights={"md": 1}))
    with RunStore.create(path, plan) as store:
        with pytest.raises(IntegrityError, match="accepted"):
            store.freeze_allocation(selected)
        for item in items:
            store.accept(item)
        invalid = selected.model_copy(
            update={
                "items": (
                    selected.items[0].model_copy(update={"source_hash": "0" * 64}),
                    selected.items[1],
                )
            }
        )
        with pytest.raises(IntegrityError, match="source checksum"):
            store.freeze_allocation(invalid)
        (path / "allocation.json").write_bytes(b"{}")
        with pytest.raises(IntegrityError, match="Uncheckpointed"):
            store.read_allocation()
        (path / "allocation.json").unlink()
        store.freeze_allocation(selected)
        store.freeze_allocation(selected)
        with store.connection:
            store.connection.execute("UPDATE allocation SET hash=?", ("0" * 64,))
        with pytest.raises(IntegrityError, match="checkpoint checksum"):
            store.read_allocation()
        with store.connection:
            store.connection.execute(
                "UPDATE allocation SET payload=?,hash=?", (b"{}", hashlib.sha256(b"{}").hexdigest())
            )
        with pytest.raises(IntegrityError, match="schema"):
            store.read_allocation()


def test_mutated_allocation_containers_are_revalidated_before_persistence(tmp_path: Path) -> None:
    plan = create_plan(batch_config(2), run_id="run-fixed", operation="generate")
    with RunStore.create(tmp_path / plan.run_id, plan) as store:
        for item in contents(2):
            store.accept(item)
        selected = allocate(store.contents(), RenderConfig(weights={"pdf": 0.5, "md": 0.5}))
        selected.config.weights["pdf"] = Decimal(".9")
        with pytest.raises(IntegrityError):
            store.freeze_allocation(selected)
        assert not (store.directory / "allocation.json").exists()


def test_three_format_transport_matches_bruteforce_and_tolerance_is_reported() -> None:
    items = contents(5)
    cfg = RenderConfig(weights={"pdf": Decimal(".2"), "docx": Decimal(".3"), "md": Decimal(".5")})
    plan = allocate(items, cfg, seed=19)
    targets = Counter(item.format for item in plan.items)
    groups = Counter((item.blueprint.topic_id, item.blueprint.length_band) for item in items)
    best = None
    for choices in itertools.product(cfg.weights, repeat=len(items)):
        if Counter(choices) != targets:
            continue
        cells = Counter(
            ((item.blueprint.topic_id, item.blueprint.length_band), fmt)
            for item, fmt in zip(items, choices, strict=True)
        )
        objective = sum(
            abs(cells[group, fmt] - size * Fraction(share))
            for group, size in groups.items()
            for fmt, share in cfg.weights.items()
        )
        best = objective if best is None else min(best, objective)
    assert plan.objective == best
    drift = allocate(
        items[:1],
        RenderConfig(
            weights={
                "pdf": Decimal(".6"),
                "md": Decimal(".40000000001"),
            }
        ),
    )
    assert any("normalized" in warning for warning in drift.warnings)
    zero = allocate(items[:1], RenderConfig(weights={"pdf": Decimal(0), "md": Decimal(1)}))
    assert zero.items[0].format == "md"
