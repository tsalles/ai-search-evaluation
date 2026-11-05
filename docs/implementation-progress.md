# Implementation Evidence

Status: Technical verification and independent model QA complete; human approval is not recorded  
Version: 0.1.0  
Updated: 2026-10-24

Both phases, all six native formats, combined execution, recovery, validation, and the CLI are implemented. This ledger distinguishes offline tests, actual Azure calls, model-based visual review, measured scale, and external human approval.

## Task and test ledger

Every implementation slice used a targeted failing behavioral contract before implementation, followed by targeted checks and the applicable regression gate. Review tasks do not have fabricated unit-test RED results.

| Task | Implemented contract and primary tests | Evidence |
|------|---------------------------------------|----------|
| T00 | Requirements, task/test traceability, persistence/rendering decisions | User approved the baseline on 2026-10-23 |
| T01 | Package, CLI bootstrap, isolated wheel install | Five initial failing contracts; six initial green tests plus lint/types/build |
| T02 | Immutable canonical models, references, typed tables, serialization/hash | 25 initial failing contracts; 31 cumulative green tests |
| T03 | Safe configuration, quotas, reproducible read-only planning | 12 initial failing contracts and a persisted-Decimal regression; 70 cumulative green tests |
| T04 | One-item persisted Markdown tracer, separate/combined parity | Five initial failing contracts; 76 cumulative green tests |
| T05 | Atomic canonical files, SQLite, locks, checksums, reconciliation | 24 initial failing durability cases; corruption/handle-release regression and complete store suite |
| T06 | Actual SDK/token/HTTP boundary and live capability doctor | Provider/doctor failures reproduced before fixes; L06 and actual authoring passed |
| T07 | Separate retry owners, requests/tokens/concurrency/deadlines/cancellation | `test_execution_limits.py`, generation and audited-budget regressions |
| T08 | Frozen/shared facts, typed materialization, visible entities and units | `test_fact_composition.py`; grouped-number and repeated-unit regressions |
| T09 | Exact length bands, local language confidence, genres, profiles, terms | `test_quality_controls.py`; versioned prompt and all measurable boundaries |
| T10 | Exact normalized payload and inclusive shingle Jaccard uniqueness | `test_uniqueness.py`, independent pairwise/rational oracles, generation exhaustion |
| T11 | Complete standalone Phase 1, ordered acceptance and retained hashes | `test_generate_phase.py`; actual Azure pilot and unfinished-slot-only resume |
| T12 | Exact largest-remainder format quotas | 13 initial failing contracts; rational/property cases up to N=1,000 |
| T13 | Optimal topic/length transportation, seeded immutable assignments | `test_stratified_assignment.py`; exhaustive small-case optimality and persistence |
| T14 | Complete Markdown and renderer contract | `rendering/test_markdown.py`, artifact contract/damage tests |
| T15 | Escaped self-contained semantic HTML | `rendering/test_html.py`; independent DOM/table parsing |
| T16 | Native DOCX text/lists/tables and pagination | `rendering/test_docx.py`; saved XML and actual Word/schema QA |
| T17 | Native typed XLSX, precision/row bounds, literal formula-like cells | `rendering/test_xlsx.py`; independent ZIP/XML/cell/table readback |
| T18 | Native PPTX continuation, tables, fonts and bounded geometry | `rendering/test_pptx.py`; keep-with-next regressions and fixed native exports |
| T19 | Native text PDF, licensed portable fonts and table geometry | `rendering/test_pdf.py`; `pypdf` plus independent `pdfplumber` readback |
| T20 | Six-format complex structures and continuation | `rendering/test_complex_profiles.py`; all six reference artifacts reviewed |
| T21 | Independent fidelity and exact-set validation | `test_artifact_validation.py`; removed facts, swapped cells, hidden content, corruption |
| T22 | Offline Phase 2, staged artifacts, ready checkpoint, atomic publication | `test_render_phase.py`; exact 12-file mix and publication-boundary interruptions |
| T23 | Combined execution, audited resume and hard-process recovery | `test_run_and_resume.py`, `test_process_recovery.py`; prompt drift and retained bytes |
| T24 | Complete JSON CLI, errors, summaries and advisory review samples | `test_cli_contract.py`, `test_reports.py`; no fabricated usage or human approval |
| T25 | Bounded actual-model pilot and content/visual QA | Prompt-v3 pilot and full fresh-output model review passed the no-critical-defect gate; human approval is not recorded |
| T26 | Real 1,000-document scale, process-tree RSS, crash/resume | Passed inside the full gate; 37 pre-crash artifacts retained and 1,000 final files verified |
| T27 | Full regression/coverage/types/build, clean installation, traceable docs | All technical checks, installed workflow, and documentation traceability passed; human approval is external |

