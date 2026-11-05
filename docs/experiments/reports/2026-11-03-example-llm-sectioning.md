# Example LLM sectioning retrieval experiment

Date: 2026-11-03, local UTC-03:00

Status: Executed and independently verified; exploratory repeated-corpus evidence; automated reference and answer assessment

## Decision

**Do not adopt the tested LLM sectioning or metadata-weighted retrieval policy. Keep tuned Document Extraction plus Text Split as the practical default.**

The hypothesis that this implementation improves retrieval was not supported. On the 93-family comparison cohort, LLM sectioning reduced BM25 parent nDCG@10 by **0.097935**, with a paired family-bootstrap interval of **[-0.113710, -0.081816]**. Matched hybrid also regressed. Development selection retained metadata **off**, and the small equal-budget answer-support diagnostic showed no compensating advantage.

This result concerns the tested planner, packing policy, corpus and query profiles. It does not establish that every LLM-assisted ingestion policy is inferior.

## What ran

- Reused the same 996 immutable native files from 166 families: 166 files each of PDF, DOCX, XLSX, PPTX, HTML and Markdown.
- Used Document Extraction in both the existing DE control and the challenger. The challenger called an authenticated custom skill for source-block planning and deterministic original-text materialization.
- Applied the same native Text Split maximum of 2,000 characters and 200-character overlap, then the same Search embedding skill and embedding space.
- Preserved Microsoft analysis, BM25 `k1=2.4`, `b=0.75`, and the existing HNSW configuration. Hybrid used matched `k=50`, vector weight `0.5`.
- Selected metadata weighting on 33 development families, then compared policies on the 93 families still named `calibration` in the inherited protocol.
- Retained the existing tuned CU index as a reference. It uses native 1,024-token chunks with zero overlap.
- All families had supplied results in earlier studies. This is exploratory repeated-data analysis, not independent confirmation.

### Raw-document-only boundary

Uploads contained raw file bytes and MIME types, with no custom Blob metadata. The indexer performed extraction, invoked the sectioning endpoint, materialized sections, split them and generated document embeddings. No local plans, canonical titles, account-name catalogs, facts or qrels supplied indexing features. Document embeddings used chunk content alone.

The model returned only source-bound title/heading references and ordered section starts. Python sliced the exact extracted source text; the model did not rewrite section bodies. Source text and raw model audits were retained as non-searchable provenance, excluded from retrieval fields and answer contexts.

The six-format smoke passed all twelve files after an auxiliary audit-field schema repair. The remaining incremental run processed 984 sources with zero failed items, errors or warnings. The final snapshot covered all 996 source identities.

## Retrieval comparison

Metrics deduplicate parents within the same raw top-50 chunk budget. Binary relevance is grade at least 2; nDCG uses gains 0/1/3/7. Paraphrases average within intents, intents within families, then families. Intervals use the inherited paired family-bootstrap procedure.

### BM25

| Policy | Parent nDCG@10 | Precision@1 | Recall@10 |
|--------|----------------|-------------|-----------|
| Tuned DE control | 0.768648 | 0.608602 | 0.935663 |
| Tuned CU reference | 0.775082 | 0.588172 | 0.953405 |
| LLM sections, metadata off | 0.670713 | 0.560215 | 0.815681 |

| Challenger minus DE | Effect | Paired 95% interval |
|---------------------|--------|--------------------|
| BM25 nDCG@10 | -0.097935 | [-0.113710, -0.081816] |
| Matched hybrid nDCG@10 | -0.063188 | [-0.083976, -0.042278] |

Both Precision@1 and Recall@10 also failed the declared 0.02 loss guards relative to the DE control.

### Matched hybrid

| Policy | Parent nDCG@10 | Precision@1 | Recall@10 |
|--------|----------------|-------------|-----------|
| Tuned DE control, matched query policy | 0.593723 | 0.607527 | 0.744892 |
| Tuned CU reference, matched query policy | 0.613574 | 0.636559 | 0.765502 |
| LLM sections, metadata off | 0.530534 | 0.508602 | 0.685753 |

These are matched hybrid settings, not a new exhaustive retuning of every hybrid parameter.

## Metadata weighting did not recover quality

The index exposed only pipeline-derived literal titles and headings. Candidate weights were fixed before scoring; selection maximized development nDCG@10 subject to Precision@1 and Recall@10 loss guards.

| Development policy | nDCG@10 | Precision@1 | Recall@10 |
|--------------------|---------|-------------|-----------|
| Metadata off | 0.640603 | 0.512121 | 0.787879 |
| Soft title/heading weights, 0.5/0.5 | 0.491112 | 0.409091 | 0.630051 |
| Balanced weights, 1/1 | 0.396818 | 0.339394 | 0.514646 |
| Title-led weights, 2/1 | 0.339456 | 0.254545 | 0.478283 |

Selection retained **off**. Consequently, the selected combined policy and section-only policy are identical on the comparison cohort; their repeated rankings are not independent evidence. The table establishes the development outcome of these weights, not a confirmatory comparison of every metadata policy or evidence about unavailable semantic reranking.

Literal source grounding establishes provenance, not useful field typing, scope or ranking value.

## Equal-budget answer support

Twenty fixed answerable questions were selected before retrieval results. Each policy supplied original whole chunks under the same 4,096-token source-context cap, using exact short-alias JSON exposure. No stored full-document audit text or additional metadata was appended.

`gpt-5.4-mini` generated answers; the separate existing `gpt-6-luna` deployment assessed required claims and answer correctness. Every citation had to resolve to an actually exposed native chunk. These are automated diagnostics, not human attestations.

