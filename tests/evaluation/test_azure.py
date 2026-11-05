import copy
import json

import httpx
import pytest

from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.azure import Azure, vector_value
from docgen.evaluation.corpus import source_run, sources
from docgen.evaluation.ingestion import ingest, prepare, resource_path
from docgen.evaluation.models import ARMS, ExperimentConfig, IngestionAudit, MissingSource
from docgen.evaluation.reference import released_reference
from docgen.evaluation.resources import definitions
from docgen.evaluation.snapshots import assert_stable, take_snapshot
from docgen.evaluation.state import digest, new_protocol
from tests.evaluation.azure_double import BlobTransport, Credential, SearchTransport
from tests.evaluation.fixtures import experiment_config


def azure_fixture(workspace):
    reference = released_reference(workspace)
    _, contents = sources(workspace)
    backend = SearchTransport(workspace, reference, contents)
    blobs = BlobTransport()
    credential = Credential()
    client = httpx.Client(transport=httpx.MockTransport(backend))
    azure = Azure(
        workspace.protocol, credential=credential, http_client=client, blob_transport=blobs
    )
    return azure, backend, blobs, credential


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        (
            {
                "search": "sample", "semanticQuery": "sample",
                "semanticConfiguration": "content-only",
            },
            "semantic_quota",
        ),
        (
            {"search": "sample", "queryType": "semantic", "semanticConfiguration": "content-only"},
            "semantic_quota",
        ),
        ({"search": "sample"}, "azure_request"),
    ],
)
def test_semantic_payment_required_stops_without_retry_or_success_cache(
    staged_workspace, body, expected_code,
):
    requests = []

    def rejected(request):
        requests.append(request)
        return httpx.Response(402, json={"error": {"message": "Semantic allowance exhausted."}})

    client = httpx.Client(transport=httpx.MockTransport(rejected))
    with Azure(staged_workspace.protocol, credential=Credential(), http_client=client) as azure:
        with pytest.raises(ProviderError) as raised:
            staged_workspace.invoke(
                "search", "semantic-quota-check",
                lambda: azure.search("POST", "indexes/sample/docs/search", body=body),
                fingerprint="frozen-semantic-request", semantic=expected_code == "semantic_quota",
            )
    client.close()
    assert raised.value.code == expected_code
    assert raised.value.retryable is False
    assert "402" in str(raised.value)
    if expected_code == "semantic_quota":
        assert "quota" in str(raised.value).lower()
        assert "sequential" in str(raised.value).lower()
    assert len(requests) == 1
    assert staged_workspace.get("remote:semantic-quota-check") is None
    assert staged_workspace.database.execute(
        "SELECT status,error FROM attempts WHERE tag='semantic-quota-check'",
    ).fetchall() == [("failed", expected_code)]


def test_resource_builder_has_only_the_controlled_extraction_chunking_difference():
    protocol = new_protocol(experiment_config())
    de, cu = (definitions(protocol, arm) for arm in ARMS)
    assert de["indexes"]["fields"] == cu["indexes"]["fields"]
    key = next(field for field in de["indexes"]["fields"] if field.get("key"))
    assert key["searchable"] is True
    assert key["analyzer"] == "keyword"
    assert de["indexes"]["vectorSearch"] == cu["indexes"]["vectorSearch"]
    assert de["datasources"]["container"] == cu["datasources"]["container"]
    assert de["datasources"]["credentials"]["connectionString"].startswith("ResourceId=")
    assert "my-index" not in json.dumps((de, cu))
    de_skills, cu_skills = de["skillsets"]["skills"], cu["skillsets"]["skills"]
    assert de_skills[1]["unit"] == "characters"
    assert de_skills[1]["pageOverlapLength"] == 200
    assert cu_skills[0]["chunkingProperties"] == {
        "method": "semantic",
        "unit": "tokens",
        "maximumLength": 2000,
        "overlapLength": 0,
    }
    assert not any("SplitSkill" in skill["@odata.type"] for skill in cu_skills)
    assert de_skills[-1]["inputs"][0]["source"] == "/document/pages/*"
    assert cu_skills[-1]["inputs"][0]["source"] == "/document/text_sections/*/content"
    assert de_skills[-1]["deploymentId"] == cu_skills[-1]["deploymentId"]


