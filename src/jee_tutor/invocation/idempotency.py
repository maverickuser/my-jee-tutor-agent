from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import threading
import time
from typing import Any, Callable


@dataclass
class IdempotencyClaim:
    status: str
    response: dict[str, Any] | None = None


@dataclass
class _IdempotencyEntry:
    fingerprint: str
    created_at: float
    response: dict[str, Any] | None = None


class InvocationIdempotencyStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = 600.0,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.ttl_seconds = ttl_seconds
        self.monotonic = monotonic
        self._entries: dict[str, _IdempotencyEntry] = {}
        self._lock = threading.Lock()

    def claim(self, key: str, payload: dict[str, Any]) -> IdempotencyClaim:
        fingerprint = self._fingerprint(payload)
        with self._lock:
            self._remove_expired_entries()
            entry = self._entries.get(key)
            if entry is None:
                self._entries[key] = _IdempotencyEntry(
                    fingerprint=fingerprint,
                    created_at=self.monotonic(),
                )
                return IdempotencyClaim(status="acquired")
            if entry.fingerprint != fingerprint:
                return IdempotencyClaim(status="conflict")
            if entry.response is None:
                return IdempotencyClaim(status="in_progress")
            return IdempotencyClaim(status="completed", response=deepcopy(entry.response))

    def complete(self, key: str, response: dict[str, Any]) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.response = deepcopy(response)

    def abandon(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def _remove_expired_entries(self) -> None:
        now = self.monotonic()
        expired = [
            key
            for key, entry in self._entries.items()
            if now - entry.created_at >= self.ttl_seconds
        ]
        for key in expired:
            self._entries.pop(key, None)

    @staticmethod
    def _fingerprint(payload: dict[str, Any]) -> str:
        canonical_payload = {
            key: value for key, value in payload.items() if key != "idempotency_key"
        }
        encoded = json.dumps(
            canonical_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


invocation_idempotency_store = InvocationIdempotencyStore()
