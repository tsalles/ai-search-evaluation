# Contracts and Configuration

Status: Implemented version 1 content contracts with opt-in structure/layout extensions; authoring prompt version 5
Version: 0.1  
Date: 2026-10-26

## Input contract

Use one versioned YAML or JSON configuration. Phase 1 requires `generation`; Phase 2 requires `rendering` and an existing content-ready run; combined execution requires both. Reject unknown fields and invalid types. Persist the effective configuration and a secret-free semantic fingerprint.

```yaml
schema_version: "1"
seed: 1729
generation:
  count: 12
  language: pt
  locale: pt-BR
  audience: retail banking customers
  topics:
    - id: bank-products
      description: Fictional retail banking products
    - id: bank-procedures
      description: Fictional branch and digital banking procedures
  genre_weights:
    explainer: 0.25
    procedure: 0.25
    faq: 0.25
    comparison: 0.25
  length_weights:
    short: 0.30
    medium: 0.50
    long: 0.20
  structure_profile: baseline
  quality:
    max_candidates_per_item: 3
    near_duplicate_jaccard: 0.85
    language_confidence_min: 0.90
  provider:
    base_url: https://example.openai.azure.com/openai/v1/
    deployment: gpt-6-luna
    api: responses
  limits:
    concurrency: 2
    request_timeout_seconds: 120
    transport_attempts_per_candidate: 3
    max_requests: 108
    max_output_tokens_per_request: 8000
    max_observed_total_tokens: 250000
rendering:
  weights:
    pdf: 0.25
    docx: 0.25
    xlsx: 0.15
    pptx: 0.15
    html: 0.10
    md: 0.10
  allocation: stratified
  layout_profile: baseline
```

This configuration shape is implemented. The live example is [banking.yaml](../examples/banking.yaml); the values above describe a bounded run, not a guarantee that stochastic authoring completes within its candidate budget. Local authentication comes from `DefaultAzureCredential`; credential values are not configuration fields. Provider fields are not needed for Phase 2.

Additional optional controls: per-topic shares, topic briefs and permitted terminology, required terms, style/register, explicit scenario facts, and an audience. Topic shares are either omitted for all topics or supplied for all. Genres and length bands must use supported keys. Separate semantic controls from operational limits; do not add arbitrary prompt fragments or executable templates.

Supported locale profiles are `pt-BR`/`pt` and `en-US`/`en`; mismatched language/locale pairs and unsupported profiles fail. Omitted audience defaults to general readers. Omitted genre/length mixes use the example proportions; omitted structure/layout profiles use baseline. Count and topics are required. Phase 2 requires an explicit format mix; omitted formats have zero share, and an empty mix is invalid. Regional writing style remains a review responsibility.

Operational validation bounds: candidate and transport attempt limits each in `[1, 5]`, concurrency in `[1, 16]`, and request timeout in `[1, 600]` seconds. Default values are 3, 3, 2, and 120 respectively. If omitted, `max_requests` is `N * max_candidates_per_item * transport_attempts_per_candidate`. Output limits must be positive and compatible with the verified model; a positive observed-token stop threshold is required for live generation.

Observed-token thresholds are scheduling controls, not hard billing caps. Already in-flight requests can overshoot by their combined permitted output plus input/reasoning usage; missing provider usage prevents a finite measured-token guarantee and is reported explicitly. Request-count limits remain enforceable. Reported reasoning-token details are retained; they are not invented when absent.

Length bands count whitespace-delimited business-text words after NFC normalization and fact materialization, including table text and list items but excluding provenance and the synthetic-content banner: short 200 to 400, medium 500 to 900, long 1,000 to 1,600. These initial approved values must be calibrated against all six renderers; changing them requires explicit approval and versioned regression checks.

