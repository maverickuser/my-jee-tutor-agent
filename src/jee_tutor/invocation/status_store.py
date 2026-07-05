from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from typing import Any, Protocol

import boto3

from jee_tutor.invocation.models import (
    AgentInvocationRecord,
    AgentInvocationStatus,
    AgentLLMCallRecord,
)


logger = logging.getLogger(__name__)


class InvocationStatusStore(Protocol):
    def upsert_invocation(self, record: AgentInvocationRecord) -> None: ...

    def update_invocation(
        self,
        invocation_id: str,
        **fields: Any,
    ) -> None: ...

    def append_llm_call(self, invocation_id: str, record: AgentLLMCallRecord) -> None: ...


class NullInvocationStatusStore:
    def upsert_invocation(self, record: AgentInvocationRecord) -> None:
        return None

    def update_invocation(self, invocation_id: str, **fields: Any) -> None:
        return None

    def append_llm_call(self, invocation_id: str, record: AgentLLMCallRecord) -> None:
        return None


@dataclass(frozen=True)
class InvocationStatusConfig:
    table_name: str = ""
    region: str = "ap-south-1"
    enabled: bool = False

    @classmethod
    def from_environment(cls) -> "InvocationStatusConfig":
        table_name = os.getenv("INVOCATION_STATUS_TABLE_NAME", "").strip()
        enabled_value = os.getenv("INVOCATION_STATUS_ENABLED", "true").strip().lower()
        enabled = enabled_value in {"1", "true", "yes", "on"} and bool(table_name)
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-south-1"
        return cls(table_name=table_name, region=region, enabled=enabled)


class DynamoDbInvocationStatusStore:
    def __init__(self, *, table_name: str, region: str):
        self.table_name = table_name
        self.region = region
        self._table = None

    @classmethod
    def from_environment(cls) -> InvocationStatusStore:
        config = InvocationStatusConfig.from_environment()
        if not config.enabled:
            return NullInvocationStatusStore()
        return cls(table_name=config.table_name, region=config.region)

    def upsert_invocation(self, record: AgentInvocationRecord) -> None:
        table = self._table_client()
        values: dict[str, Any] = {
            ":status": record.status.value,
            ":updated_at": record.updated_at,
            ":image_count": record.image_count,
        }
        names: dict[str, str] = {
            "#status": "status",
            "#updated_at": "updated_at",
            "#image_count": "image_count",
        }
        update_parts = [
            "#status = :status",
            "#updated_at = :updated_at",
            "#image_count = :image_count",
        ]
        set_if_not_none = {
            "idempotency_key": record.idempotency_key,
            "status_reason": record.status_reason,
            "subject": record.subject,
            "recipient_email": record.recipient_email,
            "runtime_commit_sha": record.runtime_commit_sha,
            "analysis_pdf_uri": record.analysis_pdf_uri,
            "email_delivery_id": record.email_delivery_id,
            "email_status": record.email_status,
            "email_error": record.email_error,
            "error_type": record.error_type,
            "error_message": record.error_message,
            "completed_at": record.completed_at,
        }
        if record.created_at:
            values[":created_at"] = record.created_at
            update_parts.append("created_at = if_not_exists(created_at, :created_at)")
        for field_name, field_value in set_if_not_none.items():
            if field_value is None:
                continue
            placeholder = f":{field_name}"
            names[f"#{field_name}"] = field_name
            values[placeholder] = field_value
            update_parts.append(f"#{field_name} = {placeholder}")

        table.update_item(
            Key={"invocation_id": record.invocation_id},
            UpdateExpression="SET " + ", ".join(update_parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def update_invocation(self, invocation_id: str, **fields: Any) -> None:
        if not fields:
            return None
        table = self._table_client()
        values: dict[str, Any] = {":updated_at": _utc_now()}
        names: dict[str, str] = {"#updated_at": "updated_at"}
        set_parts = ["#updated_at = :updated_at"]
        for field_name, field_value in fields.items():
            if field_value is None:
                continue
            placeholder = f":{field_name}"
            names[f"#{field_name}"] = field_name
            values[placeholder] = field_value
            set_parts.append(f"#{field_name} = {placeholder}")
        if len(set_parts) == 1:
            return None
        table.update_item(
            Key={"invocation_id": invocation_id},
            UpdateExpression="SET " + ", ".join(set_parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def append_llm_call(self, invocation_id: str, record: AgentLLMCallRecord) -> None:
        table = self._table_client()
        call = record.model_dump(exclude_none=True)
        table.update_item(
            Key={"invocation_id": invocation_id},
            UpdateExpression=(
                "SET llm_calls = list_append(if_not_exists(llm_calls, :empty_calls), :call), "
                "updated_at = :updated_at"
            ),
            ExpressionAttributeValues={
                ":empty_calls": [],
                ":call": [call],
                ":updated_at": _utc_now(),
            },
        )

    def _table_client(self):
        if self._table is None:
            self._table = boto3.resource("dynamodb", region_name=self.region).Table(
                self.table_name
            )
        return self._table


def build_invocation_status_store() -> InvocationStatusStore:
    return DynamoDbInvocationStatusStore.from_environment()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_agent_invocation_record(
    *,
    invocation_id: str,
    idempotency_key: str | None,
    status: AgentInvocationStatus,
    image_count: int,
    subject: str | None = None,
    recipient_email: str | None = None,
    status_reason: str | None = None,
    runtime_commit_sha: str | None = None,
    analysis_pdf_uri: str | None = None,
    email_delivery_id: str | None = None,
    email_status: str | None = None,
    email_error: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    completed_at: str | None = None,
    llm_calls: list[Mapping[str, Any]] | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> AgentInvocationRecord:
    now = _utc_now()
    return AgentInvocationRecord(
        invocation_id=invocation_id,
        idempotency_key=idempotency_key,
        status=status,
        status_reason=status_reason,
        subject=subject,
        image_count=image_count,
        recipient_email=recipient_email,
        created_at=created_at or now,
        updated_at=updated_at or now,
        completed_at=completed_at,
        runtime_commit_sha=runtime_commit_sha,
        analysis_pdf_uri=analysis_pdf_uri,
        email_delivery_id=email_delivery_id,
        email_status=email_status,
        email_error=email_error,
        error_type=error_type,
        error_message=error_message,
        llm_calls=[AgentLLMCallRecord.model_validate(call) for call in (llm_calls or [])],
    )
