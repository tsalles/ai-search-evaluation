import hashlib
import math
from pathlib import Path
from types import TracebackType
from typing import Self
from urllib.parse import urlsplit

import httpx
from azure.core import MatchConditions
from azure.core.credentials import TokenCredential
from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.core.paging import PageIterator
from azure.core.pipeline.transport import HttpRequest, HttpResponse, HttpTransport
from azure.identity import AzureCliCredential, CredentialUnavailableError, get_bearer_token_provider
from azure.storage.blob import BlobServiceClient, ContentSettings
from pydantic import JsonValue, TypeAdapter, ValidationError

from docgen.blob_push import CONTENT_TYPES, file_signature
from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.models import Document
from docgen.evaluation.state import Protocol, RemoteValue
from docgen.models import Usage
from docgen.providers.azure import reject_constant, unique_pairs


def object_value(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ProviderError("invalid_response", "Azure returned a nonobject response.")
    return value


def vector_value(value: JsonValue, dimensions: int) -> list[float]:
    if (
        not isinstance(value, list)
        or len(value) != dimensions
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
    ):
        raise ProviderError(
            "invalid_vector", "Azure returned a missing or invalid embedding vector."
        )
    try:
        vector = [float(item) for item in value if isinstance(item, (int, float))]
    except OverflowError:
        raise ProviderError("invalid_vector", "Azure returned an out-of-range vector.") from None
    if not all(math.isfinite(item) for item in vector) or not any(vector):
        raise ProviderError("invalid_vector", "Azure returned a zero embedding vector.")
    return vector


class Azure:
    def __init__(
        self,
        protocol: Protocol,
        *,
        credential: TokenCredential | None = None,
        http_client: httpx.Client | None = None,
        blob_transport: HttpTransport[HttpRequest, HttpResponse] | None = None,
    ) -> None:
        if http_client is not None and http_client.follow_redirects:
            raise InputError("Azure experiment clients must not follow redirects.")
        self.protocol = protocol
        self.owned_credential = (
            AzureCliCredential(
                process_timeout=min(60, protocol.config.limits.request_timeout_seconds)
            )
            if credential is None
            else None
        )
        self.credential = credential if credential is not None else self.owned_credential
        if self.credential is None:
            raise InputError("An Entra token credential is required.")
        self._token_providers = {
            scope: get_bearer_token_provider(self.credential, scope)
            for scope in ("https://search.azure.com/.default", "https://ai.azure.com/.default")
        }
        self.client = http_client or httpx.Client(follow_redirects=False)
        self.owns_client = http_client is None
        self.blobs = BlobServiceClient(
            protocol.config.storage.account_url,
            credential=self.credential,
            transport=blob_transport,
            retry_total=0,
            connection_timeout=protocol.config.limits.request_timeout_seconds,
            read_timeout=protocol.config.limits.request_timeout_seconds,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self.blobs.close()
        if self.owns_client:
            self.client.close()
        if self.owned_credential is not None:
            self.owned_credential.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        scope: str,
        body: dict[str, JsonValue] | None = None,
        allow_missing: bool = False,
        create_only: bool = False,
        if_match: str | None = None,
        timeout_seconds: float | None = None,
    ) -> RemoteValue:
        import json

        search_root = self.protocol.config.search.endpoint + "/"
        embedding_url = self.protocol.config.search.embedding.base_url + "embeddings"
        if not (
            scope == "https://search.azure.com/.default"
            and url.startswith(search_root)
            or scope == "https://ai.azure.com/.default"
            and url == embedding_url
        ):
            raise InputError(
                "Refusing to send Azure credentials outside configured service endpoints."
            )
        if scope == "https://search.azure.com/.default":
            path = urlsplit(url).path
            verb = method.upper()
            query = verb == "POST" and path.endswith("/docs/search")
            if verb not in {"GET", "HEAD"} and not query:
                if "/docs/" in path:
                    raise InputError(
                        "Only the Azure AI Search indexing pipeline may write document fields "
                        "or document embeddings."
                    )
                self.protocol.require_pipeline_only()
        else:
            self.protocol.require_pipeline_only()
        if if_match is not None and (
            create_only or not isinstance(if_match, str) or len(if_match) < 2
            or not if_match.startswith('"') or not if_match.endswith('"')
            or any(ord(char) < 32 or ord(char) >= 127 for char in if_match)
        ):
            raise InputError("Conditional updates require a strong, non-wildcard resource ETag.")
        if timeout_seconds is not None and (
            isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= self.protocol.config.limits.request_timeout_seconds
        ):
            raise InputError("A transport timeout must be positive and within the frozen deadline.")
        try:
            headers = {"Authorization": "Bearer " + self._token_providers[scope]()}
            if create_only:
                headers["If-None-Match"] = "*"
            if if_match is not None:
                headers["If-Match"] = if_match
            response = self.client.request(
                method,
                url,
                json=body,
                headers=headers,
                timeout=(
                    timeout_seconds if timeout_seconds is not None
                    else self.protocol.config.limits.request_timeout_seconds
                ),
            )
        except (ClientAuthenticationError, CredentialUnavailableError):
            raise ProviderError(
                "authentication",
                "Azure CLI authentication failed; run az login for the intended tenant.",
            ) from None
        except (httpx.TimeoutException, httpx.TransportError):
            raise ProviderError(
                "transport",
                "Azure request did not complete; its remote outcome may be unknown.",
                retryable=True,
            ) from None
        if response.status_code == 404 and allow_missing:
            return RemoteValue(data=None)
        if not 200 <= response.status_code < 300:
            if (
                response.status_code == 402
                and scope == "https://search.azure.com/.default"
                and body is not None
                and ("semanticQuery" in body or body.get("queryType") == "semantic")
            ):
                raise ProviderError(
                    "semantic_quota",
                    "Azure AI Search rejected semantic reranking (HTTP 402): the semantic "
                    "quota or billing allowance is exhausted. Sequential requests do not "
                    "restore this allowance; renew quota or explicitly authorize paid usage.",
                )
            code = (
                "authorization"
                if response.status_code in {401, 403}
                else "resource_conflict"
                if response.status_code in {409, 412}
                else "azure_request"
            )
            retry_after = response.headers.get("retry-after")
            delay = float(retry_after) if retry_after and retry_after.isdecimal() else None
            raise ProviderError(
                code,
                f"Azure rejected the request (HTTP {response.status_code}); check roles, "
                "network access, resource readiness and the pinned API capabilities.",
                retryable=response.status_code in {408, 429, 500, 502, 503, 504},
                retry_after_seconds=delay,
            )
        if not response.content:
            return RemoteValue(data={})
        try:
            decoded = json.loads(
                response.content,
                object_pairs_hook=unique_pairs,
                parse_constant=reject_constant,
            )
            value = TypeAdapter(dict[str, JsonValue]).validate_python(decoded, strict=True)
        except (ValueError, UnicodeError, ValidationError):
            raise ProviderError("invalid_response", "Azure returned invalid JSON.") from None
        if response.headers.get("etag") and "@odata.etag" not in value:
            value["@odata.etag"] = response.headers["etag"]
        return RemoteValue(data=value)

    def search(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, JsonValue] | None = None,
        preview: bool = False,
        allow_missing: bool = False,
        create_only: bool = False,
    ) -> RemoteValue:
        settings = self.protocol.config.search
        version = settings.cu_api_version if preview else settings.query_api_version
        return self.request(
            method,
            settings.endpoint + "/" + path + "?api-version=" + version,
            scope="https://search.azure.com/.default",
            body=body,
            allow_missing=allow_missing,
            create_only=create_only,
        )

    def embed(self, text: str) -> RemoteValue:
        response = self.embed_many((text,))
        value = object_value(response.data)
        vectors = value.get("vectors")
        if not isinstance(vectors, list) or len(vectors) != 1:
            raise ProviderError("invalid_embedding", "Expected one checked embedding vector.")
        return RemoteValue(
            data={"vector": vectors[0], "reported_model": value["reported_model"]},
            tokens=response.tokens,
        )

    def embed_many(self, texts: tuple[str, ...]) -> RemoteValue:
        if not texts or len(texts) > 16 or any(not text.strip() for text in texts):
            raise InputError("Embedding batches require one to sixteen nonempty inputs.")
        settings = self.protocol.config.search
        response = self.request(
            "POST",
            settings.embedding.base_url + "embeddings",
            scope="https://ai.azure.com/.default",
            body={
                "model": settings.embedding.deployment,
                "input": [text for text in texts],
                "dimensions": settings.dimensions,
                "encoding_format": "float",
            },
        )
        value = object_value(response.data)
        data, usage = value.get("data"), value.get("usage")
        if not isinstance(data, list) or len(data) != len(texts) or not isinstance(usage, dict):
            raise ProviderError("invalid_embedding", "Embedding response or usage is missing.")
        tokens = usage.get("total_tokens")
        if (
            type(tokens) is not int
            or tokens < 0
            or usage.get("prompt_tokens") != tokens
        ):
            raise ProviderError("invalid_usage", "Embedding usage or ordering is invalid.")
        observed_usage = Usage(input_tokens=tokens, output_tokens=0, total_tokens=tokens)
        if value.get("model") != settings.model_name:
            raise ProviderError(
                "embedding_space",
                "Embedding model does not match the protocol.",
                usage=observed_usage,
            )
        try:
            vectors: list[JsonValue] = []
            for index, raw in enumerate(data):
                item = object_value(raw)
                if type(item.get("index")) is not int or item["index"] != index:
                    raise ProviderError("invalid_embedding", "Embedding batch ordering differs.")
                vector = vector_value(item.get("embedding"), settings.dimensions)
                if any(abs(number) > 3.4028234663852886e38 for number in vector):
                    raise ProviderError(
                        "invalid_vector", "Embedding exceeds Edm.Single storage precision."
                    )
                vectors.append([number for number in vector])
        except ProviderError as error:
            raise ProviderError(error.code, str(error), usage=observed_usage) from None
        return RemoteValue(
            data={"vectors": vectors, "reported_model": value.get("model")},
            tokens=tokens,
        )

    def blob_properties(self, name: str) -> RemoteValue:
        try:
            blob = self.blobs.get_blob_client(self.protocol.config.storage.container, name)
            properties = blob.get_blob_properties()
        except ResourceNotFoundError as error:
            if getattr(error, "error_code", None) == "BlobNotFound":
                return RemoteValue(data=None)
            raise self.storage_error(error) from None
        except AzureError as error:
            raise self.storage_error(error) from None
        return RemoteValue(
            data={
                "name": name,
                "size": properties.size,
                "metadata": dict(properties.metadata),
                "etag": properties.etag,
            }
        )

    def upload(self, document: Document, path: Path) -> RemoteValue:
        self.protocol.require_pipeline_only()
        blob = self.blobs.get_blob_client(
            self.protocol.config.storage.container,
            self.protocol.source_prefix + "/" + document.filename,
        )
        try:
            signature = file_signature(path.stat())
            with path.open("rb") as stream:
                sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
                if sha256 != document.artifact_hash or file_signature(path.stat()) != signature:
                    raise IntegrityError("Source bytes changed before upload.")
                stream.seek(0)
                blob.upload_blob(
                    stream,
                    overwrite=False,
                    length=document.byte_count,
                    max_concurrency=1,
                    validate_content=True,
                    metadata={},
                    content_settings=ContentSettings(content_type=CONTENT_TYPES[path.suffix]),
                )
            if file_signature(path.stat()) != signature:
                raise IntegrityError(
                    "Source changed during upload; a remote write may have occurred."
                )
        except AzureError as error:
            raise self.storage_error(error) from None
        return RemoteValue(data={"uploaded": True})

    def verify_blob(self, document: Document, etag: str) -> RemoteValue:
        blob = self.blobs.get_blob_client(
            self.protocol.config.storage.container,
            self.protocol.source_prefix + "/" + document.filename,
        )
        actual = hashlib.sha256()
        byte_count = 0
        try:
            download = blob.download_blob(
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
                validate_content=True,
                max_concurrency=1,
            )
            for chunk in download.chunks():
                byte_count += len(chunk)
                if byte_count > document.byte_count:
                    raise IntegrityError("Stored source bytes exceed their frozen size.")
                actual.update(chunk)
        except AzureError as error:
            raise self.storage_error(error) from None
        if byte_count != document.byte_count or actual.hexdigest() != document.artifact_hash:
            raise IntegrityError("Stored source bytes differ from their frozen SHA-256 checksum.")
        return RemoteValue(data={"sha256": actual.hexdigest(), "etag": etag})

    def list_blobs(self, marker: str | None = None) -> RemoteValue:
        try:
            pages = (
                self.blobs.get_container_client(
                    self.protocol.config.storage.container,
                )
                .list_blobs(
                    name_starts_with=self.protocol.source_prefix + "/",
                    results_per_page=1000,
                )
                .by_page(continuation_token=marker)
            )
            if not isinstance(pages, PageIterator):
                raise ProviderError("invalid_blob_pager", "Storage returned an invalid pager.")
            entries = next(pages)
            values: list[JsonValue] = [
                {"name": item.name, "size": item.size, "etag": item.etag} for item in entries
            ]
            return RemoteValue(data={"values": values, "next": pages.continuation_token})
        except StopIteration:
            return RemoteValue(data={"values": [], "next": None})
        except AzureError as error:
            raise self.storage_error(error) from None

    @staticmethod
    def storage_error(error: AzureError) -> ProviderError:
        status = error.status_code if isinstance(error, HttpResponseError) else None
        return ProviderError(
            "storage_authorization" if status in {401, 403} else "storage_request",
            "Blob operation failed; check the CLI user, container permissions and network access.",
            retryable=isinstance(error, (ServiceRequestError, ServiceResponseError))
            or status in {408, 429, 500, 502, 503, 504},
        )
