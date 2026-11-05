# Independent SaaS retrieval comparison

Status: Executed and independently audited; automated synthetic reference

Observed nDCG@10 leader: **Tuned DE + Split, BM25 + semantic**, **0.6310**, 95% CI [0.5996, 0.6601]. Tuned DE leads tuned CU on this fresh synthetic cohort.

## Fresh corpus and frozen methods

- New topic: fictional enterprise SaaS subscriptions, activation and support commitments.
- 996 new documents, 166 families and 166 native files per format: PDF, DOCX, XLSX, PPTX, HTML and Markdown. Family format composition varies.
- New seed, entity catalog, facts, prose, queries, qrels, protocol and source-run namespace. Authoring used gpt-5.4-mini, unlike the earlier banking corpus.
- Fixed evaluated cohort: 93 fresh families and 1,116 utterances per condition. The remaining 73 indexed families are distractors, not tuning data.
- Four physical indexes and ten frozen logical conditions. No retrieval/index retuning on this corpus.
- The initial authoring pass accepted 983 canonical sources. Thirteen unfinished slots used an audited recovery with tighter producer shape/word constraints and a twenty-candidate allowance. These accepted hashes remain preserved in the failed original run; acceptance alone did not establish source/native quality.
- The final revision retains 935 canonical/native documents byte-identically from its immediate predecessor and wholly regenerates 61. The first audit rejected 139 for glyph/native-fit failures; the deeper plain-text audit added 115 rejections for serialization/control residue or reserved characters. No accepted text was stripped, padded or repaired.
- All original failed sources, native files and attempts remain preserved. Every replacement retains its frozen facts, logical plan, format and native layout and passes native preflight before acceptance. Prior requests/tokens/candidate counts stay included in the unchanged 6,000-request/20-million observed-token main-run ceilings. The correction precedes all retrieval outcomes and is not another independent replication.
- A controlled heading trial preserved every accepted source and passed its native assignment after making heading/title budgets advisory. The final short procedure exposed joined paragraph words under another decoder word-count pattern. All per-slot text word budgets became guidance while character, fact, shape, whole-document length and native checks remained strict. Only that pending slot received an audited 20-to-30 candidate allowance; no other accepted document was rewritten and the main request/token caps stayed unchanged.
- Native visual QA after the previous measured revision found unresolved fact markers and malformed prose. The final source-quality correction rejects 61 whole documents and retains 935. Its origin, original 11,160 rankings and 80 diagnostic contexts are preserved and excluded here. Every final index, ranking and evidence assessment was collected again. No retrieval/index settings or family/question cohorts were retuned.
- This is a technical source correction after an earlier measurement, not an additional independent replication or pristine outcome-blind confirmation. Rejections were selected by source-only QA, not comparative ranking scores. Combined paid execution caps and usage are disclosed separately, including the superseded run.
- The last pending source repeatedly changed the spelling/accents of its fictional plan name. The producer bound exact scoped names in the title before free description, while preserving all 995 accepted sources. That pending slot used an audited 30-to-40 candidate allowance under the same main request/token caps.
- Source authoring retained 2,659 attempts and 15,307,790 observed tokens, with 15 unknown outcomes disclosed. Ten separate bounded compatibility probes remain recorded. Character limits stayed at canonical composition after controlled probes isolated a decoder failure for intersecting character-length and word-pattern assertions.
- Original DE uses 2,000 characters with 200 overlap; original CU uses 2,000 tokens with zero overlap. Tuned DE retains its native window; tuned CU uses 1,024 tokens.
- Original BM25 uses k1=1.2, b=0.75; tuned BM25 uses k1=2.4, b=0.75. Both retain Portuguese Microsoft analysis and the prior frozen HNSW settings.
- Uploads contain native bytes/MIME only and empty custom Blob metadata. All document features and embeddings originate in Search skillsets.
- Search requests were sequential. Fresh question vectors were computed only from the new questions; lexical BM25 profiles require no query vectors.

## Native indexing coverage

| Native ingestion | Source documents | Indexed chunks |
|------------------|------------------|----------------|
| Original DE + Split | 996 | 3229 |
| Original CU | 996 | 1192 |
| Tuned DE + Split | 996 | 3229 |
| Tuned CU | 996 | 1951 |

Every index contains all 996 sources. Chunk counts describe the actual native segmentation, not billed pages or a complete ingestion-cost estimate. Retrieval uses the same top-fifty chunk budget, then deduplicates parent documents.

## Results

