# Synthetic Document Generator

Status: Implemented and technically verified; human corpus approval is not recorded  
Python: 3.12 or later  
Initial platform: Windows  
Date: 2026-10-26

Generate controlled synthetic document corpora for comparing retrieval across PDF, DOCX, XLSX, PPTX, HTML, and Markdown.

## Public source snapshot

This copy contains the current source, tests, and documentation with sanitized deployment examples.

- Azure account names, endpoints, subscription identifiers, and private network addresses are examples. Replace them with your own configuration before authorizing any live command or deployment.
- Local Azure planning exports, environment files, generated corpora, evaluation databases, and customer-provided documents are excluded.
- Historical experiment reports retain their recorded synthetic-corpus results. Deployment aliases are sanitized, and links to ignored local evidence require the original private workspace.
- The public repository starts with fresh history. Previous commits, personal Git author metadata, and private agent snapshot refs are not included.

Keep local credentials and generated Office/PDF files excluded by the ignore rules. Publish this repository's `main` branch rather than mirroring the original private repository.

## Capabilities

- **Phase 1:** Author content through an existing Azure OpenAI Responses deployment, enforce schema/fact/language/length/structure/uniqueness controls, and persist immutable canonical JSON.
- **Phase 2:** Render saved content offline, assigning every content item to exactly one format. No LLM rewriting or alternate-format copies.
- **Combined execution:** Generate, validate, render, and publish with one command.
- **Reproducible allocation:** Exact integer format quotas with seeded topic/length balancing and a recorded optimal transportation objective.
- **Structure variation:** Per-item simple/moderate/complex plans, 24 built-in recipes, bounded custom recipes, and independently sampled native layouts. Recipe runs also balance logical complexity across formats.
- **Recovery:** Retain accepted content and verified artifacts; resume interrupted work without regenerating accepted items or changing their formats.
- **Publication:** Publish only a complete validated corpus. Keep canonical content, attempts, fact ledgers, manifests, and reports outside the indexable directory.
- **Blob upload:** Push a corpus to Azure Blob Storage with streamed native files, optional private-container creation, explicit overwrite control, and secret-safe results.
- **Blob clearing:** Preview or explicitly delete current blobs in one container or virtual-folder prefix, preserving the container/account and protecting changed versions with ETags.
- **Paired retrieval experiments:** Generate fresh scenario families, review source-backed queries/qrels, ingest identical files through DE/Text Split and CU/native semantic chunking, and compare saved hybrid rankings offline.

The initial defaults target Brazilian Portuguese and 1 to 1,000 items. English/US is also configurable. Files contain native text, editable Office structures, and native tables. Scans, OCR, charts/images, macros and formula evaluation remain outside normal generation. The separate experiment workflow requires a newly generated corpus and provides fictional banking and SaaS subscription/support presets.

Latest retrieval evidence: [final topic-shifted SaaS comparison](docs/experiments/reports/2026-11-05-independent-saas-results.md). On 996 final native documents and a fixed 93-family cohort, the frozen tuned DE plus Text Split and semantic BM25 configuration scored 0.630991 nDCG@10 versus tuned CU's 0.612588. Its paired relative gain is 3.00%, with a 95% family-bootstrap CI of [1.15%, 4.92%]. All ten conditions were reindexed and collected after a documented source-quality correction; earlier sources and measurements remain preserved. References and answer-support judgments are automated, not human reviewed.

The [earlier banking semantic comparison](docs/experiments/reports/2026-11-04-example-semantic-results.md) favored the same DE policy, scoring 0.815840 versus 0.804055, and restored the historical service's free semantic plan. Cross-corpus score differences are not paired treatment effects. The isolated SaaS S1 service remains provisioned with paid semantic search.

