import hashlib
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import JsonValue, ValidationError

from docgen.allocation import AllocationPlan, Assignment
from docgen.budgets import BudgetOverride, effective_generation, increase_budget
from docgen.errors import InputError, IntegrityError
from docgen.evaluation.state import Workspace, digest, json_bytes, new_protocol
from docgen.models import Content, Record, content_hash, serialize
from docgen.persistence import atomic_write, safe_child
from docgen.planning import create_plan
from docgen.quality import Acceptance
from docgen.renderers.base import Artifact, render_document
from docgen.results import Result
from docgen.store import RunStore
from docgen.validation import validate_artifact


class SourceRevision(Record):
    legacy_optional_fields = ("origin_artifact_directory",)
    schema_version: Literal["1"] = "1"
    target_protocol: str
    origin_protocol: str
    origin_path: Path
    origin_run_id: str
    config_hash: str
    origin_files: dict[str, str]
    original_hashes: dict[str, str]
    retained: dict[str, str]
    rejected: dict[str, tuple[str, ...]]
    allocation: AllocationPlan
    retained_artifacts: tuple[Artifact, ...]
    inherited_attempt_count: int
    inherited_attempt_hash: str
    origin_artifact_directory: Literal["artifacts.pending", "corpus"] | None = None


def source_file_hashes(directory: Path) -> dict[str, str]:
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise IntegrityError("Source revisions cannot inherit filesystem links.")
        if path.is_file() and not path.name.endswith(".lock"):
            result[str(path.relative_to(directory))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _attempt_hash(store: RunStore, count: int) -> str:
    return digest([attempt.model_dump(mode="json") for attempt in store.attempts()[:count]])


def create_source_revision(
    source: Workspace, output: Path, *, rejected: dict[str, tuple[str, ...]],
) -> Path:
    return _create_revision(source, output, rejected=rejected, published=False)


def create_quality_revision(
    source: Workspace, output: Path, *, rejected: dict[str, tuple[str, ...]],
) -> Path:
    return _create_revision(source, output, rejected=rejected, published=True)


def _create_revision(
    source: Workspace, output: Path, *, rejected: dict[str, tuple[str, ...]], published: bool,
) -> Path:
    source.require_valid()
    source.protocol.require_pipeline_only()
    origin = safe_child(source.path, source.protocol.source_run_id)
    inherited = source.get("source-lineage") is not None or (
        source.get("source-fork-origin") is not None
    )
    reference = source.get("reference")
    if not published and (
        reference is not None or inherited or (source.path / "reference-draft.json").exists()
        or (origin / "corpus").exists() or (origin / "ready.json").exists()
    ):
        raise InputError(
            "Source correction requires an unpublished, unreleased original source run."
        )
    if published:
        seal = source.get("reference-complete")
        if (
            inherited or not isinstance(reference, dict) or reference.get("status") != "provisional"
            or not isinstance(seal, dict) or seal.get("reference_hash") != digest(reference)
            or not (origin / "corpus").is_dir()
            or hashlib.sha256((source.path / "reference.json").read_bytes()).hexdigest()
            != seal.get("reference_hash")
            or hashlib.sha256((source.path / "qrels.trec").read_bytes()).hexdigest()
            != seal.get("qrels_hash")
        ):
            raise InputError("Published quality correction requires a sealed provisional source.")
    elif source.database.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]:
        raise InputError("Source correction is forbidden after any remote evaluation request.")
    if source.path == output.absolute() or source.path in output.absolute().parents:
        raise InputError("Place corrected workspaces outside the original experiment directory.")
    before = source_file_hashes(source.path)
    with RunStore.open(origin, recover=False) as original:
        contents = original.contents()
        allocation = original.read_allocation()
        generation = original.plan.effective_config.generation
        if (
            len(contents) != len(original.plan.blueprints) or allocation is None
            or generation is None
            or original.plan.effective_config != source.protocol.generation_config
        ):
            raise InputError(
                "Source correction requires complete canonical content and allocation."
            )
        if published:
            from docgen.publication import load_ready

            if load_ready(original, allocation) is None:
                raise IntegrityError("Published quality correction has no complete native seal.")
        originals = {content.blueprint.content_id: content_hash(content) for content in contents}
        if (
            not rejected or not set(rejected) <= set(originals)
            or any(not reasons or any(not reason.strip() for reason in reasons)
                   for reasons in rejected.values())
        ):
            raise InputError("Every rejection must identify a planned item and a nonempty reason.")
        retained = {key: value for key, value in originals.items() if key not in rejected}
        gate = Acceptance(generation)
        states = original.rendered_states()
        artifacts = []
        for content in contents:
            identifier = content.blueprint.content_id
            if identifier not in retained:
                continue
            gate.accept(content)
            assignment = next(row for row in allocation.items if row.content_id == identifier)
            state = states.get(identifier)
            if state is None or state.status != "verified":
                raise InputError(
                    "Every retained source must already have a verified native artifact."
                )
            check = validate_artifact(
                content, assignment, origin / ("corpus" if published else "artifacts.pending"),
                expected_sha256=state.hash,
            )
            if not check.valid or state.hash is None or state.byte_count is None:
                raise IntegrityError(
                    "A retained native source differs from its verified checkpoint."
                )
            artifacts.append(Artifact(
                content_id=identifier, format=assignment.format, filename=assignment.filename,
                source_hash=assignment.source_hash, sha256=state.hash, byte_count=state.byte_count,
            ))
        protocol = new_protocol(source.protocol.config)
        if protocol.generation_config != source.protocol.generation_config:
            raise IntegrityError("Source revision changed the frozen generation configuration.")
        with Workspace.create(output, protocol) as target:
            plan = create_plan(protocol.generation_config, run_id=protocol.source_run_id)
            if plan.blueprints != original.plan.blueprints:
                raise IntegrityError("Source revision changed frozen facts or logical structures.")
            with RunStore.create(safe_child(target.path, protocol.source_run_id), plan) as store:
                store.inherit_authoring(original)
                effective = effective_generation(original)
                increase_budget(store, BudgetOverride(
                    max_requests=effective.request_limit,
                    max_observed_total_tokens=effective.limits.max_observed_total_tokens,
                    max_candidates_per_item=effective.quality.max_candidates_per_item,
                ))
                for content in contents:
                    if content.blueprint.content_id in retained:
                        store.accept(content)
                revision = SourceRevision(
                    target_protocol=protocol.id, origin_protocol=source.protocol.id,
                    origin_path=source.path, origin_run_id=source.protocol.source_run_id,
                    config_hash=digest(protocol.config), origin_files=before,
                    original_hashes=originals, retained=retained, rejected=rejected,
                    allocation=allocation, retained_artifacts=tuple(artifacts),
                    inherited_attempt_count=len(original.attempts()),
                    inherited_attempt_hash=_attempt_hash(original, len(original.attempts())),
                    origin_artifact_directory="corpus" if published else None,
                )
                target.record("authoring-source-revision", revision)
                target.export("authoring-source-revision.json", revision)
                if published:
                    target.put("quality-correction-policy", {
                        "preserved_measured_origin": str(source.path),
                        "source_quality_only_rejections": {
                            key: list(reasons) for key, reasons in rejected.items()
                        },
                        "inherited_evaluation_records": 0,
                        "inherited_query_vectors": 0,
                        "inherited_rankings": 0,
                        "new_indexing_and_measurement_required": True,
                        "not_an_additional_independent_replication": True,
                    })
                failures: tuple[dict[str, JsonValue], ...] = tuple(
                    {
                        "code": "quality_rejected", "phase": "generation",
                        "content_id": identifier, "retryable": True,
                        "message": "; ".join(reasons),
                    }
                    for identifier, reasons in sorted(rejected.items())
                )
                atomic_write(store.directory / "reports" / "content-quality.json", serialize(Result(
                    run_id=plan.run_id, operation=plan.operation, status="incomplete",
                    requested_count=len(contents), accepted_count=len(retained), failures=failures,
                )))
            path = target.path
    if source_file_hashes(source.path) != before:
        raise IntegrityError("The original source changed while its correction was being prepared.")
    return path