Filenames above are relative to `tests`. Planned U/I/P/L/V/C suite IDs remain mapped to requirements, stories, and conformance cases in [test strategy](test-strategy.md). They are not claimed to be literal filenames.

## Regression and package evidence

- Historical complete baseline before live calibration: 350 offline tests passed; one live test was explicitly deselected. Branch-only coverage, Ruff, strict typing, and source/wheel builds passed.
- After native visual and authoring fixes: 370 non-scale offline tests passed; both paid live tests were explicitly deselected. Combined statement/branch coverage was 92%; the separate 85% overall and 95% critical branch-only gates passed. Ruff, strict mypy for 50 application files, and both package builds passed.
- A later source-distribution regression reproduced inclusion of an arbitrary operator/QA directory. The explicit source-package allowlist fixes it; all three packaging/installed-entry-point tests pass.
- Final full run: **372 passed, zero failures/errors/skips, two paid live tests explicitly deselected**. Overall branch coverage is **1,129/1,308 = 86.31%**; critical branch coverage is **225/236 = 95.34%**. Combined statement/branch coverage is 92.23%. Ruff, strict mypy for 50 application files, dependency consistency, and source/wheel builds passed. The full test run took 2,160.54 seconds on this shared host.

The local command is `.\scripts\check.ps1 -q`. It runs the entire offline suite, branch-only coverage gates, Ruff, strict application typing, and source/wheel builds. No required offline test is hidden by a marker or xfail.

Coverage's displayed total combines statements and branches. Coverage measures exercised code, not absence of defects. Offline sockets are blocked; live tests require explicit `-m live --allow-live`.

## Actual Azure evidence

The existing `example` / `gpt-6-luna` deployment accepted renewable `DefaultAzureCredential` bearer tokens through the v1 Responses API. L06 passed with 527 reported tokens, and a separate actual authoring smoke passed with 2,935 reported tokens. No infrastructure or RBAC was changed.

The adapter:

- Uses `https://ai.azure.com/.default`, `store: false`, strict JSON output, bounded output tokens, and no SDK retries.
- Validates the response fields the application consumes rather than requiring unrelated optional SDK metadata absent from Azure.
- Preserves missing usage/model-version data as null. The API did not provide a model-version header; the management-plane version is not substituted.
- Restricts local authentication to `AzureCliCredential` when the documented environment setting is used. Interactive browser/broker sign-in is excluded.

Earlier notes that T06 was blocked at 174 tests described a temporary authorization checkpoint. The user's subsequent direction authorized the bounded planned tests, and actual data-plane evidence supersedes that checkpoint.

## Live pilot and calibration

The retained prompt-v2 pilot is `run-5e71741dfa2e4a4092ce3dbb6f30b846`. It contains 12 accepted items and exactly:

| PDF | DOCX | XLSX | PPTX | HTML | Markdown |
|-----|------|------|------|------|----------|
| 3 | 3 | 2 | 2 | 1 | 1 |

Phase 2 and final validation ran with sockets and Azure credential construction explicitly forbidden. All accepted source hashes survived rendering and resume. Only documents are in the corpus.

