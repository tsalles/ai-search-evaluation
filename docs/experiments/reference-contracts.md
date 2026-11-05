# Reference and experiment contracts

Status: Design contract with raw-document-only protocol v2; see the runbook for actual interfaces

Date: 2026-10-30

## Core separation

The [experiment design](design.md) defines a fresh-corpus, paired DE_SPLIT-versus-CU protocol. These contracts separate newly generated source truth, shared reviewed relevance, arm-specific observed chunks, and paired rankings. Answer strings are review aids; the scorer consumes frozen relevance/evidence records rather than asking a model to grade each search result during measurement. Controlled forks can reuse a completed experiment's immutable corpus and reference, with explicit lineage and no claim of an independent replication. Arbitrary generation-run imports remain outside the protocol.

The implementation uses versioned top-level records and strict typed subrecords in [evaluation models](../../src/docgen/evaluation/models.py), with protocol-scoped IDs, checksummed SQLite records, sealed reference/qrels exports and fingerprint-bound snapshots/results. Follow [the runbook](usage.md) and [actual configuration](../../examples/retrieval-experiment.yaml), rather than treating illustrative payloads below as executable schemas.

The fuller research contract below includes future fields and analyses. Current evidence anchors record block IDs, list ordinals or table row/column coordinates and source quotes, not leaf character spans. Human-reviewed certified-scope parent qrels and shared lexical, vector, weighted hybrid, pipeline-entity hybrid and content-only semantic-reranked profiles are implemented, with independent request fingerprints and report seals. Historical generator-assisted entity profiles remain available only for offline interpretation of their original records. Reviewed chunk support maps, pooled exploratory scoring, token-budget evidence packing, portable release manifests and matched-format views remain deferred. Do not mutate released qrels, snapshots or rankings.

## Pipeline-only document features

New protocols and forks use schema version `2` and freeze `enrichment_policy: search-pipeline-only`. Each arm receives only the raw native file bytes, native MIME types and technical source identities. The uploader adds no custom Blob metadata. Titles, entity names, embeddings and other ranking features must come from that arm's Search indexing pipeline.

The application cannot merge document annotations, replace document vectors or use the generator's fact ledger as a query-name catalog. Canonical source fields and judgments remain evaluator-only inputs for byte integrity, source mapping, reference validation and scoring. They cannot repair extraction losses, create document features or alter runtime retrieval requests.

Entity treatments run inside both skillsets, with common model/settings and inputs from each arm's own extraction. Do not share annotations between arms or provide corpus-specific dictionaries. Native version 3 uses Entity Recognition V3 and a Shaper to retain source-grounded Product/Organization occurrences in `entity_data/entities`; experimental GenAI versions 1/2 remain separately identified. Document embeddings stay native-text-only. Snapshot audits reject ungrounded or malformed entities without repairing the index. The distinct `pipeline-entity-hybrid` profile uses these server-produced fields with an unchanged query; historical generator-assisted profiles remain forbidden.

Protocol v1 remains readable for historical offline scoring and inspection. Its creation intent, query requests, snapshots and reports retain their original serialization and hashes. Live preparation, ingestion and collection require a new v2 fork. Historical assisted results do not satisfy the v2 restriction.

