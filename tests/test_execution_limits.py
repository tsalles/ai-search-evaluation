import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from docgen.config import Config
from docgen.errors import ProviderError
from docgen.execution import Execution
from docgen.models import Usage
from docgen.providers.azure import DraftResponse
from tests.test_azure_provider import draft
from tests.test_planning import configuration


def candidate(tokens: int | None = 10) -> DraftResponse:
    return DraftResponse(
        payload=draft(), response_id="resp-test", request_id=None,
        reported_model="test-model", model_version=None,
        usage=Usage(input_tokens=0, output_tokens=tokens, total_tokens=tokens)
        if tokens is not None else None,
    )


def settings(**limits: int) -> Config:
    data = configuration()
    data["generation"]["limits"] = limits
    return Config.model_validate(data)


def test_retry_after_is_honored_without_multiplying_transport_attempts() -> None:
    waits = []
    calls = 0
    execution = Execution(settings().generation, wait=waits.append)

    def flaky() -> DraftResponse:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ProviderError("rate_limited", "rate", retryable=True, retry_after_seconds=4)
        return candidate()

    assert execution.invoke(flaky).payload == draft()
    assert calls == 3
    assert waits == [4, 4]
    assert execution.summary()["requests"] == 3
    assert execution.summary()["unknown_outcomes"] == 2
    assert execution.summary()["total_tokens"] is None


@pytest.mark.parametrize("code", ["authentication", "authorization", "refusal", "model_drift"])
def test_terminal_errors_are_not_retried(code: str) -> None:
    execution = Execution(settings().generation)
    calls = 0

    def terminal() -> DraftResponse:
        nonlocal calls
        calls += 1
        raise ProviderError(code, "terminal")

    with pytest.raises(ProviderError) as failure:
        execution.invoke(terminal)
    assert failure.value.code == code
    assert calls == 1


def test_retry_exhaustion_request_budget_and_observed_token_stop() -> None:
    execution = Execution(settings(max_requests=2).generation, wait=lambda seconds: None)

    def fail() -> DraftResponse:
        raise ProviderError("provider_unavailable", "busy", retryable=True)

    with pytest.raises(ProviderError, match="request budget"):
        execution.invoke(fail)
    assert execution.summary()["requests"] == 2
    execution = Execution(settings(transport_attempts_per_candidate=2).generation,
                          wait=lambda seconds: None)
    with pytest.raises(ProviderError) as failure:
        execution.invoke(fail)
    assert failure.value.code == "provider_unavailable"
    assert execution.summary()["requests"] == 2
    execution = Execution(settings(max_observed_total_tokens=10).generation)
    execution.invoke(lambda: candidate(10))
    with pytest.raises(ProviderError, match="token budget"):
        execution.invoke(lambda: candidate(1))
    assert execution.summary()["observed_total_tokens"] == 10


def test_retry_deadline_and_late_success_are_explicit() -> None:
    now = [0.0]
    execution = Execution(
        settings(request_timeout_seconds=5).generation, clock=lambda: now[0],
        wait=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )

    def fail() -> DraftResponse:
        raise ProviderError("rate_limited", "rate", retryable=True, retry_after_seconds=10)

    with pytest.raises(ProviderError) as failure:
        execution.invoke(fail)
    assert failure.value.code == "deadline"
    assert execution.summary()["requests"] == 1

    def slow() -> DraftResponse:
        now[0] += 6
        return candidate()

    with pytest.raises(ProviderError) as failure:
        execution.invoke(slow)
    assert failure.value.code == "deadline"
    assert execution.summary()["observed_total_tokens"] == 10


def test_cancelled_work_does_not_schedule_and_jitter_is_seeded() -> None:
    execution = Execution(settings().generation)
    execution.cancel()
    with pytest.raises(ProviderError) as failure:
        execution.invoke(lambda: candidate())
    assert failure.value.code == "cancelled"
    assert execution.summary()["requests"] == 0
    waits = []
    for _ in range(2):
        observed = []
        executor = Execution(settings(transport_attempts_per_candidate=2).generation,
                             seed=7, wait=observed.append)
        with pytest.raises(ProviderError):
            executor.invoke(lambda: (_ for _ in ()).throw(
                ProviderError("timeout", "test", retryable=True)
            ))
        waits.append(observed)
    assert waits[0] == waits[1]
    assert len(waits[0]) == 1
    assert 0.8 <= waits[0][0] <= 1.2


def test_concurrent_map_is_bounded_and_consumed_in_input_order() -> None:
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    active = 0
    peak = 0
    execution = Execution(settings(concurrency=2).generation)

    def job(index: int) -> int:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=10)
        with lock:
            active -= 1
        return index

    jobs = [lambda index=index: job(index) for index in range(6)]
    assert list(execution.ordered(jobs)) == list(range(6))
    assert peak == 2


def test_inflight_overshoot_is_reported_and_resume_counts_are_preserved() -> None:
    execution = Execution(
        settings(concurrency=2, max_observed_total_tokens=15).generation,
        previous_requests=2, previous_tokens=3, previous_unknown=1,
    )
    barrier = threading.Barrier(2)

    def call() -> DraftResponse:
        barrier.wait(timeout=10)
        return candidate(10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(execution.invoke, call) for _ in range(2)]
        assert all(result.result().payload == draft() for result in results)
    summary = execution.summary()
    assert summary["requests"] == 4
    assert summary["observed_total_tokens"] == 23
    assert summary["token_overshoot"] == 8
    assert summary["unknown_outcomes"] == 1
    with pytest.raises(ProviderError):
        execution.invoke(lambda: candidate())


def test_early_close_or_job_error_cancels_unscheduled_work() -> None:
    execution = Execution(settings(concurrency=1).generation)
    jobs = [lambda: 1, lambda: 2]
    iterator = execution.ordered(jobs)
    assert next(iterator) == 1
    iterator.close()
    with pytest.raises(ProviderError, match="cancelled"):
        execution.invoke(lambda: candidate())
    execution = Execution(settings(concurrency=1).generation)
    with pytest.raises(ValueError, match="job failed"):
        list(execution.ordered([lambda: (_ for _ in ()).throw(ValueError("job failed"))]))
