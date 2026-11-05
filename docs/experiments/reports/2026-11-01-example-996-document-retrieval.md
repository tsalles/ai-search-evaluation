# Example 996-document raw-only retrieval experiment

Date: 2026-11-01

Status: Executed and independently verified; provisional reference; exploratory conclusions

## Conclusion

**Content-only semantic hybrid remains the strongest tested retrieval policy. The experiment does not establish DE/CU equivalence or eliminate the need for tuning.**

- Both pipelines indexed all 996 fresh native documents without errors or warnings.
- The predeclared semantic-hybrid primary produced parent nDCG@10 **0.816400 for DE** and **0.807573 for CU**.
- CU minus DE was **-0.008827**, with a paired family bootstrap 95% interval of **[-0.023414, +0.006549]**. No equivalence margin or equivalence test was predeclared.
- Semantic reranking increased nDCG@10 by **0.309060 for DE** and **0.300088 for CU** against the same-index hybrid control.
- Native chunk sizes remain substantially different. Equal-token chunk/evidence quality, human reference review and arm-specific raw-only tuning remain outstanding.

The earlier description of hybrid results as "effectively tied" referred to similar point estimates at one cutoff. It did not demonstrate that the extraction/chunking policies are equally good across tasks, formats, cutoffs or operating costs.

## Frozen protocol and corpus

| Item | Executed setting |
|---|---|
| Experiment | `experiment-0b5c8c21cea24c098b58e261ebd8fb89` |
| Source run | `run-419bb5aa33ae4b978c76355015934b60` |
| Seed | 20261031 |
| Protocol | Version 2, `enrichment_policy: search-pipeline-only` |
| Corpus | 996 newly authored native documents, 166 scenario families |
| Format quotas | 166 files each in PDF, DOCX, XLSX, PPTX, HTML and Markdown |
| Family size | Six distinct source documents per family; formats are balanced globally |
| Family splits | 93 calibration, 33 development, 40 test |
| Reference | Explicit `automated_study` release; no certified human reviewers |
| Test cohort | 240 intents, 480 utterances; 200 answerable and 40 unanswerable intents |
| DE index | `docgen-eval-e261ebd8fb89-de-index` |
| CU index | `docgen-eval-e261ebd8fb89-cu-index` |
| DE native policy | Document Extraction and Text Split; 2,000 characters, 200-character overlap |
| CU native policy | Content Understanding semantic chunking; 2,000 tokens, zero overlap |
| Embeddings | `text-embedding-3-large`, 3,072 dimensions; native chunk text only |
| Common retrieval | Content-only BM25/vector hybrid; vector weight 1, vector k 50, raw top 50 |
| Primary | Test `semantic-hybrid`, parent nDCG@10 |
| Secondary control | Test ordinary `hybrid` on the same frozen indexes |
| Collection | 960 arm/query outcomes per profile, 1,920 total |

The paired protocol requires six source documents per family, so this run used 996 instead of exactly 1,000. Each family does not necessarily contain one document in every format: only three of the 166 families contain all six formats. Source roles and corpus-wide format quotas remain frozen; there are no alternate-format copies of the same accepted content.

Every source document was indexed, including documents from non-test families. Only the 40 predeclared test families supplied evaluation questions. Increasing indexed documents increases distractors; it does not automatically increase the number of independent evaluated families.

This is a fresh authoring run rather than a fork of the 300-document corpus. It still uses the same synthetic banking preset and templated query/reference methodology, so it does not establish generalization to organizational documents.

## Preserved raw-only boundary

- Uploads attached no custom Blob metadata, including checksum, title or account-name metadata.
- Each arm consumed the same native file bytes through its own Search skillset.
- Each index contains only `id`, `parent_id`, `content`, `content_path` and `embedding`. Technical IDs and paths do not contribute to lexical ranking.
- Both semantic configurations prioritize `content` only, with no title or keyword fields, scoring profiles or default boosts.
- There was no entity extractor in this run, no outside name catalog, no client-side document merge and no document-vector replacement.
- Canonical sources and qrels remained evaluator-only. They did not enrich indexed documents, repair extraction losses or change runtime query text.
- All 480 question-only embeddings were newly generated, then reused across both arms and both profiles. No historical question vectors were inherited.

## Ingestion and native chunk sizes

| Measure | DE | CU |
|---|---:|---:|
| Indexed source documents | 996 | 996 |
| Native chunks | 3,204 | 1,188 |
| Mean chunk tokens, `cl100k_base` | 425.37 | 1,128.37 |
| Median chunk tokens | 483 | 1,201.5 |
| Missing sources | 0 | 0 |
| Indexer errors | 0 | 0 |
| Indexer warnings | 0 | 0 |

