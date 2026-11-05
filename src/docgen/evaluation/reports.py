import math
import random
from collections import defaultdict
from importlib.metadata import version
from statistics import mean

from pydantic import JsonValue

from docgen.errors import InputError, IntegrityError
from docgen.evaluation.corpus import source_run
from docgen.evaluation.metrics import parent_metrics
from docgen.evaluation.models import ARMS, Arm, QueryCohort, Split
from docgen.evaluation.profiles import Profile, report_suffix, scope
from docgen.evaluation.reference import provisional_policy, released_reference
from docgen.evaluation.runner import collected_rankings, selected_intents
from docgen.evaluation.snapshots import snapshot
from docgen.evaluation.state import Workspace, digest
from docgen.sampling import derived_seed
from docgen.store import RunStore


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    location = (len(ordered) - 1) * probability
    low = math.floor(location)
    high = math.ceil(location)
    return ordered[low] + (ordered[high] - ordered[low]) * (location - low)


def paired_estimates(
    families: dict[str, dict[Arm, dict[str, float]]],
    *,
    seed: int,
    resamples: int,
) -> dict[str, JsonValue]:
    if not families or resamples < 100:
        raise InputError("Paired estimates require answerable families and at least 100 resamples.")
    names = sorted(families)
    metrics = sorted(families[names[0]]["de_split"])
    differences = {
        metric: [
            families[family]["content_understanding"][metric] - families[family]["de_split"][metric]
            for family in names
        ]
        for metric in metrics
    }
    output: dict[str, JsonValue] = {}
    for metric in metrics:
        left = mean(families[family]["de_split"][metric] for family in names)
        right = mean(families[family]["content_understanding"][metric] for family in names)
        interval: list[JsonValue] | None = None
        if len(names) >= 2:
            randomizer = random.Random(derived_seed(seed, "family-bootstrap:" + metric))
            values = [
                mean(randomizer.choices(differences[metric], k=len(names)))
                for _ in range(resamples)
            ]
            interval = [percentile(values, 0.025), percentile(values, 0.975)]
        output[metric] = {
            "de_split": left,
            "content_understanding": right,
            "cu_minus_de": right - left,
            "ci95": interval,
            "family_count": len(names),
        }
    return output


