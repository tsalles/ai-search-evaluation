import re
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

import yaml
from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from docgen.config import GenerationConfig, ProviderConfig, RenderConfig, Share, UniqueSafeLoader
from docgen.errors import InputError
from docgen.models import Fact, Identifier, Record, Text

Arm = Literal["de_split", "content_understanding"]
ARMS: tuple[Arm, ...] = ("de_split", "content_understanding")
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
EntityName = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
Split = Literal["calibration", "development", "test"]


def default_splits() -> dict[Split, Decimal]:
    return {
        "calibration": Decimal("0.2"),
        "development": Decimal("0.2"),
        "test": Decimal("0.6"),
    }


class ExperimentLimits(Record):
    legacy_optional_fields = ("max_semantic_attempts",)
    max_search_attempts: Annotated[StrictInt, Field(ge=1)] = 2592
    max_semantic_attempts: Annotated[StrictInt, Field(ge=0)] | None = None
    max_embedding_attempts: Annotated[StrictInt, Field(ge=1)] = 1296
    max_admin_attempts: Annotated[StrictInt, Field(ge=1)] = 2000
    max_blob_attempts: Annotated[StrictInt, Field(ge=1)] = 5000
    max_observed_embedding_tokens: Annotated[StrictInt, Field(ge=1)] = 100000
    max_query_tokens: Annotated[StrictInt, Field(ge=1, le=8191)] = 256
    max_chunks: Annotated[StrictInt, Field(ge=1, le=100000)] = 20000
    request_timeout_seconds: Annotated[StrictInt, Field(ge=1, le=600)] = 60
    transport_attempts: Annotated[StrictInt, Field(ge=1, le=5)] = 3


class EmbeddingSettings(Record):
    base_url: Text
    deployment: Text
    api: Literal["embeddings"] = "embeddings"

    @field_validator("base_url")
    @classmethod
    def safe_endpoint(cls, value: str) -> str:
        return ProviderConfig.azure_https_only(value)


class EntityExtractionSettings(Record):
    legacy_optional_fields = ("base_url", "method", "deployment")
    version: Literal["1", "2", "3"] = "2"
    method: Literal["ner"] | None = None
    deployment: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")] | None = None
    base_url: Text | None = None

    @field_validator("base_url")
    @classmethod
    def safe_endpoint(cls, value: str | None) -> str | None:
        return ProviderConfig.azure_https_only(value) if value is not None else None

    @model_validator(mode="after")
    def valid_method(self) -> Self:
        if self.method == "ner":
            if self.version != "3" or self.deployment is not None or self.base_url is not None:
                raise ValueError("Native NER requires version 3 and no chat deployment settings.")
        elif self.version == "3" or self.deployment is None:
            raise ValueError("GenAI entity extraction requires its chat deployment settings.")
        return self


class IndexTuning(Record):
    legacy_optional_fields = ("analyzer_comparison_fields",)
    analyzer: Literal["microsoft", "lucene", "standard"] = "microsoft"
    bm25_k1: Annotated[float, Field(strict=True, ge=0, le=3)] = 1.2
    bm25_b: Annotated[float, Field(strict=True, ge=0, le=1)] = 0.75
    hnsw_m: Annotated[StrictInt, Field(ge=4, le=10)] = 4
    hnsw_ef_construction: Annotated[StrictInt, Field(ge=100, le=1000)] = 400
    hnsw_ef_search: Annotated[StrictInt, Field(ge=100, le=1000)] = 500
    analyzer_comparison_fields: StrictBool | None = None


class QueryTuning(Record):
    legacy_optional_fields = ("analyzer",)
    vector_k: Annotated[StrictInt, Field(ge=50, le=1000)] | None = None
    vector_weight: Annotated[float, Field(strict=True, gt=0, le=10)] | None = None
    vector_exhaustive: StrictBool = False
    search_mode: Literal["any", "all"] = "any"
    analyzer: Literal["default", "lucene", "standard"] | None = None


class SectionEnrichmentSettings(Record):
    uri: Text
    auth_resource_id: Annotated[str, Field(
        pattern=r"^api://[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
    )]

    @field_validator("uri")
    @classmethod
    def safe_uri(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https" or not parsed.hostname
            or not parsed.hostname.endswith(".azurewebsites.net")
            or parsed.path != "/api/sections" or parsed.query or parsed.fragment
            or parsed.username or parsed.password or parsed.port not in {None, 443}
        ):
            raise ValueError("Use the authenticated Function HTTPS sections endpoint.")
        return value


