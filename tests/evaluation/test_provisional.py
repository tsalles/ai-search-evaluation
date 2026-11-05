import json
import shutil
from types import SimpleNamespace

import httpx
import pytest

from docgen.cli import main
from docgen.errors import InputError, IntegrityError
from docgen.evaluation.azure import Azure
from docgen.evaluation.corpus import generate_sources, source_run
from docgen.evaluation.models import ExperimentConfig
from docgen.evaluation.reference import (
    build_reference,
    release_reference,
    released_reference,
    review_intent,
    validate_reference,
)
from docgen.evaluation.state import Workspace, new_protocol
from docgen.evaluation.variants import fork_experiment
from tests.evaluation.azure_double import Credential
from tests.evaluation.fixtures import FamilyProvider, experiment_config, fresh_workspace
from tests.evaluation.test_azure import azure_fixture


@pytest.fixture(scope="session")
def provisional_draft_template(tmp_path_factory):
    with fresh_workspace(tmp_path_factory.mktemp("provisional-draft")) as workspace:
        assert generate_sources(workspace, provider=FamilyProvider()).status == "complete"
        build_reference(workspace)
        path = workspace.path
    return path


@pytest.fixture
def draft_workspace(tmp_path, provisional_draft_template):
    target = tmp_path / provisional_draft_template.name
    shutil.copytree(provisional_draft_template, target)
    with Workspace(target) as workspace:
        yield workspace


@pytest.fixture(scope="session")
def provisional_pilot_template(tmp_path_factory):
    data = json.loads(experiment_config().model_dump_json())
    data["family_count"] = 3
    data["generation"]["count"] = 18
    data["split_weights"] = {"calibration": 0, "development": 0.3, "test": 0.7}
    protocol = new_protocol(ExperimentConfig.model_validate_json(json.dumps(data)))
    with Workspace.create(tmp_path_factory.mktemp("provisional-pilot"), protocol) as workspace:
        assert generate_sources(workspace, provider=FamilyProvider()).status == "complete"
        build_reference(workspace)
        path = workspace.path
    return path


@pytest.fixture
def pilot_workspace(tmp_path, provisional_pilot_template):
    target = tmp_path / provisional_pilot_template.name
    shutil.copytree(provisional_pilot_template, target)
    with Workspace(target) as workspace:
        yield workspace


@pytest.fixture(scope="session")
def provisional_study_template(tmp_path_factory):
    data = json.loads(experiment_config().model_dump_json())
    data["family_count"] = 51
    data["generation"]["count"] = 306
    data["generation"]["limits"]["max_requests"] = 1000
    data["split_weights"] = {"calibration": 0.94, "development": 0.02, "test": 0.04}
    protocol = new_protocol(ExperimentConfig.model_validate_json(json.dumps(data)))
    with Workspace.create(tmp_path_factory.mktemp("provisional-study"), protocol) as workspace:
        generated = generate_sources(workspace, provider=FamilyProvider())
        assert generated.status == "complete", generated.model_dump(mode="json")
        build_reference(workspace)
        path = workspace.path
    return path


@pytest.fixture
def study_workspace(tmp_path, provisional_study_template):
    target = tmp_path / provisional_study_template.name
    shutil.copytree(provisional_study_template, target)
    with Workspace(target) as workspace:
        yield workspace


def test_provisional_release_is_explicit_sealed_and_never_fakes_human_review(draft_workspace):
    workspace = draft_workspace
    with pytest.raises(InputError, match="Human review"):
        release_reference(workspace)
    reference = release_reference(workspace, provisional=True)
    assert reference.status == "provisional"
    assert all(not intent.reviews for intent in reference.intents)
    assert all(
        query.authorship == "template" for intent in reference.intents for query in intent.queries
    )
    assert released_reference(workspace) == reference
    assert len((workspace.path / "qrels.trec").read_bytes().splitlines()) == 24 * 12
    assert release_reference(workspace, provisional=True) == reference
    with pytest.raises(InputError, match="mode"):
        release_reference(workspace, provisional_pilot=True)
    with pytest.raises(InputError, match="mode"):
        release_reference(workspace)
    with pytest.raises(InputError, match="Human review"):
        validate_reference(workspace, reference, release=True)
    with pytest.raises(InputError, match="released"):
        review_intent(
            workspace,
            intent_id=reference.intents[0].id,
            reviewer="Actual future reviewer",
            certify_scope=True,
        )


