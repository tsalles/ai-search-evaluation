import math
import random
import unicodedata
from collections.abc import Callable, Collection
from functools import partial
from importlib.metadata import version

from pydantic import JsonValue

from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.azure import Azure, object_value, vector_value
from docgen.evaluation.models import (
    ARMS,
    Intent,
    Query,
    QueryCohort,
    Ranking,
    Reference,
    Snapshot,
    Split,
)
from docgen.evaluation.profiles import (
    ENTITY_PROFILES,
    LEXICAL_PROFILES,
    SEMANTIC_PROFILES,
    Profile,
    profile_vector_k,
    report_suffix,
    retrieval_request,
    scope,
)
from docgen.evaluation.reference import released_reference
from docgen.evaluation.snapshots import assert_stable, snapshot
from docgen.evaluation.state import RemoteValue, Workspace, digest, require_live
from docgen.sampling import derived_seed
from docgen.tokenization import token_count as token_count


def selected_intents(
    reference: Reference, split: Split, *, cohort: QueryCohort | None = None,
) -> tuple[Intent, ...]:
    if cohort is None:
        return tuple(intent for intent in reference.intents if intent.split == split)
    if cohort.split != split:
        raise InputError("The query cohort belongs to a different split.")
    selected = {intent.id: intent for intent in reference.intents}
    if any(
        identifier not in selected or selected[identifier].split != split
        for identifier in cohort.intent_ids
    ):
        raise InputError("Query cohort intents are missing or belong to a different split.")
    return tuple(selected[identifier] for identifier in cohort.intent_ids)


def queries(
    reference: Reference, split: Split, *, cohort: QueryCohort | None = None,
) -> tuple[Query, ...]:
    result = tuple(
        query for intent in selected_intents(reference, split, cohort=cohort)
        for query in intent.queries
    )
    if not result:
        raise InputError("The selected split has no reviewed queries.")
    return result


def query_vector(
    workspace: Workspace,
    azure: Azure,
    query: Query,
    *,
    count_tokens: Callable[[str], int],
) -> list[float]:
    text = unicodedata.normalize("NFC", query.text)
    count = count_tokens(text)
    if type(count) is not int or count < 1:
        raise InputError("The tokenizer returned an invalid query length.")
    if count > workspace.protocol.config.limits.max_query_tokens:
        raise InputError("Query exceeds the frozen token limit; truncation is forbidden.")
    settings = workspace.protocol.config.search
    identity: dict[str, JsonValue] = {
        "text": text,
        "endpoint": settings.embedding.base_url,
        "deployment": settings.embedding.deployment,
        "model": settings.model_name,
        "dimensions": settings.dimensions,
        "tokenizer": "cl100k_base",
        "tiktoken_version": version("tiktoken"),
    }
    fingerprint = digest(identity)
    response = workspace.invoke(
        "embedding",
        "vector:" + fingerprint,
        partial(azure.embed, text),
        fingerprint=fingerprint,
    )
    value = object_value(response.data)
    if response.tokens is None or value.get("reported_model") != settings.model_name:
        raise ProviderError(
            "embedding_space", "Embedding usage or model does not match the protocol."
        )
    workspace.put("embedding-reported-model", value["reported_model"])
    return vector_value(value.get("vector"), settings.dimensions)


def hybrid_request(query: Query, vector: list[float]) -> dict[str, JsonValue]:
    return retrieval_request(query, vector, profile="hybrid")


