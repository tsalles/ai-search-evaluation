# Development tuning of the DE and CU retrieval pipelines

Status: Completed development tuning; source-derived labels and results remain provisional

Date: 2026-10-30

## Conclusion

The strongest tested improvement was **source-name-aware hybrid retrieval with common semantic reranking**, while retaining the original native chunk sizes.

On the same development cohort, parent nDCG@10 increased from **0.6699 to 0.8304 for DE** and from **0.6776 to 0.8126 for CU**. Precision@1 increased from **0.77 to 0.85** and **0.71 to 0.75**, respectively. Wrong-family first results fell from 11 to zero for DE and from 14 to two for CU, out of 100 answerable utterances per arm.

Smaller native chunks improved the lighter hybrid configuration, but their final semantic combination did not exceed the simpler semantic configuration on either arm's nDCG@10 point estimate. Do not automatically promote the additional native changes.

These are **development-selection results**, not fresh held-out confirmation. The reference is automated and unreviewed. Parent relevance still does not establish that retrieved chunks support a complete answer.

## Scope and controls

- Reused the same 300 accepted sources, 50 families and native files from the [executed pilot](2026-10-29-example-retrieval-pilot.md). No new documents were authored.
- Selected profiles only on the previously unqueried development split: 10 families, 60 intents and 120 utterances. Fifty intents were answerable; ten were no-answer controls.
- Every profile returned all 240 required arm/query outcomes. Ranking metrics used the 100 answerable utterances per arm; no-answer scores remained not applicable.
- Executed eight shared retrieval profiles, three contextual/native candidates and one final semantic interaction check: **12 reports and 2,880 successful responses**.
- Kept source membership, query wording, qrels, embedding space and downstream settings common between the two arms within each comparison.
- Reused the identical 120 development query embeddings across profiles and derived variants. Existing validated query embeddings were inherited, not billed again.
- Kept the original main and smoke indexes, source artifacts, rankings and reports unchanged. No new test-split queries were collected.

The source run is `run-029b3f322ae44048acb296616e9e3c5a`. The tuning master is `experiment-c3b31cd074324101a8f1d7958ee27b6f`. This is reuse of one corpus, not four independent corpus replications.

Both arms used `text-embedding-3-large`, 3,072 dimensions, content-only lexical retrieval unless a profile explicitly enabled source fields, and a raw depth of 50 chunks. Vector retrieval used `k: 50`, approximate HNSW and cosine similarity. Semantic profiles required successful semantic responses; partial/fallback results were not accepted as alternate rankings.

## Implemented changes

### Common retrieval and source metadata

All tuning indexes contain source `title`, `account_names` and a source-context hash. Candidate names come from accepted canonical source fields and are checked against visible source text. Retrieval does not use relevance grades, required-claim IDs, hidden family IDs or gold target-document filters.

The `entity-semantic` profile uses:

| Setting | Executed value |
|---------|----------------|
| Lexical fields | `content`, `title`, `account_names` |
| Field weights | Content 1, title 2, account names 4 |
| Query-name handling | Soft phrase boosts of 4 for complete source names explicitly present in the query |
| Vector contribution | Weight 1, `k: 50` |
| Semantic input | Original plain query through `semanticQuery` |
| Semantic configuration | Source title, account-name keywords and content |
| Missing/partial semantic output | Fail explicitly; no silent RRF fallback |

This metadata is supplied consistently to both arms. It does not evaluate each extractor's ability to discover titles or names. A production system must provide comparable document metadata or an independently validated extraction/catalog process.

### Context and native chunk variants

| Case | DE native split | CU native semantic split | Title/name prefix in document embeddings | DE chunks | CU chunks |
|------|-----------------|--------------------------|-----------------------------------------|----------:|----------:|
| Ranking control | 2,000 characters, 200-character overlap | 2,000 tokens, zero overlap | No | 962 | 357 |
| Context | Same as ranking control | Same as ranking control | Yes | 962 | 357 |
| Native 1024 | 512 tokens, 64-token overlap | 1,024 tokens, zero overlap | Yes | 948 | 584 |
| Native 512 | 512 tokens, 128-token overlap | 512 tokens, zero overlap | Yes | 1,036 | 1,098 |

CU retained its own extraction and semantic chunking. No external Text Split stage was added after CU, and semantic overlap stayed zero.

Context enrichment preserved the original native chunk content and boundaries. It changed only source annotations and, when enabled, the document embedding input. The ranking and context cases were verified to have identical native text units in both arms.