## Install and verify

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\scripts\check.ps1 -q
```

The check script runs the entire offline suite, branch-only coverage gates, Ruff, strict application typing, and source/wheel builds. Offline tests block network access. The Windows dependency snapshot is [requirements-dev.lock](requirements-dev.lock).

To reproduce the verified development versions on Windows/Python 3.12:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### Original verification evidence (2026-10-24)

- **372 offline tests passed**, with no failures or skips; both paid live tests were explicitly deselected.
- Branch coverage: **86.31% overall**, **95.34% critical modules**. Ruff, strict typing for 50 application files, dependency consistency, and source/wheel builds passed.
- The live capability probe and a fresh **12-document, six-format Azure pilot** passed. The final pilot recorded **21 requests and 96,801 tokens**, with no unknown usage.
- A real **1,000-document hard-crash/recovery** test passed with **582,103,040 bytes peak process-tree RSS**, below 1 GiB. It retained all accepted content, the allocation, and 37 pre-crash artifact files.
- An isolated installed-wheel environment exercised fixture generation, planning, diagnostics, all six native renderers, validation, and resume with network/credential access forbidden.
- Actual Office exports and independent model review found and verified a PPTX heading-pagination fix. Model review is recorded separately from human approval.

Detailed evidence, calibration findings, and limitations are in [implementation evidence](docs/implementation-progress.md).

### Initial structure/layout verification (2026-10-26)

- **683 offline cases verified across full runs and focused reruns**, including the existing 1,000-document hard-crash/recovery case. No functional assertions or property-example counts were reduced.
- Final branch coverage: **87.99% overall**, **95.70% critical modules**, above the unchanged 85%/95% gates.
- Ruff, strict typing for **55 application files**, dependency consistency, and source/wheel builds passed.
- Read-only compatibility checks retained byte-identical serialization for **24 canonical items across two historical runs**.
- The updated example passes no-write planning and local diagnostics. New model-adherence rates and human visual approval remain unverified; no paid inference calls were made for this extension.

### Authoring correction verification (2026-10-26)

- **761 current offline regression tests passed**; the separate 1,000-document scale/recovery case was not rerun for this correction.
- Final branch coverage is **88.20% overall** and **95.70% critical modules**. Ruff, strict typing for **57 application files**, and source/wheel builds passed.
- Offline replay of saved live drafts now accepts the 417-word edge case under a hypothetical 5% policy, rejects 509/530-word short drafts, and removes false singular/plural unit contradictions without changing protected values.
- The original incomplete run's plan and **10 accepted files remain unchanged**. Prompt version 5 requires a new run for the corrected authoring controls. No additional paid calls were made.

### Blob upload verification (2026-10-26)

- The full non-scale regression run passed **811 tests**; the final upload-focused suite passed **51 tests**, including an additional invalid-signing-key regression.
- Branch coverage is **88.37% overall** and **95.70% critical modules**. Ruff, strict typing for **58 application files**, dependency consistency, and source/wheel builds passed.
- Tests use the real Azure Blob SDK with an in-memory transport, including bounded block uploads, exact file bytes, MIME types, credential precedence/redaction, conflicts, source/publication guards, and partial-write reporting.
- No real storage account was accessed or modified. Actual connection-string permissions/network rules require a separately authorized upload.

### Entra upload verification (2026-10-27)

- **827 non-scale regression tests passed**. Branch coverage is **88.48% overall** and **95.70% critical modules**; Ruff, strict typing for 58 application files, and source/wheel builds passed.
- Offline cases verify Storage bearer-token scope/headers, Azure CLI identity selection, credential ownership, ignored connection-string sources, safe account URLs, and secret-safe Azure error codes.
- An explicitly authorized container-scoped data-contributor assignment was verified for the logged-in user. A read-only live check still returned `AuthorizationFailure` while the target account's public network access remained disabled.
- No blobs were uploaded, account keys retrieved, or network/Shared Key policies changed. An approved network path is still required.

### Paired retrieval verification (2026-10-28)

- The full offline release gate passed **919 tests**, including the 1,000-document crash/recovery and installed-package regressions. Two paid live tests were deliberately deselected.
- Full-run branch coverage was **86.72% overall** and **95.70% for critical modules**, above the unchanged 85%/95% thresholds. Ruff, strict typing for **72 application files**, dependency consistency and source/wheel builds passed.
- After separating embedding API metadata from the document Responses configuration, the final affected-surface rerun passed **169 experiment/provider/configuration tests**.
- Tests cover fresh six-format families, paragraph/list/table evidence, manual-review seals, real Blob SDK and Search REST transports, shared vectors, independent metric fixtures, source loss, streaming mutation, interruption recovery and drift rejection.
- The documented console planning command returned the expected two-family workload: twelve documents, twelve intents, twenty-four utterances, forty-eight paired queries and twenty-four shared embeddings. This was local planning, not live inference or indexing.
- No live Azure benchmark, paid inference, real human dataset approval, role change or network change was performed for this implementation.

### Paired retrieval review corrections (2026-10-29)

- A requirement-led review reproduced eight correctness gaps through ten failing cases, then added three further regression checks. Corrections cover exact entity scope, frozen fact validity, actual Blob bytes and ETags, permanent drift quarantine, embedding-cache validation, source-plan resume checks and service-normalized resource readback.
- All **314 directly affected tests** passed after the corrections. The wider non-scale release gate passed **933 tests**, with two paid live tests deselected.
- Branch coverage is **86.76% overall** and **95.70% for critical modules**. Ruff, strict typing for 72 application files, dependency checks and source/wheel builds passed.
- The existing 1,000-document scale/recovery case passed in the preceding full release run and was not rerun for these scoped corrections. No live Azure calls or human reference approvals were performed.
- Previously prepared workspaces need `experiment prepare --live` to establish version-bound source-byte verification before snapshot reuse or scoring. See [the runbook](docs/experiments/usage.md).

### Blob clearing verification (2026-10-29)

- The final **98 clear/upload tests passed** using the real Storage SDK with offline transports. Cases include preview-only defaults, prefix boundaries, conditional deletes, snapshots, changed/new blobs, selection limits, partial failures, cancellation, safe error messages and dot-segment URL scope protection.
- A wider non-scale run recorded **961 passing cases and one rendering-checkpoint timeout** in an existing process-recovery test. All three recovery boundaries subsequently passed in isolation without changing that test.
- Refreshed branch coverage is **86.82% overall** and **95.70% for critical modules**. Ruff, strict typing for 73 application files, dependency checks and source/wheel builds passed.
- No real blobs, containers, accounts, snapshots or versions were deleted during implementation/testing.

## Azure authentication

Use existing accounts and model deployments. Normal generation uses renewable bearer tokens from `DefaultAzureCredential`, not API keys. The experimental commands select the logged-in `AzureCliCredential` explicitly.

Experimental `prepare` and `ingest` create uniquely named Search data-plane resources and upload to a protocol-owned prefix only with `--live`. They do not create accounts, deploy models, enable networking, change RBAC or reset existing indexes.

```powershell
az login
$env:AZURE_TOKEN_CREDENTIALS = 'AzureCliCredential'
```

The `example` account is a placeholder. Set the Azure HTTPS v1 endpoint and deployment name in [banking.yaml](examples/banking.yaml) to your own existing deployment before making live requests.

`doctor` is local-only unless `--live` is supplied. The live flag authorizes one paid synthetic schema request capped at 2,048 output tokens. Normal generation also consumes inference quota, bounded by its configured request, candidate, timeout, concurrency, and observed-token limits. No currency cost estimate is asserted.

## CLI

All operation results are one versioned JSON object on stdout; diagnostics use stderr. `--json` is supported explicitly. Help/version remain plain text.

```powershell
# Preview both phases without inference or output mutation.
.\.venv\Scripts\docgen.exe plan --config .\examples\banking.yaml --json
.\.venv\Scripts\docgen.exe doctor --config .\examples\banking.yaml --json

