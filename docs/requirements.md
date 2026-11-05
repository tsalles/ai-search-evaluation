# Requirements

Status: Accepted implementation baseline on 2026-10-23  
Version: 0.1  
Date: 2026-10-22  
Describes AI capability: yes

## Summary and scope

The primary user is a retrieval researcher who needs a reproducible, auditable synthetic corpus with controlled format and structure distributions. The generator produces exactly N distinct accepted content items and exactly N final documents, with one immutable format assignment per item. It supports the agreed scope in the [overview](../README.md).

Out of scope: retrieval adapters, index provisioning, retrieval metrics, benchmark questions or answer keys, OCR, scanned documents, image/chart comprehension, legacy Office formats, macros, formula evaluation, a hosted service, and remote/object-storage backends. Version 1 supports local filesystems; network shares are not a verified persistence target.

## User stories

All stories are included in the initial release. Priority orders delivery.

| ID | Priority | Independently testable user outcome |
|----|----------|------------------------------------|
| US01 | P1 | Configure topics, item count, and controls; inspect a plan without calling Azure. |
| US02 | P1 | Generate N validated, distinct content items and reuse them without generating again. |
| US03 | P1 | Render all six formats with exact allocated totals and no cross-format duplication. |
| US04 | P1 | Run both phases and resume interrupted work without replacing accepted content. |
| US05 | P1 | Obtain native, structurally varied documents with preserved facts and balanced format groups. |
| US06 | P2 | Diagnose failures and inspect provenance, counts, validation, and usage outside the indexable corpus. |
| US07 | P1 | Implement one tested slice at a time with no known failing regression gates. |

## Functional requirements

The task references below identify the primary implementation owner. Detailed test IDs are in each task and the [test strategy](test-strategy.md).

| ID | Required observable behavior | Primary tasks |
|----|------------------------------|---------------|
| FR01 | Accept unique topic IDs, nonempty topic descriptions, and integer count N in `[1, 1000]`; reject booleans, duplicates, and invalid counts before creating a run. | T03 |
| FR02 | Allocate topics uniformly unless all topics have explicit valid shares; report actual integer topic quotas and topics allocated zero items. | T03 |
| FR03 | Accept validated language/locale, audience, genre mix, length-band mix, structure profile, seed, and bounded quality/resource settings. Initial default locale is `pt-BR`. | T03, T09 |
| FR04 | Preview quotas, rounding, sparse cells, estimated workload, and constraints without inference or modifying output directories. | T03, T24 |
| FR05 | Authenticate to the selected Azure deployment using `DefaultAzureCredential` and renewable bearer tokens; never require or persist an API key. | T06 |
| FR06 | Explicitly verify the selected API, structured-output schema, token limit parameter, refusal/truncation handling, and supported optional parameters before a live generation run. Unsupported required capabilities fail with an actionable diagnostic. | T06 |
| FR07 | Persist versioned, validated canonical JSON with stable content/block/fact IDs, native table data, provenance, and a content hash. | T02, T04 |
| FR08 | Generate fictional domain scenarios with explicit fact ledgers; resolve fact references consistently and reject contradictory protected values or unresolved references. Shared scenarios use an explicitly frozen ledger. | T08 |
| FR09 | Enforce requested word bands, detected base language, genre-specific structures, and optional required terms; report that regional style and semantic plausibility still require review. | T09 |
| FR10 | Reject duplicate normalized payloads and lexical near-duplicates at the configured threshold; retain no duplicate as accepted content. Retry only within the configured limit. | T10 |
| FR11 | Accept content only after all required local quality checks pass; exhausted candidates leave a failed slot, never an empty or placeholder success. | T10, T11 |
| FR12 | Phase 1 succeeds only with N accepted immutable content items; it requires no format weights and creates no final-format documents. | T11 |
| FR13 | Accept only supported format shares in `[0, 1]` summing to 1 within the documented tolerance. Use largest-remainder rounding to produce integer totals summing to N; zero-share formats receive zero items. | T12 |
| FR14 | Assign each accepted item once using topic/length stratification, exact global format quotas, a documented balance objective, and seeded tie-breaking; report imbalance and sparse groups. | T13 |
| FR15 | Render Markdown and HTML with headings, text, lists, and tables; HTML is self-contained and contains no executable or remote content. | T04, T14, T15 |
| FR16 | Render native editable DOCX paragraphs, headings, lists, and tables, including multipage content. | T16 |
| FR17 | Render native XLSX cells and tables on sensibly divided sheets, preserving numeric/unit meaning; use literal cells rather than executing generated formulas. | T17 |
| FR18 | Render native editable PPTX text and tables over multiple slides; never hide required content in notes or images. | T18 |
| FR19 | Render text-extractable PDF with portable Portuguese glyph support and paginated tables/text; never rasterize the document body. | T19 |
| FR20 | Preserve every canonical business-text block, protected fact, and table row/column association; reject truncation, missing blocks, unsupported structures, and overflow instead of dropping content. | T20, T21 |
| FR21 | Phase 2 reads persisted accepted content and performs zero inference calls or content paraphrasing. | T22 |
| FR22 | Combined execution has a Phase 1 completion barrier, then performs the same allocation/rendering steps as separate execution. A complete run contains N final documents. | T23 |
| FR23 | Resume preserves accepted hashes, original assignments, and verified artifacts; detects changed configurations, corruption, and conflicting writers; never changes an item's format. | T05, T23 |
| FR24 | Bound requests, output tokens per request, concurrency, retries, and timeouts; record partial failures and cancellation. Budget or retry exhaustion is not reported as success. | T07 |
| FR25 | Use safe generated filenames, exclusive run ownership, same-volume atomic writes, and validated publication. Do not execute LLM text, overwrite another run, or publish a partial corpus as complete. | T05, T22 |
| FR26 | Put only final documents in the published corpus; keep canonical JSON, prompts, fact ledgers, reports, and provenance outside it. Do not generate a retrieval evaluation package in this release. | T22 |
| FR27 | For every implementation task, demonstrate its intended failing test, then passing targeted checks and the full applicable offline suite before proceeding. | T01, T27 |
| FR28 | Emit versioned reports and CLI results containing requested/actual counts, per-format totals, status, failures, quality/balance results, hashes, and known/unknown usage without credentials. | T24 |
| FR29 | Opt into exact logical complexity quotas and bounded built-in/custom recipe pools; freeze resolved block structures before authoring and preserve them across rejection/resume. Reject invalid or infeasible shapes before inference. | Structure extension |
| FR30 | Independently allocate supported native layout mixtures within each format, freeze their choices, and render without rewriting accepted content. Preserve legacy configurations and hashes when extensions are absent. | Structure extension |
| FR31 | Verify realized structures/native layouts through saved-file readback; report complexity, recipes, layout counts, signatures, sparse coverage, and accepted/verified distinctions outside the corpus. | Structure extension |
| FR32 | Allow an explicit frozen word-band tolerance up to 5%, retain nominal targets/labels, and report exact inward-rounded acceptance bounds and actual use of grace. Default to strict historical bounds. | Authoring corrections |
| FR33 | Recognize known grammatical measurement-unit variants without changing numeric values, currencies, periods, day types, unknown-unit case, or stored display labels. | Authoring corrections |
| FR34 | Opt into length-aware recipe sampling and exact frozen title/block word budgets, aim at nominal band centers after fact expansion, and reject infeasible shapes before inference. | Authoring corrections |
| FR35 | Upload a caller-selected corpus to an explicit Azure Blob container using a connection-string argument or process/dotenv value, without generation configuration, credential persistence, or inference. | Blob push |
| FR36 | Stream supported native files with preserved relative names/content types, bounded transfers, explicit overwrite/private-container creation, and truthful partial-failure/cancellation results. | Blob push |
| FR37 | Reject non-document/link/unpublished/corrupt managed input before cloud writes; keep credentials and SAS values out of application results/errors and leave local runs unchanged. | Blob push |
| FR38 | Explicitly support Entra upload with the currently logged-in Azure CLI user, ignore connection-string sources in that mode, protect bearer tokens with account-URL restrictions, and preserve caller credential ownership. | Blob Entra access |

