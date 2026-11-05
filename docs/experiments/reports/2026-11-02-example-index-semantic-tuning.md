# Example index and semantic tuning

Date: 2026-11-02, local UTC-03:00

Status: Executed within the existing free semantic plan; quota-limited semantic coverage; provisional references and exploratory repeated-data analysis

## Recommendation

**Keep DE plus Text Split as the practical default for this native-text corpus. Set BM25 `k1` to 2.4, retain `b` at 0.75 and retain `pt-Br.microsoft`. Use content-only BM25 plus native semantic reranking when semantic allowance is available.**

Use ordinary BM25 as an explicitly selected quota-independent option today. The service has rejected additional semantic queries with HTTP 402. No paid billing upgrade was authorized or performed; an application must not silently substitute BM25 for a failed semantic request.

| Setting | DE | CU challenger |
|---|---|---|
| Native chunking | 2,000 characters, 200-character overlap | 1,024 tokens, zero overlap |
| Content analyzer | `pt-Br.microsoft` | `pt-Br.microsoft` |
| BM25 | `k1=2.4`, `b=0.75` | `k1=2.4`, `b=0.75` |
| Quality-first query profile | `semantic-bm25` | `semantic-bm25` |
| Current quota-independent profile | `bm25` | `bm25` |
| HNSW | `m=4`, `efConstruction=400`, `efSearch=500` | Same |

The index changes improved lexical nDCG@10 by **0.027076 for DE** and **0.026234 for CU** on the 93-family comparison cohort. Both family-bootstrap intervals exclude zero, but these reused families do not supply independent confirmation.

On the 33-family semantic development cohort, selected BM25 plus semantic scored **0.816919 for DE** and **0.804567 for CU**. CU minus DE was **-0.012352**, interval **[-0.020244, -0.005069]**. This is a development result after policy selection, not a universal extractor ranking or a new confirmatory semantic test.

## Executed scope and constraints

- Reused the same 996 immutable native files from 166 scenario families, with 166 files per format globally. Each family has six distinct source documents; it does not necessarily contain every format.
- Indexed all sources once per arm into two isolated comparison indexes. DE produced 3,204 chunks; CU produced 1,932. Both indexers finished without errors or warnings.
- Completed 12 BM25 combinations and three analyzer choices on all 33 development families, comprising 396 utterances and 792 paired arm/question outcomes per policy.
- Completed six nonsemantic candidate-generation policies and four native semantic policies on that cohort.
- Completed default lexical, tuned lexical and selected-policy L1 comparisons on all 93 original calibration families, comprising 1,116 utterances per policy.
- Retained 26,496 complete arm/question outcomes across 28 report cells. Exact repeated requests reused confirmed responses; 22,680 distinct query fingerprints were independently verified.
- All existing families had already supplied evaluated results in earlier studies. These comparisons are exploratory, including the cohort still named `calibration`.

The original semantic design included two k100 semantic candidates and three semantic comparisons on the 93-family cohort. Azure rejected the first k100 semantic cell with:

> Free Query Semantic Usage exceeded for the month.

Those cells remain unexecuted. The stopping amendment retained every complete semantic cell, preserved rejected requests and did not exclude candidates based on their scores. A paid-plan decision was unavailable, so billing remained free. The report does not replace missing semantic comparisons with nonsemantic results.

Earlier application dispatch totals had suggested that semantic execution was already blocked. A bounded native request actually succeeded, so execution continued until the service itself rejected further requests. Application counters are not an authoritative remaining-allowance meter.

## Isolation and raw-document provenance

- All features came from each arm's own Search skillset. Uploads contained raw bytes and MIME types, with no custom Blob metadata.
- Analyzer comparison fields received exact copies of the same native chunk text inside the index projection. They supplied no titles, canonical account names, outside annotations or new information.
- Snapshot audits required `content_lucene` and `content_standard` to equal the original `content`. Semantic reranking consumed `content` once.
- BM25 stages conditionally changed only `k1` and `b` on the two owned indexes. Append-only intents, prior ETags and fresh definition readbacks bound every stage.
- Native indexer execution and other resource definitions stayed pinned. Complete native text/vector and raw-source-version checks bracketed the study.
- Both arms reused confirmed, byte-identical question vectors. The study issued no new query embeddings and no client document-field or document-vector writes.
- Technical IDs remained plumbing rather than relevance features. Retrieval used original question text, raw depth 50, coverage 100 and explicit semantic failure handling.

