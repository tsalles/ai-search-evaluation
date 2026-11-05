import argparse
from collections import Counter

from azure.identity import AzureCliCredential
from pydantic import JsonValue

from docgen.errors import InputError
from docgen.evaluation.azure import Azure
from docgen.evaluation.corpus import generate_sources, source_run
from docgen.evaluation.models import (
    ARMS,
    IngestionAudit,
    QueryCohort,
    Reference,
    load_experiment_config,
)
from docgen.evaluation.profiles import PROFILES, report_suffix, scope
from docgen.evaluation.reference import (
    build_reference,
    load_record,
    provisional_policy,
    release_reference,
    review_intent,
    validate_reference,
)
from docgen.evaluation.state import Protocol, Workspace, digest, new_protocol, require_live
from docgen.persistence import safe_child
from docgen.planning import base_result, create_plan


def overview(protocol: Protocol) -> dict[str, JsonValue]:
    generation = protocol.generation_config.generation
    if generation is None or generation.families is None:
        raise InputError("The fresh family-aware generation plan is missing.")
    create_plan(protocol.generation_config, run_id=protocol.source_run_id)
    splits = Counter(family.split for family in generation.families)
    return {
        "experiment_id": protocol.id,
        "source_run_id": protocol.source_run_id,
        "source_prefix": protocol.source_prefix,
        "family_count": len(generation.families),
        "document_count": generation.count,
        "expected_intents": len(generation.families) * 6,
        "expected_utterances": len(generation.families) * 12,
        "family_splits": {key: value for key, value in splits.items()},
        "expected_primary_query_requests": splits["test"] * 12 * 2,
        "expected_shared_test_embeddings": splits["test"] * 12,
        "generation_request_ceiling": generation.request_limit,
        "evaluation_limits": protocol.config.limits.model_dump(mode="json"),
        "arms": {
            arm: {
                "index": protocol.resource_name(arm, "index"),
                "skillset": protocol.resource_name(arm, "skills"),
                "indexer": protocol.resource_name(arm, "indexer"),
            }
            for arm in ARMS
        },
        "retrieval": "hybrid_without_query_time_semantic_reranking",
        "evidence_metrics": "not_evaluated_without_independent_chunk_support_review",
        "human_review_required": True,
        "live_calls_authorized": False,
        "enrichment_policy": protocol.enrichment_policy,
    }


