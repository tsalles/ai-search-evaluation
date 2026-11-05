# Test Strategy

Status: Implemented suites and technical gates verified; external human approval is not recorded  
Version: 0.1  
Date: 2026-10-26

## Test layers and doubles

| Layer | Real behavior under test | Boundaries that may be doubled |
|-------|--------------------------|-------------------------------|
| Unit/contract, `Uxx` | Public configuration, models, quality, quotas, and result/error behavior | Clock, randomness source, external credentials/HTTP |
| Property, `Pxx` | Quota invariants, seeded planning, uniqueness oracle, optimal balance, recovery invariants | Bounded generated inputs |
| Integration, `Ixx` | Real SQLite/filesystem, real renderers, independent saved-file parsing, CLI and wheel | Azure transport/model responses only |
| Live, `Lxx` | Existing deployment, Entra data plane, actual API/schema behavior, real generated output | None for the tested Azure interaction |
| Visual/human, `Vxx` | Topic relevance, plausibility, regional language, clipping, reading order | Record viewer/environment and whether the reviewer is a model or a human |
| Review, `Cxx` | Approval, traceability, and release evidence | No fabricated automated result |

Use pytest and Hypothesis; use a test network guard and fake clock rather than wall-clock sleeps. Exercise public interfaces and observable files/results. Do not mock owned orchestration, SQLite, native renderers, or validators in integration tests. External HTTP uses an in-memory transport, not a public endpoint.

Current evidence and exact executed counts are in [implementation progress](implementation-progress.md). The check script enforces branch-only thresholds separately from coverage's combined statement/branch percentage. The live-test authorization guard is tested: selecting a live suite without `--allow-live` fails before invoking Azure. Both live tests are explicitly deselected in the offline gate; neither is described as passed by that gate.

Test names state behavior. Tests must be independent, order-insensitive, deterministic offline, and assert actual output shape/value. Binary golden-file equality and full stochastic prose snapshots are unsuitable correctness oracles.

Quota, blueprint, and exhaustive-allocation properties retain their full example counts and assertions, but do not impose Hypothesis's default 200 ms CPU deadline. Coverage instrumentation and shared Windows scheduling are not application latency contracts. Generate positive-total quota vectors constructively rather than rejecting all-zero draws. The independent scale memory bound and process-recovery handshake limits remain enforced.

## Test inventory and ownership

Each ID below expands into the concrete boundary/error cases in its [task contract](implementation-plan.md). A task cannot be done because a future suite is merely named.

| Task | Required suites | Main measurable result |
|------|-----------------|------------------------|
| T00 | C00 | Human approval and coherent dependency/traceability baseline |
| T01 | U01, I01 | Working installed CLI and network-isolated test gate |
| T02 | U02, I02 | Strict schemas, exact JSON round-trip, valid realistic fixtures |
| T03 | U03, P03, I03 | Rejected invalid inputs and reproducible no-write planning |
| T04 | U04, I04 | One saved item, one real Markdown file, separate/combined parity |
| T05 | U05, I05 | Ownership, atomic-write failure, integrity/reconciliation |
| T06 | U06, I06, L06 | Correct credential/HTTP contract and verified live capability |
| T07 | U07, I07 | Exact request/concurrency/retry/budget bounds and cancellation |
| T08 | U08, I08 | Consistent facts, visible scenario distinctions, resolved references |
| T09 | U09, I09 | Exact word/language/genre/profile boundary behavior |
| T10 | U10, P10, I10 | Duplicate/near-duplicate thresholds and ordered acceptance |
| T11 | U11, I11 | Exactly N accepted items, resumable Phase 1, no final documents |
| T12 | U12, P12, I12 | Hamilton quotas and all validation/rounding edges |
| T13 | U13, P13, I13 | Exact unique balanced assignments and small-case optimality |
| T14 | U14, I14 | Markdown preservation, escaping, common renderer contract |
| T15 | U15, I15 | Semantic safe self-contained HTML |
| T16 | U16, I16 | Native DOCX structure and all source data |
| T17 | U17, I17 | Native typed safe XLSX, precision and size boundaries |
| T18 | U18, I18 | Native PPTX tables/text and continuation without shrink/truncation |
| T19 | U19, I19 | Text PDF with packaged fonts, Unicode and pagination |
| T20 | U20, I20 | Six-format complex fixtures and capability/geometry limits |
| T21 | U21, I21 | Independent validation rejects plausible-looking damaged files |
| T22 | U22, I22 | Exact offline corpus; atomic complete-set publication |
| T23 | U23, I23 | Separate/combined parity, idempotency, hard-process recovery |
| T24 | U24, I24 | CLI/result/report/exit-code contracts match disk reality |
| T25 | L25, V25 | Bounded actual-model pilot and attributed content/visual review; human acceptance remains a separately recorded gate |
| T26 | I26, P26 | 1,000 real artifacts, exact mix, resource/recovery evidence |
| T27 | C27, I27 | Traceable release evidence and clean installed-package workflow |