`generation.quality.word_band_tolerance` is an optional fraction in `[0, 0.05]`. Omission retains strict nominal bounds and historical serialization. With tolerance `t`, acceptance uses `ceil(nominal_min * (1 - t))` through `floor(nominal_max * (1 + t))`, inclusive. At 5%, the bands are 190-420, 475-945, and 950-1,680; they remain disjoint. The authoring target stays at the nominal midpoint, not the tolerated edge. Accepted content retains its planned length-band label and actual word count; the `length_tolerance` quality check identifies use of grace.

Tolerance is immutable semantic configuration included in the run fingerprint, not a budget increase. It never relaxes facts, native fidelity, structure, language, or uniqueness. Length-policy and per-item actual/grace information appear in planning, content-quality, rendering, and validation details.

## Structure recipes and native layouts

The input example above shows the compatible legacy profile controls. The current [banking example](../examples/banking.yaml) opts into the following replacements:

| Control | Contract |
|---------|----------|
| `generation.structure.complexity_weights` | Finite shares totaling one, using `simple`, `moderate`, and `complex`; defaults are 0.30/0.45/0.25 |
| `generation.structure.recipe_weights` | Optional `genre -> complexity -> recipe ID -> share` overrides; every pool totals one |
| `generation.structure.recipes` | Custom recipe ID to validated declaration; IDs cannot replace built-in recipes |
| `generation.structure.length_aware` | Optional Boolean; true compacts short shapes, reserves long-form prose, and freezes centered word budgets |
| `rendering.layout_weights` | Optional `format -> native layout ID -> share`; each supplied format must have positive format share and each pool totals one |

Do not supply `structure_profile` with `structure`, or `layout_profile` with `layout_weights`, including an explicit baseline profile. Omission preserves legacy behavior. Typed snapshots omit the replaced profile fields and absent extensions, preserving old content hashes and semantic fingerprints.

The version 1 catalog contains two built-in recipes per genre/complexity pair: `<genre>-<complexity>-a` and `-b`. Omitted recipe pools select those equally. The second recipe adds a reference list and context before the main content. Repeated explanatory sections and question/answer pairs, bounded list/table sizes, nested-item placement, and optional closing paragraphs provide further seeded variation.

Custom declarations use the same canonical block vocabulary:

```yaml
generation:
  structure:
    recipes:
      customer-guide:
        genre: explainer
        complexity: simple
        groups:
          - repeat: {min: 3, max: 5}
            blocks:
              - {kind: heading, role: A distinct customer concern, level: 1}
              - {kind: paragraph, role: Explain the concern and its conditions}
          - optional: true
            blocks:
              - {kind: paragraph, role: Closing guidance}
    recipe_weights:
      explainer:
        simple: {customer-guide: 1.0}
```

Each group has ordered blocks, an optional Boolean, and a repetition range (default one; permitted one to twenty). Blocks declare `kind` and `role`; headings declare `level` and optionally `question: true`; lists declare `items` and optionally `subitems` ranges; tables declare `columns` and `rows` ranges. Subitems belong to one seeded parent item. Roles are untrusted authoring data, not executable templates. Every possible instance must retain genre minimums and valid heading order. Instances contain at most 100 blocks, lists at most 100 total items, and tables at most eight columns and 200 data rows.

Complexity uses measurable features: heading depth at least two, nested lists, multiple tables, table width at least five columns, and callouts. Simple recipes allow none of those features; moderate recipes guarantee at least one and limit heading depth to two; complex recipes guarantee at least two. All retain heading/list model ceilings of three/two. Genre minimums still apply, including tables for comparisons and five top-level procedure steps.

Planning allocates exact global complexity quotas, then exact recipe quotas within each realized genre/complexity pool. A constrained seeded flow assigns complexity without changing topic/genre/length assignments. Every positive-share recipe in a pool must have a maximum shape whose minimum word capacity fits the assigned word band; infeasible mixes fail before run creation/inference. This conservative check does not promise that arbitrary prose will fit a physical layout or output-token budget.

Resolved structure plans persist recipe ID/hash, version, complexity, stable slot IDs, roles, order, heading levels, exact list-item levels, and exact table dimensions. Authoring must fill those slots without adding/reordering blocks. Rejections retain the same plan. Structure-enabled run plans use planning algorithm version 2; legacy plans retain version 1.

