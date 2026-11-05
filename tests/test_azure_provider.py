import json
import logging
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError

from docgen.cli import main
from docgen.config import Config, Limits, ProviderConfig
from docgen.doctor import doctor
from docgen.errors import InputError, ProviderError
from docgen.providers.azure import AzureProvider
from docgen.wire import DRAFT_SCHEMA
from tests.test_planning import configuration

SETTINGS = ProviderConfig(
    base_url="https://example.openai.azure.com/openai/v1/", deployment="gpt-6-luna"
)


def draft() -> dict[str, Any]:
    return {
        "title": "Teste de capacidade",
        "blocks": [
            {"id": "intro", "kind": "paragraph", "text": "Texto ficticio.",
             "level": None, "table_id": None},
        ],
        "list_items": [], "columns": [], "cells": [], "facts": [],
    }


def response() -> dict[str, Any]:
    return {
        "id": "resp-test", "object": "response", "created_at": 1792758000,
        "status": "completed", "model": "gpt-6-luna-2026-09-22",
        "output": [{
            "id": "msg-test", "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": json.dumps(draft()), "annotations": []}],
        }],
        "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        "temperature": 1, "top_p": 1, "error": None, "incomplete_details": None,
        "usage": {
            "input_tokens": 10, "output_tokens": 20, "total_tokens": 30,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 5},
        },
    }


class ExpiringCredential:
    def __init__(self) -> None:
        self.scopes: list[tuple[str, ...]] = []
        self.closed = False

    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        self.scopes.append(scopes)
        return AccessToken(f"sentinel-token-{len(self.scopes)}", int(time.time()) + 10)

    def close(self) -> None:
        self.closed = True