## BM25 and analyzer development results

The same BM25 grid ran in each arm. Selection maximized parent nDCG@10 with Precision@1 and Recall@10 loss guards of 0.02 relative to the control. Numerical ties within 1e-12 retained the control, then declared order.

| k1 | b | DE nDCG@10 | CU nDCG@10 |
|---:|---:|---:|---:|
| 0.6 | 0.00 | 0.726997 | 0.739425 |
| 0.6 | 0.50 | 0.720258 | 0.732764 |
| 0.6 | 0.75 | 0.717478 | 0.729009 |
| 0.6 | 1.00 | 0.709408 | 0.722356 |
| 1.2 | 0.00 | 0.754937 | 0.764374 |
| 1.2 | 0.50 | 0.746975 | 0.763924 |
| 1.2 | 0.75 | 0.742840 | 0.759741 |
| 1.2 | 1.00 | 0.737740 | 0.752021 |
| 2.4 | 0.00 | 0.753297 | 0.776826 |
| 2.4 | 0.50 | 0.759615 | 0.785041 |
| 2.4 | 0.75 | 0.761859 | 0.789796 |
| 2.4 | 1.00 | 0.760071 | 0.783004 |

Both arms nominated `k1=2.4`, `b=0.75`. Analyzers were then compared at those settings without re-extracting documents.

| Analyzer | DE nDCG@10 | CU nDCG@10 |
|---|---:|---:|
| `pt-Br.microsoft` | 0.761859 | 0.789796 |
| `pt-Br.lucene` | 0.697377 | 0.768203 |
| `standard.lucene` | 0.682188 | 0.763569 |

Microsoft remained selected in both arms. Generic `pt.lucene` was rejected during schema validation; its failed namespace and original creation intent were preserved. Corrected empty schemas were accepted before corpus preparation continued.

## Lexical comparison on 93 families

These policies query the same frozen native chunks and differ only in BM25 settings. Both use the Microsoft analyzer. Metrics deduplicate parents before each cutoff; binary relevance is grade at least 2, and nDCG uses gains 0/1/3/7. Paraphrases average within intents, intents within families, then families.

| Metric | Default DE | Default CU | Tuned DE | Tuned CU |
|---|---:|---:|---:|---:|
| Precision@1 | 0.569892 | 0.564516 | 0.608602 | 0.588172 |
| Precision@3 | 0.483154 | 0.486380 | 0.499642 | 0.498566 |
| Precision@5 | 0.394409 | 0.396129 | 0.402796 | 0.412258 |
| Precision@10 | 0.238602 | 0.241505 | 0.242473 | 0.247419 |
| Precision@20 | 0.127957 | 0.128387 | 0.128333 | 0.128871 |
| Recall@1 | 0.240412 | 0.234319 | 0.253584 | 0.241756 |
| Recall@3 | 0.591756 | 0.591398 | 0.598925 | 0.600806 |
| Recall@5 | 0.774910 | 0.782258 | 0.786470 | 0.805914 |
| Recall@10 | 0.918190 | 0.933423 | 0.935663 | 0.953405 |
| Recall@20 | 0.982616 | 0.989158 | 0.985215 | 0.992204 |
| nDCG@1 | 0.571531 | 0.565950 | 0.617102 | 0.594470 |
| nDCG@3 | 0.616670 | 0.616722 | 0.640235 | 0.636642 |
| nDCG@5 | 0.667269 | 0.672203 | 0.691635 | 0.699563 |
| nDCG@10 | 0.741572 | 0.748847 | 0.768648 | 0.775082 |
| nDCG@20 | 0.773050 | 0.776651 | 0.793515 | 0.796149 |

| Within-arm index effect | nDCG@10 gain | Paired family-bootstrap 95% interval |
|---|---:|---|
| DE tuned minus default | +0.027076 | [0.018081, 0.036183] |
| CU tuned minus default | +0.026234 | [0.018694, 0.033869] |

For tuned lexical policies, CU minus DE nDCG@10 was **+0.006434**, interval **[-0.011493, +0.023859]**. CU had higher Recall@10, while DE had higher Precision@1. These results do not establish equivalence.

The selected semantic policy's matched L1 policy was also BM25, so its third comparison cell reused the identical tuned lexical requests and produced identical metrics. It is not another independent replication.

## Native semantic tuning on 33 families

