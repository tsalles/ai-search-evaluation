import copy
import hashlib
import json
from pathlib import Path

import pytest
from filelock import FileLock

from docgen.cli import main
from docgen.errors import InputError, IntegrityError
from docgen.evaluation.inventory import export_inventory
from docgen.evaluation.resources import definitions
from docgen.evaluation.state import Workspace, new_protocol
from tests.evaluation.fixtures import experiment_config


def seed_resources(workspace):
    terminal = {}
    for arm in ("de_split", "content_understanding"):
        observed = {}
        for kind, value in definitions(workspace.protocol, arm).items():
            workspace.put(f"create:resource:{arm}:{kind}", value)
            actual = copy.deepcopy(value)
            actual["@odata.etag"] = '"created"'
            if kind == "datasources":
                actual["credentials"]["connectionString"] = None
            workspace.put(f"resource:{arm}:{kind}", actual)
            observed[kind] = actual
        terminal[arm] = copy.deepcopy(observed)
        for kind in ("datasources", "indexers"):
            terminal[arm][kind]["@odata.etag"] = '"after-indexing"'
        workspace.put("ingested-resources:" + arm, terminal[arm])
    return terminal


def manifest(result):
    return json.loads(Path(result["inventory_path"]).read_text(encoding="utf-8"))


def configurations(result, **filters):
    inventory = manifest(result)
    return [
        item for experiment in inventory["experiments"] for item in experiment["configurations"]
        if all(item.get(key) == value for key, value in filters.items())
    ]


def exported(result, item):
    return json.loads(
        (Path(result["inventory_path"]).parent / item["file"]).read_text(encoding="utf-8")
    )


def test_inventory_exports_exact_submitted_and_observed_versions_without_touching_state(tmp_path):
    with Workspace.create(tmp_path / "source", new_protocol(experiment_config())) as workspace:
        terminal = seed_resources(workspace)
        workspace.database.execute(
            "INSERT INTO attempts(kind,tag,status) VALUES ('search','pending','in_flight')"
        )
        workspace.database.commit()
        database = workspace.path / "evaluation.sqlite3"
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        result = export_inventory(workspace.path, tmp_path / "inventory")
        assert result["experiment_count"] == 1 and result["configuration_count"] == 25
        assert result["live_calls"] == 0 and result["source_workspaces_modified"] is False
        assert hashlib.sha256(database.read_bytes()).hexdigest() == before
        assert workspace.database.execute(
            "SELECT status FROM attempts WHERE tag='pending'"
        ).fetchone()[0] == "in_flight"
        submitted = configurations(result, arm="de_split", kind="datasource", phase="submitted")[0]
        assert exported(result, submitted) == definitions(workspace.protocol, "de_split")[
            "datasources"
        ]
        initial = configurations(
            result, arm="de_split", kind="indexer", phase="observed-initial",
        )[0]
        ingested = configurations(
            result, arm="de_split", kind="indexer", phase="observed-ingested",
        )[0]
        assert exported(result, initial)["@odata.etag"] == '"created"'
        assert exported(result, ingested) == terminal["de_split"]["indexers"]
        assert submitted["redacted_json_pointers"] == []
        assert ingested["api_version"] == workspace.protocol.config.search.query_api_version
        latest = manifest(result)["experiments"][0]["latest_observed_resources"]["de_split"]
        assert latest["indexer"] == ingested
        skill = configurations(result, kind="skillset", phase="submitted")[0]
        assert skill["api_version"] == workspace.protocol.config.search.cu_api_version


def test_inventory_preserves_all_epoch_definitions_and_query_policies(tmp_path):
    with Workspace.create(tmp_path / "source", new_protocol(experiment_config())) as workspace:
        terminal = seed_resources(workspace)
        first = {arm: value["indexes"] for arm, value in terminal.items()}
        second = copy.deepcopy(first)
        for value in second.values():
            value["similarity"] = {
                "@odata.type": "#Microsoft.Azure.Search.BM25Similarity", "k1": 2.4, "b": 0.75,
            }
            value["@odata.etag"] = '"tuned"'
        workspace.put("index-epoch-state:000000", {"sequence": 0, "definitions": first})
        workspace.put("index-epoch-state:000001", {"sequence": 1, "definitions": second})
        workspace.put("index-epoch-applied:000001:de_split", second["de_split"])
        policy = {"policies": {"de_split": {"profile": "semantic-bm25"}}}
        workspace.put("index-epoch-candidate:selected", policy)
        plan = {"method": "semantic-bm25", "semantic_reranking": True, "vector_k": None}
        workspace.put("collection-plan:development:semantic-bm25", plan)
        result = export_inventory(workspace.path, tmp_path / "inventory")
        epochs = [
            item for item in configurations(result, kind="index")
            if item["phase"].startswith("epoch-")
        ]
        assert len(epochs) == 4
        assert {item["epoch"] for item in epochs} == {0, 1}
        tuned = next(item for item in epochs if item["epoch"] == 1 and item["arm"] == "de_split")
        assert exported(result, tuned) == second["de_split"]
        latest = manifest(result)["experiments"][0]["latest_observed_resources"]["de_split"]
        assert latest["index"]["epoch"] == 1
        assert latest["index"]["phase"] == "epoch-000001"
        assert exported(result, configurations(result, kind="query-policy")[0]) == policy
        assert exported(result, configurations(result, kind="query-plan")[0]) == plan


