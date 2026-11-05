# Example sequential semantic confirmation

Date: 2026-11-04

Status: Sequential implementation verified locally; live comparison blocked by semantic quota

## Outcome

The single sequential readiness query returned HTTP 402:

> Free Query Semantic Usage exceeded for the month.

The service remains on free semantic billing. No billing change was authorized or performed. Sequential requests address concurrent-request throttling; they do not restore the exhausted semantic allowance.

The live check produced no scoreable semantic response. The planned comparison has not run, and this follow-up does not change the existing DE recommendation.

## Frozen comparison

All cases reuse the same 996 native documents and 93 previously evaluated families, with 1,116 utterances per case pair.

| Case pair | Index and native settings | Query policy |
|-----------|---------------------------|--------------|
| Tuned DE and CU | Existing tuned indexes; DE 2,000 characters with 200 overlap; CU 1,024 tokens | Content-only BM25 plus native semantic reranking |
| Original DE and CU | Existing default indexes; DE 2,000 characters with 200 overlap; CU 2,000 tokens | Original content-only semantic hybrid |

The existing tuned BM25 outcomes provide the no-reranking controls. The four semantic cells require 4,464 logical outcomes before cache reuse and retries. All cases must retain identical questions, relevance judgments and raw source identities.

The analysis compares semantic reranking against matched tuned BM25, tuned semantic pipelines against original semantic pipelines, and DE against CU. It retains paired family-bootstrap intervals and 0.02 absolute Precision@1 and Recall@10 loss guards. Reused families provide exploratory evidence rather than independent confirmation.

## Execution safeguards

- One request gate shared by both case pairs and one whole-run process lock.
- One second between logical query calls; retry delays follow the existing bounded `Retry-After` policy.
- Request timing excludes deliberate inter-query pacing. Historical cached timings remain historical observations.
- Confirmed request caching and readiness-response reuse prevent duplicate successful dispatches.
- A 6,000-new-Search-attempt aggregate cap includes readiness, rejected requests, retries and unknown outcomes.
- Original workspaces are protected by hashes and read-only SQLite backups. Local copies retain frozen native files.
- New query attempts use a separate continuation ledger. Original protocols, budgets and historical attempt counts are not reset or increased.
- The client rejects resource updates, document writes and new embedding inference.
- HTTP 402 stops the study without retry, semantic fallback or automatic billing changes.
- A new readiness check requires an explicit flag and retains all earlier rejection evidence.

The old default workspace has already used 9,633 of its 10,000 Search attempts. Its remaining historical budget cannot support the new full comparison. The separate continuation ledger provides an explicit new query-only scope while preserving that original history.

## Verification and remaining work

The related application tests passed 82 cases. The operational tests passed 23 cases covering serialization, pacing, cooldown-free timing, cache reuse, throttle delays, quota stops, source preservation, separate request budgets, matched cohorts and paired aggregation. Strict typing passed all 83 application modules.

The real readiness attempt issued one semantic query and recorded one quota rejection. It performed no resource mutation, billing upgrade, document generation or new embedding inference.

The full retrieval comparison, equal-context answer assessment and fresh independent confirmation remain unexecuted. Paid billing would affect the whole Search service and requires an explicit decision. No unavailable semantic result is replaced with BM25 or hybrid output.

## Evidence

- [Preregistered comparison](../../../evaluations/semantic-confirmation/study-20261104/semantic-study-preregistration.json).
- [Execution and budget addendum](../../../evaluations/semantic-confirmation/study-20261104/semantic-study-execution-addendum.json).
- [Exact readiness request](../../../evaluations/semantic-confirmation/study-20261104/semantic-readiness-intent.json).
- [Raw HTTP 402 response](../../../evaluations/semantic-confirmation/study-20261104/http-rejection-000001.json).
- [Recorded readiness outcome](../../../evaluations/semantic-confirmation/study-20261104/semantic-readiness-result.json).
- [Tuned source protection](../../../evaluations/semantic-confirmation/study-20261104/source-snapshot-tuned.json).
- [Default source protection](../../../evaluations/semantic-confirmation/study-20261104/source-snapshot-default.json).
- [Implementation and integrity verification](../../../evaluations/semantic-confirmation/study-20261104/semantic-implementation-verification.json).
- [Existing Search configuration inventory](../../../evaluations/inventory/ai-search/inventory.json).