An explicit operational-smoke exception can seal automatically checked labels with reference `status: provisional` for an all-test experiment of at most two families and twelve documents. A separate exploratory-pilot policy permits eighteen to three hundred documents in three to fifty families with at least two frozen test families. An explicitly opted-in raw-only larger study permits 306 to 996 documents in 51 to 166 complete six-document families, also requiring at least two test families. Format quotas apply across the corpus rather than requiring one file of each format per family. These policies preserve source/evidence/checksum checks and record no fabricated reviewers or human authorship. Reports remain provisional and ineligible for confirmatory conclusions; pilot/study reports identify `reference_assurance_mode` as `automated_pilot` or `automated_study`. No policy can change an existing release mode or satisfy the normal human-review gate; see [provisional execution policies](usage.md#provisional-operational-smoke).

## Records and identity

An optional experiment-level `family_domain: saas` selects the Portuguese SaaS family preset; its absence preserves the banking contract and serialization. Each fresh protocol creates a seed-specific entity catalog, frozen subscription/support facts and domain-specific source-backed intents. Corpus independence requires disjoint source artifacts and explicit overlap checks. Ordinal document IDs are local to the protocol/run namespace and need not be globally unique. A within-corpus tuning fork retains the same sources and judgments and cannot claim independent replication.

Index tuning is an explicit frozen `search.variant.index_tuning` record covering the natural-language analyzer, BM25 parameters and HNSW graph/search parameters. It changes no source fields, skill inputs, document embeddings or technical-ID analysis. `query_tuning` freezes vector candidate count, weight, exhaustive search and term-match mode; the original question and raw return depth remain unchanged. Absent extensions retain historical serialization.

The `semantic-bm25` profile reranks the content-only lexical candidate set without creating or sending a query embedding. Semantic profiles reject partial/fallback results and retain their own fingerprints and collection seals. An optional per-workspace semantic attempt limit counts retries and interrupted/failed dispatches durably; cached successful responses consume no additional dispatch. A study spanning workspaces must enforce its aggregate cap separately. No configuration or limit implicitly authorizes a paid billing upgrade.

Optional analyzer comparison fields contain exact copies of the arm's native chunk text, projected within its skillset. Their schema uses supported locale-specific analyzer names; snapshot audits require byte-equivalent text before scoring. A separately registered parameter-epoch executor may change only the owned indexes' BM25 parameters with conditional ETag writes, immutable stage records and query fingerprints including the parameter state. It pins native indexer execution, preserves every historical namespace and validates complete native text/vectors and raw-source versions at the study boundaries. These studies cannot use ordinary snapshot-bound CLI collection.

Named query cohorts select complete intents from one released split and preserve the full source/qrels reference. Membership is immutable and all selected utterances require successful paired outcomes. Cohort plans, completion seals and exports are distinct from full-split artifacts; a completed cohort cannot imply full-split completion.

Evidence contexts retain a ranked whole-chunk prefix under a declared token budget, with no gold-dependent selection or skipping. Automated claim assessments must cite literal exposed text and cover every required claim once. The evaluator validates snapshot binding and exact context construction before checking citations. Model review is not certified human review and cannot supply index or query features.

Snapshot and drift scans use ID-ordered keyset pagination with at most 250 rows per response, including full vectors. Smaller transport pages bound response size without truncating the index, changing query candidate depth or weakening byte/vector drift checks. Scans continue to an explicit empty page and retain the frozen overall request budget.

| Record | Key | Required fields and invariants |
|--------|-----|--------------------------------|
| Corpus release | `corpus_release_id` | Source run/content hashes, exact expected document IDs, corpus seed, generation/catalog/prompt versions, locale, scenario-family plan and artifact manifests |
| Canonical document | `doc_id` | Corpus-qualified mapping to original `run_id`, `content_id`, canonical hash, `family_id`, visible entities, genre, actual word count, length band, logical complexity |
| Artifact view | `view_id` | Exactly one artifact per expected `doc_id`, assigned format/layout/renderer versions, relative path, byte hash, native validation outcome; no duplicate representations within the view |
| Scenario family | `family_id` | Stable entity/alias registry, linked document/scenario IDs, scoped fact ledger, claim-coverage plan, split; each related entity/document/query variant remains in one split |
| Claim | `claim_id` | Family/entity scope, predicate, typed value or qualitative assertion, units, applicability/negation, optional fact IDs; grounded in accepted source |
| Evidence occurrence | `occurrence_id` | `claim_id`, `doc_id`, canonical hash, one or more exact block/list/table/text anchors, minimal quote and conditions, verification method/reviewer |
| Information need | `intent_id` | Family/split, scope, task type, entity constraints, answerable flag, normalized reference answer, alternative sufficient claim sets |
| Query utterance | `query_id` | `intent_id`, exact natural-language text, locale, wording category, reviewed semantic equivalence, text hash; paraphrases share truth only after review |
| Parent judgment | `(intent_id, doc_id)` | Integer grade 0-3, cited occurrences for substantive grades, rationale, provenance, review/adjudication state; absence is `unjudged` |
| Judgment coverage | `(intent_id, corpus_release_id)` | `exhaustive`, `certified_scope`, or `pooled`; expected/judged document sets and any audited zero-certification rule |
| Pipeline arm | `arm_id` | `de_split` or `content_understanding`, frozen extraction/chunking policy, index/indexer/skillset names/API fingerprints and shared source manifest identity |
| Index snapshot | `snapshot_id` | `arm_id`, view/corpus/config fingerprints, endpoint/index/API, snapshot window, full observed chunk map, embedding spec, ingestion inventory and errors |
| Chunk | `(snapshot_id, search_chunk_id)` | Opaque Search parent ID, exact source URI, canonical `doc_id`, text/text hash, view, annotations available, vector presence/dimension status |
| Chunk support | `(snapshot_id, claim_id)` | Alternative sets of chunk IDs sufficient to express that claim, relation-aware verification, mapping state (`verified`, `ambiguous`, `missing`) |
| Experiment plan | `experiment_id` | Shared source/reference/query hashes, both arm snapshot hashes, common retrieval configuration, query split, request order seed, depths, budgets and paired statistical/metric policy |
| Retrieval outcome | `(experiment_id, arm_id, query_id, method_id, repetition)` | Snapshot identity, status, request/attempt identity, latency, returned order and chunk IDs/scores, request fingerprint, safe errors/usage |
| Score report | `report_id` | Scorer/library/provider versions, input hashes, metrics and aggregation policies, exclusions/errors, slice counts, paired estimates/intervals; provisional reports explicitly identify their uncertified reference assurance |

Use an explicit registry to map `(corpus release, original run, content ID)` to `doc_id`. The ordinal `item-000001` alone is not globally unique. A canonical document retains its `doc_id` across format views; its artifact hash and Search chunk IDs change. Do not derive identity by decoding Azure-generated parent keys, stripping arbitrary URL prefixes, or interpreting a filename as a relevance label.

Current canonical `Fact.id` and block/table IDs are only unique in their declared source scope. Reference claim/evidence IDs are release-qualified and must resolve through the document registry.

## Source truth and evidence

Scenario-family planning is opt-in for the generator but required by this experimental protocol. It allocates related documents and planned claims before authoring, then resolves evidence in the freshly accepted content. Neither arm's output determines source truth. Freeze one shared reference from that content before test retrieval; do not import historical runs or regenerate sources independently for the two arms.

Evidence anchor types:

- Title, heading, paragraph or callout: block ID (or title), NFC leaf-text hash and Unicode-code-point `[start, end)` span before whitespace normalization.
- List: block ID and zero-based item ordinal plus its leaf-text span; preserve item level and parent relation.
- Table: block/table ID, zero-based data-row ordinal and column IDs, with explicit header/unit/row-label anchors.
- Distributed evidence: several anchors in one occurrence or several claims in a sufficient set. A protected value without its subject/condition is insufficient.

Do not introduce a recursive provider schema or an executable assertion language. Use small typed records and explicit condition fields; deterministic numeric checks handle protected values, while qualitative entailment and applicability require evidence review.

### Illustrative information need and judgments

The following is a fictional example, not a label for the current corpus:

```json
{
  "schema_version": "1",
  "intent_id": "intent-f018-withdrawal",
  "family_id": "family-f018",
  "split": "test",
  "locale": "pt-BR",
  "scope": {
    "entity_ids": ["entity-f018-aurora"],
    "applicability": "Titular adulto, saque pelo aplicativo"
  },
  "task_type": "fact-and-condition",
  "answerable": true,
  "reference_answer": {
    "text": "O limite diario e R$ 3.000,00; o canal exige cadastro ativo.",
    "claim_ids": ["claim-f018-daily-limit", "claim-f018-registration"]
  },
  "sufficient_claim_sets": [
    ["claim-f018-daily-limit", "claim-f018-registration"]
  ],
  "query_variants": [
    {
      "query_id": "q-f018-withdrawal-a",
      "text": "Qual e o limite diario de saque pelo aplicativo da conta Aurora e o que preciso ter ativo?",
      "wording": "direct",
      "review_status": "approved"
    },
    {
      "query_id": "q-f018-withdrawal-b",
      "text": "Na conta Aurora, quanto posso retirar por dia no app e qual cadastro e necessario?",
      "wording": "paraphrase",
      "review_status": "approved"
    }
  ]
}
```

| Document | Grade | Reason |
|----------|-------|--------|
| Correct account guide with both claims | 3 | Sufficient direct answer |
| Correct account FAQ containing only the limit | 2 | Substantive partial evidence |
| Correct account registration procedure | 2 | Supports the required condition |
| General introduction to that account | 1 | Context only |
| Similar account with a different limit | 0 | Wrong entity; never reward the matching number alone |

An unanswerable intent has `answerable: false`, no sufficient claim sets, an explicit closed-corpus gap rationale, and no grade-at-least-2 judgment. Correct negative answers such as "this product is not eligible" remain answerable.

## Qrels coverage and review

Grades attach to the information need. Approved equivalent utterances inherit them; a variant that changes meaning must get a new intent or be rejected. Every substantive grade cites accepted occurrences; grade 1 requires correct scope and supporting context; grade 0 has an explicit judgment or an audited scope-certification provenance.

| Coverage | Permitted scoring |
|----------|-------------------|
| Exhaustive | Corpus Recall, Precision and graded nDCG on approved answerable intents |
| Certified scope | Same primary metrics only after expanding the audited rule to explicit per-document zero judgments and validating every in-scope document |
| Pooled/incomplete | Exploratory metrics labeled with judgment coverage and known-positive Recall; no primary winner or claim of corpus Recall |

An explicit entity-scoped query can certify unrelated families as zero only when entity aliases, references and applicability have been checked corpus-wide. Queries about generic fees, responsibilities or all eligible products do not qualify. Sampling negatives cannot prove completeness.

Review events are append-only and identify author/model, prompt/rubric version, timestamp, cited evidence, initial grade, final grade, reviewer type and adjudication. Release requires human review of every intent/paraphrase and claimed positive, with independent review coverage from [the design](design.md#query-coverage-and-judgments). An LLM approval is never recorded as a human approval.

Export standard qrels rows `query_id 0 doc_id grade`, expanding the approved intent labels to utterance IDs. Export grade-zero rows as well; keep a separate manifest of coverage and answerability because ordinary qrels files cannot represent all release gates.

## Search snapshot contract

1. Select the exact newly generated Blob prefix and frozen source/view manifest shared by both arms.
2. Read actual index, skillset and indexer definitions; compare the source document set, not just counts.
3. Use current `content_path` to map the exact Blob URI to the expected manifest. Remove authentication query data from stored URIs and validate account/container/prefix. Do not remove semantic path segments or accept foreign documents.
4. Export all chunks with opaque keys, parent IDs, source URI, text and hash. Persist continuation/checkpoint state. The snapshot is complete only after the full expected set has been inspected.
5. Account for each expected source, its terminal ingestion outcome and any missing chunks/evidence. Detect extra parents, unresolved mappings, duplicates and indexer errors. Distinguish verified extraction loss from incomplete indexing, vector failure and configuration/authentication errors.
6. Freeze inventory and config hashes; recheck after query collection. A changed corpus/index configuration invalidates the comparison.

If existing fields prevent a trustworthy parent/vector audit, fail preflight and create an experiment-specific index with suitable retrievable/filterable fields. Do not infer hidden vector validity from a successful index count. Do not change the live research index in place just to make the experiment pass.

For the dedicated experiment index, make vectors inspectable during snapshot audit, check per-chunk dimension/nonempty/finite-value constraints, and store vector hashes alongside text hashes. Raw vector retention is optional and bounded; audit queries must not log credentials. The existing nonretrievable embedding field cannot by itself prove per-chunk validity.

For the primary pipeline comparison, retain missing parents and unchanged source qrels when terminal extraction loss is verified; label the snapshot `ingestion_degraded` and include it in end-to-end scores plus coverage. Do not remove its queries or shrink truth denominators. A common-success subset is diagnostic only. Unattempted sources, incomplete jobs, unavailable required skills, unknown mappings or operational/authentication failures block a valid comparison instead of becoming score-zero ingestion outcomes.

The two snapshots must share exact source/view membership and artifact hashes, query/reference hashes and downstream retrieval/embedding settings. Their observed chunk IDs, boundaries, counts and supported evidence can differ. The scorer must map each arm independently to the shared canonical parents and then pair by `(query_id, method_id, repetition)`; raw Search chunk IDs are never paired between arms.

### Chunk evidence alignment

A claim's support is represented as alternatives of required chunk sets. For example, `[[chunk-a], [chunk-b, chunk-c]]` means either chunk A alone, or B and C together, support the claim. All chunk IDs are scoped to one snapshot. Do not union unrelated values to manufacture a table relation.

Alignment happens before looking at system-specific test rankings. Exact normalized text can certify a simple occurrence; split/reordered tables and semantic rewrites require reviewed relation-aware mapping. `ambiguous` support is not auto-negative: the evidence comparison remains incomplete until reviewed. Verified absence after complete extraction inspection is `missing` and earns no evidence credit while retaining the source-truth denominator.

An audited parent snapshot can support the parent-only tracer before claim alignment is released. Mark its evidence metric status `not_evaluated`; enable evidence scoring only with a complete verified support-map release tied to both snapshot and reference hashes. Updating judgments or canonical occurrences invalidates the old alignment even if chunk IDs are unchanged.

## Query collection and result contract

Each arm receives only query text and the same allowlisted retrieval configuration, not reference answers, qrels, evidence IDs, target filenames or gold-dependent filters. Freeze the complete Cartesian set of `(query, arm, method)` and its arm snapshots before the first request. The primary method is the common HYBRID configuration; extra retrieval modes are paired sensitivity analyses, not arm-specific selections.

The request fingerprint covers endpoint/index/API, raw query text hash, query-vector cache hash, `top`, vector `k`, `exhaustive`, weights, search fields, query syntax, filter/filter mode, semantic configuration and timeout/fallback policy.

Vector cache keys include exact query text after NFC/newline normalization, embedding endpoint/deployment/model/version-if-reported, dimensions and normalization version. Do not casefold units, remove accents or replace protected values. Unreported model versions remain unknown. Regenerating vectors creates a new cache/release identity.

Statuses:

| Status | Meaning |
|--------|---------|
| `pending` | No accepted response saved |
| `in_flight` | Request checkpointed before sending |
| `succeeded` | Valid response, including a legitimate empty ranking, saved and hashed |
| `failed` | Explicit safe provider/auth/rate/schema/semantic-fallback error |
| `unknown` | Interrupted call with no confirmed outcome; retry may consume another remote request |

Only successful responses are reusable. Every retry preserves the same query/request fingerprint. Resume verifies source/reference/config hashes; it never silently switches modes, indexes or semantic behavior. Use one retry owner and bounded `Retry-After` handling. Record each attempt and preserve unknown cost/usage.

Results retain original service order and separate `@search.score`, semantic reranker score and optional boosted score. Do not sort one method using another score. Semantic partial/fallback responses fail the registered semantic mode. If an SDK omits response information required to detect that, use its raw response hook rather than assuming success.

## Scoring and aggregation

The metric policy is immutable:

```json
{
  "schema_version": "1",
  "ranking_unit": "parent_document",
  "parent_collapse": "first_occurrence",
  "primary_metric": "ndcg_at_10",
  "ndcg_gains": {"0": 0, "1": 1, "2": 3, "3": 7},
  "binary_relevance_min_grade": 2,
  "precision_cutoffs": [5, 10],
  "recall_cutoffs": [5, 10, 20],
  "mrr_cutoff": 10,
  "raw_chunk_depth": 50,
  "evidence_chunk_cutoffs": [5, 10, 20],
  "context_budget_tokens": 4096,
  "unanswerable_policy": "exclude_ranking_metrics_report_separately",
  "unjudged_policy": "reject_primary_score",
  "request_error_policy": "incomplete_comparison",
  "aggregation": "utterance_then_intent_then_family_equal_weight",
  "bootstrap_unit": "family",
  "bootstrap_resamples": 10000,
  "primary_contrast": "content_understanding-minus-de_split",
  "primary_retrieval_method": "hybrid"
}
```

Add a pinned tokenizer name/version, metric library/provider versions, bootstrap seed and a predeclared contrast before a scored run. Disable automatic IR-provider fallback. In TREC ranking exports use strictly descending synthetic rank scores so provider tie handling cannot reorder the observed service ranking; preserve actual scores in the richer results.

Metric conformance fixture: judgments A=3, B=2, C=0; raw chunks `[C-1, C-2, A-1]` become parent ranks `[C, A]`. At K=2:

```text
Precision@2 = 1/2
Recall@2 = 1/2
MRR@2 = 1/2
DCG@2 = 7/log2(3)
IDCG@2 = 7 + 3/log2(3)
nDCG@2 = (7/log2(3)) / (7 + 3/log2(3))
```

This catches double credit for repeated chunks, missing denominator positives, binary/graded confusion and double-exponentiated gains. Add zero-result, perfect-ranking, duplicate/foreign IDs, unjudged, no-answer and failed-request fixtures before implementation is accepted.

For evidence, let `S` be a valid sufficient claim set and let `supported(T)` be the claims whose verified chunk-support alternative is fully contained in retrieved chunk set T:

```text
EvidenceCoverage(T) = max over S of |S intersect supported(T)| / |S|
SufficiencySuccess(T) = 1 if any S is a subset of supported(T), otherwise 0
```

Apply to raw top-K chunks and to the whole-chunk ranked prefix fitting the fixed token budget. Count exact returned content using the pinned tokenizer, including repeated overlap; do not truncate/drop chunks selectively or use gold to choose context. Record actual tokens, chunks and parents used. If the first chunk exceeds the budget, the prefix is empty and that is reported, not silently repaired.

Reports contain per-utterance scores, intent/family aggregates, ordinary query-macro scores, source/evidence coverage, exact denominators, slices with family counts, the paired delta/95% interval, latency p50/p95, request/retry/error counts and cost/usage known/unknown fields. Missing requests or incomplete primary qrels prevent a `complete` comparison.

## Persistence layout and lifecycle

Default to an ignored operational directory separate from source and corpus uploads:

```text
evaluations\
  references\<reference_release_id>\
    manifest.json
    corpus.jsonl
    families.jsonl
    claims.jsonl
    evidence.jsonl
    intents.jsonl
    queries.jsonl
    judgments.jsonl
    coverage.jsonl
    reviews.jsonl
    qrels.trec
  snapshots\<snapshot_id>\
    manifest.json
    sources.jsonl
    chunks.jsonl
    claim-support.jsonl
    ingestion-report.json
  experiments\<experiment_id>\
    plan.json
    state.sqlite3
    attempts.jsonl
    results.jsonl
    reports\
```

Reference lifecycle: `draft`, `review_required`, `released`, `superseded`. Snapshot lifecycle: `collecting`, `review_required`, `frozen` or `ingestion_degraded`. Experiment lifecycle: `planned`, `collecting`, `collected`, `scored`, `reported`, with explicit `incomplete`/`cancelled`/`invalidated` outcomes. A report declares `comparison_valid` separately from its lifecycle state so a completed diagnostic report cannot look like a valid complete experiment.

Reuse atomic writes, checksums, locks and separate SQLite state from immutable payloads. Keep evaluation state separate from generation's `RunStore`; a failed benchmark never changes accepted content or its assignments. Preserve current CLI exit meanings: input/immutable conflict 2, incomplete work 3, integrity/drift failure 4, cancellation 130. Publishing a report does not imply a statistically significant improvement.
