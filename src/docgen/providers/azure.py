import json
import math
import threading
from types import TracebackType
from typing import Literal, Self

import httpx
from azure.core.credentials import TokenCredential
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from openai.types.responses import Response
from pydantic import (
    BaseModel,
    ConfigDict,
    JsonValue,
    StrictStr,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from docgen.config import Limits, ProviderConfig
from docgen.errors import InputError, ProviderError
from docgen.models import Record, Text, Usage
from docgen.wire import DRAFT_SCHEMA


def unique_pairs(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key.")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON constants are not allowed.")


class DraftResponse(Record):
    payload: dict[str, JsonValue]
    response_id: str
    request_id: str | None
    reported_model: str
    model_version: str | None
    usage: Usage | None


class ResponsePart(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["output_text", "refusal"]
    text: StrictStr | None = None

    @model_validator(mode="after")
    def text_required(self) -> Self:
        if self.type == "output_text" and self.text is None:
            raise ValueError("Output text part is missing its text.")
        return self


class ResponseItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["message", "reasoning"]
    content: tuple[ResponsePart, ...] | None = None

    @model_validator(mode="after")
    def message_content_required(self) -> Self:
        if self.type == "message" and self.content is None:
            raise ValueError("Output message is missing its content.")
        return self


class CoreResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Text
    model: Text
    status: Literal["completed", "failed", "incomplete", "cancelled", "queued", "in_progress"]
    output: tuple[ResponseItem, ...]


class AzureProvider:
    def __init__(
        self, config: ProviderConfig, *, limits: Limits | None = None,
        credential: TokenCredential | None = None, http_client: httpx.Client | None = None,
        expected_reported_model: str | None = None, expected_model_version: str | None = None,
    ) -> None:
        self.config = ProviderConfig.model_validate(config.model_dump())
        self.limits = limits or Limits()
        if http_client is not None and http_client.follow_redirects:
            raise InputError("Provider HTTP clients must not follow redirects.")
        self._owned_credential = (
            DefaultAzureCredential(
                exclude_interactive_browser_credential=True, exclude_broker_credential=True,
                process_timeout=min(60, self.limits.request_timeout_seconds),
            ) if credential is None else None
        )
        selected = credential if credential is not None else self._owned_credential
        if selected is None:
            raise InputError("A token credential is required.")
        self._client = OpenAI(
            base_url=self.config.base_url,
            api_key=get_bearer_token_provider(selected, "https://ai.azure.com/.default"),
            max_retries=0, timeout=self.limits.request_timeout_seconds,
            http_client=http_client or httpx.Client(follow_redirects=False),
        )
        self._reported_model = expected_reported_model
        self._model_version = expected_model_version
        self._model_lock = threading.Lock()
        self._closed = False

    def __enter__(self) -> Self:
        if self._closed:
            raise ProviderError("closed", "Provider is closed.")
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            try:
                self._client.close()
            finally:
                self._closed = True
                if self._owned_credential is not None:
                    self._owned_credential.close()

    @staticmethod
    def _usage(response: Response) -> Usage | None:
        if response.usage is None:
            return None
        try:
            raw = response.usage.model_dump()
            counters = {key: raw.get(key) for key in (
                "input_tokens", "output_tokens", "total_tokens"
            )}
            if any(type(value) is not int for value in counters.values()):
                raise ValueError("Missing or invalid reported counters.")
            details = raw.get("output_tokens_details")
            counters["reasoning_tokens"] = (
                details.get("reasoning_tokens") if isinstance(details, dict) else None
            )
            return Usage.model_validate(counters)
        except ValueError:
            raise ProviderError(
                "invalid_usage", "Provider returned invalid token accounting."
            ) from None

    def request(
        self, prompt: str, *, max_output_tokens: int | None = None,
        schema: dict[str, JsonValue] | None = None,
    ) -> DraftResponse:
        if self._closed:
            raise ProviderError("closed", "Provider is closed.")
        limit = self.limits.max_output_tokens_per_request if max_output_tokens is None else (
            max_output_tokens
        )
        if not isinstance(prompt, str) or not prompt.strip():
            raise InputError("A nonblank prompt is required.")
        if type(limit) is not int or not 1 <= limit <= self.limits.max_output_tokens_per_request:
            raise InputError("Request output limit must be positive and within configured limits.")
        selected_schema = DRAFT_SCHEMA if schema is None else schema
        try:
            Draft202012Validator.check_schema(selected_schema)
        except SchemaError:
            raise InputError("The requested authoring schema is invalid.") from None
        try:
            raw = self._client.responses.with_raw_response.create(
                model=self.config.deployment, input=prompt, store=False, max_output_tokens=limit,
                text={"format": {
                    "type": "json_schema", "name": "synthetic_content_v1", "strict": True,
                    "schema": {key: value for key, value in selected_schema.items()},
                }},
            )
            response = raw.parse()
        except json.JSONDecodeError:
            raise ProviderError(
                "invalid_response", "Provider returned an invalid HTTP JSON envelope."
            ) from None
        except APITimeoutError:
            raise ProviderError("timeout", "Provider request timed out.", retryable=True) from None
        except APIConnectionError:
            raise ProviderError(
                "connection", "Provider connection failed.", retryable=True
            ) from None
        except ClientAuthenticationError:
            raise ProviderError(
                "authentication", "Azure token acquisition failed; check CLI identity and RBAC."
            ) from None
        except APIStatusError as exc:
            status = exc.status_code
            code = {
                401: "authentication", 403: "authorization", 404: "deployment_not_found",
                429: "rate_limited",
            }.get(status, "provider_unavailable" if status >= 500 else "unsupported_request")
            retry_after = None
            header = exc.response.headers.get("retry-after")
            if header is not None:
                try:
                    seconds = float(header)
                    if math.isfinite(seconds) and seconds >= 0:
                        retry_after = seconds
                except ValueError:
                    retry_after = None
            raise ProviderError(
                code, f"Azure inference rejected the request (HTTP {status}); check {code}.",
                retryable=status == 429 or status >= 500, request_id=exc.request_id,
                retry_after_seconds=retry_after,
            ) from None
        if not isinstance(response, Response):
            raise ProviderError("invalid_response", "Provider response must be an object.")
        usage = self._usage(response)
        request_id = raw.headers.get("x-request-id") or raw.headers.get("apim-request-id")
        version = raw.headers.get("x-ms-model-version")
        try:
            envelope = CoreResponse.model_validate(response.model_dump())
        except ValidationError:
            raise ProviderError(
                "invalid_response", "Provider returned an invalid HTTP response envelope.",
                usage=usage, request_id=request_id,
            ) from None
        with self._model_lock:
            if (
                self._reported_model is not None and self._reported_model != envelope.model
                or self._model_version is not None and self._model_version != version
            ):
                raise ProviderError(
                    "model_drift", "Reported model/version changed or cannot be verified.",
                    usage=usage, request_id=request_id,
                )
            self._reported_model = envelope.model
            self._model_version = version
        text_parts: list[str] = []
        for output in envelope.output:
            if output.type == "message":
                if any(part.type == "refusal" for part in output.content or ()):
                    raise ProviderError(
                        "refusal", "Model refused the synthetic-content request.",
                        usage=usage, request_id=request_id,
                    )
                text_parts.extend(part.text for part in output.content or () if part.text)
        if envelope.status != "completed":
            code = "provider_failed"
            if envelope.status == "incomplete":
                code = (
                    "truncated" if response.incomplete_details
                    and response.incomplete_details.reason == "max_output_tokens" else "incomplete"
                )
            raise ProviderError(
                code, "Model did not complete a valid structured response.",
                usage=usage, request_id=request_id,
            )
        output_text = "".join(text_parts)
        if not output_text.strip():
            raise ProviderError(
                "empty_response", "Provider returned no business content.",
                usage=usage, request_id=request_id,
            )
        try:
            decoded = json.loads(
                output_text, object_pairs_hook=unique_pairs, parse_constant=reject_constant
            )
            payload = TypeAdapter(dict[str, JsonValue]).validate_python(decoded, strict=True)
        except ValueError:
            raise ProviderError(
                "invalid_json", "Model returned invalid or ambiguous JSON.",
                usage=usage, request_id=request_id,
            ) from None
        if not Draft202012Validator(selected_schema).is_valid(payload):
            raise ProviderError(
                "schema_violation", "Model output does not match the required wire schema.",
                usage=usage, request_id=request_id,
            )
        return DraftResponse(
            payload=payload, response_id=envelope.id, request_id=request_id,
            reported_model=envelope.model, model_version=version, usage=usage,
        )
