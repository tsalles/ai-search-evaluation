# Orchestration and Release Tasks

Status: T23 to T27 technical checks verified; human corpus approval is not recorded

## T23 Unify combined execution and recovery

- Stories: US04. Requirements: FR22, FR23. Prerequisites: T11, T22, T07.
- Scope: combined phase barrier, resume according to the original requested operation, completed-run idempotency, immutable semantic settings, and explicit budget overrides.
- Paths: `src\docgen\pipeline.py`, `src\docgen\recovery.py`, `tests\test_run_and_resume.py`, `tests\test_process_recovery.py`.
- U23: an incomplete Phase 1 never enters rendering; a generation-only run does not become combined on resume; a complete run does not generate again.
- I23: separate and combined execution have equivalent content/assignment semantics for fixed provider fixtures. Fail/restart at each checkpoint; accepted content is never requested again and a content ID never acquires a second format.
- I23 process tests: terminate only the known child process at generation/render/publication boundaries; verify Windows lock/file release and successful integrity-checked resume. Unknown remote attempts stay unknown and consume conservative budget.
- Acceptance: no configuration drift, repeated paid accepted-item generation, orphan adoption without a matching hash, or duplicate final file.
- Completion: public run/resume, monotonic audited budgets, hard-process checkpoint interruption, completed-run idempotency, and immutable accepted bytes/assignments pass. Historical completed content remains usable offline after a prompt update; unfinished authoring rejects version mixing.

## T24 Complete CLI, diagnostics, and audit reports

- Stories: US01, US06. Requirements: FR04, FR28. Prerequisites: T23.
- Scope: all documented commands, one-object JSON stdout, stderr logs, versioned summaries/reports, failure codes, provenance, requested/actual distribution, and safe messages.
- Paths: `src\docgen\cli.py`, `src\docgen\reports.py`, `tests\test_cli_contract.py`, `tests\test_reports.py`.
- U24: exit codes 0/2/3/4/130 match outcomes; unpublished corpus and unknown usage are null; no error is converted to success or zero usage.
- I24: invoke each command through the installed entry point with valid/invalid inputs and interrupted work; compare public JSON schemas/counts with on-disk reality. Sentinel credentials/authorization headers never appear in stdout, logs, or reports.
- Acceptance: dry-run and non-live doctor remain side-effect-free; only final documents are described as indexable; no retrieval evaluation package is generated.
- Completion: each CLI surface, JSON/exit-code contract, saved summary, safe provider errors, and seeded advisory review sample are tested. Reports keep `human_review_pending` separate from technical completion.

## T25 Run the bounded Azure pilot and human review

- Stories: US02, US03, US05, US06. Requirements: FR05, FR06, FR09, FR20, FR28. Prerequisites: T24.
- Scope: opt-in live 12-item, two-topic Portuguese corpus across all six formats using the existing deployment and explicit request/token budgets. No Search upload or index creation.
- Paths: `tests\live\test_pilot.py`, `examples\banking.yaml`, operator output under an explicitly selected local run directory.
- L25: generate/save, close the generation client, render offline, then validate exact totals, preserved facts, table relationships, profiles, uniqueness, usage/provenance, and absence of sidecars. Assert structural invariants, not exact stochastic wording.
- V25: review all 12 live files plus the six deterministic complex reference artifacts for relevance, natural Brazilian Portuguese, plausible synthetic facts, visual clipping, table readability, and intended reading order. Record viewer/OS/font versions and findings outside the corpus.
- Acceptance: no unresolved critical content/fidelity defect. Add deterministic reproductions for findings, fix the owning slice, rerun offline gates, and rerun affected bounded live cases. Do not lower quality thresholds silently.
- Review identity: model-based content/visual inspection is recorded as such. It does not create human approval; human acceptance remains a separately recorded external decision.
- Technical evidence: the final 12-item prompt-v3 live pilot passed with 21 requests and 96,801 reported tokens. All 40 native pages/slides, HTML/Markdown, and canonical contents received model review; no blocking defect was found. Minor remaining findings and the pending human gate are listed in the evidence ledger.

## T26 Verify Windows scale and resources

- Stories: US02, US03, US04. Requirements: FR01, FR12, FR20, FR23, FR24. Prerequisites: T24.
- Scope: a real 1,000-document offline run using all six real renderers, 1,000 distinct valid provider fixtures, bounded concurrency, and measured process resources.
- Paths: `tests\scale\test_thousand_documents.py`, `tests\fixtures\factories.py`, resource measurements in temporary test reports.
- I26: exact 250 PDF, 250 DOCX, 150 XLSX, 150 PPTX, 100 HTML, 100 MD; 1,000 accepted hashes and final files; all validators run; network is forbidden. Fixtures must pass normal quality checks and cannot be ID-only clones.
- P26: terminate the owned worker after 1,000 accepted contents and 37 real artifact writes, including 36 verified artifacts. Resume without a provider, retain all accepted hashes and existing artifact bytes, preserve the allocation, validate all 1,000 files, and verify completed-run idempotency. Allocation does not load binary artifacts.
- Acceptance: proposed peak process-tree RSS below 1 GiB on the recorded Windows reference environment, no leaked locks/handles, and successful rename/open checks after completion. Report elapsed time, disk size, requests, and memory; no unmeasured throughput claim.
- Completion: the full gate passed the actual hard-crash/recovery scenario, exact 1,000-file mix, 582,103,040-byte peak process-tree RSS, 28,009,780 document bytes, and 1,822.141-second measured run.

## T27 Close release gates and update operator documentation

- Stories: US06, US07. Requirements: FR27, FR28. Prerequisites: T25, T26.
- Scope: reproducible local validation command, installed-wheel smoke, user examples for both phases and resume, explicit limits, quality-review instructions, and task/test evidence ledger. CI remains pending a selected platform.
- Paths: `README.md`, `docs\`, `tests\test_installed_package.py`, package configuration and documented sample configuration.
- C27: every FR/US/CC maps to passing implemented tests or an explicitly recorded human gate; no dangling references, skipped required test, or unapproved behavior shift.
- I27: clean environment builds/installs the package and runs documented offline commands; full offline suite, lint, types, and packaging pass. Record L06/L25/V25/I26 evidence for the release revision.
- Acceptance: documentation distinguishes verified behavior, stochastic/human-review limits, and pending CI. No claim of bug-free software or passing unexecuted tests.
- Package scope: the source distribution includes only application source, tests, scripts, documentation, examples, and declared root manifests. Arbitrary operator output and QA directories are excluded and covered by a regression.
- Completion: 372 offline tests, branch thresholds, Ruff, strict types, builds, dependency consistency, isolated installed-wheel native workflow, and 17-document requirement/story/task/conformance traceability pass. This is engineering handover evidence, not a fabricated human release approval.
