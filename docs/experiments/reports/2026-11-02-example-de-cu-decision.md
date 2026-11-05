# Example DE versus CU decision study

Date: 2026-11-02

Status: Executed and independently verified; provisional synthetic reference; no certified human review

## Recommendation

**Use Document Extraction plus Text Split as the ingestion default for this native-text workload. Do not migrate to Content Understanding solely on the retrieval results measured here.**

This is a cost-aware operational recommendation under uncertainty, not a claim that DE and CU are equivalent or that DE universally wins.

- With the development-selected lexical policies, held-out nDCG@10 was **0.740805 for DE** and **0.751411 for CU**. CU minus DE was **+0.010606**, with a paired 95% interval **[-0.004090, +0.024996]**.
- With the development-selected common hybrid policy, held-out nDCG@10 was **0.601741 for DE** and **0.598845 for CU**, with a CU-minus-DE interval **[-0.020031, +0.014576]**.
- In the matched lexical answer diagnostic, both arms produced **9/10 model-rated correct answers** and **9/10 complete-support contexts** under the same 4,096-token context cap.
- CU has useful positive signals: smaller indexes at its selected 1,024-token setting, improved lexical quality after native-size tuning, and stronger automated support counts with shorter chunks. These signals do not establish a sufficiently clear general quality advantage to justify switching the current workload by default.
- DE text extraction and Text Split are non-billable utility operations; CU extraction invokes an additional billable Foundry service. Embeddings, Search capacity, answer models and other resources can still incur charges.

### Go-forward configuration

| Purpose | Current recommendation |
|---|---|
| Ingestion default | DE, 2,000-character Text Split windows, 200-character overlap |
| Immediately usable retrieval without more semantic quota | Content-only BM25 |
| Quality-first retrieval when semantic quota or approved paid billing is available | Retain the already tested content-only semantic-hybrid option; validate any newly tuned semantic policy before production promotion |
| Tuned hybrid candidate | DE 512 tokens with overlap 64; vector weight 0.5, k 50, raw depth 50 |
| CU candidate if its extra processing is justified | CU native semantic chunks of 1,024 tokens for the lexical retrieval candidate; retain 512 tokens as an evidence-quality alternative |
| Entity weighting | Keep disabled; the separate [entity experiment](2026-10-30-example-pipeline-entities.md) regressed both arms |

The [earlier 40-family test](2026-11-01-example-996-document-retrieval.md) measured semantic-hybrid nDCG@10 of 0.816400 for DE and 0.807573 for CU. It remains separate from the new development and confirmation results below. The present study does not justify replacing that larger semantic comparison with a five-family diagnostic.

The November free semantic allowance was consumed by the earlier 960 dispatches and this study's 40 additional dispatches. Production use beyond that allowance requires an approved billing change or renewed quota. Ordinary hybrid is not a silent fallback for failed semantic requests.

## What was compared

| Dimension | Executed comparison |
|---|---|
| Immutable corpus | Same 996 accepted native files, 166 scenario families; 166 files per format |
| Formats | PDF, DOCX, XLSX, PPTX, HTML and Markdown |
| Native policies per arm | Original default, 512-token windows, 1,024-token windows |
| DE overlap | Original 200 characters; 64 tokens at 512; 128 tokens at 1,024 |
| CU overlap | Zero, as required by the native semantic chunking method |
| Development retrieval grid | BM25, vector only, hybrid weights 0.5/1/2, and weight-1 hybrid with vector k 100 |
| Common exposure | Raw returned depth 50; no title/entity boosts or filters |
| Development cohort | 33 families, 396 utterances, 792 paired arm/query outcomes per profile |
| Original grid size | 3 native case pairs x 6 profiles; 14,256 successful outcomes |
| Previously unevaluated confirmation cohort | All 93 original calibration families, 1,116 utterances |
| Nonsemantic confirmation | Default and selected hybrid controls, plus default and nominated lexical cases; 8,928 successful outcomes |
| Semantic diagnostic | Preselected five-family, five-task cohort; 10 utterances and 40 successful outcomes across default and selected policies |
| Equal-token answer diagnostics | 120 native-grid contexts, then 20 separately registered lexical contexts |
| Human assurance | Reference and model judgments remain provisional; no fabricated reviewers |

Each family has six source documents. Formats are balanced across the corpus, not one-per-format within every family. These are distinct sources rather than alternate-format copies of one canonical document.

All 996 sources were indexed in every case. The inspected 40 test families were excluded from tuning and confirmation. The original `calibration` split label was preserved in the saved reports; its 93 families had not previously supplied ranking results and served as the new confirmation cohort.

