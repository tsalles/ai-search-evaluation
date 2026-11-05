import random
import threading
import time
from collections import deque
from collections.abc import Callable, Generator, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Protocol

from pydantic import JsonValue

from docgen.config import GenerationConfig
from docgen.errors import ProviderError
from docgen.models import Usage


class UsageReport(Protocol):
    @property
    def usage(self) -> Usage | None: ...


class Execution:
    def __init__(
        self, config: GenerationConfig, *, seed: int = 0,
        previous_requests: int = 0, previous_tokens: int = 0, previous_unknown: int = 0,
        clock: Callable[[], float] = time.monotonic,
        wait: Callable[[float], object] | None = None,
    ) -> None:
        self.config = config
        self._requests = previous_requests
        self._tokens = previous_tokens
        self._unknown = previous_unknown
        self._clock = clock
        self._cancelled = threading.Event()
        self._wait = wait or self._cancelled.wait
        self._lock = threading.Lock()
        self._permit = threading.BoundedSemaphore(config.limits.concurrency)
        self._random = random.Random(seed)

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def stopped(self) -> bool:
        return self._cancelled.is_set()

    @property
    def request_count(self) -> int:
        with self._lock:
            return self._requests

    def _reserve(self) -> None:
        with self._lock:
            if self._cancelled.is_set():
                raise ProviderError("cancelled", "Execution was cancelled.")
            if self._requests >= self.config.request_limit:
                raise ProviderError("request_budget", "Model request budget is exhausted.")
            if self._tokens >= self.config.limits.max_observed_total_tokens:
                raise ProviderError("token_budget", "Observed model token budget is exhausted.")
            self._requests += 1

    def _record(self, usage: Usage | None) -> None:
        with self._lock:
            if usage is None or usage.total_tokens is None:
                self._unknown += 1
            else:
                self._tokens += usage.total_tokens

    def summary(self) -> dict[str, JsonValue]:
        with self._lock:
            return {
                "requests": self._requests, "observed_total_tokens": self._tokens,
                "total_tokens": None if self._unknown else self._tokens,
                "unknown_outcomes": self._unknown,
                "token_overshoot": max(
                    0, self._tokens - self.config.limits.max_observed_total_tokens
                ),
            }

    def invoke[T: UsageReport](self, call: Callable[[], T]) -> T:
        with self._permit:
            deadline = self._clock() + self.config.limits.request_timeout_seconds
            for attempt in range(self.config.limits.transport_attempts_per_candidate):
                if self._clock() >= deadline:
                    raise ProviderError("deadline", "Candidate transport deadline is exhausted.")
                self._reserve()
                accounted = False
                try:
                    result = call()
                except ProviderError as error:
                    self._record(error.usage)
                    accounted = True
                    if not error.retryable or attempt + 1 == (
                        self.config.limits.transport_attempts_per_candidate
                    ):
                        raise
                    with self._lock:
                        jitter = self._random.uniform(0.8, 1.2)
                    delay = (
                        error.retry_after_seconds if error.retry_after_seconds is not None
                        else 2**attempt * jitter
                    )
                    if delay >= deadline - self._clock():
                        raise ProviderError(
                            "deadline", "Retry delay exceeds the remaining transport deadline.",
                            usage=error.usage,
                        ) from None
                    self._wait(delay)
                else:
                    self._record(result.usage)
                    accounted = True
                    if self._clock() > deadline:
                        raise ProviderError(
                            "deadline", "Provider completed after the transport deadline.",
                            usage=result.usage,
                        )
                    return result
                finally:
                    if not accounted:
                        self._record(None)
        raise AssertionError("Validated attempt limits must allow an attempt.")

    def ordered[T](self, jobs: Iterable[Callable[[], T]]) -> Generator[T, None, None]:
        source = iter(jobs)
        pool = ThreadPoolExecutor(max_workers=self.config.limits.concurrency)
        pending: deque[Future[T]] = deque()
        finished = False
        try:
            for _ in range(self.config.limits.concurrency):
                try:
                    job = next(source)
                except StopIteration:
                    break
                pending.append(pool.submit(job))
            while pending:
                yield pending.popleft().result()
                if not self._cancelled.is_set():
                    try:
                        job = next(source)
                    except StopIteration:
                        continue
                    pending.append(pool.submit(job))
            finished = True
        finally:
            if not finished:
                self.cancel()
            for future in pending:
                future.cancel()
            pool.shutdown(wait=True, cancel_futures=True)