# Explicitly opt in to the bounded paid capability probe.
.\.venv\Scripts\docgen.exe doctor --config .\examples\banking.yaml --live --json

# Execute both phases.
.\.venv\Scripts\docgen.exe run --config .\examples\banking.yaml --output .\runs --json

# Or execute phases separately. Substitute the returned run ID.
.\.venv\Scripts\docgen.exe generate --config .\examples\banking.yaml --output .\runs --json
.\.venv\Scripts\docgen.exe plan --config .\examples\banking.yaml --phase render --run .\runs\<run_id> --json
.\.venv\Scripts\docgen.exe render --config .\examples\banking.yaml --run .\runs\<run_id> --json

# Resume the original operation, or verify saved content/published files.
.\.venv\Scripts\docgen.exe resume --run .\runs\<run_id> --json
.\.venv\Scripts\docgen.exe validate --run .\runs\<run_id> --json
```

Generation-only needs no rendering configuration. Rendering needs only rendering configuration plus a content-ready run; it does not acquire Azure credentials.

Format shares must be finite numbers in `[0, 1]` totaling 1 within `1e-9`. Only floating-point representation drift inside that tolerance is normalized and reported. Integer quotas use largest remainders, with ascending format keys breaking exact ties. A tiny corpus can leave positive-share formats unrepresented; preview/report warnings identify this.

The example's 12-item mix produces three PDF, three DOCX, two XLSX, two PPTX, one HTML, and one Markdown file.

Edit `generation.count`, `generation.topics`, topic/genre/length shares, required terms, audience, and structure/layout controls to design another corpus. The exact controls and boundaries are in [contracts](docs/contracts.md) and [content quality](docs/content-quality.md). When increasing the count, review the example's explicit request/token budgets too; changing N does not silently raise a paid-call cap.

### Structure and layout variation

The example now opts into independently controlled logical structure and native layout. Its 12 content items receive exactly four simple, five moderate, and three complex structure plans. Native layout shares are rounded separately within each assigned format; tiny groups can leave a requested layout unrepresented, which planning/allocation reports identify.

```yaml
generation:
  quality:
    word_band_tolerance: 0.05
  structure:
    length_aware: true
    complexity_weights: {simple: 0.30, moderate: 0.45, complex: 0.25}
    recipe_weights:
      procedure:
        moderate:
          procedure-moderate-a: 0.60
          procedure-moderate-b: 0.40