The hybrid selection rule was frozen before confirmation: select each arm's best eligible native case for each common hybrid profile, allowing at most 0.02 absolute loss in Precision@1 and Recall@10 relative to the default hybrid development control. Choose the common profile with the highest mean arm nDCG@10. This selected DE 512/CU 1,024 and vector weight 0.5.

BM25 strongly outperformed vector and equal-weight hybrid controls during development. A separate lexical hypothesis was registered before any calibration results: select each arm's best native BM25 case with the same loss guards relative to default-native BM25. This selected default DE and CU 1,024. The original hybrid selection was not rewritten.

## Raw-only boundary and reproducibility

- Every case consumed identical native file bytes with **empty custom Blob metadata**.
- Indexes contain only technical IDs/paths, native `content` and pipeline-generated `embedding`. Neither title nor account-name catalogs were supplied as features.
- All semantic configurations prioritize `content` alone. There are no scoring-profile boosts, outside document merges or application-side document-vector writes.
- Reference answers, source facts and entity labels remain evaluator-only. They never repair indexed content or alter runtime query text.
- All 1,512 distinct evaluated question vectors were verified byte-identical across applicable cases. A late cache handoff shared 1,116 calibration vectors created after the finalist fork; the finalist issued no duplicate embedding requests.
- All references, claims, evidence, query wording and qrels remained identical across cases, apart from protocol identity.
- Four case workspaces used separate prefixes/resources, including the recombined selected case. All eight final arm indexes covered 996 sources without indexer errors or warnings.
- Final live checks revalidated resource definitions, source versions, native text and vector hashes. All 140 protected historical artifacts retained their hashes.

## Development grid

These are family-macro parent nDCG@10 estimates on the 33-family development cohort.

| Native case | Profile | DE | CU |
|---|---|---:|---:|
| default | bm25 | 0.735124 | 0.747843 |
| default | vector | 0.182888 | 0.194357 |
| default | hybrid | 0.423187 | 0.456217 |
| default | hybrid-lexical | 0.570126 | 0.577436 |
| default | hybrid-vector | 0.382727 | 0.408202 |
| default | hybrid-wide | 0.468629 | 0.504367 |
| tokens-512 | bm25 | 0.732245 | 0.745950 |
| tokens-512 | vector | 0.181480 | 0.134339 |
| tokens-512 | hybrid | 0.437095 | 0.404350 |
| tokens-512 | hybrid-lexical | 0.577662 | 0.582252 |
| tokens-512 | hybrid-vector | 0.399804 | 0.362274 |
| tokens-512 | hybrid-wide | 0.481985 | 0.465824 |
| tokens-1024 | bm25 | 0.732013 | 0.758337 |
| tokens-1024 | vector | 0.174344 | 0.184821 |
| tokens-1024 | hybrid | 0.444351 | 0.454585 |
| tokens-1024 | hybrid-lexical | 0.571087 | 0.587422 |
| tokens-1024 | hybrid-vector | 0.400832 | 0.403923 |
| tokens-1024 | hybrid-wide | 0.486581 | 0.498178 |

The dense-only component was weak on these explicit product-name questions. Increasing its weight worsened results; reducing it helped both arms. Expanding vector k from 50 to 100 helped some hybrid settings but did not beat the lexical-weighted hybrid or BM25 controls. This does not establish that vectors are generally ineffective on natural organizational queries.

## Held-out confirmation quality

Each policy contains all 93 confirmation families. Estimates average utterances within intent, answerable intents within family, then families. Binary relevance is grade at least 2; nDCG gains are 0/1/3/7. Parent deduplication precedes cutoffs and Precision divides by the cutoff.

Unanswerable ranking rows remain present with N/A metrics, not invented positives or discarded failed responses. Each full confirmation report has 1,860 scored answerable rows and 372 unanswerable rows.