The reprocessed ranking control also matched the original pilot's native text units, but some stored vector hashes were not bit-identical after re-embedding. Use the contemporaneous development control for these comparisons rather than treating reprocessing as perfectly deterministic.

## Frozen selection procedure

The [tuning plan](../../../evaluations/tuning/experiment-c3b31cd074324101a8f1d7958ee27b6f/tuning-plan.json) was recorded before the profile screen.

1. Evaluate all eight profiles on the same ranking-control indexes and development questions.
2. Select a common nonsemantic profile by highest mean arm nDCG@10, subject to each arm losing no more than 0.02 absolute Precision@1 or Recall@10 versus the original hybrid profile.
3. Use that same nonsemantic profile for all contextual/native candidates.
4. Select the highest eligible candidate under the same point-estimate guards versus its ranking control.
5. Apply the best eligible semantic profile from the initial screen only to the selected native candidate.

Higher mean Precision@1 and then the profile/case name break ties. These are exploratory point-estimate guardrails, not formal noninferiority tests. Both arms share the chosen profile; neither receives a separately optimized query policy.

The service remained on semantic ranker's free tier. Screening the two semantic profiles consumed 480 successful requests; the final interaction consumed 240, for a total of 720. No paid-tier or service-capacity upgrade was made.

## Shared profile screen

All values use the same ten development families. Precision uses binary relevance at grade 2 or above. Positive and negative judgments remain provisional.

| Profile | DE nDCG@10 | CU nDCG@10 | DE P@1 | CU P@1 | DE R@10 | CU R@10 | Guard eligible |
|---------|-----------:|-----------:|-------:|-------:|--------:|--------:|----------------|
| Hybrid control | 0.6699 | 0.6776 | 0.77 | 0.71 | 0.7458 | 0.8108 | Yes |
| BM25 only | 0.8209 | 0.8008 | 0.64 | 0.58 | 0.9867 | 0.9817 | No |
| Vector only | 0.4439 | 0.3273 | 0.49 | 0.29 | 0.5442 | 0.4608 | No |
| Hybrid, vector weight 0.5 | 0.7360 | 0.7181 | 0.80 | 0.76 | 0.8525 | 0.8192 | Yes |
| Hybrid, vector weight 2 | 0.6219 | 0.5914 | 0.74 | 0.64 | 0.6967 | 0.7158 | No |
| Entity-aware hybrid | 0.7170 | 0.7254 | 0.91 | 0.77 | 0.7458 | 0.8158 | Yes |
| Content-only semantic hybrid | 0.8090 | 0.7819 | 0.81 | 0.74 | 0.9458 | 0.9417 | Yes |
| Entity-aware semantic hybrid | **0.8304** | **0.8126** | **0.85** | **0.75** | **0.9633** | **0.9808** | Yes |

The selected nonsemantic profile was `hybrid-lexical`, with vector weight 0.5. The selected semantic profile was `entity-semantic`.

The screen supports the original diagnosis:

- Vector-only retrieval promoted a wrong-family document first for 45 DE and 60 CU answerable utterances, compared with 11 and 14 in the hybrid control.
- Entity-aware semantic retrieval reduced those counts to zero and two.
- BM25 retrieved most relevant parents by rank ten but degraded first-result precision, so the guardrails prevented its automatic selection.
- Entity-aware hybrid had the highest DE Precision@1, while semantic reranking provided the stronger nDCG@10/Recall@10 combination. There is no single profile that maximizes every metric.

## Recommended configuration at early cutoffs

The control below is the new development hybrid control, not the earlier 360-utterance test report. Recommended values use `entity-semantic` with the ranking-control native sizes.

| Metric | DE control | DE recommended | CU control | CU recommended |
|--------|-----------:|---------------:|-----------:|---------------:|
| Precision@1 | 0.7700 | 0.8500 | 0.7100 | 0.7500 |
| Precision@3 | 0.4667 | 0.6700 | 0.4567 | 0.6467 |
| Precision@5 | 0.3260 | 0.4800 | 0.3320 | 0.4700 |
| Recall@1 | 0.3617 | 0.3600 | 0.3142 | 0.2967 |
| Recall@3 | 0.6008 | 0.8208 | 0.5842 | 0.7983 |
| Recall@5 | 0.6850 | 0.9358 | 0.7000 | 0.9242 |
| nDCG@1 | 0.7557 | 0.8567 | 0.6943 | 0.7510 |
| nDCG@3 | 0.6521 | 0.8302 | 0.6227 | 0.7871 |
| nDCG@5 | 0.6412 | 0.8189 | 0.6283 | 0.7854 |
| nDCG@10 | 0.6699 | 0.8304 | 0.6776 | 0.8126 |
| Recall@10 | 0.7458 | 0.9633 | 0.8108 | 0.9808 |