rendering:
  layout_weights:
    pdf: {single-column: 0.50, two-column: 0.50}
    pptx: {flow: 0.50, section-led: 0.50}
```

This is an excerpt: retain the normal topics/count and format shares. Two built-in recipes exist for each genre/complexity pair, named `<genre>-<complexity>-a` and `-b`. Recipe shares apply within that genre and complexity pool. Omitted pools use equal built-in shares. [Custom recipe declarations](docs/contracts.md#structure-recipes-and-native-layouts) specify ordered groups, repetition ranges, optional groups, and block shapes.

Logical plans freeze block IDs/order, heading levels, list-item levels, and table dimensions before authoring. Retries and resume reuse those plans. Native layouts freeze after format allocation and never rewrite accepted business text. `plan` previews complexity and layout quotas without inference or output writes.

The example also enables length-aware planning and 5% word-band grace. Short plans use minimum repetitions/list/table dimensions and omit optional groups; long plans reserve more explanatory space. Version 2 structure plans freeze a title budget and per-block word budgets totaling the nominal midpoint: 300, 700, or 1,300 words. These are authoring targets, not extra per-block rejection thresholds.

Nominal bands remain 200-400, 500-900, and 1,000-1,600 words. At 5% grace, inclusive acceptance ranges are 190-420, 475-945, and 950-1,680. Grace applies only to total word count; numeric facts, units, schema, structure, language, and uniqueness remain checked. Omitting `word_band_tolerance` keeps strict historical limits. Known grammatical unit variants compare by measurement identity; values, periods, and genuinely different units are not relaxed.

These settings are frozen semantic configuration. They cannot be applied as resume-budget overrides. Prompt version 6 retains offline reading of older content but refuses unfinished authoring against an older prompt fingerprint. Start a new run with the updated example; do not edit an existing plan or accepted content.

Omitting the new controls preserves legacy `structure_profile`/`layout_profile` behavior. Do not supply a legacy profile alongside its replacement. Complexity remains separate from word count and does not establish retrieval difficulty. The original paid pilot predates these controls; no new live-generation or human-approval claim is made for this extension.

### Audited budget increases

An exhausted run does not silently reset its budgets. Increase operational limits explicitly:

```powershell
.\.venv\Scripts\docgen.exe resume --run .\runs\<run_id> --max-requests 150 --max-observed-total-tokens 300000 --max-candidates-per-item 5 --json
```

Limits may increase, not decrease; quality candidates remain bounded at ten per item, with a default of three. Increasing only the per-item candidate allowance does not increase the separate overall request or observed-token ceilings. Overrides are audited separately and do not modify the immutable run plan or quality thresholds. Already in-flight requests can overshoot an observed-token stop threshold. Missing provider usage remains unknown, not zero. Exactly-once remote billing is not promised after an interrupted request.

Completed content from known older authoring versions can still be rendered or validated offline. Unfinished generation after an authoring-prompt change requires a new run rather than mixing prompt versions.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Successful operation for its declared scope |
| 2 | Invalid input or immutable configuration conflict |
| 3 | Incomplete work, budget exhaustion, provider/quality/validation failure |
| 4 | Persistence, checksum, lock, or integrity failure |
| 130 | Cancellation; verified work is retained |

## Upload a corpus to Azure Blob Storage

`push` is separate from generation: it takes a corpus directory and container name, needs no generation configuration or Azure OpenAI access, and makes no inference calls. Storage writes and transactions can incur Azure charges.

### Microsoft Entra with your Azure CLI user

Use an explicit account URL to authenticate as the user already signed into Azure CLI:

```powershell
az login
.\.venv\Scripts\docgen.exe push --corpus .\runs\run-YOUR-ID\corpus --container documents --prefix run-YOUR-ID --account-url https://YOURACCOUNT.blob.core.windows.net --json
```

This mode uses `AzureCliCredential` directly, not a credential chain or account keys. It ignores connection-string environment/dotenv values and does not fall back to another identity or authentication method. Do not combine `--account-url` with `--connection-string` or `--env-file`. Entra account URLs must be canonical public-Azure Blob HTTPS endpoints, without a container path, credentials, or query parameters.

The user needs blob data permissions, normally **Storage Blob Data Contributor at the target container scope**. Management-plane Owner/Contributor alone is not blob data access. Use an existing container for container-scoped access; creating other containers can require broader, separately authorized access.

Authentication and networking are independent. Entra authentication works with Shared Key disabled, but does not bypass storage firewalls or disabled public endpoints. Use approved private connectivity or explicitly approved client-IP-restricted public access. The uploader never changes network rules, enables Shared Key, or grants RBAC automatically.

The [private VPN infrastructure](infra/README.md) contains the approved additive Bicep configuration and its current partial-deployment status. VPN connectivity is not ready until the documented public-IP subscription prerequisite is resolved and client verification succeeds.

### Connection string or dotenv

Connection-string precedence is `--connection-string`, then the process environment variable `AZURE_STORAGE_CONNECTION_STRING`, then the same variable in `--env-file` or the current directory's `.env`. Files are read without changing process environment variables or interpolating other variables. Existing environment values win even when `--env-file` is supplied. An explicitly empty credential source fails rather than falling back.

For local use, create a private `.env` only if you do not already have one:

```powershell
if (-not (Test-Path -LiteralPath .\.env)) {
    Copy-Item .\examples\storage.env.example .\.env
}
```

Set its value locally:

```dotenv
AZURE_STORAGE_CONNECTION_STRING="YOUR_STORAGE_CONNECTION_STRING"
```

Do not paste real credentials into source files or the example template. Environment files are gitignored. Prefer `.env` or a securely supplied environment variable over the command-line option, which can appear in shell history and process listings. Use a least-privilege connection string or SAS and an HTTPS endpoint.

Upload the published directory returned in `corpus_path`; replace the example run ID:

```powershell
.\.venv\Scripts\docgen.exe push --corpus .\runs\run-YOUR-ID\corpus --container documents --prefix run-YOUR-ID --json
```

Alternatively, supply credentials explicitly:

```powershell
.\.venv\Scripts\docgen.exe push --corpus .\my-corpus --container documents --connection-string "YOUR_STORAGE_CONNECTION_STRING" --json
```

- The container must exist unless you add `--create-container`. New containers are private; existing permissions are unchanged.
- Existing blobs cause an explicit failure. Add `--overwrite` only when replacement is intended.
- `--prefix` is optional and uses Azure object-path separators (`/`). Without it, files go directly into the container. Prefer an opaque run ID to avoid filename collisions or relevance-label leakage.
- `.env` defaults to the current working directory only; use `--env-file .\private\storage.env` for another file.
- Native PDF/DOCX/XLSX/PPTX/HTML/MD files are uploaded byte-for-byte, including nested relative paths. Non-document files, empty corpora/files, filesystem links, and unpublished generator staging are rejected.
- Managed corpora must match their complete publication manifest and allocation checksum before any network request. Standalone document directories receive document-file preflight, not a claim of canonical/native validation.

Results contain `details.uploaded_count`, `uploaded_bytes`, `failed_count`, `pending_count`, and per-file blob names/statuses/hashes. `complete` means all uploads were acknowledged by Azure; it does not claim independent remote readback. The SDK validates transfer MD5, sets content types, and stores each source SHA-256 as blob metadata.

Cloud batches are not atomic. A failure/cancellation stops further work and retains already written blobs; the last request may also have reached Azure. Inspect the JSON result before indexing the destination prefix. Retry with a new prefix or explicitly choose `--overwrite`; `push` never deletes blobs or silently skips conflicts.

The implementation follows the [Azure Blob upload guide](https://learn.microsoft.com/azure/storage/blobs/storage-blob-upload-python). No actual Azure upload is required by the offline test suite.

## Clear Blob Storage

`docgen clear` removes current blobs from one explicitly selected container. It keeps the container and storage account. Preview is the default; actual deletion requires `--yes`.

```powershell
# Preview a corpus folder using the logged-in Azure CLI user.
.\.venv\Scripts\docgen.exe clear --container documents --prefix run-YOUR-ID --account-url https://YOURACCOUNT.blob.core.windows.net --dry-run --json

