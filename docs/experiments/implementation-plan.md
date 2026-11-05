# Retrieval evaluation implementation strategy

Status: Core implementation available; live pilot, reviewed chunk support and optional studies pending

Date: 2026-10-28

## Delivery order

Implement the protocol as a paired **DE_SPLIT-versus-CU experiment on freshly generated data**. Establish metric contracts and family-aware generation first, create one source-derived reviewed reference, then ingest the exact same artifacts through both skillsets and compare them under one fixed hybrid retrieval configuration. Previous generation runs are not inputs or prerequisites. Additional retrieval modes and matched-format views are secondary.

Use [the design](design.md) for experimental decisions and [the contracts](reference-contracts.md) for payloads, invariants and metric semantics.

### Prioritized user outcomes

| Story | Priority | Observable outcome |
|-------|----------|--------------------|
| EX-US1 | P1 | A researcher can validate a reviewed reference and reproduce nDCG, Precision and Recall offline from saved rankings |
| EX-US2 | P1 | A researcher can compare DE_SPLIT and CU on the same newly generated source/reference/query set, using paired arm snapshots and identical query-time retrieval settings |
| EX-US3 | P1 | A researcher can generate related documents, supported queries and graded judgments without inventing evidence or leaking labels into Search |
| EX-US4 | P2 | A researcher can examine the pipeline difference under additional common retrieval modes and optional matched format/layout views |
| EX-US5 | P1 | A researcher can resume bounded work and obtain a versioned report with paired uncertainty, latency, coverage and known/unknown usage |

### Testable requirements

| ID | Contract |
|----|----------|
| EX-R1 | Resolve every reference/document/evidence identity and hash; fail on stale, missing, duplicate, contradictory or unreviewed required records |
| EX-R2 | Compute exact registered parent metrics after first-occurrence deduplication; retain full qrels denominators and explicit no-answer/unjudged/error policies |
| EX-R3 | Freeze two arm snapshots of the same freshly generated manifest; reject source mismatch, foreign parents, drift and unsafe filters; retain verified ingestion loss in shared source-truth denominators |
| EX-R4 | Use one identical HYBRID request configuration and shared cached vectors in both arms initially; optional BM25, VECTOR and HYBRID_SEMANTIC modes remain symmetric paired sensitivity tests |
| EX-R5 | Keep family/alias/paraphrase/view groups split-safe; use review-backed query/claim coverage and complete or honestly labeled qrels |
| EX-R6 | Preserve normal generation, publication, upload and resume semantics; do not reauthor accepted content or combine format copies in one index |
| EX-R7 | Bound request/token/concurrency/retry budgets, preserve unknown outcomes, redact credentials and require explicit opt-in for paid/cloud-changing phases |
| EX-R8 | Require every planned response for primary comparisons; produce paired family-level estimates, denominators, slices and latency/usage diagnostics |

## Implementation slices and dependencies

Dependencies below are actual prerequisites, not assumptions from table order. Existing application tests remain required; use the smallest selectors per slice and the full applicable offline gate before release.