def provider_with(
    handler: Callable[[httpx.Request], httpx.Response],
    credential: ExpiringCredential | None = None,
) -> AzureProvider:
    return AzureProvider(
        SETTINGS, limits=Limits(max_output_tokens_per_request=2048),
        credential=credential or ExpiringCredential(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )


@pytest.mark.parametrize("valid", [False, True])
def test_provider_submits_and_validates_the_same_explicit_authoring_schema(valid):
    schema = json.loads(json.dumps(DRAFT_SCHEMA))
    schema["properties"]["title"] = {"type": "string", "enum": ["Bound title"]}

    def handler(request):
        body = json.loads(request.content)
        assert body["text"]["format"]["schema"] == schema
        envelope = response()
        payload = draft()
        payload["title"] = "Bound title" if valid else "Unbound title"
        envelope["output"][0]["content"][0]["text"] = json.dumps(payload)
        return httpx.Response(200, json=envelope)

    with provider_with(handler) as provider:
        if valid:
            assert provider.request(
                "Bound content.", schema=schema,
            ).payload["title"] == "Bound title"
        else:
            with pytest.raises(ProviderError) as raised:
                provider.request("Bound content.", schema=schema)
            assert raised.value.code == "schema_violation"
            assert raised.value.usage.total_tokens == 30


def test_real_sdk_submits_strict_schema_with_renewable_tokens_and_no_storage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = []
    caplog.set_level(logging.DEBUG, logger="openai")
    credential = ExpiringCredential()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url == "https://example.openai.azure.com/openai/v1/responses"
        body = json.loads(request.content)
        assert body["model"] == "gpt-6-luna"
        assert body["store"] is False
        assert body["max_output_tokens"] == 256
        assert body["text"]["format"]["schema"] == DRAFT_SCHEMA
        assert body["text"]["format"]["strict"] is True
        assert not {"temperature", "seed", "reasoning", "tools"}.intersection(body)
        return httpx.Response(
            200, json=response(),
            headers={"x-request-id": "request-test", "x-ms-model-version": "2026-09-22"},
        )

    with provider_with(handler, credential) as provider:
        first = provider.request("Synthetic probe only.", max_output_tokens=256)
        second = provider.request("Synthetic probe only.", max_output_tokens=256)
    assert first.payload == draft()
    assert first.request_id == "request-test"
    assert first.model_version == "2026-09-22"
    assert first.usage.total_tokens == 30
    assert first.usage.reasoning_tokens == 5
    assert len(calls) == 2
    assert all(scope == ("https://ai.azure.com/.default",) for scope in credential.scopes)
    assert calls[0].headers["authorization"] != calls[1].headers["authorization"]
    assert "sentinel-token" not in first.model_dump_json() + second.model_dump_json() + caplog.text
    assert credential.closed is False


@pytest.mark.parametrize(("status", "code", "retryable"), [
    (400, "unsupported_request", False),
    (401, "authentication", False),
    (403, "authorization", False),
    (404, "deployment_not_found", False),
    (422, "unsupported_request", False),
    (429, "rate_limited", True),
    (500, "provider_unavailable", True),
    (503, "provider_unavailable", True),
])
def test_http_failures_are_safe_typed_and_not_implicitly_retried(
    status: int, code: str, retryable: bool,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status, json={"error": {"message": "sentinel-secret", "code": "unsafe"}},
            headers={"retry-after": "10"},
        )

    with provider_with(handler) as provider:
        with pytest.raises(ProviderError) as failure:
            provider.request("Synthetic probe.")
    assert calls == 1
    assert failure.value.code == code
    assert failure.value.retryable is retryable
    assert "sentinel-secret" not in "".join(traceback.format_exception(failure.value))
    if status == 429:
        assert failure.value.retry_after_seconds == 10


@pytest.mark.parametrize(("mutate", "code"), [
    (lambda r: r.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"}),
     "truncated"),
    (lambda r: r.update(status="failed"), "provider_failed"),
    (lambda r: r["output"][0].update(content=[
        {"type": "refusal", "refusal": "sentinel-secret"},
    ]), "refusal"),
    (lambda r: r["output"][0]["content"][0].update(text="{"), "invalid_json"),
    (lambda r: r["output"][0]["content"][0].update(text='{"title": "incomplete"}'),
     "schema_violation"),
    (lambda r: r["output"][0]["content"][0].update(text='{"title": NaN}'), "invalid_json"),
    (lambda r: r["output"][0]["content"][0].update(text='{"title":"a","title":"b"}'),
     "invalid_json"),
    (lambda r: r.update(output=[]), "empty_response"),
    (lambda r: r.update(usage={
        "input_tokens": 10, "output_tokens": 20, "total_tokens": 31,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 5},
    }), "invalid_usage"),
])
def test_refused_incomplete_or_invalid_drafts_are_never_success(mutate: Any, code: str) -> None:
    payload = response()
    mutate(payload)
    with provider_with(lambda request: httpx.Response(200, json=payload)) as provider:
        with pytest.raises(ProviderError) as failure:
            provider.request("Synthetic probe.")
    assert failure.value.code == code
    assert "sentinel-secret" not in str(failure.value)
    if code != "invalid_usage":
        assert failure.value.usage.total_tokens == 30


def test_unknown_usage_and_version_are_not_replaced_with_zero_or_invented_values() -> None:
    payload = response()
    payload["usage"] = None
    with provider_with(lambda request: httpx.Response(200, json=payload)) as provider:
        result = provider.request("Synthetic probe.")
    assert result.usage is None
    assert result.model_version is None
    assert result.reported_model == "gpt-6-luna-2026-09-22"


def test_azure_envelope_does_not_require_unused_openai_options_or_reasoning_summaries() -> None:
    payload = response()
    for key in ("parallel_tool_calls", "tool_choice", "tools", "temperature", "top_p"):
        payload.pop(key)
    payload["output"].insert(0, {"id": "reason-test", "type": "reasoning", "summary": None})
    with provider_with(lambda request: httpx.Response(200, json=payload)) as provider:
        result = provider.request("Synthetic probe.")
    assert result.payload == draft()
    assert result.usage.total_tokens == 30


def test_reported_model_drift_is_terminal() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        payload = response()
        calls += 1
        if calls == 2:
            payload["model"] = "gpt-6-luna-new-version"
        return httpx.Response(200, json=payload)

    with provider_with(handler) as provider:
        provider.request("Synthetic probe.")
        with pytest.raises(ProviderError) as failure:
            provider.request("Synthetic probe.")
    assert failure.value.code == "model_drift"
    assert failure.value.retryable is False


@pytest.mark.parametrize("error", [httpx.ReadTimeout("sentinel-secret"),
                                 httpx.ConnectError("sentinel-secret")])