def parse_hits(
    payload: JsonValue,
    known_chunks: Collection[str],
    *,
    semantic: bool = False,
) -> tuple[tuple[str, ...], tuple[float, ...]]:
    value = object_value(payload)
    if semantic and (
        value.get("@search.semanticPartialResponseReason") is not None
        or value.get("@search.semanticPartialResponseType") is not None
    ):
        raise ProviderError(
            "semantic_partial", "Semantic fallback/partial results are not scoreable."
        )
    rows = value.get("value")
    if not isinstance(rows, list) or len(rows) > 50 or value.get("@search.coverage") != 100:
        raise ProviderError("incomplete_query", "Search response is partial or invalid.")
    chunk_ids: list[str] = []
    scores: list[float] = []
    previous_reranker = math.inf
    for raw_hit in rows:
        hit = object_value(raw_hit)
        identifier, score = hit.get("id"), hit.get("@search.score")
        if (
            not isinstance(identifier, str)
            or identifier not in known_chunks
            or identifier in chunk_ids
            or isinstance(score, bool)
            or not isinstance(score, (int, float))
        ):
            raise IntegrityError("Query returned an unknown/duplicate chunk or invalid score.")
        try:
            observed_score = float(score)
        except OverflowError:
            raise IntegrityError("Query returned an out-of-range score.") from None
        if not math.isfinite(observed_score):
            raise IntegrityError("Query returned a nonfinite score.")
        if semantic:
            reranker = hit.get("@search.rerankerScore")
            if (
                isinstance(reranker, bool)
                or not isinstance(reranker, (int, float))
                or not math.isfinite(reranker)
                or not 0 <= reranker <= 4
                or reranker > previous_reranker
            ):
                raise ProviderError(
                    "invalid_semantic", "Semantic scores or semantic result ordering are invalid."
                )
            previous_reranker = float(reranker)
        chunk_ids.append(identifier)
        scores.append(observed_score)
    return tuple(chunk_ids), tuple(scores)


def checked_query(
    azure: Azure,
    path: str,
    body: dict[str, JsonValue],
    known_chunks: Collection[str],
    *,
    semantic: bool = False,
) -> RemoteValue:
    response = azure.search("POST", path, body=body)
    parse_hits(response.data, known_chunks, semantic=semantic)
    return response


def ranking_key(arm: str, query_id: str, profile: Profile) -> str:
    scope("development", profile)
    prefix = "ranking" if profile == "hybrid" else "ranking:" + profile
    return f"{prefix}:{arm}:{query_id}"


def _reranker_scores(payload: JsonValue) -> tuple[float, ...]:
    rows = object_value(payload).get("value")
    if not isinstance(rows, list):
        raise ProviderError("invalid_semantic", "Semantic response rows are invalid.")
    scores = []
    for row in rows:
        value = object_value(row).get("@search.rerankerScore")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ProviderError("invalid_semantic", "Semantic response score is invalid.")
        scores.append(float(value))
    return tuple(scores)


def _account_names(workspace: Workspace, profile: Profile) -> tuple[str, ...]:
    if profile == "pipeline-entity-hybrid" and workspace.protocol.entity_extraction is None:
        raise InputError("This profile requires an explicit in-pipeline entity extractor.")
    if workspace.protocol.pipeline_only:
        if profile in ENTITY_PROFILES:
            raise InputError(
                "Entity-aware profiles require an implemented in-pipeline entity extractor; "
                "generator-assisted name catalogs are forbidden."
            )
        return ()
    if profile != "hybrid" and workspace.protocol.config.search.variant is None:
        raise InputError("Create an explicit versioned variant before collecting tuning profiles.")
    if workspace.protocol.config.search.variant is None:
        return ()
    names: set[str] = set()
    for arm in ARMS:
        saved = workspace.get("snapshot:" + arm)
        if saved is None:
            raise InputError("Freeze both context-bearing variant snapshots before tuning.")
        observed = Snapshot.model_validate(saved)
        for chunk in observed.chunks:
            if chunk.source_context is None:
                raise IntegrityError("A variant snapshot is missing sealed source context.")
            names.update(chunk.source_context.account_names)
    return tuple(sorted(names))