| Slice | Depends on | Stories / requirements | Implementation surface | Acceptance evidence |
|-------|------------|------------------------|------------------------|---------------------|
| E00: freeze two-arm contracts and decisions | None | All stories; EX-R1 to EX-R8 | These documents; existing architecture decisions; proposed evaluation config | Approve fresh source/arm parity, common retrieval, grade/gain/unit/error policy; record the family extension and any later optional views before changing generator invariants; verify Windows metric-provider packaging |
| E01: offline reference validator and scorer | E00 | EX-US1; EX-R1, EX-R2 | Proposed `src/docgen/evaluation/models.py`, `reference.py`, `metrics.py`; CLI `eval score`; focused tests/fixtures | Hand-computed metric fixtures pass; complete versus pooled judgments enforced; no network or model dependency in scoring |
| E02: family-aware fresh corpus generation | E01 | EX-US3; EX-R1, EX-R5, EX-R6, EX-R7 | Opt-in extensions in `config.py`, `models.py`, `planning.py`, `prompts.py`, `composition.py`, `generation.py`; family/claim-placement planner | Newly generated artifacts belong to this protocol; frozen scoped facts/coverage, distinct sibling documents and safe splits; legacy behavior remains compatible without importing historical runs |
| E03: source-grounded reference release | E02 | EX-US1, EX-US3; EX-R1, EX-R2, EX-R5, EX-R6, EX-R7 | Proposed `reference_authoring.py`, review/release validator and JSONL contracts | Fresh calibration batch has reviewed queries, actual canonical/artifact evidence, complete qrels and supported answerability before either arm's test retrieval |
| E04: paired ingestion and snapshot audit | E03 | EX-US2, EX-US5; EX-R3, EX-R6, EX-R7, EX-R8 | Experiment-specific DE/CU indexer/skillset/index builder from `ai_search_resources`; source and evidence auditor | Both arms ingest exact same hashes/prefix; same downstream schema/model settings; distinct native chunking policies; foreign/drift errors rejected and terminal source losses accounted |
| E05: fixed hybrid collection in both arms | E04 | EX-US2, EX-US5; EX-R3, EX-R4, EX-R7, EX-R8 | Proposed `evaluation/search.py`, `runner.py`, shared query embedding cache; separate SQLite state and offline SDK transport tests | One query/reference set and vector cache; identical hybrid request settings in DE/CU; every arm/query pair tracked; failures/resume cannot switch source or mode |
| E06: paired pipeline reports and pilot | E05 | EX-US1, EX-US2, EX-US3, EX-US5; EX-R1, EX-R2, EX-R5, EX-R7, EX-R8 | `evaluation/reports.py`, family-level paired analysis; reviewed 60-family pilot release | CU-minus-DE nDCG/Precision/Recall and evidence metrics, exact shared denominators, ingestion coverage, latency/indexing cost, no success-only subset bias |
| E07: retrieval-mode sensitivity | E06 | EX-US4; EX-R3, EX-R4, EX-R6, EX-R8 | Optional BM25/vector/semantic request builders using the same two snapshots | Each added mode runs on both arms; report the arm delta per mode; no CU-hybrid versus DE-BM25 comparison presented as a pipeline effect |
| E08: matched format/layout views | E06 | EX-US4; EX-R1, EX-R3, EX-R5, EX-R6, EX-R8 | Separate opt-in benchmark exporter over native renderer registry; view manifest validation wired to uploader/snapshot preflight | Six independent views, one artifact per parent per view, every family uses each format once, content/qrels preserved, native readback and view isolation pass |
| E09: preregistered locked pipeline evaluation | E06; E07/E08 only for optional analyses | All stories; EX-R1 to EX-R8 | Frozen config, workflow checks and reproducible report bundle | No tuning on locked labels, every DE/CU query pair accounted, source parity/snapshot stability verified, paired confidence intervals and review/cost sign-off |

E01 metric fixtures and E02 generation start locally; no historical-corpus importer is required. E00-E06 deliver the actual two-arm protocol. E07 and E08 are independent optional follow-ups and do not block the primary pipeline experiment. Logical-complexity causal variants require an additional reviewed semantic-equivalence slice after E08; primary complexity/format results are slices of the paired pipeline effect.

E00 is a specification/compatibility checkpoint, not permission to delay the offline tracer indefinitely. Use Azure DevOps and existing local checks rather than inventing a new orchestration service. Remote CI/review enforcement is not evidenced in this repository; wire the release checks into the team's existing pipeline before shared locked-test releases.

The local Python/CLI and persistence choices follow existing [runtime](../architecture/decisions/0001-application-runtime.md) and [persistence](../architecture/decisions/0002-corpus-persistence.md) decisions. Keep existing [native-rendering](../architecture/decisions/0003-document-rendering.md) guarantees; E00 must explicitly record the separate benchmark-view scope before E08 permits multiple representations outside normal runs.

## Generator changes: precise extension points

| Current surface | Proposed extension | Preserve |
|-----------------|--------------------|----------|
| One scenario ID assigned per item | Optional `family_id` and frozen family plan containing related document/scenario IDs and entity aliases | Legacy scenario identity and omitted-field serialization |
| `GenerationConfig.shared_facts` applied run-wide | Resolve an exact scoped ledger from the blueprint's family/scenario plus explicitly global immutable facts | Existing fact composition and unit/value checks; no cross-family entity conflicts |
| Genre/length/structure blueprints | Add document roles and required claim/evidence-placement obligations before prose | Existing word bands/grace, measurable complexity, native portability and uniqueness |
| LLM produces factual and qualitative business text | Require frozen scenario claims plus qualitative scope/exception coverage; verify against accepted occurrences | No hidden answers, query text, qrels, family labels or evaluator hints in business documents |
| Flat document-provider wire schema | Separate small schemas for family planning/query drafts; reuse authentication, safe errors, usage and bounded execution | Do not send query records through `Draft`/`DRAFT_SCHEMA` or break the existing document provider contract |
| One normal format assignment per item | Separate benchmark-view exporter only in E08 | Existing `run`, `render`, `resume`, hashes, N-file publication and no duplicated format copies in a normal corpus |