class SearchVariant(Record):
    legacy_optional_fields = (
        "entity_extraction", "index_tuning", "query_tuning", "section_enrichment",
    )
    embedding_context: StrictBool = False
    de_tokens: Annotated[StrictInt, Field(ge=128, le=2048)] | None = None
    de_overlap_tokens: Annotated[StrictInt, Field(ge=0, le=512)] = 64
    cu_tokens: Annotated[StrictInt, Field(ge=100, le=8000)] = 2000
    entity_extraction: EntityExtractionSettings | None = None
    index_tuning: IndexTuning | None = None
    query_tuning: QueryTuning | None = None
    section_enrichment: SectionEnrichmentSettings | None = None

    @model_validator(mode="after")
    def valid_overlap(self) -> Self:
        if self.de_tokens is not None and self.de_overlap_tokens >= self.de_tokens:
            raise ValueError("Text Split overlap must be shorter than its token window.")
        if (
            self.query_tuning is not None
            and self.query_tuning.analyzer not in {None, "default"}
            and (self.index_tuning is None or not self.index_tuning.analyzer_comparison_fields)
        ):
            raise ValueError("Analyzer queries require native-text analyzer comparison fields.")
        return self


class SearchSettings(Record):
    legacy_optional_fields = ("variant",)
    endpoint: Text
    ai_services_endpoint: Text
    name_prefix: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")] = "docgen-eval"
    query_api_version: Literal["2026-04-01"] = "2026-04-01"
    cu_api_version: Literal["2026-05-01-preview"] = "2026-05-01-preview"
    embedding: EmbeddingSettings
    dimensions: Annotated[StrictInt, Field(ge=1, le=3072)] = 3072
    model_name: Literal["text-embedding-3-large", "text-embedding-3-small"] = (
        "text-embedding-3-large"
    )
    raw_top: Literal[50] = 50
    vector_k: Literal[50] = 50
    variant: SearchVariant | None = None

    @field_validator("endpoint")
    @classmethod
    def safe_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or re.fullmatch(r"[a-z0-9-]+\.search\.windows\.net", parsed.hostname) is None
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.port not in {None, 443}
        ):
            raise ValueError("Use a canonical HTTPS Azure AI Search endpoint without secrets.")
        return value.rstrip("/")

    @field_validator("ai_services_endpoint")
    @classmethod
    def safe_ai_services(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or re.fullmatch(
                r"[a-z0-9-]+\.(?:cognitiveservices|services\.ai)\.azure\.com",
                parsed.hostname,
            )
            is None
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.port not in {None, 443}
        ):
            raise ValueError("Use a canonical HTTPS Foundry resource endpoint without secrets.")
        return value.rstrip("/")

    @model_validator(mode="after")
    def embedding_space(self) -> Self:
        if self.model_name == "text-embedding-3-small" and self.dimensions > 1536:
            raise ValueError("text-embedding-3-small supports at most 1536 dimensions.")
        return self


class StorageSettings(Record):
    resource_id: Text
    container: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")]
    prefix_root: Identifier = "retrieval-experiments"

    @model_validator(mode="after")
    def resource(self) -> Self:
        if (
            re.fullmatch(
                r"/subscriptions/[a-fA-F0-9-]{36}/resourceGroups/[^/;?#\\\s]+/providers/"
                r"Microsoft\.Storage/storageAccounts/[a-z0-9]{3,24}",
                self.resource_id,
            )
            is None
            or "--" in self.container
        ):
            raise ValueError("Use a Storage account resource ID and a valid private container.")
        return self

    @property
    def account_url(self) -> str:
        return f"https://{self.resource_id.rsplit('/', 1)[1]}.blob.core.windows.net"


class ExperimentConfig(Record):
    legacy_optional_fields = ("family_domain",)
    schema_version: Literal["1"] = "1"
    family_domain: Literal["saas"] | None = None
    seed: Annotated[StrictInt, Field(ge=0, le=2**63 - 1)] = 1729
    family_count: Annotated[StrictInt, Field(ge=1, le=166)] = 2
    generation: GenerationConfig
    rendering: RenderConfig
    search: SearchSettings
    storage: StorageSettings
    limits: ExperimentLimits = Field(default_factory=ExperimentLimits)
    split_weights: dict[Split, Share] = Field(default_factory=default_splits)
    bootstrap_resamples: Annotated[StrictInt, Field(ge=100, le=100000)] = 10000

    @model_validator(mode="after")
    def coherent(self) -> Self:
        from docgen.config import check_mix

        if self.generation.count != self.family_count * 6:
            raise ValueError("Fresh experiments require exactly six documents per family.")
        if self.generation.families is not None or self.generation.shared_facts:
            raise ValueError("Experiment families/facts are created by the fresh protocol planner.")
        check_mix(self.split_weights)
        return self