def test_inventory_marks_missing_and_failed_resources_without_reconstructing_configs(tmp_path):
    protocol = new_protocol(experiment_config()).model_copy(
        update={"schema_version": "1", "enrichment_policy": None},
    )
    with Workspace.create(tmp_path / "source", protocol) as workspace:
        old = definitions(workspace.protocol, "de_split")["indexes"]
        old["fields"][2]["analyzer"] = "pt.microsoft"
        workspace.put("create:resource:de_split:indexes", old)
        workspace.put("invalidated", {"reason": "historical_failure"})
        result = export_inventory(workspace.path, tmp_path / "inventory")
        item = manifest(result)["experiments"][0]
        assert item["invalidated"] is True
        assert item["protocol_schema_version"] == "1"
        assert item["resource_coverage"]["de_split"]["observed-initial"]["not_recorded"] == [
            "datasource", "index", "indexer", "skillset",
        ]
        original = configurations(result, phase="submitted")[0]
        assert exported(result, original)["fields"][2]["analyzer"] == "pt.microsoft"
        assert not configurations(result, phase="observed-initial")


def test_inventory_lists_plan_only_workspaces_and_never_claims_deployment(tmp_path):
    with Workspace.create(tmp_path / "source", new_protocol(experiment_config())) as workspace:
        result = export_inventory(workspace.path, tmp_path / "inventory")
        item = manifest(result)["experiments"][0]
        assert item["configuration_records_present"] is False
        assert result["configuration_count"] == 1
        assert configurations(result)[0]["kind"] == "search-settings"


def test_inventory_preserves_pilot_schema_repair_submissions_and_observations(tmp_path):
    with Workspace.create(tmp_path / "source", new_protocol(experiment_config())) as workspace:
        before = {}
        for kind, body in definitions(workspace.protocol, "de_split").items():
            observed = copy.deepcopy(body)
            observed["@odata.etag"] = '"initial"'
            workspace.put(f"create:resource:de_split:{kind}", body)
            workspace.put(f"resource:de_split:{kind}", observed)
            before[kind] = observed
        after = copy.deepcopy(before)
        after["indexes"]["fields"].append({
            "name": "audit_payload", "type": "Edm.String", "searchable": False,
            "filterable": False, "sortable": False, "facetable": False,
        })
        after["indexes"]["@odata.etag"] = '"repaired"'
        submitted_index = copy.deepcopy(after["indexes"])
        submitted_index.pop("@odata.etag")
        intent = {
            "before": before, "submitted_index": submitted_index,
            "submitted_skillset": before["skillsets"],
        }
        workspace.put("section-study:resource-repair:0001:intent", intent)
        workspace.put("section-study:resource-repair:0001", {"after": after})
        result = export_inventory(workspace.path, tmp_path / "inventory")
        proposed = configurations(
            result, kind="index", phase="submitted-pilot-repair",
        )
        assert len(proposed) == 1 and exported(result, proposed[0]) == submitted_index
        repaired = configurations(
            result, kind="index", phase="observed-pilot-repair",
        )
        assert len(repaired) == 1 and exported(result, repaired[0]) == after["indexes"]
        latest = manifest(result)["experiments"][0]["latest_observed_resources"]["de_split"]
        assert latest["index"]["phase"] == "observed-pilot-repair"
        assert not configurations(
            result, arm="content_understanding", phase="observed-pilot-repair",
        )


def test_inventory_redacts_credentials_visibly_and_preserves_nonsecret_resource_ids(tmp_path):
    with Workspace.create(tmp_path / "source", new_protocol(experiment_config())) as workspace:
        source = definitions(workspace.protocol, "de_split")["datasources"]
        source["credentials"]["connectionString"] = "AccountName=account;AccountKey=sentinel-secret"
        workspace.put("create:resource:de_split:datasources", source)
        skill = definitions(workspace.protocol, "de_split")["skillsets"]
        skill["headers"] = {"Authorization": "Bearer sentinel-token"}
        skill["privateEndpoint"] = "https://example.test/blob?sig=sentinel-signature"
        workspace.put("create:resource:de_split:skillsets", skill)
        result = export_inventory(workspace.path, tmp_path / "inventory")
        raw = "".join(
            json.dumps(exported(result, item)) for item in configurations(result)
        ) + Path(result["inventory_path"]).read_text(encoding="utf-8")
        assert all(value not in raw for value in (
            "sentinel-secret", "sentinel-token", "sentinel-signature",
        ))
        entry = configurations(result, kind="datasource")[0]
        assert entry["redacted_json_pointers"] == ["/credentials/connectionString"]
        assert entry["configuration_sha256"] != entry["file_sha256"]
        entry = configurations(result, kind="skillset")[0]
        assert set(entry["redacted_json_pointers"]) == {
            "/headers/Authorization", "/privateEndpoint",
        }