def collection_plan(
    workspace: Workspace,
    split: Split,
    *,
    reference: Reference | None = None,
    profile: Profile = "hybrid",
    cohort: QueryCohort | None = None,
) -> dict[str, JsonValue]:
    scope(split, profile, cohort=cohort)
    if reference is None:
        reference = released_reference(workspace)
    selected = list(queries(reference, split, cohort=cohort))
    variant = workspace.protocol.config.search.variant
    tuning = variant.query_tuning if variant else None
    randomizer = random.Random(derived_seed(workspace.protocol.config.seed, "queries:" + split))
    randomizer.shuffle(selected)
    order: list[JsonValue] = []
    first = randomizer.randrange(2)
    for index, query in enumerate(selected):
        arms = ARMS if (first + index) % 2 == 0 else tuple(reversed(ARMS))
        order.extend({"arm": arm, "query_id": query.id} for arm in arms)
    result: dict[str, JsonValue] = {
        "protocol_id": workspace.protocol.id,
        "reference_hash": digest(reference),
        "split": split,
        "method": profile,
        "raw_top": 50,
        "vector_k": (
            None if profile == "semantic-bm25" else profile_vector_k(profile, tuning=tuning)
        ),
        "semantic_reranking": profile in SEMANTIC_PROFILES,
        "minimum_coverage": 100,
        "snapshot_hashes": {
            arm: digest(snapshot(workspace, arm, reference=reference)) for arm in ARMS
        },
        "embedding": workspace.protocol.config.search.embedding.model_dump(mode="json"),
        "model": workspace.protocol.config.search.model_name,
        "dimensions": workspace.protocol.config.search.dimensions,
        "tokenizer": "cl100k_base",
        "tiktoken_version": version("tiktoken"),
        "query_hash": digest([query.model_dump(mode="json") for query in selected]),
        "order": order,
    }
    if workspace.protocol.config.search.variant is not None or profile != "hybrid":
        names = _account_names(workspace, profile)
        result["profile_version"] = "1"
        result["request_template_hash"] = digest([
            retrieval_request(query, [0.0], profile=profile, account_names=names, tuning=tuning)
            for query in selected
        ])
    if tuning is not None:
        result["query_tuning"] = tuning.model_dump(mode="json")
    if workspace.protocol.pipeline_only:
        result["enrichment_policy"] = workspace.protocol.enrichment_policy
    if cohort is not None:
        result["query_cohort"] = cohort.model_dump(mode="json")
    return result


def collect(
    workspace: Workspace,
    azure: Azure,
    *,
    live: bool,
    split: Split = "test",
    count_tokens: Callable[[str], int] = token_count,
    profile: Profile = "hybrid",
    cohort: QueryCohort | None = None,
) -> tuple[Ranking, ...]:
    require_live(live)
    workspace.require_valid()
    workspace.protocol.require_pipeline_only()
    if workspace.get("index-parameter-epochs") is not None:
        raise InputError("Versioned index-parameter studies require their explicit epoch executor.")
    account_names = _account_names(workspace, profile)
    reference = released_reference(workspace)
    selected = {query.id: query for query in queries(reference, split, cohort=cohort)}
    if cohort is not None:
        workspace.put("query-cohort:" + cohort.name, {
            "reference_hash": digest(reference),
            "cohort": cohort.model_dump(mode="json"),
        })
    frozen = {arm: snapshot(workspace, arm, reference=reference) for arm in ARMS}
    snapshot_hashes = {arm: digest(frozen[arm]) for arm in ARMS}
    collection_scope = scope(split, profile, cohort=cohort)
    plan = collection_plan(workspace, split, reference=reference, profile=profile, cohort=cohort)
    workspace.put("collection-plan:" + collection_scope, plan)
    for arm in ARMS:
        assert_stable(workspace, azure, arm, reference=reference)
    by_chunk = {arm: {chunk.id: chunk for chunk in frozen[arm].chunks} for arm in ARMS}
    semantic = profile in SEMANTIC_PROFILES
    variant = workspace.protocol.config.search.variant
    tuning = variant.query_tuning if variant else None
    rankings: list[Ranking] = []
    order = plan["order"]
    if not isinstance(order, list):
        raise IntegrityError("Collection order is invalid.")
    for raw in order:
        pair = object_value(raw)
        arm_value, query_id = pair["arm"], pair["query_id"]
        if arm_value not in ARMS or not isinstance(query_id, str) or query_id not in selected:
            raise IntegrityError("Collection arm/query membership differs from the frozen plan.")
        arm = "de_split" if arm_value == "de_split" else "content_understanding"
        key = ranking_key(arm, query_id, profile)
        saved = workspace.get(key)
        if saved is not None:
            ranking = Ranking.model_validate(saved)
        else:
            query = selected[query_id]
            vector = (
                query_vector(workspace, azure, query, count_tokens=count_tokens)
                if profile not in LEXICAL_PROFILES else None
            )
            body = retrieval_request(
                query, vector, profile=profile, account_names=account_names, tuning=tuning,
            )
            identity: dict[str, JsonValue] = {
                "body": body,
                "arm": arm,
                "snapshot": snapshot_hashes[arm],
            }
            try:
                response = workspace.invoke(
                    "search",
                    key,
                    partial(
                        checked_query,
                        azure,
                        f"indexes/{workspace.protocol.resource_name(arm, 'index')}/docs/search",
                        body,
                        by_chunk[arm],
                        semantic=semantic,
                    ),
                    fingerprint=digest(identity),
                    semantic=semantic,
                )
            except IntegrityError:
                workspace.put("invalidated", {"reason": "snapshot_drift"})
                raise
            chunk_ids, scores = parse_hits(response.data, by_chunk[arm], semantic=semantic)
            if response.elapsed_ms is None:
                raise IntegrityError("A confirmed query has no durable timing record.")
            ranking = Ranking(
                arm=arm,
                query_id=query_id,
                status="succeeded",
                chunk_ids=chunk_ids,
                scores=scores,
                elapsed_ms=response.elapsed_ms,
                reranker_scores=_reranker_scores(response.data) if semantic else None,
            )
            workspace.record(key, ranking)
        if ranking.arm != arm or ranking.query_id != query_id or ranking.status != "succeeded":
            raise IntegrityError("A saved ranking differs from its required successful outcome.")
        if semantic and (
            ranking.reranker_scores is None
            or len(ranking.reranker_scores) != len(ranking.chunk_ids)
        ):
            raise IntegrityError(
                "A saved semantic ranking is missing its validated reranker scores."
            )
        rankings.append(ranking)
    reference = released_reference(workspace)
    for arm in ARMS:
        assert_stable(workspace, azure, arm, reference=reference)
    if workspace.get("collection-usage:" + collection_scope) is None:
        workspace.put("collection-usage:" + collection_scope, workspace.usage())
    workspace.put(
        "collection-complete:" + collection_scope,
        {
            "plan_hash": digest(plan),
            "rankings_hash": digest([ranking.model_dump(mode="json") for ranking in rankings]),
        },
    )
    workspace.export(
        f"rankings-{report_suffix(split, profile, cohort=cohort)}.json",
        [ranking.model_dump(mode="json") for ranking in rankings],
    )
    return tuple(rankings)


