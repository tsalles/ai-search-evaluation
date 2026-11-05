# Example in-pipeline entity retrieval experiment

Date: 2026-10-30, local UTC-03:00; indexing completed on 2026-10-31 UTC

Status: Executed, provisional reference labels, development-only analysis

## Conclusion

**Retain ordinary content-only hybrid retrieval. Do not promote the tested entity-weighted profile.**

- Both Search pipelines indexed all 300 immutable raw documents and extracted source-grounded mentions entirely inside their skillsets.
- Adding the indexed entity field to lexical retrieval with weight 2 reduced development nDCG@10 from **0.675802 to 0.570044 for DE** and from **0.672920 to 0.603411 for CU**.
- Both arms failed the predeclared Precision@1 and Recall@10 loss guards. The sealed selection retained `hybrid`.
- The completed treatment used native Entity Recognition V3 and Shaper. Earlier GenAI treatments failed full-corpus grounding and were not scored.
- These results evaluate a particular entity-weighting policy on provisional synthetic references. They do not establish an extraction-arm winner or prove that every possible in-pipeline entity treatment is ineffective.

## Frozen inputs and treatment

| Item | Executed setting |
|---|---|
| Experiment | `experiment-268e4a67d1b24d67afd27c979808d5b3` |
| Protocol | Version 2, `enrichment_policy: search-pipeline-only` |
| Source run | `run-029b3f322ae44048acb296616e9e3c5a`, reused without new authoring |
| Corpus | 300 documents, 50 families, 50 files in each of PDF, DOCX, XLSX, PPTX, HTML and Markdown |
| Evaluation cohort | 10 development families, 60 intents, 120 utterances |
| Answerability | 50 answerable intents and 10 unanswerable intents |
| DE index | `docgen-eval-7c979808d5b3-de-index` |
| CU index | `docgen-eval-7c979808d5b3-cu-index` |
| DE native policy | Document Extraction and Text Split, 2,000 characters, 200-character overlap |
| CU native policy | Content Understanding semantic chunking, 2,000 tokens, zero overlap |
| Document embeddings | Native chunk text only; `text-embedding-3-large`, 3,072 dimensions |
| Entity extraction | Same native Entity Recognition V3 skill in each arm; Product and Organization categories, Portuguese, minimum precision setting 0.5 |
| Entity projection | Shaper preserves each recognized text occurrence in `entity_data/entities` |
| Control | `hybrid`, lexical search over `content` only |
| Retrieval treatment | `pipeline-entity-hybrid`, lexical search over `content,entity_data/entities`; weights 1 and 2 respectively |
| Common retrieval | Original question text, vector weight 1, vector k 50, raw depth 50 |
| Collection | 240 successful arm/query outcomes per profile, 480 total; zero semantic requests |

Both profiles queried the **same frozen treatment indexes**. The control ignored the entity field; the treatment enabled its lexical matches and scoring weight. This isolates the retrieval-policy effect within this indexing run. It does not isolate the cost of running NER, nor an ingestion difference against separately rebuilt historical indexes.

Sources, question wording, judgments and question-only vectors were inherited unchanged from the [raw-only control](2026-10-30-example-raw-only-control.md). This reused, previously inspected corpus is not an independent replication. No test-split queries were collected for this treatment or used for selection.

## Raw-only boundary and entity semantics

- Uploads contained native file bytes and MIME types, with **no custom Blob metadata**, including checksum or account-name metadata.
- Both arms derived entities from their own native extracted text. Neither arm received canonical titles, fact entities, a corpus-specific name catalog, source-specific examples or the other arm's annotations.
- The application made no document merges or document-vector replacement calls. Native document embedding inputs remained DE pages or CU text-section content.
- Each index has six root fields: `id`, `parent_id`, `content`, `content_path`, `embedding` and the complex `entity_data` object. IDs and paths remain non-ranking plumbing.
- The whole structured entity object is projected. An explicit empty array is valid; a missing object or unsupported source span blocks the audit and scoring.
- Native version 3 retains repeated occurrences, with at most 512 occurrences per chunk and exact character matching against that chunk. The client does not repair, deduplicate or discard annotations.
- Query construction adds no name catalog, phrase expansion, reference-dependent filter or semantic reranking. The index has no default scoring profile; entity weighting requires the explicit treatment profile.

The NER minimum precision setting is a service parameter, **not a measured precision result on this corpus**. A literal source span does not prove correct Product/Organization typing or complete financial-product-name extraction.

## Implementation trials

| Trial | Observation | Experimental disposition |
|---|---|---|
| GenAI version 1 | A small smoke passed; the 300-document attempt encountered request-rate failures and unsupported extracted names | Preserved the failed workspace; no full-corpus retrieval scores |
| GenAI version 2 | Batch size one and sequential arms resolved operational indexing failures; whitespace-only grounding allowed PDF line wraps, but unsupported names remained | Grounding audit rejected the treatment; no full-corpus retrieval scores |
| Native NER version 3 | A 12-document smoke covered every source; the final 300-document run passed exact source grounding with zero indexer errors or warnings | Collected and scored both development profiles |