@pytest.mark.parametrize(
    ("language", "locale", "expected_analyzer"),
    [("pt", "pt-BR", "pt-Br.microsoft"), ("en", "en-US", "en.microsoft")],
)
def test_resource_builder_uses_supported_content_analyzers_for_both_arms(
    language, locale, expected_analyzer
):
    data = json.loads(experiment_config().model_dump_json())
    data["generation"].update(language=language, locale=locale)
    protocol = new_protocol(ExperimentConfig.model_validate_json(json.dumps(data)))
    for arm in ARMS:
        content = next(
            field
            for field in definitions(protocol, arm)["indexes"]["fields"]
            if field["name"] == "content"
        )
        assert content["analyzer"] == expected_analyzer


def test_snapshot_scans_bound_vector_pages_without_omitting_any_chunks(staged_workspace):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    for index in range(251):
        extra = copy.deepcopy(backend.chunks["de_split"][0])
        extra["id"] = f"z-extra-{index:04d}"
        backend.chunks["de_split"].append(extra)
    expected = {chunk["id"] for chunk in backend.chunks["de_split"]}

    def reject_oversized_scan(request):
        if request.method == "POST" and request.url.path.endswith("/docs/search"):
            body = json.loads(request.content)
            if body.get("search") == "*" and body["top"] > 250:
                raise httpx.ReadTimeout("Oversized vector scan response", request=request)

    azure.client.event_hooks["request"].append(reject_oversized_scan)
    with azure:
        prepare(workspace, azure, live=True)
        ingest(workspace, azure, live=True)
        observed = take_snapshot(workspace, azure, "de_split", live=True)
        assert {chunk.id for chunk in observed.chunks} == expected
        assert len(observed.chunks) == 263
        assert not observed.missing
        scans = [
            json.loads(request.content)
            for request in backend.requests
            if request.method == "POST" and request.url.path.endswith("/docs/search")
        ]
        assert len(scans) == 3
        assert all(body["top"] == 250 for body in scans)
        assert scans[0].get("filter") is None
        assert all("filter" in body for body in scans[1:])
        assert_stable(workspace, azure, "de_split")


def test_real_blob_sdk_and_search_http_freeze_both_fresh_snapshots(staged_workspace):
    workspace = staged_workspace
    azure, backend, blobs, credential = azure_fixture(workspace)
    with azure:
        with pytest.raises(InputError, match="--live"):
            prepare(workspace, azure, live=False)
        assert not backend.requests and not blobs.requests
        prepare(workspace, azure, live=True)
        assert len(blobs.blobs) == 12
        assert all(item["metadata"] == {} for item in blobs.blobs.values())
        assert all("indexers" not in path for path in backend.resources)
        statuses = ingest(workspace, azure, live=True)
        assert all(value["status"] == "success" for value in statuses.values())
        backend.page_size = 3
        snapshots = [take_snapshot(workspace, azure, arm, live=True) for arm in ARMS]
        assert snapshots[0].source_hash == snapshots[1].source_hash
        assert snapshots[0].reference_hash == snapshots[1].reference_hash
        assert all(len(value.chunks) == 12 for value in snapshots)
        assert all(not value.missing for value in snapshots)
        put_count = sum(request.method == "PUT" for request in backend.requests)
        prepare(workspace, azure, live=True)
        ingest(workspace, azure, live=True)
        assert sum(request.method == "PUT" for request in backend.requests) == put_count
        assert_stable(workspace, azure, "de_split")
        backend.chunks["de_split"][0]["content"] += " Changed."
        with pytest.raises(IntegrityError, match="drift"):
            assert_stable(workspace, azure, "de_split")
    assert "https://search.azure.com/.default" in credential.scopes
    assert "https://storage.azure.com/.default" in credential.scopes
    for arm in ARMS:
        skillset_requests = [
            request
            for request in backend.requests
            if request.url.path == "/" + resource_path(workspace, arm, "skillsets")
        ]
        assert {request.method for request in skillset_requests} == {"GET", "PUT"}
        assert all(
            request.url.params["api-version"] == workspace.protocol.config.search.cu_api_version
            for request in skillset_requests
        )