All completed semantic candidates used the selected index settings. Hybrid k50 policies varied vector weight; lexical semantic used no query vectors.

| Policy | DE nDCG@10 | CU nDCG@10 | DE P@1 | CU P@1 | DE R@10 | CU R@10 |
|---|---:|---:|---:|---:|---:|---:|
| BM25 plus semantic | 0.816919 | 0.804567 | 0.830303 | 0.787879 | 0.975253 | 0.976010 |
| Hybrid plus semantic, weight 0.25 | 0.812656 | 0.802202 | 0.827273 | 0.790909 | 0.974242 | 0.970455 |
| Hybrid plus semantic, weight 0.5 | 0.809230 | 0.801406 | 0.821212 | 0.793939 | 0.971212 | 0.969444 |
| Hybrid plus semantic, weight 1 | 0.804310 | 0.804159 | 0.824242 | 0.796970 | 0.958838 | 0.970707 |

BM25 plus semantic passed the loss guards and achieved the highest nDCG@10 among completed policies in both arms. The tested k100 nonsemantic controls remain available in the evidence; they cannot establish k100 semantic quality.

The next table compares matched BM25 inputs before and after native semantic reranking on this same 33-family cohort. Do not compare these point estimates directly with the preceding 93-family table.

| Metric | BM25 DE | BM25 CU | Semantic DE | Semantic CU |
|---|---:|---:|---:|---:|
| Precision@1 | 0.566667 | 0.621212 | 0.830303 | 0.787879 |
| Precision@3 | 0.488889 | 0.508081 | 0.647475 | 0.635354 |
| Precision@5 | 0.399394 | 0.413939 | 0.469091 | 0.472727 |
| Precision@10 | 0.244545 | 0.247273 | 0.253333 | 0.253030 |
| Precision@20 | 0.126970 | 0.128182 | 0.128182 | 0.129091 |
| Recall@1 | 0.222475 | 0.255051 | 0.350505 | 0.321212 |
| Recall@3 | 0.580556 | 0.612626 | 0.788636 | 0.779293 |
| Recall@5 | 0.778030 | 0.807576 | 0.915657 | 0.921970 |
| Recall@10 | 0.939394 | 0.951515 | 0.975253 | 0.976010 |
| Recall@20 | 0.975758 | 0.987879 | 0.986869 | 0.993434 |
| nDCG@1 | 0.579365 | 0.624820 | 0.824675 | 0.781530 |
| nDCG@3 | 0.622199 | 0.654706 | 0.795436 | 0.778850 |
| nDCG@5 | 0.681255 | 0.713809 | 0.791731 | 0.781247 |
| nDCG@10 | 0.761859 | 0.789796 | 0.816919 | 0.804567 |
| nDCG@20 | 0.781228 | 0.807557 | 0.824854 | 0.814470 |

| Development contrast | Arm | nDCG@10 gain | Family-bootstrap 95% interval |
|---|---|---:|---|
| Semantic versus matched BM25 | DE | +0.055060 | [0.020735, 0.094342] |
| Semantic versus matched BM25 | CU | +0.014771 | [-0.020886, 0.051799] |
| Semantic BM25 versus semantic hybrid weight 1 | DE | +0.012609 | [0.006233, 0.019103] |
| Semantic BM25 versus semantic hybrid weight 1 | CU | +0.000408 | [-0.007155, 0.008312] |

Policy selection and these semantic estimates use the same development data. Intervals use 10,000 paired family resamples, are exploratory and are not adjusted for multiple comparisons or selection. No equivalence margin or equivalence test was predeclared.

## HNSW accuracy and operational characteristics

An exhaustive-KNN control ran for every development utterance on the actual comparison indexes. It measures neighbor recovery rather than semantic relevance.

| Arm | Questions | Mean top-50 neighbor overlap | Minimum overlap | Identical top-50 sets |
|---|---:|---:|---:|---:|
| DE | 396 | 99.792929% | 98% | 355 |
| CU | 396 | 99.893939% | 96% | 377 |

Both means exceeded the predeclared 99% graph-expansion threshold. HNSW was therefore retained rather than expanding `m` or `efConstruction`. This is not a claim of perfect ANN retrieval or sufficient answer evidence; a larger corpus needs a fresh accuracy/performance audit.