The native policies combine extraction and chunking. Character windows and token windows are different treatments, not an extraction-only comparison. CU used fewer, larger chunks; source coverage alone does not demonstrate that every extracted fact or table survived.

Both indexers ran sequentially on 2026-10-31. DE completed 996 source attempts from 18:32:47 to 18:35:32 UTC; CU completed its 996 attempts from 18:35:54 to 18:38:36 UTC.

## Test ranking results

Each profile has 800 scored answerable arm/query rows and 160 unanswerable responses with N/A ranking metrics. Parent deduplication precedes each cutoff. Precision divides by the cutoff; binary relevance is grade at least 2; nDCG uses gains 0/1/3/7.

Point estimates average utterances within an intent, answerable intents within a family, then families. The primary uncertainty unit is the family, with 10,000 paired bootstrap resamples over 40 test families.

| Metric | Hybrid DE | Hybrid CU | Semantic DE | Semantic CU |
|---|---:|---:|---:|---:|
| Precision@1 | 0.617500 | 0.600000 | 0.837500 | 0.810000 |
| Precision@3 | 0.346667 | 0.356667 | 0.648333 | 0.625000 |
| Precision@5 | 0.247500 | 0.250000 | 0.465500 | 0.465000 |
| Recall@1 | 0.255208 | 0.265208 | 0.368750 | 0.358333 |
| Recall@3 | 0.427083 | 0.447500 | 0.790000 | 0.764583 |
| Recall@5 | 0.506667 | 0.526250 | 0.907917 | 0.908333 |
| nDCG@1 | 0.614167 | 0.591429 | 0.840119 | 0.814048 |
| nDCG@3 | 0.492912 | 0.490414 | 0.801698 | 0.778634 |
| nDCG@5 | 0.487328 | 0.487460 | 0.791573 | 0.781659 |
| nDCG@10, primary | 0.507340 | 0.507484 | 0.816400 | 0.807573 |
| Precision@10 | 0.137250 | 0.136250 | 0.250250 | 0.251250 |
| Recall@10 | 0.562708 | 0.575000 | 0.964792 | 0.971458 |
| nDCG@20 | 0.557056 | 0.515342 | 0.825492 | 0.816540 |
| Recall@20 | 0.729375 | 0.596250 | 0.977917 | 0.983542 |

The full sealed reports retain Precision, Recall, nDCG and MRR at 1/3/5/10/20.

### Arm comparison and equivalence

| Profile | CU minus DE nDCG@10 | Paired 95% interval |
|---|---:|---|
| Hybrid control | +0.000144 | [-0.040238, +0.040852] |
| Semantic hybrid primary | -0.008827 | [-0.023414, +0.006549] |

An interval spanning zero does not demonstrate equivalence. The semantic-primary interval still permits CU to trail DE by about 2.34 absolute nDCG percentage points or lead by about 0.65. Practical equivalence would require a predeclared acceptable difference, an appropriate equivalence analysis and sufficiently precise estimates.

Results also differ by cutoff. Semantic nDCG@3 favors DE by a point estimate of 0.023064, with a CU-minus-DE interval of [-0.046330, -0.001454]. The hybrid control's Recall@20 was 0.729375 for DE and 0.596250 for CU. These are exploratory secondary endpoints; intervals across the many metrics and cutoffs are not multiplicity-adjusted and do not establish a universal winner.

Every answerable query returned at least 29 distinct parents in DE and 43 in CU within the raw depth of 50. The hybrid Recall@20 difference is therefore not caused by CU returning fewer than 20 parents. A ranking-error review is needed to explain it.

### Semantic policy effect

The following intervals compare semantic hybrid against ordinary hybrid **within the same arm**. They are separate, post-hoc descriptive profile-effect estimates, not the CU-minus-DE intervals above.

| Arm | nDCG@10 increase | Within-arm paired 95% interval |
|---|---:|---|
| DE | +0.309060 | [+0.264144, +0.354159] |
| CU | +0.300088 | [+0.257294, +0.343945] |

Precision@1 increased by 0.220000 for DE and 0.210000 for CU. Recall@10 increased by 0.402083 for DE and 0.396458 for CU. The run supports semantic reranking as the strongest tested policy on this corpus; it does not identify an optimized chunking policy.

## Operations, recovery and verification

The first authoring pass accepted 979 sources; the next accepted 994. Two persistent rejected candidates put decimal facts in text-typed table columns. Audited per-item candidate limits increased from three to six, then ten; total request/token ceilings and all quality rules stayed unchanged. Valid model candidates completed the remaining slots. No rejected payload was repaired and no accepted source was rewritten.

