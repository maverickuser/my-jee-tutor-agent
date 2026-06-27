from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar


T = TypeVar("T")
logger = logging.getLogger(__name__)

DEFAULT_GEMINI_REQUESTS_PER_MINUTE = 100
RETRYABLE_HTTP_STATUS_CODES = frozenset({429, 500, 503})


class GeminiRateLimiter:
    def __init__(
        self,
        *,
        requests_per_minute: int = DEFAULT_GEMINI_REQUESTS_PER_MINUTE,
        max_attempts: int = 2,
        initial_backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 10.0,
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
        return self.call_attempts(lambda _attempt: func(*args, **kwargs))

    def call_attempts(self, func: Callable[[int], T]) -> T:
        for attempt in range(1, self.max_attempts + 1):
            self._wait_for_slot()
            try:
                return func(attempt)
            except Exception as exc:
                retryable = is_retryable_gemini_error(exc)
                status_code = exception_status_code(exc)
                if attempt == self.max_attempts or not retryable:
                    logger.error(
                        "llm_attempt_failed attempt=%s max_attempts=%s "
                        "status_code=%s retryable=%s error_type=%s error=%s",
                        attempt,
                        self.max_attempts,
                        status_code,
                        retryable,
                        exc.__class__.__name__,
                        exc or "[no message]",
                    )
                    raise
                backoff_seconds = self._backoff_seconds(attempt)
                logger.warning(
                    "gemini_retryable_error attempt=%s max_attempts=%s backoff_seconds=%.2f "
                    "status_code=%s error_type=%s error=%s",
                    attempt,
                    self.max_attempts,
                    backoff_seconds,
                    status_code,
                    exc.__class__.__name__,
                    exc or "[no message]",
                )
                self.sleep(backoff_seconds)

        raise RuntimeError(  # pragma: no cover - loop always returns or raises
            "Gemini rate limiter exhausted without returning or raising."
        )

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


def is_retryable_gemini_error(exc: Exception) -> bool:
    return (
        exception_status_code(exc) in RETRYABLE_HTTP_STATUS_CODES
        or is_retryable_timeout_error(exc)
    )


def is_retryable_timeout_error(exc: Exception) -> bool:
    for current in _exception_chain(exc):
        if isinstance(current, TimeoutError):
            return True
        class_name = current.__class__.__name__.lower()
        message = str(current).lower()
        if "timeout" in class_name or "timed out" in message or "timeout" in message:
            return True
    return False


def exception_status_code(exc: Exception) -> int | None:
    for current in _exception_chain(exc):
        status_code = getattr(current, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        response = getattr(current, "response", None)
        response_status = getattr(response, "status_code", None)
        if isinstance(response_status, int):
            return response_status
    return None


def _exception_chain(exc: Exception):
    current: BaseException | None = exc
    seen: set[int] = set()
    while isinstance(current, Exception) and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


gemini_rate_limiter = GeminiRateLimiter()