def execute(args: argparse.Namespace) -> dict[str, JsonValue]:
    action = args.experiment_action
    result = base_result("experiment:" + action, "complete")
    if action == "section-trial":
        from pathlib import Path

        from pydantic import TypeAdapter

        from docgen.evaluation.section_trial import SectionTrialSettings, run_section_trial

        trial = run_section_trial(
            args.source, args.output, SectionTrialSettings(
                base_url=args.base_url, deployment=args.deployment,
                subscription=args.subscription, sample_size=args.sample_size, seed=args.seed,
                max_input_tokens=args.max_input_tokens,
                max_completion_tokens=args.max_completion_tokens,
                max_observed_total_tokens=args.max_total_tokens,
                max_chunk_characters=args.max_chunk_characters,
                timeout_seconds=args.timeout_seconds,
            ), live=args.live,
        )
        details = TypeAdapter(dict[str, JsonValue]).validate_python(trial, strict=True)
        result["details"] = details
        result["status"] = details["status"]
        result["requested_count"] = details["source_count"]
        result["accepted_count"] = details["accepted_model_plans"]
        result["reports"] = {
            "section_trial": str(Path(str(trial["trial_path"])) / "summary.json"),
        }
        if details["status"] == "incomplete":
            result["failures"] = [{
                "code": "section_trial_incomplete", "phase": "experiment:section-trial",
                "retryable": False,
                "message": (
                    "Not every local model plan was accepted; see the recorded trial outcomes."
                ),
            }]
        return result
    if action == "inventory":
        from docgen.evaluation.inventory import export_inventory

        inventory = export_inventory(args.experiment or args.root, args.output)
        result["details"] = inventory
        result["status"] = "ready"
        result["reports"] = {
            "search_inventory": inventory["inventory_path"],
        }
        return result
    if action in {"plan", "init"}:
        config = load_experiment_config(args.config)
        protocol = new_protocol(config)
        details = overview(protocol)
        result["status"] = "planned"
        result["requested_count"] = config.generation.count
        if action == "init":
            with Workspace.create(args.output, protocol) as workspace:
                details["experiment_path"] = str(workspace.path)
                workspace.export("experiment-plan.json", details)
            result["status"] = "ready"
        result["details"] = details
        return result
    with Workspace(args.experiment) as workspace:
        if action != "status":
            workspace.require_valid()
        result["run_id"] = workspace.protocol.source_run_id
        result["requested_count"] = workspace.protocol.config.generation.count
        details = {
            "experiment_id": workspace.protocol.id,
            "experiment_path": str(workspace.path),
        }
        cohort = (
            load_record(args.cohort, QueryCohort)
            if action in {"collect", "score"} and args.cohort else None
        )
        if workspace.protocol.pipeline_only:
            details["enrichment_policy"] = workspace.protocol.enrichment_policy
        if action == "fork":
            from docgen.evaluation.variants import fork_experiment

            target = fork_experiment(workspace, load_experiment_config(args.config), args.output)
            details["variant_path"] = str(target)
            result["status"] = "ready"
        elif action == "generate":
            require_live(args.live)
            with AzureCliCredential(
                process_timeout=min(
                    60,
                    workspace.protocol.config.generation.limits.request_timeout_seconds,
                ),
            ) as credential:
                generated = generate_sources(workspace, credential=credential, live=True)
            result.update(generated.model_dump(mode="json"))
            result["operation"] = "experiment:generate"
            details.update(generated.details)
            details["source_run_path"] = str(source_run(workspace))
        elif action == "reference-build":
            draft = build_reference(workspace)
            details["reference_path"] = str(safe_child(workspace.path, "reference-draft.json"))
            details["intent_count"] = len(draft.intents)
            details["evidence_count"] = len(draft.evidence)
            result["status"] = "ready"
        elif action == "review":
            review_intent(
                workspace,
                intent_id=args.intent,
                reviewer=args.reviewer,
                certify_scope=args.certify_scope,
            )
            result["status"] = "valid"
        elif action == "reference-validate":
            draft = load_record(safe_child(workspace.path, "reference-draft.json"), Reference)
            validate_reference(workspace, draft, release=args.for_release)
            result["status"] = "valid"
            details["release_checks_included"] = args.for_release
        elif action == "release":
            released = release_reference(
                workspace, provisional=args.provisional, provisional_pilot=args.provisional_pilot,
                provisional_study=args.provisional_study,
            )
            details["reference_hash"] = digest(released)
            details["reference_status"] = released.status
            details["human_review_certified"] = released.status == "released"
            if released.status == "provisional":
                details["provisional_policy"] = provisional_policy(workspace, released)
            result["reports"] = {
                "reference": str(safe_child(workspace.path, "reference.json")),
                "qrels": str(safe_child(workspace.path, "qrels.trec")),
            }
        elif action == "score":
            from docgen.evaluation.reports import score

            report = score(workspace, split=args.split, profile=args.profile, cohort=cohort)
            details["paired"] = report["paired"]
            details["denominators"] = report["denominators"]
            details["evidence_metrics"] = report["evidence_metrics"]
            details["report_status"] = report["status"]
            if "reference_assurance_mode" in report:
                details["reference_assurance_mode"] = report["reference_assurance_mode"]
            result["reports"] = {
                "evaluation": str(safe_child(
                    workspace.path,
                    f"report-{report_suffix(args.split, args.profile, cohort=cohort)}.json",
                )),
            }
        elif action == "status":
            details["source_run_exists"] = source_run(workspace).is_dir()
            details["reference_built"] = workspace.get("reference-baseline") is not None
            details["reference_released"] = workspace.get("reference-complete") is not None
            saved_reference = workspace.get("reference")
            details["reference_status"] = (
                Reference.model_validate(saved_reference).status
                if saved_reference is not None
                else None
            )
            saved_policy = workspace.get("provisional-reference")
            if isinstance(saved_policy, dict):
                details["provisional_policy"] = saved_policy.get("mode")
            details["snapshots"] = {
                arm: workspace.get("snapshot:" + arm) is not None for arm in ARMS
            }
            details["invalidated"] = workspace.get("invalidated")
            details["completed_splits"] = [
                split
                for split in ("calibration", "development", "test")
                if workspace.get("collection-complete:" + split) is not None
            ]
            if (
                workspace.protocol.pipeline_only
                or workspace.protocol.config.search.variant is not None
            ):
                details["sources_prepared"] = workspace.get("blobs-verified") is not None
                if workspace.protocol.source_context_enabled:
                    details["context_ready"] = {
                        arm: workspace.get("context-complete:" + arm) is not None for arm in ARMS
                    }
                details["completed_profiles"] = {
                    split: [
                        profile for profile in PROFILES
                        if workspace.get(
                            "collection-complete:" + split
                            + (":" + profile if profile != "hybrid" else "")
                        ) is not None
                    ]
                    for split in ("calibration", "development", "test")
                }
            cohort_rows = workspace.database.execute(
                "SELECT name FROM records WHERE name LIKE 'query-cohort:%' ORDER BY name"
            ).fetchall()
            if cohort_rows:
                completed: dict[str, JsonValue] = {}
                for (name,) in cohort_rows:
                    saved_cohort = workspace.get(name)
                    if not isinstance(saved_cohort, dict):
                        raise InputError("Saved query cohort is invalid.")
                    selected = QueryCohort.model_validate(saved_cohort.get("cohort"))
                    completed[selected.name] = {
                        "split": selected.split,
                        "profiles": [
                            profile for profile in PROFILES
                            if workspace.get(
                                "collection-complete:"
                                + scope(selected.split, profile, cohort=selected)
                            ) is not None
                        ],
                    }
                details["completed_cohorts"] = completed
            result["usage"] = workspace.usage()
            result["status"] = "ready"
            if details["invalidated"] is not None:
                result["status"] = "integrity_error"
                result["failures"] = [
                    {
                        "code": "experiment_invalidated",
                        "phase": "experiment:status",
                        "retryable": False,
                        "message": "Snapshot drift requires a new experiment.",
                    }
                ]
        else:
            require_live(args.live)
            if action in {"prepare", "ingest", "collect"}:
                workspace.protocol.require_pipeline_only()
            with Azure(workspace.protocol) as azure:
                if action == "prepare":
                    from docgen.evaluation.ingestion import prepare

                    prepare(workspace, azure, live=True)
                elif action == "ingest":
                    from docgen.evaluation.ingestion import ingest

                    statuses = ingest(workspace, azure, live=True, wait_seconds=args.wait_seconds)
                    details["indexers"] = statuses
                    if not all(
                        isinstance(value, dict) and value.get("status") == "success"
                        for value in statuses.values()
                    ):
                        result["status"] = "incomplete"
                        result["failures"] = [
                            {
                                "code": "ingestion_pending",
                                "phase": "experiment:ingest",
                                "retryable": True,
                                "message": "Indexing is still running; repeat ingest.",
                            }
                        ]
                elif action == "snapshot":
                    from docgen.evaluation.snapshots import take_snapshot

                    audit = load_record(args.audit, IngestionAudit) if args.audit else None
                    observed = take_snapshot(workspace, azure, args.arm, live=True, audit=audit)
                    details["chunk_count"] = len(observed.chunks)
                    details["missing_count"] = len(observed.missing)
                elif action == "collect":
                    from docgen.evaluation.runner import collect

                    outcomes = collect(
                        workspace, azure, live=True, split=args.split, profile=args.profile,
                        cohort=cohort,
                    )
                    details["response_count"] = len(outcomes)
                else:
                    raise InputError("Unsupported experiment phase.")
            result["usage"] = workspace.usage()
        result["details"] = details
    return result
