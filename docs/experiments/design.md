# Retrieval experiment design

Status: Core workflow implemented; live pilot and optional research extensions pending

Date: 2026-10-28

Describes AI capability: yes

## Recommendation and scope

The primary objective is to compare retrieval quality after two alternative ingestion pipelines: **Document Extraction plus Text Split** versus **Content Understanding performing both extraction and chunking**. Generate a fresh corpus as part of this protocol, freeze its files and independently reviewed reference dataset, send those exact same files through both arms, then collect paired Search rankings and score them offline.

Previous generation runs and uploaded/indexed corpora are outside this experimental protocol. They are neither input data nor prerequisites. Reuse generator code and skillset templates, not historical documents or judgments. Evaluate parent-document discovery and chunk-evidence retrieval separately.

The primary user is the retrieval researcher comparing these two combined extraction/chunking approaches. Success means an auditable paired arm difference with shared relevance judgments, source-truth denominators, uncertainty, costs, and failure coverage. Ranking algorithms, format and complexity are controls or secondary analyses, not competing primary objectives.

Deliverables are specified in [reference contracts](reference-contracts.md) and [implementation slices](implementation-plan.md). Follow [the runbook](usage.md) for executable commands and current limitations. The core parent-metric comparison is implemented; chunk-support metrics and Studies B/C remain follow-ups.

| Study | Question | Keep fixed | Permitted claim |
|-------|----------|------------|-----------------|
| A: primary pipeline comparison | Does Content Understanding improve retrieval over Document Extraction plus Text Split? | Identical newly generated artifacts, shared query/reference release, embedding space and retrieval settings | Paired end-to-end extraction/chunking-policy comparison |
| B: retrieval sensitivity | Does the arm difference persist under other retrieval modes? | The same fresh corpus/reference and both audited arm snapshots | Per-mode CU-minus-DE differences and arm-by-retrieval interaction, not a new primary ranking winner |
| C: format | How does native format affect the same semantic content? | Canonical content, queries, judgments, candidate identities, controlled layout policy | Matched-content format-assignment comparison |
| D: complexity | Where do structure/layout cause failures? | Report topic, length, genre and query-type controls | Descriptive slices initially; causal claims require matched semantic variants |

Study A is the first deliverable. Use the same fixed HYBRID configuration without semantic reranking in both arms initially; this is a proposed baseline, not a claim that hybrid is optimal. Study B can add BM25, vector and hybrid-plus-semantic as paired sensitivity analyses. Study C is optional and requires a separate exporter; normal pipeline comparison does not require rendering every document into multiple formats. Do not start with the entire factorial cross-product.

Out of scope initially: answer-generating RAG evaluation, agentic/multi-turn retrieval, training a ranker, production traffic A/B tests, OCR/image interpretation, conflicting document versions, and automatic production-index replacement.

## Reusable implementation and baseline templates

Repository inspection identifies reusable components and candidate pipeline settings:

- Canonical content already preserves block IDs, list levels, table coordinates, fact references, hashes and provenance. Reuse these as evidence anchors; a fact ledger alone does not establish relevance.
- [Document Extraction/Text Split](../../ai_search_resources/skillset_de.json) uses 2,000 characters and 200-character overlap. [Content Understanding](../../ai_search_resources/skillset-cu.json) uses semantic 2,000-token chunks and no overlap. This changes extraction, chunk size and segmentation together.
- Both definitions currently target `my-index`. Exported IDs are Search-generated chunk/parent keys, not canonical content identities. The index includes searchable IDs/path-like titles and no explicit corpus/view identity.
- Existing local validation establishes native artifact fidelity, not what Azure extraction preserved. A Search snapshot needs its own ingestion/evidence audit.

These are templates, not experimental snapshots or audited live settings. Provision experiment-specific resources and record the actual deployed definitions. Native validation establishes the fidelity of newly generated source artifacts, not what either ingestion arm will preserve.

### Two-arm treatment and controls

