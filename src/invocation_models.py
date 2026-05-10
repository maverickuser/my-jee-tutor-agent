from typing import Any

from pydantic import BaseModel, Field, model_validator

from agents.tutor_agent.observability import EvaluationScore
from image_inputs import ImageMediaPayload


class TutorInvocationPayload(BaseModel):
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
        return self.question_context or self.prompt

    def safe_trace_input(self) -> dict[str, Any]:
        return self.model_dump(
            exclude={"image_data_uri", "image_data_uris", "image_folder", "media"}
        )


class TutorInvocationResponse(BaseModel):
    analysis: str


class ErrorResponse(BaseModel):
    error: str
    details: list[str] = Field(default_factory=list)