@pytest.mark.parametrize(
    ("families", "weights"),
    [
        (3, {"calibration": 0, "development": 0, "test": 1}),
        (50, {"calibration": 0, "development": 0, "test": 1}),
        (2, {"calibration": 1, "development": 0, "test": 0}),
        (2, {"calibration": 0, "development": 1, "test": 0}),
        (2, {"calibration": 0.5, "development": 0, "test": 0.5}),
    ],
)
def test_provisional_release_rejects_non_smoke_protocols_before_generation(
    tmp_path, families, weights
):
    data = json.loads(experiment_config().model_dump_json())
    data.update(family_count=families, split_weights=weights)
    data["generation"]["count"] = families * 6
    protocol = new_protocol(ExperimentConfig.model_validate_json(json.dumps(data)))
    with Workspace.create(tmp_path, protocol) as workspace:
        with pytest.raises(InputError, match="12 documents"):
            release_reference(workspace, provisional=True)
        assert not source_run(workspace).exists()
        assert workspace.get("reference") is None
        assert workspace.get("provisional-reference") is None


def test_larger_provisional_pilot_is_separate_and_keeps_default_human_review(pilot_workspace):
    with pytest.raises(InputError, match="Human review"):
        release_reference(pilot_workspace)
    with pytest.raises(InputError, match="12 documents"):
        release_reference(pilot_workspace, provisional=True)
    reference = release_reference(pilot_workspace, provisional_pilot=True)
    assert reference.status == "provisional"
    assert pilot_workspace.get("provisional-reference")["mode"] == "automated_pilot"
    assert released_reference(pilot_workspace) == reference
    assert release_reference(pilot_workspace, provisional_pilot=True) == reference
    assert all(not intent.reviews for intent in reference.intents)
    assert all(
        query.authorship == "template" for intent in reference.intents for query in intent.queries
    )
    with pytest.raises(InputError, match="Human review"):
        validate_reference(pilot_workspace, reference, release=True)
    with pytest.raises(InputError, match="mode"):
        release_reference(pilot_workspace, provisional=True)


@pytest.mark.parametrize(
    ("families", "weights"),
    [
        (2, {"calibration": 0, "development": 0, "test": 1}),
        (51, {"calibration": 0.2, "development": 0.2, "test": 0.6}),
        (3, {"calibration": 1, "development": 0, "test": 0}),
        (3, {"calibration": 0.5, "development": 0.4, "test": 0.1}),
    ],
)
def test_provisional_pilot_rejects_out_of_scope_protocols_before_generation(
    tmp_path, families, weights
):
    data = json.loads(experiment_config().model_dump_json())
    data.update(family_count=families, split_weights=weights)
    data["generation"]["count"] = families * 6
    protocol = new_protocol(ExperimentConfig.model_validate_json(json.dumps(data)))
    with Workspace.create(tmp_path, protocol) as workspace:
        with pytest.raises(InputError, match="300 documents"):
            release_reference(workspace, provisional_pilot=True)
        assert not source_run(workspace).exists()
        assert workspace.get("reference") is None


def test_300_document_pilot_policy_accepts_predeclared_held_out_plan_without_generating(
    tmp_path,
):
    data = json.loads(experiment_config().model_dump_json())
    data.update(
        family_count=50,
        split_weights={"calibration": 0.2, "development": 0.2, "test": 0.6},
    )
    data["generation"]["count"] = 300
    protocol = new_protocol(ExperimentConfig.model_validate_json(json.dumps(data)))
    with Workspace.create(tmp_path, protocol) as workspace:
        with pytest.raises(InputError, match="Cannot load"):
            release_reference(workspace, provisional_pilot=True)
        assert not source_run(workspace).exists()
        assert workspace.get("reference") is None