## Invariants

- An accepted content ID has one immutable payload. An allocated content ID has one immutable format.
- A complete corpus has exactly N files, N distinct content IDs, and zero duplicate normalized payloads.
- Rendering never invokes an LLM or changes business meaning.
- No credentials or answer-bearing sidecars enter the published corpus.
- A completed item is not regenerated on resume. Unknown remote request outcomes remain explicitly unknown.
- A requested seed reproduces planning/allocation, not stochastic model output or binary file bytes.

## Conformance examples

| ID | Scenario and input | Expected result |
|----|--------------------|-----------------|
| CC01 | Generate N=3 with two equally weighted topics and valid provider responses. | Topic quotas are 2 and 1 using the stable tie rule; three accepted JSON items; no final documents. |
| CC02 | Render N=7 with PDF=0.5, DOCX=0.3, MD=0.2. | Four PDFs, two DOCX files, one Markdown file; each content ID appears once. |
| CC03 | Supply format weights totaling 0.9, NaN, a negative share, or an unknown format. | Input error before allocation, inference, or output mutation; no silent normalization. |
| CC04 | Render N=1 with PDF=0.6, DOCX=0.4. | One PDF, zero DOCX; report the unrepresented positive-share format. |
| CC05 | Fail one generation slot after three quality candidates. | Phase 1 is incomplete; accepted items remain; no complete corpus is published. |
| CC06 | Resume after a verified PDF was written but before the database commit. | Reconcile its hash; reuse the same PDF path and assignment; do not generate another format. |
| CC07 | Render without Azure credentials, with network access forbidden. | Phase 2 still succeeds from valid persisted content. |
| CC08 | Render a long Portuguese table with currency, dates, and similar product names. | All facts and table associations survive independent readback; overflow fails rather than truncates. |
| CC09 | Request a changed format mix on an already allocated run. | Explicit immutable-plan error; existing files and assignments remain unchanged. |
| CC10 | Provider returns refusal, incomplete JSON, or truncated output. | Typed failed attempt with bounded handling; never accepted or replaced with generic text. |
| CC11 | Plan 100 recipe-enabled items with simple/moderate/complex shares 0.30/0.45/0.25. | Exactly 30/45/25 frozen plans; repeated planning reproduces slots; layout changes do not change content plans. |
| CC12 | A candidate changes a planned list level, table size, question, or block order. | Reject within bounded attempts and retry the same frozen structure. |
| CC13 | Render recipe-enabled items through native layout mixtures and interrupt after an artifact write. | Recover the same assignment/layout, retain accepted content and valid native bytes, and make no new inference calls. |
| CC14 | Remove actual native DOCX columns while retaining the saved two-column layout label. | Independent validation rejects the native layout. |
| CC15 | Enable 5% grace for a short item. | Accept 190-420 inclusive; retain short as the planned label and report grace; reject 189, 421, and 530. |
| CC16 | Match numeric value one with singular/plural business-day labels. | Accept the grammatical variants unchanged; reject calendar/generic day substitution, numeric mismatch, currency/period changes, and SI-prefix case changes. |
| CC17 | Plan a short complex comparison with length-aware sampling. | Preserve required complexity/genre features, compact within declared recipe bounds, and freeze positive slot/title budgets summing to the 300-word target. |
| CC18 | Push a corpus with credentials from an argument, process environment, or UTF-8 dotenv file. | Apply documented precedence without changing process environment or exposing credentials. |
| CC19 | Push onto an existing blob without overwrite permission. | Return incomplete with explicit conflict and uploaded/failed/pending counts; do not overwrite or continue silently. |
| CC20 | Push a changed managed corpus or a run's unpublished staging directory. | Fail preflight before any storage request or resource creation. |
| CC21 | Select Entra with an account URL while a connection-string environment value exists. | Use Azure CLI/token credentials only, request the Storage token audience, report Entra mode, and never expose the token. |