| Component | DE_SPLIT arm | CU arm |
|-----------|--------------|--------|
| Input | The same frozen new corpus manifest and Blob prefix | Identical source files and hashes |
| Extraction | Document Extraction skill | Content Understanding skill |
| Chunking | Text Split with frozen length/overlap/language settings | Content Understanding's native semantic chunking with frozen settings |
| Output | DE chunk text and source-parent map | CU chunk text and source-parent map |
| Embeddings | Common deployment/model/dimensions | The same embedding space |
| Index | Dedicated DE index | Dedicated CU index with the same downstream schema/vector/analyzer settings |
| Retrieval | Fixed hybrid query settings and shared cached query vectors | Identical query/retrieval settings |
| Truth | Source-derived, reviewed queries/qrels/evidence | The same frozen reference, with a separate observed chunk-support map |

Different chunk counts, boundaries, lengths and extracted representations are expected treatment effects; do not require equal chunk IDs/text or generate a separate corpus/reference for each arm. The current character-versus-token settings are candidate end-to-end policies, not equivalent sizes. Freeze each arm on development data; if tuning arm-specific chunking, allow symmetric development budgets and retain the same query-time controls.

Keep generated keywords out of primary lexical/semantic search fields, disable semantic reranking for the primary baseline, and keep common downstream enrichment identical. Account for indexing time, chunk/embedding volume and inference cost separately. Verify native semantic CU capability/API/format support before freezing the arm; never silently replace it with fixed-size chunking.

CU semantic chunking is distinct from query-time semantic reranking: keep the former enabled in the CU arm even though the primary retrieval baseline omits the latter. The documented CU `method: semantic` and token-length controls require the `2026-05-01-preview` skillset API or a later explicitly verified version. Pin that separately from the common Search query API; do not rely on stable-API default fixed-size behavior.

## Reference data: plan truth, verify evidence, then ask questions

1. **Plan scenario families.** Define fictional entities, typed claims, applicability, exceptions, and near-miss siblings before prose. A family is a coherent subject with several related documents; it is not one arbitrary topic.
2. **Plan evidence coverage.** Assign claims and qualitative requirements to particular documents/structures. Include responsibilities, negations, scope and conditions, not only amounts/dates.
3. **Author and accept content.** Reuse current schema, fact, length, structure and uniqueness checks. Scope shared facts to the family; do not make all families share one global entity. Unused planned facts are not accepted evidence.
4. **Freeze accepted content.** Resolve actual block/list/table occurrences and readback. Missing or ambiguous required evidence fails the reference build instead of becoming a guessed answer.
5. **Create information needs.** Generate user-like questions from accepted evidence without exposing filenames, internal IDs, grade labels, or the document's wording as a mandatory phrase. Record the intended question separately from its natural-language variants.
6. **Judge relevance across the corpus.** The document used to author a question is a candidate positive, not the only positive. Sibling FAQs, procedures and tables can also answer it. Wrong-entity or wrong-applicability near misses are negatives even when lexically similar.
7. **Review and release.** Validate query equivalence, all claimed positives and answerability. Freeze dataset hashes and reviewer decisions before measuring test systems.

Both arms must remain absent from source-truth authoring: create queries/qrels from the newly accepted canonical content and verified artifacts, not DE or CU output. A planned claim that is absent from accepted content cannot become gold. Keep the reference independent of pipeline-specific chunk boundaries and review actual chunk support only after ingestion.

### Query coverage and judgments

| Dimension | Required coverage |
|-----------|-------------------|
| Information need | Entity/fact lookup; eligibility/threshold; exception/procedure; table/comparison; distributed or set-valued evidence |
| Wording | Direct user wording and a verified paraphrase per intent; natural abbreviations and lexical mismatch where appropriate |
| Evidence | Prose, ordered steps, nested exceptions, table headers/units/rows, and evidence spanning multiple chunks/documents |
| Negatives | Near-miss entity, wrong condition, wrong attribute/unit, topically related background |
| Unanswerable | A genuinely missing requested fact/entity within the closed corpus; an explicit negative answer is still answerable |

Use ordinal grades: **3** directly and sufficiently answers the need; **2** supplies correct substantive partial evidence; **1** supplies useful context within the correct entity/scope but not substantive answer evidence; **0** irrelevant, wrong entity/applicability, or misleading. Multi-document needs may have only grade-2 parents. Binary metrics use grade at least 2.