Do not infer family truth from an LLM's new answer after the corpus is frozen. Family generation has two gates: planned truth/coverage is immutable before authoring; actual evidence and question validity are approved after acceptance. An unsupported planned claim fails/retries within the explicit budget rather than silently appearing in gold.

For the 360-document pilot, plan one generation run within the existing 1,000-item limit. Independent corpus seeds are separate runs/releases. Do not increase request/token budgets automatically with count. Sibling documents should share meaningful claims while remaining distinct business documents, not near-duplicate padding that bypasses uniqueness controls.

## Implemented command workflow

The actual namespace is `docgen experiment`; [the runbook](usage.md) is the executable guide. Normal document commands remain unchanged. The implementation uses typed consolidated JSON records rather than the earlier JSONL/interface sketch.

| Command phase | Function | External effects |
|-------------------------|----------|------------------|
| `plan`, `init` | Preview and freeze fresh source/family/resource identities | No Azure calls; `init` writes local state |
| `generate` | Author/render fresh sources; repeat to resume | Bounded paid generation with `--live` |
| `reference-build` | Draft source-backed claims, queries and judgments | Local only |
| `review`, `reference-validate`, `release` | Record human approval and seal reference/qrels | Local only |
| `prepare`, `ingest` | Upload identical sources, create owned resources and start initial indexers | Requires `--live`; no resets or production resources |
| `snapshot` | Audit/freeze one completed arm | Bounded read-only Azure calls with `--live` |
| `collect` | Collect/resume paired hybrid rankings with shared vectors | Bounded Search/embedding/audit calls with `--live` |
| `score`, `status` | Produce offline metrics/report or inspect durable progress | Local only |

Review input uses editable draft JSON plus immutable payload-bound review events. Release rejects missing, stale or unaudited approvals. Human origin/semantic quality remain reviewer attestations. No automatic model judging is enabled.

Search provisioning/reindexing belongs to a separately approved preparation operation or reviewed resource deployment, not `eval run`. Create dedicated DE/CU indexes and matching indexers/skillsets from the start; never reset `my-index` or use unrelated existing corpus contents. Both indexers read the same new source prefix. Verify compatible CU semantic capability/API support; unavailable treatment settings fail preflight instead of silently changing chunking.

### Frozen experiment configuration

Use [retrieval-experiment.yaml](../../examples/retrieval-experiment.yaml). It specifies two families/twelve documents, all-test smoke splits, existing Azure selectors and independent generation/evaluation budgets. The immutable protocol derives resource names and source prefixes; callers cannot import previous runs or supply independent corpora for the arms.

CU semantic skillsets use `2026-05-01-preview`; common queries use `2026-04-01`. The implementation uses direct REST instead of a stable Search SDK so preview treatment fields survive serialization. Query vectors are cached by exact normalized text and embedding identity. All evaluation attempts, including audits and retries on resume, consume persistent ceilings. Observed-token counters disclose unknown usage; they are not currency guarantees.

The 60-family design still implies 432 test utterances and 864 primary paired outcomes, but its budgets must also cover audit scans, retries and resumptions. The sample's smoke limits do not scale automatically.

## Test and verification matrix

The matrix is the broader design target. Chunk-support/packing and matched-view cases EX-C10, EX-C15 and EX-C16 are deferred; related evidence-union or pooled-scoring clauses are not claimed by the parent-only implementation. Current reports expose evidence metrics as `not_evaluated`.