| Policy | nDCG@10 | 95% CI | Gain over weakest | Gain 95% CI | P@1 | R@10 |
|--------|---------|--------|-------------------|-------------|-----|------|
| Tuned DE + Split, BM25 + semantic | 0.6310 | [0.5996, 0.6601] | +101.15% | [+87.41%, +116.82%] | 0.6849 | 0.7294 |
| Tuned CU, BM25 + semantic | 0.6126 | [0.5815, 0.6418] | +95.29% | [+82.12%, +110.14%] | 0.6613 | 0.7221 |
| Untuned DE + Split, semantic hybrid | 0.5848 | [0.5532, 0.6146] | +86.44% | [+73.98%, +100.37%] | 0.6602 | 0.6677 |
| Untuned CU, semantic hybrid | 0.5623 | [0.5288, 0.5942] | +79.24% | [+68.16%, +91.65%] | 0.6108 | 0.6657 |
| Tuned DE + Split, BM25 | 0.5570 | [0.5121, 0.5985] | +77.57% | [+63.97%, +92.18%] | 0.4806 | 0.7035 |
| Tuned CU, BM25 | 0.5532 | [0.5070, 0.5979] | +76.35% | [+62.90%, +90.44%] | 0.4624 | 0.6957 |
| Untuned DE + Split, BM25 | 0.4813 | [0.4398, 0.5203] | +53.42% | [+40.31%, +67.24%] | 0.4000 | 0.6284 |
| Untuned CU, BM25 | 0.4733 | [0.4272, 0.5179] | +50.88% | [+37.33%, +65.27%] | 0.4065 | 0.6145 |
| Default DE + Split, hybrid | 0.3253 | [0.2983, 0.3515] | +3.69% | [-4.13%, +12.21%] | 0.3785 | 0.3808 |
| Default CU, hybrid | 0.3137 | [0.2871, 0.3401] | +0.00% | [+0.00%, +0.00%] | 0.3699 | 0.3670 |

The weakest reference is **Default CU, hybrid**. Gains over that condition mix retrieval mode and index/native-chunk changes. The matched contrasts below isolate the named changes.

| Contrast | nDCG difference | 95% CI | Relative gain | Relative 95% CI |
|----------|-----------------|--------|---------------|-----------------|
| Tuned DE + Split, BM25 + semantic versus Tuned CU, BM25 + semantic | +0.0184 | [0.0071, 0.0297] | +3.00% | [+1.15%, +4.92%] |
| Tuned DE + Split, BM25 + semantic versus Untuned DE + Split, semantic hybrid | +0.0462 | [0.0353, 0.0572] | +7.89% | [+5.97%, +9.95%] |
| Tuned DE + Split, BM25 + semantic versus Tuned DE + Split, BM25 | +0.0740 | [0.0493, 0.0990] | +13.28% | [+8.38%, +19.04%] |
| Tuned CU, BM25 + semantic versus Untuned CU, semantic hybrid | +0.0503 | [0.0364, 0.0646] | +8.95% | [+6.35%, +11.80%] |
| Tuned CU, BM25 + semantic versus Tuned CU, BM25 | +0.0594 | [0.0291, 0.0899] | +10.74% | [+4.91%, +17.47%] |

Intervals use 10,000 paired family-bootstrap draws, with utterances averaged within intents and intents within families. Percentage ratios are recalculated inside every draw. All 45 policy pairs are available in JSON. Intervals are not multiplicity adjusted. The weakest-policy selection is descriptive; an interval containing zero does not prove equivalence.

## Corpus separation

- Native SHA-256 overlap: 0.
- Canonical SHA-256 overlap: 0.
- Normalized entity overlap: 0; question overlap: 0; pilot-catalog overlap: 0.
- Maximum cross-corpus business-text word-5 Jaccard: 0.006061, below the preregistered 0.15 ceiling.
- Similarity excludes technical metadata and includes document titles and table text. Local ordinal IDs may repeat; protocol/run namespaces are distinct.

This verifies corpus separation. Shared generator, renderers, template-based questions, model family and evaluator remain sources of common bias. Family-bootstrap intervals do not quantify shared generator or model uncertainty.

## Equal-budget evidence diagnostic

Twenty questions were selected before retrieval outcomes: four per answerable task, balanced across both utterance forms and twenty distinct families. All four policies received the same questions and at most 4,096 tokens of original whole-chunk JSON context.

| Semantic policy | Model-rated correct | All required claims supported |
|-----------------|---------------------|-------------------------------|
| Tuned DE + Split, BM25 + semantic | 17/20 | 18/20 |
| Tuned CU, BM25 + semantic | 16/20 | 16/20 |
| Untuned DE + Split, semantic hybrid | 15/20 | 17/20 |
| Untuned CU, semantic hybrid | 14/20 | 13/20 |

