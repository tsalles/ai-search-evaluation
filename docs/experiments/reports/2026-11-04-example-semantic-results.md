# Example matched semantic retrieval results

Date: 2026-11-04

Status: Executed and independently verified; exploratory repeated-corpus evidence; automated answer assessment

## Decision

**Use tuned Document Extraction plus Text Split with content-only BM25 followed by native semantic reranking for this workload.**

On the same 93-family comparison cohort, tuned DE plus semantic scored **0.815840 nDCG@10**, versus **0.804055** for tuned CU. DE's advantage was **0.011786**, with a paired 95% interval of **[0.005671, 0.018087]**.

The matched original-default comparison now supports a measured improvement for DE: **+0.014678**, interval **[0.009479, 0.019959]**. CU's end-to-end change remains inconclusive and fails its Precision@1 loss guard.

These are results for the tested native-text corpus and policies. All families had supplied earlier experimental results; this is not fresh independent confirmation or a universal extractor ranking.

## Matched comparison

All four cases indexed the same 996 immutable native files. The 93 evaluated families supplied 1,116 utterances per case pair, producing 4,464 arm/query outcomes. Corpus-wide format quotas remain 166 files each of PDF, DOCX, XLSX, PPTX, HTML and Markdown.

| Policy | Parent nDCG@10 | Precision@1 | Recall@10 |
|--------|----------------|-------------|-----------|
| Original DE, semantic hybrid | 0.801163 | 0.812903 | 0.947491 |
| Original CU, semantic hybrid | 0.802870 | 0.823656 | 0.953853 |
| Tuned DE, BM25 plus semantic | 0.815840 | 0.817204 | 0.975806 |
| Tuned CU, BM25 plus semantic | 0.804055 | 0.798925 | 0.967115 |

Original DE uses 2,000-character Text Split windows with 200-character overlap. Original CU uses native 2,000-token semantic chunks with zero overlap. Both original semantic-hybrid policies use vector k 50 and weight 1.

The tuned cases retain DE's native windows and CU's selected 1,024-token chunks. Both use `pt-Br.microsoft`, BM25 `k1=2.4`, `b=0.75`, and the `content-only` semantic configuration. Tuned semantic BM25 neither requests nor sends query vectors.

All cases return at most 50 native chunks before parent deduplication. Relevance threshold is grade 2; nDCG gains are 0/1/3/7. Paraphrases average within intents, intents within families, then families. Intervals use 10,000 paired family-bootstrap resamples.

### Effects and loss guards

| Contrast | nDCG@10 effect | Paired 95% interval |
|----------|----------------|--------------------|
| DE semantic versus matched tuned BM25 | +0.047193 | [0.029887, 0.064536] |
| CU semantic versus matched tuned BM25 | +0.028973 | [0.009636, 0.048677] |
| Tuned DE semantic versus original DE semantic | +0.014678 | [0.009479, 0.019959] |
| Tuned CU semantic versus original CU semantic | +0.001185 | [-0.006638, 0.009440] |
| Tuned DE semantic versus tuned CU semantic | +0.011786 | [0.005671, 0.018087] |

Both arms pass the 0.02 absolute Precision@1 and Recall@10 loss guards when adding semantic reranking to tuned BM25. Tuned DE also passes both guards against its original semantic pipeline.

Tuned CU loses **0.024731 Precision@1** against original CU semantic hybrid, exceeding the permitted 0.02 loss. Its nDCG interval spans zero. Do not promote that CU policy as a demonstrated end-to-end improvement.

The original-versus-tuned semantic contrasts change complete pipelines, including query policy and CU chunk size. They are not isolated measurements of index tuning. Earlier 40-family and 33-family tables remain separate historical cohorts and are not subtracted from these matched results.

## Equal-budget answer support

Twenty fixed answerable questions were registered before the retrieval outcomes. Each policy supplied original whole chunks under an exact 4,096-token JSON context cap, with short numeric citation aliases and no appended document metadata.

`gpt-5.4-mini` generated answers; the separate `gpt-6-luna` deployment assessed required facts and answer correctness. Reference facts were assessor-only and never supplied indexing or answer-generation features.

| Policy | Model-rated correct | All required claims supported | Mean claim-support fraction |
|--------|---------------------|-------------------------------|-----------------------------|
| Tuned DE semantic | 18/20 | 20/20 | 1.000 |
| Tuned CU semantic | 17/20 | 19/20 | 0.975 |
| Original DE semantic | 17/20 | 19/20 | 0.975 |
| Original CU semantic | 18/20 | 18/20 | 0.950 |

