import math
import random
from collections import Counter, defaultdict
from fractions import Fraction
from importlib.metadata import version
from typing import Annotated, Literal, Self

import networkx as nx
from pydantic import (
    Field,
    StrictInt,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from docgen.config import RenderConfig
from docgen.errors import InputError, IntegrityError
from docgen.layouts import layout_counts, layout_pool, plan_layouts
from docgen.models import (
    Content,
    Format,
    Identifier,
    LengthBand,
    Profile,
    Record,
    content_hash,
)
from docgen.planning import derived_seed, quotas
from docgen.structure_models import LAYOUT_CAPABILITIES, Complexity, LayoutPlan


def format_quotas(count: int, config: RenderConfig) -> dict[Format, int]:
    if type(count) is not int or not 1 <= count <= 1000:
        raise InputError("Content count must be an integer in [1, 1000].")
    try:
        checked = RenderConfig.model_validate(config.model_dump())
    except ValidationError as exc:
        raise InputError("Invalid format shares or rendering profile.") from exc
    return quotas(count, checked.weights)


class Assignment(Record):
    legacy_optional_fields = ("layout_plan",)
    content_id: Identifier
    source_hash: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    format: Format
    filename: str
    renderer_version: Literal["1"] = "1"
    layout_profile: Profile
    layout_plan: LayoutPlan | None = None

    @model_validator(mode="after")
    def exact_filename(self) -> Self:
        if self.filename != f"{self.content_id}.{self.format}":
            raise ValueError("Artifact filename must be its content ID and assigned extension.")
        if self.layout_plan is not None and (
            self.layout_plan.recipe not in LAYOUT_CAPABILITIES[self.format]
            or self.layout_profile != self.layout_plan.profile
        ):
            raise ValueError("Native layout plan is incompatible with its format/profile.")
        return self


class Stratum(Record):
    legacy_optional_fields = ("complexity",)
    topic_id: Identifier
    length_band: LengthBand
    size: StrictInt = Field(ge=1)
    counts: dict[Format, StrictInt]
    deviations: dict[Format, float]
    complexity: Complexity | None = None


class AllocationPlan(Record):
    legacy_optional_fields = ("recipe_counts", "layout_counts")
    schema_version: Literal["1"] = "1"
    algorithm_version: Literal["transport-v1", "transport-v2-structure"] = "transport-v1"
    solver_version: str
    seed: StrictInt
    config: RenderConfig
    items: tuple[Assignment, ...]
    strata: tuple[Stratum, ...]
    objective_numerator: StrictInt = Field(ge=0)
    objective_denominator: StrictInt = Field(ge=1)
    warnings: tuple[str, ...]
    genre_counts: dict[str, dict[str, int]]
    structure_counts: dict[str, dict[str, int]]
    recipe_counts: dict[str, dict[str, int]] | None = None
    layout_counts: dict[str, dict[str, int]] | None = None

    @property
    def objective(self) -> Fraction:
        return Fraction(self.objective_numerator, self.objective_denominator)

    @model_validator(mode="after")
    def valid_margins(self) -> Self:
        targets = format_quotas(len(self.items), self.config)
        if len({item.content_id for item in self.items}) != len(self.items):
            raise ValueError("Each content ID must have exactly one assignment.")
        if Counter(item.format for item in self.items) != Counter(targets):
            raise ValueError("Assignments do not match exact global quotas.")
        total = sum(Fraction(value) for value in self.config.weights.values())
        shares = {key: Fraction(value) / total for key, value in self.config.weights.items()}
        columns: Counter[str] = Counter()
        objective = Fraction(0)
        for stratum in self.strata:
            if (
                sum(stratum.counts.values()) != stratum.size
                or set(stratum.counts) != set(targets)
                or any(count < 0 for count in stratum.counts.values())
            ):
                raise ValueError("Stratum counts must be complete and nonnegative.")
            columns.update(stratum.counts)
            objective += sum(
                abs(count - stratum.size * shares[fmt]) for fmt, count in stratum.counts.items()
            )
        if columns != Counter(targets) or objective != self.objective:
            raise ValueError("Strata or objective do not match the assigned margins.")
        if self.config.layout_weights is not None:
            actual = {
                fmt: layout_counts(tuple(
                    item.layout_plan for item in self.items
                    if item.format == fmt and item.layout_plan is not None
                ))
                for fmt in targets
            }
            if any(item.layout_plan is None for item in self.items) or any(
                Counter(actual[fmt]) != Counter(quotas(size, layout_pool(self.config, fmt)))
                for fmt, size in targets.items()
            ) or self.layout_counts != actual:
                raise ValueError("Native layout assignments do not match their exact quotas.")
        elif self.layout_counts is not None or any(
            item.layout_plan is not None for item in self.items
        ):
            raise ValueError("Native layout assignments require explicit layout_weights.")
        return self


def allocate(
    contents: tuple[Content, ...],
    config: RenderConfig,
    *,
    seed: int = 0,
) -> AllocationPlan:
    targets = format_quotas(len(contents), config)
    if len({item.blueprint.content_id for item in contents}) != len(contents):
        raise InputError("Content IDs must be unique before allocation.")
    groups: dict[
        tuple[str, LengthBand, Complexity | Literal[""]], list[Content]
    ] = defaultdict(list)
    for item in sorted(contents, key=lambda item: item.blueprint.content_id):
        groups[
            item.blueprint.topic_id, item.blueprint.length_band,
            item.blueprint.structure_plan.complexity if item.blueprint.structure_plan else "",
        ].append(item)
    total = sum(Fraction(value) for value in config.weights.values())
    shares = {key: Fraction(value) / total for key, value in config.weights.items()}
    scale = math.lcm(*(value.denominator for value in shares.values()))
    graph: nx.DiGraph[str] = nx.DiGraph()
    segments = []
    for index, (group, items) in enumerate(sorted(groups.items())):
        source = f"s-{index}"
        graph.add_node(source, demand=-len(items))
        for fmt in sorted(targets):
            if targets[fmt] == 0:
                continue
            destination = f"f-{fmt}"
            graph.add_node(destination, demand=targets[fmt])
            ideal = len(items) * shares[fmt]
            for unit in range(1, len(items) + 1):
                delta = abs(unit - ideal) - abs(unit - 1 - ideal)
                segments.append(
                    (source, destination, f"e-{index}-{fmt}-{unit}", int(delta * scale), group, fmt)
                )
    ranks = list(range(len(segments)))
    random.Random(derived_seed(seed, "flow-tie")).shuffle(ranks)
    priority = len(contents) * len(segments) + 1
    for (source, destination, node, cost, _, _), rank in zip(segments, ranks, strict=True):
        graph.add_node(node, demand=0)
        graph.add_edge(source, node, capacity=1, weight=cost * priority + rank)
        graph.add_edge(node, destination, capacity=1, weight=0)
    try:
        _, raw = nx.network_simplex(graph)
        flow = TypeAdapter(dict[str, dict[str, StrictInt]]).validate_python(raw, strict=True)
        if any(
            source not in flow or destination not in flow[source]
            for source, destination in graph.edges
        ):
            raise IntegrityError("Allocation solver returned an incomplete flow.")
    except (nx.NetworkXException, ValidationError) as exc:
        raise IntegrityError(
            "Balanced allocation solver failed; no random fallback was used."
        ) from exc
    matrix = {group: {fmt: 0 for fmt in targets} for group in groups}
    for source, _, node, _, group, fmt in segments:
        matrix[group][fmt] += flow[source][node]
    assignments = []
    strata = []
    warnings = []
    if sum(config.weights.values()) != 1:
        warnings.append("Format representation drift normalized within the 1e-9 tolerance.")
    objective = Fraction(0)
    genres: dict[str, Counter[str]] = {fmt: Counter() for fmt in targets}
    structures: dict[str, Counter[str]] = {fmt: Counter() for fmt in targets}
    recipes: dict[str, Counter[str]] = {fmt: Counter() for fmt in targets}
    for (topic, length, complexity), items in sorted(groups.items()):
        group = (topic, length, complexity)
        counts = matrix[group]
        selected = list(items)
        stream = f"items:{topic}:{length}" + (f":{complexity}" if complexity else "")
        random.Random(derived_seed(seed, stream)).shuffle(selected)
        position = 0
        deviations = {}
        for fmt, count in sorted(counts.items()):
            difference = count - len(items) * shares[fmt]
            objective += abs(difference)
            deviations[fmt] = float(difference)
            if shares[fmt] > 0 and count == 0:
                warnings.append(f"unrepresented {fmt} in {topic}/{length}.")
            if abs(difference) > 1:
                warnings.append(f"balance deviation exceeds one item: {topic}/{length}/{fmt}.")
            for item in selected[position : position + count]:
                assignments.append(
                    Assignment(
                        content_id=item.blueprint.content_id,
                        source_hash=content_hash(item),
                        format=fmt,
                        filename=f"{item.blueprint.content_id}.{fmt}",
                        layout_profile=config.layout_profile,
                    )
                )
                genres[fmt][item.blueprint.genre] += 1
                structure = item.blueprint.structure_plan
                structure_key = (
                    structure.complexity if structure else item.blueprint.structure_profile
                )
                structures[fmt][structure_key] += 1
                if structure is not None:
                    recipes[fmt][structure.recipe_id] += 1
            position += count
        strata.append(
            Stratum(
                topic_id=topic,
                length_band=length,
                size=len(items),
                counts=counts,
                deviations=deviations,
                complexity=complexity or None,
            )
        )
    if config.layout_weights is not None:
        by_id = {content.blueprint.content_id: content for content in contents}
        selected_layouts = plan_layouts(
            {
                fmt: tuple(by_id[item.content_id] for item in assignments if item.format == fmt)
                for fmt in targets
            },
            config, seed=seed,
        )
        assignments = [
            Assignment.model_validate({
                **item.model_dump(),
                "layout_plan": selected_layouts[item.content_id],
                "layout_profile": selected_layouts[item.content_id].profile,
            })
            for item in assignments
        ]
        for fmt, size in targets.items():
            for name, count in quotas(size, layout_pool(config, fmt)).items():
                if layout_pool(config, fmt)[name] > 0 and count == 0:
                    warnings.append(f"Unrepresented positive-share native layout: {fmt}/{name}.")
    structured = any(item.blueprint.structure_plan is not None for item in contents)
    return AllocationPlan(
        algorithm_version="transport-v2-structure" if structured else "transport-v1",
        solver_version=version("networkx"),
        seed=seed,
        config=config,
        items=tuple(sorted(assignments, key=lambda item: item.content_id)),
        strata=tuple(strata),
        objective_numerator=objective.numerator,
        objective_denominator=objective.denominator,
        warnings=tuple(warnings),
        genre_counts={key: dict(value) for key, value in genres.items()},
        structure_counts={key: dict(value) for key, value in structures.items()},
        recipe_counts={key: dict(value) for key, value in recipes.items()} if structured else None,
        layout_counts={
            fmt: layout_counts(tuple(
                item.layout_plan for item in assignments
                if item.format == fmt and item.layout_plan is not None
            ))
            for fmt in targets
        } if config.layout_weights is not None else None,
    )
