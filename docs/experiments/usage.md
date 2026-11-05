# Running a paired retrieval experiment

Status: Protocol v2 enforces raw-document-only ingestion; human reference approval and live Azure execution are separate gates

Verification evidence: [offline release checks](../../README.md#paired-retrieval-verification-2026-10-28)

Live protocol-v2 evidence: [300-document raw-only control](reports/2026-10-30-example-raw-only-control.md).

Shared entity treatment evidence: [300-document in-pipeline experiment](reports/2026-10-30-example-pipeline-entities.md). The tested entity-weighted profile regressed both arms; retain ordinary `hybrid`.

Fresh larger-study evidence: [996-document hybrid and semantic comparison](reports/2026-11-01-example-996-document-retrieval.md). Semantic reranking improved both arms; the current evidence does not establish DE/CU equivalence or remove the need for development-only chunk tuning.

Executed decision evidence: [native-size, retrieval, equal-token evidence and resource comparison](reports/2026-11-02-example-de-cu-decision.md). The study preserves raw-only ingestion and previously unevaluated confirmation families, recommends DE as the practical native-text default, and identifies the remaining semantic-quota and human-review limits.

Executed index tuning: [BM25, analyzers, native semantic policies and full development ANN audit](reports/2026-11-02-example-index-semantic-tuning.md). Both arms selected `k1=2.4`, `b=0.75` and Microsoft analysis. Four native semantic policies completed all 33 development families before a measured monthly quota rejection; the remaining semantic cells were not scored.

Executed LLM sectioning: [996-document source-grounded sectioning and metadata experiment](reports/2026-11-03-example-llm-sectioning.md). The actual Search pipeline indexed every source, but sectioning regressed retrieval and development selection retained metadata off. Keep tuned DE plus Text Split.

Executed matched semantic comparison: [paid sequential reranking and original-default controls](reports/2026-11-04-example-semantic-results.md). On the same 93 families, tuned DE semantic BM25 scored 0.815840 nDCG@10 versus tuned CU's 0.804055 and original DE semantic hybrid's 0.801163. The study restored the original free billing plan, retained all 50 indexes and archived all four cases' live JSON definitions. Results remain exploratory repeated-corpus evidence.

Executed topic-shifted comparison: [final corrected SaaS sources and frozen-policy repeat](reports/2026-11-05-independent-saas-results.md). All four indexes contain every one of 996 final native documents. The ten frozen conditions cover 93 families and 1,116 utterances each. Tuned DE semantic BM25 leads with 0.630991 nDCG@10 versus tuned CU's 0.612588; the paired relative gain is 3.00%, 95% CI [1.15%, 4.92%]. Original untuned hybrid controls score 0.325261 for DE and 0.313685 for CU.

The final study preserves earlier failed and measured source revisions, regenerates 61 additional whole documents following native visual QA, and collects every final ranking again without retuning. It is a technical source correction, not an additional independent replication or pristine outcome-blind confirmation. All labels remain automatically assured. Final audits verified 11,160 rankings, 186,000 metric values, 330 intervals, 80 bounded evidence contexts and strictly sequential Search requests. The historical service's 50 index names and free semantic plan remain unchanged; the isolated paid S1 service retains eight indexes across the superseded and final measurements.

## Recorded Search configuration inventory

Export the recorded JSON configurations for every experiment without contacting Azure:

```powershell
.\.venv\Scripts\docgen.exe experiment inventory --root .\evaluations `
    --output .\evaluations\inventory\ai-search --json
```

Open the generated [configuration catalog](../../evaluations/inventory/ai-search/inventory.json). It links to plain JSON files for both arms:

- Submitted index, skillset, indexer and data-source definitions, including rejected creation intents.
- Initial Azure readbacks and separately sealed post-ingestion versions.
- Every recorded BM25 index epoch and applied metadata revision.
- Frozen protocol Search settings, query collection plans and epoch query policies. Semantic configurations, scoring profiles, analyzers and vector profiles remain inside their complete index JSON.

`latest_observed_resources` points directly to the latest recorded configuration of each kind. It is historical evidence, not a claim about current Azure state. Missing observations are explicitly `not_recorded`; planned and failed workspaces are included without reconstructing their definitions from newer code.

Each entry includes its source-record checksum, configuration checksum, exported-file checksum and API version. Credential values are visibly redacted with JSON-pointer locations; managed-identity `ResourceId` connection strings and Azure-withheld null values remain intact. No source database, published report or Azure resource is modified.

Repeated export is idempotent for unchanged records. Content-addressed JSON files and versioned catalogs preserve earlier inventories; `inventory.json` selects the current catalog. To export one workspace, use `--experiment` instead of `--root` and choose a separate output directory:

```powershell
.\.venv\Scripts\docgen.exe experiment inventory --experiment $experiment `
    --output .\evaluations\single-experiment-inventory --json
```

The command refuses corrupted source records, filesystem links, changed exported files and an output catalog belonging to another source.

## Local LLM sectioning prototype

Run the planner locally against the existing Azure OpenAI deployment. This requires no Function App, app registration, new Search index or hosting plan. The model still runs in Azure; this command does not install an on-device model.

The initial reader accepts raw UTF-8 Markdown files. It preserves their original characters and native block order, exposes short block IDs, and requests a literal title reference plus section-start references. Tables, lists and recognized question/answer units remain atomic. The model cannot rewrite section bodies; deterministic slicing materializes them from the original text.

Create offline controls and inspect the exact proposed model requests:

```powershell
.\.venv\Scripts\docgen.exe experiment section-trial --source $rawMarkdownDirectory `
    --output .\evaluations\section-local --sample-size 12 --seed 42 `
    --max-chunk-characters 4000 --json
```

Authorize a bounded live planner trial using the same existing subscription:

Replace the example endpoint and all-zero subscription identifier with your own values before running this paid command.

```powershell
.\.venv\Scripts\docgen.exe experiment section-trial --source $rawMarkdownDirectory `
    --output .\evaluations\section-local --sample-size 12 --seed 42 `
    --max-chunk-characters 4000 --max-input-tokens 12000 `
    --max-completion-tokens 2048 --max-total-tokens 100000 --timeout-seconds 30 `
    --base-url https://example.openai.azure.com/openai/v1/ `
    --deployment gpt-5.4-mini `
    --subscription 00000000-0000-0000-0000-000000000000 --live --json
```

Use `--sample-size 1` for one input file. A directory selector samples its immediate Markdown files reproducibly, without opening canonical facts, qrels or other sidecars. Keep the output directory outside the raw source directory. Azure CLI authentication uses the explicit subscription; authentication failures do not switch identities or endpoints.

| Local treatment | Purpose |
|-----------------|---------|
| Unsectioned baseline | Pack atomic source blocks under the fixed character bound |
| Native headings | Use the document's existing Markdown heading boundaries |
| LLM metadata only | Keep baseline chunks unchanged and add the model-selected literal document title |
| LLM sections only | Apply proposed boundaries without enabling title/section metadata |
| LLM metadata and sections | Apply the same boundaries and expose the literal title/heading references |

These are local diagnostic views, not indexed retrieval arms. Every view uses the same block packer, with no overlap. The 4,000-character smoke bound accommodates its longest atomic FAQ; an oversized block fails explicitly rather than being split, dropped or silently given a larger limit. This packer does not reproduce Azure Text Split or CU token chunking.

Each fresh trial retains:

- The selected raw bytes, source hashes and original offsets.
- Native controls and the complete model request, including its source-constrained JSON schema.
- A durable intent before every model dispatch, exact HTTP response bytes and observed token usage.
- Accepted plans and separate metadata/sectioning views, or explicit rejected outcomes.
- Attempt, input, output, timeout and observed-token limits. No model request is automatically retried.

Input-token reservations are conservative `cl100k_base` estimates of the complete request, including its schema, plus 1,024 tokens. Actual provider usage remains authoritative. Missing usage or a transport-unknown outcome blocks subsequent calls. An interrupted dispatched attempt is recorded as unknown, not as a valid empty title or an undispatched document.

All outputs remain local test artifacts. Nothing is uploaded as Blob metadata, merged into Search or used to replace document vectors. A real Search custom skill later needs an authenticated HTTPS endpoint reachable by the hosted indexer; ordinary localhost is inaccessible. Hosting on Azure Functions is optional. PDF/Office extraction, live skillset execution and retrieval/answer-support evaluation remain separate gates.

### Executed local smoke

The exploratory smoke reused twelve raw Markdown files from the existing 996-document corpus. It provides development evidence, not an independent confirmation sample or a six-format comparison.

| Pass | Accepted plans | Model dispatches | Observed tokens |
|------|----------------|------------------|-----------------|
| Initial schema | 11 of 12 | 12 | 22,318 |
| Authentication failure before dispatch | 0 of 12 | 0 | 0 |
| Source-constrained schema | 12 of 12 | 12 | 26,683 |

The independent checks found:

- All twelve selected titles matched the existing native document titles. This sample demonstrates no additional title information from the LLM.
- LLM and native-heading boundaries matched in six documents and differed in six.
- Unsectioned packing produced 22 chunks; native headings produced 58 sections/chunks; the LLM produced 53 sections and 55 chunks.
- Every diagnostic view reconstructed the complete original text, stayed within the 4,000-character bound and preserved its protected tables, lists and FAQ units.
- The successful pass recorded a median local model roundtrip of about 1.37 seconds and a maximum of about 2.44 seconds, including response capture and validation. These are not hosted-skill latency measurements.

The two model passes used 24 dispatches and 49,001 observed tokens in total. Chunk counts and boundary agreement are descriptive diagnostics, not relevance or answer-support scores.

The first pass correctly rejected a cross-section heading reference. The second model pass constrained decoding to valid source/start/heading pairs instead of repairing the rejected annotation. The original failed trial and a transient Azure CLI discovery failure remain recorded.

Open the [successful local summary](../../evaluations/section-local/section-trial-b55050b779f347778823e91fcdf0450e/summary.json), [independent verification](../../evaluations/section-local/section-trial-b55050b779f347778823e91fcdf0450e/verification.json) and [initial rejected trial](../../evaluations/section-local/section-trial-946a5c7f5459434689d98614411365bb/summary.json). The verification also records a corrected advisory metadata-only view flag; the title-only view's actual chunks and absent section headings were unchanged. Historical files were not rewritten.

Exact source coverage and literal labels establish mechanical integrity. They do not prove useful semantic grouping, retrieval improvement or human approval. Keep the current DE recommendation until a Search-pipeline comparison measures those outcomes.

### Live Search-pipeline follow-on

The [completed live experiment](reports/2026-11-03-example-llm-sectioning.md) used the same 996 raw documents, with a staged two-per-format smoke and incremental full ingestion. Its authenticated skill ran Document Extraction output through the source-bound planner and original-text materializer before native Text Split and embedding. No local prototype annotations were uploaded.

The opt-in `search.variant.section_enrichment` object requires an authenticated Function `uri` ending in `/api/sections` and its `api://` Entra application `auth_resource_id`. It affects only DE; the CU reference remains native. The existing paired defaults stay unchanged. Library preparation/ingestion can select `arms=("de_split",)` when only one index slot is available.

The service implementation and composed infrastructure live in [the section skill](../../services/section-skill/). The deployed study uses private, keyless audit storage and authorizes only Search's identity. Its durable 1,100-attempt/8,000,000-token ledger and request cache are study-scoped; do not assume the completed endpoint has an unlimited budget for another corpus.

The initial audit-field schema failure and its conditional repair are preserved in the [configuration inventory](../../evaluations/inventory/ai-search/inventory.json). Current definitions create large provenance fields with search, filtering, sorting and faceting disabled. The executed candidate retained its original auxiliary columns and added a retrievable-only audit replacement rather than deleting the index; its exact historical readbacks remain visible.

## What this measures

The primary comparison is CU minus DE on parent-document nDCG@10. Protocol v2 reports Precision, Recall, nDCG and MRR at 1/3/5/10/20. Both arms index the same files and use identical query policies. The primary control uses hybrid retrieval without query-time semantic reranking; content-only semantic reranking is a separately frozen profile.

- DE uses Document Extraction and Text Split, with 2,000 characters and 200-character overlap.
- CU uses native semantic chunking, with 2,000 tokens and no overlap.
- These are different combined extraction/chunking policies, not equivalent chunk sizes or an extraction-only intervention.
- The source-derived reference is released before ingestion. Source losses remain in Recall and IDCG denominators.

## Raw-document-only enrichment boundary

Every new experiment and fork uses protocol v2 with `enrichment_policy: search-pipeline-only`.

- Upload only the native file bytes with their MIME types. Do not attach custom Blob metadata, source titles, account-name lists, sidecar facts or generator-derived dictionaries.
- Derive document features and embeddings through each arm's Search skillset. Application-side document merges and document-vector replacement are forbidden.
- Use only the query text for request construction. Generator-derived entity catalogs, relevance labels and family IDs cannot add boosts or filters.
- Keep canonical sources, reference facts and qrels in the evaluator. They can establish source identity, integrity and scoring truth, but cannot supply document or query features.
- Keep source paths and document IDs as non-ranking identity/provenance plumbing.

Entity extraction is a separately versioned, shared skillset treatment. Each arm derives entities from its own extracted text, using the same extractor settings. An extraction loss cannot be repaired using canonical facts or the other arm's output. Protocol v2 continues to reject the historical generator-assisted entity profiles.

Historical protocol v1 workspaces remain readable for status and offline scoring. Live preparation, ingestion and collection require a new raw-only fork. Existing protocols, references, snapshots, requests and reports are not rewritten.

## Configure existing Azure resources

Install the project as described in [the README](../../README.md). Copy and edit [retrieval-experiment.yaml](../../examples/retrieval-experiment.yaml), replacing every `replace-me` selector.

| Configuration | Required selection |
|---------------|--------------------|
| `generation.provider` | Existing Azure OpenAI v1 chat deployment for document authoring |
| `search.endpoint` | Existing Azure AI Search service |
| `search.ai_services_endpoint` | Foundry resource available to the CU skill |
| `search.embedding` | Existing embedding deployment used by both skillsets and query vectors |
| `search.model_name`, `dimensions` | Actual embedding model and supported dimensions |
| `storage.resource_id`, `container` | Existing Storage account ARM ID and private container |

Use `az login` and select the intended subscription/tenant before live phases. Required access:

- The logged-in user needs Blob Data Contributor on the corpus container, Search Service Contributor for resource definitions, Search Index Data Reader for queries, and the appropriate inference role on the model resources. Application-side document-writer access is unnecessary: indexers perform all document enrichment and writes.
- The Search service's system-assigned managed identity needs Blob Data Reader on the container, Cognitive Services User on the attached Foundry resource, and the embedding service's inference role.
- Network rules must permit the relevant user and service paths. The application does not change networking, assign roles, create containers or deploy models.
- Both skillsets use `search.cu_api_version`, pinned to `2026-05-01-preview`: CU semantic chunking and DE's explicit Text Split `unit` require the preview contract. Both creation and readback use that version. Queries and the other Search resource definitions use `2026-04-01`; unsupported treatment settings fail rather than falling back.

Do not upgrade the embedding deployment during the experiment. Deployment/model version changes not exposed by Search definitions require external operational control.

## Plan, initialize and generate

The example is a smoke experiment: two families, twelve native documents, twelve intents and twenty-four utterances, all in the test split. Its intervals are exploratory.

```powershell
$docgen = '.\.venv\Scripts\docgen.exe'
$config = '.\examples\retrieval-experiment.yaml'
& $docgen experiment plan --config $config --json
$created = & $docgen experiment init --config $config --output .\evaluations --json |
    ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Experiment initialization failed.' }
$experiment = $created.details.experiment_path

# Explicitly authorize bounded paid document authoring.
& $docgen experiment generate --experiment $experiment --live --json
& $docgen experiment reference-build --experiment $experiment --json
```

`plan` performs no writes or Azure calls. `init` freezes unique source/resource identities and the effective family plan. Repeating `generate` resumes the same source run and retains accepted documents and format assignments.

Generation results and the persisted run summary include cumulative authoring requests and observed tokens, including earlier attempts on resume. Offline rendering does not reset those counters. Observed tokens are usage evidence, not a monetary cost estimate.

Resuming retains rejection feedback for unfinished source slots so the next authoring request can correct earlier validation failures. The feedback remains untrusted task context; source, fact, structure and length checks are unchanged. Invalid or foreign-run rejection reports stop the resume before new model calls.

An explicit audited per-item retry override can allow up to forty candidates when difficult source slots exhaust their default three attempts. Increasing that allowance alone leaves the overall request and observed-token ceilings unchanged; it does not relax validation or rewrite accepted sources. Record the original failed summary and accepted hashes before a study recovery, and disclose any departure from the preregistered authoring allowance separately from unchanged retrieval settings.

Native table layout preserves source text. PowerPoint keeps its readable fourteen-point table font and expands columns for long unbreakable words when the slide has enough total width, rather than shrinking, truncating or rewriting the content.

The preset creates related fictional account documents with scoped fees, eligibility, procedures, conditions and exceptions. Structure and native format still use the generator's seeded controls. Claim coverage is frozen before prose; exact evidence locations are resolved from accepted content.

### Fresh business domains

The default family preset remains fictional banking. Set the experiment-level `family_domain: saas` to generate Portuguese-language enterprise software subscriptions and support commitments instead. Use [the complete SaaS smoke configuration](../../examples/saas-retrieval-experiment.yaml):

```powershell
& $docgen experiment plan --config .\examples\saas-retrieval-experiment.yaml --json
```

The SaaS preset freezes two plan entities per family and five fact types per entity: BRL monthly subscription price, first-response SLA, activation, service exclusion and workflow ownership. Its six document roles support price, response, exclusion, comparison, activation/ownership and unanswerable-hosting-country questions. A first-response SLA never asserts a resolution deadline.

Entity catalogs depend on the seed. Source protocols and run namespaces are new at initialization; local ordinal document IDs may repeat between namespaces. Omit `family_domain` to preserve the original banking families, prompt bytes and historical serialization. The supplied SaaS facts and question templates target `pt-BR`.

SaaS Azure authoring submits and validates the same fact-bound response schema. It binds fact identities, entities, values, units and compatible numeric table columns. Quantitative prose uses fact placeholders. Length-aware requests also bind frozen slots and minimum prose/list production budgets; final fact, structure, word-band and native-rendering checks remain unchanged. Failed candidates remain recorded rather than padded, rewritten or silently accepted. Exhausted systemic transport retries stop further source-item dispatch.

For a separate-corpus comparison:

- Initialize a fresh protocol rather than forking a previous dataset.
- Freeze domain, generation limits, cohort, retrieval/index settings and acceptance criteria before observing rankings.
- Audit native and canonical hashes, normalized entity/question overlap and cross-corpus business-text similarity against prior sources. Changing the topic alone does not establish independence.
- Create query embeddings from the new questions. Sharing sources and question vectors between treatments within this new corpus preserves the paired comparison.
- Keep all indexing enrichment inside Search and all Search requests sequential.
- Keep automatic reference assurance explicit. New artifacts and a new topic do not remove shared generator, renderer, template or evaluator bias.

Fork only within the new study when comparing tuned and original settings on identical new sources. Such a fork is a paired treatment, not another independent corpus.

## Review and release the reference

Open the returned `reference-draft.json` in the experiment directory. Review each intent against its canonical source and rendered document:

1. Check both utterances, entity scope, answerability, answer and required claims.
2. Check every in-family grade and cited block/list/table evidence. Table values require their subject, header and applicability context.
3. Confirm that outside-family documents cannot answer the explicitly scoped query.
4. Edit queries and mark edited utterances `authorship: human` for at least 20% of intents. A text change is mechanically required; human origin and semantic equivalence remain reviewer attestations.

Templates ask about stated BRL amounts and age requirements. A currency amount alone does not establish a monthly billing cadence, and an age value alone does not establish a minimum threshold. Verify any additional qualifiers and exceptions against the accepted text during human review. Scope validation distinguishes complete account names, including a base account versus its `Plus` sibling, and rejects additional known entities outside the intent's declared scope.

Rebuilding preserves existing drafts and their wording. Revise unsupported qualifiers before approval; automated corrections must retain `authorship: template` and do not satisfy the human-writing requirement. Never rewrite a released reference.

Record approval only after that review:

```powershell
& $docgen experiment review --experiment $experiment `
    --intent family-0001-fee --reviewer 'Reviewer Name' --certify-scope --json
```

Every intent needs approval. No-answer and multi-claim intents, plus a seeded 20% sample of the others, need a second distinct reviewer. The command records a payload-bound event; editing that intent invalidates its previous approvals. Reviewer names are local audit attestations, not authenticated identities. Do not automate approvals or invent reviewer names.

```powershell
& $docgen experiment reference-validate --experiment $experiment --for-release --json
& $docgen experiment release --experiment $experiment --json
```

Release writes immutable reference JSON and exhaustive TREC qrels with a checksum seal. Rebuilding the draft preserves edits. Released truth cannot be reapproved or replaced; changed semantics require a new experiment.

### Provisional operational smoke

For pipeline validation without human approval, an explicit provisional release is available only for an all-test experiment with at most two families and twelve documents:

```powershell
& $docgen experiment release --experiment $experiment --provisional --json
```

This mode still validates source lineage, evidence, query scope and judgment coverage, and seals the reference and qrels. It does not create reviewer attestations or relabel template questions as human-authored. The reference has `status: provisional`; scored reports also have `status: provisional`, an automated-only warning and `human_review_certified: false`.

Use the normal ingestion and scoring commands below. Treat the results as an operational smoke check, not a validated benchmark or a confirmatory choice of retrieval strategy. Release mode is immutable. The normal release command remains human-reviewed, and a larger experiment cannot use this smoke-only exception.

### Provisional exploratory pilot

For a larger automated comparison, a separate explicit policy permits eighteen to three hundred documents in three to fifty families, with at least two test families in the frozen family plan:

```powershell
& $docgen experiment release --experiment $experiment --provisional-pilot --json
```

The prepared 300-document plan reserves ten families for calibration, ten for development and thirty for test evaluation. Both indexes contain all 300 sources; the primary comparison uses only the 360 held-out test utterances. Keep the retrieval controls fixed before collecting test results.

This option preserves source/evidence/checksum checks and records `automated_pilot` provenance. Its reports remain provisional, identify `reference_assurance_mode: automated_pilot`, and do not certify human review or permit confirmatory conclusions. It is mutually exclusive with `--provisional`; the twelve-document smoke limit and default human-reviewed release remain unchanged. A sealed release cannot switch between these policies.

### Provisional larger study

A separately opted-in raw-only study supports 306 to 996 documents in 51 to 166 complete six-document families, with at least two frozen test families:

```powershell
& $docgen experiment release --experiment $experiment --provisional-study --json
```

The existing six-documents-per-family contract makes 996 the largest balanced sample below 1,000. Formats are balanced globally; each family is not required to contain one source in every format. Exactly 1,000 documents are not accepted by the paired family protocol. The smoke and 300-document pilot limits remain unchanged.

This policy keeps every source, evidence, checksum, query and judgment validation. It records `automated_study`, keeps reference/report status provisional, and identifies `reference_assurance_mode: automated_study` without certifying human review. All three provisional flags are mutually exclusive; default human-reviewed release remains unchanged.

Choose the evaluation-family allocation and query profiles before authoring or reading results. A 166-family plan with calibration/development/test shares 0.56/0.20/0.24 allocates 93/33/40 families. All 996 documents are indexed, while its 40-family test requires 960 semantic requests for two arms and two utterances per intent. Query count depends on evaluated families, not total corpus documents. Preserve a semantic dispatch ceiling, wait for an approved free-quota renewal when necessary, and never enable paid billing or silently substitute ordinary hybrid results.

## Upload, ingest and freeze both arms

```powershell
& $docgen experiment prepare --experiment $experiment --live --json
& $docgen experiment ingest --experiment $experiment --wait-seconds 300 --live --json
& $docgen experiment snapshot --experiment $experiment --arm de_split --live --json
& $docgen experiment snapshot --experiment $experiment --arm content_understanding --live --json
```

`prepare` uploads only the published source artifacts to the unique protocol prefix and creates dedicated data sources, indexes and skillsets. It refuses overwrites and foreign resource collisions. `ingest` creates each indexer once; Azure starts its initial run. Repeating the command checks progress without resetting or rerunning the indexer.

Azure can advance data-source and indexer ETags during their initial execution without changing their definitions. The workflow retains creation records and seals terminal resource versions after indexing completes. Before that first seal, only the ETag of those two resource kinds may change; all other fields and index/skillset versions remain locked. Subsequent version changes still block snapshots and collection.

## Versioned development tuning

Keep the completed experiment unchanged. Copy its configuration and add explicit `search.variant` settings:

```yaml
search:
  # Retain the source experiment's endpoint, embedding and API settings.
  variant:
    embedding_context: false
    de_tokens: null
    de_overlap_tokens: 64
    cu_tokens: 2000
```

The snippet is an addition to the complete source configuration, not a standalone configuration. Keep generation, seed, formats, splits, storage and embedding space identical. Operational limits can be set for each new variant before initialization.

```powershell
& $docgen experiment fork --experiment $sourceExperiment `
    --config .\evaluations\tuning-config.yaml --output .\evaluations\tuning --json
```

`fork` validates and copies the same accepted canonical sources and native files into a new workspace with separate resource names and a unique Blob prefix. It preserves query wording, judgments and qrels, inherits the original reference assurance, and records the source lineage. It does not generate another independent corpus. Authoring is forbidden in a fork. Previously validated query embeddings can be inherited without charging their original usage again.

Query vectors created after a fork also need sharing before cross-variant comparisons. The evaluator's `inherit_query_vectors` API validates the identical embedding endpoint, deployment, model and dimensions, then copies only confirmed question-vector cache entries with known usage. It never replaces conflicting target entries. Use it under both workspace locks before collecting a newly evaluated cohort; independent verification should compare the actual question vectors across cases, not only the configured model names.

New variant indexes contain native chunk content, pipeline-generated embeddings and technical source identities. They do not receive canonical source titles, account names or context hashes. `embedding_context` must remain `false`; `true` fails before a new protocol is created. Native chunk-size controls remain available.

Earlier protocol v1 development studies used application-supplied source annotations and optional context-prefixed re-embedding. Those assisted results remain historical and do not satisfy the raw-only restriction. Their immutable records remain available for offline inspection.

Available common retrieval profiles:

| `--profile` | Behavior |
|-------------|----------|
| `hybrid` | Original content-only lexical/vector mixture, vector weight 1 |
| `bm25` | Content-only lexical retrieval without query embeddings |
| `vector` | Vector-only retrieval |
| `hybrid-lexical` | Content-only hybrid, vector weight 0.5 |
| `hybrid-vector` | Content-only hybrid, vector weight 2 |
| `hybrid-wide` | Content-only hybrid, vector weight 1, vector k 100; raw returned depth remains 50 |
| `entity-hybrid` | Historical v1 assisted profile; rejected in new raw-only experiments |
| `semantic-hybrid` | Content-only hybrid plus common semantic reranking |
| `semantic-hybrid-lexical` | Content-only semantic hybrid, vector weight 0.5 |
| `semantic-hybrid-vector` | Content-only semantic hybrid, vector weight 2 |
| `semantic-hybrid-wide` | Content-only semantic hybrid with vector k 100 and raw returned depth 50 |
| `semantic-bm25` | Content-only BM25 followed by semantic reranking, without query embeddings |
| `entity-semantic` | Historical v1 assisted profile; rejected in new raw-only experiments |
| `pipeline-entity-hybrid` | Original question over content and pipeline-extracted entities, with common field weights 1 and 2; requires explicit entity extraction |

```powershell
& $docgen experiment prepare --experiment $variant --live --json
& $docgen experiment ingest --experiment $variant --wait-seconds 300 --live --json
& $docgen experiment snapshot --experiment $variant --arm de_split --live --json
& $docgen experiment snapshot --experiment $variant --arm content_understanding --live --json
& $docgen experiment collect --experiment $variant --split development `
    --profile semantic-hybrid --live --json
& $docgen experiment score --experiment $variant --split development `
    --profile semantic-hybrid --json
```

Each allowed profile has independent fingerprint-bound requests, ranking records, collection seals and report files. Shared query-vector cache entries are reused across profiles and arms. Semantic partial results, missing scores and fallback ordering fail explicitly; they are not successful empty rankings or alternate ranking modes. Both arms receive the same query policy.

Tuning reports include cutoffs 1/3/5/10/20 and retain the original nDCG@10 primary endpoint. Use development data for selection. A subsequent analysis of an already inspected test split remains exploratory.

For native chunk-size variants, set `de_tokens: 512` with overlap 64 or 128, and test `cu_tokens: 1024` or 512. CU still performs native semantic chunking with zero overlap. New indexer executions can introduce extraction variability even when settings are unchanged; compare frozen chunk text hashes before calling a context comparison an isolated embedding ablation.

Semantic ranking can incur charges or exhaust a free-tier quota. Inspect service readiness before collection, freeze the profile sequence and budgets, and do not silently enable paid billing or substitute fallback results. Ingestion-side embedding and CU charges are not reported by the Search API.

### Index and semantic tuning controls

Index and query controls are opt-in additions to the complete fork configuration:

```yaml
search:
  variant:
    embedding_context: false
    de_tokens: null
    de_overlap_tokens: 64
    cu_tokens: 1024
    index_tuning:
      analyzer: microsoft
      bm25_k1: 1.2
      bm25_b: 0.75
      hnsw_m: 4
      hnsw_ef_construction: 400
      hnsw_ef_search: 500
    query_tuning:
      vector_k: 100
      vector_weight: 0.5
      vector_exhaustive: false
      search_mode: any
limits:
  max_semantic_attempts: 0
```

Merge the example into the original complete configuration and retain its other limits. The zero semantic budget deliberately blocks semantic dispatch until a separately authorized positive limit is frozen in a new experiment. Setting a budget does not change the service billing plan.

| Control | Supported values and effect |
|---------|-----------------------------|
| `analyzer` | `microsoft`, locale-specific `lucene`, or `standard`; Brazilian Portuguese uses `pt-Br.microsoft` or `pt-Br.lucene`, never generic `pt.lucene` |
| `bm25_k1` | Finite number from 0 to 3; controls term-frequency saturation |
| `bm25_b` | Finite number from 0 to 1; controls chunk-length normalization |
| `hnsw_m` | Integer from 4 to 10; graph connectivity |
| `hnsw_ef_construction` | Integer from 100 to 1,000; graph construction candidates |
| `hnsw_ef_search` | Integer from 100 to 1,000; graph search candidates |
| `vector_k` | Optional integer from 50 to 1,000; overrides the selected vector profile's candidate count |
| `vector_weight` | Optional finite number greater than 0 and at most 10; overrides the selected vector profile's weight |
| `vector_exhaustive` | Boolean; compares exact KNN with the HNSW graph on the same vectors |
| `search_mode` | `any` or `all`; original question wording remains unchanged |
| `index_tuning.analyzer_comparison_fields` | Optional Boolean; projects the same native chunk text into `content_lucene` and `content_standard` inside the skillset |
| `query_tuning.analyzer` | Optional `default`, `lucene` or `standard`; selects the corresponding native-text field and requires comparison fields for nondefault choices |

Query overrides apply consistently to vector/hybrid profiles and their semantic counterparts. Lexical profiles never request or send query vectors. All profiles retain raw returned depth 50, content-only search, full coverage and strict semantic failure handling. Omitting these controls preserves historical requests and serialized configuration.

Use the following staged comparison:

1. Freeze native chunking and embedding settings. Compare HNSW top-50 chunk sets with exhaustive KNN before spending capacity on graph variants. ANN candidate recall does not measure answer relevance.
2. Compare BM25 `k1` and `b`, then analyzers, using development families and predeclared Precision@1/Recall@10 loss guards. New indexing executions can change native extraction; verify source text/vector hashes before interpreting differences as index-only effects.
3. Compare `semantic-bm25` with semantic hybrid candidates under the same index settings. Vary vector weight and k while returning 50 chunks. Score Precision, Recall and nDCG at 1/3/5/10/20.
4. Recheck finalists with the same whole-chunk token cap and untouched confirmation data. Once all existing families have supplied evaluated results, further reuse is exploratory rather than independent confirmation.

For lexical semantic collection:

```powershell
& $docgen experiment collect --experiment $variant --split development `
    --profile semantic-bm25 --live --json
& $docgen experiment score --experiment $variant --split development `
    --profile semantic-bm25 --json
```

An optional `max_semantic_attempts` counts actual dispatches, including retries, rejected responses and unknown outcomes after interruption. Successful cached requests can be reused after the limit is reached; nonsemantic requests retain their separate Search budget. The limit is per workspace. A multi-workspace study also needs an aggregate dispatch guard.

The CLI creates separate resources and does not update sealed indexes in place. Check remaining index, indexer and skillset slots before a grid; lack of capacity does not authorize deleting historical resources or upgrading the service. Changes to index analysis or HNSW require new indexing and can incur CU and embedding charges.

An explicitly registered parameter-epoch study can fit the lexical grid into two isolated indexes. The pipeline projects identical native text into the analyzer fields once; snapshot auditing rejects any difference between these copies. Semantic reranking still reads the original `content` field once. Each stage conditionally updates only BM25 `k1`/`b` on its owned indexes using the prior ETag and retains an append-only intent, readback and query-policy record. Indexer execution and all other resource definitions remain pinned. Fresh complete text/vector and raw-source audits bracket the study. Ordinary CLI collection refuses an epoch-managed index rather than treating a changed definition as its original snapshot.

Application dispatch counts do not establish the service's remaining semantic allowance. Verify readiness with a bounded native semantic request on the current plan; record actual quota rejections, retain an aggregate attempt cap and never reset quota state or silently enable paid billing.

Collectors execute requests sequentially. The [sequential semantic continuation](reports/2026-11-04-example-semantic-confirmation.md) also uses one shared request gate across its default and tuned cases, a process lock and a one-second gap between logical query calls. Deliberate pacing is excluded from recorded request latency. Existing confirmed responses remain reusable.

The subsequent [authorized paid execution](reports/2026-11-04-example-semantic-results.md) completed the matched comparison. Its controller changed only `properties.semanticSearch`, restored the prior free plan after Search collection and verified unchanged capacity and historical indexes. Paid consent applies service-wide during that window. Restoring free billing does not make an exhausted allowance available again.

| Response | Required handling |
|----------|-------------------|
| HTTP 429 | Honor `Retry-After` within the frozen retry and deadline limits |
| HTTP 402 on a semantic request | Record `semantic_quota`, stop without retry or fallback, and wait for renewed allowance or explicit paid-plan authorization |
| Partial semantic response | Reject it rather than scoring an ordinary-search substitute |

Sequential execution does not restore an exhausted monthly semantic allowance. The continuation preserves original protocols and attempt ledgers. New queries use a separate bounded ledger, while inherited confirmed queries retain their original provenance. A blocked readiness result prevents collection; an explicit recheck preserves the previous result instead of overwriting it.

These controls use the pinned stable query API. Preview query rewriting and `maxTextRecallSize` require a separate API-version treatment and are not accepted as arbitrary configuration keys. Captions, answer extraction and timeout settings are not substitutes for semantic relevance tuning.

Official references: [BM25 parameters](https://learn.microsoft.com/azure/search/index-ranking-similarity), [HNSW configuration](https://learn.microsoft.com/azure/search/vector-search-how-to-create-index) and [semantic query requests](https://learn.microsoft.com/azure/search/semantic-how-to-query-request).

### Bounded query cohorts and evidence contexts

An explicit cohort can select complete intents within one released split without rewriting the reference or qrels. A cohort JSON file contains `name`, `split` and unique `intent_ids`. Every utterance from each selected intent remains required for both arms:

```json
{
  "name": "selected-intents",
  "split": "test",
  "intent_ids": ["family-0001-fee", "family-0002-fee"]
}
```

Replace the example identifiers with intents actually present in the selected split. Freeze the selection before reviewing results. `collect` and `score` accept the same `--cohort` path:

```powershell
& $docgen experiment collect --experiment $variant --split test `
    --profile semantic-hybrid --cohort .\selected-cohort.json --live --json
& $docgen experiment score --experiment $variant --split test `
    --profile semantic-hybrid --cohort .\selected-cohort.json --json
```

Cohort membership cannot change under the same name. Cohorts have separate collection plans, seals, reports and TREC exports; they cannot mark an entire split/profile complete. Status lists them under `completed_cohorts`. Existing full-split exports retain their original names and serialization.

The evidence-context API exposes the ranked whole-chunk prefix within a declared token budget, including technical citation wrappers. It stops before the next chunk would exceed the budget and never skips chunks using relevance labels. An empty ranking or first-chunk overflow remains explicitly visible.

Automated evidence assessments must cover each required claim exactly once and cite literal text from exposed native chunks. Whitespace-only normalization permits native line wrapping; inferred quotes, unexposed chunks and mismatched context text fail. These checks establish citation provenance, not human semantic approval. Model-rated answer correctness or sufficiency must be reported separately from human-reviewed chunk entailment. No evaluator output can enrich indexed documents or alter runtime retrieval requests.

Short citation aliases such as `c1` can identify exposed chunks without asking a model to reproduce long opaque Search keys. The evaluator maps only those exact declared aliases to frozen chunk IDs; it never uses fuzzy matching, repairs quote text or changes the exposed whole-chunk prefix. Preserve the raw assessment and alias map, then apply the same literal quote checks to the resolved citations.

For automated chunk-support review, the model can select supporting chunk aliases rather than generate quotations. The evaluator resolves each alias to that complete exposed native chunk and retains its exact text as the citation. Unknown, repeated or unexposed identifiers fail. This constrains citation provenance without certifying the model's semantic support judgment or changing the answer model's context.

### Shared in-pipeline entity treatment

The native treatment uses Entity Recognition V3 followed by a Shaper skill. Add this to the complete source configuration before creating a new fork:

```yaml
search:
  variant:
    embedding_context: false
    entity_extraction:
      version: "3"
      method: ner
```

Both arms extract Product and Organization mentions from their own native chunk text, with the same language and minimum precision 0.5. The Shaper retains the source text of each recognized occurrence in `entity_data/entities`, including repeated mentions. Version 3 requires exact source-character grounding and permits at most 512 occurrences per chunk. It uses no custom model endpoint, catalog or supplied reference facts. Empty arrays remain valid structured outputs.

General NER can return partial product names, organization names and generic spans. Grounding is not proof of semantic entity accuracy; measure its retrieval effect before recommending it.

The experimental GenAI alternative is configured separately:

```yaml
search:
  variant:
    embedding_context: false
    entity_extraction:
      version: "2"
      deployment: gpt-5.4-mini
      base_url: https://replace-me.openai.azure.com/openai/v1/
```

The GenAI deployment must already exist at the explicit Azure OpenAI v1 base URL and support the GenAI Prompt skill's chat-completions endpoint. Do not infer this model endpoint from the CU endpoint: a Foundry resource can expose different hosts for these APIs. The Search system-assigned identity needs inference access. The application creates no model deployment and grants no document-writer access.

Both skillsets run the same GenAI Prompt skill on their own native chunk text. Version 2 requests proper financial-product names without a supplied catalog, source-specific examples or reference facts. It permits whitespace-only folding of PDF line breaks while preserving source words, case, accents and punctuation. It rejects inferred, repaired or translated names. Structured output contains an `entities` array, with at most 1,024 completion tokens and sixteen names of 256 characters each. Native document embeddings still consume only native chunk text. Version 1 retains its original exact-character grounding for historical audits.

Index projections retain the complete structured output as `entity_data`, whose searchable member is `entity_data/entities`. Mapping the whole object preserves valid empty arrays without dropping native chunks. Snapshots require this object and an explicit array, reject missing or ungrounded values, and retain the actual indexed entities. Versions 1 and 2 reject duplicate names; native version 3 retains repeated source occurrences. This is an audit gate: the client never repairs, drops or writes annotations back to Search. Later entity drift invalidates collection like text/vector drift.

Compare `hybrid` and `pipeline-entity-hybrid` on the same frozen treatment indexes. The latter uses `searchFields: content,entity_data/entities` and a shared scoring profile; it does not build a query-name catalog, rewrite the question or introduce gold-dependent filters. Reports include extracted-entity coverage independently of retrieval scores. A grounded span alone does not establish correct semantic entity typing or improved relevance.

First validate readiness through a bounded in-pipeline smoke. Versions 2 and 3 set indexer batch size to one and execute the arms sequentially to respect shared resource request limits. Keep failed creation intents unchanged and create a new workspace for definition corrections. GenAI inference and native entity recognition add indexing cost; model/service usage is not currently retained by the index projection. GenAI can still infer unsupported names on a larger corpus; grounding failures block scoring rather than silently dropping or repairing outputs. Do not mix this treatment with a semantic billing upgrade or native chunk-size changes.

Both indexes use the same supported content analyzer: `pt-Br.microsoft` for Brazilian Portuguese or `en.microsoft` for English. If a rejected resource definition requires a code correction, initialize a new experiment rather than rewriting the old workspace's immutable creation intent.

Azure index projections require a searchable document key with the `keyword` analyzer. Both indexes use that key schema. Ordinary hybrid retrieval searches only `content`; the explicit pipeline entity profile also searches `entity_data/entities`. Neither profile searches document identifiers.

Preparation records a local upload intent before writing each source and verifies its actual SHA-256 through a conditional `If-Match` download. It rejects preexisting blobs without an owned upload intent, all custom Blob metadata, and changed source versions. The final inventory must contain those exact verified versions. Repeated preparation reuses byte-verification records for unchanged versions. These verification reads consume the Blob-operation budget.

Historical workspaces without byte-verification seals cannot reuse snapshots or scoring without the original required proofs. Create a raw-only fork for further live work rather than repairing or extending a historical ingestion.

If ingestion is pending, the command returns `incomplete` and exit code 3. Repeat it after the jobs finish. Authentication, configuration, embedding errors, unattempted sources and invalid vectors block comparison.

Polling a pending indexer is different from restarting a failed job. The CLI does not reset or rerun terminal failures. Correct Azure readiness before starting; a failed initial job needs a deliberate full reset/run of its owned indexer outside this CLI, before any snapshot/audit is frozen, or a new experiment. Never reset an indexer after its snapshot is frozen.

For terminal source loss or indexer diagnostics, snapshotting exports the execution and an editable ingestion-audit draft. A human must certify that these are source/extraction losses rather than operational failures and account for every absent source. Pass the completed typed audit with `snapshot --audit <path>`. Ambiguous or unreviewed loss is never silently scored as zero.

## Collect, resume and score

### Correcting an unpublished source run

The Python API `docgen.evaluation.revisions.create_source_revision(source, output, rejected=...)` creates a separate corrective workspace from a failed, unpublished source run. `source` is its locked `Workspace`; `rejected` maps planned document IDs to tuples of rejection reasons. The original must have complete canonical content and a frozen native allocation, and every retained document must already have a verified artifact. The operation refuses published corpora, released references, inherited treatment forks and any remote evaluation attempt.

Continue the returned workspace through `docgen.evaluation.corpus.generate_sources` or `experiment generate`. Generic run resume refuses pending corrective authoring without the experiment's native acceptance gate. The experiment path preserves retained bytes, includes all inherited model usage and candidate counts, validates each replacement in its original native assignment before acceptance, and publishes only a complete verified corpus. The checksummed `authoring-source-revision.json` records original file hashes, rejections, retained hashes, inherited attempts and the frozen allocation. A correction does not create an independent replication or confer human reference approval.

For an already published automatically assured corpus, use the separate `create_quality_revision` API only with explicit source-quality rejection reasons. It preserves the complete measured origin, imports authoring usage and retained source bytes, and inherits zero evaluation requests, reference labels, query vectors or rankings. Build a new reference and repeat all indexing and query collection. Preserve earlier results and disclose the correction timing and combined paid usage; never pair old rankings with corrected source hashes.

### Collecting released sources

```powershell
& $docgen experiment collect --experiment $experiment --split test --live --json
& $docgen experiment score --experiment $experiment --split test --json
& $docgen experiment status --experiment $experiment --json
```

Collection interleaves the two arms in a seeded, balanced order. Each exact NFC-normalized query has one cached embedding shared across both arms. Overlong queries fail without truncation. Index/source inventories and resource, text and vector hashes are checked before and after collection. Detected drift invalidates reuse of the experiment.

Invalid stored vectors and foreign query hits also quarantine collection. Restoring the previous index contents does not clear an observed drift event or make its previously cached rankings reusable. Embedding model checks run before a response enters the successful shared-vector cache.

Repeat the same command after interruption or a recoverable failure. Confirmed responses are reused; unknown outcomes and all attempts remain counted. Per-invocation retries share persistent protocol-wide request/token ceilings. Snapshot enumeration also consumes these ceilings. Exhausted limits are not automatically increased.

Scoring is offline and requires every arm/query response and the post-collection seal. A successful empty answerable ranking scores zero. Unanswerable rankings have N/A metrics, not invented abstention scores. Parent deduplication happens before each cutoff; Precision divides by K, and binary relevance starts at grade 2.

## Outputs and interpretation

The experiment directory contains the fresh source run, checksummed protocol/SQLite state, editable draft, reviewed reference/qrels, both arm snapshots, saved rankings, TREC runs and `report-test.json`. Index only the source run's published corpus; the uploader never includes labels or reports.

The report includes paired family-level estimates and 95% bootstrap intervals, per-query scores, overlapping descriptive source slices, ingestion coverage, successful-attempt latency and known/unknown usage. Fewer than two answerable families yields no confidence interval. Azure indexing charges are not reported by the Search API.

Chunk entailment/support metrics are `not_evaluated`. Parent hits alone do not prove answer preservation in the returned chunks. Reviewed chunk support, token-budget evidence scoring and matched-format exports remain unimplemented. Synthetic-bank findings do not establish retrieval quality on organizational documents.

For the larger design, set sixty families, `generation.count: 360`, split weights 20/20/60 and explicitly calibrated budgets before initialization. This produces 432 test utterances and 864 paired primary Search outcomes. Keep enough request capacity for snapshots, retries and resumptions; the smoke example's limits are not a larger-run budget.

## Optional source cleanup

After measurement is finished, `docgen clear` can delete the protocol's Blob folder while preserving the container/account. Use the `source_prefix` returned by `experiment init`; preview the exact account, container and folder before adding `--yes`. See [clear behavior and retention limits](../../README.md#clear-blob-storage).

Do not clear sources while collecting or intending to resume live queries: source inventory drift invalidates collection. Cleanup does not delete Search indexes or local experiment records, and Azure versioning/soft-delete retention can retain data and charges.
