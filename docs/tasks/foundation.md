# Foundation Tasks

Status: T00 to T07 complete  
Implemented test evidence is in [implementation progress](../implementation-progress.md). Planned test IDs remain suite identifiers rather than literal filenames.

## T00 Approve the implementation baseline

- Stories: US07. Requirements: FR27. Prerequisites: none.
- Scope: approve requirements/contracts, quality defaults, allocation objective, [ADR 0002](../architecture/decisions/0002-corpus-persistence.md), and [ADR 0003](../architecture/decisions/0003-document-rendering.md). Keep CI selection explicitly deferred.
- Paths: this plan, the proposed ADRs, and their directly affected specification sections.
- C00: verify no unresolved implementation-blocking policy remains; record human approval and any approved changes. Link/dependency/traceability checks must pass.
- Acceptance: proposed implementation baseline is accepted. This is a review task, so there is no fabricated unit-test RED result.
- Completion: the user explicitly approved the implementation baseline on 2026-10-23, including canonical JSON/SQLite persistence, native renderers, balanced exact-count allocation, and initial quality thresholds. This records the approval point, not the current implementation status.

## T01 Establish package and executable test gates

- Stories: US07. Requirements: FR27. Prerequisites: T00.
- Scope: Python 3.12 package, CLI entry point, pytest, Ruff, application typing, and package-build checks. Add dependencies only in manifests before installation.
- Paths: `pyproject.toml`, `src\docgen\__init__.py`, `src\docgen\__main__.py`, `tests\test_cli_bootstrap.py`, `tests\conftest.py`.
- U01: `--help` and `--version` return 0 without Azure credentials or output mutations; an unknown command returns input error.
- I01: build a wheel, install it in a temporary environment, and invoke the entry point. Default tests forbid external network access.
- Acceptance: targeted RED/GREEN evidence and a repeatable local validation command; no generator fake is exposed as a production option.
- Completion: RED observed; six initial tests, isolated installed-wheel smoke, Ruff, strict typing, and build gates passed before T02 started.

## T02 Define canonical contracts and realistic fixtures

