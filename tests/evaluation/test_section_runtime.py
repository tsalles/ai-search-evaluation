import base64
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import azure.functions as func
import httpx
import pytest
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

from docgen.evaluation.section_service import handle_skill_request

SERVICE = Path(__file__).resolve().parents[2] / "services" / "section-skill"
CALLER = "00000000-0000-0000-0000-000000000001"


class Download:
    def __init__(self, value):
        self.value = value

    def readall(self):
        return self.value


class Blob:
    def __init__(self, values, name):
        self.values, self.name = values, name

    def download_blob(self, **kwargs):
        if self.name not in self.values:
            raise ResourceNotFoundError("missing")
        return Download(self.values[self.name])

    def upload_blob(self, raw, *, overwrite=False, **kwargs):
        if self.name in self.values and not overwrite:
            raise ResourceExistsError("already exists")
        self.values[self.name] = raw

    def acquire_lease(self, **kwargs):
        return SimpleNamespace(release=lambda: None)


def load_module(name, path, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def response(request):
    data = json.loads(request.content)
    source = json.loads(data["messages"][1]["content"])
    return {
        "id": "model-response", "model": "gpt-5.4-mini-test",
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        "choices": [{
            "finish_reason": "stop",
            "message": {"role": "assistant", "refusal": None, "content": json.dumps({
                "source_sha256": source["source_sha256"], "title_block": None,
                "sections": [{"start_block": "b0000", "heading_block": None}],
            })},
        }],
    }


def payload(text="Native extracted text.\nAnother paragraph.\n"):
    return {"values": [{
        "recordId": "opaque-record", "data": {
            "text": text, "source_path": "https://owned.blob.core.windows.net/raw/input.pdf",
        },
    }]}


@pytest.fixture
def runtime(monkeypatch):
    module = load_module("section_runtime_under_test", SERVICE / "runtime.py", monkeypatch)
    monkeypatch.setenv("SECTION_MODEL_BASE_URL", "https://owned.openai.azure.com/openai/v1/")
    monkeypatch.setenv("SECTION_MODEL_DEPLOYMENT", "gpt-5.4-mini")
    monkeypatch.setenv("SECTION_STORAGE_URL", "https://owned.blob.core.windows.net")
    monkeypatch.setenv("SECTION_SEARCH_PRINCIPAL_ID", CALLER)
    values, calls = {}, []
    handler = [lambda request: httpx.Response(200, json=response(request))]

    def dispatch(request):
        calls.append(request)
        return handler[0](request)

    client = httpx.Client(transport=httpx.MockTransport(dispatch), follow_redirects=False)
    container = SimpleNamespace(get_blob_client=lambda name: Blob(values, name))
    monkeypatch.setattr(module, "ManagedIdentityCredential", lambda **kwargs: object())
    monkeypatch.setattr(
        module, "get_bearer_token_provider", lambda *args: lambda: "secret-model-bearer",
    )
    monkeypatch.setattr(module, "BlobServiceClient", lambda *args, **kwargs: SimpleNamespace(
        get_container_client=lambda name: container,
    ))
    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: client)
    try:
        yield module, values, calls, handler
    finally:
        client.close()


def test_durable_model_ledger_reuses_completed_plan_and_preserves_wire_records(runtime):
    module, values, calls, _ = runtime
    ledger = module.BlobModelLedger()
    first = handle_skill_request(payload(), deployment="gpt-5.4-mini", model_call=ledger)
    second = handle_skill_request(payload(), deployment="gpt-5.4-mini", model_call=ledger)
    assert first == second
    assert first["values"][0]["errors"] == []
    assert len(calls) == 1
    budget = json.loads(values["budget.json"])
    assert budget["attempts"] == 1
    assert budget["observed_tokens"] == 30
    assert budget["in_flight"] is None
    assert any(name.endswith("-request.json") for name in values)
    assert any(name.endswith("-response.json") for name in values)
    assert all(b"secret-model-bearer" not in raw for raw in values.values())
    audit = json.loads(first["values"][0]["data"]["enrichment"]["model_audit"])
    assert audit["global_attempts"] == 1
    assert audit["global_observed_tokens"] == audit["total_tokens"] == 30
    assert json.loads(base64.b64decode(audit["request_base64"]))["model"] == "gpt-5.4-mini"
    assert json.loads(base64.b64decode(audit["response_base64"]))["id"] == "model-response"