| Case | Input | Required outcome |
|------|-------|------------------|
| EX-C01 | Grades A=3/B=2/C=0; chunks C-1,C-2,A-1 | Dedup C,A; Precision@2=0.5, Recall@2=0.5, MRR@2=0.5 and exact [graded nDCG fixture](reference-contracts.md#scoring-and-aggregation) |
| EX-C02 | Perfect ranking or successful empty result | nDCG=1 for ideal order; empty answerable ranking scores zero, precision denominator stays K |
| EX-C03 | Relevant parent absent from retrieved set | Recall denominator and IDCG still include it |
| EX-C04 | Wrong entity, wrong condition, or evidence value without table association | No substantive relevance/evidence credit |
| EX-C05 | No-answer query with contextual grade-1 documents | Ranking metrics N/A and excluded explicitly; no invented abstention success |
| EX-C06 | Unjudged returned parent or incomplete pooled qrels | Primary comparison rejected; exploratory known-positive scoring clearly labeled |
| EX-C07 | Changed canonical/source hash, chunk snapshot or query text | Fail immutable-reference validation before collection/scoring |
| EX-C08 | Foreign parent replaces a missing parent, keeping total counts equal | Exact set audit fails; count equality is not accepted |
| EX-C09 | Same parent has many overlapping chunks | One document credit; evidence union gives no repeated claim credit; token budget counts actual overlap |
| EX-C10 | Claim spans two chunks, or table labels are reordered | Require verified support set; missing/ambiguous mapping is not fabricated as negative |
| EX-C11 | 403, 429, timeout, malformed response or semantic fallback | Safe distinct failures, bounded retry, no secret logs, no false successful empty ranking |
| EX-C12 | Crash after request checkpoint or saved response | Resume reuses valid payloads, preserves unknown outcomes and counts possible duplicate billing |
| EX-C13 | Unreleased model-only qrels or paraphrase crossing a family split | Reference release rejected |
| EX-C14 | Chunk size changes from characters to tokens between DE/CU | New snapshot; comparison labeled combined ingestion policy, not extraction-only |
| EX-C15 | Export six native formats | Six isolated views with exact membership/hashes; no mixed-copy index and no changes to original content/run |
| EX-C16 | Whole-chunk 4,096-token budget cannot fit the next chunk | Stop prefix packing; record actual tokens, no gold-aware skip/truncation |
| EX-C17 | A request/system has unresolved failures | Locked aggregate marked incomplete; successful-only mean cannot declare a winner |
| EX-C18 | Paired methods with paraphrases/families/repeated views | Bootstrap resamples families with pairings intact; no pseudoreplicated significance |
| EX-C19 | Query/document vectors have different dimensions, model space or cache fingerprints | Fail preflight before mixed-space Search requests or comparison |
| EX-C20 | A stage exhausts its request/token budget with calls in flight | Stop new work, persist complete/unknown outcomes and require an audited explicit increase; do not reset counters on resume |
| EX-C21 | Two arm manifests differ by source content, artifact hash or query/reference release | Reject the paired comparison before collection/scoring |
| EX-C22 | CU uses one retrieval mode or embedding model while DE uses another | Reject the primary comparison; paired sensitivity must use identical common retrieval settings |
| EX-C23 | One arm has verified terminal extraction loss | Preserve all source queries/qrels/Recall denominators, include the loss in end-to-end results and report coverage; incomplete/unauthorized indexing instead blocks evaluation |

Use real SQLite/filesystems, public CLI/library interfaces and an in-memory SDK transport. Standard-metric conformance checks compare the selected provider with independent arithmetic, including gains and thresholds; do not validate merely that a library returned a number. Snapshot scans must handle continuation and source URI edge cases. Keep network forbidden in offline tests, and put paid capability/miniature indexing probes behind explicit authorization.

## Workload, release and rollback strategy

1. Complete E00-E03 using hand-computed metric fixtures and a freshly generated calibration-only batch of two families/twelve documents. No previous generation run is used.
2. Complete E04-E06 as an actual two-arm tracer: same new artifacts/reference, separate DE/CU indexes, common hybrid retrieval, paired scores and source/evidence coverage. Freeze saved response fixtures for future offline scorer work.
3. Generate the larger reference corpus within the protocol, inspect reference agreement and family-level CU-minus-DE variance, then set the confirmatory size/effect/latency policy before locked queries are measured.
4. Collect primary Study A first. Add Study B retrieval sensitivity or Study C matched views only after the pipeline contrast works; never let optional ranking/format studies replace the primary objective.
5. Publish reference/snapshot/config/result/scorer hashes, exact successful/failed denominators, metrics/intervals and limitations. Do not report synthetic-bank results as general organizational-document performance.

Generation, indexing, reference review and retrieval are separate checkpoints. Partial work remains unpublished/incomplete. Rollback means selecting the previous immutable release/snapshot; it never rewrites an old reference or deletes a production index.

Each implementation slice runs existing lint, strict typing, focused tests and applicable full offline coverage gates. The implementation adds IR-provider/tokenizer dependencies, reuses HTTPX and the Blob SDK, and updates the Windows dependency snapshot. Verify installed-wheel behavior and exclude operational corpora, gold labels and credentials from distributions.

## Execution status

The core E00-E06 software path is available for fresh generation, reviewed source truth, paired ingestion/snapshots, common hybrid collection and parent scoring. Human-reviewed pilot execution remains an operational gate. Relation-aware evidence metrics, additional ranking modes and matched views need separate implementation/review; no live results are asserted.
