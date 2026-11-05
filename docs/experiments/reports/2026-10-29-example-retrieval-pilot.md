# Document Extraction versus Content Understanding: executed retrieval pilot

Status: Completed exploratory pilot; reference labels and results are provisional

Report date: 2026-10-29, UTC-03:00

## Executive summary

Both pipelines indexed the same 300 freshly generated documents successfully. We evaluated 360 held-out query utterances from 30 test families, obtaining all 720 paired responses.

Content Understanding (CU) achieved higher point estimates for parent-document nDCG@10, Precision@10 and Recall@10. The primary nDCG@10 difference was **+0.0190**, with a 95% paired family-bootstrap interval of **[-0.0217, +0.0588]**. This interval includes zero, so the primary result does not establish a clear winner.

The reference used automated source-derived checks and the explicit `automated_pilot` release policy. No human relevance review or human query authorship was certified. These findings are exploratory and apply to the generated corpus and executed retrieval configuration.

**This experiment measured parent-document discovery. It did not measure chunk answer support, answer correctness, or evidence sufficiency at equal context-token cost.**

## Experiment identity and evidence

| Item | Value |
|------|-------|
| Experiment ID | `experiment-0b7b09aa7db14d038a627abe555fe73b` |
| Fresh source run | `run-029b3f322ae44048acb296616e9e3c5a` |
| Seed | `20261029` |
| Search endpoint | `https://ai-search-example.search.windows.net` |
| Baseline index | `docgen-eval-7abe555fe73b-de-index` |
| Challenger index | `docgen-eval-7abe555fe73b-cu-index` |
| Evaluation split | `test` |
| Reference assurance | `provisional`, `automated_pilot`; `human_review_certified: false` |
| Final result verification | `2026-10-30T00:51:28Z`, equivalent to 2026-10-29 21:51:28 UTC-03:00 |

Primary evidence:

- [Machine-readable results](../../../evaluations/main/experiment-0b7b09aa7db14d038a627abe555fe73b/report-test.json)
- [Supplemental Precision, Recall and nDCG at 1, 3 and 5](../../../evaluations/main/experiment-0b7b09aa7db14d038a627abe555fe73b/report-test-cutoffs-1-3-5.json)
- [Frozen protocol](../../../evaluations/main/experiment-0b7b09aa7db14d038a627abe555fe73b/protocol.json) and [experiment plan](../../../evaluations/main/experiment-0b7b09aa7db14d038a627abe555fe73b/experiment-plan.json)
- [Sealed reference](../../../evaluations/main/experiment-0b7b09aa7db14d038a627abe555fe73b/reference.json) and [exhaustive TREC qrels](../../../evaluations/main/experiment-0b7b09aa7db14d038a627abe555fe73b/qrels.trec)
- [Independent result verification](../../../evaluations/main/experiment-0b7b09aa7db14d038a627abe555fe73b/live-pilot-verification.json)
- [Published corpus](../../../evaluations/main/experiment-0b7b09aa7db14d038a627abe555fe73b/run-029b3f322ae44048acb296616e9e3c5a/corpus)

These evidence links resolve in the local experiment workspace. The generated artifacts are gitignored; distributing this Markdown file alone does not distribute its underlying dataset or results.

## Objective and treatment

The objective was to compare two combined extraction and chunking policies under common downstream retrieval controls:

| Setting | Baseline: DE + Split | Challenger: CU |
|---------|----------------------|----------------|
| Extraction | Document Extraction skill, default parsing, content and metadata, no image extraction | Content Understanding skill |
| Chunking | Text Split, pages mode | Native semantic chunking |
| Maximum chunk length | 2,000 characters | 2,000 tokens |
| Overlap | 200 characters | Zero |
| Source membership | Same 300 native files | Same 300 native files |

The different chunk-size units are intentional treatment settings. This is a comparison of the complete policies, not an extraction-only experiment or an equal-sized-chunk comparison.

Shared controls:

- Embeddings: `text-embedding-3-large`, 3,072 dimensions, using the same deployment for indexed content and query vectors.
- Content analyzer: `pt-Br.microsoft` in both indexes.
- Retrieval: content-only lexical search plus vector search, with simple query syntax and no query-time semantic reranking.
- Raw retrieval depth: `top: 50`; vector `k: 50`, weight `1.0`, approximate HNSW, cosine similarity, `vectorFilterMode: preFilter`.
- HNSW settings: `m: 4`, `efConstruction: 400`, `efSearch: 500`.
- Each exact query used one shared cached embedding across both arms. Requests required 100% Search coverage.
- Query API: `2026-04-01`; both skillset definitions used `2026-05-01-preview`.
- Dedicated resource names and a unique Blob prefix isolated this run from the earlier smoke test and manually configured indexes.