| Policy | Model-rated correct | All required claims supported | Mean claim-support fraction |
|--------|---------------------|-------------------------------|-----------------------------|
| DE control | 17/20 | 18/20 | 0.950 |
| CU reference | 17/20 | 17/20 | 0.875 |
| LLM sections | 16/20 | 16/20 | 0.825 |

All 60 contexts stayed within the cap. Mean context tokens were 3,781 for DE, 3,756.65 for CU and 3,928.45 for LLM sections. The diagnostic used 121 counted model attempts and 431,664 observed tokens, including one received output rejected by validation before a fresh bounded attempt. No annotation or quotation was repaired.

The sample is too small to establish general answer-quality superiority or equivalence. It provides no evidence that the retrieval regression bought better answer support.

## Fragmentation diagnostic

| Policy | Chunks | Median characters | Chunks below 200 characters |
|--------|--------|-------------------|-----------------------------|
| DE control | 3,204 | 1,921 | 2 |
| CU reference | 1,932 | 2,802.5 | 2 |
| LLM sections | 6,706 | 626 | 1,560 |

Matching maximum chunk length does not match the resulting chunk distribution. The planner produced many short sections, increasing index fan-out and changing which evidence fits into a fixed raw-candidate and context budget. This is an observed diagnostic consistent with the regression, not a separately isolated causal proof. Native-layout, minimum-section-size and non-LLM heading controls were not executed here.

Mean distinct parents in the raw BM25 top 50 were 34.58 for DE, 40.12 for CU and 30.28 for LLM sections. The more fragmented challenger therefore exposed fewer distinct parents before parent deduplication.

## Semantic scope and cost

A fresh bounded semantic readiness request returned HTTP 402 on the existing free plan. Semantic comparisons remain unexecuted; no paid upgrade occurred and no BM25 result substitutes for a semantic result.

Indexing issued 996 unique model requests and recorded **4,074,948 observed tokens**. Schema-repair reruns reused the durable request cache. Query vectors were inherited rather than recomputed, and document vectors remained Search-pipeline outputs. The challenger also required a hosted authenticated endpoint and more document chunks. These token counts are observed usage, not a monetary invoice.

The Function scales to zero, but the new private endpoint, audit storage and monitoring resources remain provisioned and can incur ongoing charges. They are isolated study resources; no automatic deletion was performed.

## Operational and integrity record

- The original source workspace was read through a verified SQLite snapshot. Original protocol, reference, qrels and database hashes remained protected.
- The candidate uses only the fiftieth index slot. Existing control text/vector hashes were checked before and after collection.
- An inherited management-group policy disables public storage access. The endpoint respects it through an isolated new VNet/private endpoint/private DNS group; existing networking and VPN settings were not changed.
- The single-tenant, secretless API authorizes the exact Search client/object identities. Live anonymous, forged-principal and wrong-audience requests were rejected.
- A Flex-incompatible worker setting was removed during provisioning. Initial deployment failures remain recorded.
- The smoke exposed Search's 32,766-byte term limit on an auxiliary audit field. An ETag-conditional amendment added a retrievable-only replacement field and updated the projection; the old unused field and failed smoke records were retained. No index was deleted and no model plan was rewritten.
- Polling was corrected to distinguish a newly dispatched indexer execution from its preceding successful smoke result.

Independent verification checked 44,722 stored-record hashes, 996 raw upload proofs, all 996 model request/response pairs, 6,706 source-grounded chunks, 10,512 logical ranking outcomes, 175,200 independently recomputed metric values and 200 paired intervals. It reconstructed 8,280 distinct query fingerprints and verified all 1,116 used question vectors against the original cache. Every original DE chunk remained present in the challenger's extracted source text.

All 60 actual evidence exposures and 116 literal citations were checked. Numeric citation-alias order was restored from the saved original chunk sequence when reconstructing the exact model-visible token count. A separate live check confirmed all 49 historical index names remain, the service has exactly 50 indexes, and anonymous/spoofed/wrong-audience callers receive HTTP 401.

## Evidence and configurations

- [Preregistered design](../../../evaluations/section-study/experiment-34f2a2502eee4caea7bc0385ed1a42bd/section-study-preregistration.json).
- [Six-format smoke](../../../evaluations/section-study/experiment-34f2a2502eee4caea7bc0385ed1a42bd/section-pilot-verification.json).
- [Full native indexer result](../../../evaluations/section-study/experiment-34f2a2502eee4caea7bc0385ed1a42bd/section-indexer-full-v2.json).
- [Metadata policy selection](../../../evaluations/section-study/experiment-34f2a2502eee4caea7bc0385ed1a42bd/section-study-metadata-selection.json).
- [Retrieval metrics and intervals](../../../evaluations/section-study/experiment-34f2a2502eee4caea7bc0385ed1a42bd/section-study-retrieval-report.json).
- [Answer-support results](../../../evaluations/section-study/experiment-34f2a2502eee4caea7bc0385ed1a42bd/section-study-evidence-report.json).
- [Independent verification](../../../evaluations/section-study/experiment-34f2a2502eee4caea7bc0385ed1a42bd/section-study-independent-verification.json).
- [Recorded configuration inventory](../../../evaluations/inventory/ai-search/inventory.json), including original submissions, pilot repair submissions/readbacks and final observed resources.

Any future section-packing or metadata experiments should select changes on development data and use fresh confirmation data before broader promotion. Do not retune against these comparison outcomes to force a positive result.