Query authors and reviewers must not inspect which system wins. A model may draft questions/judgments, but must cite canonical evidence and may not turn its own prose into unquestioned gold. Review every query's meaning and positive evidence; independently double-review all unanswerable/distributed/ambiguous cases plus a seeded 20% of other cases. Record adjudication, ordinal-weighted agreement and substantive-positive disagreements separately; an abundance of easy zero labels must not hide positive-label disagreement. Model self-agreement is not human approval.

Prefer query drafts authored from the structured information need and validated claims rather than copied source paragraphs/headings. Include a human-authored subset of at least 20% of intents, distributed across task types. Measure lexical overlap as a diagnostic, not an automatic rejection rule: entity names and legitimate product terminology naturally recur. Keep both direct and paraphrased forms instead of selecting whichever makes a preferred retriever win.

### Complete relevance sets and honest Recall

- For a newly generated smoke batch, assess every query against every source document.
- For the planned family-based dataset, inspect all six family documents. Outside-family documents can receive explicit certified zero labels only for unambiguously entity-scoped needs with disjoint entities/aliases and a corpus-wide scope audit.
- That scope rule is a testable closed-world assumption, not permission to assume every unjudged document is irrelevant. Global/broad queries require full-corpus review or an explicitly incomplete reference.
- Add the union of top-50 results from both arms and registered retrieval modes, sibling candidates and seeded random negatives to the adjudication pool, with equal depth and assessor-blinded arm identities. Review unexpected out-of-family hits. If this exposes a reference error, invalidate the comparison and publish a new reference release for both arms; never adjust only one arm's score. New methods must not be disadvantaged by an old arm/method-specific pool.
- Keep `unjudged` distinct from grade 0. For pooled/incomplete qrels, publish judged coverage and label recall as **known-positive Recall**, not corpus Recall. Locked primary comparisons require complete parent qrels and all evaluated returned candidates judged.
- Confirm each positive intent has at least one supported relevant parent. At least two of five answerable intents per family should have multiple relevant parents; at least one should require combined evidence. Otherwise Recall mostly becomes a single-hit metric.

## Recommended dataset sizes and splits

| Stage | Size | Purpose |
|-------|------|---------|
| Fresh smoke | Two newly generated families, six documents each; ten answerable intents and two negative controls, each worded twice | Source/reference correctness and a complete DE-versus-CU tracer |
| Fresh reference pilot | 60 newly generated families, six documents per family: 360 documents | Calibrate both pipelines, judgment effort and paired uncertainty |
| Confirmation | At least three independently authored corpus seeds after pilot sizing | Replication; report each seed as well as an aggregate |

Per pilot family, plan five answerable intents and one unanswerable control, each with two semantically equivalent phrasings: **360 intents and 720 query utterances**. Example document roles are product guide, procedure, FAQ, comparison, near-miss sibling, and exception/scope supplement; assign genres and structures deliberately rather than equating a role to one fixed format.

Split entire families 20% train/calibration, 20% development, 60% locked test: 12/12/36 families. All related documents, names, query paraphrases and future render variants stay together. For test, this yields 180 answerable and 36 unanswerable intents, or 432 utterances. Paraphrases and repeated renderings do not create independent samples.

Develop generation/judgment prompts on calibration families and retrieval settings on development families; freeze them before authoring/scoring the locked test. All corpus documents may remain available as retrieval distractors across splits; test judgments and test performance must not enter tuning. Hide test labels from the retrieval runner. Retire a test release to development if repeatedly used to tune.

These are starting workload sizes, not a power guarantee. Use pilot family-level CU-minus-DE differences to estimate the sample size needed for the predeclared practical effect. The fresh smoke batch is calibration-only and cannot provide a reliable performance conclusion. Distinct `scenario_id` strings do not prove independence; the planned entity/claim families define the grouping.

## Azure Search: isolate and audit the indexed corpus

Create experiment-specific index/indexer/skillset names; never point competing skillsets at the same mutable `my-index`. Restrict Blob input to the exact corpus/view prefix. Record source artifact hash, index definition, skillset/indexer fingerprints, API version, embedding deployment/dimensions, extraction settings, observed document inventory and snapshot time.