def test_transport_errors_have_safe_diagnostics(error: Exception) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise error

    with provider_with(handler) as provider:
        with pytest.raises(ProviderError) as failure:
            provider.request("Synthetic probe.")
    assert failure.value.retryable is True
    assert failure.value.code in {"timeout", "connection"}
    assert calls == 1
    assert "sentinel-secret" not in "".join(traceback.format_exception(failure.value))


def test_credential_failures_are_safe_and_do_not_issue_http_requests() -> None:
    class BadCredential(ExpiringCredential):
        def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
            raise ClientAuthenticationError("sentinel-secret")

    def unexpected(request: httpx.Request) -> httpx.Response:
        pytest.fail("Authentication failure must not send an HTTP request.")

    with provider_with(unexpected, BadCredential()) as provider:
        with pytest.raises(ProviderError) as failure:
            provider.request("Synthetic probe.")
    assert failure.value.code == "authentication"
    assert "sentinel-secret" not in "".join(traceback.format_exception(failure.value))


def test_local_doctor_has_no_credential_or_network_side_effects(tmp_path: Path) -> None:
    data = configuration()
    data["generation"]["provider"] = SETTINGS.model_dump(mode="python")
    cfg = Config.model_validate(data)
    result = doctor(cfg)
    assert result["status"] == "ready"
    assert result["details"]["live_verified"] is False
    assert result["details"]["scope"] == "local"
    assert result["usage"] is None
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(InputError, match="provider"):
        doctor(Config.model_validate(configuration()))


def test_invalid_request_limits_and_closed_provider_fail_before_http() -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid requests must not send HTTP.")

    with provider_with(unexpected) as provider:
        for limit in (0, -1, True, 4096):
            with pytest.raises(InputError):
                provider.request("Synthetic probe.", max_output_tokens=limit)
        with pytest.raises(InputError):
            provider.request(" ")
    with pytest.raises(ProviderError, match="closed"):
        provider.request("Synthetic probe.")


@pytest.mark.parametrize("body", [b"not-json", b'{"status":"completed"}', b"[]"])
def test_malformed_http_success_is_not_an_untyped_crash(body: bytes) -> None:
    with provider_with(lambda request: httpx.Response(
        200, content=body, headers={"content-type": "application/json"}
    )) as provider:
        with pytest.raises(ProviderError) as failure:
            provider.request("Synthetic probe.")
    assert failure.value.code == "invalid_response"


def test_redirect_is_not_followed_or_sent_to_a_second_host() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(307, headers={"location": "https://example.invalid/collect"})

    with provider_with(handler) as provider:
        with pytest.raises(ProviderError):
            provider.request("Synthetic probe.")
    assert calls == ["example.openai.azure.com"]


@pytest.mark.parametrize(("timeout", "credential_timeout"), [(120, 60), (5, 5)])
def test_owned_default_credential_is_closed_and_interactive_login_is_disabled(
    monkeypatch: pytest.MonkeyPatch, timeout: int, credential_timeout: int,
) -> None:
    credential = ExpiringCredential()
    arguments = []

    def build(**kwargs: Any) -> ExpiringCredential:
        arguments.append(kwargs)
        return credential

    monkeypatch.setenv("AZURE_TOKEN_CREDENTIALS", "AzureCliCredential")
    monkeypatch.setattr("docgen.providers.azure.DefaultAzureCredential", build)
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=response())
    ))
    with AzureProvider(
        SETTINGS, limits=Limits(request_timeout_seconds=timeout), http_client=client
    ) as provider:
        provider.request("Synthetic probe.")
    assert credential.closed
    assert client.is_closed
    assert arguments == [{
        "exclude_interactive_browser_credential": True,
        "exclude_broker_credential": True,
        "process_timeout": credential_timeout,
    }]


def test_live_doctor_path_with_real_sdk_and_simulated_azure() -> None:
    data = configuration()
    data["generation"]["provider"] = SETTINGS.model_dump(mode="python")
    cfg = Config.model_validate(data)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=response())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = doctor(cfg, live=True, credential=ExpiringCredential(), http_client=client)
    assert len(calls) == 1
    assert calls[0]["max_output_tokens"] == 2048
    assert calls[0]["store"] is False
    assert result["status"] == "ready"
    assert result["details"]["live_verified"] is True
    assert result["details"]["scope"] == "live"
    assert result["details"]["wire_schema_validated"] is True
    assert result["usage"]["total_tokens"] == 30