The diagnostic is small and automated. Complete context support does not guarantee a correct generated answer, and these counts do not establish general answer-quality superiority or equivalence.

### Assessment contract recovery

Two received first-format assessments added an unrequested `comparison-difference` claim. Validation rejected both. All 37 completed first-format assessments were excluded from final quality counts.

The homogeneous replacement contract requires the exact claim IDs as object keys and restricts supporting references to exposed aliases. Supported claims require at least one source selection. Questions, truth, answer prompts and context exposures stayed unchanged; confirmed identical answers were reused.

The complete diagnostic consumed **197 model attempts and 713,158 observed tokens**, within the unchanged 200-attempt and 1,000,000-token ceilings. Six received outputs were rejected: two unrequested-claim outputs, two output-limit incompletions and two malformed JSON outputs. Every rejected response and its usage remain recorded. No answer, annotation or quotation was repaired.

## Latency and operational scope

| Policy | p50 milliseconds | p95 milliseconds |
|--------|------------------|------------------|
| Tuned DE semantic | 297.00 | 391.00 |
| Tuned CU semantic | 313.00 | 406.00 |
| Original DE semantic | 391.00 | 468.00 |
| Original CU semantic | 406.00 | 488.75 |

These are successful transport-attempt timings, excluding deliberate inter-query pacing. Cases ran sequentially rather than as an interleaved performance benchmark. Twenty original semantic outcomes reused confirmed historical responses, so their timings remain historical. Do not interpret these summaries as a controlled production latency or concurrency result.

- The user explicitly authorized paid semantic execution after the preserved free-plan HTTP 402 rejection.
- The controller used one request in flight, a one-second gap between logical query calls, a 6,000-new-Search-attempt cap and a three-hour paid-window deadline.
- The study issued 4,444 new semantic requests while the standard plan was active and reused 20 original semantic outcomes. Forty nonsemantic integrity Search requests and the earlier free-plan rejection bring total new Search attempts to 4,485.
- Only `properties.semanticSearch` changed, through two single-property management PATCH operations. The original free plan was restored and rechecked. Replicas and partitions remain one each; other service properties stayed unchanged.
- All 50 historical index names remain present. No index, skillset, indexer, datasource, document field or document vector was changed.
- No documents were regenerated or reindexed. No new document or query embedding inference occurred. Existing raw-only enrichment boundaries remain enforced.
- Usage counts and returned model tokens are recorded; a currency invoice is not attributed. Standard semantic billing was service-wide during the temporary window.

## Verification and configurations

Independent verification checked 168,976 stored-record hashes, all 4,464 ranking outcomes, 74,400 per-query metric values, 120 paired intervals, all 80 exact-budget exposures, 197 raw evaluator responses and 199 literal citations. It reconstructed request fingerprints and preserved original source-workspace checksums.

The study inventory contains 16 live resource definitions, four exact query-request examples and three billing-state snapshots. The historical global inventory remains available separately.

- [Paid execution amendment and fixed cohorts](../../../evaluations/semantic-confirmation/study-20261104/paid-continuation/paid-execution-amendment.json).
- [Tuned semantic report](../../../evaluations/semantic-confirmation/study-20261104/paid-continuation/tuned-semantic-report.json).
- [Original semantic report](../../../evaluations/semantic-confirmation/study-20261104/paid-continuation/original-semantic-report.json).
- [Matched effects and guards](../../../evaluations/semantic-confirmation/study-20261104/paid-continuation/semantic-comparison-results.json).
- [Homogeneous answer-support report](../../../evaluations/semantic-confirmation/study-20261104/paid-continuation/semantic-evidence-report.json).
- [Fixed-claim assessment contract](../../../evaluations/semantic-confirmation/study-20261104/paid-continuation/semantic-evidence-contract-v2.json).
- [Independent verification](../../../evaluations/semantic-confirmation/study-20261104/paid-continuation/independent-semantic-verification.json).
- [Study Search JSON inventory](../../../evaluations/semantic-confirmation/study-20261104/paid-continuation/semantic-configuration-inventory.json).
- [Restored service configuration](../../../evaluations/semantic-confirmation/study-20261104/paid-continuation/service-restored.json).
- [Historical configuration inventory](../../../evaluations/inventory/ai-search/inventory.json).

Production promotion still needs representative fresh data and human relevance/evidence review. Current serving must respect available semantic allowance; quota failures must not silently fall back to BM25 or hybrid.