| Requirement | Strategy |
|-------------|----------|
| Canonical parent identity | Exact external map from normalized Blob source URI to corpus-qualified canonical document ID and artifact hash |
| Current chunk/parent IDs | Retain opaque Search IDs in snapshot/result logs; do not parse them to infer original content IDs |
| Reindexing | New snapshot and chunk map; reject old chunk labels with new IDs/text |
| Cohort isolation | Dedicated index preferred; otherwise validated filterable corpus/view fields and identical prefilters in every method |
| Metadata leakage | IDs/paths are retrievable/filterable, not searchable; restrict lexical search fields explicitly |
| Titles | Use visible business titles if reliably populated; otherwise use a content-only semantic configuration. Blob URLs are not semantic titles |
| Enrichment | Verify nonempty text, vector dimension and embedding presence; confirm keyword field exists before enabling it |
| Completeness | The same expected source manifest in both arms; no foreign parents; account for every attempted source and its terminal ingestion outcome, including missing chunks/evidence |

Index counts alone are insufficient: one missing parent and one foreign parent can cancel numerically. Freeze the observed chunks and text hashes. Disable uncontrolled scheduling/reindexing during collection; verify inventory/configuration again after it. Fail a run on drift.

Preserve source-truth denominators when an arm loses documents or evidence. Verified terminal extraction loss or unsupported source formats remain in the primary end-to-end evaluation and coverage report; never delete their queries or reduce Recall/IDCG denominators. An optional common-success subset is a labeled diagnostic only. Incomplete indexing, permission/configuration errors, unresolved mappings or unattempted files are operational failures that block a valid comparison, not convenient zero-score substitutions.

Predeclare the source-format mix and format-capability treatment before generation; do not drop poorly supported formats after seeing which arm fails. Parent ranking, evidence survival, and source-format ingestion coverage explain different failure stages.

### Common retrieval baseline and optional sensitivity matrix

| ID | Configuration | Query behavior |
|----|---------------|----------------|
| HYBRID | Primary common configuration | Same content-only lexical request and cached vector, `k=50`, weight 1.0, registered fusion/filter settings, no semantic reranking |
| BM25 | Optional sensitivity | Same natural-language `search` and content-only fields; simple syntax; no vectors or semantic reranking |
| VECTOR | Optional sensitivity | Same cached query vector, one embedding field, `k=50`; no lexical query |
| HYBRID_SEMANTIC | Optional sensitivity | The same hybrid settings with a fixed content-based semantic configuration, identical in both arms |
| BM25_SEMANTIC | Later optional ablation | Isolates semantic reranking without dense retrieval |

Return **50 raw chunks** per query/configuration, with the same eligible corpus and filters; score parent cutoffs 5/10/20. Azure semantic ranker only reranks up to 50 initial results, so candidate recall must be reported separately. Fewer than K unique parents is a real result; do not secretly issue extra queries for just one method.

Precompute each query vector once per normalized query/model/dimension tuple and reuse it across VECTOR/HYBRID and snapshots. Preserve accents and meaning; do not strip factual constraints. Use `text-embedding-3-large`, 3,072 dimensions initially to match existing artifacts. Verify actual deployment compatibility; query and document vectors must use the same embedding space.

Capture explicit text/vector `k`, `top`, HNSW/exhaustive mode, vector weights, filters/filter mode, searchable fields, semantic configuration, synonym/scoring profiles and API options. Tune only registered development grids. RRF's internal rank constant is not vector `k`; preserve the service's RRF behavior rather than implementing a second fusion step. Use a fixed stable API version supporting the chosen capabilities; preview CU capabilities, if required, are pinned and reported separately. Do not silently downgrade an unavailable feature.

The semantic variant must return a successful reranked response. If Azure returns a partial response or falls back to lexical/vector ordering, record a failed semantic configuration rather than silently accepting it. Service-side model versions are not always exposed; record the evaluation window and available version metadata and describe reranker reproducibility as best effort, not a fully pinned model.

## Metrics and ranking units

**Primary:** parent-document nDCG@10. **Secondary:** parent Precision@5/10, Recall@5/10/20, MRR@10 and candidate Recall within the 50-chunk retrieval pool.

1. Map every returned chunk to a canonical parent.
2. Preserve the service's final order; retain score fields for diagnostics, not cross-method sorting.
3. Collapse repeated parents by first occurrence, then apply K. Multiple chunks from the same document never multiply document-level credit.