Recall@1 did not improve. It divides each hit by that intent's total relevant-parent count, so its macro average can move differently from Precision@1 when different task types improve. Do not interpret the aggregate gains as improvement at every cutoff.

The recommended-profile nDCG@10 contrast, CU minus DE, was -0.0178 with a 95% paired family-bootstrap interval of [-0.0392, +0.0016]. This does not establish an arm winner.

Exploratory within-arm nDCG@10 improvements versus the development hybrid control were:

- DE: +0.1605, with a descriptive post-selection interval of [+0.1064, +0.2230].
- CU: +0.1350, with a descriptive post-selection interval of [+0.0839, +0.1864].

These intervals are not independent confirmation or multiplicity-adjusted inference.

## Native candidates and the final interaction

All native-stage candidates used the selected common `hybrid-lexical` profile.

| Case | DE nDCG@10 | CU nDCG@10 | DE P@1 | CU P@1 | Guard outcome |
|------|-----------:|-----------:|-------:|-------:|---------------|
| Ranking control | 0.7360 | 0.7181 | 0.80 | 0.76 | Eligible control |
| Context | 0.7603 | 0.7186 | 0.79 | 0.70 | Rejected: CU first-hit drop |
| Native 1024 | 0.7721 | 0.7413 | 0.81 | 0.71 | Rejected: CU first-hit drop |
| Native 512 | 0.7742 | 0.7595 | 0.79 | 0.74 | Selected native candidate |

Native 512 passed the inclusive two-percentage-point guard and had the highest eligible mean nDCG@10. Its final `entity-semantic` results were:

| Configuration | DE nDCG@10 | CU nDCG@10 | DE P@1 | CU P@1 | DE R@10 | CU R@10 |
|---------------|-----------:|-----------:|-------:|-------:|--------:|--------:|
| Ranking control plus entity-semantic | **0.8304** | **0.8126** | 0.85 | 0.75 | 0.9633 | 0.9808 |
| Native 512 plus entity-semantic | 0.8260 | 0.8079 | 0.82 | 0.79 | 0.9758 | 0.9575 |

Native 512 won the lighter hybrid stage but did not add a primary-metric gain after semantic reranking. Its primary differences versus the ranking semantic configuration were -0.0044 for DE and -0.0047 for CU; both descriptive paired intervals included zero.

It improved CU Precision@1 by four percentage points, but reduced DE Precision@1 by three points and CU Recall@10 by approximately 2.33 points. It also increased total indexed chunks from 1,319 to 2,134. Keep it as a tested alternative rather than declaring it universally better.

The [native-stage selection](../../../evaluations/tuning/experiment-c3b31cd074324101a8f1d7958ee27b6f/variant-selection.json) remains recorded separately from the [final recommendation](../../../evaluations/tuning/experiment-c3b31cd074324101a8f1d7958ee27b6f/final-recommendation.json); the earlier selection history was not rewritten.

## Evidence sufficiency diagnostic

A [label-blinded review packet](../../../evaluations/tuning/experiment-c3b31cd074324101a8f1d7958ee27b6f/evidence-review-draft.json) contains 20 development utterances from ten intents/families, balanced across the five answerable task types.

It provides 80 randomized contexts: the ranking and native-512 configurations, each with DE and CU. Each context uses the actual raw ranked chunk prefix and stops before the next whole chunk would exceed 4,096 tokens. Counts include title/account/citation wrappers and exclude the query, instructions and reference-answer review aid.

| Configuration | Mean whole chunks per sampled context | Mean context tokens |
|---------------|--------------------------------------:|--------------------:|
| Ranking DE | 7.90 | 3,807.85 |
| Ranking CU | 3.20 | 3,542.70 |
| Native-512 DE | 7.45 | 3,780.05 |
| Native-512 CU | 9.25 | 3,845.75 |

All 80 budgets and prefix choices were independently checked. No chunks were selected using relevance labels or skipped to optimize gold coverage. Explicit case/arm labels are hidden; intrinsic output styles can still reveal clues. The unblinding key is separate from the review packet.