Length-aware runs use planning algorithm version 3 and structure plan version 2. Short sampling uses each required group's minimum repetition count, minimum list/table dimensions, and no optional groups; required complexity/genre features remain intact. Medium sampling bounds item/table range growth; long sampling uses maximum group repetitions to provide sufficient prose slots. These choices do not rewrite custom recipes or alter their declared bounds.

Version 2 plans also persist `target_words`, `title_words`, and each slot's `word_budget`; title and slot budgets sum exactly to the nominal midpoint. List budgets cover every item together; table budgets cover all headers, units, and cells together. Counts are assessed after fact expansion. Tables receive concise budgets and prose receives remaining capacity. Infeasible word-budget/recipe combinations fail preflight before run creation or inference. Per-block budgets guide authoring; only the total word-band acceptance range is a quality boundary.

| Format | Native layout IDs | Default when its layout pool is omitted |
|--------|-------------------|-----------------------------------------|
| PDF/DOCX | `single-column`, `two-column` | `single-column` |
| PPTX | `flow`, `section-led` | `flow` |
| XLSX | `compact`, `sectioned` | `sectioned` |
| HTML | `linear`, `sectioned` | `linear` |
| Markdown | `semantic` | `semantic` |

Defaults in this table apply when `layout_weights` is enabled. Otherwise the legacy layout profile remains authoritative. Layout quotas are exact within each format after integer rounding. Every native layout choice is frozen with the assignment. Sectioned layouts require primary headings; two-column layouts require at least two prose/list units. Combined planning checks resolved structures before generation; render-only preflight checks actual saved content before allocation is frozen.

PPTX section-led flow starts primary headings on new slides while retaining following content. Compact XLSX keeps narrative on one sheet and retains separate native table sheets; sectioned XLSX also partitions primary sections. Sectioned HTML creates actual section elements. Markdown has no simulated columns/pages. PDF two-column layout explicitly partitions prose and checks actual text geometry; DOCX checks native column declarations. Unsupported capabilities fail rather than downgrading.

## Planning, rounding, and balance

1. Validate finite decimal shares in `[0, 1]`; reject booleans and nonnumeric inputs. Sum tolerance is `1e-9`. Only accepted floating-point representation drift inside that tolerance is normalized and recorded.
2. For a mix with N items, compute `q_f = N * p_f`, assign `floor(q_f)`, then distribute the remaining slots in descending fractional-remainder order. Break exact ties by ascending canonical key. This applies to topic, genre, length, and format margins.
3. Zero-share entries receive no items. Positive shares can round to zero; preview and reports must identify them. No promise of coverage is made for undersized corpora.
4. Blueprints assign topic, genre, and length before knowing the output format. Use independent derived PRNG streams so a layout change cannot reshuffle content identities.
5. For Phase 2, stratify accepted items by `(topic_id, length_band)` for legacy runs, adding logical complexity for recipe runs (`transport-v2-structure`). For stratum s, ideal format count is `q_sf = n_s * p_f`.
6. Choose nonnegative integer `x_sf` with row sums `n_s` and column sums equal to the global largest-remainder targets. Minimize `sum(abs(x_sf - q_sf))` using integer-scaled minimum-cost transportation flow. Use seeded deterministic tie-breaking only after the primary objective. Record solver/library version.
7. Shuffle content IDs within each stratum using its derived seed, then assign its computed format counts. Persist the complete assignment before writing any final-format file.
8. Report the actual contingency table, objective, per-cell deviations, unrepresented groups, and genre/structure distributions by format. Flag nonempty cells deviating by more than one item and every unrepresented positive target; do not invent extra documents to improve balance.

The optimizer has exact hard global counts, not a universal guarantee of every format appearing in every stratum. Validate optimality against exhaustive enumeration for small fixtures. Topic, length, and opted-in logical complexity are balancing axes; genre and individual recipes are diagnostic axes. Sparse high-dimensional cells can still produce complexity imbalance, which reports expose.

