# Example raw-document-only retrieval control

Date: 2026-10-30

Status: Executed, provisional reference labels, exploratory analysis

## Summary

- Both pipelines indexed the same 300 immutable native files without custom Blob metadata, canonical titles, account-name annotations or application-side document-vector writes.
- Test hybrid parent nDCG@10 was **0.599804 for DE** and **0.636861 for CU**. CU minus DE was **+0.037057**, with a paired family bootstrap 95% interval of **[-0.001896, +0.075082]**.
- The primary interval includes zero. These synthetic-source, unreviewed-reference results do not establish an arm winner.
- Content-only semantic reranking improved both arms' development point estimates without generator-assisted features. It was not run on the test split because the service remained on its existing free semantic plan.

## Frozen protocol and inputs

| Item | Executed setting |
|---|---|
| Experiment | `experiment-5bef74ccdb8e43aea99d6145ef4cf138` |
| Protocol | Version 2, `enrichment_policy: search-pipeline-only` |
| Source run | `run-029b3f322ae44048acb296616e9e3c5a` |
| Corpus | 300 documents, 50 families, 50 files in each of PDF, DOCX, XLSX, PPTX, HTML and Markdown |
| Family splits | 10 calibration, 10 development, 30 test |
| DE index | `docgen-eval-6145ef4cf138-de-index` |
| CU index | `docgen-eval-6145ef4cf138-cu-index` |
| DE native policy | Document Extraction followed by Text Split, 2,000 characters, 200-character overlap |
| CU native policy | Content Understanding semantic chunking, 2,000 tokens, zero overlap |
| Embeddings | `text-embedding-3-large`, 3,072 dimensions, common deployment |
| Query policy | Content-only hybrid, vector weight 1, raw depth 50, vector k 50 |
| Semantic treatment | Common content-only semantic configuration, development only, fail on partial/fallback results |
| New authoring | None; sources, query wording and qrels were inherited unchanged |

This is a new indexing and retrieval run on an already inspected corpus, not an independent corpus replication. The reference retains the original automated exploratory-pilot assurance. Human relevance review was not certified.

## Enforced raw-only boundary

Both indexes contain only `id`, `parent_id`, `content`, `content_path` and `embedding`. Index projections retain content, pipeline-generated embeddings and the technical source path.

- The uploader attached no custom Blob metadata, including checksum metadata. It retained local upload intents and conditional SHA-256 byte verification.
- Both skillsets received the native file data. Document embedding inputs were native DE pages or CU text-section content.
- No source-title, account-name or context-hash fields were added. There were no scoring profiles or default scoring-profile boosts.
- Semantic ranking used content only, with no title or keyword fields.
- The application performed no document merge or document re-embedding. It needed two new index-scoped reader grants and no document-writer grants.
- Canonical sources and judgments remained evaluator-only inputs for source integrity, reference checks and scoring. They did not supply document features or runtime query boosts.

No entity-extraction skill was included in this control. A future entity treatment must run in both skillsets on each arm's own extracted text, without a supplied corpus-specific catalog or cross-arm annotations.

## Coverage and cohorts

| Measure | DE | CU |
|---|---:|---:|
| Indexed source documents | 300 | 300 |
| Native chunks | 962 | 357 |
| Missing sources | 0 | 0 |
| Indexer errors | 0 | 0 |
| Indexer warnings | 0 | 0 |

The run collected 1,200 successful arm/query outcomes:

| Cohort | Families | Utterances | Answerable intents | Arm/query outcomes |
|---|---:|---:|---:|---:|
| Development hybrid | 10 | 120 | 50 | 240 |
| Test hybrid, predeclared primary | 30 | 360 | 150 | 720 |
| Development semantic hybrid | 10 | 120 | 50 | 240 |

Unanswerable utterances retain N/A ranking metrics. Metrics average paraphrases within each intent, then answerable intents within each family, then families. Precision and Recall use grade 2 as the binary threshold; nDCG uses gains 0/1/3/7. Parent deduplication precedes each cutoff, and Precision divides by the cutoff.

## Test hybrid results

| Metric | DE | CU | CU minus DE |
|---|---:|---:|---:|
| Precision@1 | 0.660000 | 0.696667 | +0.036667 |
| Precision@3 | 0.401111 | 0.413333 | +0.012222 |
| Precision@5 | 0.288000 | 0.298000 | +0.010000 |
| Recall@1 | 0.301944 | 0.310556 | +0.008611 |
| Recall@3 | 0.508056 | 0.531111 | +0.023056 |
| Recall@5 | 0.596944 | 0.621389 | +0.024444 |
| nDCG@1 | 0.650952 | 0.696667 | +0.045714 |
| nDCG@3 | 0.564590 | 0.588835 | +0.024245 |
| nDCG@5 | 0.561337 | 0.586500 | +0.025163 |
| nDCG@10, primary | 0.599804 | 0.636861 | +0.037057 |
| Precision@10 | 0.168000 | 0.179333 | +0.011333 |
| Recall@10 | 0.686111 | 0.737222 | +0.051111 |
| MRR@10 | 0.758905 | 0.788698 | +0.029794 |

