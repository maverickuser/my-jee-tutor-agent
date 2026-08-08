"""Authenticate CD requests and resolve their execution profile."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import hmac
import json
import os
import time
from typing import Any, Protocol

import boto3

from jee_tutor.model_routing import ExecutionProfile


EXECUTION_PROFILE_HEADER = "X-JEE-Execution-Profile"
CD_TIMESTAMP_HEADER = "X-JEE-CD-Timestamp"
CD_RUN_ID_HEADER = "X-JEE-CD-Run-ID"
CD_SIGNATURE_HEADER = "X-JEE-CD-Signature"
CD_HEADER_NAMES = (
    EXECUTION_PROFILE_HEADER,
    CD_TIMESTAMP_HEADER,
    CD_RUN_ID_HEADER,
    CD_SIGNATURE_HEADER,
)
CD_SIGNATURE_VERSION = "v1"
DEFAULT_CD_SIGNATURE_MAX_AGE_SECONDS = 300


class ExecutionProfileAuthorizationError(ValueError):
    """Raised when a caller attempts an unauthenticated CD invocation."""


class CdSecretProvider(Protocol):
    def __call__(self) -> str: ...


@dataclass(frozen=True)
class CdExecutionRequestSigner:
    """Create short-lived CD headers without exposing model choice in payloads."""

    secret: str
    run_id: str
    now: Callable[[], float] = time.time

    def headers(self, payload: Mapping[str, Any]) -> dict[str, str]:
        return build_cd_request_headers(
            secret=self.secret,
            run_id=self.run_id,
            payload=payload,
            timestamp=int(self.now()),
        )


def canonical_payload_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


def canonical_cd_signature_input(
    *,
    timestamp: int,
    run_id: str,
    payload_hash: str,
) -> bytes:
    return (
        f"{CD_SIGNATURE_VERSION}\n{ExecutionProfile.CD.value}\n{timestamp}\n"
        f"{run_id}\n{payload_hash}"
    ).encode("utf-8")


def sign_cd_request(
    *,
    secret: str,
    timestamp: int,
    run_id: str,
    payload: Mapping[str, Any],
) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        canonical_cd_signature_input(
            timestamp=timestamp,
            run_id=run_id,
            payload_hash=payload_sha256(payload),
        ),
        hashlib.sha256,
    ).hexdigest()


def build_cd_request_headers(
    *,
    secret: str,
    run_id: str,
    payload: Mapping[str, Any],
    timestamp: int | None = None,
) -> dict[str, str]:
    effective_timestamp = int(time.time()) if timestamp is None else timestamp
    return {
        EXECUTION_PROFILE_HEADER: ExecutionProfile.CD.value,
        CD_TIMESTAMP_HEADER: str(effective_timestamp),
        CD_RUN_ID_HEADER: run_id,
        CD_SIGNATURE_HEADER: sign_cd_request(
            secret=secret,
            timestamp=effective_timestamp,
            run_id=run_id,
            payload=payload,
        ),
    }


@dataclass(frozen=True)
class CdExecutionProfileAuthenticator:
    secret_provider: CdSecretProvider
    now: Callable[[], float] = time.time
    max_age_seconds: int = DEFAULT_CD_SIGNATURE_MAX_AGE_SECONDS

    def resolve(
        self,
        *,
        payload: Mapping[str, Any],
        request_headers: Mapping[str, str] | None,
    ) -> ExecutionProfile:
        headers = _normalized_headers(request_headers)
        required_keys = {name.casefold() for name in CD_HEADER_NAMES}
        supplied_keys = required_keys.intersection(headers)
        if not supplied_keys:
            return ExecutionProfile.LIVE
        if supplied_keys != required_keys:
            raise ExecutionProfileAuthorizationError(
                "Incomplete CD execution-profile authentication headers."
            )

        profile = headers[EXECUTION_PROFILE_HEADER.casefold()].strip().casefold()
        if profile != ExecutionProfile.CD.value:
            raise ExecutionProfileAuthorizationError("Unsupported execution profile.")

        timestamp = _parse_timestamp(headers[CD_TIMESTAMP_HEADER.casefold()])
        if abs(self.now() - timestamp) > self.max_age_seconds:
            raise ExecutionProfileAuthorizationError(
                "CD execution-profile authentication has expired."
            )

        run_id = headers[CD_RUN_ID_HEADER.casefold()].strip()
        signature = headers[CD_SIGNATURE_HEADER.casefold()].strip().casefold()
        if not run_id or not _is_sha256_hex(signature):
            raise ExecutionProfileAuthorizationError(
                "Malformed CD execution-profile authentication headers."
            )

        expected = sign_cd_request(
            secret=self.secret_provider(),
            timestamp=timestamp,
            run_id=run_id,
            payload=payload,
        )
        if not hmac.compare_digest(signature, expected):
            raise ExecutionProfileAuthorizationError(
                "Invalid CD execution-profile authentication signature."
            )
        return ExecutionProfile.CD


def resolve_execution_profile(
    *,
    payload: Mapping[str, Any],
    request_headers: Mapping[str, str] | None,
    authenticator: CdExecutionProfileAuthenticator | None = None,
) -> ExecutionProfile:
    return (authenticator or default_cd_authenticator()).resolve(
        payload=payload,
        request_headers=request_headers,
    )


@lru_cache(maxsize=1)
def default_cd_authenticator() -> CdExecutionProfileAuthenticator:
    return CdExecutionProfileAuthenticator(secret_provider=_load_cd_execution_secret)


@lru_cache(maxsize=1)
def _load_cd_execution_secret() -> str:
    secret_arn = os.getenv("CD_EXECUTION_HMAC_SECRET_ARN", "").strip()
    if not secret_arn:
        raise ExecutionProfileAuthorizationError(
            "CD execution-profile authentication is not configured."
        )
    return load_cd_execution_secret(secret_arn)


def load_cd_execution_secret(
    secret_id: str,
    *,
    secrets_client: Any | None = None,
) -> str:
    try:
        response = (secrets_client or boto3.client("secretsmanager")).get_secret_value(
            SecretId=secret_id
        )
    except Exception as exc:
        raise ExecutionProfileAuthorizationError(
            "CD execution-profile authentication is unavailable."
        ) from exc
    secret = response.get("SecretString", "")
    if not isinstance(secret, str) or not secret:
        raise ExecutionProfileAuthorizationError(
            "CD execution-profile authentication is not configured."
        )
    return secret


@contextmanager
def attach_agentcore_cd_headers(
    client: Any,
    headers: Mapping[str, str],
) -> Iterator[None]:
    """Inject allowlisted headers before Botocore applies its SigV4 signature."""

    event_name = "before-sign.bedrock-agentcore.InvokeAgentRuntime"

    def add_headers(request: Any, **_kwargs: Any) -> None:
        for name, value in headers.items():
            request.headers[name] = value

    client.meta.events.register_first(event_name, add_headers)
    try:
        yield
    finally:
        client.meta.events.unregister(event_name, add_headers)


def _normalized_headers(
    request_headers: Mapping[str, str] | None,
) -> dict[str, str]:
    if not request_headers:
        return {}
    return {
        str(name).casefold(): str(value)
        for name, value in request_headers.items()
    }


def _parse_timestamp(value: str) -> int:
    try:
        return int(value.strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise ExecutionProfileAuthorizationError(
            "Malformed CD execution-profile authentication timestamp."
        ) from exc


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "CD_HEADER_NAMES",
    "CD_RUN_ID_HEADER",
    "CD_SIGNATURE_HEADER",
    "CD_TIMESTAMP_HEADER",
    "EXECUTION_PROFILE_HEADER",
    "CdExecutionRequestSigner",
    "CdExecutionProfileAuthenticator",
    "ExecutionProfileAuthorizationError",
    "attach_agentcore_cd_headers",
    "build_cd_request_headers",
    "canonical_payload_bytes",
    "load_cd_execution_secret",
    "payload_sha256",
    "resolve_execution_profile",
    "sign_cd_request",
]