For parent rank i with judgment grade g:

```text
relevant(g) = 1 when g >= 2, otherwise 0
Precision@K = relevant parents in the first K / K
Recall@K = relevant parents in the first K / all relevant parents in the frozen corpus
DCG@K = sum((2^g_i - 1) / log2(i + 1)), i starts at 1
nDCG@K = DCG@K / ideal DCG@K over the full frozen judgments
```

Pad short result lists with zero gain for precision/DCG; do not divide precision by the number returned. MRR uses the first grade-at-least-2 hit. IDCG never comes only from retrieved candidates. Publish positive counts and the attainable Precision@K ceiling `min(K, relevant_count) / K`; with one relevant parent, Precision@10 cannot exceed 0.1 even for an ideal retrieval. Empty/failed responses are distinct: a successful empty response scores zero for an answerable query; a service failure is an error, not a fabricated empty ranking.

Unanswerable queries have no grade-at-least-2 parents. They may still have grade-1 background, so zero IDCG is not guaranteed by the grade definition. Explicitly report their ranking metrics as **not applicable**, outside answerable macro averages, regardless of contextual gain. Keep them as separate negative controls. Search normally returns results even when no answer exists; do not claim abstention without an explicit decision policy calibrated on development data.

Use pinned `ir_measures` and its explicitly selected `pytrec_eval` provider for conventional metrics, after verifying the exact package/provider on Windows. Set `nDCG(dcg="log2", gains={0:0,1:1,2:3,3:7}, judged_only=False)` and the relevant cutoff. This uses explicit gains once; do not also select exponential DCG or exponentiate input judgments. Set binary relevance thresholds to 2 on original grades, or supply a separately derived binary qrels view. Verify both paths against hand-computed cases. An unavailable/unsupported provider fails installation/preflight, not a silent scoring fallback.

### Evidence metrics independent of chunk boundaries

Store minimal sufficient sets of semantic claims and their validated source occurrences. Different occurrences of the same claim are alternatives, not extra credit. A table answer must include the association between value, entity/row, column/unit and applicable condition.

- **EvidenceCoverage@K chunks:** maximum fraction of one valid sufficient claim set supported by the union of top-K raw chunks.
- **SufficiencySuccess@K chunks:** one if any full sufficient claim set is supported; otherwise zero.
- Report at K=5/10/20 and under a fixed **4,096-token context budget** using a pinned tokenizer. Pack a prefix of whole ranked chunks; stop when the next chunk exceeds the budget. Do not select chunks using gold labels.
- Add ingestion-stage evidence survival and single-chunk sufficiency diagnostics. Parent discovery can succeed while the retrieved chunk omits the answer or exception. When several partial chunks support one claim together, record that required chunk set; token/value presence alone cannot certify the relation.

Align observed chunk text to canonical occurrences independently of system rankings, once per snapshot/reference pair. Exact normalized matches can certify simple prose; reordered tables, semantic transformations and ambiguous spans require relation-aware review. An unmapped chunk is not automatically irrelevant. Preserve cases where evidence is split, distorted or lost. The first parent-metric tracer may report evidence metrics as `not_evaluated` until an alignment release is complete; it must not fabricate zero evidence scores.

## Statistical analysis and operational fairness

- Average paraphrases within an intent, intents within a family, and families equally for the main estimate; report ordinary query-macro means as a secondary view. Publish the exact aggregation policy.
- Pair each query across the DE_SPLIT and CU snapshots from the exact same corpus release. Use 10,000 seeded paired bootstrap resamples at family level, preserving all paraphrases and arm pairings. For multiple corpus seeds, report seed-level results and a hierarchical seed/family bootstrap; three seeds do not prove broad domain generalization.
- Predeclare one primary contrast: **CU minus DE_SPLIT on nDCG@10 with the common HYBRID configuration**. Report effect size and 95% confidence interval. Sensitivity analyses report the CU-minus-DE delta within each common retrieval mode, not CU-hybrid versus DE-BM25. Use a documented multiplicity correction, such as Holm, for secondary inferential comparisons. Correlated format views are not independent observations.
- Before locked evaluation, register a practical-effect target and acceptable latency/cost tradeoff. An initial planning value is +0.03 nDCG with no more than 0.02 absolute Recall@20 degradation; pilot-based confirmation replaces these defaults before freezing test.
- Report slices by query type, topic, length, genre, logical complexity, native layout and format, with sample/family counts. Single-target queries have a target format; distributed queries form a mixed-format category. Do not filter away other-format distractors to manufacture format slices.
- Randomize/interleave request order in seeded blocks; keep concurrency fixed and measure warm-up separately. Log service region/tier/replicas/partitions and supported scoring-statistics/session settings. Avoid concurrent indexing or uncontrolled load during collection. Log search latency, query embedding latency and end-to-end latency separately, labeling cached versus cold embedding paths. Repeats measure runtime stability, not new relevance samples.
- All query/configuration pairs are required. On unresolved failures, the locked comparison is incomplete; never silently average only successful queries. Publish error rate and a separately labeled pessimistic zero-credit sensitivity analysis if useful.