@pytest.mark.parametrize("families", [51, 166])
def test_provisional_study_accepts_exact_complete_family_boundaries_before_generation(
    tmp_path, families,
):
    data = json.loads(experiment_config().model_dump_json())
    data.update(
        family_count=families,
        split_weights={"calibration": 0.56, "development": 0.20, "test": 0.24},
    )
    data["generation"]["count"] = families * 6
    protocol = new_protocol(ExperimentConfig.model_validate_json(json.dumps(data)))
    with Workspace.create(tmp_path, protocol) as workspace:
        with pytest.raises(InputError, match="Cannot load"):
            release_reference(workspace, provisional_study=True)
        assert not source_run(workspace).exists()
        assert workspace.get("reference") is None
        if families == 166:
            planned = protocol.generation_config.generation.families
            assert protocol.config.generation.count == 996
            assert sum(family.split == "test" for family in planned) == 40


@pytest.mark.parametrize(
    ("families", "weights"),
    [
        (2, {"calibration": 0, "development": 0, "test": 1}),
        (50, {"calibration": 0.2, "development": 0.2, "test": 0.6}),
        (51, {"calibration": 1, "development": 0, "test": 0}),
        (51, {"calibration": 0.99, "development": 0, "test": 0.01}),
    ],
)
def test_provisional_study_rejects_wrong_sizes_or_inadequate_test_families_before_generation(
    tmp_path, families, weights,
):
    data = json.loads(experiment_config().model_dump_json())
    data.update(family_count=families, split_weights=weights)
    data["generation"]["count"] = families * 6
    protocol = new_protocol(ExperimentConfig.model_validate_json(json.dumps(data)))
    with Workspace.create(tmp_path, protocol) as workspace:
        with pytest.raises(InputError, match="306 to 996"):
            release_reference(workspace, provisional_study=True)
        assert not source_run(workspace).exists()
        assert workspace.get("reference") is None


def test_provisional_study_requires_raw_only_protocol_before_generation(tmp_path):
    data = json.loads(experiment_config().model_dump_json())
    data.update(family_count=51)
    data["generation"]["count"] = 306
    protocol = new_protocol(ExperimentConfig.model_validate_json(json.dumps(data)))
    historical = protocol.model_copy(update={"schema_version": "1", "enrichment_policy": None})
    with Workspace.create(tmp_path, historical) as workspace:
        with pytest.raises(InputError, match="historical"):
            release_reference(workspace, provisional_study=True)
        assert not source_run(workspace).exists()
        assert workspace.get("reference") is None


def test_large_study_keeps_human_review_explicit_and_release_mode_immutable(study_workspace):
    with pytest.raises(InputError, match="Human review"):
        release_reference(study_workspace)
    with pytest.raises(InputError, match="300 documents"):
        release_reference(study_workspace, provisional_pilot=True)
    reference = release_reference(study_workspace, provisional_study=True)
    assert len(reference.documents) == 306
    assert reference.status == "provisional"
    assert study_workspace.get("provisional-reference")["mode"] == "automated_study"
    assert released_reference(study_workspace) == reference
    assert release_reference(study_workspace, provisional_study=True) == reference
    assert all(not intent.reviews for intent in reference.intents)
    assert all(
        query.authorship == "template" for intent in reference.intents for query in intent.queries
    )
    with pytest.raises(InputError, match="Human review"):
        validate_reference(study_workspace, reference, release=True)
    with pytest.raises(InputError, match="mode"):
        release_reference(study_workspace, provisional_pilot=True)
    with pytest.raises(InputError, match="mode"):
        release_reference(study_workspace)


