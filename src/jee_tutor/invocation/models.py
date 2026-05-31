from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from jee_tutor.agent.observability import EvaluationScore
from jee_tutor.invocation.image_inputs import ImageMediaPayload


class TutorInvocationPayload(BaseModel):
    task: str | None = None
    attempt_id: str | None = None
    email: str | None = None
    user_name: str | None = None
    subject: str | None = None
    s3_bucket: str | None = None
    s3_prefix: str | None = None
    s3_uri: str | None = None
    image_count: int | None = None
    source: str | None = None
    image_data_uri: str | None = None
    image_data_uris: list[str] = Field(default_factory=list)
    image_folder: str | None = None
    image_s3_uri: str | None = None
    image_s3_prefix: str | None = None
    media: ImageMediaPayload | None = None
    question_context: str | None = None
    prompt: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    evaluation_scores: list[EvaluationScore] = Field(default_factory=list)
    analysis_mode: Literal["baseline", "graph_grounded", "comparison"] = "comparison"
    save_analysis_pdf: bool = True
    analysis_pdf_s3_uri: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_agentcore_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        if normalized.get("s3_uri") and not normalized.get("image_s3_uri"):
            normalized["image_s3_uri"] = normalized["s3_uri"]

        if (
            normalized.get("s3_bucket")
            and normalized.get("s3_prefix")
            and not normalized.get("image_s3_prefix")
        ):
            normalized["image_s3_prefix"] = cls._s3_uri(
                normalized["s3_bucket"],
                normalized["s3_prefix"],
            )

        return normalized

    @model_validator(mode="after")
    def require_image_payload(self) -> "TutorInvocationPayload":
        if (
            self.image_data_uri
            or self.image_data_uris
            or self.image_folder
            or self.image_s3_uri
            or self.image_s3_prefix
            or (self.media and self.media.to_data_uri())
        ):
            return self
        raise ValueError(
            "Missing image payload. Send image_folder, image_s3_uri, image_s3_prefix, "
            "image_data_uris, image_data_uri, or media with type=image, format, and base64 data."
        )

    @property
    def resolved_question_context(self) -> str | None:
        return self.question_context or self.prompt or self.task

    def safe_trace_input(self) -> dict[str, Any]:
        return self.model_dump(
            exclude={
                "email",
                "image_data_uri",
                "image_data_uris",
                "image_folder",
                "media",
                "user_name",
            }
        )

    @staticmethod
    def _s3_uri(bucket: str, key: str) -> str:
        return f"s3://{bucket.strip('/')}/{key.lstrip('/')}"


class TutorInvocationResponse(BaseModel):
    analysis: str
    baseline_analysis: str | None = None
    graph_grounded_analysis: str | None = None
    graph_validation: dict[str, Any] | None = None
    analysis_pdf_uri: str | None = None
    analysis_markdown_uri: str | None = None
    artifact_errors: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str
    details: list[str] = Field(default_factory=list)