| Comparison index | Chunks | Index storage MiB | Vector index MiB |
|---|---:|---:|---:|
| DE | 3,204 | 165.04 | 37.72 |
| CU | 1,932 | 114.66 | 22.75 |

These storage figures include three analyzer fields. They are not measurements of a single-analyzer production schema. CU retained the smaller footprint, but the service stayed at one Standard replica and one partition, so no capacity or fixed-bill saving was demonstrated. Native CU and document embeddings remain billable pipeline operations; complete currency attribution was unavailable.

The 47 original indexes remained present; the two new indexes brought usage to 49 of 50 slots. Both application grants were verified as index-scoped readers without a writer role. No resource reset, deletion, new model deployment, network change or paid semantic upgrade occurred.

## Integrity and implementation verification

- Independently checked 26,496 ranking outcomes, 441,600 metric values, 22,680 distinct query fingerprints and three policy nominations.
- Independently recomputed 60 paired comparison intervals, 80 semantic development intervals and 18 within-arm effect intervals at tolerance 1e-12.
- Verified 396 actually used shared question vectors byte-identical to their source cache, 996 raw-upload byte proofs, 15 parameter states and 167 protected historical artifacts.
- Independently verified another 1,584 ANN request fingerprints and 792 neighbor-overlap values.
- Main semantic ledger: 3,168 successes, two quota rejections and one transport-failed unknown outcome. One prior readiness success brings the observed study total to 3,172 semantic attempts, below its 12,000-attempt cap. No quota-rejected response was scored.
- The combined related production regression suite passed 157 cases. The operational executor/auditor suite passed 26 cases, including empty-body update readback, interrupted writes, stale versions, source drift, quota-specific seals, independent formulas and bounded reconnection.
- Scoped transport recovery retained all confirmed results and budgets. Small request attempts left room for retries; full-vector scans retained their 250-row pages and 60-second timeout.

These findings concern parent-document retrieval on provisional synthetic references. This study did not create human-reviewed chunk labels or a new answer-generation quality assessment. Earlier automated answer diagnostics are historical evidence, not measurements of these tuned treatments.

## Evidence and reproducible settings

- [Selected serving policy and current semantic quota gate](../../../evaluations/index-epochs/experiment-292c2fc4a2244fe3bda7a454ff7c5859/index-epoch-selected-serving-policy.json).
- [Complete verified analysis](../../../evaluations/index-epochs/experiment-292c2fc4a2244fe3bda7a454ff7c5859/index-epoch-free-scope-analysis.json) and [independent verification](../../../evaluations/index-epochs/experiment-292c2fc4a2244fe3bda7a454ff7c5859/index-epoch-free-scope-independent-verification.json).
- [Original design](../../../evaluations/index-epochs/experiment-292c2fc4a2244fe3bda7a454ff7c5859/index-epoch-study-plan.json), [pre-query design addendum](../../../evaluations/index-epochs/experiment-292c2fc4a2244fe3bda7a454ff7c5859/index-epoch-design-addendum.json) and [quota stopping scope](../../../evaluations/index-epochs/experiment-292c2fc4a2244fe3bda7a454ff7c5859/index-epoch-free-quota-scope.json).
- [Actual quota rejection](../../../evaluations/index-epochs/experiment-292c2fc4a2244fe3bda7a454ff7c5859/index-epoch-semantic-quota-rejection.json), [final source/vector audit](../../../evaluations/index-epochs/experiment-292c2fc4a2244fe3bda7a454ff7c5859/index-epoch-free-scope-live-verification.json) and [service, roles and footprint readback](../../../evaluations/index-epochs/experiment-292c2fc4a2244fe3bda7a454ff7c5859/index-epoch-post-study-operations.json).
- [All original index names preserved](../../../evaluations/index-epochs/experiment-292c2fc4a2244fe3bda7a454ff7c5859/index-epoch-historical-index-preservation.json).
- [Full development ANN audit](../../../evaluations/index-tuning-readiness/experiment-adaa0a328a894cee869e40b3bea78d50/full-development-ann-audit.json) and [independent ANN verification](../../../evaluations/index-tuning-readiness/experiment-adaa0a328a894cee869e40b3bea78d50/full-development-ann-independent-verification.json).
- [Final publication verification](../../../evaluations/index-epochs/experiment-292c2fc4a2244fe3bda7a454ff7c5859/index-epoch-publication-verification.json).
- [Configuration and execution contracts](../usage.md#index-and-semantic-tuning-controls).
