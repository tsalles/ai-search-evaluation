import copy
import json

import pytest
from pydantic import ValidationError

from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.models import ARMS, Query, QueryTuning, SearchVariant
from docgen.evaluation.profiles import retrieval_request
from docgen.evaluation.resources import definitions
from docgen.evaluation.runner import collect
from docgen.evaluation.state import Workspace
from docgen.evaluation.variants import fork_experiment
from tests.evaluation.test_azure import azure_fixture
from tests.evaluation.test_tuning_variants import freeze, variant_config


@pytest.mark.parametrize("analyzer", ["lucene", "standard"])
def test_comparison_queries_require_explicit_in_pipeline_analyzer_fields(analyzer):
    with pytest.raises(ValidationError, match="comparison fields"):
        SearchVariant(query_tuning=QueryTuning(analyzer=analyzer))
    query = Query(id="one", text="Quanto custa a Conta Aurora?")
    body = retrieval_request(
        query, None, profile="semantic-bm25", tuning=QueryTuning(analyzer=analyzer),
    )
    assert body["searchFields"] == "content_" + analyzer
    assert body["semanticQuery"] == query.text
    assert body["semanticConfiguration"] == "content-only"
    assert "vectorQueries" not in body
    with pytest.raises(InputError, match="content-only"):
        retrieval_request(
            query, [0.1], profile="pipeline-entity-hybrid",
            tuning=QueryTuning(analyzer=analyzer),
        )


def test_analyzer_fields_project_exactly_the_same_native_text_without_extra_features(
    staged_workspace, tmp_path,
):
    config = variant_config(staged_workspace, index_tuning={"analyzer_comparison_fields": True})
    path = fork_experiment(staged_workspace, config, tmp_path / "variant")
    with Workspace(path) as workspace:
        for arm in ARMS:
            resources = definitions(workspace.protocol, arm)
            fields = {field["name"]: field for field in resources["indexes"]["fields"]}
            assert fields["content_lucene"]["analyzer"] == "pt-Br.lucene"
            assert fields["content_standard"]["analyzer"] == "standard.lucene"
            mappings = resources["skillsets"]["indexProjections"]["selectors"][0]["mappings"]
            sources = {
                mapping["source"] for mapping in mappings
                if mapping["name"] in {"content", "content_lucene", "content_standard"}
            }
            assert len(sources) == 1
            assert not {"title", "account_names", "entity_data"} & set(fields)
        azure, backend, _, _ = azure_fixture(workspace)
        for chunks in backend.chunks.values():
            for chunk in chunks:
                for field in ("content_lucene", "content_standard"):
                    chunk[field] = chunk["content"]
        with azure:
            freeze(workspace, azure)
            backend.chunks["de_split"][0]["content_lucene"] += " changed"
            with pytest.raises(IntegrityError, match="Analyzer comparison"):
                from docgen.evaluation.snapshots import scan_chunks

                scan_chunks(workspace, azure, "de_split")


@pytest.mark.parametrize("etag", ["*", "", "not-an-etag", '"bad\r\nheader"', '"bad\u00e9"'])
def test_conditional_resource_updates_reject_unsafe_etags_before_authentication(
    staged_workspace, etag,
):
    azure, backend, _, credential = azure_fixture(staged_workspace)
    with azure, pytest.raises(InputError, match="ETag"):
        azure.request(
            "PUT", workspace_url(staged_workspace), scope="https://search.azure.com/.default",
            body={}, if_match=etag,
        )
    assert not backend.requests and not credential.scopes


def workspace_url(workspace):
    return (
        workspace.protocol.config.search.endpoint + "/indexes/"
        + workspace.protocol.resource_name("de_split", "index")
        + "?api-version=2026-04-01&allowIndexDowntime=true"
    )


def test_conditional_bm25_update_keeps_other_index_settings_and_rejects_stale_etags(
    staged_workspace, tmp_path,
):
    config = variant_config(staged_workspace, index_tuning={})
    path = fork_experiment(staged_workspace, config, tmp_path / "variant")
    with Workspace(path) as workspace:
        azure, backend, _, _ = azure_fixture(workspace)
        with azure:
            freeze(workspace, azure)
            key = "indexes/" + workspace.protocol.resource_name("de_split", "index")
            original = copy.deepcopy(backend.resources[key])
            body = {k: v for k, v in original.items() if k != "@odata.etag"}
            body["similarity"]["b"] = 0.25
            response = azure.request(
                "PUT", workspace_url(workspace), scope="https://search.azure.com/.default",
                body=body, if_match=original["@odata.etag"],
            )
            updated = response.data
            assert updated["similarity"]["b"] == 0.25
            assert updated["fields"] == original["fields"]
            assert updated["vectorSearch"] == original["vectorSearch"]
            with pytest.raises(ProviderError, match="412"):
                azure.request(
                    "PUT", workspace_url(workspace), scope="https://search.azure.com/.default",
                    body=body, if_match=original["@odata.etag"],
                )
            sent = [
                request for request in backend.requests
                if request.method == "PUT" and "if-match" in request.headers
            ]
            assert len(sent) == 2
            assert all("if-none-match" not in request.headers for request in sent)
            assert json.loads(sent[0].content)["similarity"]["b"] == 0.25


def test_epoch_indexes_cannot_be_queried_as_the_original_frozen_cli_collection(staged_workspace):
    staged_workspace.put("index-parameter-epochs", {"version": "1"})
    azure, backend, _, _ = azure_fixture(staged_workspace)
    with azure, pytest.raises(InputError, match="epoch executor"):
        collect(staged_workspace, azure, live=True)
    assert not backend.requests


@pytest.mark.parametrize("timeout", [True, 0, -1, 61, float("nan"), float("inf")])
def test_per_attempt_transport_timeout_cannot_exceed_or_bypass_the_frozen_limit(
    staged_workspace, timeout,
):
    azure, backend, _, credential = azure_fixture(staged_workspace)
    with azure, pytest.raises(InputError, match="frozen deadline"):
        azure.request(
            "GET", workspace_url(staged_workspace), scope="https://search.azure.com/.default",
            timeout_seconds=timeout,
        )
    assert not backend.requests and not credential.scopes