def test_provisional_study_preserves_evidence_integrity(study_workspace):
    reference = build_reference(study_workspace)
    changed = reference.model_copy(update={"evidence": reference.evidence[:-1]})
    study_workspace.replace_draft(
        "reference-draft.json", changed.model_dump_json(indent=2).encode(),
    )
    with pytest.raises(IntegrityError, match="evidence"):
        release_reference(study_workspace, provisional_study=True)
    assert study_workspace.get("reference") is None
    assert study_workspace.get("provisional-reference") is None


def test_provisional_study_fork_preserves_unreviewed_provenance_and_immutable_qrels(
    study_workspace, tmp_path,
):
    reference = release_reference(study_workspace, provisional_study=True)
    data = json.loads(study_workspace.protocol.config.model_dump_json())
    data["search"]["variant"] = {"embedding_context": False}
    target = fork_experiment(
        study_workspace, ExperimentConfig.model_validate_json(json.dumps(data)), tmp_path / "forks",
    )
    with Workspace(target) as fork:
        inherited = released_reference(fork)
        assert inherited.status == "provisional"
        assert inherited.intents == reference.intents
        assert fork.get("provisional-reference")["mode"] == "automated_study"
        assert fork.get("source-lineage")["human_review_certified"] is False
        assert (fork.path / "qrels.trec").read_bytes() == (
            study_workspace.path / "qrels.trec"
        ).read_bytes()


@pytest.mark.parametrize("flag", [None, "yes", 1])
def test_provisional_study_requires_a_boolean_opt_in(pilot_workspace, flag):
    with pytest.raises(InputError, match="Boolean"):
        release_reference(pilot_workspace, provisional_study=flag)
    assert pilot_workspace.get("reference") is None


@pytest.mark.parametrize("other_flag", ["provisional", "provisional_pilot"])
def test_provisional_study_cannot_be_combined_with_other_policies(
    pilot_workspace, capsys, other_flag,
):
    with pytest.raises(InputError, match="one provisional"):
        release_reference(pilot_workspace, provisional_study=True, **{other_flag: True})
    option = "--provisional" if other_flag == "provisional" else "--provisional-pilot"
    assert main(
        [
            "experiment", "release", "--experiment", str(pilot_workspace.path),
            "--provisional-study", option, "--json",
        ]
    ) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid_input"
    assert pilot_workspace.get("reference") is None


@pytest.mark.parametrize("flag", [None, "yes", 1])
def test_provisional_pilot_requires_a_boolean_opt_in(pilot_workspace, flag):
    with pytest.raises(InputError, match="Boolean"):
        release_reference(pilot_workspace, provisional_pilot=flag)
    assert pilot_workspace.get("reference") is None


