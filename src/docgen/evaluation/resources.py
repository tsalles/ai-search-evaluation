from urllib.parse import urlsplit

from pydantic import JsonValue

from docgen.evaluation.entities import entity_skills
from docgen.evaluation.models import Arm
from docgen.evaluation.state import Protocol

ResourceDefinitions = dict[str, dict[str, JsonValue]]


def definitions(protocol: Protocol, arm: Arm) -> ResourceDefinitions:
    settings = protocol.config.search
    variant = settings.variant
    tuning = variant.index_tuning if variant else None
    language = protocol.config.generation.language
    lucene_analyzer = "pt-Br.lucene" if language == "pt" else "en.lucene"
    analyzer = (
        "standard.lucene" if tuning and tuning.analyzer == "standard"
        else lucene_analyzer if tuning and tuning.analyzer == "lucene"
        else "pt-Br.microsoft" if language == "pt" else "en.microsoft"
    )
    index_name = protocol.resource_name(arm, "index")
    skillset_name = protocol.resource_name(arm, "skills")
    source_name = protocol.resource_name(arm, "source")
    sectioning = variant.section_enrichment if variant and arm == "de_split" else None
    context = "/document/pages/*" if arm == "de_split" else "/document/text_sections/*"
    section_context = "/document/section_enrichment/sections/*"
    if sectioning is not None:
        context = section_context + "/pages/*"
    text = context if arm == "de_split" else context + "/content"
    skills: list[JsonValue] = []
    section_skills: list[JsonValue] = []
    if sectioning is not None:
        section_skills.append({
            "@odata.type": "#Microsoft.Skills.Custom.WebApiSkill",
            "name": "grounded-section-planning",
            "context": "/document",
            "uri": sectioning.uri,
            "authResourceId": sectioning.auth_resource_id,
            "httpMethod": "POST",
            "timeout": "PT3M50S",
            "batchSize": 1,
            "degreeOfParallelism": 1,
            "inputs": [
                {"name": "text", "source": "/document/extracted_content"},
                {"name": "source_path", "source": "/document/metadata_storage_path"},
            ],
            "outputs": [{"name": "enrichment", "targetName": "section_enrichment"}],
        })
    if arm == "de_split":
        skills.extend(
            [
                {
                    "@odata.type": "#Microsoft.Skills.Util.DocumentExtractionSkill",
                    "name": "document-extraction",
                    "context": "/document",
                    "parsingMode": "default",
                    "dataToExtract": "contentAndMetadata",
                    "configuration": {"imageAction": "none"},
                    "inputs": [{"name": "file_data", "source": "/document/file_data"}],
                    "outputs": [{"name": "content", "targetName": "extracted_content"}],
                },
                *section_skills,
                {
                    "@odata.type": "#Microsoft.Skills.Text.SplitSkill",
                    "name": "text-split",
                    "context": section_context if sectioning is not None else "/document",
                    "defaultLanguageCode": (
                        protocol.config.generation.locale if variant
                        else protocol.config.generation.language
                    ),
                    "textSplitMode": "pages",
                    "maximumPageLength": (
                        variant.de_tokens if variant and variant.de_tokens is not None else 2000
                    ),
                    "pageOverlapLength": (
                        variant.de_overlap_tokens
                        if variant and variant.de_tokens is not None else 200
                    ),
                    "maximumPagesToTake": 0,
                    "unit": (
                        "azureOpenAITokens"
                        if variant and variant.de_tokens is not None else "characters"
                    ),
                    "inputs": [{
                        "name": "text",
                        "source": (
                            section_context + "/text"
                            if sectioning is not None else "/document/extracted_content"
                        ),
                    }],
                    "outputs": [{"name": "textItems", "targetName": "pages"}],
                },
            ]
        )
    else:
        skills.append(
            {
                "@odata.type": "#Microsoft.Skills.Util.ContentUnderstandingSkill",
                "name": "content-understanding",
                "context": "/document",
                "extractionOptions": [],
                "chunkingProperties": {
                    "method": "semantic",
                    "unit": "tokens",
                    "maximumLength": variant.cu_tokens if variant else 2000,
                    "overlapLength": 0,
                },
                "inputs": [{"name": "file_data", "source": "/document/file_data"}],
                "outputs": [{"name": "text_sections", "targetName": "text_sections"}],
            }
        )
    if protocol.entity_extraction is not None:
        skills.extend(entity_skills(
            protocol.entity_extraction, context, text, protocol.config.generation.language,
        ))
    embedding_endpoint = urlsplit(settings.embedding.base_url)
    skills.append(
        {
            "@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill",
            "name": "embeddings",
            "context": context,
            "resourceUri": f"https://{embedding_endpoint.hostname}",
            "deploymentId": settings.embedding.deployment,
            "dimensions": settings.dimensions,
            "modelName": settings.model_name,
            "inputs": [{"name": "text", "source": text}],
            "outputs": [{"name": "embedding", "targetName": "embedding"}],
        }
    )
    result: ResourceDefinitions = {
        "datasources": {
            "name": source_name,
            "type": "azureblob",
            "credentials": {
                "connectionString": f"ResourceId={protocol.config.storage.resource_id};"
            },
            "container": {
                "name": protocol.config.storage.container,
                "query": protocol.source_prefix + "/",
            },
        },
        "indexes": {
            "name": index_name,
            "fields": [
                {
                    "name": "id",
                    "type": "Edm.String",
                    "key": True,
                    "filterable": True,
                    "sortable": True,
                    "searchable": True,
                    "analyzer": "keyword",
                },
                {
                    "name": "parent_id",
                    "type": "Edm.String",
                    "filterable": True,
                    "searchable": False,
                },
                {
                    "name": "content",
                    "type": "Edm.String",
                    "searchable": True,
                    "analyzer": analyzer,
                },
                {"name": "content_path", "type": "Edm.String", "searchable": False},
                {
                    "name": "embedding",
                    "type": "Collection(Edm.Single)",
                    "searchable": True,
                    "retrievable": True,
                    "stored": True,
                    "dimensions": settings.dimensions,
                    "vectorSearchProfile": "shared-hnsw",
                },
            ],
            "vectorSearch": {
                "algorithms": [
                    {
                        "name": "shared-hnsw",
                        "kind": "hnsw",
                        "hnswParameters": {
                            "metric": "cosine",
                            "m": tuning.hnsw_m if tuning else 4,
                            "efConstruction": tuning.hnsw_ef_construction if tuning else 400,
                            "efSearch": tuning.hnsw_ef_search if tuning else 500,
                        },
                    }
                ],
                "profiles": [{"name": "shared-hnsw", "algorithm": "shared-hnsw"}],
            },
        },
        "skillsets": {
            "name": skillset_name,
            "skills": skills,
            "cognitiveServices": {
                "@odata.type": "#Microsoft.Azure.Search.AIServicesByIdentity",
                "subdomainUrl": settings.ai_services_endpoint,
                "identity": None,
            },
            "indexProjections": {
                "selectors": [
                    {
                        "targetIndexName": index_name,
                        "parentKeyFieldName": "parent_id",
                        "sourceContext": context,
                        "mappings": [
                            {"name": "content", "source": text},
                            {"name": "embedding", "source": context + "/embedding"},
                            {"name": "content_path", "source": "/document/metadata_storage_path"},
                        ],
                    }
                ],
                "parameters": {"projectionMode": "skipIndexingParentDocuments"},
            },
        },
        "indexers": {
            "name": protocol.resource_name(arm, "indexer"),
            "dataSourceName": source_name,
            "targetIndexName": index_name,
            "skillsetName": skillset_name,
            "parameters": {
                "maxFailedItems": -1,
                "maxFailedItemsPerBatch": -1,
                "configuration": {
                    "dataToExtract": "storageMetadata",
                    "allowSkillsetToReadFileData": True,
                    "failOnUnsupportedContentType": True,
                    "failOnUnprocessableDocument": True,
                },
            },
        },
    }
    if tuning is not None:
        result["indexes"]["similarity"] = {
            "@odata.type": "#Microsoft.Azure.Search.BM25Similarity",
            "k1": tuning.bm25_k1,
            "b": tuning.bm25_b,
        }
    if tuning is not None and tuning.analyzer_comparison_fields:
        fields = result["indexes"]["fields"]
        projections = result["skillsets"]["indexProjections"]
        if not isinstance(fields, list) or not isinstance(projections, dict):
            raise TypeError("Analyzer comparison requires structured index fields/projections.")
        selectors = projections["selectors"]
        if not isinstance(selectors, list) or not isinstance(selectors[0], dict):
            raise TypeError("Analyzer comparison requires a structured projection selector.")
        mappings = selectors[0]["mappings"]
        if not isinstance(mappings, list):
            raise TypeError("Analyzer comparison requires a projection mapping list.")
        for suffix, analysis in (
            ("lucene", lucene_analyzer), ("standard", "standard.lucene"),
        ):
            name = "content_" + suffix
            fields.append({
                "name": name, "type": "Edm.String", "searchable": True, "analyzer": analysis,
            })
            mappings.append({"name": name, "source": text})
    if protocol.pipeline_only or variant is not None:
        configurations: list[JsonValue] = [{
            "name": "content-only",
            "prioritizedFields": {
                "prioritizedContentFields": [{"fieldName": "content"}],
            },
        }]
        result["indexes"]["semantic"] = {"configurations": configurations}
    if protocol.source_context_enabled:
        fields = result["indexes"]["fields"]
        if not isinstance(fields, list):
            raise TypeError("Controlled index fields must be a list.")
        fields.extend([
            {
                "name": "title", "type": "Edm.String", "searchable": True,
                "analyzer": analyzer,
            },
            {
                "name": "account_names", "type": "Collection(Edm.String)",
                "searchable": True, "analyzer": "keyword",
            },
            {"name": "source_context_hash", "type": "Edm.String", "searchable": False},
        ])
        result["indexes"]["scoringProfiles"] = [{
            "name": "source-context",
            "text": {"weights": {"title": 2.0, "account_names": 4.0, "content": 1.0}},
        }]
        configurations.append({
            "name": "source-context",
            "prioritizedFields": {
                "titleField": {"fieldName": "title"},
                "prioritizedKeywordsFields": [{"fieldName": "account_names"}],
                "prioritizedContentFields": [{"fieldName": "content"}],
            },
        })
    if protocol.entity_extraction is not None:
        fields = result["indexes"]["fields"]
        if not isinstance(fields, list):
            raise TypeError("Controlled index fields must be a list.")
        fields.append({
            "name": "entity_data", "type": "Edm.ComplexType",
            "fields": [{
                "name": "entities", "type": "Collection(Edm.String)", "searchable": True,
                "analyzer": analyzer,
            }],
        })
        selectors = result["skillsets"]["indexProjections"]
        if not isinstance(selectors, dict):
            raise TypeError("Controlled index projections must be an object.")
        entries = selectors["selectors"]
        if not isinstance(entries, list) or not isinstance(entries[0], dict):
            raise TypeError("Controlled projection selectors must be objects.")
        mappings = entries[0]["mappings"]
        if not isinstance(mappings, list):
            raise TypeError("Controlled projection mappings must be a list.")
        mappings.append({
            "name": "entity_data", "source": context + "/entity_extraction",
        })
        result["indexes"]["scoringProfiles"] = [{
            "name": "pipeline-entities",
            "text": {"weights": {"content": 1.0, "entity_data/entities": 2.0}},
        }]
        if protocol.entity_extraction.version in {"2", "3"}:
            parameters = result["indexers"]["parameters"]
            if not isinstance(parameters, dict):
                raise TypeError("Controlled indexer parameters must be an object.")
            parameters["batchSize"] = 1
    if sectioning is not None:
        fields = result["indexes"]["fields"]
        projections = result["skillsets"]["indexProjections"]
        parameters = result["indexers"]["parameters"]
        if not isinstance(fields, list) or not isinstance(projections, dict) or not isinstance(
            parameters, dict,
        ):
            raise TypeError("Section enrichment requires structured fields and projections.")
        entries = projections["selectors"]
        if not isinstance(entries, list) or not isinstance(entries[0], dict):
            raise TypeError("Section enrichment requires a projection selector.")
        mappings = entries[0]["mappings"]
        if not isinstance(mappings, list):
            raise TypeError("Section enrichment requires projection mappings.")
        metadata_fields: list[JsonValue] = [
            {"name": "title", "type": "Edm.String", "searchable": True, "analyzer": analyzer},
            {"name": "heading", "type": "Edm.String", "searchable": True, "analyzer": analyzer},
        ]
        for name in ("ordinal", "section_count", "source_start", "source_end"):
            metadata_fields.append({"name": name, "type": "Edm.Int32", "searchable": False})
        for name in ("source_sha256", "request_key", "model"):
            metadata_fields.append({"name": name, "type": "Edm.String", "searchable": False})
        fields.extend([
            {
                "name": "source_text", "type": "Edm.String", "searchable": False,
                "filterable": False, "sortable": False, "facetable": False,
            },
            {
                "name": "model_audit_payload", "type": "Edm.String", "searchable": False,
                "filterable": False, "sortable": False, "facetable": False,
            },
            {
                "name": "section_metadata", "type": "Edm.ComplexType",
                "fields": metadata_fields,
            },
        ])
        mappings.extend([
            {"name": "source_text", "source": "/document/section_enrichment/source_text"},
            {"name": "model_audit_payload", "source": "/document/section_enrichment/model_audit"},
            {"name": "section_metadata", "source": section_context + "/metadata"},
        ])
        result["indexes"]["scoringProfiles"] = [{
            "name": name,
            "text": {"weights": {
                "content": 1.0, "section_metadata/title": title,
                "section_metadata/heading": heading,
            }},
        } for name, title, heading in (
            ("metadata-soft", 0.5, 0.5),
            ("metadata-balanced", 1.0, 1.0),
            ("metadata-title", 2.0, 1.0),
        )]
        configurations.append({
            "name": "section-metadata",
            "prioritizedFields": {
                "titleField": {"fieldName": "section_metadata/title"},
                "prioritizedKeywordsFields": [{"fieldName": "section_metadata/heading"}],
                "prioritizedContentFields": [{"fieldName": "content"}],
            },
        })
        parameters["batchSize"] = 1
    return result


def contains(actual: JsonValue, expected: JsonValue) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            contains(actual.get(key), value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(contains(left, right) for left, right in zip(actual, expected, strict=True))
        )
    if isinstance(expected, str) and expected.startswith("https://") and isinstance(actual, str):
        try:
            left, right = urlsplit(actual), urlsplit(expected)
            if left.path in {"", "/"} and right.path in {"", "/"}:
                return (
                    left.scheme == right.scheme == "https"
                    and left.hostname == right.hostname
                    and (left.port or 443) == (right.port or 443)
                    and not any(
                        (
                            left.username,
                            left.password,
                            left.query,
                            left.fragment,
                            right.username,
                            right.password,
                            right.query,
                            right.fragment,
                        )
                    )
                )
        except ValueError:
            return False
    return type(actual) is type(expected) and actual == expected
