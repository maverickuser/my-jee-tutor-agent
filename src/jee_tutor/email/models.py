from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EmailDeliveryStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    QUEUED = "queued"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EmailDeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_id: str = Field(min_length=1)
    recipient_email: str = Field(min_length=3)
    pdf_uri: str = Field(min_length=1)
    invocation_id: str | None = None
    idempotency_key: str | None = None
    subject_key: str = Field(min_length=1)
    body_template_key: str = Field(min_length=1)
    from_address_key: str = Field(min_length=1)


class EmailDeliveryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_id: str = Field(min_length=1)
    recipient_email: str = Field(min_length=3)
    pdf_uri: str = Field(min_length=1)
    invocation_id: str | None = None
    idempotency_key: str | None = None
    subject_key: str = Field(min_length=1)
    body_template_key: str = Field(min_length=1)
    from_address_key: str = Field(min_length=1)


class EmailDeliveryOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: EmailDeliveryStatus
    delivery_id: str | None = None
    error: str | None = None
