import hashlib
import json
import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from docgen.config import Config
from docgen.errors import InputError, IntegrityError
from docgen.families import role_fact_ids
from docgen.layouts import layout_preview, preflight_layouts
from docgen.models import Blueprint, Content, Identifier, Record
from docgen.prompts import PROMPT_VERSION
from docgen.sampling import derived_seed as derived_seed
from docgen.sampling import expand as expand
from docgen.sampling import quotas as quotas
from docgen.structures import plan_structures, structure_details
from docgen.word_budgets import length_policy


class RunPlan(Record):
    schema_version: Literal["1"] = "1"
    algorithm_version: Literal["1", "2", "3", "4"] = "1"
    run_id: Identifier
    operation: Literal["generate", "run"]
    effective_config: Config
    semantic_fingerprint: str
    blueprints: tuple[Blueprint, ...]
    topic_quotas: dict[str, int]
    genre_quotas: dict[str, int]
    length_quotas: dict[str, int]


def semantic_fingerprint(config: Config, *, prompt_version: str | None = None) -> str:
    generation = config.generation
    if generation is None:
        raise InputError("A content plan requires generation configuration.")
    payload = generation.model_dump(mode="json", exclude={"limits"})
    payload["prompt_version"] = PROMPT_VERSION if prompt_version is None else prompt_version
    payload["wire_version"] = "1"
    payload["seed"] = config.seed
    # Rendering is frozen separately, after content generation.
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def create_plan(
    config: Config, *, run_id: str, operation: Literal["generate", "run"] = "run"
) -> RunPlan:
    config.require_phase(operation)
    generation = config.generation
    if generation is None:
        raise InputError("A content plan requires generation configuration.")
    count = generation.count
    topic_weights = {
        topic.id: topic.share if topic.share is not None else Decimal(1) / len(generation.topics)
        for topic in generation.topics
    }
    topics = quotas(count, topic_weights)
    genres = quotas(count, generation.genre_weights)
    lengths = quotas(count, generation.length_weights)
    topic_ids = expand(topics, derived_seed(config.seed, "topic"))
    genre_ids = expand(genres, derived_seed(config.seed, "genre"))
    length_ids = expand(lengths, derived_seed(config.seed, "length"))
    blueprints = tuple(
        Blueprint(
            content_id=f"item-{index + 1:06}",
            ordinal=index + 1,
            topic_id=topic_ids[index],
            genre=genre_ids[index],
            length_band=length_ids[index],
            language=generation.language,
            locale=generation.locale,
            audience=generation.audience,
            scenario_id=f"scenario-{index + 1:06}",
            structure_profile=generation.structure_profile,
            family_id=(
                generation.families[index // 6].id if generation.families is not None else None
            ),
            required_fact_ids=(
                role_fact_ids(generation.families[index // 6], index % 6)
                if generation.families is not None else None
            ),
        )
        for index in range(count)
    )
    if generation.structure is not None:
        blueprints = plan_structures(blueprints, generation.structure, seed=config.seed)
    if config.rendering is not None and operation == "run":
        preflight_layouts(blueprints, config.rendering)
    return RunPlan(
        algorithm_version=(
            "4" if generation.families is not None else
            "3" if generation.structure is not None and generation.structure.length_aware else
            "2" if generation.structure is not None else "1"
        ),
        run_id=run_id,
        operation=operation,
        effective_config=config,
        semantic_fingerprint=semantic_fingerprint(config),
        blueprints=blueprints,
        topic_quotas=topics,
        genre_quotas={key: value for key, value in genres.items()},
        length_quotas={key: value for key, value in lengths.items()},
    )


def base_result(operation: str, status: str) -> dict[str, JsonValue]:
    return {
        "schema_version": "1",
        "run_id": None,
        "operation": operation,
        "status": status,
        "requested_count": None,
        "accepted_count": None,
        "verified_document_count": None,
        "format_counts": {},
        "failures": [],
        "usage": None,
        "reports": {},
        "corpus_path": None,
        "details": {},
    }


def preview(
    config: Config, *, operation: Literal["generate", "run"] = "run"
) -> dict[str, JsonValue]:
    plan = create_plan(config, run_id="preview", operation=operation)
    generation = config.generation
    if generation is None:
        raise InputError("A content plan requires generation configuration.")
    warnings: list[JsonValue] = []
    format_counts: dict[str, JsonValue] = {}
    mixes = {
        "topic": plan.topic_quotas,
        "genre": plan.genre_quotas,
        "length": plan.length_quotas,
    }
    if generation.structure is not None:
        mixes["complexity"] = {
            key: value for key, value in quotas(
                generation.count, generation.structure.complexity_weights,
            ).items()
        }
    if config.rendering is not None and operation == "run":
        targets = quotas(generation.count, config.rendering.weights)
        for key, target in targets.items():
            share = config.rendering.weights[key]
            format_counts[key] = {
                "requested_share": float(share),
                "allocated_count": target,
                "verified_count": None,
            }
            if share > 0 and target == 0:
                warnings.append(f"Unrepresented positive-share format: {key}.")
        if sum(config.rendering.weights.values()) != Decimal(1):
            warnings.append("Format representation drift normalized inside the 1e-9 tolerance.")
    for name, margins in mixes.items():
        for group_key, target in margins.items():
            if target == 0:
                warnings.append(f"Unrepresented {name}: {group_key}.")
    strata = {(b.topic_id, b.length_band) for b in plan.blueprints}
    present_formats = sum(
        value > 0
        for value in (
            quotas(generation.count, config.rendering.weights).values()
            if config.rendering and operation == "run"
            else ()
        )
    )
    if present_formats and any(
        sum((b.topic_id, b.length_band) == group for b in plan.blueprints) < present_formats
        for group in strata
    ):
        warnings.append("Sparse topic/length strata cannot represent every format.")
    result = base_result("plan", "planned")
    result.update(
        requested_count=generation.count,
        format_counts=format_counts,
        details={
            "topic_quotas": dict(plan.topic_quotas),
            "genre_quotas": dict(plan.genre_quotas),
            "length_quotas": dict(plan.length_quotas),
            "warnings": warnings,
            "max_requests": generation.request_limit,
            "semantic_fingerprint": plan.semantic_fingerprint,
            "algorithm_version": plan.algorithm_version,
            "phase": operation,
            "length_policy": length_policy(generation.quality.word_band_tolerance),
            **(
                {
                    "layouts": layout_preview(
                        quotas(generation.count, config.rendering.weights), config.rendering,
                    ),
                }
                if operation == "run" and config.rendering is not None
                and config.rendering.layout_weights is not None else {}
            ),
            **(
                {"structure": structure_details(plan.blueprints)}
                if generation.structure is not None else {}
            ),
        },
    )
    return result


def preview_render(directory: Path, config: Config) -> dict[str, JsonValue]:
    from docgen.allocation import allocate, format_quotas

    config.require_phase("render")
    if config.rendering is None:
        raise InputError("Rendering configuration is required.")
    try:
        raw_plan = (directory / "plan.json").read_bytes()
        plan = RunPlan.model_validate_json(raw_plan)
        database = (directory / "state.sqlite3").absolute()
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            saved_hash = connection.execute("SELECT plan_hash FROM state WHERE id=1").fetchone()
            if saved_hash is None or saved_hash[0] != hashlib.sha256(raw_plan).hexdigest():
                raise IntegrityError("Saved plan checksum mismatch.")
            rows = connection.execute(
                "SELECT id,hash FROM items WHERE status='accepted' ORDER BY ordinal"
            ).fetchall()
        if {row[0] for row in rows} != {item.content_id for item in plan.blueprints}:
            raise InputError("All content must be accepted before planning Phase 2.")
        contents = []
        for content_id, expected_hash in rows:
            raw = (directory / "content" / f"{content_id}.json").read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected_hash:
                raise IntegrityError("Canonical source checksum differs.")
            content = Content.model_validate_json(raw)
            if content.blueprint != next(
                item for item in plan.blueprints if item.content_id == content_id
            ):
                raise IntegrityError("Canonical source blueprint differs.")
            contents.append(content)
        allocation = allocate(tuple(contents), config.rendering, seed=plan.effective_config.seed)
    except (OSError, sqlite3.Error) as exc:
        raise IntegrityError("Cannot inspect saved content in read-only mode.") from exc
    result = base_result("plan", "planned")
    targets = format_quotas(len(contents), config.rendering)
    result.update(
        run_id=plan.run_id,
        requested_count=len(contents),
        accepted_count=len(contents),
        format_counts={
            fmt: {
                "requested_share": float(share),
                "allocated_count": targets[fmt],
                "verified_count": None,
            }
            for fmt, share in config.rendering.weights.items()
        },
        details={
            "phase": "render",
            "warnings": list(allocation.warnings),
            "objective": str(allocation.objective),
            "strata": [stratum.model_dump(mode="json") for stratum in allocation.strata],
            "allocation_frozen": (directory / "allocation.json").exists(),
            "structure_counts": {
                fmt: {key: count for key, count in counts.items()}
                for fmt, counts in allocation.structure_counts.items()
            },
            **(
                {"layouts": layout_preview(targets, config.rendering)}
                if config.rendering.layout_weights is not None else {}
            ),
        },
    )
    return result