- Stories: US02, US05. Requirements: FR07. Prerequisites: T01.
- Scope: versioned run/blueprint/content/block/table/fact/provenance models and provider wire schema. Create valid Portuguese baseline/complex fixtures with headings, lists, table values, currency, dates, and explicit fact references.
- Paths: `src\docgen\models.py`, `src\docgen\wire.py`, `tests\test_content_contract.py`, `tests\fixtures\`.
- U02: accept valid models; reject unknown versions, unknown fields, duplicate IDs, broken references, ragged tables, bad cell types, and invalid precision/limits.
- I02: JSON round-trip preserves business meaning, decimal values, accents, and stable serialization/hash. Wire schema stays inside verified structural limits; local validation retains stricter constraints.
- Acceptance: fixtures are independently usable by all future renderer tests; no recursive provider schema or format-specific prose field.
- Completion: strict immutable content models, typed table/fact relationships, Portuguese fixtures, shallow wire schema, and round-trip/hash tests pass. The complete gate had 31 tests before T03 started.

## T03 Implement configuration and dry-run planning

- Stories: US01. Requirements: FR01, FR02, FR03, FR04. Prerequisites: T02.
- Scope: safe YAML/JSON loading, phase-specific validation, topic/genre/length quotas, stable blueprints, secret-free fingerprint, and read-only `plan`.
- Paths: `src\docgen\config.py`, `src\docgen\planning.py`, `src\docgen\cli.py`, `tests\test_planning.py`.
- U03: N=0/1001/Boolean, duplicate topics, blank briefs, bad locale, mixed topic weights, unknown profile, and nonfinite shares fail before mutation. Phase 1 needs no rendering/provider credentials; Phase 2 needs no provider fields.
- P03: valid topic/genre/length margins sum to N for N=1..1000; a fixed seed/config yields the same blueprint semantics; zero allocations are reported.
- I03: CLI plan emits the expected shape, sparse-group warnings, and workload bounds without provider calls or directory creation.
- Acceptance: changing operational budgets does not silently change the semantic fingerprint; changing prompts/seed/semantic settings does.
- Completion: configuration/loader/planner/CLI and seeded-margin properties pass. A reproduced persisted-Decimal issue was fixed; all 70 then-implemented tests passed before T04 started.

## T04 Deliver the one-item end-to-end tracer

- Stories: US02, US03, US04. Requirements: FR07, FR15, FR22. Prerequisites: T03.
- Scope: public generation/render/run functions for one valid item, persisted canonical JSON, a minimal SQLite item checkpoint, and one Markdown artifact. Inject a provider double in tests only.
- Paths: `src\docgen\pipeline.py`, `src\docgen\store.py`, `src\docgen\renderers\markdown.py`, `tests\test_tracer.py`.
- U04: a valid provider draft becomes one accepted content payload; an invalid draft raises the typed failure and is not marked accepted.
- I04: generate saves JSON; a fresh process/API instance renders that saved item with the provider forbidden; combined execution produces one Markdown file with the same semantics.
- Acceptance: one real thin path spans planning, provider boundary, persistence, rendering, and result reporting. Missing production provider configuration fails explicitly rather than returning fixture content.
- Completion: standalone and combined one-item library traces pass, including fresh-process offline rendering and rejected invalid candidates. All 76 then-implemented tests passed before T05 started. This tracer does not expose an unfinished production-generation CLI.

## T05 Add durable checkpoints and exclusive ownership

- Stories: US04, US06. Requirements: FR23, FR25. Prerequisites: T04.
- Scope: SQLite schema/versioning, immutable content/hash checks, attempt lifecycle, cross-platform run lock, atomic same-volume writes, and recovery states.
- Paths: `src\docgen\store.py`, `src\docgen\persistence.py`, `tests\test_store.py`, `tests\test_process_recovery.py`.
- U05: conflicting lock, unsafe path, duplicate accepted identity, altered content, unknown store version, and overwrite attempts fail explicitly.
- I05: inject disk-full/access-denied/rename failure and interruption before/after each file/database boundary; reopen the store and either reconcile a matching expected hash or report integrity failure.
- Acceptance: committed accepted items survive a fresh process; unrelated files are never deleted; locks release correctly on Windows. Unresolved remote attempts retain unknown status.
- Completion: lock/integrity, process interruption, temporary-file, SQLite transaction, unknown attempt, and corruption tests pass. A Windows error-path handle leak was reproduced and fixed; all 114 then-implemented tests passed.

## T06 Connect Azure and verify model capabilities

- Stories: US02, US06. Requirements: FR05, FR06. Prerequisites: T05.
- Scope: actual Azure/OpenAI adapter, renewable credential provider, non-live/live doctor, supported-parameter record, and explicit privacy/storage behavior.
- Paths: `src\docgen\providers\base.py`, `src\docgen\providers\azure.py`, `tests\test_azure_provider.py`, `tests\live\test_capabilities.py`.
- U06: mocked external HTTP/token boundaries prove deployment-name routing, token renewal, configured credential selection, strict schema submission, and no persisted/logged token. Refusal, truncated/incomplete response, malformed JSON, unknown usage, and 401/403 have typed outcomes. Reported model-version drift is recorded and blocks silent mixed-version continuation.
- I06: the real SDK with an in-memory HTTP transport sends the expected request body, including no-server-storage when supported, and preserves safe failure details without hidden model/API fallback.
- L06: opt in to a bounded synthetic schema probe against `example`/`gpt-6-luna`; verify v1 endpoint, Entra permission, Responses API, wire schema, output/reasoning budget semantics, and required storage option. Maximum three small requests, each capped at 2,048 output tokens, with usage recorded; an inadequate probe budget is a distinct incomplete diagnostic, not proof the model lacks schema support.
- Acceptance: required live capabilities are proven, or the task remains blocked with an actionable diagnostic. Do not infer capability from management metadata or silently switch SDK/API/model.
- Completion: transport/credential/schema/error contracts pass with the actual SDK and injected HTTP. The bounded existing-deployment L06 probe passed with reported usage; actual authoring and the 12-item pilot also passed. Safe response-envelope validation handles Azure's absent unconsumed SDK fields without inventing model version or token details.

## T07 Bound requests, retries, budgets, and cancellation

- Stories: US02, US04, US06. Requirements: FR24. Prerequisites: T06.
- Scope: one transport retry owner, separate quality-attempt budget, bounded concurrency, deadlines, observed usage thresholds, audited budget overrides, and graceful cancellation.
- Paths: `src\docgen\execution.py`, `src\docgen\providers\azure.py`, `tests\test_execution_limits.py`.
- U07: use fake clocks/barriers to verify 429 `Retry-After`, retryable 5xx, terminal auth/refusal, timeout exhaustion, and no SDK retry multiplication. Exactly configured attempt/request limits must be respected.
- I07: concurrent work never exceeds the limit; budget stop schedules no further calls, retains completed items, records unknown usage as null, and reports bounded in-flight overshoot. Cancellation is non-success and resumable.
- Acceptance: operational bounds hold through the public generation API without real sleeps or timing-sensitive assertions; increasing a resume budget is explicit and audited.
- Completion: execution-limit, retry/cancellation, multi-item budget, and audited-override regressions pass. The live pilot retained accepted work through a timeout and reports its unknown outcome rather than a fabricated zero.