def test_provisional_modes_are_mutually_exclusive(pilot_workspace, capsys):
    with pytest.raises(InputError, match="one provisional"):
        release_reference(pilot_workspace, provisional=True, provisional_pilot=True)
    assert (
        main(
            [
                "experiment", "release", "--experiment", str(pilot_workspace.path),
                "--provisional", "--provisional-pilot", "--json",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["status"] == "invalid_input"
    assert pilot_workspace.get("reference") is None


def test_provisional_status_without_explicit_release_record_is_rejected(draft_workspace):
    reference = build_reference(draft_workspace).model_copy(update={"status": "provisional"})
    draft_workspace.record("reference", reference)
    with pytest.raises(IntegrityError, match="explicit provisional"):
        released_reference(draft_workspace)


@pytest.mark.parametrize("flag", [None, "yes", 1])
def test_provisional_release_rejects_non_boolean_opt_in(draft_workspace, flag):
    with pytest.raises(InputError, match="Boolean"):
        release_reference(draft_workspace, provisional=flag)
    assert draft_workspace.get("reference") is None


def test_provisional_release_does_not_override_invalidated_protocols(draft_workspace):
    draft_workspace.put("invalidated", {"reason": "Observed resource drift."})
    with pytest.raises(IntegrityError, match="invalidated"):
        release_reference(draft_workspace, provisional=True)
    assert draft_workspace.get("reference") is None


def test_human_reviewed_reference_cannot_be_downgraded(staged_workspace):
    with pytest.raises(InputError, match="mode"):
        release_reference(staged_workspace, provisional=True)
    assert released_reference(staged_workspace).status == "released"
    assert staged_workspace.get("provisional-reference") is None


def test_provisional_release_preserves_source_evidence_checks(draft_workspace):
    reference = build_reference(draft_workspace)
    changed = reference.model_copy(update={"evidence": reference.evidence[:-1]})
    draft_workspace.replace_draft(
        "reference-draft.json", changed.model_dump_json(indent=2).encode()
    )
    with pytest.raises(IntegrityError, match="evidence"):
        release_reference(draft_workspace, provisional=True)
    assert draft_workspace.get("reference") is None
    assert draft_workspace.get("provisional-reference") is None


def test_provisional_reference_exports_remain_checksum_sealed(draft_workspace):
    release_reference(draft_workspace, provisional=True)
    path = draft_workspace.path / "qrels.trec"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(IntegrityError, match="differs"):
        released_reference(draft_workspace)


@pytest.mark.parametrize(
    ("workspace_fixture", "release_flag", "mode", "responses", "source_count"),
    [
        ("draft_workspace", "--provisional", "automated_smoke", 48, 12),
        ("pilot_workspace", "--provisional-pilot", "automated_pilot", 48, 18),
        ("study_workspace", "--provisional-study", "automated_study", 48, 306),
    ],
)
def test_provisional_cli_runs_all_phases_and_labels_the_report(
    request, workspace_fixture, release_flag, mode, responses, source_count, monkeypatch, capsys
):
    import tiktoken

    import docgen.evaluation.cli as cli

    workspace = request.getfixturevalue(workspace_fixture)
    directory = workspace.path
    workspace.close()
    assert (
        main(
            [
                "experiment", "release", "--experiment", str(directory),
                release_flag, "--json",
            ]
        )
        == 0
    )
    released = json.loads(capsys.readouterr().out)
    assert released["details"]["reference_status"] == "provisional"
    assert released["details"]["provisional_policy"] == mode
    with Workspace(directory) as workspace:
        unused, backend, blobs, _ = azure_fixture(workspace)
        unused.close()
        protocol = workspace.protocol

    def client_factory(selected):
        assert selected == protocol
        return Azure(
            selected,
            credential=Credential(),
            blob_transport=blobs,
            http_client=httpx.Client(transport=httpx.MockTransport(backend)),
        )

    monkeypatch.setattr(cli, "Azure", client_factory)
    monkeypatch.setattr(
        tiktoken, "get_encoding",
        lambda _: SimpleNamespace(encode=lambda text, **kwargs: list(range(25))),
    )
    for phase, extra in (
        ("prepare", ["--live"]),
        ("ingest", ["--live"]),
        ("snapshot", ["--arm", "de_split", "--live"]),
        ("snapshot", ["--arm", "content_understanding", "--live"]),
        ("collect", ["--live"]),
        ("score", []),
        ("status", []),
    ):
        code = main(["experiment", phase, "--experiment", str(directory), *extra, "--json"])
        result = json.loads(capsys.readouterr().out)
        assert code == 0, (phase, result)
        if phase == "score":
            assert result["details"]["report_status"] == "provisional"
        if phase == "status":
            assert result["details"]["reference_status"] == "provisional"
    report = json.loads((directory / "report-test.json").read_bytes())
    assert report["status"] == "provisional"
    assert report["reference_status"] == "provisional"
    assert report["human_review_certified"] is False
    assert report["eligible_for_confirmatory_conclusions"] is False
    assert report["denominators"]["arm_query_responses"] == responses
    assert report["denominators"]["source_documents"] == source_count
    assert report["denominators"]["families"] == 2
    assert report["denominators"]["utterances"] == 24
    assert any("PROVISIONAL" in warning for warning in report["warnings"])
    if mode in {"automated_pilot", "automated_study"}:
        assert report["reference_assurance_mode"] == mode
        assurance = "exploratory-study" if mode == "automated_study" else "exploratory-pilot"
        assert any(assurance in warning for warning in report["warnings"])