@pytest.mark.parametrize("corrupt", ["record", "protocol"])
def test_inventory_rejects_source_corruption_without_publishing_a_catalog(tmp_path, corrupt):
    with Workspace.create(tmp_path / "source", new_protocol(experiment_config())) as workspace:
        seed_resources(workspace)
        if corrupt == "record":
            workspace.database.execute(
                "UPDATE records SET hash='wrong' WHERE name='resource:de_split:indexes'"
            )
            workspace.database.commit()
        else:
            path = workspace.path / "protocol.json"
            path.write_bytes(path.read_bytes() + b"\n")
        with pytest.raises(IntegrityError, match="checksum"):
            export_inventory(workspace.path, tmp_path / "inventory")
        assert not (tmp_path / "inventory" / "inventory.json").exists()


def test_inventory_is_idempotent_and_preserves_previous_catalog_revisions(tmp_path):
    with Workspace.create(tmp_path / "source", new_protocol(experiment_config())) as workspace:
        seed_resources(workspace)
        first = export_inventory(workspace.path, tmp_path / "inventory")
        assert export_inventory(workspace.path, tmp_path / "inventory") == first
        original = Path(first["versioned_inventory_path"]).read_bytes()
        workspace.put("collection-plan:new-profile", {"method": "bm25"})
        second = export_inventory(workspace.path, tmp_path / "inventory")
        assert first["versioned_inventory_path"] != second["versioned_inventory_path"]
        assert Path(first["versioned_inventory_path"]).read_bytes() == original


def test_inventory_rejects_unsafe_output_and_unrelated_existing_catalogs(tmp_path):
    with Workspace.create(tmp_path / "source", new_protocol(experiment_config())) as workspace:
        with pytest.raises(InputError, match="outside"):
            export_inventory(workspace.path, workspace.path / "inventory")
        output = tmp_path / "inventory"
        output.mkdir()
        existing = output / "inventory.json"
        existing.write_text('{"unrelated":true}', encoding="utf-8")
        with pytest.raises(InputError, match="another source"):
            export_inventory(workspace.path, output)
        assert existing.read_text(encoding="utf-8") == '{"unrelated":true}'


def test_inventory_cli_backfills_multiple_categories_without_azure_or_source_mutations(
    tmp_path, capsys,
):
    root = tmp_path / "evaluations"
    paths = []
    for category in ("smoke", "main"):
        with Workspace.create(root / category, new_protocol(experiment_config())) as workspace:
            seed_resources(workspace)
            paths.append(workspace.path)
    before = {
        str(path): hashlib.sha256((path / "evaluation.sqlite3").read_bytes()).hexdigest()
        for path in paths
    }
    output = tmp_path / "inventory"
    assert main([
        "experiment", "inventory", "--root", str(root), "--output", str(output), "--json",
    ]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["status"] == "ready"
    assert value["details"]["experiment_count"] == 2
    assert value["details"]["configuration_count"] == 50
    assert value["reports"]["search_inventory"] == str(output / "inventory.json")
    assert before == {
        str(path): hashlib.sha256((path / "evaluation.sqlite3").read_bytes()).hexdigest()
        for path in paths
    }


def test_inventory_rejects_modified_configuration_files_without_replacing_the_catalog(tmp_path):
    with Workspace.create(tmp_path / "source", new_protocol(experiment_config())) as workspace:
        seed_resources(workspace)
        result = export_inventory(workspace.path, tmp_path / "inventory")
        catalog = Path(result["inventory_path"])
        before = catalog.read_bytes()
        entry = configurations(result, kind="index", phase="submitted")[0]
        file = catalog.parent / entry["file"]
        file.write_text('{"changed":true}', encoding="utf-8")
        with pytest.raises(IntegrityError, match="configuration export differs"):
            export_inventory(workspace.path, catalog.parent)
        assert catalog.read_bytes() == before


def test_inventory_lock_prevents_concurrent_publication(tmp_path):
    with Workspace.create(tmp_path / "source", new_protocol(experiment_config())) as workspace:
        output = tmp_path / "inventory"
        output.mkdir()
        with FileLock(output / ".inventory.lock"):
            with pytest.raises(IntegrityError, match="locked"):
                export_inventory(workspace.path, output)
        assert not (output / "inventory.json").exists()