# Delete the selected current versions only after reviewing the target.
.\.venv\Scripts\docgen.exe clear --container documents --prefix run-YOUR-ID --account-url https://YOURACCOUNT.blob.core.windows.net --yes --json
```

Omit `--prefix` to target all current blobs in that container. A supplied prefix is a virtual folder: `run-one` matches `run-one/` and its children, not `run-one-more` or a blob named exactly `run-one`. Authentication matches `push`: `--account-url` selects Azure CLI Entra credentials; connection strings use argument/environment/dotenv precedence.

- Each execution takes a fresh, fully enumerated selection before deleting anything. A preview is not a saved deletion plan.
- Selection is capped at 10,000 blobs. Narrow the prefix or explicitly set `--max-blobs` up to 100,000; exceeding it deletes nothing.
- Ambiguous `.` or `..` path segments in returned blob names abort selection before any deletion, preventing HTTP URL normalization from escaping the target scope.
- Every deletion uses the selected ETag with `If-Match`. Changed replacements are preserved. Once selection finishes, concurrent new blobs are not added to the deletion plan.
- Snapshots are preserved by default. A blob with snapshots blocks deletion unless you explicitly add `--include-snapshots`.
- Soft-deleted data, previous versions, legal holds, leases and retention/immutability policies are not purged or bypassed. Empty active listings do not mean permanent erasure or immediate storage-cost removal.
- Failure/cancellation stops further deletions and returns known deleted, already-absent, failed, pending and unknown counts. Exit code 3 means incomplete, and 130 means cancelled. Cloud batches are not atomic.
- `complete` requires a final empty listing of the selected active-blob scope. Concurrent writes or failed verification return incomplete.
- This command does not remove Azure AI Search documents or local runs/references. Clearing sources of a frozen experiment prevents further live collection against that source inventory.

The user needs **Storage Blob Data Contributor** or equivalent data-plane delete permission at the target scope, plus approved network access. No roles, networking or account policies are changed. See [Azure Blob deletion semantics](https://learn.microsoft.com/azure/storage/blobs/storage-blob-delete-python).

## Library

```python
from pathlib import Path
from docgen.config import load_config
from docgen.pipeline import generate, render, resume, run, validate