def test_unknown_model_transport_is_durable_and_prevents_additional_dispatch(runtime):
    module, values, calls, handler = runtime

    def timeout(request):
        raise httpx.ReadTimeout("unsafe detail", request=request)

    handler[0] = timeout
    ledger = module.BlobModelLedger()
    first = handle_skill_request(payload(), deployment="gpt-5.4-mini", model_call=ledger)
    second = handle_skill_request(
        payload("A different document.\n"), deployment="gpt-5.4-mini", model_call=ledger,
    )
    assert first["values"][0]["errors"] and second["values"][0]["errors"]
    assert len(calls) == 1
    assert json.loads(values["budget.json"])["in_flight"] is not None
    assert any(name.endswith("-unknown.json") for name in values)
    assert "unsafe detail" not in json.dumps(first)


@pytest.mark.parametrize("status", [401, 403, 429])
def test_pre_inference_denial_is_counted_and_can_retry_without_unknown_paid_usage(runtime, status):
    module, values, calls, handler = runtime
    handler[0] = lambda request: httpx.Response(status, json={"error": "denied"})
    ledger = module.BlobModelLedger()
    first = handle_skill_request(payload(), deployment="gpt-5.4-mini", model_call=ledger)
    assert first["values"][0]["errors"]
    assert json.loads(values["budget.json"])["in_flight"] is None
    handler[0] = lambda request: httpx.Response(200, json=response(request))
    second = handle_skill_request(payload(), deployment="gpt-5.4-mini", model_call=ledger)
    assert second["values"][0]["errors"] == []
    assert len(calls) == 2
    assert json.loads(values["budget.json"])["attempts"] == 2
    assert json.loads(values["budget.json"])["observed_tokens"] == 30


def test_refusal_retains_known_usage_and_never_redispatches_the_failed_plan(runtime):
    module, values, calls, handler = runtime

    def refused(request):
        data = response(request)
        data["choices"][0]["message"]["refusal"] = "declined"
        return httpx.Response(200, json=data)

    handler[0] = refused
    ledger = module.BlobModelLedger()
    for _ in range(2):
        result = handle_skill_request(payload(), deployment="gpt-5.4-mini", model_call=ledger)
        assert result["values"][0]["errors"]
    assert len(calls) == 1
    assert json.loads(values["budget.json"])["observed_tokens"] == 30
    assert json.loads(values["budget.json"])["in_flight"] is None


def test_model_drift_halts_future_inference_but_retains_observed_cost(runtime):
    module, values, calls, handler = runtime
    ledger = module.BlobModelLedger()
    assert handle_skill_request(payload(), deployment="gpt-5.4-mini", model_call=ledger)[
        "values"
    ][0]["errors"] == []

    def changed(request):
        data = response(request)
        data["model"] = "changed-model"
        return httpx.Response(200, json=data)

    handler[0] = changed
    for text in ("Second input.\n", "Third input.\n"):
        result = handle_skill_request(
            payload(text), deployment="gpt-5.4-mini", model_call=ledger,
        )
        assert result["values"][0]["errors"]
    assert len(calls) == 2
    assert json.loads(values["budget.json"])["observed_tokens"] == 60
    assert json.loads(values["budget.json"])["halt_reason"] == "model_drift"


def test_request_cap_is_enforced_before_another_model_dispatch(runtime):
    module, values, calls, _ = runtime
    values["budget.json"] = module.Budget(attempts=1100).model_dump_json().encode()
    ledger = module.BlobModelLedger()
    result = handle_skill_request(payload(), deployment="gpt-5.4-mini", model_call=ledger)
    assert result["values"][0]["errors"]
    assert calls == []


def test_real_functions_handler_fails_closed_and_runs_the_authenticated_contract(
    runtime, monkeypatch,
):
    module, values, calls, _ = runtime
    monkeypatch.setitem(sys.modules, "runtime", module)
    application = load_module(
        "section_function_under_test", SERVICE / "function_app.py", monkeypatch,
    )
    function = application.app.get_functions()[0].get_user_function()
    context = SimpleNamespace(invocation_id="invocation-test")
    for caller in (None, "not-the-search-identity"):
        headers = {} if caller is None else {"X-MS-CLIENT-PRINCIPAL-ID": caller}
        request = func.HttpRequest(
            method="POST", url="https://owned.azurewebsites.net/api/sections",
            headers=headers, body=json.dumps(payload()).encode(),
        )
        assert function(request, context).status_code == 403
    assert calls == []
    request = func.HttpRequest(
        method="POST", url="https://owned.azurewebsites.net/api/sections",
        headers={"X-MS-CLIENT-PRINCIPAL-ID": CALLER},
        body=json.dumps(payload()).encode(),
    )
    result = function(request, context)
    assert result.status_code == 200
    assert json.loads(result.get_body())["values"][0]["errors"] == []
    receipt = json.loads(values["invocations/invocation-test.json"])
    assert receipt["caller_principal_id"] == CALLER
    assert len(calls) == 1