def test_failed_doctor_keeps_failure_and_usage_instead_of_success() -> None:
    data = configuration()
    data["generation"]["provider"] = SETTINGS.model_dump(mode="python")
    payload = response()
    payload["status"] = "incomplete"
    payload["incomplete_details"] = {"reason": "max_output_tokens"}
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)
    ))
    result = doctor(
        Config.model_validate(data), live=True,
        credential=ExpiringCredential(), http_client=client,
    )
    assert result["status"] == "incomplete"
    assert result["details"]["live_verified"] is False
    assert result["failures"][0]["code"] == "truncated"
    assert result["usage"]["total_tokens"] == 30


def test_cli_doctor_default_is_local_only(tmp_path: Path) -> None:
    data = configuration()
    data["generation"]["provider"] = SETTINGS.model_dump(mode="python")
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "docgen", "doctor", "--config", str(path), "--json"],
        capture_output=True, text=True, cwd=tmp_path, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["details"]["live_verified"] is False
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("next_version", ["v2", None])
def test_reported_version_drift_or_loss_blocks_continuation(next_version: str | None) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        value = "v1" if calls == 1 else next_version
        headers = {"x-ms-model-version": value} if value is not None else {}
        return httpx.Response(200, json=response(), headers=headers)

    with provider_with(handler) as provider:
        provider.request("Synthetic probe.")
        with pytest.raises(ProviderError) as failure:
            provider.request("Synthetic probe.")
    assert failure.value.code == "model_drift"


def test_redirecting_client_is_rejected_before_credential_discovery() -> None:
    with httpx.Client(follow_redirects=True) as client:
        with pytest.raises(InputError, match="redirect"):
            AzureProvider(SETTINGS, http_client=client)


def test_missing_core_usage_is_an_error_but_unknown_reasoning_stays_unknown() -> None:
    payload = response()
    payload["usage"]["input_tokens"] = None
    with provider_with(lambda request: httpx.Response(200, json=payload)) as provider:
        with pytest.raises(ProviderError) as failure:
            provider.request("Synthetic probe.")
    assert failure.value.code == "invalid_usage"
    payload = response()
    payload["usage"]["output_tokens_details"] = {}
    with provider_with(lambda request: httpx.Response(200, json=payload)) as provider:
        result = provider.request("Synthetic probe.")
    assert result.usage.total_tokens == 30
    assert result.usage.reasoning_tokens is None


def test_doctor_failed_http_has_unknown_not_zero_usage() -> None:
    data = configuration()
    data["generation"]["provider"] = SETTINGS.model_dump(mode="python")
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(401, json={"error": {"message": "sentinel-secret"}})
    ))
    result = doctor(
        Config.model_validate(data), live=True,
        credential=ExpiringCredential(), http_client=client,
    )
    assert result["status"] == "incomplete"
    assert result["usage"] is None
    assert result["failures"][0]["code"] == "authentication"
    assert "sentinel-secret" not in json.dumps(result)


def test_cli_invalid_doctor_input_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(configuration()), encoding="utf-8")
    assert main(["doctor", "--config", str(path), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid_input"


def test_cli_live_failure_exits_three_with_safe_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    data = configuration()
    data["generation"]["provider"] = SETTINGS.model_dump(mode="python")
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    class SimulatedHTTPClient(httpx.Client):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(transport=httpx.MockTransport(
                lambda request: httpx.Response(429, json={"error": {"message": "sentinel-secret"}})
            ))

    monkeypatch.setattr(
        "docgen.providers.azure.DefaultAzureCredential", lambda **kwargs: ExpiringCredential()
    )
    monkeypatch.setattr("docgen.providers.azure.httpx.Client", SimulatedHTTPClient)
    assert main(["doctor", "--config", str(path), "--live", "--json"]) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "incomplete"
    assert result["failures"][0]["code"] == "rate_limited"
    assert "sentinel-secret" not in json.dumps(result)