The first attempt retained nine accepted items and failed three slots. A regression fixed valid localized thousands separators, then an audited candidate-limit increase from three to five completed only the missing slots. Request and observed-token caps were not silently increased.

Recorded usage: **25 requests, 110,804 observed tokens, one unknown outcome** from a timeout. Total usage remains null. No monetary estimate or exactly-once billing claim is made.

Model content review found low-severity wording defects: repeated unit periods, singular/plural agreement, an unclear pair of equal-valued attributes, and redundant transfer units. Prompt version 3 explicitly addresses these cases, and composition now rejects adjacent repeated units rather than rewriting prose. The old accepted corpus remains immutable; fresh live output is required to assess the changed instructions.

### Final prompt-v3 pilot

The current pilot is `run-0a33eff14dde4c7e8c2ccfd3703215f8`, with the same exact six-format mix above. Generation, network/credential-forbidden rendering, and independent corpus validation passed. All 12 accepted contents use prompt version 3.

The first attempt accepted 11 items; one long slot exhausted its three-candidate limit, including an overlength rejection. An explicit audited increase to five candidates completed that slot. All 11 earlier hashes remained unchanged; the original 108-request and 250,000-observed-token caps were not increased.

Final recorded usage: **21 requests, 96,801 observed and total tokens, zero unknown outcomes**. This is this pilot's usage, not a total for all earlier experiments. Independent model review covered all 40 native Office/PDF pages, 11 contact sheets, actual HTML/Markdown, and all 12 canonical contents.

No blocking content/fidelity defect, numerical contradiction, real customer identifier, PPTX orphan heading, clipping, overlap, or visible content loss was found. All 12 published hashes still match the ready manifest.

The fresh pilot still has the following low-severity review findings. They are disclosed rather than silently editing accepted content, expanding the paid judge scope, or claiming a general semantic/grammar oracle:

| Location | Remaining finding | Interpretation |
|----------|-------------------|----------------|
| `item-000010`, `criterios-paragrafo`, DOCX page 1 | `40 transferências/mês por mês` | Nonidentical wording can repeat a unit beyond the exact adjacent-suffix guard |
| `item-000011`, `paragrafo-acesso`, Markdown | `até 3 tentativas vezes` | Redundant count nouns remain a free-form language review concern |
| `item-000003`, selected FAQ answers, DOCX pages 1 to 2 | Unaccented unit labels such as `dias uteis` | Base-language confidence does not establish orthographic quality |
| `item-000003`, contestation FAQ | The question concerns filing time while the answer gives analysis time | Human review should distinguish related but different procedural intervals |
| XLSX print previews, items 2 and 9 | Some section headings end a printed page | Native worksheet cells and following rows remain intact; derived PDF print pagination is not the corpus format |

The prior singular `1 dias úteis` and equal-valued deposit/fee conflation were not observed again. The remaining findings do not alter protected values or automated native-fidelity results. Human content acceptance remains pending; curate or regenerate before using this pilot where these linguistic distinctions matter.

## Native visual review

The reviewer is an independent AI model, not a human approver.

- Initial inspection covered 68 actual Office/PDF pages, 15 contact sheets, all 12 canonical documents, pilot HTML/Markdown, and all six complex references.
- Microsoft Word, PowerPoint, and Excel exported readonly synthetic files to PDF. The original native files were not modified. PDF rasterization used `pypdfium2`.
- Complex references intentionally repeat `apoio` as a layout stressor; this is not production-corpus quality evidence.
- Representative complex DOCX/PPTX packages passed schema validation. Browser inspection confirmed readable semantic HTML, no external assets, and no table-cell overflow. An independent Markdown preview preserved escapes, structure, and tables.
- Visual review found three PPTX orphan headings. Five deterministic following-content cases failed before the repair. The renderer now reserves space for the first actual paragraph/callout/list fragment or native table header/data row.
- Fixed readonly native exports were re-reviewed across **39 slides and seven contact sheets**. All three headings share a slide with their following content. No new clipping, overlap, content loss, or orphan headings were observed.
- Published prompt-v2 files and all 12 accepted hashes remained unchanged. QA copies stay outside the corpus.
- Native viewer versions: Word, PowerPoint, and Excel **16.0.20527.20088** on Windows 11. Exact Arial regular/bold and packaged Vera regular/bold SHA256 fingerprints are retained with the visual evidence.

