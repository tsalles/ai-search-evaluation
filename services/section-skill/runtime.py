import base64
import hashlib
import json
import os
import threading
from typing import Annotated

import httpx
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.identity import ManagedIdentityCredential, get_bearer_token_provider
from azure.storage.blob import BlobServiceClient, ContentSettings
from pydantic import Field, JsonValue, TypeAdapter

from docgen.config import ProviderConfig
from docgen.errors import IntegrityError, ProviderError
from docgen.evaluation.section_service import (
    ModelResult,
    canonical_request,
    model_result_from_response,
)
from docgen.models import Record
from docgen.tokenization import token_count


class Budget(Record):
    attempts: Annotated[int, Field(strict=True, ge=0)] = 0
    observed_tokens: Annotated[int, Field(strict=True, ge=0)] = 0
    in_flight: str | None = None
    reported_model: str | None = None
    model_version: str | None = None
    halt_reason: str | None = None
    request_cap: Annotated[int, Field(strict=True, ge=1)] = 1100
    token_cap: Annotated[int, Field(strict=True, ge=1)] = 8000000


class BlobModelLedger:
    def __init__(self) -> None:
        self.settings = ProviderConfig(
            base_url=os.environ["SECTION_MODEL_BASE_URL"],
            deployment=os.environ["SECTION_MODEL_DEPLOYMENT"],
        )
        self.credential = ManagedIdentityCredential(
            client_id=os.environ.get("AZURE_CLIENT_ID"),
        )
        self.token = get_bearer_token_provider(
            self.credential, "https://cognitiveservices.azure.com/.default",
        )
        self.storage = BlobServiceClient(
            os.environ["SECTION_STORAGE_URL"], credential=self.credential,
            retry_total=0, connection_timeout=15, read_timeout=15,
        )
        self.container = self.storage.get_container_client("section-audit")
        self.client = httpx.Client(timeout=30, follow_redirects=False)
        self.lock = threading.Lock()

    def _read(self, name: str) -> bytes | None:
        try:
            return self.container.get_blob_client(name).download_blob().readall()
        except ResourceNotFoundError:
            return None

    def _write(self, name: str, raw: bytes) -> None:
        client = self.container.get_blob_client(name)
        try:
            client.upload_blob(
                raw, overwrite=False, content_settings=ContentSettings(
                    content_type="application/json",
                ),
            )
        except ResourceExistsError:
            if client.download_blob().readall() != raw:
                raise IntegrityError(
                    "An existing audit record differs from its owned content."
                ) from None

    def receipt(self, invocation_id: str, payload: object) -> None:
        self._write(
            "invocations/" + invocation_id + ".json",
            json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(),
        )

    def __call__(self, request: dict[str, JsonValue]) -> ModelResult:
        raw_request = canonical_request(request)
        key = hashlib.sha256(raw_request).hexdigest()
        with self.lock:
            cached = self._read(key + "/result.json")
            if cached is not None:
                return ModelResult.model_validate_json(cached)
            failed = self._read(key + "/failure.json")
            if failed is not None:
                raise ProviderError("cached_model_failure", "The recorded model attempt failed.")
            bearer = self.token()
            budget_blob = self.container.get_blob_client("budget.json")
            try:
                budget_blob.upload_blob(Budget().model_dump_json().encode(), overwrite=False)
            except ResourceExistsError:
                pass
            lease = budget_blob.acquire_lease(lease_duration=60)
            try:
                budget = Budget.model_validate_json(
                    budget_blob.download_blob(lease=lease).readall(),
                )
                if budget.halt_reason is not None:
                    raise ProviderError(
                        "model_halted", "The model study is halted by its audit ledger."
                    )
                if budget.in_flight is not None:
                    raise ProviderError(
                        "unknown_model_outcome",
                        "An earlier model dispatch has an unresolved outcome; no redispatch.",
                    )
                previous = self._read(key + "/last-denial.json")
                if previous is not None:
                    denial = TypeAdapter(dict[str, JsonValue]).validate_json(previous)
                    if denial.get("retryable_before_inference") is not True:
                        raise IntegrityError("The previous model attempt is not safely retryable.")
                estimated = token_count(raw_request.decode()) + 1024 + 2048
                if (
                    budget.request_cap != 1100 or budget.token_cap != 8000000
                    or budget.attempts >= budget.request_cap
                    or budget.observed_tokens + estimated > budget.token_cap
                ):
                    raise ProviderError(
                        "model_budget", "The frozen model request/token cap is reached."
                    )
                attempt = budget.attempts + 1
                prefix = key + f"/attempt-{attempt:05d}"
                self._write(prefix + "-request.json", raw_request)
                pending = budget.model_copy(update={"attempts": attempt, "in_flight": key})
                budget_blob.upload_blob(
                    pending.model_dump_json().encode(), overwrite=True, lease=lease,
                )
                try:
                    response = self.client.post(
                        self.settings.base_url + "chat/completions",
                        json=request, headers={"Authorization": "Bearer " + bearer},
                    )
                except httpx.TransportError:
                    self._write(prefix + "-unknown.json", b'{"status":"transport_unknown"}')
                    raise ProviderError(
                        "transport_unknown", "Model transport failed with an unknown outcome."
                    ) from None
                self._write(prefix + "-response.json", json.dumps({
                    "status_code": response.status_code,
                    "request_id": (
                        response.headers.get("x-request-id")
                        or response.headers.get("apim-request-id")
                    ),
                    "model_version": response.headers.get("x-ms-model-version"),
                    "body_base64": base64.b64encode(response.content).decode(),
                }, ensure_ascii=False).encode())
                if response.status_code in {401, 403, 429}:
                    settled = pending.model_copy(update={"in_flight": None})
                    budget_blob.upload_blob(
                        settled.model_dump_json().encode(), overwrite=True, lease=lease,
                    )
                    denial_bytes = json.dumps({
                        "retryable_before_inference": True,
                        "http_status": response.status_code,
                    }).encode()
                    denial_blob = self.container.get_blob_client(key + "/last-denial.json")
                    denial_blob.upload_blob(denial_bytes, overwrite=True)
                    raise ProviderError(
                        "model_access_or_rate_limit",
                        f"Model access/rate limit was rejected (HTTP {response.status_code}).",
                    )
                try:
                    inferred, tokens = model_result_from_response(
                        response.content, status_code=response.status_code, request_key=key,
                    )
                except ProviderError as exc:
                    if exc.usage is not None and exc.usage.total_tokens is not None:
                        settled = pending.model_copy(update={
                            "in_flight": None,
                            "observed_tokens": budget.observed_tokens + exc.usage.total_tokens,
                        })
                        budget_blob.upload_blob(
                            settled.model_dump_json().encode(), overwrite=True, lease=lease,
                        )
                        self._write(key + "/failure.json", json.dumps({
                            "code": exc.code, "known_tokens": exc.usage.total_tokens,
                        }).encode())
                    raise
                version = response.headers.get("x-ms-model-version")
                drift = budget.reported_model is not None and (
                    budget.reported_model != inferred.model or budget.model_version != version
                )
                total = budget.observed_tokens + tokens
                settled = pending.model_copy(update={
                    "in_flight": None, "observed_tokens": total,
                    "reported_model": budget.reported_model or inferred.model,
                    "model_version": budget.model_version if budget.reported_model else version,
                    "halt_reason": (
                        "model_drift" if drift
                        else "model_budget" if total > budget.token_cap else None
                    ),
                })
                budget_blob.upload_blob(
                    settled.model_dump_json().encode(), overwrite=True, lease=lease,
                )
                if drift:
                    raise ProviderError("model_drift", "The model/version changed during indexing.")
                if settled.observed_tokens > settled.token_cap:
                    raise ProviderError("model_budget", "Observed model usage exceeded the cap.")
                if inferred.audit_json is None:
                    raise IntegrityError("A completed model result has no raw response audit.")
                audit = TypeAdapter(dict[str, JsonValue]).validate_json(inferred.audit_json)
                audit.update({
                    "request_base64": base64.b64encode(raw_request).decode(),
                    "global_attempts": settled.attempts,
                    "global_observed_tokens": settled.observed_tokens,
                    "request_key": key,
                })
                inferred = inferred.model_copy(update={
                    "audit_json": json.dumps(audit, separators=(",", ":")),
                })
                self._write(key + "/result.json", inferred.model_dump_json().encode())
                return inferred
            finally:
                lease.release()