## AI cost posture

| Field | Initial policy |
|-------|-----------------|
| Model-tier commitment | Use the existing `gpt-6-luna` deployment. No model substitution, embeddings service, or paid judge is implicit. |
| Latency budget | Initial request deadline 120 seconds, at most three transport attempts per candidate and three candidates per item. These bounds are not a corpus-completion SLA. |
| Prompt-stability invariant | Version prompts, wire schema, fact profiles, and semantic settings; freeze them in the run fingerprint. Resume rejects semantic drift. |
| Per-call cost ceiling | Hard controls cover one request and its configured maximum output tokens; model currency pricing is unverified, so no monetary ceiling is claimed. Stop scheduling on observed-token thresholds; report in-flight overshoot. |
| Cost-incident escalation | Stop scheduling when bounds are exhausted, checkpoint, exit incomplete, and show request/token usage and unknown outcomes. Increasing a budget is an explicit audited resume action. |

## Decision status and evolution

Runtime is accepted in [ADR 0001](architecture/decisions/0001-application-runtime.md). The user accepted persistence and rendering in [ADR 0002](architecture/decisions/0002-corpus-persistence.md) and [ADR 0003](architecture/decisions/0003-document-rendering.md) through T00 on 2026-10-23. Provider capability and authoring have actual data-plane evidence in [implementation progress](implementation-progress.md). CI platform selection remains deferred.

| Version | Date | Change | Trigger | Author |
|---------|------|--------|---------|--------|
| 0.1 | 2026-10-22 | Initial scope, requirements, conformance examples, and test-first baseline. | new work | Project planning |
| 0.1 | 2026-10-23 | User approved the implementation baseline, initial thresholds, and persistence/rendering decisions without changing scope. | other (baseline approval) | User approval |
| 0.1 | 2026-10-24 | Implemented both phases, six formats, recovery, quality controls, reports, and the CLI. Added versioned QA fixes without relaxing length/language/uniqueness thresholds. | failure (validation) | Engineering implementation |
| 0.1 | 2026-10-26 | Added opt-in frozen logical recipes and independent native layout mixtures with exact quotas, native readback, complexity-aware allocation, reporting, and historical compatibility. | new work | Engineering implementation |
| 0.1 | 2026-10-26 | Added explicit word-band grace, measurement-unit identity, and length-aware budgeted authoring after live candidates exposed false unit contradictions and short-plan overruns. Historical content remains immutable. | failure (validation) | Engineering implementation |
| 0.1 | 2026-10-26 | Added independent Blob Storage upload with safe connection-string/dotenv resolution, bounded native streams, publication guards, explicit resource controls, and partial-write reports. | new work | Engineering implementation |
| 0.1 | 2026-10-27 | Added explicit logged-user Entra upload after the target account's Shared Key and public-network policies blocked key-based uploads. Network policies remain unchanged. | new work | Engineering implementation |