Native NER used the existing Search enrichment path without a new chat deployment or custom validation service. Each definition correction used a separate immutable workspace. Invalid GenAI outputs were not silently dropped, repaired from evaluator facts or included in the final scored treatment.

The successful native smoke produced 29 DE chunks and 12 CU chunks across the same 12 sources. The final native main indexed sequentially: DE from 02:07:02 to 02:08:58 UTC, then CU from 02:10:09 to 02:11:29 UTC on 2026-10-31.

## Coverage and observed entity spans

| Measure | DE | CU |
|---|---:|---:|
| Indexed sources | 300 | 300 |
| Native chunks | 962 | 357 |
| Chunks with entity occurrences | 796 | 341 |
| Sources with at least one occurrence | 294 | 295 |
| Extracted occurrences, including repeats | 3,035 | 2,845 |
| Distinct literal spans | 357 | 349 |
| Missing sources | 0 | 0 |
| Indexer errors | 0 | 0 |
| Indexer warnings | 0 | 0 |

All **5,880 occurrences** passed independent exact-source grounding. These counts describe coverage and repetition; they are not entity precision or recall.

Common literal spans illustrate the general-purpose extractor's limitations:

| Span | DE occurrences | CU occurrences |
|---|---:|---:|
| `Documento` | 450 | 415 |
| `Aurora` | 338 | 341 |
| `banco` | 145 | 116 |
| `produto` | 78 | 59 |
| `Plus` | 54 | 52 |
| `Banco Aurora` | 51 | 46 |

Emphasizing generic or partial spans, and retaining repeated mentions in a searchable collection, can amplify unhelpful lexical signals. That is a plausible mechanism for the observed regression, not a separately established causal explanation. Human semantic typing and a ranking-error decomposition were not performed.

## Development ranking results

Each profile has 200 scored answerable arm/query rows. The other 40 responses retain N/A ranking metrics. Metrics average paraphrases within an intent, answerable intents within a family, then families. Parent deduplication precedes each cutoff. Precision divides by the cutoff, binary relevance is grade at least 2, and nDCG uses gains 0/1/3/7.

| Metric | Hybrid DE | Hybrid CU | Entity DE | Entity CU |
|---|---:|---:|---:|---:|
| Precision@1 | 0.800000 | 0.670000 | 0.600000 | 0.630000 |
| Precision@3 | 0.470000 | 0.460000 | 0.390000 | 0.366667 |
| Precision@5 | 0.328000 | 0.326000 | 0.288000 | 0.292000 |
| Recall@1 | 0.385000 | 0.290833 | 0.271667 | 0.278333 |
| Recall@3 | 0.610000 | 0.599167 | 0.498333 | 0.481667 |
| Recall@5 | 0.689167 | 0.694167 | 0.592500 | 0.605000 |
| nDCG@1 | 0.785714 | 0.656190 | 0.581429 | 0.609048 |
| nDCG@3 | 0.663725 | 0.623159 | 0.534847 | 0.529872 |
| nDCG@5 | 0.649284 | 0.618992 | 0.537600 | 0.551415 |
| nDCG@10, primary | 0.675802 | 0.672920 | 0.570044 | 0.603411 |
| Precision@10 | 0.181000 | 0.198000 | 0.165000 | 0.180000 |
| Recall@10 | 0.742500 | 0.815000 | 0.673333 | 0.729167 |

The full sealed reports also retain MRR and every metric at 1/3/5/10/20.

### Predeclared selection guards

Promotion required higher mean-arm nDCG@10 and no more than 0.02 absolute loss in either Precision@1 or Recall@10 for **each** arm.

| Change from same-index hybrid | DE | CU |
|---|---:|---:|
| nDCG@10 | -0.105758 | -0.069510 |
| Precision@1 | -0.200000 | -0.040000 |
| Recall@10 | -0.069167 | -0.085833 |
| Per-arm loss guards passed | No | No |

Mean-arm nDCG@10 also decreased. The [sealed selection](../../../evaluations/entities-development/experiment-268e4a67d1b24d67afd27c979808d5b3/pipeline-entity-selection.json) records `eligible_by_per_arm_guards: false`, `higher_mean_arm_ndcg10: false`, `recommended_profile: hybrid` and `test_results_used: false`.

### Arm differences and uncertainty

| Profile | CU minus DE nDCG@10 | Paired family bootstrap 95% interval |
|---|---:|---|
| Hybrid control | -0.002882 | [-0.057570, +0.051457] |
| Entity-weighted hybrid | +0.033366 | [-0.020367, +0.084152] |

These intervals use 10,000 paired bootstrap resamples over ten development families. They compare **CU against DE within a profile**, not entity weighting against its control within an arm. Both intervals include zero; neither establishes an arm winner. The profile-effect rows above are point-estimate changes, without profile-effect confidence intervals.

## Verification and operations