def score(
    workspace: Workspace, *, split: Split = "test", profile: Profile = "hybrid",
    cohort: QueryCohort | None = None,
) -> dict[str, JsonValue]:
    reference = released_reference(workspace)
    policy = provisional_policy(workspace, reference) if reference.status == "provisional" else None
    assurance = (
        "exploratory-study" if policy == "automated_study"
        else "exploratory-pilot" if policy == "automated_pilot"
        else "smoke-only"
    )
    rankings = collected_rankings(
        workspace, split, reference=reference, profile=profile, cohort=cohort,
    )
    collection_scope = scope(split, profile, cohort=cohort)
    cutoffs = (
        (1, 3, 5, 10, 20)
        if workspace.protocol.pipeline_only or workspace.protocol.config.search.variant is not None
        else (5, 10, 20)
    )
    snapshots = {arm: snapshot(workspace, arm, reference=reference) for arm in ARMS}
    intents = {
        intent.id: intent for intent in selected_intents(reference, split, cohort=cohort)
    }
    by_query = {query.id: intent for intent in intents.values() for query in intent.queries}
    chunks = {arm: {chunk.id: chunk for chunk in snapshots[arm].chunks} for arm in ARMS}
    per_query: list[JsonValue] = []
    grouped: dict[tuple[str, Arm], list[dict[str, float]]] = defaultdict(list)
    per_intent: dict[tuple[str, Arm], dict[str, float]] = {}
    run_rows: dict[Arm, list[str]] = {arm: [] for arm in ARMS}
    for ranking in rankings:
        intent = by_query[ranking.query_id]
        if any(identifier not in chunks[ranking.arm] for identifier in ranking.chunk_ids):
            raise IntegrityError("A returned chunk has no frozen source mapping.")
        parents = list(
            dict.fromkeys(
                chunks[ranking.arm][identifier].doc_id for identifier in ranking.chunk_ids
            )
        )
        grades = {judgment.doc_id: judgment.grade for judgment in intent.judgments}
        qrels = {document.id: grades.get(document.id, 0) for document in reference.documents}
        metrics = parent_metrics(parents, qrels, cutoffs=cutoffs) if intent.answerable else None
        per_query.append(
            {
                "arm": ranking.arm,
                "query_id": ranking.query_id,
                "intent_id": intent.id,
                "family_id": intent.family_id,
                "answerable": intent.answerable,
                "parent_ids": [parent for parent in parents],
                "returned_chunks": len(ranking.chunk_ids),
                "returned_parents": len(parents),
                "metrics": {key: value for key, value in metrics.items()}
                if metrics is not None
                else None,
                "metric_status": "scored" if metrics is not None else "not_applicable_unanswerable",
                "successful_attempt_latency_ms": ranking.elapsed_ms,
            }
        )
        if metrics is not None:
            grouped[(intent.id, ranking.arm)].append(metrics)
        run_rows[ranking.arm].extend(
            f"{ranking.query_id} Q0 {parent} {index} {-index} {ranking.arm}"
            for index, parent in enumerate(parents, 1)
        )
    family_intents: dict[tuple[str, Arm], list[dict[str, float]]] = defaultdict(list)
    for (intent_id, arm), observations in grouped.items():
        metrics = {key: mean(row[key] for row in observations) for key in observations[0]}
        per_intent[(intent_id, arm)] = metrics
        family_intents[(intents[intent_id].family_id, arm)].append(metrics)
    families: dict[str, dict[Arm, dict[str, float]]] = {}
    for (family_id, arm), observations in family_intents.items():
        families.setdefault(family_id, {})[arm] = {
            key: mean(row[key] for row in observations) for key in observations[0]
        }
    if not families or any(set(values) != set(ARMS) for values in families.values()):
        raise InputError("No complete paired answerable-family observations are available.")
    estimates = paired_estimates(
        families,
        seed=workspace.protocol.config.seed,
        resamples=workspace.protocol.config.bootstrap_resamples,
    )
    slices: dict[str, JsonValue] = {}
    for attribute in ("task_type", "format", "genre", "complexity", "length_band"):
        groups: dict[str, set[str]] = defaultdict(set)
        for intent in intents.values():
            if not intent.answerable:
                continue
            if attribute == "task_type":
                labels = {intent.task_type}
            else:
                relevant = {judgment.doc_id for judgment in intent.judgments if judgment.grade >= 2}
                labels = {
                    str(getattr(document, attribute))
                    for document in reference.documents
                    if document.id in relevant
                }
            for label in labels:
                groups[label].add(intent.id)
        rows: dict[str, JsonValue] = {}
        for label, intent_ids in sorted(groups.items()):
            arm_means: dict[str, JsonValue] = {}
            for arm in ARMS:
                observations = [per_intent[(intent_id, arm)] for intent_id in sorted(intent_ids)]
                arm_means[arm] = {
                    key: mean(row[key] for row in observations) for key in observations[0]
                }
            rows[label] = {
                "intent_count": len(intent_ids),
                "family_count": len({intents[identifier].family_id for identifier in intent_ids}),
                "query_count": sum(len(intents[identifier].queries) for identifier in intent_ids),
                "intent_macro_metrics": arm_means,
            }
        slices[attribute] = rows
    ingestion: dict[str, JsonValue] = {}
    latency: dict[str, JsonValue] = {}
    for arm in ARMS:
        observed = snapshots[arm]
        times = [ranking.elapsed_ms for ranking in rankings if ranking.arm == arm]
        ingestion[arm] = {
            "source_count": len(reference.documents),
            "observed_source_count": len({chunk.doc_id for chunk in observed.chunks}),
            "missing_sources": [item.model_dump(mode="json") for item in observed.missing],
            "chunk_count": len(observed.chunks),
            "indexer_errors": observed.indexer_errors,
            "indexer_warnings": observed.indexer_warnings,
        }
        latency[arm] = {
            "mean_ms": mean(times),
            "p50_ms": percentile(times, 0.5),
            "p95_ms": percentile(times, 0.95),
        }
    with RunStore.open(source_run(workspace)) as store:
        generation_attempts = store.attempts()
    generation_tokens = sum(
        attempt.usage.total_tokens or 0 for attempt in generation_attempts if attempt.usage
    )
    report: dict[str, JsonValue] = {
        "schema_version": "1",
        "protocol_id": workspace.protocol.id,
        "status": "provisional" if reference.status == "provisional" else "complete",
        "split": split,
        "method": profile,
        "primary_metric": "ndcg_at_10",
        "reference_hash": digest(reference),
        "snapshot_hashes": {arm: digest(snapshots[arm]) for arm in ARMS},
        "metric_implementation": {
            "ir_measures": version("ir-measures"),
            "provider": "pytrec_eval",
            "pytrec_eval_terrier": version("pytrec-eval-terrier"),
            "gains": [0, 1, 3, 7],
            "binary_threshold": 2,
            "cutoffs": list(cutoffs),
            "parent_policy": "first_occurrence_deduplication_before_cutoff",
            "precision_denominator": "cutoff",
            "missing_source_denominator": "retained_in_gold",
        },
        "aggregation": {
            "point_estimates": "query_macro_within_intent_then_intent_macro_within_family",
            "interval": "paired_family_percentile_bootstrap",
            "bootstrap_resamples": workspace.protocol.config.bootstrap_resamples,
            "ci_unavailable_reason": "fewer_than_two_families" if len(families) < 2 else None,
        },
        "denominators": {
            "families": len(families),
            "intents": len(intents),
            "utterances": len(by_query),
            "answerable_intents": sum(intent.answerable for intent in intents.values()),
            "unanswerable_intents": sum(not intent.answerable for intent in intents.values()),
            "arm_query_responses": len(rankings),
            "source_documents": len(reference.documents),
        },
        "paired": estimates,
        "per_query": per_query,
        "slices": slices,
        "slice_policy": "overlapping_source_labels_descriptive_only",
        "ingestion": ingestion,
        "latency": {
            "scope": "successful_transport_attempt_including_authentication",
            "arms": latency,
        },
        "evidence_metrics": {
            "status": "not_evaluated",
            "reason": "Chunk entailment/support mappings require a separate relation-aware review.",
        },
        "usage": {
            "evaluation": workspace.get("collection-usage:" + collection_scope),
            "scope": "cumulative_protocol_usage_through_first_successful_collection_seal",
            "generation_attempts": len(generation_attempts),
            "observed_generation_tokens": generation_tokens,
            "generation_usage_unknown": sum(
                attempt.usage is None or attempt.usage.total_tokens is None
                for attempt in generation_attempts
            ),
            "azure_indexing_cost": "not_reported_by_search_api",
        },
        "warnings": [
            "Synthetic-source findings do not establish performance on organizational documents.",
            *(
                [
                    f"PROVISIONAL: Reference labels use automated {assurance} validation; "
                    "human review was not certified. Do not treat this as a validated benchmark."
                ]
                if reference.status == "provisional"
                else []
            ),
            *(
                ["Small family count; bootstrap intervals are exploratory."]
                if len(families) < 20
                else []
            ),
        ],
    }
    if reference.status == "provisional":
        report["reference_status"] = "provisional"
        report["human_review_certified"] = False
        report["eligible_for_confirmatory_conclusions"] = False
        if policy in {"automated_pilot", "automated_study"}:
            report["reference_assurance_mode"] = policy
    if workspace.protocol.pipeline_only:
        report["enrichment_policy"] = workspace.protocol.enrichment_policy
        report["document_feature_source"] = "raw_documents_through_search_skillsets"
        report["external_document_metadata"] = False
        report["external_document_vector_writes"] = False
    if workspace.protocol.entity_extraction is not None:
        report["pipeline_entity_extraction"] = (
            workspace.protocol.entity_extraction.model_dump(mode="json")
        )
        report["pipeline_entity_coverage"] = {
            arm: {
                "chunks_with_entities": sum(bool(chunk.entities) for chunk in saved.chunks),
                "entity_mentions": sum(len(chunk.entities or ()) for chunk in saved.chunks),
                "distinct_entities": len({
                    entity for chunk in saved.chunks for entity in chunk.entities or ()
                }),
                "source_documents_with_entities": len({
                    chunk.doc_id for chunk in saved.chunks if chunk.entities
                }),
            }
            for arm, saved in snapshots.items()
        }
    if workspace.protocol.config.search.variant is not None:
        report["variant"] = workspace.protocol.config.search.variant.model_dump(mode="json")
        report["source_lineage"] = workspace.get("source-lineage")
        report["analysis_role"] = "development_tuning" if split == "development" else "exploratory"
    if cohort is not None:
        report["query_cohort"] = cohort.model_dump(mode="json")
    workspace.put("report:" + collection_scope, report)
    suffix = report_suffix(split, profile, cohort=cohort)
    workspace.export(f"report-{suffix}.json", report)
    for arm in ARMS:
        workspace.export_bytes(
            f"run-{arm}-{suffix}.trec", ("\n".join(run_rows[arm]) + "\n").encode()
        )
    return report
