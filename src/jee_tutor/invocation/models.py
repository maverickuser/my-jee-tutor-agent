from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TutorInvocationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str | None = None
    subject: str | None = None
    image_s3_prefix: str | None = None
    image_data_uri: str | None = None
    save_analysis_pdf: bool = True
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def require_exactly_one_image_payload(self) -> "TutorInvocationPayload":
        image_source_count = sum(bool(value) for value in [self.image_s3_prefix, self.image_data_uri])
        if image_source_count == 1:
            return self
        raise ValueError(
            "Send exactly one image input: image_s3_prefix or image_data_uri."
        )

    @property
    def resolved_question_context(self) -> str | None:
        return self.task

    def safe_trace_input(self) -> dict[str, Any]:
        return self.model_dump(
            exclude={
                "image_data_uri",
            }
        )


class TutorInvocationResponse(BaseModel):
    analysis: str
    message: str | None = None
    pdf_wait_minutes: int | None = None
    analysis_pdf_uri: str | None = None
    analysis_markdown_uri: str | None = None
    artifact_errors: list[str] = Field(default_factory=list)
    runtime_commit_sha: str | None = None


class ErrorResponse(BaseModel):
    error: str
    details: list[str] = Field(default_factory=list)