Answerer: gpt-5.4-mini; assessor: gpt-6-luna. The fixed required-claim-map-v2 contract was used from the first request. 161 model attempts used 585,961 observed tokens. 3 rejected received outputs remain recorded. All model usage in this final diagnostic was observed. Two received assessor outputs were retained and rejected: one incomplete output and one response containing two JSON messages. A sealed same-contract continuation allowed at most four durable attempts per request identity, within the original total attempt and token caps. Existing valid answers/assessments were reused unchanged; no partial JSON object was selected or repaired. No source, answer, claim or quotation was repaired. These twenty-question counts are diagnostic model judgments, not human ratings or precise evidence of equivalence.

## Earlier banking corpus

| Semantic policy | Banking nDCG@10 | Fresh SaaS nDCG@10 |
|-----------------|-----------------|-------------------|
| Tuned DE + Split, BM25 + semantic | 0.8158 | 0.6310 |
| Tuned CU, BM25 + semantic | 0.8041 | 0.6126 |
| Untuned CU, semantic hybrid | 0.8029 | 0.5623 |
| Untuned DE + Split, semantic hybrid | 0.8012 | 0.5848 |

These are different corpora, topics and authoring deployments. Cross-corpus score differences are not paired treatment effects. Use the fresh within-corpus contrasts to assess whether the prior selection transfers.

## Audit, resources and deliverables

- Verified 11,160 ranking request/response fingerprints, 186,000 metric values and 330 independently recomputed confidence intervals.
- Verified 80 exact exposures, 161 raw evaluator responses and 209 literal citations.
- Maximum simultaneous Search requests: 1.
- Preserved all 50 historical indexes and the historical service's capacity/billing configuration.
- New service: <https://dgsaas0e518aae.search.windows.net>. Standard S1, one replica and one partition, Entra-only authentication and paid semantic search. It remains provisioned and continues billing.
- An initial native service declaration passed preflight but failed actual creation because authOptions must be null with local authentication disabled. The corrected pinned AVM module deployed successfully; both attempts and all configurations are retained.
- [Native corpus ZIP](../../../evaluations/saas-confirmation-study/study-0e518aae-final/independent-saas-native-corpus.zip) and [distribution hashes](../../../evaluations/saas-confirmation-study/study-0e518aae-final/native-corpus-distribution-manifest.json).
- [Complete results and paired intervals](../../../evaluations/saas-confirmation-study/study-0e518aae-final/independent-comparison-results.json), [source independence audit](../../../evaluations/saas-confirmation-study/study-0e518aae-final/source-independence-audit.json), [evidence diagnostic](../../../evaluations/saas-confirmation-study/study-0e518aae-final/independent-evidence-report.json) and [independent verification](../../../evaluations/saas-confirmation-study/study-0e518aae-final/independent-study-verification.json).
- [Source correction amendment](../../../evaluations/saas-confirmation-study/study-0e518aae-final/source-correction-amendment-v1.json) and [complete corrected-source audit](../../../evaluations/saas-confirmation-study/study-0e518aae-final/corrected-source-audit-v1.json).
- [Heading decoder amendment](../../../evaluations/saas-confirmation-study/study-0e518aae-final/source-correction-decoder-amendment-v2.json) and [final-slot producer amendment](../../../evaluations/saas-confirmation-study/study-0e518aae-final/source-correction-final-slot-amendment-v3.json).
- [Final source-quality correction](../../../evaluations/saas-confirmation-study/study-0e518aae-final/source-quality-correction-v4.json) and [literal-entity producer amendment](../../../evaluations/saas-confirmation-study/study-0e518aae-final/literal-entity-title-amendment-v5.json), [final source clarity audit](../../../evaluations/saas-confirmation-study/study-0e518aae-final/final-source-clarity-audit.json), [sampled native visual fix review](../../../evaluations/saas-confirmation-study/study-0e518aae-final/final-native-visual-fix-review.json) and [combined superseded/final paid usage](../../../evaluations/saas-confirmation-study/study-0e518aae-final/combined-paid-usage-v2.json).
- [Known received-output retry amendment](../../../evaluations/saas-confirmation-study/study-0e518aae-final/evidence-known-output-retry-amendment-v1.json).
- [Study configuration inventory](../../../evaluations/saas-confirmation-study/study-0e518aae-final/experimental-inventory/manifest.json) and [submitted/live JSON views](../../../evaluations/saas-confirmation-study/study-0e518aae-final/configurations).

References remain automatically assured, not human reviewed. Findings support a synthetic decision study and do not establish production performance on organizational documents.