def load_source_revision(workspace: Workspace, store: RunStore) -> SourceRevision | None:
    raw = workspace.get("authoring-source-revision")
    if raw is None:
        return None
    try:
        revision = SourceRevision.model_validate_json(json_bytes(raw))
    except ValidationError as error:
        raise IntegrityError("Source correction lineage is invalid.") from error
    planned = {blueprint.content_id for blueprint in store.plan.blueprints}
    if (
        revision.target_protocol != workspace.protocol.id
        or revision.config_hash != digest(workspace.protocol.config)
        or set(revision.retained) & set(revision.rejected)
        or set(revision.retained) | set(revision.rejected) != planned
        or set(revision.original_hashes) != planned
        or {row.content_id: row.source_hash for row in revision.allocation.items}
        != revision.original_hashes
        or _attempt_hash(store, revision.inherited_attempt_count) != revision.inherited_attempt_hash
    ):
        raise IntegrityError(
            "Source correction differs from its frozen contract or inherited usage."
        )
    observed = {row.blueprint.content_id: content_hash(row) for row in store.contents()}
    if any(observed.get(key) != value for key, value in revision.retained.items()):
        raise IntegrityError("A retained canonical source changed in the correction.")
    if source_file_hashes(revision.origin_path) != revision.origin_files:
        raise IntegrityError("The preserved original source differs from its revision evidence.")
    return revision


