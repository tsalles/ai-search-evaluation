# Sources and Verified Context

Official guidance checked: 2026-10-22  
Implementation evidence updated: 2026-10-24

## Official guidance

| Source | Design consequence |
|--------|--------------------|
| [Azure OpenAI v1 endpoint and Entra authentication](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/switching-endpoints) | Use the OpenAI client, deployment name, renewable bearer-token provider, and the documented v1 audience. |
| [Azure structured outputs](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/structured-outputs) | Both Responses and Chat Completions support the feature in documented configurations; the selected model still needs a live compatibility check. |
| [Azure Identity credential chains](https://learn.microsoft.com/azure/developer/python/sdk/authentication/credential-chains) | Azure CLI can supply `DefaultAzureCredential`; a specific credential name via `AZURE_TOKEN_CREDENTIALS` requires version 1.24.0 or later. |
| [Azure AI Search blob document formats](https://learn.microsoft.com/azure/search/search-howto-indexing-azure-blob-storage) | The requested six formats are supported source formats, but parsing/indexing strategy and extraction limits remain external evaluation concerns. |

The checked structured-output guidance requires all wire fields to be required, nullable unions for optional values, and `additionalProperties: false`. It documents a restricted JSON Schema subset, up to five nesting levels and 100 object properties. Local validation must enforce constraints absent from that subset. Recheck limits during T06; do not assume schema support solely from a deployed model name.

No currency pricing was verified and no monetary cost estimate is asserted. No model capability not exercised by a data-plane test is described as verified.

## Azure discovery evidence

Read-only CLI calls in the original private workspace found two existing Foundry accounts, each with a succeeded `gpt-6-luna` deployment. Account and resource-group identifiers are omitted from this public snapshot.

The example endpoint `https://example.openai.azure.com/` is a placeholder. The privately discovered model version was `2026-09-22`. Management-plane network metadata does not establish client reachability, data-plane RBAC, or model API compatibility.

The Azure MCP credential chain did not authenticate during discovery. CLI management-plane discovery succeeded instead. Subsequent explicitly enabled SDK tests used renewable Entra bearer tokens for bounded capability and authoring requests. No API keys were requested or saved, and no Azure resources or role assignments were changed.

## Evidence boundaries

- Actual L06, L25, native Office/PDF/HTML/Markdown QA, and scale evidence are distinguished in [implementation progress](implementation-progress.md).
- The API reports the deployment name but no explicit model-version header. The management-plane version is not substituted for an unknown runtime version.
- Native readback and model-based visual review are separate from human content approval.
- This plan does not claim that local file readback predicts either retrieval engine's extraction quality.