config = load_config(Path(r"examples\banking.yaml"))
result = run(config, Path(r"runs"))
print(result.status, result.corpus_path)
```

The same orchestration backs the CLI and library. Tests can inject an external content-provider double; no fake-provider CLI or production fallback exists.

```python
from pathlib import Path
from docgen.pipeline import push

result = push(
    Path(r"runs\run-YOUR-ID\corpus"),
    container="documents",
    prefix="run-YOUR-ID",
    env_file=Path(".env"),
)
print(result["status"])
```

The upload API returns the same versioned result dictionary as its CLI command and does not modify run state or persist credentials.

```python
from docgen.pipeline import clear

preview = clear(
    container="documents",
    account_url="https://YOURACCOUNT.blob.core.windows.net",
    prefix="run-YOUR-ID",
)
print(preview["details"]["files"])
# Pass confirm=True only when deletion of the selected scope is intended.
```

## Output and evaluation safeguards

Each run contains canonical content, SQLite checkpoints, attempts, allocation/publication manifests, reports, and at most one published `corpus` directory. Index **only** that final directory, and only after the operation reports `complete`.

Once allocated, format assignments, native layout plans, source hashes, and paths are immutable. Filenames use opaque content IDs. Native readback validates every business-text block, protected table association, and applicable spreadsheet type. Recipe runs also compare native heading/list levels where those structures are represented, plus columns, sections, sheet partitions, and slide starts required by the selected layout. It rejects hidden/rasterized content, changed checksums, clipping indicators, and extra/missing files. Rendering fails explicitly when a block cannot fit at the minimum font size; it never truncates or silently changes format.

Planning seeds reproduce allocation, not new stochastic LLM wording or binary file bytes. Lexical uniqueness is not a semantic-uniqueness guarantee. Language detection does not establish Brazilian regional style. Unique content per format supports matched-group comparisons rather than a paired causal experiment on identical content. Automated checks and visual review reduce risk; they do not prove bug-free software or retrieval quality.

Render, resume, and allocation-aware validation results include a seeded advisory sample in `details.review`. Legacy runs cover every present format. Recipe/layout runs cover every present format/complexity/layout group. The sample size is `min(N, max(present_groups, ceil(0.02 * N)))`. Its status remains `human_review_pending`: technical `complete` does not grant human content approval.

The pilot passed native fidelity and the no-critical-defect model-review gate, but contains disclosed minor wording/FAQ and spreadsheet print-preview findings. Review [the evidence and findings](docs/implementation-progress.md#final-prompt-v3-pilot) before treating it as a human-approved evaluation corpus.

Pilot runs and QA previews are deliberately excluded from distributable packages. Use the successful operation's returned `corpus_path` as the indexable directory. Source-control hosting and remote CI remain deferred.

## Paired retrieval experiments

Use [the experiment runbook](docs/experiments/usage.md) and [the validated example configuration](examples/retrieval-experiment.yaml). The workflow creates a fresh corpus and reference, then compares **Document Extraction plus Text Split** with **Content Understanding performing extraction and native semantic chunking**. Both arms share the same source files, reviewed judgments, query vectors and query-time hybrid settings.

```powershell
.\.venv\Scripts\docgen.exe experiment plan --config .\examples\retrieval-experiment.yaml --json
.\.venv\Scripts\docgen.exe experiment --help
```

The core implementation includes human review/release gates, exact parent nDCG/Precision/Recall/MRR at 1/3/5/10/20 for protocol v2, paired family-level bootstrap intervals, source-loss diagnostics, persistent request budgets, interruption recovery and snapshot-drift rejection. A smoke configuration creates two families, twelve documents, twelve intents and twenty-four utterances. No historical run is imported.

For a different Portuguese-language business topic, use [the SaaS example](examples/saas-retrieval-experiment.yaml) with `family_domain: saas`. It creates seed-specific fictional plan names, BRL monthly prices, first-response SLAs, activation responsibilities and service exclusions. Changing a seed or topic does not certify independence from previous corpora; [fresh-domain controls](docs/experiments/usage.md#fresh-business-domains) require overlap audits and frozen retrieval policies.

An explicit `experiment release --provisional` supports an all-test operational smoke with at most twelve documents. A separate `--provisional-pilot` option supports eighteen to three hundred documents in three to fifty families with at least two test families. Both keep automated-only reference assurance visible in sealed references and reports, create no human attestations, and cannot satisfy the normal human-reviewed release requirements. See the [provisional execution runbook](docs/experiments/usage.md#provisional-operational-smoke).

For a larger raw-only sample, `--provisional-study` supports 306 to 996 documents in 51 to 166 complete six-document families. Formats are balanced across the corpus, not required to appear once in every family. It preserves the existing smaller limits and records explicitly unreviewed study provenance. A balanced sample near 1,000 contains 996 documents; semantic query budgets depend on the frozen evaluated-family count. See [larger-study controls](docs/experiments/usage.md#provisional-larger-study).

New experiments and forks use protocol v2 with raw-document-only ingestion. They upload no custom Blob metadata, derive document features and embeddings only in each arm's Search skillset, and reject application-side annotations, document-vector writes and generator-assisted entity profiles. Historical v1 records remain readable for offline scoring; further live work requires a new raw-only fork. See the [enrichment boundary](docs/experiments/usage.md#raw-document-only-enrichment-boundary).

The [executed raw-only control](docs/experiments/reports/2026-10-30-example-raw-only-control.md) re-indexed the same 300 files into separate resources and collected 1,200 successful outcomes. Both arms covered every source without indexer diagnostics; independent checks verified 20,000 metric values, 60 bootstrap intervals and all request fingerprints.

The [fresh 996-document study](docs/experiments/reports/2026-11-01-example-996-document-retrieval.md) completed 1,920 paired outcomes over 40 test families. Content-only semantic hybrid achieved nDCG@10 of 0.8164 for DE and 0.8076 for CU, improving both arms over ordinary hybrid. The primary arm interval includes zero; equivalence and optimized chunking are not established. Independent checks verified 32,000 metric values, all request fingerprints and raw-only provenance.

The [DE/CU decision study](docs/experiments/reports/2026-11-02-example-de-cu-decision.md) completed 23,224 outcomes across three native-size policies, six retrieval profiles and previously unevaluated confirmation families, plus 140 equal-token model-reviewed contexts. It recommends DE as the practical native-text ingestion default, with BM25 as the immediate quota-independent retrieval option. CU retains task/evidence and footprint advantages, but no universal quality winner or equivalence was established; full semantic confirmation remains quota-blocked.

The [index and native semantic tuning study](docs/experiments/reports/2026-11-02-example-index-semantic-tuning.md) completed 12 BM25 settings, three analyzers and four native semantic policies within the existing free allowance. Both arms selected Microsoft analysis with `k1=2.4`, `b=0.75`; BM25 plus semantic was best among completed semantic candidates. The report separates the 93-family lexical comparison from 33-family semantic development results and preserves the actual quota-limited cells as unexecuted.

The [experimental Search configuration inventory](evaluations/inventory/ai-search/inventory.json) contains the recorded index, skillset, indexer and data-source JSON for both arms, with submitted/readback versions, index epochs and query policies. See [inventory export](docs/experiments/usage.md#recorded-search-configuration-inventory) to refresh it offline without modifying historical experiments or Azure resources.

A [local LLM sectioning prototype](docs/experiments/usage.md#local-llm-sectioning-prototype) tests literal title selection and source-block boundary planning using the existing Azure OpenAI deployment, without new hosting or Search resources. A twelve-file Markdown smoke accepted all plans after tightening the model schema; raw responses, the earlier rejection, controls and configuration remain recorded. These local views are never uploaded as metadata and do not establish retrieval gains or PDF/Office extraction quality.

The [executed 996-document LLM sectioning experiment](docs/experiments/reports/2026-11-03-example-llm-sectioning.md) subsequently ran enrichment inside Search across all six formats. LLM sectioning regressed BM25 and matched-hybrid retrieval, metadata weighting selected off, and the equal-budget answer diagnostic showed no compensating gain. The tuned DE recommendation remains unchanged.

Versioned development tuning can fork the same frozen sources into separate resources and compare BM25, vector, weighted hybrid and content-only semantic-reranked profiles. Native DE/CU chunk-size controls remain available. Historical title/account-assisted studies do not satisfy the v2 restriction. See [development tuning](docs/experiments/usage.md#versioned-development-tuning).

Explicit [query cohorts and evidence contexts](docs/experiments/usage.md#bounded-query-cohorts-and-evidence-contexts) support quota-bounded paired diagnostics and equal-token whole-chunk exposure. Cohorts preserve the original reference and have independent seals. Automated evidence citations must come from exposed native chunks; model review does not certify human approval.

An optional [shared entity treatment](docs/experiments/usage.md#shared-in-pipeline-entity-treatment) extracts source-grounded entity mentions inside both Search skillsets. Native Entity Recognition and experimental GenAI treatments remain explicitly versioned. The `pipeline-entity-hybrid` profile uses only pipeline-produced mentions, without a query catalog or application-side document writes.

The [executed in-pipeline entity experiment](docs/experiments/reports/2026-10-30-example-pipeline-entities.md) covered all 300 sources, verified 5,880 native source occurrences and collected 480 development outcomes. Entity weighting reduced both arms' retrieval scores and failed the predeclared loss guards, so ordinary `hybrid` remains recommended. The complete evaluation suite passed 195 cases.

Chunk entailment/support metrics and matched-format exports remain follow-ups. Reports mark evidence metrics `not_evaluated`; parent relevance does not prove that a retrieved chunk contains the answer. Offline test approval does not constitute a human-reviewed dataset or a completed live Azure benchmark.

## Documentation

| Document | Purpose |
|----------|---------|
| [Requirements](docs/requirements.md) | Functional requirements, stories, invariants, and conformance cases |
| [Architecture](docs/architecture.md) | Components, phase boundaries, Azure integration, and failure handling |
| [Contracts](docs/contracts.md) | Configuration, canonical schemas, allocation, storage, and results |
| [Content quality](docs/content-quality.md) | Generation controls, profiles, fidelity, and evaluation safeguards |
| [Implementation plan](docs/implementation-plan.md) | Dependency-linked, test-first task contracts |
| [Implementation evidence](docs/implementation-progress.md) | Test/live/visual/scale evidence and known limits |
| [Test strategy](docs/test-strategy.md) | Behavioral test inventory and release gates |
| [Glossary](docs/domain/GLOSSARY.md) | Domain definitions |
| [Sources](docs/sources.md) | Official guidance and verified Azure context |
| [Retrieval experiment design](docs/experiments/design.md) | Reference dataset, controls, metrics, statistical methodology and cost posture |
| [Experiment runbook](docs/experiments/usage.md) | Executable fresh-corpus, review, ingestion, collection and scoring commands |
| [Experiment contracts](docs/experiments/reference-contracts.md) | Identity, evidence, qrels, snapshots, rankings, scoring and release invariants |
| [Experiment implementation strategy](docs/experiments/implementation-plan.md) | Delivery slices, implemented scope and deferred research extensions |