def preflight_revision_candidate(content: Content, revision: SourceRevision) -> None:
    if content.blueprint.content_id not in revision.rejected:
        return
    frozen = next(
        row for row in revision.allocation.items if row.content_id == content.blueprint.content_id
    )
    assignment = Assignment.model_validate({
        **frozen.model_dump(), "source_hash": content_hash(content),
    })
    with TemporaryDirectory(prefix="docgen-native-preflight-") as directory:
        path = Path(directory)
        artifact = render_document(content, assignment, path)
        check = validate_artifact(content, assignment, path, expected_sha256=artifact.sha256)
        if not check.valid:
            raise InputError(
                "Assigned native layout failed readback: "
                + "; ".join(issue.message for issue in check.issues)
            )


def prepare_revision_rendering(store: RunStore, revision: SourceRevision) -> None:
    contents = {row.blueprint.content_id: row for row in store.contents()}
    if any(
        content_hash(contents[key]) == revision.original_hashes[key] for key in revision.rejected
    ):
        raise IntegrityError("Rejected source text was reused instead of regenerated.")
    allocation = AllocationPlan.model_validate({
        **revision.allocation.model_dump(),
        "items": [
            {**row.model_dump(), "source_hash": content_hash(contents[row.content_id])}
            for row in revision.allocation.items
        ],
    })
    store.freeze_allocation(allocation)
    if (store.directory / "corpus").exists():
        return
    staging = safe_child(store.directory, "artifacts.pending")
    staging.mkdir(exist_ok=True)
    states = store.rendered_states()
    assignments = {row.content_id: row for row in allocation.items}
    for artifact in revision.retained_artifacts:
        if artifact.content_id in states:
            continue
        origin = safe_child(revision.origin_path, revision.origin_run_id)
        source = safe_child(
            safe_child(origin, revision.origin_artifact_directory or "artifacts.pending"),
            artifact.filename,
        )
        if hashlib.sha256(source.read_bytes()).hexdigest() != artifact.sha256:
            raise IntegrityError("A retained original native artifact changed before copying.")
        store.start_artifact(artifact.content_id)
        shutil.copyfile(source, safe_child(staging, artifact.filename))
        check = validate_artifact(
            contents[artifact.content_id], assignments[artifact.content_id], staging,
            expected_sha256=artifact.sha256,
        )
        store.verify_artifact(artifact, check)