## Canonical content and model boundary

| Record | Required information |
|--------|----------------------|
| Run plan | Schema version, run ID, effective configuration, semantic fingerprint, planning seed/algorithm version, N blueprints |
| Blueprint | Stable content ID and ordinal, topic, genre, length band, locale, audience, scenario ID, required structure, optional frozen structure plan |
| Accepted content | Version, blueprint ID, title, ordered blocks, frozen fact ledger, quality outcome, normalized fingerprint, JSON hash, provenance |
| Block | Unique ID, kind, logical order/heading level, text or typed items/table reference, fact references |
| Table | Stable ID, ordered columns with names/types/visible units, ordered rows with typed cells; no ambiguous merged data cells |
| Fact | ID, scenario/entity scope, value/type/unit/display representation, optional validity interval |
| Provenance | Deployment/model version if reported, prompt/schema versions, request/attempt IDs, timestamps, supplied/supported model controls, reported usage |
| Assignment | Content ID/hash, immutable format, renderer/profile version, optional frozen native layout plan, one relative output path |

Baseline blocks: heading, paragraph, ordered/unordered list, rectangular table, and callout. Sections use heading levels rather than a recursively nested tree. An FAQ is headings plus answer paragraphs; procedures are ordered items; tables are data, not Markdown strings. Cell types are text, decimal, date, and Boolean. Bound table sizes and text lengths against every selected renderer.

Cell/fact and corpus fact comparisons use a finite registry of known grammatical unit variants: Portuguese/English business days, calendar days, generic days, hours, months, and years. Unknown units retain their literal case and measurement expression. No general stemming, numeric conversion, period removal, or currency conversion occurs. Business days remain distinct from calendar/generic days; `ms` remains distinct from `Ms`. Original unit labels and fact displays remain unchanged in canonical content and native artifacts. Repeating an equivalent unit after a fact placeholder is still rejected.

Use a small nonrecursive provider wire schema separately from stricter internal models. Require explicit nullable fields, reject additional properties, and stay inside the provider's schema depth/property limits. Do not send unsupported Pydantic constraints or discriminator constructs without T06 verification. Local validation still enforces lengths, bounds, relationships, and uniqueness.

An LLM draft can contain a scenario-scoped fact ledger and prose with explicit `{{fact:ID}}` references. Materialize references deterministically before acceptance; table values come from the same frozen ledger. Unreferenced quantitative assertions require validation or candidate rejection. Content-scoped scenarios are the default; a configured shared scenario cannot be redefined by another item. The ledger is synthetic consistency data, not a claim of real banking accuracy or an exported retrieval answer key.

Different scenarios must have distinguishable visible entity/product labels or explicit visible validity context. A hidden scenario ID alone cannot justify conflicting facts about what appears to be the same entity to a reader.

Reject unknown schema versions and invalid IDs, references, type combinations, units, or table shapes. Changing accepted content requires a new content identity and a new generation run, not an in-place edit.

## Persistence and identity

Proposed layout, all on the same local volume:

```text
<output>\<run_id>\
  plan.json
  state.sqlite3
  content\<content_id>.json
  attempts\<attempt_id>.json
  artifacts.pending\<content_id>.<assigned_extension>
  corpus\<content_id>.<assigned_extension>
  ready-manifest.json
  reports\content-quality.json
  reports\allocation.json
  reports\validation.json
  reports\run-summary.json
```

`artifacts.pending` is renamed to `corpus`; both are not published copies. Temporary files and attempt records are never indexable documents. Filenames use generated opaque IDs, never titles, topic labels, query terms, or facts.

Use a generated run ID once, then stable ordinal-derived item IDs within that run. New runs have new identities even with the same seed. A same-run restart reads the saved plan instead of replanning.

Save accepted JSON with deterministic serialization and its SHA-256. Before resume/render, verify expected IDs, versions, hashes, and file counts. SQLite and same-directory temporary writes have explicit reconciliation states. A valid file after a crash can be adopted only if its recorded expected identity and hash match; otherwise report an integrity error.