def collected_rankings(
    workspace: Workspace,
    split: Split,
    *,
    reference: Reference | None = None,
    profile: Profile = "hybrid",
    cohort: QueryCohort | None = None,
) -> tuple[Ranking, ...]:
    workspace.require_valid()
    collection_scope = scope(split, profile, cohort=cohort)
    plan = collection_plan(workspace, split, reference=reference, profile=profile, cohort=cohort)
    if cohort is not None and workspace.get("query-cohort:" + cohort.name) != {
        "reference_hash": plan["reference_hash"],
        "cohort": cohort.model_dump(mode="json"),
    }:
        raise IntegrityError("The saved query cohort differs from its immutable selection.")
    if workspace.get("collection-plan:" + collection_scope) != plan:
        raise IntegrityError(
            "The saved collection plan differs from this release or software version."
        )
    order = plan["order"]
    if not isinstance(order, list):
        raise IntegrityError("Collection order is invalid.")
    result: list[Ranking] = []
    for raw in order:
        pair = object_value(raw)
        arm, query_id = pair["arm"], pair["query_id"]
        if not isinstance(arm, str) or not isinstance(query_id, str):
            raise IntegrityError("Saved collection membership is invalid.")
        value = workspace.get(ranking_key(arm, query_id, profile))
        if value is None:
            raise InputError(
                "Primary scoring requires every arm/query response, including empty results."
            )
        ranking = Ranking.model_validate(value)
        if (
            ranking.status != "succeeded"
            or len(ranking.chunk_ids) != len(ranking.scores)
            or ranking.arm != pair["arm"]
            or ranking.query_id != pair["query_id"]
            or profile in SEMANTIC_PROFILES and (
                ranking.reranker_scores is None
                or len(ranking.reranker_scores) != len(ranking.chunk_ids)
            )
        ):
            raise InputError("Primary scoring cannot discard failed or malformed query outcomes.")
        result.append(ranking)
    expected: dict[str, JsonValue] = {
        "plan_hash": digest(plan),
        "rankings_hash": digest([ranking.model_dump(mode="json") for ranking in result]),
    }
    if workspace.get("collection-complete:" + collection_scope) != expected:
        raise InputError(
            "Collection is unsealed; resume it to complete both post-collection drift checks."
        )
    workspace.export(
        f"rankings-{report_suffix(split, profile, cohort=cohort)}.json",
        [ranking.model_dump(mode="json") for ranking in result],
    )
    return tuple(result)