## Corpus and reference dataset

The generator created 50 fictional banking-account families with six related documents per family. Language was Portuguese, locale `pt-BR`. Each accepted source was assigned one native format.

| Dimension | Executed allocation |
|-----------|---------------------|
| Total documents | 300 |
| Formats | 50 PDF, 50 DOCX, 50 XLSX, 50 PPTX, 50 HTML, 50 Markdown |
| Logical complexity | 90 simple, 135 moderate, 75 complex |
| Length bands | 90 short, 150 medium, 60 long |
| Native layouts | Seeded per-format layouts; all source and format assignments remained frozen |
| Source-derived reference | 400 grounded claims, 1,437 evidence anchors |
| Full query dataset | 300 intents, 600 utterances, two utterances per intent |
| Qrels | 180,000 rows: 600 utterances by 300 documents |

The length acceptance policy allowed 5% grace around the nominal bands: 190-420 words for short, 475-945 for medium, and 950-1,680 for long.

| Split | Families | Documents | Intents | Utterances | Queried in this evaluation |
|-------|---------:|----------:|--------:|-----------:|---------------------------|
| Calibration | 10 | 60 | 60 | 120 | No |
| Development | 10 | 60 | 60 | 120 | No |
| Test | 30 | 180 | 180 | 360 | Yes |
| Total | 50 | 300 | 300 | 600 | Test only |

Both indexes contained all 300 documents, including calibration and development sources as distractors. Family membership kept related documents and query variants in one split.

The test set contained 150 answerable intents and 30 no-answer intents. All 360 utterances were retrieved against both arms; the 300 answerable utterances contributed to ranking metrics. The remaining 60 had ranking metrics marked not applicable. Search-result presence was not treated as an abstention decision.

Reference construction used accepted canonical source facts and paragraph, list and table anchors, independently of either extractor. Within-family parent grades reflected required-claim coverage; documents outside the explicitly named synthetic family received zero relevance under the scope assumption. Human review did not certify the semantic completeness of those labels. Template questions asked about stated monetary amounts and age requirements without adding unsupported billing cadence or minimum-age qualifiers.

## Scoring and statistical method

1. Retain the service's original top-50 chunk order.
2. Map each chunk to its canonical source document.
3. Collapse repeated parents by first occurrence, then apply cutoffs. The original evaluation used 5, 10 and 20; the offline supplement adds 1 and 3 for Precision, Recall and nDCG.
4. Compute graded nDCG with grades 0-3 and gains 0, 1, 3 and 7. Precision, Recall and MRR use binary relevance at grade 2 or above.
5. Average utterances within an intent, intents within a family, and families equally.
6. Estimate CU minus DE with 10,000 seeded, paired family-bootstrap resamples and percentile 95% intervals.

The primary metric was parent nDCG@10. The independent resampling units were **30 test families**, not 720 responses. Precision used the requested cutoff as its denominator; Recall and ideal DCG retained all source positives. Metric implementation: `ir_measures 0.4.3`, explicitly using `pytrec_eval` through `pytrec-eval-terrier 0.5.11`.

The additional cutoffs were requested after the executed evaluation and are descriptive post-hoc analyses. They reuse the same frozen rankings, qrels, parent deduplication, family aggregation and 10,000-resample bootstrap. The supplemental @5 values exactly match the original per-query scores and paired estimates. No retrieval or model calls were repeated, and the original sealed results remain unchanged.

## Retrieval results

Values below are rounded to four decimal places. Positive differences favor CU.

| Metric | DE + Split | CU | CU minus DE | 95% paired interval |
|--------|-----------:|---:|------------:|---------------------|
| **nDCG@10, primary** | **0.6118** | **0.6308** | **+0.0190** | **[-0.0217, +0.0588]** |
| nDCG@1 | 0.6886 | 0.6819 | -0.0067 | [-0.0781, +0.0676] |
| nDCG@3 | 0.5802 | 0.5750 | -0.0051 | [-0.0535, +0.0426] |
| nDCG@5 | 0.5753 | 0.5770 | +0.0016 | [-0.0445, +0.0461] |
| nDCG@20 | 0.6174 | 0.6384 | +0.0211 | [-0.0207, +0.0613] |
| Precision@1 | 0.6900 | 0.6867 | -0.0033 | [-0.0767, +0.0733] |
| Precision@3 | 0.4078 | 0.4111 | +0.0033 | [-0.0333, +0.0367] |
| Precision@5 | 0.2913 | 0.2980 | +0.0067 | [-0.0153, +0.0280] |
| Precision@10 | 0.1690 | 0.1810 | +0.0120 | [+0.0020, +0.0223] |
| Precision@20 | 0.0865 | 0.0928 | +0.0063 | [+0.0010, +0.0115] |
| Recall@1 | 0.3086 | 0.2942 | -0.0144 | [-0.0569, +0.0292] |
| Recall@3 | 0.5181 | 0.5225 | +0.0044 | [-0.0497, +0.0533] |
| Recall@5 | 0.6064 | 0.6194 | +0.0131 | [-0.0403, +0.0650] |
| Recall@10 | 0.6892 | 0.7439 | +0.0547 | [+0.0078, +0.1017] |
| Recall@20 | 0.7028 | 0.7583 | +0.0556 | [+0.0050, +0.1036] |
| MRR@5 | 0.7764 | 0.7741 | -0.0024 | [-0.0558, +0.0506] |
| MRR@10 | 0.7797 | 0.7816 | +0.0019 | [-0.0493, +0.0529] |
| MRR@20 | 0.7799 | 0.7819 | +0.0020 | [-0.0493, +0.0542] |