def test_unowned_search_collision_is_not_overwritten(staged_workspace):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    path = resource_path(workspace, "de_split", "indexes")
    existing = {"name": "unowned", "@odata.etag": '"foreign"'}
    backend.resources[path] = copy.deepcopy(existing)
    with azure, pytest.raises(IntegrityError, match="unowned"):
        prepare(workspace, azure, live=True)
    assert backend.resources[path] == existing


@pytest.mark.parametrize("late_kind", ["datasources", "indexers"])
def test_initial_runtime_etags_are_sealed_but_later_changes_remain_drift(
    staged_workspace, late_kind
):
    workspace = staged_workspace
    unused, backend, blobs, credential = azure_fixture(workspace)
    unused.close()
    updated = set()

    def transport(request):
        response = backend(request)
        for arm in ARMS:
            name = workspace.protocol.resource_name(arm, "indexer")
            if (
                request.url.path.endswith("/search.status")
                and name in request.url.path
                and arm not in updated
            ):
                for kind in ("datasources", "indexers"):
                    backend.resources[resource_path(workspace, arm, kind)]["@odata.etag"] = (
                        f'"post-run-{arm}-{kind}"'
                    )
                updated.add(arm)
        return response

    with Azure(
        workspace.protocol, credential=credential, blob_transport=blobs,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    ) as azure:
        prepare(workspace, azure, live=True)
        ingest(workspace, azure, live=True)
        assert updated == set(ARMS)
        observed = take_snapshot(workspace, azure, "de_split", live=True)
        assert len(observed.chunks) == 12
        initial = workspace.get("resource:de_split:" + late_kind)
        sealed = workspace.get("ingested-resources:de_split")[late_kind]
        assert initial["@odata.etag"] != sealed["@odata.etag"]
        assert {key: value for key, value in initial.items() if key != "@odata.etag"} == {
            key: value for key, value in sealed.items() if key != "@odata.etag"
        }
        assert_stable(workspace, azure, "de_split")
        backend.resources[resource_path(workspace, "de_split", late_kind)][
            "@odata.etag"
        ] = '"changed-after-freeze"'
        with pytest.raises(IntegrityError, match="drift"):
            assert_stable(workspace, azure, "de_split")


@pytest.mark.parametrize("kind", ["datasources", "indexers", "indexes", "skillsets"])
def test_initial_ingestion_never_rebases_changed_controlled_resources(staged_workspace, kind):
    workspace = staged_workspace
    unused, backend, blobs, credential = azure_fixture(workspace)
    unused.close()
    changed = False

    def transport(request):
        nonlocal changed
        response = backend(request)
        if request.url.path.endswith("/search.status") and not changed:
            resource = backend.resources[resource_path(workspace, "de_split", kind)]
            resource["@odata.etag"] = '"different-version"'
            if kind == "datasources":
                resource["container"]["query"] += "foreign/"
            elif kind == "indexers":
                resource["skillsetName"] = "foreign-skillset"
            changed = True
        return response

    with Azure(
        workspace.protocol, credential=credential, blob_transport=blobs,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    ) as azure:
        prepare(workspace, azure, live=True)
        with pytest.raises(IntegrityError, match="drift"):
            ingest(workspace, azure, live=True)
    assert workspace.get("ingested-resources:de_split") is None