| Metric | Default hybrid DE | Default hybrid CU | Tuned hybrid DE | Tuned hybrid CU | Selected BM25 DE | Selected BM25 CU |
|---|---:|---:|---:|---:|---:|---:|
| Precision@1 | 0.537634 | 0.555914 | 0.609677 | 0.615054 | 0.584946 | 0.577419 |
| Precision@3 | 0.328315 | 0.331900 | 0.382437 | 0.372760 | 0.470609 | 0.476344 |
| Precision@5 | 0.233548 | 0.237419 | 0.268387 | 0.257204 | 0.386452 | 0.395269 |
| Recall@1 | 0.230376 | 0.255197 | 0.266039 | 0.274910 | 0.242294 | 0.244803 |
| Recall@3 | 0.415681 | 0.436380 | 0.483154 | 0.482616 | 0.573477 | 0.583065 |
| Recall@5 | 0.486649 | 0.515143 | 0.558871 | 0.545072 | 0.760753 | 0.779391 |
| nDCG@1 | 0.533897 | 0.557296 | 0.599949 | 0.609370 | 0.585100 | 0.571736 |
| nDCG@3 | 0.450538 | 0.469851 | 0.521036 | 0.522115 | 0.607826 | 0.612125 |
| nDCG@5 | 0.446787 | 0.468245 | 0.514034 | 0.509570 | 0.658981 | 0.671177 |
| nDCG@10 | 0.461122 | 0.483285 | 0.601741 | 0.598845 | 0.740805 | 0.751411 |
| Precision@10 | 0.126882 | 0.127849 | 0.187957 | 0.187527 | 0.239032 | 0.241828 |
| Recall@10 | 0.523029 | 0.553763 | 0.759857 | 0.757527 | 0.921685 | 0.935573 |
| nDCG@20 | 0.509692 | 0.491355 | 0.692844 | 0.695256 | 0.772759 | 0.778595 |

Full saved reports also retain Precision, Recall, nDCG and MRR at 1/3/5/10/20.

| Policy contrast | CU minus DE nDCG@10 | Paired family bootstrap 95% interval |
|---|---:|---|
| Default hybrid | +0.022162 | [-0.002877, +0.048099] |
| Tuned common hybrid | -0.002896 | [-0.020031, +0.014576] |
| Selected lexical policies | +0.010606 | [-0.004090, +0.024996] |

Intervals use 10,000 paired family resamples. No equivalence margin or equivalence test was predeclared. Intervals spanning zero do not prove equivalence. Secondary metrics and overlapping source-format slices are exploratory and not multiplicity-adjusted.

Tuning the common hybrid policy increased nDCG@10 by 0.140619 for DE, interval [0.123659, 0.158140], and 0.115560 for CU, interval [0.097520, 0.133785]. These are combined native/query-policy effects, not extraction-only effects.

Within CU's lexical policy, changing native chunks from 2,000 to 1,024 tokens increased nDCG@10 by 0.026149, interval [0.006637, 0.047497]. CU tuning was worthwhile; its remaining advantage over the selected DE lexical policy was much smaller.

Task differences remain: selected lexical DE scored 0.896370 on comparison tasks versus CU 0.869708; CU scored 0.751591 on conditions/process tasks versus DE 0.718320. The same source can contribute to multiple format slices, so those slices are descriptive rather than a matched-format causal experiment.

## Limited semantic comparison

The following comparisons use the same predeclared 10 utterances from five calibration families. Nonsemantic controls were reaggregated from their sealed full-cohort outcomes without extra requests.

| End-to-end policy | DE nDCG@10 | CU nDCG@10 |
|---|---:|---:|
| Default hybrid | 0.307252 | 0.475114 |
| Tuned hybrid | 0.562394 | 0.609060 |
| Selected BM25 | 0.659420 | 0.698646 |
| Default semantic hybrid | 0.676072 | 0.746376 |
| Tuned semantic hybrid | 0.747483 | 0.748233 |

The tuned semantic CU-minus-DE interval is [-0.031480, +0.025516]. Both tuned arms reached Recall@10 of 1.0 on this small diagnostic. Five families do not establish semantic superiority, equivalence or an optimized production policy.

The free plan had at most 40 requests remaining. A question seeking approval for a service-wide paid semantic plan received no available decision, so billing stayed free. A full semantic development sweep and independent semantic confirmation remain unexecuted. In particular, lexical-only retrieval plus semantic reranking was not evaluated and must not be presented as a verified winner.

## Equal-token answer and evidence quality

The answer deployment was `gpt-5.4-mini`; the assessor was `gpt-6-luna`. Neither received arm/case labels. The answer model received only the original question and the ranked native whole-chunk prefix, capped at 4,096 `cl100k_base` tokens including original citation wrappers. The evaluator did not skip chunks using gold labels.

The assessor separately received evaluator truth and those same exposed source chunks. It selected supporting chunk IDs; the evaluator resolved only exact declared aliases to complete literal source text. All required claims were assessed exactly once. Unknown or repeated identifiers failed, and no quote text was repaired or fabricated.

