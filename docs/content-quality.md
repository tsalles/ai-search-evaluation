# Content and Corpus Quality

Status: Implemented initial quality controls; model-based pilot calibration recorded separately from human approval  
Version: 0.1  
Date: 2026-10-26

## Generation controls

| Axis | Control and acceptance |
|------|------------------------|
| Subject coverage | Topic briefs, explicit integer quotas, and optional required terms. Human review checks relevance; keyword presence alone does not prove it. |
| Fictional facts | Scenario-scoped entities, amounts, dates, conditions, and units in a frozen ledger. Materialize explicit fact references and validate tables against it. Do not present synthetic rates or procedures as real banking guidance. |
| Language and locale | Default Portuguese with Brazilian formatting; English/US is the other initial configurable profile. Fixed-seed local detection requires the selected base language at confidence at least 0.90. Detection does not distinguish Brazilian from European Portuguese; review regional style separately. |
| Length | Enforce the exact word-band definition in [contracts](contracts.md). Reject under/overlength candidates within bounded attempts. |
| Word-band grace | Optional frozen tolerance up to 5%; round acceptance bounds inward to whole words, retain nominal targets/labels, and report actual counts and use of grace. |
| Genre | Explainer: at least three headings. Procedure: at least five ordered steps. FAQ: at least four question/answer pairs. Comparison: at least one table with three data rows and three columns. |
| Structure | Every item has a title, a valid heading order, nonempty business content, unique block IDs, resolved references, and no unsupported blocks. |
| Planned variation | Opt-in recipe runs require the exact frozen block IDs/order/kinds, heading levels, question headings, list-item levels, and table dimensions; retries never resample an easier structure. |
| Terminology | Optional canonical vocabulary, audience, abbreviation policy, and required terms; no forced keyword repetition. |
| Exact uniqueness | Hash normalized business payload after NFC, case folding, and whitespace collapse; exclude IDs, provenance, and standard synthetic banners. Preserve numbers, units, accents, and table relationships. |
| Lexical uniqueness | Default reject Jaccard similarity at least 0.85 over five-word shingles against accepted items. Skip neither short inputs nor tables; input length requirements provide sufficient text. |
| Candidate exhaustion | Three candidates per item by default, configurable within one to forty. Report failed slots; never relax thresholds automatically. A later increase is an audited monotonic resume action under unchanged global request/token limits. |

Initial topic inputs can describe banking products and procedures, but topics are not hard-coded to banking. Domain presets supply style and allowed synthetic fact types; arbitrary topics still use the same content contract. No real customer data, genuine identifiers, or copied proprietary documents are needed.

The experimental SaaS preset supplies fictional plan names, BRL monthly prices, first-response targets and scoped support responsibilities. Its Azure response schema binds typed table cells to compatible fact values/units and prevents bare quantitative prose outside fact references. Titles start with the complete literal scoped plan names followed by a colon and a freely authored description, preventing the decoder from changing fictional name spelling or accents. Banking authoring retains its original wire contract. After bounded systemic transport retries are exhausted, source generation stops dispatching further items instead of repeating an outage across the corpus.

SaaS source acceptance also checks every visible business-text field against the portable font's printable Latin repertoire. It rejects foreign scripts, invisible controls, object/replacement characters, reserved serialization characters, leaked JSON fields, unresolved SaaS fact markers, runs of comma-joined words and incomplete trailing causal clauses. This is separate from whole-document language probability, which can miss a short corrupt span. The producer uses the same repertoire; neither boundary strips or repairs source text. Native visual samples can reveal additional source defects that require separately recorded whole-document regeneration.

An unpublished experimental source correction preserves the failed original, imports its authoring attempts and candidate counts into the unchanged global budgets, and regenerates explicitly rejected whole documents in a separate workspace. Retained canonical and native bytes stay unchanged. Every replacement must render and pass native readback in its original frozen format/layout before acceptance can reserve facts or uniqueness. Published sources, released references and remotely measured experiments cannot use this operation.

The separate `create_quality_revision` API can correct an already published, automatically assured provisional corpus. It preserves the measured origin and creates a fresh workspace with no inherited reference, indexing requests, query vectors or rankings. All comparisons must be indexed and collected again against the corrected bytes. It refuses human-approved sources and treatment forks. This technical correction is not an additional independent replication, and earlier measured results remain separate evidence.

