# Architecture

Status: Implemented; verification evidence is maintained in the implementation ledger  
Version: 0.1  
Date: 2026-10-26

## Design

Use a local Python application with a reusable public API and a CLI over the same orchestration functions. Separate LLM authoring from deterministic rendering through versioned canonical JSON. No agent runtime, queue, web service, Search resource, or new Azure deployment is required.

| Component | Responsibility | External dependency |
|-----------|----------------|---------------------|
| Configuration and planner | Validate inputs; allocate topics, genres, lengths and optional complexity; resolve bounded recipes into frozen slots and fingerprints. | Pydantic, safe YAML parser, constrained NetworkX flow |
| Generation service | Request structured drafts; materialize facts; validate language, structure, length, and uniqueness. | Provider interface; local language detector |
| Azure provider | Acquire renewable tokens; submit bounded requests; translate response outcomes. | `openai`, `azure-identity` |
| Run store | Persist immutable JSON, attempt records, checkpoints, assignments, and hashes. | Standard-library SQLite; cross-platform file lock |
| Format allocator | Compute exact quotas, balance topic/length and opted-in logical complexity, and freeze per-item native layout recipes. | Exact integer transportation flow with NetworkX |
| Renderer registry | Select a native renderer for the assigned format; never rewrite content. | Native file libraries |
| Artifact validator | Independently inspect saved files, planned heading/list structures, native layout features, text, facts, and layout bounds. | ZIP/XML, Markdown/HTML parsing, `pypdf`, `pdfplumber` |
| Publisher and reporter | Publish only a complete validated corpus; export audit summaries outside it. | Local filesystem |
| Corpus uploader | Validate local document input/publication hashes, resolve storage credentials privately, and stream native bytes to an explicit blob destination with partial-write reporting. | `azure-storage-blob`, `python-dotenv` |

Source organization follows these responsibilities. Public paths are `generate(config, output)`, `render(run, render_config)`, `run(config, output)`, `resume(run, budget_override=None)`, and `validate(run)`. Typed results and injected provider interfaces allow offline tests without a production fake-provider mode.

The independent `push(corpus, *, container, ...)` API and CLI command need no generation configuration or Azure OpenAI access. A user-supplied storage connection string is resolved from the argument, process environment, or one dotenv file without persisting it in plans/reports or modifying process environment. Real SDK HTTP transport can be replaced at the network boundary for offline tests.

An explicit account URL selects Entra authentication using the logged-in Azure CLI user deterministically. This path ignores connection-string sources and restricts token-bearing requests to canonical public-Azure Blob endpoints. Application-owned credentials and clients share a bounded cleanup scope; caller-supplied token credentials retain caller ownership. Identity selection never silently falls back after authorization failure. Container data RBAC and an approved network path are independent and are not changed by the uploader.

Local file/type/link and publication-manifest checks precede any network request. The uploader streams files into block blobs with native content types, transfer-MD5 validation, and source hash metadata. No-overwrite is the default. Container creation is explicit and private. Azure provides per-blob writes, not atomic corpus publication; failures retain prior writes and report remaining work. SDK errors are translated into credential-safe diagnostics instead of copying server messages/URLs.

## Execution and persistence

1. Validate configuration and produce immutable content blueprints, including resolved structure slots when recipe controls are enabled.
2. Acquire exclusive ownership of a new run directory.
3. Phase 1 generates candidates with bounded concurrency. Evaluate acceptance in blueprint order so duplicate resolution does not depend on response timing.
4. Atomically save each accepted content JSON and record its hash/checkpoint.
5. Require N accepted items before starting Phase 2.
6. Freeze the format allocation and optional native layout plans. Render each item to its single assigned path under an unpublished staging directory.
7. Independently validate every artifact and the complete set.
8. Write a ready-manifest with checksums, then atomically rename the same-volume staging directory to the final corpus directory.
9. Record completion and export reports outside the corpus. On resume, reconcile a crash between publication and the state commit using the ready-manifest.

SQLite is the mutable job-state authority; canonical JSON is the immutable content authority. Exported manifests are snapshots, not competing mutable stores. Filesystem writes and database transactions are not jointly atomic: checkpoint states and reconciliation explicitly cover each boundary. See [contracts](contracts.md) and [ADR 0002](architecture/decisions/0002-corpus-persistence.md).

Run-level states: `planned`, `generating`, `content_ready`, `allocated`, `rendering`, `validating`, `complete`, `incomplete`, `cancelled`. An incomplete run records its failed phase and resumes from a verified checkpoint. Item/attempt statuses are separate. A quality-rejected candidate is not an accepted item.

## Azure integration

- The account and resource group named `example`, and `https://example.openai.azure.com/openai/v1/`, are sanitized placeholders.
- Earlier private validation confirmed deployment/model `gpt-6-luna`, version `2026-09-22`, provisioning state `Succeeded`. Configure and verify your own deployment before live use.
- `DefaultAzureCredential` with `get_bearer_token_provider` and `https://ai.azure.com/.default` passed the live capability and authoring tests.
- For a local CLI-authenticated session, explicitly restricting the credential chain to `AzureCliCredential` through `AZURE_TOKEN_CREDENTIALS` still uses `DefaultAzureCredential`; this requires `azure-identity` 1.24.0 or later. Do not silently sign in with another identity or launch a browser.
- The `model` API argument is the deployment name. A working management-plane CLI session does not prove data-plane permission.
- The v1 Responses API accepts the application's strict wire schema, `store: false`, and output-token bound. Transport tests cover refusal, incomplete/malformed responses, safe errors, token renewal, and the SDK boundary.
- Do not assume support for temperature, model seed, reasoning controls, or a tokenizer. Omit unrequested optional sampling controls; reject explicitly requested unsupported controls.
- If a provider reports a changed model version during a run/resume, stop rather than silently mixing versions. An unreported model version remains unknown; configuration cannot pin an unverifiable version.
- No API keys, tokens, tenant identifiers, or raw HTTP authorization headers belong in saved configuration or logs.

