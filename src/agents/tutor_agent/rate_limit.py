from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar


T = TypeVar("T")


class GeminiRateLimiter:
    def __init__(
        self,
        *,
        requests_per_minute: int = 5,
        max_attempts: int = 4,
        initial_backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
    ):
        self.min_interval_seconds = 60.0 / requests_per_minute
        self.max_attempts = max_attempts
        self.initial_backoff_seconds = initial_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.sleep = sleep
        self.monotonic = monotonic
        self.jitter = jitter
        self._lock = threading.Lock()
        self._next_allowed_at = 0.0

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        for attempt in range(1, self.max_attempts + 1):
            self._wait_for_slot()
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                if attempt == self.max_attempts or not is_retryable_rate_limit_error(exc):
                    raise
                self.sleep(self._backoff_seconds(attempt))

        raise RuntimeError("Gemini rate limiter exhausted without returning or raising.")

    def _wait_for_slot(self) -> None:
        with self._lock:
            now = self.monotonic()
            wait_seconds = max(0.0, self._next_allowed_at - now)
            self._next_allowed_at = max(now, self._next_allowed_at) + self.min_interval_seconds

        if wait_seconds:
            self.sleep(wait_seconds)

    def _backoff_seconds(self, attempt: int) -> float:
        exponential = self.initial_backoff_seconds * (2 ** (attempt - 1))
        jitter_seconds = self.jitter()
        return min(self.max_backoff_seconds, exponential + jitter_seconds)


def is_gemini_model(model: str) -> bool:
    return model.startswith("gemini/") or model.startswith("google/")


def is_retryable_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    status_code = getattr(exc, "status_code", None)
    return status_code == 429 or any(
        marker in text
        for marker in (
            "rate limit",
            "ratelimit",
            "resource_exhausted",
            "quota",
            "too many requests",
            "429",
        )
    )


gemini_rate_limiter = GeminiRateLimiter()
