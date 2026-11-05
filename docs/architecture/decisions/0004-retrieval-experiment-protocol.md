# 0004 Retrieval Experiment Protocol

Status: Accepted

Live experimental validation: pending

Date: 2026-10-28

## Context

The user requested a fresh-corpus comparison of Document Extraction plus Text Split against Content Understanding performing both extraction and native chunking. Original generation remains one format per accepted item. Prior runs are not inputs.

## Options evaluated

### Priorities and requirements

1. Establish fresh, independent source truth before either ingestion arm; pipeline-derived judgments would bias the comparison.
2. Compare the requested combined native policies under common retrieval; applying Text Split to CU would change the treatment.
3. Preserve existing source hashes and one-format-per-item generation; experiments must remain opt-in.

| Option | Independent fresh truth | Requested native contrast | Existing generator invariants |
|--------|-------------------------|---------------------------|-------------------------------|
| Fresh family sources and an independent reviewed reference | Meets; accepted evidence and human approval precede ingestion | Meets with separate native DE/CU arms | Meets through omitted optional family fields; adds review work |
| Existing index or retrieved-pool judgments | Does not meet fresh scope; truth can depend on retrieval | Partial; requires reindexing/control beyond the existing pool | Preserves old content but does not satisfy this protocol |
| Fresh reference with Text Split after both extractors | Meets with the same independent review | Does not meet; measures extraction with a shared external chunker | Can preserve generation, but answers a different research question |

## Decision

Choose fresh family sources with separate native arms because they meet the first two priorities. Implement a separate `docgen experiment` workflow with an immutable protocol and a checksummed SQLite evaluation workspace. Extend generation through opt-in family IDs and required scoped facts; omit absent fields to meet the compatibility priority. Use a bounded pt/en fictional banking preset, resolve actual evidence after acceptance, and require human-attested query/judgment release before ingestion.

Each arm gets separate protocol-owned Search resources over identical source hashes/prefixes. Keep common content-only hybrid settings, embedding deployment/dimensions and cached query vectors. Audit full source/chunk/vector inventories, resource versions and terminal ingestion before and after collection. Keep verified extraction loss in source denominators; operational failure blocks scoring.

Use `ir_measures` with the explicit `pytrec_eval` provider, exponential gains 0/1/3/7, binary threshold 2, first-occurrence parent deduplication and paired family bootstrap. No-answer queries receive N/A ranking metrics. Report evidence metrics as `not_evaluated` until relation-aware chunk support has its own reviewed implementation.

## Azure client choice

Use the existing HTTPX dependency for Search REST and embedding requests, and the real Blob SDK for source streaming. A stable Search SDK can omit preview CU fields; direct REST preserves the exact treatment JSON and supports transport-boundary tests without adding an SDK solely for serialization.

Pin Search queries to `2026-04-01` and CU semantic skillsets to `2026-05-01-preview`, as documented in [the CU skill reference](https://learn.microsoft.com/azure/search/cognitive-search-skill-content-understanding). Authentication uses renewable Azure CLI credentials. The application never elevates permissions or changes network policy.

## Consequences

- Paid/cloud-changing phases require explicit `--live`; preparation never modifies production indexes.
- Source, reviewed truth, snapshots, rankings and report inputs are immutable and fingerprint-bound. Interrupted staging is reconstructed from confirmed state; unknown request outcomes retain budget accounting.
- Named reviews provide a local audit trail, not authenticated reviewer identity or automated semantic proof.
- Native CU support, model deployment stability, permissions and networking remain live execution gates. Prices are not verified; indexing charges unavailable from the API remain explicitly unknown.
- Human-reviewed pilot execution, evidence support maps, ranking sensitivity and matched-format views remain separate from this core implementation.