After allocation, format weights, layout weights/plans, and assignments are immutable. Re-running Phase 2 with the same plan is idempotent; a different mix is rejected. Version 1 has no operation that copies accepted content into another run and changes its format.

Operational budget increases can be supplied explicitly on resume and are appended to the audit history. Endpoint, deployment, prompt/schema, semantic controls, seed, and accepted content cannot change. Unknown in-flight provider outcomes are recorded conservatively; exactly-once external billing is not promised.

Known historical prompt fingerprints can be opened for offline rendering, validation, or completed-run recovery. Unfinished generation requires the current authoring fingerprint and fails before another request after a prompt change. This does not rewrite old plans or silently reauthor accepted content.

Prompt version 5 introduces centered targets and explicit word-budget guidance. Historical prompt versions 1-4 remain readable offline. New tolerance/length-aware controls do not retrofit existing runs; accepted content, plan bytes, and source hashes remain immutable.

## CLI and result contract

Implemented commands, using Windows path syntax:

```powershell
docgen plan --config .\experiment.yaml --phase run --json
docgen doctor --config .\experiment.yaml
docgen doctor --config .\experiment.yaml --live
docgen generate --config .\experiment.yaml --output .\runs
docgen render --config .\experiment.yaml --run .\runs\<run_id>
docgen run --config .\experiment.yaml --output .\runs
docgen resume --run .\runs\<run_id>
docgen validate --run .\runs\<run_id>
docgen push --corpus .\runs\<run_id>\corpus --container documents --prefix <run_id> --json
```

`plan` performs no writes or inference. Non-live `doctor` checks configuration/dependencies only and explicitly reports `live_verified: false`; `doctor --live` makes a separately budgeted minimal request. `resume` continues the originally requested operation; a generation-only run does not silently become a combined run. `render` starts Phase 2 on a content-ready run. Completed runs validate rather than regenerate. Validation declares its scope as content or published corpus; valid content is not reported as a published corpus.

All commands support `--json`. Emit one JSON result to stdout and logs to stderr. Required result fields: `schema_version`, `run_id`, `operation`, `status`, `requested_count`, `accepted_count`, `verified_document_count`, `format_counts`, `failures`, `usage`, `reports`, `corpus_path`, `details`. Use null for inapplicable run/count fields, unknown usage, or an unpublished corpus; do not substitute zero for unknown data.

Each `format_counts` entry has `requested_share`, `allocated_count`, and `verified_count`; an unallocated count is null, not an actual zero. `details` is an operation-specific payload: plan quotas/warnings/workload, doctor capabilities and verification scope, validation outcomes/scope, execution progress/budget history, or `review` with a seeded advisory sample and explicit `human_review_pending` status. Warnings are separate from failures.

Successful terminal statuses are `planned` for preview, `ready` for the declared doctor scope, `content_ready` for generation only, `complete` for rendering/combined execution, and `valid` for validation. Resume returns the original operation's appropriate success status. Failure statuses are `invalid_input`, `incomplete`, `integrity_error`, or `cancelled`.

Recipe previews expose complexity quotas, recipe counts, per-item structural signatures/metrics, and native layout quotas/capabilities. Content-quality reports distinguish planned and accepted structure. Allocation reports include complexity/recipe/layout counts by format and sparse/rounded-zero warnings. Run summaries and corpus validation distinguish accepted from verified structure/layout distributions. Native validation reports include measured layout features. All remain outside the indexable corpus.

Each failure contains `code`, `phase`, optional `content_id`/`attempt_id`, `retryable`, and a safe message. Exit codes: 0 success, 2 invalid input/immutable-plan conflict, 3 incomplete work including provider/budget/quality failure, 4 persistence/integrity/lock failure, 130 user cancellation. CLI and library expose equivalent typed outcomes.

## Blob push contract

