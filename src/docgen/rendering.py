import hashlib
from collections import Counter

from pydantic import JsonValue, ValidationError

from docgen.allocation import allocate
from docgen.config import RenderConfig
from docgen.errors import InputError, IntegrityError
from docgen.models import serialize
from docgen.persistence import atomic_write, safe_child
from docgen.publication import load_ready, publish
from docgen.renderers.base import Artifact, render_document
from docgen.reports import corpus_structure_details, review_details
from docgen.results import Result
from docgen.store import RunStatus, RunStore
from docgen.validation import CorpusValidation, validate_artifact, validate_set
from docgen.word_budgets import content_length_details


def render_content(store: RunStore, config: RenderConfig) -> Result:
    try:
        config = RenderConfig.model_validate_json(config.model_dump_json())
    except ValidationError as exc:
        raise InputError("Invalid render configuration.") from exc
    contents = store.contents()
    if len(contents) != len(store.plan.blueprints):
        raise IntegrityError("All planned content must be accepted before rendering.")
    allocation = store.read_allocation()
    if allocation is None:
        allocation = allocate(contents, config, seed=store.plan.effective_config.seed)
        store.freeze_allocation(allocation)
    elif allocation.config != config:
        raise InputError("The frozen format mix and layout configuration are immutable.")
    ready = load_ready(store, allocation)
    states = store.rendered_states()
    corpus = safe_child(store.directory, "corpus")
    staging = safe_child(store.directory, "artifacts.pending")
    failures: list[dict[str, JsonValue]] = []
    report: CorpusValidation | None = None
    status: RunStatus = "incomplete"
    generation = store.plan.effective_config.generation

    def hashes() -> dict[str, str]:
        return {
            key: state.hash
            for key, state in states.items()
            if state.status == "verified" and state.hash is not None
        }

    try:
        if corpus.exists():
            if ready is None or staging.exists():
                raise IntegrityError("Published corpus has no exclusive complete ready checkpoint.")
            report = validate_set(corpus, contents, allocation, expected_hashes=hashes())
            if not report.valid:
                raise IntegrityError(
                    "Published corpus failed checksum or native-content validation."
                )
            status = "complete"
        else:
            staging.mkdir(exist_ok=True)
            names = {item.filename for item in allocation.items}
            if any(not entry.is_file() or entry.name not in names for entry in staging.iterdir()):
                raise IntegrityError(
                    "Staging contains unexpected files or directories; nothing was deleted."
                )
            by_id = {content.blueprint.content_id: content for content in contents}
            store.set_status("rendering")
            for selected in allocation.items:
                content = by_id[selected.content_id]
                path = safe_child(staging, selected.filename)
                state = states.get(selected.content_id)
                if path.exists() and state is None:
                    raise IntegrityError("Uncheckpointed artifact cannot be adopted.")
                if state is not None and state.status == "verified":
                    check = validate_artifact(
                        content, selected, staging, expected_sha256=state.hash
                    )
                    if not check.valid:
                        raise IntegrityError(
                            "A verified artifact is missing or corrupt; it was not replaced."
                        )
                    continue
                store.start_artifact(selected.content_id)
                if path.exists():
                    recovered = validate_artifact(content, selected, staging)
                    if recovered.valid:
                        raw = path.read_bytes()
                        artifact = Artifact(
                            content_id=selected.content_id,
                            format=selected.format,
                            filename=selected.filename,
                            source_hash=selected.source_hash,
                            sha256=hashlib.sha256(raw).hexdigest(),
                            byte_count=len(raw),
                        )
                        states[selected.content_id] = store.verify_artifact(artifact, recovered)
                        continue
                    path.unlink()
                    store.record_rejection(selected.content_id)
                try:
                    artifact = render_document(content, selected, staging)
                except InputError as error:
                    failures.append(
                        {
                            "code": "render_failed",
                            "phase": "render",
                            "content_id": selected.content_id,
                            "retryable": False,
                            "message": str(error),
                        }
                    )
                    continue
                check = validate_artifact(
                    content, selected, staging, expected_sha256=artifact.sha256
                )
                if not check.valid:
                    failures.append(
                        {
                            "code": "artifact_validation",
                            "phase": "render",
                            "content_id": selected.content_id,
                            "retryable": True,
                            "message": "; ".join(issue.message for issue in check.issues),
                        }
                    )
                    continue
                states[selected.content_id] = store.verify_artifact(artifact, check)
            store.set_status("validating")
            report = validate_set(staging, contents, allocation, expected_hashes=hashes())
            if report.valid and not failures:
                artifacts = []
                for selected in allocation.items:
                    state = states[selected.content_id]
                    assert state.hash is not None and state.byte_count is not None
                    artifacts.append(
                        Artifact(
                            content_id=selected.content_id,
                            format=selected.format,
                            filename=selected.filename,
                            source_hash=selected.source_hash,
                            sha256=state.hash,
                            byte_count=state.byte_count,
                        )
                    )
                publish(store, allocation, tuple(artifacts), staging)
                status = "complete"
    except KeyboardInterrupt:
        status = "cancelled"
    except IntegrityError:
        store.set_status("incomplete")
        raise
    store.set_status(status)
    counts = Counter(item.format for item in allocation.items)
    verified = Counter(item.format for item in allocation.items if item.content_id in hashes())
    result = Result(
        run_id=store.plan.run_id,
        operation="render",
        status=status,
        requested_count=len(contents),
        accepted_count=len(contents),
        verified_document_count=sum(verified.values()),
        failures=tuple(failures),
        format_counts={
            fmt: {
                "requested_share": float(share),
                "allocated_count": counts[fmt],
                "verified_count": verified[fmt],
            }
            for fmt, share in config.weights.items()
        },
        usage={"requests": 0, "observed_total_tokens": 0, "total_tokens": 0, "unknown_outcomes": 0},
        corpus_path=corpus.resolve() if status == "complete" else None,
        reports={
            "allocation": str(store.directory / "allocation.json"),
            "validation": str(store.directory / "reports" / "validation.json"),
            "run_summary": str(store.directory / "reports" / "run-summary.json"),
        },
        details={
            "review": review_details(allocation, contents),
            **(
                {"length": content_length_details(
                    contents, generation.quality.word_band_tolerance,
                )}
                if generation is not None and (
                    generation.quality.word_band_tolerance is not None
                    or generation.structure is not None and generation.structure.length_aware
                ) else {}
            ),
            **(
                {"structure": corpus_structure_details(allocation, contents, set(hashes()))}
                if allocation.recipe_counts is not None or allocation.layout_counts is not None
                else {}
            ),
        },
    )
    if report is not None:
        atomic_write(
            safe_child(safe_child(store.directory, "reports"), "validation.json"),
            serialize(report),
            overwrite=True,
        )
    atomic_write(
        safe_child(safe_child(store.directory, "reports"), "run-summary.json"),
        serialize(result),
        overwrite=True,
    )
    return result
