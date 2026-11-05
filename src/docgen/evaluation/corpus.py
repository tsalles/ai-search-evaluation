from functools import partial
from pathlib import Path

from azure.core.credentials import TokenCredential

from docgen.errors import InputError, IntegrityError
from docgen.evaluation.models import Document
from docgen.evaluation.revisions import (
    load_source_revision,
    preflight_revision_candidate,
    prepare_revision_rendering,
)
from docgen.evaluation.state import Workspace, digest, require_live
from docgen.families import validate_family
from docgen.generation import generate_content
from docgen.models import Content
from docgen.persistence import safe_child
from docgen.planning import create_plan
from docgen.providers.base import ContentProvider
from docgen.rendering import render_content
from docgen.reports import save_summary
from docgen.results import Result
from docgen.store import RunStore


def source_run(workspace: Workspace) -> Path:
    return safe_child(workspace.path, workspace.protocol.source_run_id)


def generate_sources(
    workspace: Workspace,
    *,
    provider: ContentProvider | None = None,
    credential: TokenCredential | None = None,
    live: bool = False,
) -> Result:
    workspace.protocol.require_pipeline_only()
    if (
        workspace.get("source-lineage") is not None
        or workspace.get("source-fork-origin") is not None
    ):
        raise InputError("Variant sources are inherited and immutable; authoring is forbidden.")
    if provider is None:
        require_live(live)
    workspace.require_valid()
    protocol = workspace.protocol
    directory = source_run(workspace)
    if directory.exists():
        store = RunStore.open(directory)
    else:
        store = RunStore.create(
            directory,
            create_plan(
                protocol.generation_config,
                run_id=protocol.source_run_id,
            ),
        )
    with store:
        if store.plan.run_id != protocol.source_run_id or (
            store.plan.effective_config != protocol.generation_config
        ):
            raise IntegrityError("Source run differs from the fresh experiment protocol.")
        revision = load_source_revision(workspace, store)
        result = generate_content(
            store, provider=provider, credential=credential,
            candidate_validator=(
                partial(preflight_revision_candidate, revision=revision) if revision else None
            ),
        )
        if result.status == "content_ready":
            rendering = protocol.generation_config.rendering
            if rendering is None:
                raise IntegrityError("Protocol rendering configuration is missing.")
            if revision is not None:
                prepare_revision_rendering(store, revision)
            rendered = render_content(store, rendering)
            result = Result.model_validate(
                {**rendered.model_dump(), "usage": result.usage}
            )
        return save_summary(store.directory, result)


def sources(workspace: Workspace) -> tuple[tuple[Document, ...], tuple[Content, ...]]:
    import hashlib

    from docgen.publication import load_ready

    with RunStore.open(source_run(workspace)) as store:
        if store.plan.run_id != workspace.protocol.source_run_id or (
            store.plan.effective_config != workspace.protocol.generation_config
        ):
            raise IntegrityError("Source run differs from the fresh experiment protocol.")
        contents = store.contents()
        allocation = store.read_allocation()
        if allocation is None or load_ready(store, allocation) is None:
            raise InputError(
                "Fresh source generation must finish and publish before reference building."
            )
        states = store.rendered_states()
        by_id = {content.blueprint.content_id: content for content in contents}
        documents = []
        generation = store.plan.effective_config.generation
        if generation is None or generation.families is None:
            raise IntegrityError("Experimental sources have no frozen family plan.")
        for content in contents:
            try:
                validate_family(content, generation)
            except ValueError:
                raise IntegrityError(
                    "Accepted source facts differ from their frozen family plan."
                ) from None
        families = {family.id: family for family in generation.families}
        for assignment in allocation.items:
            content = by_id[assignment.content_id]
            family = families.get(content.blueprint.family_id or "")
            state = states.get(assignment.content_id)
            path = safe_child(safe_child(store.directory, "corpus"), assignment.filename)
            if family is None or state is None or state.status != "verified":
                raise IntegrityError("Fresh corpus identity or publication state differs.")
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != state.hash:
                raise IntegrityError("Fresh source artifact checksum differs.")
            documents.append(
                Document(
                    id=assignment.content_id,
                    family_id=family.id,
                    canonical_hash=digest(content),
                    filename=assignment.filename,
                    artifact_hash=actual,
                    byte_count=path.stat().st_size,
                    format=assignment.format,
                    genre=content.blueprint.genre,
                    length_band=content.blueprint.length_band,
                    complexity=(
                        content.blueprint.structure_plan.complexity
                        if content.blueprint.structure_plan
                        else content.blueprint.structure_profile
                    ),
                    entities=family.entities,
                )
            )
        return tuple(documents), contents