## Conformance and story traceability

| Requirement group/story | Mandatory evidence |
|-------------------------|--------------------|
| US01; FR01 to FR04 | U03/P03/I03, U09/I09, I24 |
| US02; FR05 to FR12 | U02/I02, U04/I04, U06/I06/L06, U08/I08, U09/I09, U10/P10/I10, U11/I11 |
| US03; FR13 to FR19 | U12/P12/I12, U13/P13/I13, U14/I14 through U19/I19 |
| US05; FR20 | U20/I20, U21/I21, V25 |
| US03/US04; FR21 to FR23 | U22/I22, U23/I23, U05/I05 |
| US04; FR24/FR25 | U07/I07, U05/I05, I22/I23, I26/P26 |
| US06; FR26/FR28 | I22, U24/I24, L25/V25, C27/I27 |
| US07; FR27 | C00, U01/I01, per-task RED/GREEN records, C27/I27 |

| Conformance case | Evidence |
|------------------|----------|
| CC01 | P03, I11 |
| CC02 | U12, I22 |
| CC03 | U12, P12, I03 |
| CC04 | U12, P12, I13 |
| CC05 | I10, I11 |
| CC06 | I05, I22, I23 |
| CC07 | I22 |
| CC08 | I16/I17/I18/I19, I20/I21, V25 |
| CC09 | I13, I23 |
| CC10 | U06/I06, I07, I11 |

## Fixture and corruption matrix

Maintain small hand-inspectable fixtures, not only randomly generated data:

- Portuguese accented words represented correctly in UTF-8, punctuation, currency/percentages, ISO dates, and locale display dates.
- Two near-miss product names, explicit numeric thresholds, exceptions, and distinct visible scenario labels.
- Numeric and literal formula-like cells; long sheet names/collisions; values around Excel precision/cell limits.
- Min/max word counts, each genre, empty/invalid fields, wrong language, and confidence/similarity thresholds.
- One-cell, multirow, multipage, wide, and multiline tables with labels required to disambiguate each value.
- Long slide/page/sheet continuation; nested lists; two-column native prose.
- Structurally valid but semantically damaged artifacts: swapped cell, missing exception, changed amount, hidden-only fact.
- Corrupt ZIP/PDF, stale/changed hash, unexpected output file, abandoned temporary file, and a valid file between filesystem/database commits.

Renderer fixture reuse across formats is allowed in tests outside published corpora; the application still forbids duplicate content in its final document set.

## Structure and layout extension

| Suite | Observable contract |
|-------|---------------------|
| [Structure planning](../tests/test_structure_planning.py) | Exact complexity quotas, reproducible slots/signatures, layout/content independence, exclusive legacy/new controls, unsupported-layout rejection before mutation |
| [Structure authoring](../tests/test_structure_authoring.py) | All four genres, three complexity levels, and three word bands; exact wire composition; rejected shape drift; retry/resume reuse |
| [Custom recipes](../tests/test_structure_recipes.py) | Bounded optional/repeated groups, invalid declarations, capacity-constrained planning, solver errors, exhaustive small-case optimality, immutable layout quotas |
| [Native structures/layouts](../tests/rendering/test_structure_layouts.py) | Every supported native layout in all six formats, nesting/table preservation, exact layout quotas, actual-column corruption detection |
| [Structure pipeline](../tests/test_structure_pipeline.py) | Complete varied six-format corpus, complexity-aware allocation/reporting, review coverage, crash adoption, zero-rewrite resume, historical serialization |
| [Authoring controls](../tests/test_authoring_controls.py) | Exact grace/rounding boundaries, unit-inflection equivalence with strict dimensions/values, budgeted short/medium/long plans, native end-to-end rendering, reports, and immutable historical authoring boundaries |

These suites cover FR29 to FR31 and CC11 to CC14 in addition to the original regression gates. Native layout checks inspect saved structures, not only stored labels. PDF geometry/text fidelity is separate from tagged-PDF semantics. The offline provider fixture fills the real frozen slots and exercises real persistence, rendering, and readback.

