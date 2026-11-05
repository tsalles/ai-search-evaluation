from docgen.errors import InputError
from docgen.evaluation.corpus import sources
from docgen.evaluation.models import SourceContext
from docgen.evaluation.state import Workspace
from docgen.families import referenced_entities
from docgen.text import business_units


def source_contexts(workspace: Workspace) -> dict[str, SourceContext]:
    if workspace.protocol.pipeline_only:
        raise InputError(
            "Canonical source context is historical metadata, not a Search pipeline output."
        )
    _, contents = sources(workspace)
    result = {}
    for content in contents:
        visible = " ".join(business_units(content))
        names = referenced_entities(visible, {fact.entity for fact in content.facts})
        result[content.blueprint.content_id] = SourceContext(
            title=content.title, account_names=tuple(sorted(names)),
        )
    return result