The primary CU-minus-DE 95% interval is [-0.001896, +0.075082], based on 10,000 paired family bootstrap resamples over 30 test families. The sealed report also contains all metrics and intervals at 1/3/5/10/20.

## Development semantic comparison

| Profile | Arm | nDCG@10 | Precision@1 | Recall@10 |
|---|---|---:|---:|---:|
| Hybrid | DE | 0.666960 | 0.780000 | 0.735833 |
| Hybrid | CU | 0.657115 | 0.650000 | 0.806667 |
| Semantic hybrid | DE | 0.803556 | 0.810000 | 0.940833 |
| Semantic hybrid | CU | 0.788940 | 0.740000 | 0.954167 |

Semantic reranking increased development nDCG@10 by 0.136596 for DE and 0.131826 for CU. It used the same frozen indexes and shared query vectors, without title/account assistance.

The semantic-development CU-minus-DE nDCG@10 interval is [-0.038056, +0.006551]. Recall@1 did not uniformly improve: DE changed from 0.384167 to 0.338333, while CU changed from 0.280833 to 0.293333. Higher overall ranking quality does not imply improvement at every cutoff.

The test primary remained hybrid regardless of development results. No profile or arm was selected using the test scores.

## Verification and bounded operations

| Check | Result |
|---|---|
| Evaluation regression suite | 172 cases passed |
| Repository Ruff and strict typing | Passed; 76 source modules checked |
| Source distribution and wheel | Both built successfully |
| Historical report compatibility | Smoke, 300-document pilot and assisted development reports rescore identically |
| Protected historical artifacts | 61 immutable files retained their hashes |
| Raw source and Blob proofs | All 300 native hashes, empty metadata dictionaries and version-bound byte proofs verified |
| Independent request audit | All 1,200 request fingerprints matched plain-query, content-only templates |
| Independent numerical audit | 20,000 per-query metric values and 60 family bootstrap intervals verified at absolute tolerance 1e-12 |
| Actual Azure schema audit | Five technical/content/vector fields; no scoring profiles, semantic title/keyword fields or external embedding inputs |

| Operation | Actual attempts | Frozen ceiling |
|---|---:|---:|
| Search | 1,240 | 1,800 |
| Blob | 1,220 | 1,800 |
| Admin | 168 | 2,000 |
| Application embeddings | 0 | 50 |
| Observed application embedding tokens | 0 | 20,000 |
| Semantic dispatches | 240 | 260 |

The Search total includes 1,200 successful retrieval outcomes, operational scans/probes and six authorization failures while new reader grants propagated. No retrieval outcome failed. Previously validated question-only vectors were reused from 480 inherited cache entries.

The service remained Standard with one replica, one partition and `semanticSearch: free`. The run made no billing-mode, capacity or network changes, no index resets and no deletions. Native CU and indexer embedding charges are not returned by the Search API; zero application embedding tokens does not mean zero indexing cost.

## Interpretation and next treatment

- This run verifies the raw-only restriction and supplies a clean native DE/CU control. The historical assisted recommendation is not a recommendation under this contract.
- Both arms reproduced the prior native-size control's exact chunk-text multisets for all 300 parents. Exact text/vector hash multisets matched for 130 DE parents and 198 CU parents. Recomputed vectors and regenerated opaque chunk IDs prevent interpreting differences from earlier runs as an isolated metadata-removal effect.
- Different native chunk sizes remain part of the treatment. Parent retrieval metrics do not measure equal-token evidence quality or demonstrate that returned chunks contain sufficient answers.
- Chunk support/entailment remains `not_evaluated`. Human reference review, organizational-document validation and confirmatory arm selection remain outstanding.
- The next separate treatment can add a common in-pipeline entity extractor and measure its incremental effect against this control. It must not restore identities from canonical facts when an arm loses them.

## Sealed evidence

All paths below refer to the raw-only workspace:

- [Protocol](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/protocol.json) and [frozen run plan](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/raw-only-run-plan.json).
- [Source lineage](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/source-lineage.json), [reference](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/reference.json) and [qrels](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/qrels.trec).
- [Test hybrid report](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/report-test.json).
- [Development hybrid report](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/report-development.json) and [development semantic report](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/report-development-semantic-hybrid.json).
- [DE snapshot](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/snapshot-de_split.json) and [CU snapshot](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/snapshot-content_understanding.json).
- [Live verification](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/raw-only-live-verification.json) and [actual pipeline provenance](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/raw-only-pipeline-provenance.json).
- [Independent numerical and request verification](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/raw-only-independent-verification.json), [code verification](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/raw-only-code-verification.json) and [native re-indexing comparison](../../../evaluations/raw-only/experiment-5bef74ccdb8e43aea99d6145ef4cf138/raw-only-native-variability.json).