`push(corpus, *, container, connection_string=None, account_url=None, credential=None, env_file=None, prefix="", overwrite=False, create_container=False)` uploads native files without authoring, rendering, local run mutation, or credential persistence. The CLI exposes equivalent controls with `--corpus` and `--container` required; a library caller can inject a `TokenCredential` for Entra mode. No `--config`, `--run`, Azure OpenAI credential, or generation-ready state is required.

An explicit `account_url` selects Microsoft Entra authentication. The CLI uses the currently logged-in Azure CLI user through `AzureCliCredential(process_timeout=60)`, never `DefaultAzureCredential` or an implicit fallback chain. This mode does not read connection-string environment/dotenv values. Explicit connection-string/env-file controls cannot be combined with it. An injected token credential requires an account URL, remains caller-owned, and is not closed; application-owned Azure CLI credentials are closed with the client.

Entra account URLs require HTTPS on the canonical Azure public Blob domains (`.blob.core.windows.net` or `.blob.storage.azure.net`), optional port 443, and an empty/root path. Userinfo, SAS/query/fragment data, container paths, and arbitrary hosts are rejected before token acquisition. This prevents accidentally sending a logged-in user's storage bearer token to a non-Azure endpoint.

Credential resolution is an explicit argument, then `AZURE_STORAGE_CONNECTION_STRING` in the process environment, then that key in the selected file or current-directory `.env`. A present empty/invalid source fails closed. Dotenv parsing accepts UTF-8/BOM, does not search parent directories, interpolate variables, or change process environment. Connection strings and SAS query values never appear in application result/error messages. Prefer private environment files over command-line credentials because shell history/process listings are outside application redaction.

Standard Azure container names must be 3-63 lowercase letters/digits with single internal hyphens. Prefixes are optional relative slash-separated object paths; reject empty/traversal segments, query/fragment data, backslashes, control characters, and oversized blob names. HTTPS endpoints are required. `.env`, `.env.*`, and `*.env` are gitignored; the checked-in storage example contains no credentials.

Preflight recursively collects only nonempty PDF/DOCX/XLSX/PPTX/HTML/MD files, rejects filesystem links and other files, and hashes input using bounded streams. Relative paths become blob names below the chosen prefix. For generator-managed input, require the published `corpus` directory, valid plan/allocation/ready metadata, exact manifest file membership, matching sizes, and SHA-256 values. A standalone document directory is supported without claiming canonical/native-content validation.

Each upload uses a block blob, the native MIME type, transfer-MD5 validation, source SHA-256 metadata, bounded SDK retry/timeouts, and one transfer connection per file. File size/identity/mtime snapshots detect ordinary source mutation before/during upload. Do not modify the source while pushing. Existing blobs fail by default; `--overwrite` authorizes replacement. `--create-container` explicitly authorizes creating a private container and does not change an existing container's access policy.

Results retain the version 1 envelope with `operation: push`; generation-only accepted/verified counts, run ID, inference usage, and published-corpus result path remain null. `requested_count` is the input file count. `details` contains safe endpoint/container/prefix, `auth_mode` (`entra` or `connection_string`), credential-source enum, source-validation scope, per-file names/sizes/hashes/status/optional ETag, and uploaded/failed/pending totals. `container_created` is null if creation was attempted but its outcome is unknown. Unavailable Azure CLI login has an actionable safe error. Only allowlisted Azure service error codes are exposed; server error messages and tokens remain excluded.

Blob data RBAC and network access are independent prerequisites. Prefer data-contributor access at the existing target container scope. Entra does not bypass a disabled public endpoint, firewall, private-endpoint requirements, or Azure RBAC conditions. The upload operation does not modify RBAC, network rules, Shared Key policy, or public-access settings.

`complete` means Azure acknowledged every file, not independent remote content readback. On the first upload failure, stop and return `incomplete` with explicit safe errors and partial counts; cancellation returns `cancelled`. Confirmed writes are retained and in-flight writes may have occurred. There is no batch rollback, automatic blob deletion, implicit overwrite, silent conflict skip, or exactly-once transaction claim. Existing exit-code semantics apply.