Interpretation:

- The primary estimate favors CU, but its interval spans both a small disadvantage and a larger advantage. The study does not establish CU superiority on nDCG@10.
- At @1, DE has slightly higher point estimates for all three requested metrics; at @3 the direction is mixed, and at @5 CU has slightly higher estimates. All nine @1/@3/@5 difference intervals include zero, so these early-rank results do not establish a clear winner.
- CU Recall@10 was 5.47 percentage points higher. Some secondary intervals exclude zero, but they are exploratory and were not adjusted for multiple comparisons.
- The reference had an average of 2.6 relevant parents per answerable intent. Consequently, mean attainable Precision@10 was 0.2600 even for ideal rankings. These Precision values are not answer-accuracy percentages.
- Format and structure slices in the JSON report are descriptive and can overlap. They do not isolate format effects using matched content.

## Ingestion, latency and usage

| Observation | DE + Split | CU |
|-------------|-----------:|---:|
| Sources processed | 300 | 300 |
| Sources represented in frozen chunks | 300 | 300 |
| Missing sources | 0 | 0 |
| Failed items, indexer errors, warnings | 0, 0, 0 | 0, 0, 0 |
| Frozen chunks | 962 | 357 |
| Initial indexer execution duration | 78.4 seconds | 88.8 seconds |
| Mean successful query-attempt latency | 257.0 ms | 231.0 ms |
| Median successful query-attempt latency | 250.0 ms | 219.0 ms |
| 95th-percentile successful query-attempt latency | 297.0 ms | 250.8 ms |

Indexer execution ran on 2026-10-30 UTC, starting at approximately 00:21:47, equivalent to 2026-10-29 21:21:47 UTC-03:00. Query latency includes authentication in successful transport attempts and excludes separate query embedding time. These single-run timings are operational observations, not controlled throughput or latency benchmarks.

| Usage item | Observed value |
|------------|----------------|
| Authoring deployment | `gpt-6-luna` |
| Authoring calls | 423 |
| Observed authoring tokens | 2,418,628 |
| Authoring usage uncertainty | One earlier timed-out request had unknown usage; total billed tokens are unknown |
| Original global authoring ceilings | 2,700 attempts; 3,000,000 observed tokens; neither increased |
| Shared query embeddings | 360 requests; 8,048 observed tokens; zero unknown embedding usage |
| Successful paired retrieval responses | 720 |
| Cumulative attempts at collection seal | 734 Search, 360 embedding, 129 administration, 1,373 Blob |
| Cumulative attempts after final verification | 738 Search, 360 embedding, 143 administration, 1,375 Blob |
| Monetary cost | Not calculated; Azure indexing cost was not returned by the Search API |

Attempt totals include scans, preflight checks, retries and audits, rather than only the 720 experimental searches. Three failed Blob reads were retained in accounting before successful resume.

## Recovery and verification

The initial authoring pass accepted 273 sources. Audited per-item retry limits increased from 3 to 5 and then 10 to finish difficult table layouts. Global request/token ceilings and quality thresholds stayed unchanged. Resume preserved rejection feedback and every previously accepted canonical hash.

All 300 sources were eventually accepted. One six-column PowerPoint table needed content-aware column widths to accommodate a long header at the existing fourteen-point font size. The repair changed no canonical text, preserved the other 299 native files byte-for-byte, and made no new model calls. Native geometry and readback checks passed; the three affected slides were also inspected through local read-only PowerPoint exports.

Execution verification established:

- Exact source, format, length and complexity quotas and valid native publication.
- Actual uploaded-byte SHA-256 verification under ETag conditions, followed by matching Blob inventories.
- Complete source membership, finite correctly dimensioned vectors, and frozen text/vector hashes in both snapshots.
- Resource, Blob, chunk and execution stability before and after collection and at final verification.
- Independent recomputation of 7,200 per-query metric values, paired aggregation and all 12 bootstrap intervals to tolerance `1e-12`.
- Additional independent verification of 5,400 supplemental per-query Precision, Recall and nDCG values at @1/@3/@5 and all nine corresponding bootstrap intervals. The original result, reference, qrels, rankings, snapshots and TREC-run file hashes remained unchanged.
- Agreement between exported TREC rankings and the JSON report; identical offline rescoring without new requests.
- Passing affected suites: 49 provisional-policy/reference/CLI cases, 205 authoring/retry/contract cases, and 242 rendering/publication cases. These are separate test-run counts, not a combined full-suite result.
- Passing repository lint, strict typing for 73 source modules, and source/wheel builds. A new complete repository test run or thousand-document scale run was not part of this pilot verification.

The original indexes remained at 37 records in `my-index` and 14 in `my-index-kw`. The completed smoke indexes remained at 29 DE chunks and 12 CU chunks. The larger run did not modify those resources.

## Post-execution chunk-size diagnostic

A separate read-only analysis of the saved rankings examined the implications of comparing different native chunk sizes. It introduced no new relevance labels or cloud requests.

| Diagnostic | DE + Split | CU |
|------------|-----------:|---:|
| Median tokens per indexed chunk | 483 | 1,193 |
| Average content tokens in the top 10 raw chunks | 4,833.0 | 10,158.3 |
| Average distinct parents in the top 50 raw chunks | 37.25 | 47.91 |
| Average whole chunks fitting in a 4,096-token prefix | 8.01 | 3.68 |
| Average content tokens used by that prefix | 3,859.8 | 3,515.2 |

Token measurements used `cl100k_base` and counted chunk content only, excluding metadata, separators and prompt overhead. The illustrative prefix rule stopped when the next whole ranked chunk would exceed 4,096 tokens; it did not skip or select chunks using relevance labels.

CU's top ten chunks contained approximately 2.1 times as much text. Native chunking is part of the treatment, so this observation does not invalidate the pipeline comparison. It does limit interpretation: fixed chunk depth does not represent equal context cost, and parent deduplication can credit a document even when the retrieved chunk omits the required answer evidence.

No evidence-coverage or answer-sufficiency score was computed for that token budget. The main report correctly records chunk evidence metrics as `not_evaluated`.

## Earlier smoke run

Before the larger pilot, an operational smoke used 12 fresh documents in two families, 24 utterances and 48 paired responses. Both arms covered every source without indexer errors. It produced 29 DE chunks and 12 CU chunks; parent nDCG@10 was 0.8767 for DE and 0.8966 for CU.

The smoke reference was also provisional. Its two-family sample and different corpus composition support operational validation, not pooling with the larger pilot or claiming an independent confirmatory replication. See the [smoke results](../../../evaluations/smoke/experiment-f85781f93f28490e83f1dec325b69b74/report-test.json).

## Limitations and recommended follow-up

1. **Unreviewed reference:** automated claim coverage and scope checks do not certify every query's meaning, every table relation or every negative judgment.
2. **Synthetic scope:** fifty related banking-account families do not establish performance on heterogeneous organizational documents. Explicit synthetic entity names also simplify scope identification.
3. **Uncertainty:** thirty test families support a larger exploratory comparison than the smoke, but the primary interval still includes zero.
4. **Combined treatment:** extraction behavior, chunk boundaries, chunk length and overlap changed together; the result cannot attribute an effect to extraction alone.
5. **Ranking-unit limits:** parent discovery does not establish chunk sufficiency. No generated-answer correctness, chunk entailment, abstention behavior or equal-token evidence quality was evaluated.
6. **Single execution:** one corpus seed and one retrieval configuration do not characterize robustness across seeds, model/service changes or operational loads. Secondary comparisons were not multiplicity-adjusted.
7. **Reproducibility:** artifacts capture protocol and observed snapshot identities, but the executed code included uncommitted changes. Commit `0c870e7` alone does not reproduce this run's implementation.

Recommended next step: preserve these results and perform a small blinded evidence-sufficiency diagnostic using the same questions and a predeclared context budget. Judge complete, correct, qualified answer support from the actual retrieved context before implementing exhaustive chunk labels. Treat that follow-up as exploratory; register rules and obtain independent reference review before making confirmatory claims.

The present conclusion is **a directional CU advantage in parent recall, with no established primary-metric winner and no measured chunk-answer-quality advantage**.