BM25, cosine, RRF and semantic scores are not comparable probabilities. Do not use one global score threshold across modes, or report a confidence interval over raw scores as retrieval quality.

## Controlled format and pipeline follow-up

The normal generator still assigns one format per accepted content item. Preserve that contract.

For Study C, add an opt-in **benchmark-view exporter** outside normal runs: render the same immutable canonical items into six separate views. Within each view, each parent appears once. Assign the six formats once per six-document family, then rotate assignments across the six views so each parent occurs in every format exactly once. Never index the six copies together.

Reuse semantic qrels across views but validate each artifact, source map and snapshot independently. Keep length/genre/logical content fixed and use a declared baseline native-layout policy first; investigate richer layouts separately. This measures a matched-content format-assignment policy including its extraction effects. Simultaneously rotating distractors is not a pure isolated effect of one target file's encoding.

Study A deliberately compares the combined extraction/chunking policies. Do not impose a common external chunker on the primary arms: Content Understanding must perform both operations. An extractor-only ablation or canonical-text control can be a separately labeled future diagnostic. Merely changing both size settings to the number 2,000 does not equalize characters and tokens.

For Study D, first use the current independent logical-complexity/native-layout labels as descriptive slices. A controlled follow-up holds claims, entities, conditions, genre and actual word count within a declared tolerance while rearranging evidence into simple/moderate/complex structures. Review that each variant preserves the same answerability/qrels. A renderer-only layout experiment can preserve identical canonical text; a logical-structure rewrite cannot be assumed semantically equivalent merely because its fact values match.

## Engineering decisions and risks

| Decision | Selected strategy | Reason and boundary |
|----------|-------------------|---------------------|
| Execution model | Local CLI/library plus SQLite and immutable JSON/JSONL | Reuse existing Windows-first execution and recovery patterns; no hosted evaluation service |
| Search integration | Typed `azure-search-documents` adapter; raw request/result logging without credentials | One public request contract per mode, offline SDK transport tests, Entra data-reader access |
| Metrics | Pinned IR library/provider with explicit gain/binary semantics | Standard definitions with independent numeric fixtures; no model judge in metric calculation |
| Generation change | Opt-in family/coverage plan before authoring; preserve old serializers | Cross-document truth and distractors without modifying accepted content or legacy runs |
| Review | Human-adjudicated reference release; bounded optional model assistance | No self-certified gold and no hidden benchmark tuning |
| Authorization | Read-only Search collection by default; separate explicit indexing/generation opt-in | Research execution must not reset or replace production indexes, alter RBAC, or leak qrels |

Assume the newly generated study stays in fictional retail banking and Brazilian Portuguese, matching the configured domain/locale. English, additional domains, hosted automation and user-traffic distributions require separate releases, not hidden changes.

The repository has local offline test/build gates and version-controlled feature branches. No remote CI pipeline or required PR review policy was found; treat wiring these checks into the existing Azure DevOps process as an implementation prerequisite before repeated team releases, not a reason to provision a new platform. Small-team/manual reference review is the initial workflow.

Controls against experimental failure:

- Keep all qrels, expected answers, evidence maps, query-generation prompts, result logs and reports outside upload/index prefixes. Upload only an approved artifact manifest.
- Treat retrieved/source text as untrusted data for query drafting or optional judging; disable tools/actions in judge prompts, require structured evidence citations, and validate every referenced ID.
- Use approved Azure endpoints and renewable Entra credentials; `Search Index Data Reader` is sufficient for collection. Index definition inspection/provisioning can require separate roles and must not silently elevate.
- Bound reference-authoring, judging, embedding, snapshot-export and Search requests independently. Keep retries to one owner and cap result sizes. Never log tokens, keys, SAS query strings or authorization headers.
- Record failed ingest, missing evidence, unknown judgments, interrupted requests, index drift and semantic fallback as first-class outcomes. Preserve original query denominators and do not silently publish an incomplete test.

## Cost posture, gates and defaults

| AI cost field | Policy |
|---------------|--------|
| Model-tier commitment | Reuse configured generation and embedding deployments. No implicit new judge/model provisioning; optional independent judge requires explicit configuration and budget |
| Latency budget | Explicit request deadline, bounded retry/concurrency, per-stage latency recording; no unverified completion SLA |
| Prompt-stability invariant | Freeze authoring, query, judge, rubric and tokenizer versions before test; new versions create new releases |
| Per-call cost ceiling | Explicit request/output-token and observed-total limits for generation/judging/embeddings; Search/semantic request ceilings; preview workload, not invented currency totals |
| Cost-incident escalation | Stop new work on budget exhaustion, retain checkpoints/known usage, report unknown in-flight outcomes; require an audited explicit increase |

For one pilot test split: 432 utterances times one common HYBRID mode times two arms is **864 Search requests**. Optional four-mode sensitivity requires **3,456** requests across both arms. A later six-view comparison of both arms under one common mode requires **5,184** requests. These exclude development searches, retries, repeats, indexing, embeddings and judgment work. Query vectors are computed once per query and reused in both arms. Produce a dry-run estimate before every paid phase.

Release gates: immutable input hashes; reviewed evidence/query coverage; complete primary qrels; family-disjoint splits; exact parent inventory; valid vectors and source map; no answer-bearing sidecars in the index; all expected request outcomes; identical scoring/aggregation policy; versioned report. Synthetic-bank findings do not establish performance on real organizational documents.

## Sources and decision status

This design uses official [Content Understanding skill guidance](https://learn.microsoft.com/azure/search/cognitive-search-skill-content-understanding), [Text Split guidance](https://learn.microsoft.com/azure/search/cognitive-search-skill-textsplit), [Azure RRF guidance](https://learn.microsoft.com/azure/search/hybrid-search-ranking), [semantic ranking limits](https://learn.microsoft.com/azure/search/semantic-search-overview), [vector query behavior](https://learn.microsoft.com/azure/search/vector-search-how-to-query), [hybrid queries](https://learn.microsoft.com/azure/search/hybrid-search-how-to-query), [index projections](https://learn.microsoft.com/azure/search/search-how-to-define-index-projections), [API version guidance](https://learn.microsoft.com/azure/search/search-api-versions), [IR metric definitions](https://ir-measur.es/en/latest/measures.html), and [NIST qrels guidance](https://trec.nist.gov/data/qrels_eng/).

The [accepted protocol decision](../architecture/decisions/0004-retrieval-experiment-protocol.md) implements fresh generation, reviewed source truth, paired DE_SPLIT/CU snapshots, common hybrid collection and parent metrics without historical-run dependencies. Exact evidence locations are resolved after acceptance; chunk entailment/support scoring remains unimplemented. Dataset sizes and practical-effect values require calibration rather than implying statistical power. Cloud readiness, human reference approval, actual index inventory and paid budgets remain execution gates.

### Evolution log

| Version | Date | Change | Trigger | Author |
|---------|------|--------|---------|--------|
| 0.1 | 2026-10-28 | Defined the reference-first retrieval experiment extension and staged implementation strategy | new work | Research design |
| 0.2 | 2026-10-28 | Made newly generated DE_SPLIT-versus-CU ingestion the primary paired experiment; removed prior-run import and ranking-first dependencies | user scope clarification | Research design |
| 0.3 | 2026-10-28 | Implemented the core local/CLI protocol and documented compact v1 payloads, manual review, live gates and deferred evidence/view analyses | implementation requested | Implementation |