def load_experiment_config(path: Path) -> ExperimentConfig:
    try:
        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            import json

            from docgen.providers.azure import reject_constant, unique_pairs

            json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
            return ExperimentConfig.model_validate_json(raw)
        return ExperimentConfig.model_validate(
            yaml.load(raw, Loader=UniqueSafeLoader)
        )
    except (OSError, UnicodeError, yaml.YAMLError, ValueError):
        raise InputError(
            "Invalid experiment configuration; check its fields, paths and budgets."
        ) from None


class Document(Record):
    id: Identifier
    family_id: Identifier
    canonical_hash: Digest
    filename: Text
    artifact_hash: Digest
    byte_count: Annotated[StrictInt, Field(ge=1)]
    format: Text
    genre: Text
    length_band: Text
    complexity: Text
    entities: tuple[Text, ...]


class Evidence(Record):
    id: Identifier
    claim_id: Identifier
    doc_id: Identifier
    block_id: Identifier
    quote: Text
    item_index: Annotated[StrictInt, Field(ge=0)] | None = None
    table_row: Annotated[StrictInt, Field(ge=0)] | None = None
    column_id: Identifier | None = None


class Claim(Record):
    id: Identifier
    family_id: Identifier
    fact: Fact


class Query(Record):
    id: Identifier
    text: Text
    authorship: Literal["template", "human"] = "template"


class QueryCohort(Record):
    name: Identifier
    split: Split
    intent_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=10000)]

    @field_validator("intent_ids")
    @classmethod
    def unique_intents(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("A query cohort cannot repeat an intent.")
        return value


class Judgment(Record):
    doc_id: Identifier
    grade: Annotated[StrictInt, Field(ge=0, le=3)]
    evidence_ids: tuple[Identifier, ...] = ()
    rationale: Text


class Review(Record):
    reviewer: Text
    payload_hash: Digest
    scope_certified: StrictBool


class Intent(Record):
    id: Identifier
    family_id: Identifier
    split: Literal["calibration", "development", "test"]
    task_type: Text
    answerable: StrictBool
    required_claims: tuple[Identifier, ...]
    reference_answer: Text | None
    entities: tuple[Text, ...]
    queries: Annotated[tuple[Query, ...], Field(min_length=2)]
    judgments: tuple[Judgment, ...]
    reviews: tuple[Review, ...] = ()


class Reference(Record):
    schema_version: Literal["1"] = "1"
    protocol_id: Identifier
    source_hash: Digest
    status: Literal["draft", "released", "provisional"] = "draft"
    documents: tuple[Document, ...]
    claims: tuple[Claim, ...]
    evidence: tuple[Evidence, ...]
    intents: tuple[Intent, ...]


class SourceContext(Record):
    title: Text
    account_names: tuple[Text, ...]


class SectionMetadata(Record):
    title: Annotated[str, Field(strict=True, min_length=1, max_length=256)] | None
    heading: Annotated[str, Field(strict=True, min_length=1, max_length=256)] | None
    ordinal: Annotated[StrictInt, Field(ge=0, le=31)]
    section_count: Annotated[StrictInt, Field(ge=1, le=32)]
    source_start: Annotated[StrictInt, Field(ge=0)]
    source_end: Annotated[StrictInt, Field(ge=1)]
    source_sha256: Digest
    request_key: Digest
    model: Text


class Chunk(Record):
    legacy_optional_fields = ("source_context", "entities", "section_metadata")
    id: Text
    parent_id: Text
    doc_id: Identifier
    content: Annotated[str, Field(min_length=1, max_length=500000)]
    text_hash: Digest
    vector_hash: Digest
    source_context: SourceContext | None = None
    entities: tuple[EntityName, ...] | None = None
    section_metadata: SectionMetadata | None = None


class MissingSource(Record):
    doc_id: Identifier
    reviewer: Text
    reason: Text


class IngestionAudit(Record):
    arm: Arm
    execution_hash: Digest
    reviewer: Text
    source_failures_only: Literal[True]
    missing: tuple[MissingSource, ...] = ()


class Snapshot(Record):
    schema_version: Literal["1"] = "1"
    protocol_id: Identifier
    arm: Arm
    source_hash: Digest
    resource_hash: Digest
    reference_hash: Digest
    execution_hash: Digest
    blob_hash: Digest
    chunks: tuple[Chunk, ...]
    missing: tuple[MissingSource, ...] = ()
    indexer_errors: Annotated[StrictInt, Field(ge=0)] = 0
    indexer_warnings: Annotated[StrictInt, Field(ge=0)] = 0


class Ranking(Record):
    legacy_optional_fields = ("reranker_scores",)
    arm: Arm
    query_id: Identifier
    status: Literal["succeeded", "failed"]
    chunk_ids: tuple[Text, ...] = ()
    scores: tuple[float, ...] = ()
    elapsed_ms: float = Field(ge=0)
    failure_code: Text | None = None
    reranker_scores: tuple[float, ...] | None = None