Fact-reference checks prevent protected-value drift; they do not prove that every free-form statement is plausible or that two paraphrases are semantically distinct. Exact and shingle checks are reproducible lexical guards, not a semantic-uniqueness guarantee. Do not add embeddings or an LLM judge implicitly. Pilot review determines whether a later optional semantic quality gate is justified.

## Logical complexity and native layouts

`generation.structure` assigns exact simple/moderate/complex quotas before authoring. Recipe choice controls arrangement independently of complexity; repetition ranges and optional groups are resolved into immutable slots. Custom declarations retain the same block and genre boundaries as the built-in catalog. See [the recipe contract](contracts.md#structure-recipes-and-native-layouts).

| Logical level | Guaranteed structural envelope |
|---------------|--------------------------------|
| Simple | Flat headings/lists, at most one table with at most four columns, no callouts |
| Moderate | At least one distinguishing feature; heading depth at most two |
| Complex | At least two distinguishing features; heading/list ceilings remain three/two |

Distinguishing features are heading depth at least two, nested lists, multiple tables, at least five table columns, and callouts. A comparison still needs its genre-minimum table at every complexity. Word count remains an independent constraint. Structural complexity labels are not a measured retrieval-difficulty score.

Opt-in length-aware sampling reduces short table/list sizes and optional groups while keeping required complexity features. Long plans provide more prose capacity. Frozen word budgets target the nominal midpoint and count materialized facts, headings, lists, and table text together. Budgets are block totals, not per-cell allowances. All authoring requests use them as guidance. SaaS requests additionally bind heading levels, null payload fields, table identities/row bounds, array counts, portable characters and frozen facts in the producer schema. Hard word-count patterns caused the tested decoder to emit escaped JSON in short headings or join paragraph words to fit a limit; they are excluded from free-text fields. Canonical acceptance still enforces the whole-document word band and the 2,048-character text ceiling. The request schema omits character-length assertions because the tested model returned HTTP 500 when those assertions intersected word patterns. These controls do not pad source text or replace final fact, structure, length and native-readback checks.

At 5% word-band grace, short/medium/long acceptance becomes 190-420, 475-945, and 950-1,680. A 417-word short item can pass; a 530-word short item still fails. Omitting the option preserves strict historical bands. Tolerance and length-aware choices are semantic configuration and cannot silently change on resume.

`rendering.layout_weights` independently samples supported native arrangements after format allocation. No renderer summarizes text to fit slides or changes business meaning. Compact XLSX refers to narrative partitioning, not flattened table data. Markdown supports semantic structure but has no physical column/page difficulty levels.

Canonical shape signatures exclude IDs, roles, wording, and advisory word budgets. Counts/signatures describe structural diversity separately from lexical uniqueness; repeated recipes are valid. Reports distinguish accepted and verified content and show native layout counts by format. The advisory review sample covers every present format/complexity/layout combination.

## Legacy native structure profiles

Configurations without the new controls retain baseline and bounded complex profiles. Do not combine a legacy profile with its replacement control. Profile support is explicit; generation cannot request a structure that the selected formats would silently discard.

| Structure | Baseline | Complex profile |
|-----------|----------|-----------------|
| Logical sections and headings | At least two levels supported | Long sections and continuation boundaries |
| Lists and procedures | Native ordered/unordered items | Nested lists to depth two, explicit exceptions/callouts |
| Tables | Rectangular, visible headers and units | Multiple tables, long cells, wide tables, repeated headers where applicable |
| Pagination/partitioning | Reflow without lost text | DOCX/PDF page breaks; PPTX continuation slides; XLSX multiple sheets |
| Layout variation | One logical reading flow | Two-column prose in PDF/DOCX; equivalent ordered sections elsewhere |
| Spreadsheet/presentation data | Actual cell/table structures | Multiple native tables and section partitions |

Merged data cells, rasterized tables, hidden facts, notes-only answers, charts without textual data, mathematical typesetting, and image-only content are deferred. Repeated table headers and shared fictional scenario facts are allowed inside the documented scope; duplicating an entire content item into another format is never allowed.

Enforced minimum font sizes: DOCX/XLSX 11 pt, PDF 10 pt, PPTX 14 pt. Continuation is preferable to shrinking below these bounds. Use bounded table widths and text-length checks; fail a genuinely unrenderable block with its ID. Do not omit rows, cut text, or substitute a paragraph for a native table. PPTX headings remain with their first following body/list fragment or table header/data row.

Fact placeholders insert the full canonical value and unit. Composition rejects adjacent repeated unit suffixes, such as `{{fact:rate}} ao ano` when that fact already includes `% ao ano`. Prompt version 3 also asks for singular/plural agreement and distinct labels for equal-valued attributes. These checks do not constitute a general grammar or semantic correctness oracle.

Unit comparisons recognize only explicit known grammatical variants, including Portuguese and English singular/plural forms. Values, currencies, periods, and business/calendar day distinctions remain strict; unknown units retain case-sensitive literal identity. Unit labels and displays are never rewritten to force agreement. Equivalent repeated unit forms after a placeholder are rejected too.

## Fidelity acceptance

Every renderer must pass both structural inspection and independent readback of its saved artifact:

1. Every canonical business-text block is reconstructable after NFC and layout-whitespace normalization, preserving accents.
2. Every protected fact retains its value, unit, scope, and relevant condition.
3. Every table preserves row membership, column association, and cell meaning. Token presence alone is insufficient.
4. Numeric XLSX cells retain the allowed decimal precision and have visible units/labels; money must not depend on invisible number-format metadata for meaning. Values exceeding Excel's verified precision are rejected or explicitly represented as text according to the declared column type.
5. PPTX/PDF text is native, not a screenshot. Required content is not relegated to notes, comments, hidden cells, or metadata.
6. Geometry checks verify planned bounds; readback verifies preservation. Representative visual review checks clipping and reading order that libraries cannot prove for every Office/viewer version.
7. Only declared structural decoration, repeated headers, page/slide numbers, and the fixed synthetic-content notice may be added.
8. Recipe runs compare native heading/list levels in MD/HTML/DOCX/XLSX/PPTX. PDF preserves visible text, table associations, and geometry; it does not claim tagged-PDF heading/list semantics. Layout checks inspect actual DOCX columns, PDF text geometry, HTML sections, XLSX narrative sheet counts, and PPTX primary-heading slide starts.

Keep block-to-artifact location mappings in validation reports outside the corpus. A validator failure prevents publication and reports the affected content/block. Distinguish renderer defects from deliberately difficult yet valid structures.

## Retrieval-study safeguards

- Upload/index only the published corpus directory. Do not index canonical JSON, rejected attempts, fact ledgers, reports, ready-manifests, or planning documents.
- Use opaque filenames. Business titles and labels in the document body are legitimate content; filenames and sidecars must not reveal relevance labels.
- Allocate formats after authoring and quality acceptance. Do not prompt the model to simplify a topic for PowerPoint or expand it for PDF.
- Balance topic/length strata, adding logical complexity for recipe runs, while preserving exact format totals. Report genre, structure, and exact word distributions by format as possible residual confounders.
- Warn on sparse strata or missing formats; a nonzero weight does not guarantee representation in a tiny corpus.
- Keep near-miss product names, thresholds, exceptions, dates, and table lookups plausible but explicit. Avoid ambiguous contradictory claims unless a future version introduces labeled version/conflict scenarios.
- Use multiple independent seeds when comparing engines. Unique content per format prevents a paired identical-content experiment, so cross-format results are matched-group observations, not proof of a pure causal format effect.
- Corpus integrity validation is not retrieval evaluation. No query set, qrels, expected-answer export, ingestion job, or engine score is included.

## Human review and calibration

T25 produces a 12-document live pilot covering all formats, with all pilot documents reviewed for relevance, natural Brazilian Portuguese, factual coherence, and visual fidelity. This is a release gate, not a paid judge loop.

For later generated corpora, reports select a seeded review sample of `min(N, max(number_of_present_formats, ceil(0.02 * N)))` documents, including each present format. The versioned method first selects one seeded item per present format, then fills the remaining places from the other assignments without replacement. It never changes assignments or duplicates published content.

Render, resume, and allocation-aware validation results expose the sample in `details.review`, outside the indexable corpus. Its status is `human_review_pending` and its reviewer is null. Automated validation and model-based visual review do not grant human approval. Record any later human decision separately with reviewer, date, viewer, findings, and the reviewed source/artifact hashes.

Calibrate language confidence, duplicate threshold, lengths, and layout limits against pilot findings. Any change is versioned, reruns affected regression fixtures, and requires plan/config approval; do not change thresholds in the middle of a run.
