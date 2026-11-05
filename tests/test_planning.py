import copy
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from docgen.config import Config, load_config
from docgen.errors import InputError
from docgen.planning import create_plan, preview


def configuration(count: int = 12) -> dict[str, Any]:
    return {
        "schema_version": "1", "seed": 1729,
        "generation": {
            "count": count, "topics": [
                {"id": "produtos", "description": "Produtos bancarios ficticios"},
                {"id": "procedimentos", "description": "Procedimentos bancarios ficticios"},
            ],
        },
        "rendering": {"weights": {"md": 1}},
    }


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(extra=True),
    lambda d: d.update(schema_version="2"),
    lambda d: d.update(seed=True),
    lambda d: d["generation"].update(count=0),
    lambda d: d["generation"].update(count=1001),
    lambda d: d["generation"].update(count=True),
    lambda d: d["generation"]["topics"].append(copy.deepcopy(d["generation"]["topics"][0])),
    lambda d: d["generation"]["topics"][0].update(description=" "),
    lambda d: d["generation"]["topics"][0].update(share=0.5),
    lambda d: d["generation"].update(language="en", locale="pt-BR"),
    lambda d: d["generation"].update(structure_profile="anything"),
    lambda d: d["generation"].update(genre_weights={"faq": 0.9}),
    lambda d: d["generation"].update(length_weights={"enormous": 1}),
    lambda d: d["generation"].update(quality={"max_candidates_per_item": True}),
    lambda d: d["generation"].update(limits={"concurrency": 17}),
    lambda d: d["generation"].update(limits={"max_output_tokens_per_request": 0}),
    lambda d: d["generation"].update(limits={"max_observed_total_tokens": 0}),
    lambda d: d["rendering"].update(weights={"md": True}),
    lambda d: d["rendering"].update(weights={"md": "1"}),
    lambda d: d["rendering"].update(weights={"md": float("nan")}),
    lambda d: d["rendering"].update(weights={"md": float("inf")}),
    lambda d: d["rendering"].update(weights={"md": -1, "pdf": 2}),
    lambda d: d["rendering"].update(weights={"md": 0.9}),
    lambda d: d["rendering"].update(weights={"unknown": 1}),
    lambda d: d["rendering"].update(weights={}),
    lambda d: d["generation"].update(provider={
        "base_url": "https://user:secret@example.openai.azure.com/openai/v1/",
        "deployment": "test",
    }),
])
def test_invalid_configuration_is_rejected_before_planning(mutation: Any) -> None:
    data = configuration()
    mutation(data)
    with pytest.raises(ValidationError):
        Config.model_validate(data)


@given(st.integers(min_value=1, max_value=1000), st.integers(min_value=0, max_value=100000))
@settings(max_examples=40, deadline=None)
def test_blueprints_reproduce_all_margins_with_stable_semantics(count: int, seed: int) -> None:
    data = configuration(count)
    data["seed"] = seed
    cfg = Config.model_validate(data)
    first = create_plan(cfg, run_id="run-fixed", operation="generate")
    second = create_plan(cfg, run_id="run-fixed", operation="generate")
    assert first == second
    assert len(first.blueprints) == count
    assert len({b.content_id for b in first.blueprints}) == count
    assert sum(first.topic_quotas.values()) == count
    assert sum(first.genre_quotas.values()) == count
    assert sum(first.length_quotas.values()) == count
    for topic, quota in first.topic_quotas.items():
        assert sum(b.topic_id == topic for b in first.blueprints) == quota
    for genre, quota in first.genre_quotas.items():
        assert sum(b.genre == genre for b in first.blueprints) == quota
    for length, quota in first.length_quotas.items():
        assert sum(b.length_band == length for b in first.blueprints) == quota


