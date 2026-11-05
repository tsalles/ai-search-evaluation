# Azure AI Search resource definitions

## Deployment placeholders

These JSON files are sanitized templates. Replace the `example` account names and endpoints, the all-zero subscription identifier, and the example Blob prefix with your own values before applying them. The datasource uses a managed-identity resource reference, not a storage account key or SAS. Exported service ETags are omitted.

## Document Extraction skillset

[skillset_de.json](skillset_de.json) extracts document text, splits it into overlapping character-based chunks, and enriches each chunk with embeddings and keywords.

| Producer | Output in the enrichment tree | Consumers |
|----------|-------------------------------|-----------|
| Document Extraction `content`, renamed `extracted_content` | `/document/extracted_content` | Text Split |
| Text Split `textItems`, renamed `pages` | `/document/pages/*` | Embedding text, keyword text, projected content |
| Embedding skill | `/document/pages/*/embedding` | Projected embedding |
| Key phrase extraction | `/document/pages/*/keywords/*` | Projected keywords |

`textItems` is the Text Split output name, not a property inside each chunk. After renaming the output to `pages`, each item is the text itself. A source ending in `/pages/*/textItems` therefore references a nonexistent child.

[indexer.json](indexer.json) already enables `allowSkillsetToReadFileData`, which supplies Document Extraction's `/document/file_data` input. The existing Brazilian Portuguese language, 2,000-character chunks, 200-character overlap, and 3,072-dimensional embeddings are unchanged.

## Related index requirements

- The skillset targets `my-index` and projects a `keywords` collection. [index-kw.json](index-kw.json) includes that field; [index.json](index.json) is a baseline variant without it. Ensure the live index has the required `Collection(Edm.String)` field.
- The existing title projection references `/document/document_title`. This configuration does not produce that node. Populate it separately, or intentionally change the title source to an available Blob metadata field such as `/document/metadata_storage_name`. The text-path repair does not change title semantics.
- [skillset-cu.json](skillset-cu.json) uses Content Understanding's object-shaped `text_sections` output. Its `/content` child paths are a different contract and are unchanged.

## Apply and verify

Update the live skillset definition using the corrected JSON. Local edits alone do not update Azure resources. Run the existing indexer, resetting it first if previously processed documents must be re-enriched.

In an Azure AI Search debug session, verify that `/document/pages/0` contains chunk text and that its `embedding` and `keywords` annotations are populated. Confirm the target index contains projected chunk content and vectors.

Indexer execution can invoke billable embedding and language services. Offline contract tests validate the local wiring; they do not prove a live indexer run succeeded.

References: [Text Split skill](https://learn.microsoft.com/azure/search/cognitive-search-skill-textsplit), [Document Extraction](https://learn.microsoft.com/azure/search/cognitive-search-skill-document-extraction), and [index projections](https://learn.microsoft.com/azure/search/search-how-to-define-index-projections).