| Native setting | Arm | Complete-support contexts | Model-rated correct answers | Abstentions | Contexts |
|---|---|---:|---:|---:|---:|
| Default | DE | 11 | 10 | 6 | 20 |
| Default | CU | 9 | 9 | 5 | 20 |
| 512 tokens | DE | 10 | 10 | 2 | 20 |
| 512 tokens | CU | 15 | 13 | 2 | 20 |
| 1,024 tokens | DE | 8 | 8 | 7 | 20 |
| 1,024 tokens | CU | 13 | 13 | 3 | 20 |

These native-grid contexts all use the selected common lexical-weighted hybrid query policy. They cover 20 utterances from ten development families, not 20 independent families. They diagnose settings within the native grid; the recombined finalist index was not independently answer-rated as another corpus.

CU's shorter chunks improved automated context support and answer ratings relative to its default. This is a useful RAG signal that parent nDCG alone missed. It remains a small model-reviewed diagnostic with no certified human entailment labels.

The separately registered lexical supplement used five whole intents, one per task, selected deterministically from the original evidence cohort:

| Same-query, same-native-case comparison | Hybrid correct | BM25 correct | Hybrid complete support | BM25 complete support | Contexts per policy |
|---|---:|---:|---:|---:|---:|
| DE default native case | 7 | 9 | 7 | 9 | 10 |
| CU 1,024-token native case | 8 | 9 | 8 | 9 | 10 |

Both lexical arms answered 9/10 correctly with 9/10 complete support. These results do not prove equal chunk quality. Model judgments can misinterpret relationships even when every citation is literal. Unanswerable answer-generation safety was not separately evaluated.

### Evaluator correction and cost accounting

Free quotation generation failed strict grounding: the model mistyped 221-character opaque keys and later associated text with the wrong short chunk alias or paraphrased it. The initial v1/v2 trials were preserved but excluded in full from final evidence scores.

The homogeneous v3 contract asks the assessor to select only exposed chunk IDs and resolves complete source chunks deterministically. Question text, answer inputs, native exposure, token cap, rankings and required claims stayed unchanged. Identical previously generated answers were reused.

An append-only audited evaluation override increased the request ceiling from 300 to 350 to replace the discarded assessments. The original 2,000,000 observed-token cap remained unchanged. All earlier attempts stayed in the same ledger. Actual use was 321 model requests: 312 succeeded, eight were rejected, and one transport-failed request has unknown usage. Observed usage was 1,111,441 tokens, including rejected responses. This is not a claim of complete monetary cost or human approval.

## Extraction opportunity, resource use and latency

Every native setting preserved all 1,163 evaluator-defined source-name presence opportunities and all 1,158 unbound numeric-value opportunities. This literal readback check does not validate entity/value binding, table relationships, unit interpretation or semantic completeness. The answer diagnostic addresses some of those relationships separately.

| Native case | Arm | Chunks | Mean chunk tokens | Index storage MiB | Vector index MiB |
|---|---|---:|---:|---:|---:|
| Default | DE | 3,204 | 425.37 | 139.63 | 37.72 |
| Default | CU | 1,188 | 1,128.37 | 62.39 | 13.99 |
| 512 tokens | DE | 3,142 | 439.12 | 138.17 | 36.99 |
| 512 tokens | CU | 3,632 | 368.79 | 154.06 | 42.76 |
| 1,024 tokens | DE | 1,874 | 724.65 | 90.13 | 22.07 |
| 1,024 tokens | CU | 1,932 | 693.64 | 90.96 | 22.75 |

Footprints are the frozen development-phase service observations. CU's selected lexical index was smaller than default DE's, but both fit the existing capacity. The 512-token CU setting lost the compact-index advantage.

Native embedding-input token estimates were approximately 1.34 million for CU and 1.36 to 1.38 million for DE. Fewer chunks did not imply proportionally fewer embedding tokens. These `cl100k_base` counts are estimates of native embedding inputs, not returned billing meters.

| Confirmation query policy | DE p50 ms | CU p50 ms | DE p95 ms | CU p95 ms |
|---|---:|---:|---:|---:|
| Default hybrid | 297 | 297 | 2456.75 | 2406.75 |
| Tuned hybrid | 266 | 266 | 313 | 313 |
| Selected BM25 | 157 | 157 | 188 | 188 |

Timing scope is the successful Search transport attempt including authentication, excluding query embedding and failure/retry time. The shared Windows client had a coarse monotonic clock and intermittent transport delays. Profile phases ran at different times. These observations are not a controlled throughput benchmark, extractor-only latency proof or production SLA.

### Cost implications