Model review reduces risk but does not establish human approval or universal Office/viewer behavior. Runtime results continue to expose `details.review.status = human_review_pending` with a seeded advisory sample.

## Scale evidence

The first real offline 1,000-item run passed normal quality/uniqueness acceptance, all real renderers, independent native validation, exact quotas, completed-run resume, and directory rename checks:

| Measurement | Recorded baseline |
|-------------|-------------------|
| Format counts | 250 PDF, 250 DOCX, 150 XLSX, 150 PPTX, 100 HTML, 100 Markdown |
| Peak process-tree RSS | 330,403,840 bytes, below 1 GiB |
| Document bytes | 27,990,107 |
| Elapsed time | 3,791.687 seconds on the loaded shared Windows host |
| Provider-fixture calls | 1,000; fixtures pass normal acceptance and are not ID-only copies |

The final hard-crash variant passed inside the full gate. It terminated the known worker subtree after 37 real artifact writes, retained 36 verified artifacts plus the valid uncommitted file, resumed without a provider, preserved all accepted hashes/allocation/artifact bytes, validated all 1,000 files, and checked completed-run idempotency and handle release.

| Measurement | Final crash/recovery result |
|-------------|-----------------------------|
| Format counts | 250 PDF, 250 DOCX, 150 XLSX, 150 PPTX, 100 HTML, 100 Markdown |
| Peak process-tree RSS | **582,103,040 bytes**, below 1,073,741,824 bytes |
| Document bytes | 28,009,780 |
| Elapsed time | 1,822.141 seconds |
| Provider-fixture calls | 1,000 before termination; no provider used on recovery |
| Environment | Windows 11 build 26200, Python 3.12.10 |
| Native libraries | python-docx 1.2.0, python-pptx 1.0.2, openpyxl 3.1.5, ReportLab 4.5.1, pypdf 6.21.0, pdfplumber 0.11.10, NetworkX 3.7 |

No throughput SLA is inferred from a shared-host measurement. Scale fixtures demonstrate capacity and structure handling, not the linguistic quality of 1,000 live LLM documents.

## Packaging, operation, and external gates

- Source distributions explicitly include source, tests, scripts, documentation, examples, and declared manifests. Runs, virtual environments, arbitrary operator output, and QA previews are excluded.
- The clean installed-wheel check passed in isolated Python mode with the module loaded from its installed site-packages. It generated 12 accepted canonical fixture contents, invoked installed CLI planning/non-live diagnostics/render/validate/resume entry points, produced the exact native six-format mix, and retained all hashes after resume. Sockets and Azure credential construction were forbidden. Fixtures are explicitly offline replays, not new inference.
- CI/source-control hosting remains intentionally deferred. This workspace has not been initialized, committed, pushed, or deployed by this implementation.
- No Search upload, ingestion job, queries, qrels, expected-answer package, or retrieval benchmark was created.
- Human content/release acceptance is not recorded. Any later approval needs reviewer, date, viewer, findings, and the reviewed hashes; technical `complete` does not mean human-approved.
- No claim of bug-free software, semantic deduplication, regional-dialect certainty, or retrieval-engine quality is made.
- Code quality's four critical criteria pass: requirement/ADR conformance, regression preservation, and behavior-focused coverage including reproducing bug tests. Git/CI traceability is deferred as requested. Dependency consistency is checked; an advisory-database security audit is not claimed.
- Documentation validation passed for **17 Markdown documents, 41 local links/anchors, 83 implemented source/test paths, 28 tasks, 28 requirements, seven stories, and ten conformance cases**. Dependencies are acyclic.
