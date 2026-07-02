from __future__ import annotations

import atexit
import json
import logging
import os
import queue
import re
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

import boto3


SENSITIVE_PATTERN = re.compile(
    r"(data:image/[^;]+;base64,[A-Za-z0-9+/=]+|https?://\S*[?&](?:X-Amz-|token=)\S+|"
    r"(?:api[_-]?key|license[_-]?key|secret|authorization)\s*[=:]\s*\S+|"
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b)",
    re.IGNORECASE,
)


def redact_log_value(value: str, max_length: int = 2000) -> str:
    return SENSITIVE_PATTERN.sub("[redacted]", value)[:max_length]


@dataclass(frozen=True)
class NewRelicLogConfig:
    enabled: bool
    secret_arn: str
    region: str = "US"
    queue_capacity: int = 1000
    batch_size: int = 100
    send_timeout_seconds: float = 2.0
    retry_count: int = 2
    shutdown_flush_seconds: float = 2.0

    @classmethod
    def from_environment(cls) -> "NewRelicLogConfig":
        enabled = os.getenv("NEW_RELIC_LOG_ENABLED", "false").lower() == "true"
        return cls(
            enabled=enabled,
            secret_arn=os.getenv("NEW_RELIC_LICENSE_KEY_SECRET_ARN", ""),
            region=os.getenv("NEW_RELIC_REGION", "US").upper(),
            queue_capacity=int(os.getenv("NEW_RELIC_LOG_QUEUE_CAPACITY", "1000")),
            batch_size=int(os.getenv("NEW_RELIC_LOG_BATCH_SIZE", "100")),
            send_timeout_seconds=float(os.getenv("NEW_RELIC_LOG_SEND_TIMEOUT", "2")),
            retry_count=int(os.getenv("NEW_RELIC_LOG_RETRY_COUNT", "2")),
            shutdown_flush_seconds=float(os.getenv("NEW_RELIC_LOG_SHUTDOWN_TIMEOUT", "2")),
        )


class NewRelicLogHandler(logging.Handler):
    """Non-blocking request-thread handler with a dedicated transport worker."""

    def __init__(
        self,
        config: NewRelicLogConfig,
        *,
        license_key: str,
        sender: Callable[[list[dict[str, Any]], str, float], None] | None = None,
    ):
        super().__init__()
        self.config = config
        self.license_key = license_key
        self.sender = sender or self._send
        self.records: queue.Queue[dict[str, Any]] = queue.Queue(config.queue_capacity)
        self.stop_event = threading.Event()
        self.dropped_count = 0
        self.delivery_failure_count = 0
        self._last_warning = 0.0
        self.worker = threading.Thread(
            target=self._worker,
            name="new-relic-log-worker",
            daemon=True,
        )
        self.worker.start()
        atexit.register(self.close)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = {
                "timestamp": int(record.created * 1000),
                "severity": record.levelname,
                "service": getattr(record, "service_name", "jee-tutor-agent"),
                "environment": os.getenv("APP_ENVIRONMENT", "unknown"),
                "commit_sha": os.getenv("JEE_TUTOR_GIT_SHA", "unknown"),
                "logger": record.name,
                "message": redact_log_value(record.getMessage()),
            }
            for name in ("correlation_id", "trace_id", "workflow_stage", "terminal_outcome"):
                value = getattr(record, name, None)
                if value:
                    payload[name] = redact_log_value(str(value), 200)
            self.records.put_nowait(payload)
        except queue.Full:
            self.dropped_count += 1
            self._fallback_warning("new_relic_log_queue_full")
        except Exception:
            self.delivery_failure_count += 1
            self._fallback_warning("new_relic_log_serialization_failed")

    def _worker(self) -> None:
        while not self.stop_event.is_set() or not self.records.empty():
            batch = self._next_batch()
            if not batch:
                continue
            for attempt in range(self.config.retry_count + 1):
                try:
                    self.sender(batch, self.license_key, self.config.send_timeout_seconds)
                    break
                except Exception:
                    if attempt == self.config.retry_count:
                        self.delivery_failure_count += len(batch)
                        self._fallback_warning("new_relic_log_delivery_failed")

    def _next_batch(self) -> list[dict[str, Any]]:
        try:
            first = self.records.get(timeout=0.1)
        except queue.Empty:
            return []
        batch = [first]
        while len(batch) < self.config.batch_size:
            try:
                batch.append(self.records.get_nowait())
            except queue.Empty:
                break
        return batch

    def _send(
        self,
        records: list[dict[str, Any]],
        license_key: str,
        timeout: float,
    ) -> None:
        host = "log-api.eu.newrelic.com" if self.config.region == "EU" else "log-api.newrelic.com"
        request = urllib.request.Request(
            f"https://{host}/log/v1",
            data=json.dumps(records, separators=(",", ":")).encode(),
            headers={"Api-Key": license_key, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"New Relic Log API returned HTTP {response.status}.")

    def _fallback_warning(self, category: str) -> None:
        now = time.monotonic()
        if now - self._last_warning >= 60:
            self._last_warning = now
            sys.stderr.write(
                f"{category} dropped={self.dropped_count} "
                f"delivery_failures={self.delivery_failure_count}\n"
            )

    def close(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        self.worker.join(timeout=self.config.shutdown_flush_seconds)
        super().close()


def build_new_relic_handler(
    config: NewRelicLogConfig | None = None,
    *,
    secrets_client: Any = None,
    sender: Callable[[list[dict[str, Any]], str, float], None] | None = None,
) -> NewRelicLogHandler | None:
    resolved = config or NewRelicLogConfig.from_environment()
    if not resolved.enabled or not resolved.secret_arn:
        return None
    try:
        client = secrets_client or boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=resolved.secret_arn)
        key = response.get("SecretString", "").strip()
        if not key:
            raise ValueError("New Relic secret is empty.")
        return NewRelicLogHandler(resolved, license_key=key, sender=sender)
    except Exception as exc:
        sys.stderr.write(f"new_relic_logging_disabled initialization_error={type(exc).__name__}\n")
        return None