| Component | DE | CU |
|---|---|---|
| Native text extraction | Free utility extraction | Additional billable Foundry/CU processing |
| Native chunking | Non-billable Text Split | Part of the CU treatment |
| Embeddings | Model-provider charges apply | Model-provider charges apply |
| Query semantic reranking | Same quota/billing policy | Same quota/billing policy |
| Current dedicated Search capacity | Existing Standard, one replica and one partition | Same shared capacity |
| Complete attributable currency cost | Not available from these projections | Not available from these projections |

Smaller indexes can defer future capacity growth, but this experiment did not reduce Search Units or measure a corresponding bill saving. Retail-price lookups returned no applicable rate rows; no zero-dollar rate was inferred.

Official billing references: [Document Extraction](https://learn.microsoft.com/azure/search/cognitive-search-skill-document-extraction), [Text Split](https://learn.microsoft.com/azure/search/cognitive-search-skill-textsplit), [Content Understanding](https://learn.microsoft.com/azure/search/cognitive-search-skill-content-understanding) and [Search cost model](https://learn.microsoft.com/azure/search/search-sku-manage-costs).

## Verification and operational boundaries

- 23,224 ranking request fingerprints, 387,200 per-query metric values and 480 paired arm bootstrap intervals were independently verified at absolute tolerance 1e-12.
- All 3,984 raw-upload proofs across four case prefixes, all cross-case references/qrels, all 1,512 evaluated shared question vectors and all 140 equal-token evidence contexts were independently checked.
- Both policy nomination rules were recomputed independently from development data, including loss guards and deterministic ties. Confirmation results did not reselect policies.
- The complete evaluation suite passed 242 cases. The final evidence-contract rerun passed 21 cases, including nine added alias/chunk-support cases. Strict typing covers 78 application modules.
- Recovery retained confirmed requests, all source hashes and frozen results. Full-vector scan pages were bounded to 250 rows with a reproducing 263-chunk regression; scans still continue through an empty page and validate every vector.
- Subscription-scoped renewable credentials, bounded transport recovery and unchanged aggregate request budgets were retained. No paid semantic upgrade, new model deployment, capacity/network change, document-writer grant, index reset or resource deletion occurred.
- Source distribution, wheel, numeric report cells, evidence links and historical integrity are checked in the final report-verification record.

## Decision limits

The recommendation applies to the tested native-text synthetic banking corpus. Human relevance review, representative organizational documents, scans/OCR, charts/images and production concurrency remain outside this evidence.

CU remains worth considering when those requirements matter, when compact indexes change capacity economics, or when representative reviewed answer-evidence gains justify its added processing. For the current corpus, retrieval-policy tuning produced larger and more consistent gains than choosing CU over DE. Keep DE as the practical default and retain CU as a measured challenger rather than treating either as a universally superior extractor.

## Sealed evidence

- [Frozen study plan](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/decision-run-plan.json), [hybrid nomination](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/decision-selection.json) and [lexical hypothesis](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/decision-bm25-hypothesis.json).
- [Complete analysis](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/decision-analysis.json), [source readback](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/decision-source-readback.json) and [independent verification](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/decision-independent-verification.json).
- [Default hybrid confirmation](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/report-calibration.json), [tuned hybrid confirmation](../../../evaluations/decision-variants/experiment-700fdbfbf27b4d32923780c77067f079/report-calibration-hybrid-lexical.json), [default lexical confirmation](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/report-calibration-bm25.json) and [1,024-token lexical confirmation](../../../evaluations/decision-variants/experiment-1d737c4f986b4c12af71b2845e9c7836/report-calibration-bm25.json).
- [Default semantic diagnostic](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/report-calibration-semantic-hybrid-cohort-free-semantic-diagnostic.json) and [tuned semantic diagnostic](../../../evaluations/decision-variants/experiment-700fdbfbf27b4d32923780c77067f079/report-calibration-semantic-hybrid-lexical-cohort-free-semantic-diagnostic.json).
- [Native-grid model evidence](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/decision-evidence-v3-results.json), [matched lexical model evidence](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/decision-bm25-evidence-v3-results.json), [extractive citation contract](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/decision-evidence-citation-contract-v3.json) and [audited model budget](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/decision-evidence-budget-v3.json).
- [Late query-vector handoff](../../../evaluations/decision-variants/experiment-700fdbfbf27b4d32923780c77067f079/query-vector-handoff-calibration.json), [final live stability](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/decision-live-verification.json) and [final report verification](../../../evaluations/decision/experiment-11e0e091aac048408dde6b2a40c3d963/decision-report-verification.json).
