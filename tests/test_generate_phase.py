import json
import threading
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest

from docgen.budgets import BudgetOverride, increase_budget
from docgen.config import Config, GenerationConfig
from docgen.errors import IntegrityError, ProviderError
from docgen.generation import generate_content
from docgen.models import Blueprint, Content, content_hash
from docgen.pipeline import generate
from docgen.store import RunStore
from tests.fixtures.factories import content_wire, diverse_content
from tests.test_azure_provider import SETTINGS, ExpiringCredential, response
from tests.test_planning import configuration


class BatchProvider:
    def __init__(self, fail: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail = fail
        self._lock = threading.Lock()

    def generate(self, blueprint: Blueprint, config: GenerationConfig) -> Content:
        with self._lock:
            self.calls.append(blueprint.content_id)
        if blueprint.content_id == self.fail:
            raise ProviderError("refusal", "Synthetic fixture refusal.")
        return diverse_content(blueprint)


def batch_config(count: int = 4, **limits: int) -> Config:
    data = configuration(count)
    data["generation"]["length_weights"] = {"short": 1}
    data["generation"]["limits"] = limits
    return Config.model_validate(data)


def test_phase_one_generates_exactly_n_items_and_no_artifacts(tmp_path: Path) -> None:
    source = BatchProvider()
    result = generate(batch_config(8), tmp_path, provider=source)
    assert result.status == "content_ready", result
    assert result.accepted_count == 8
    assert len(source.calls) == 8
    directory = tmp_path / result.run_id
    with RunStore.open(directory) as store:
        assert len(store.contents()) == 8
        assert all(item.normalized_fingerprint for item in store.contents())
        assert len(store.attempts()) == 8
        assert Counter(item.blueprint.genre for item in store.contents()) == store.plan.genre_quotas
        assert store.connection.execute("SELECT COUNT(*) FROM assignments").fetchone()[0] == 0
    assert not (directory / "corpus").exists()


def test_restart_reuses_accepted_hashes_and_calls_only_unfinished_slots(tmp_path: Path) -> None:
    source = BatchProvider(fail="item-000001")
    result = generate(batch_config(), tmp_path, provider=source)
    assert result.status == "incomplete"
    assert result.accepted_count == 3
    directory = tmp_path / result.run_id
    with RunStore.open(directory) as store:
        before = {item.blueprint.content_id: content_hash(item) for item in store.contents()}
        retry = BatchProvider()
        resumed = generate_content(store, provider=retry)
        assert resumed.status == "content_ready", resumed
        assert retry.calls == ["item-000001"]
        after = {item.blueprint.content_id: content_hash(item) for item in store.contents()}
        assert all(after[key] == value for key, value in before.items())


def test_duplicate_candidates_exhaust_without_placeholders_and_do_not_get_free_retries(
    tmp_path: Path,
) -> None:
    class DuplicateProvider(BatchProvider):
        def generate(self, blueprint: Blueprint, config: GenerationConfig) -> Content:
            self.calls.append(blueprint.content_id)
            first = blueprint.model_copy(update={"ordinal": 1})
            return diverse_content(first).model_copy(update={"blueprint": blueprint})

    data = batch_config(3).model_dump()
    data["generation"]["genre_weights"] = {"explainer": 1}
    source = DuplicateProvider()
    result = generate(Config.model_validate(data), tmp_path, provider=source)
    assert result.status == "incomplete"
    assert result.accepted_count == 1
    assert len(source.calls) == 7
    with RunStore.open(tmp_path / result.run_id) as store:
        before = len(source.calls)
        again = generate_content(store, provider=source)
        assert again.status == "incomplete"
        assert len(source.calls) == before
        assert all(store.candidate_count(key) == 3 for key in ("item-000002", "item-000003"))
    assert not (tmp_path / result.run_id / "corpus").exists()


def test_request_budget_is_durable_and_stops_scheduling_new_model_work(tmp_path: Path) -> None:
    source = BatchProvider()
    result = generate(batch_config(5, max_requests=2), tmp_path, provider=source)
    assert result.status == "incomplete"
    assert len(source.calls) == 2
    assert result.usage["requests"] == 2
    with RunStore.open(tmp_path / result.run_id) as store:
        resumed = generate_content(store, provider=source)
        assert resumed.status == "incomplete"
        assert len(source.calls) == 2
        assert len(store.attempts()) == 2


def test_exhausted_transport_retries_stop_new_items_instead_of_repeating_an_outage(
    tmp_path: Path,
) -> None:
    class DisconnectedProvider(BatchProvider):
        def generate(self, blueprint: Blueprint, config: GenerationConfig) -> Content:
            self.calls.append(blueprint.content_id)
            raise ProviderError("connection", "Known transport failure.", retryable=True)

    source = DisconnectedProvider()
    result = generate(batch_config(6, concurrency=1), tmp_path, provider=source)
    assert result.status == "incomplete"
    assert result.accepted_count == 0
    assert len(source.calls) == 3
    assert set(source.calls) == {"item-000001"}
    assert result.usage["requests"] == 3
    assert any(failure["code"] == "connection" for failure in result.failures)


def test_larger_candidate_limit_cannot_exceed_the_overall_request_cap(tmp_path: Path) -> None:
    class InvalidProvider(BatchProvider):
        def generate(self, blueprint: Blueprint, config: GenerationConfig) -> Content:
            self.calls.append(blueprint.content_id)
            raise ProviderError("invalid_candidate", "Rejected fixture candidate.")

    data = batch_config(1, max_requests=2, concurrency=1).model_dump()
    data["generation"]["quality"]["max_candidates_per_item"] = 10
    source = InvalidProvider()
    result = generate(Config.model_validate(data), tmp_path, provider=source)
    assert result.status == "incomplete"
    assert len(source.calls) == result.usage["requests"] == 2


def test_cancelled_requests_remain_unknown_instead_of_fabricated_success(tmp_path: Path) -> None:
    class CancelProvider(BatchProvider):
        def generate(self, blueprint: Blueprint, config: GenerationConfig) -> Content:
            raise KeyboardInterrupt

    result = generate(batch_config(2, concurrency=1), tmp_path, provider=CancelProvider())
    assert result.status == "cancelled"
    assert result.accepted_count == 0
    with RunStore.open(tmp_path / result.run_id) as store:
        assert len(store.attempts()) == 1
        assert store.attempts()[0].status == "unknown"


def test_real_azure_adapter_is_wired_through_tracking_composition_and_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        context = json.loads(body["input"].split("Context:\n", 1)[1])
        blueprint = Blueprint.model_validate(context["blueprint"])
        calls.append(blueprint.content_id)
        payload = response()
        payload["output"][0]["content"][0]["text"] = json.dumps(
            content_wire(diverse_content(blueprint))
        )
        return httpx.Response(200, json=payload)

    class SimulatedHTTPClient(httpx.Client):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(
        "docgen.providers.azure.DefaultAzureCredential", lambda **kwargs: ExpiringCredential()
    )
    monkeypatch.setattr("docgen.providers.azure.httpx.Client", SimulatedHTTPClient)
    data = batch_config(3).model_dump()
    data["generation"]["provider"] = SETTINGS
    result = generate(Config.model_validate(data), tmp_path)
    assert result.status == "content_ready", result
    assert len(calls) == 3
    assert result.usage["observed_total_tokens"] == 90
    with RunStore.open(tmp_path / result.run_id) as store:
        assert all(item.provenance.reported_model for item in store.contents())
        assert len(list((store.directory / "attempts").glob("*.json"))) == 3


def test_resume_preserves_rejection_feedback_in_the_real_authoring_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        context = json.loads(body["input"].split("Context:\n", 1)[1])
        contexts.append(context)
        blueprint = Blueprint.model_validate(context["blueprint"])
        wire = content_wire(diverse_content(blueprint))
        if len(contexts) == 1:
            wire["title"] = "Untracked value 99"
        payload = response()
        payload["output"][0]["content"][0]["text"] = json.dumps(wire)
        return httpx.Response(200, json=payload)

    class SimulatedHTTPClient(httpx.Client):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(
        "docgen.providers.azure.DefaultAzureCredential", lambda **kwargs: ExpiringCredential()
    )
    monkeypatch.setattr("docgen.providers.azure.httpx.Client", SimulatedHTTPClient)
    data = batch_config(1, concurrency=1, max_requests=3).model_dump()
    data["generation"].update(provider=SETTINGS, quality={"max_candidates_per_item": 1})
    first = generate(Config.model_validate(data), tmp_path)
    assert first.status == "incomplete"
    assert contexts[0]["prior_rejections"] == []
    with RunStore.open(tmp_path / first.run_id) as store:
        increase_budget(store, BudgetOverride(max_candidates_per_item=2))
        resumed = generate_content(store)
        assert resumed.status == "content_ready"
    assert len(contexts) == 2
    assert any("Quantitative prose" in message for message in contexts[1]["prior_rejections"])


@pytest.mark.parametrize("corruption", ["malformed", "foreign_run"])
def test_resume_rejects_invalid_persisted_rejection_reports_before_model_calls(
    tmp_path: Path, corruption: str,
) -> None:
    source = BatchProvider(fail="item-000001")
    first = generate(batch_config(1), tmp_path, provider=source)
    path = tmp_path / first.run_id / "reports" / "content-quality.json"
    if corruption == "malformed":
        path.write_text("{", encoding="utf-8")
    else:
        data = json.loads(path.read_bytes())
        data["run_id"] = "run-foreign"
        path.write_text(json.dumps(data), encoding="utf-8")
    before = len(source.calls)
    with RunStore.open(tmp_path / first.run_id) as store:
        with pytest.raises(IntegrityError, match="rejection"):
            generate_content(store, provider=source)
    assert len(source.calls) == before
