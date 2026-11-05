import json

import pytest
from azure.core.exceptions import ServiceRequestError

from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.azure import Azure
from docgen.evaluation.ingestion import ingest, prepare
from docgen.evaluation.models import ARMS, SearchVariant
from docgen.evaluation.reference import released_reference
from docgen.evaluation.resources import definitions
from docgen.evaluation.runner import collect
from docgen.evaluation.snapshots import take_snapshot
from docgen.evaluation.state import Protocol, Workspace, new_protocol
from tests.evaluation.fixtures import experiment_config
from tests.evaluation.test_azure import azure_fixture


def test_new_protocol_requires_pipeline_only_enrichment():
    protocol = new_protocol(experiment_config())
    assert protocol.schema_version == "2"
    assert protocol.enrichment_policy == "search-pipeline-only"
    assert protocol.pipeline_only is True
    for arm in ARMS:
        resources = definitions(protocol, arm)
        assert {field["name"] for field in resources["indexes"]["fields"]} == {
            "id", "parent_id", "content", "content_path", "embedding",
        }
        semantic = resources["indexes"]["semantic"]["configurations"]
        assert semantic == [{
            "name": "content-only",
            "prioritizedFields": {"prioritizedContentFields": [{"fieldName": "content"}]},
        }]


def test_new_protocol_rejects_external_embedding_context_before_creation():
    settings = experiment_config()
    search = settings.search.model_copy(
        update={"variant": SearchVariant(embedding_context=True)},
    )
    with pytest.raises(InputError, match="pipeline"):
        new_protocol(settings.model_copy(update={"search": search}))


def test_archived_protocol_serialization_is_unchanged_and_live_mutations_are_blocked(
    tmp_path,
):
    legacy = new_protocol(experiment_config()).model_copy(
        update={"schema_version": "1", "enrichment_policy": None},
    )
    serialized = legacy.model_dump_json()
    assert "enrichment_policy" not in json.loads(serialized)
    assert Protocol.model_validate_json(serialized).model_dump_json() == serialized
    with Workspace.create(tmp_path, legacy) as workspace:
        with Azure(workspace.protocol) as azure:
            for operation in (prepare, ingest, collect):
                with pytest.raises(InputError, match="historical"):
                    operation(workspace, azure, live=True)
        assert workspace.usage()["attempts"] == dict.fromkeys(
            ("admin", "blob", "embedding", "search"), 0,
        )


def test_native_ingestion_never_uses_canonical_context_or_external_document_writes(
    staged_workspace, monkeypatch,
):
    def forbidden(*args, **kwargs):
        pytest.fail("Raw-only ingestion accessed generator-assisted source context.")

    monkeypatch.setattr("docgen.evaluation.context.source_contexts", forbidden)
    workspace = staged_workspace
    azure, backend, blobs, _ = azure_fixture(workspace)
    with azure:
        prepare(workspace, azure, live=True)
        assert all(item["metadata"] == {} for item in blobs.blobs.values())
        assert all(
            not any(key.casefold().startswith("x-ms-meta-") for key in request.headers)
            for request in blobs.requests if request.method == "PUT"
        )
        ingest(workspace, azure, live=True)
        for arm in ARMS:
            observed = take_snapshot(workspace, azure, arm, live=True)
            assert len(observed.chunks) == 12
            assert all(chunk.source_context is None for chunk in observed.chunks)
            assert workspace.get("context-complete:" + arm) is None
        assert not any(
            request.url.path.endswith("/docs/index")
            or "/embeddings" in str(request.url)
            for request in backend.requests
        )


@pytest.mark.parametrize("profile", ["entity-hybrid", "entity-semantic"])
def test_raw_only_rejects_generator_assisted_entity_profiles_before_requests(
    staged_workspace, profile,
):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    with azure:
        prepare(workspace, azure, live=True)
        ingest(workspace, azure, live=True)
        for arm in ARMS:
            take_snapshot(workspace, azure, arm, live=True)
        before = len(backend.requests)
        with pytest.raises(InputError, match="pipeline"):
            collect(workspace, azure, live=True, profile=profile)
        assert len(backend.requests) == before
        assert workspace.get("collection-complete:test:" + profile) is None


@pytest.mark.parametrize("direct", [False, True])
def test_client_document_writes_are_rejected_before_authorization(staged_workspace, direct):
    workspace = staged_workspace
    azure, backend, _, credential = azure_fixture(workspace)
    path = "indexes/" + workspace.protocol.resource_name("de_split", "index") + "/docs/index"
    with azure, pytest.raises(InputError, match="indexing pipeline"):
        if direct:
            azure.request(
                "POST",
                workspace.protocol.config.search.endpoint + "/" + path,
                scope="https://search.azure.com/.default",
                body={"value": []},
            )
        else:
            azure.search("POST", path, body={"value": []})
    assert not backend.requests
    assert not credential.scopes


def test_raw_only_refuses_preexisting_blobs_without_an_owned_upload_intent(staged_workspace):
    workspace = staged_workspace
    azure, _, _, _ = azure_fixture(workspace)
    reference = released_reference(workspace)
    from docgen.evaluation.corpus import source_run

    with azure:
        document = reference.documents[0]
        azure.upload(document, source_run(workspace) / "corpus" / document.filename)
        with pytest.raises(IntegrityError, match="unowned"):
            prepare(workspace, azure, live=True)


@pytest.mark.parametrize(
    "metadata", [{"account_names": "provided-name"}, {"docgen_sha256": "hash"}],
)
def test_raw_only_refuses_custom_metadata_even_on_an_owned_upload(staged_workspace, metadata):
    workspace = staged_workspace
    azure, backend, blobs, _ = azure_fixture(workspace)

    def inject_metadata():
        next(iter(blobs.blobs.values()))["metadata"] = metadata
        blobs.after_upload = None

    blobs.after_upload = inject_metadata
    with azure, pytest.raises(IntegrityError, match="mismatched"):
        prepare(workspace, azure, live=True)
    assert not backend.resources


def test_raw_only_resumes_an_owned_unknown_upload_without_overwriting(staged_workspace):
    workspace = staged_workspace
    azure, backend, blobs, _ = azure_fixture(workspace)

    def lose_upload_response():
        blobs.after_upload = None
        raise ServiceRequestError("Simulated response loss after source creation.")

    blobs.after_upload = lose_upload_response
    with azure:
        with pytest.raises(ProviderError):
            prepare(workspace, azure, live=True)
        assert len(blobs.blobs) == 1
        original = {name: dict(item) for name, item in blobs.blobs.items()}
        assert not backend.resources
        prepare(workspace, azure, live=True)
        assert len(blobs.blobs) == 12
        assert all(blobs.blobs[name] == item for name, item in original.items())
        assert all(item["metadata"] == {} for item in blobs.blobs.values())