The MCP authentication chain failed during initial discovery; read-only CLI management calls succeeded. Subsequent bounded data-plane tests verified the selected connection and generated actual content. The response reports the deployment/model name but no model-version header; runtime model version therefore remains null rather than being copied from management metadata. No fallback API or model is selected.

## Native rendering

| Format | Implementation | Meaningful structure |
|--------|-------------------------|----------------------|
| MD | Small deterministic writer | Heading hierarchy, lists, GFM tables |
| HTML | Escaped semantic HTML and fixed local CSS | Sections, headings, lists, actual table elements |
| DOCX | `python-docx` | Styles, paragraphs, list numbering, native tables and page flow |
| XLSX | `openpyxl` | Sections on sheets, typed cells, actual table ranges, visible units |
| PPTX | `python-pptx` | Native text boxes and tables, slide continuation |
| PDF | ReportLab Platypus | Embedded licensed fonts, native text, pagination, repeated table headers |

PDF rendering and layout measurement use Bitstream Vera regular/bold plus the redistribution license bundled by the declared ReportLab dependency. Missing assets fail explicitly. DOCX/XLSX/PPTX declare Arial; actual Office exports are a QA aid, not a runtime requirement. No Office installation or HTML-to-PDF browser is needed to generate documents. Binary bytes may vary due to timestamps or library metadata; fidelity is measured semantically.

PDF table readback uses `pdfplumber` line-grid geometry in addition to `pypdf` text/metadata checks. Spreadsheet limits include 15 significant decimal digits, native dates from 1900, bounded row heights, and literal formula-like strings. Unfit content fails explicitly. PowerPoint queues section headings until the first following text/list fragment or table header/data row can share a slide.

Authoring prompt version 5 retains complete-unit placeholders, grammatical fact phrasing, and exact frozen recipe slots, and adds centered word targets plus per-block budget guidance. Completed content from known earlier prompt fingerprints remains usable offline. Absent extensions retain historical serialization and fingerprints. Unfinished generation cannot mix an older authoring fingerprint with current instructions.

Logical recipe models are separate from the provider wire schema: groups and ranges compile to ordered canonical slots, while the provider still returns the existing nonrecursive draft representation. Composition preserves the plan; local acceptance verifies its realization. Separate derived seed streams own complexity assignment, recipe selection, slot parameters, and native layouts. Retries never resample a failed structure.

The explicit native layout capability registry is shared by configuration, planning, allocation, and diagnostics. Unsupported requests fail preflight. Native readback verifies the selected arrangement rather than trusting its stored label. Two-column PDF partitions prose at a safe boundary; PPTX retains headings with following content. All accepted business text and typed table data remain authoritative.

Length-aware planning uses algorithm version 3 and budgeted structure plan version 2. A separate bounded word allocator reserves concise title/heading/table targets and distributes the remaining nominal word target across prose and lists. Short structures compact within recipe bounds; long structures reserve enough prose capacity. The nominal band and frozen tolerance remain separate from advisory slot budgets. Quality assessment enforces only the configured total envelope.

Measurement-unit identity is separate from visible grammatical labels. A finite alias registry is shared by canonical relationship validation, corpus fact consistency, and duplicate-unit placeholder checks. It does not convert values, collapse periods, or normalize unknown SI prefixes. Original serialized content remains unchanged.

All formats must handle the same baseline canonical blocks. Native-layout variation is declared in a capability matrix; unsupported requested variations fail preflight instead of being silently downgraded. [ADR 0003](architecture/decisions/0003-document-rendering.md) records alternatives.

## Failure and resource model

| Condition | Required behavior |
|-----------|-------------------|
| 429, retryable 5xx, transport timeout | Bounded retry with `Retry-After`, seeded testable jitter, and one retry owner; disable SDK retries. |
| Authentication/authorization, unsupported request, refusal | Typed diagnostic; no blind transport retry. A refusal is a terminal content-slot failure. |
| Invalid/truncated candidate | Retry as a new quality candidate within its separate limit. Never accept partial JSON. |
| Budget exhaustion or cancellation | Stop scheduling, drain or cancel in-flight work, record known/unknown usage, retain verified work, exit non-success. |
| Disk full, access denied, checksum mismatch | Explicit persistence/integrity failure; do not publish or overwrite evidence. |
| Second writer | Fail run-lock acquisition; never infer lock ownership solely from a PID. |
| Crash after a remote request | Mark an unresolved attempt outcome unknown; a later retry consumes budget and might have been billed twice. |
| Crash around file/SQLite/publication boundaries | Reconcile only against the planned IDs, hashes, and ready-manifest; reject unexpected files. |

Start with two generation requests in flight and one rendering writer. Keep accepted items on disk and load only the required item during rendering. The 1,000-item scale gate measures actual memory and file-handle behavior before claiming that capacity.

## Engineering conventions

- Python baseline: 3.12; the Windows dependency snapshot records the verified environment.
- Local gates: pytest, property tests, Ruff, strict typing of application code, and package build/install smoke tests.
- Test-first development, one green task at a time, with no unrelated cleanup.
- Source-control/PR hosting and CI configuration are pending the user's platform choice. Do not initialize or publish a repository as part of this planning task.
- No infrastructure changes are needed for the planned application. Future CI must reuse local gates and require separate opt-in for paid Azure tests.