def test_missing_sources_require_execution_bound_review_and_remain_in_gold(staged_workspace):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    with azure:
        prepare(workspace, azure, live=True)
        ingest(workspace, azure, live=True)
        backend.chunks["content_understanding"].pop()
        with pytest.raises(InputError, match="human audit"):
            take_snapshot(workspace, azure, "content_understanding", live=True)
        reference = released_reference(workspace)
        status = backend.statuses["content_understanding"]["lastResult"]
        audit = IngestionAudit(
            arm="content_understanding",
            execution_hash=digest(status),
            reviewer="Source Reviewer",
            source_failures_only=True,
            missing=(
                MissingSource(
                    doc_id=reference.documents[-1].id,
                    reviewer="Source Reviewer",
                    reason="Reviewed terminal extraction produced no chunks for this exact source.",
                ),
            ),
        )
        observed = take_snapshot(workspace, azure, "content_understanding", live=True, audit=audit)
        assert len(observed.chunks) == 11 and len(observed.missing) == 1
        assert len(reference.documents) == 12


def test_incomplete_auth_failed_and_unmapped_ingestion_are_not_scoreable(staged_workspace):
    workspace = staged_workspace
    azure, backend, _, _ = azure_fixture(workspace)
    with azure:
        prepare(workspace, azure, live=True)
        ingest(workspace, azure, live=True)
        status = backend.statuses["de_split"]["lastResult"]
        status["itemsProcessed"] -= 1
        with pytest.raises(IntegrityError, match="every source"):
            take_snapshot(workspace, azure, "de_split", live=True)
        status["itemsProcessed"] += 1
        status["errors"] = [{"statusCode": 403, "name": "authorization"}]
        with pytest.raises(ProviderError, match="invalidate"):
            take_snapshot(workspace, azure, "de_split", live=True)
        status["errors"] = []
        backend.chunks["de_split"][0]["content_path"] = "https://foreign.blob.core.windows.net/x"
        with pytest.raises(IntegrityError, match="foreign"):
            take_snapshot(workspace, azure, "de_split", live=True)


def test_embedding_and_http_error_translation_use_actual_rest(staged_workspace):
    azure, backend, _, credential = azure_fixture(staged_workspace)
    with azure:
        embedding = azure.embed("Qual e a mensalidade?")
        assert embedding.data["vector"] == [0.1, 0.2, 0.3]
        assert embedding.tokens == 25
        assert "https://ai.azure.com/.default" in credential.scopes
        azure.embed("Outra consulta sobre mensalidades.")
        assert credential.scopes.count("https://ai.azure.com/.default") == 1
        backend.failures["indexes/no-access"] = 403
        with pytest.raises(ProviderError) as failure:
            azure.search("GET", "indexes/no-access")
        assert failure.value.code == "authorization"
        assert "sentinel-sensitive" not in str(failure.value)
        assert not failure.value.retryable


def test_credentials_cannot_be_forwarded_to_an_unconfigured_endpoint(staged_workspace):
    azure, backend, _, credential = azure_fixture(staged_workspace)
    with azure, pytest.raises(InputError, match="outside configured"):
        azure.request(
            "POST",
            "https://unconfigured.example/collect",
            scope="https://search.azure.com/.default",
        )
    assert not backend.requests and not credential.scopes


def test_source_mutation_during_streaming_invalidates_the_experiment(staged_workspace):
    workspace = staged_workspace
    azure, backend, blobs, _ = azure_fixture(workspace)
    document = released_reference(workspace).documents[0]
    path = source_run(workspace) / "corpus" / document.filename
    original = path.read_bytes()
    blobs.after_upload = lambda: path.write_bytes(original + b"changed")
    with azure:
        with pytest.raises(IntegrityError, match="during upload"):
            prepare(workspace, azure, live=True)
        assert workspace.get("invalidated") is not None
        path.write_bytes(original)
        with pytest.raises(IntegrityError, match="permanently"):
            prepare(workspace, azure, live=True)
    assert not backend.resources


@pytest.mark.parametrize(
    "value",
    [None, [], [0, 0, 0], [1, True, 2], [1, 2], [1, 2, float("inf")], [10**400, 2, 3]],
)
def test_invalid_vectors_are_rejected(value):
    with pytest.raises(ProviderError, match="vector"):
        vector_value(value, 3)