| Check | Result |
|---|---|
| Complete evaluation regression suite | 195 cases passed in 711.44 seconds |
| Repository Ruff and strict application typing | Passed; 77 source modules |
| Source distribution and wheel | Built successfully |
| Raw-source and Blob audit | 300 byte hashes, empty metadata dictionaries and version-bound proofs verified |
| Independent ranking request audit | All 480 fingerprints matched original-question content/entity templates |
| Independent numerical audit | 8,000 per-query metric values and 40 family bootstrap intervals verified at absolute tolerance 1e-12 |
| Independent entity audit | All 5,880 source occurrences verified; no canonical feature assistance or client document writes |
| Historical protection | 108 protected artifacts retained their hashes |
| Actual Azure definition audit | Native NER and direct Shaper present in both skillsets; six-field schemas, whole-object projection, native-text embeddings, explicit weights 1/2 |
| CLI status | Raw-only enrichment, both snapshots present, both development profiles complete, no invalidation, no completed test profile |

The regression count covers the entire evaluation suite, including historical compatibility, GenAI paths, native NER, raw-only boundaries, error handling and profile seals. It is not a claim that the entire repository or its separate scale/recovery suite was rerun for this treatment.

| Final native-main operation | Actual attempts | Frozen ceiling |
|---|---:|---:|
| Search | 512 | 1,000 |
| Blob | 1,216 | 1,800 |
| Administration | 139 | 2,000 |
| Application embeddings | 0 | 50 |
| Observed application embedding tokens | 0 | 20,000 |
| Semantic dispatches | 0 | 0 |

The Search attempts comprise 506 successful operations, including all 480 retrieval outcomes, and six failed authorization attempts while reader grants propagated. No final retrieval outcome failed. These totals describe the final native main only; previous failed/smoke trials incurred additional operations and processing.

Only index-scoped reader access was added for queries; no new document-writer grants were made. The service retained its existing capacity and free semantic setting. No network, billing-mode or model-capacity changes, index resets or resource deletions were performed.

Native entity recognition, CU and indexer embeddings can incur charges. Their tokens and monetary cost are not returned by these projections. Zero application embedding requests does **not** mean zero indexing cost. Failed and successful trial namespaces remain preserved; cleanup requires a separate authorized operation.

## Recommendation and remaining limits

- Keep `hybrid` as the default for this entity treatment. Preserve the negative result rather than changing weights until the same development set appears favorable.
- Before another entity treatment, review general NER's semantic typing and complete-name extraction. Test a predeclared precision/category or in-pipeline validation change in a fresh versioned workspace, without supplying canonical names to the pipeline.
- Treat the previously tested content-only semantic profile as a separate alternative. This run did not evaluate it or consume additional semantic quota.
- Human reference review, validation on organizational documents and confirmatory replication remain outstanding. Parent retrieval metrics do not establish chunk support, entailment or equal-token answer sufficiency; those remain `not_evaluated`.

## Sealed evidence

- [Protocol](../../../evaluations/entities-development/experiment-268e4a67d1b24d67afd27c979808d5b3/protocol.json), [run plan](../../../evaluations/entities-development/experiment-268e4a67d1b24d67afd27c979808d5b3/pipeline-entity-run-plan.json) and [source lineage](../../../evaluations/entities-development/experiment-268e4a67d1b24d67afd27c979808d5b3/source-lineage.json).
- [Control report](../../../evaluations/entities-development/experiment-268e4a67d1b24d67afd27c979808d5b3/report-development.json) and [entity-weighted report](../../../evaluations/entities-development/experiment-268e4a67d1b24d67afd27c979808d5b3/report-development-pipeline-entity-hybrid.json).
- [DE snapshot](../../../evaluations/entities-development/experiment-268e4a67d1b24d67afd27c979808d5b3/snapshot-de_split.json) and [CU snapshot](../../../evaluations/entities-development/experiment-268e4a67d1b24d67afd27c979808d5b3/snapshot-content_understanding.json).
- [Live verification](../../../evaluations/entities-development/experiment-268e4a67d1b24d67afd27c979808d5b3/pipeline-entity-live-verification.json), [independent verification](../../../evaluations/entities-development/experiment-268e4a67d1b24d67afd27c979808d5b3/pipeline-entity-independent-verification.json), [actual pipeline provenance](../../../evaluations/entities-development/experiment-268e4a67d1b24d67afd27c979808d5b3/pipeline-entity-pipeline-provenance.json) and [code verification](../../../evaluations/entities-development/experiment-268e4a67d1b24d67afd27c979808d5b3/pipeline-entity-code-verification.json).
- [Successful native smoke verification](../../../evaluations/entities-smoke/experiment-e24f906d0dc341f8929d678138946a13/pipeline-entity-live-verification.json).
- Rejected full-corpus trials: [GenAI version 1 protocol](../../../evaluations/entities-development/experiment-cbc98496f9bf43d398e418f5d612bf94/protocol.json) and [GenAI version 2 protocol](../../../evaluations/entities-development/experiment-42daaa0c13684829b81253e28b367ef1/protocol.json).

Official contracts: [Entity Recognition V3](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-entity-recognition-v3), [Shaper](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-shaper) and [GenAI Prompt skill](https://learn.microsoft.com/en-us/azure/search/cognitive-search-skill-genai-prompt).