def test_semantic_fingerprint_excludes_only_operational_controls() -> None:
    data = configuration()
    cfg = Config.model_validate(data)
    original = create_plan(cfg, run_id="run-a", operation="run")
    data["generation"]["limits"] = {"concurrency": 3, "max_requests": 800}
    changed_limits = create_plan(Config.model_validate(data), run_id="run-b", operation="run")
    assert original.semantic_fingerprint == changed_limits.semantic_fingerprint
    assert original.blueprints == changed_limits.blueprints
    data["generation"]["audience"] = "experts"
    changed_audience = create_plan(Config.model_validate(data), run_id="run-b", operation="run")
    assert original.semantic_fingerprint != changed_audience.semantic_fingerprint
    data["seed"] += 1
    changed_seed = create_plan(Config.model_validate(data), run_id="run-b", operation="run")
    assert changed_seed.semantic_fingerprint != changed_audience.semantic_fingerprint


def test_generation_needs_no_formats_or_credentials_and_render_needs_no_provider() -> None:
    data = configuration(3)
    del data["rendering"]
    plan = create_plan(Config.model_validate(data), run_id="run-test", operation="generate")
    assert sorted(plan.topic_quotas.values()) == [1, 2]
    assert plan.effective_config.generation.provider is None
    cfg = Config.model_validate({"rendering": {"weights": {"pdf": 1}}})
    cfg.require_phase("render")
    with pytest.raises(InputError, match="generation"):
        cfg.require_phase("generate")
    with pytest.raises(InputError, match="rendering"):
        Config.model_validate(data).require_phase("run")


def test_rounding_drift_and_unrepresented_groups_are_reported() -> None:
    data = configuration(1)
    data["rendering"]["weights"] = {"pdf": 0.6, "docx": 0.40000000001}
    result = preview(Config.model_validate(data), operation="run")
    assert result["requested_count"] == 1
    assert result["format_counts"]["pdf"]["allocated_count"] == 1
    assert result["format_counts"]["docx"]["allocated_count"] == 0
    assert any("normalized" in warning.lower() for warning in result["details"]["warnings"])
    assert any("unrepresented" in warning.lower() for warning in result["details"]["warnings"])
    assert result["corpus_path"] is None


def test_topic_shares_and_tie_rule_are_explicit() -> None:
    data = configuration(3)
    data["generation"]["topics"][0]["share"] = 0.8
    data["generation"]["topics"][1]["share"] = 0.2
    plan = create_plan(Config.model_validate(data), run_id="run-test", operation="generate")
    assert plan.topic_quotas == {"procedimentos": 1, "produtos": 2}
    assert preview(Config.model_validate(configuration(3)))["details"]["topic_quotas"] == {
        "procedimentos": 2, "produtos": 1,
    }


@pytest.mark.parametrize("text", [
    "generation: {count: 2}\ngeneration: {count: 3}\n",
    "seed: !!python/object/apply:os.system ['echo BAD']",
    "seed: [unclosed",
    '{"seed": 1, "seed": 2}',
    "[]",
])
def test_loader_rejects_unsafe_duplicate_or_invalid_documents(text: str, tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(InputError):
        load_config(path)


def test_cli_plan_is_json_and_never_creates_a_run(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(configuration()), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "docgen", "plan", "--config", str(path), "--json"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "planned"
    assert payload["run_id"] is None
    assert payload["requested_count"] == 12
    assert payload["details"]["max_requests"] == 108
    assert payload["usage"] is None
    assert list(tmp_path.iterdir()) == [path]
    path.write_text(json.dumps(configuration(0)), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "docgen", "plan", "--config", str(path), "--json"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "invalid_input"
    assert "Traceback" not in result.stderr


def test_default_shares_use_exact_decimals() -> None:
    cfg = Config.model_validate(configuration())
    assert cfg.generation.length_weights["short"] == Decimal("0.3")


def test_effective_config_and_plan_round_trip_without_losing_decimal_shares() -> None:
    cfg = Config.model_validate(configuration())
    assert Config.model_validate_json(cfg.model_dump_json()) == cfg
    plan = create_plan(cfg, run_id="run-fixed", operation="run")
    assert type(plan).model_validate_json(plan.model_dump_json()) == plan