The overnight attached semantic worker was no longer present when checked on 2026-11-01, with zero semantic dispatches. After confirming no orphan worker, the unchanged semantic stage resumed and completed. Actual dispatches ran from 09:27:29 to 09:33:36 UTC, after the frozen 08:00 UTC gate.

| Check | Verified result |
|---|---|
| Evaluation regression suite | 211 cases passed across complementary runs: 42 release-policy cases and 169 other evaluation cases |
| Audited retry regressions | Two recovery cases passed |
| Application typing and Ruff | Passed; all 77 source-module hashes still match the validated implementation |
| Native source integrity | 996 hashes, global format quotas, empty metadata and version-bound Blob byte proofs verified |
| Request fingerprint audit | All 1,920 ranking fingerprints matched plain-question content-only hybrid/semantic templates |
| Independent numerical audit | 32,000 per-query metric values and 40 arm-comparison bootstrap intervals verified at absolute tolerance 1e-12 |
| Query-vector audit | 480 question-only embedding attempts; no document embedding attempts |
| Actual pipeline provenance | Five-field schemas, content-only semantic configurations, native-text embedding inputs, no entity or metadata donors |
| Historical integrity | 124 protected artifacts retained their hashes; all previous 994 accepted source contents remained unchanged |
| Packaging | Source distribution and wheel built with the completed report |

| Recorded application operation | Actual attempts |
|---|---:|
| Search | 1,976 |
| Query embeddings | 480 |
| Administration | 133 |
| Blob | 3,999 |
| Observed query embedding tokens | 10,894 |
| Semantic dispatches, including retries | 960 |

All 1,920 retrieval outcomes succeeded. Search totals also include scans/probes and six authorization failures during initial reader-grant propagation. No semantic response was accepted as a fallback or partial success. Actual semantic dispatches stayed within the 1,000 ceiling and the service remained on its free semantic plan.

Authoring used 1,273 requests and 7,135,942 observed tokens; two transient request outcomes have unknown usage. Native CU, indexer embeddings and total monetary costs are not returned by these projections. No claim of zero or complete monetary cost is made.

Only new index-scoped reader access was needed for application queries. No document-writer grants, model deployments, capacity/billing/network changes, index resets or resource deletions were made. Historical resources remain intact.

## Tuning recommendation

1. Retain content-only semantic hybrid as the current tested retrieval policy. Use ordinary hybrid explicitly when semantic quota or cost is unsuitable.
2. Screen raw-only native chunk settings on the untouched 33-family development cohort. Candidate treatments can include DE token windows of 512/1,024 with bounded overlap and CU native semantic windows of 512/1,024/2,000 tokens. Do not infer CU's optimum from the historical metadata-assisted tuning study.
3. Evaluate lexical/vector balance and candidate depth under the same declared query policy, exposure budget and semantic quota for both arms.
4. Review source-backed ranking errors by task and format. Add answer-evidence sufficiency under an equal token budget before interpreting parent relevance as chunk quality.
5. Freeze selected policies before a fresh held-out comparison. The current test set has now been inspected; post-tuning reuse would remain exploratory. Human reference review and a predeclared practical-equivalence margin are needed for an equivalence claim.

The corpus contains native text and tables. Scans, OCR-heavy documents, charts/images and organizational-document generalization remain outside this executed evidence. The tested entity-weighting policy remains rejected by the separate [entity experiment](2026-10-30-example-pipeline-entities.md).

## Sealed evidence

- [Protocol](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/protocol.json), [frozen run plan](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/large-sample-run-plan.json) and [reference](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/reference.json).
- [Hybrid test report](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/report-test.json), [semantic-primary report](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/report-test-semantic-hybrid.json) and [within-arm semantic effects](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/large-sample-profile-effects.json).
- [DE snapshot](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/snapshot-de_split.json), [CU snapshot](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/snapshot-content_understanding.json) and [actual pipeline provenance](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/large-sample-pipeline-provenance.json).
- [Generation proof](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/large-sample-generation-verification.json), [indexing proof](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/large-sample-indexing-verification.json), [live completion proof](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/large-sample-live-verification.json) and [semantic resumption proof](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/large-sample-semantic-resumption.json).
- [Independent verification](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/large-sample-independent-verification.json), [validated code proof](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/large-sample-code-verification.json) and [final report verification](../../../evaluations/large-sample/experiment-0b5c8c21cea24c098b58e261ebd8fb89/large-sample-report-verification.json).
