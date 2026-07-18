from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jee_tutor.privacy import redact_student_metadata


class TutorInvocationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str | None = None
    subject: str | None = None
    image_s3_prefix: str | None = None
    image_data_uri: str | None = None
    recipient_email: str | None = None
    save_analysis_pdf: bool = True
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_recipient_email(self) -> "TutorInvocationPayload":
        if self.recipient_email is None:
            return self

        recipient_email = self.recipient_email.strip()
        if not recipient_email:
            raise ValueError("recipient_email must not be blank.")
        if " " in recipient_email or recipient_email.count("@") != 1:
            raise ValueError("recipient_email must be a valid email address.")
        local_part, domain = recipient_email.split("@", 1)
        if not local_part or not domain or "." not in domain:
            raise ValueError("recipient_email must be a valid email address.")
        self.recipient_email = recipient_email
        return self

    @model_validator(mode="after")
    def require_exactly_one_image_payload(self) -> "TutorInvocationPayload":
        image_source_count = sum(
            bool(value) for value in [self.image_s3_prefix, self.image_data_uri]
        )
        if image_source_count == 1:
            if self.recipient_email and not self.image_s3_prefix:
                raise ValueError(
                    "recipient_email requires image_s3_prefix so the PDF can be stored in S3."
                )
            return self
        raise ValueError("Send exactly one image input: image_s3_prefix or image_data_uri.")

    @property
    def resolved_question_context(self) -> str | None:
        return self.task

    @property
    def should_write_analysis_pdf(self) -> bool:
        return self.save_analysis_pdf or self.recipient_email is not None

    def safe_trace_input(self) -> dict[str, Any]:
        trace_input = self.model_dump(
            exclude={
                "image_data_uri",
                "recipient_email",
            }
        )
        return redact_student_metadata(trace_input)


class TutorInvocationResponse(BaseModel):
    analysis: str
    message: str | None = None
    pdf_wait_minutes: int | None = None
    analysis_pdf_uri: str | None = None
    analysis_markdown_uri: str | None = None
    diagnosis_report_id: str | None = None
    diagnosis_json_uri: str | None = None
    artifact_errors: list[str] = Field(default_factory=list)
    email_status: str = "not_requested"
    email_delivery_id: str | None = None
    email_error: str | None = None
    runtime_commit_sha: str | None = None


class ErrorResponse(BaseModel):
    error: str
    details: list[str] = Field(default_factory=list)
    runtime_commit_sha: str | None = None


class AgentInvocationStatus(StrEnum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REPLAYED = "REPLAYED"
    BLOCKED = "BLOCKED"


class AgentLLMCallStatus(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRIED = "RETRIED"


class AgentLLMCallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_call_id: str = Field(min_length=1)
    batch_index: int = Field(ge=0)
    batch_size: int | None = Field(default=None, ge=0)
    model: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    status: AgentLLMCallStatus
    attempt_number: int = Field(ge=1)
    started_at: str
    ended_at: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    error_type: str | None = None
    error_message: str | None = None
    response_summary: str | None = None


class AgentInvocationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invocation_id: str = Field(min_length=1)
    idempotency_key: str | None = None
    status: AgentInvocationStatus
    status_reason: str | None = None
    subject: str | None = None
    image_count: int = Field(ge=0)
    recipient_email: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None
    runtime_commit_sha: str | None = None
    analysis_pdf_uri: str | None = None
    email_delivery_id: str | None = None
    email_status: str | None = None
    email_error: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    llm_calls: list[AgentLLMCallRecord] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