**All judgments are unfilled and human review is pending.** These exposure measurements are not evidence-quality scores. Chunk support, answer correctness and sufficiency metrics remain `not_evaluated`.

## Usage, permissions and verification

| Application-logged usage | Actual | Frozen combined cap |
|--------------------------|-------:|--------------------:|
| Search attempts | 3,094 | 4,000 |
| Embedding requests | 435 | 1,650 |
| Administration attempts | 1,177 | 2,000 |
| Blob attempts | 4,887 | 7,200 |
| Observed embedding tokens | 2,619,577 | 6,020,000 |

Embedding requests comprised 120 shared query requests and 315 contextual document batches. There were no unknown application embedding-usage outcomes and no new authoring calls. Indexer-driven embeddings and CU processing incur separate charges that the Search API does not report; no total monetary cost is asserted.

Contextual variants first obtained native indexer embeddings and then performed the controlled contextual re-embedding. That experimental scaffolding performs redundant vectorization; a production contextual pipeline should construct its embedding context before its final embedding step.

All eight tuning indexes represented all 300 sources, without missing sources, indexer errors or warnings. Source, native-file, Blob-byte/ETag, resource, execution, chunk-text, metadata and vector audits passed.

- Independently verified 48,000 per-query metric values and 240 paired report intervals to tolerance `1e-12`.
- Verified the profile/case selection inputs and all 80 diagnostic context budgets/prefixes.
- Passed the complete 168-case evaluation regression suite and additional interrupted-fork/CLI checks. Repository lint, strict typing for 76 source modules, and source/wheel builds passed.
- Used temporary document-writer access only on the eight new indexes; all eight grants were removed after snapshots. Scoped reader access remains.
- Kept semantic billing at `free`, with one Standard replica and one partition.
- Preserved original index counts: manual indexes 37/14 records, smoke indexes 29/12 chunks, original main indexes 962/357 chunks.
- Verified eight original main artifact hashes and identical offline rescoring of the original main and smoke reports.

Source-context writes retain successful batch caches across Search visibility delays. Verification handles the declared single-precision storage representation, including signed zero, while post-snapshot text/vector/metadata hashes remain strict. None of these fixes relaxed evidence labels or rewrote accepted source content.

## Recommendation and reproducibility

Use the ranking variant's `entity-semantic` profile as the current primary-metric candidate:

- DE index: `docgen-eval-d7958ee27b6f-de-index`.
- CU index: `docgen-eval-d7958ee27b6f-cu-index`.
- Retain DE's 2,000-character/200-overlap split and CU's native 2,000-token/zero-overlap semantic chunks.
- Retain common source metadata, soft query-name boosts and common semantic reranking.

For a lower-cost nonsemantic alternative, `hybrid-lexical` improved both arms while retaining the early-rank guards. Do not silently substitute it for semantic results when quotas or availability fail.

The original production/manual and experiment resources were not modified to adopt this candidate. This report recommends a tested versioned configuration; it is not an unreviewed production deployment.

Evidence and reproducibility:

- [Consolidated tuning results](../../../evaluations/tuning/experiment-c3b31cd074324101a8f1d7958ee27b6f/tuning-results.json)
- [Recommended development report](../../../evaluations/tuning/experiment-c3b31cd074324101a8f1d7958ee27b6f/report-development-entity-semantic.json)
- [Profile selection](../../../evaluations/tuning/experiment-c3b31cd074324101a8f1d7958ee27b6f/profile-selection.json)
- [Independent numerical verification](../../../evaluations/tuning/experiment-c3b31cd074324101a8f1d7958ee27b6f/tuning-numerical-verification.json)
- [Live integrity, budget and permission verification](../../../evaluations/tuning/experiment-c3b31cd074324101a8f1d7958ee27b6f/tuning-live-verification.json)
- [Independent evidence-packet verification](../../../evaluations/tuning/experiment-c3b31cd074324101a8f1d7958ee27b6f/evidence-packet-independent-verification.json)
- [Versioned tuning commands](../usage.md#versioned-development-tuning)

The generated evidence is gitignored and local; this Markdown file alone does not distribute it. Executed code includes uncommitted changes, so commit `0c870e7` alone cannot reproduce the tuning implementation.

Next, review the provisional source judgments and blinded contexts, freeze the selected configuration, and assess it on a prospectively untouched validation cohort or fresh families. Neither repeated use of the already inspected test split nor development-selection confidence intervals provide confirmatory evidence.