An initial user-run prompt-version-4 pilot accepted ten of twelve items and remained unpublished. Saved responses exposed a false singular/plural unit contradiction and repeated short-band overruns. Prompt version 5 and the corrected planning/validation controls are verified offline; no additional paid calls are implicit. Offline verification cannot establish model adherence rates, regional writing quality, equal extraction difficulty, or visual correctness in every Office/viewer version. Any later paid pilot requires explicit authorization and separate evidence.

## Blob upload verification

[Blob upload tests](../tests/test_blob_push.py) exercise the real Azure Blob SDK using an in-memory HTTP transport. They cover all six MIME types, nested names, source hashes and exact bytes, bounded block transfers, conditional no-overwrite requests, explicit private-container creation, SAS/error redaction, dotenv precedence/BOM handling, immutable environment, source mutation, local input/publication guards, partial writes, cancellation, and CLI exit/result contracts.

The test clock removes SDK backoff waits without removing retry-count assertions. Network access remains forbidden. These tests do not create storage resources or upload a real corpus. Connection strings in fixtures are generated dummy values, not operator credentials. Cloud permissions, account policies, and real connectivity require a separately authorized upload.

Entra cases exercise the real SDK's Storage token audience and bearer header, explicit identity selection, ignored connection-string sources, credential lifecycle/ownership, canonical account-URL restrictions, CLI exclusivity, unavailable sign-in, and allowlisted Azure error codes. Tokens and arbitrary server details must remain absent from results/errors. Live access probes are read-only and do not weaken storage networking or authentication policies.

## Execution gates

Implemented local commands:

```powershell
python -m pytest .\tests\test_format_quotas.py -q
python -m pytest -q -m "not live"
python -m ruff check .
python -m mypy .\src\docgen
python -m build
```

Use the smallest selector first, then run the full implemented offline suite before closing every task. The full suite includes implemented scale tests; no failing gate is hidden by a marker or xfail. Use focused checks for typing/build when unrelated files are unchanged, but T27 runs all gates from a clean install.

Offline tests must not silently reach Azure through credential discovery. Live tests are explicitly selected and enabled by an opt-in flag/environment guard. A requested live test with invalid credentials or unavailable deployment fails; it is not converted to a skip/pass.

Run L06 at provider introduction and after provider/API/auth/wire-schema changes. Run affected bounded live tests after semantic prompt changes. Run L25 and V25 for release. Paid live tests are not invoked for every unrelated pure renderer or quota edit; their exclusion is explicit, not a claim that they ran.

Enforced coverage guardrails: at least 85% overall application branch coverage and 95% for  allocation, persistence/recovery, and quality acceptance. These are secondary checks: every listed boundary/error invariant must have a behavioral test even when coverage targets already pass. Do not test third-party internals to inflate coverage.

## Failure-injection and resource rules

- Simulate external time/HTTP failures without sleeping.
- Use isolated temporary directories and child processes; terminate only known test child PIDs.
- Exercise file-write, fsync/rename, database-commit, response-persistence, validation, and publication boundaries.
- Test two writers against one run; a reader must not interpret staging as a complete corpus.
- Test response-order changes against fixed candidates; acceptance and assignment remain stable.
- Test cancellation and unknown remote outcomes without promising exactly-once billing.
- T26 uses real renderers and validators, never fake files or deduplication exemptions. Record process-tree RSS, disk size, elapsed time, platform, and dependency versions.
- Target Windows first; future Linux CI should run the same deterministic suite after a CI platform is selected.

## Release acceptance and residual limits

| Gate | Pass condition |
|------|----------------|
| Functional corpus | N accepted items, N final files, exact format quotas, unique content IDs/payloads, all source hashes unchanged |
| Fidelity | 100% required business blocks/protected facts/table associations retained; no hidden-only or rasterized business content |
| Recovery | Every tested interruption preserves assignments and verified accepted items without duplicate publication |
| Provider | Existing model passes L06; L25 generates actual content inside the explicit pilot budget |
| Quality | Required automated controls pass; V25 records no unresolved critical relevance/locale/fidelity defect |
| Capacity | I26/P26 prove 1,000 files and the proposed measured resource bound |
| Engineering | All applicable tests/lint/types/build pass; evidence maps to the release revision |

Human review cannot exhaustively prove content correctness, and lexical deduplication cannot prove semantic uniqueness. Native readback is generator integrity evidence, not a guarantee of either engine's extraction or retrieval performance. CI platform and monetary pricing remain explicit external decisions.
