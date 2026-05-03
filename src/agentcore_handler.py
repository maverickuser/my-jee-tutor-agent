import base64
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator

from agents.tutor_agent import run_tutor_workflow
from agents.tutor_agent.guardrails import RuntimeGuardrail
from agents.tutor_agent.observability import EvaluationScore, LangfuseObservability


SUPPORTED_IMAGE_FORMATS = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".webp": "webp",
}


class ImageMediaPayload(BaseModel):
    type: str
    format: str
    data: str

    def to_data_uri(self) -> str | None:
        if self.type != "image":
            return None
        return f"data:image/{self.format};base64,{self.data}"


class TutorInvocationPayload(BaseModel):
    image_data_uri: str | None = None
    image_data_uris: list[str] = Field(default_factory=list)
    image_folder: str | None = None
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
        if self.image_data_uri or self.image_data_uris or self.image_folder or self.image_from_media:
            return self
        raise ValueError(
            "Missing image payload. Send image_folder, image_data_uris, image_data_uri, "
            "or media with type=image, format, and base64 data."
        )

    @property
    def image_from_media(self) -> str | None:
        if not self.media:
            return None
        return self.media.to_data_uri()

    @property
    def resolved_image_data_uri(self) -> str:
        return self.image_data_uri or self.image_from_media or ""

    @property
    def resolved_image_data_uris(self) -> list[str]:
        image_data_uris = list(self.image_data_uris)
        if self.image_data_uri:
            image_data_uris.append(self.image_data_uri)
        if self.image_from_media:
            image_data_uris.append(self.image_from_media)
        if self.image_folder:
            image_data_uris.extend(_image_folder_data_uris(self.image_folder))
        return image_data_uris

    @property
    def resolved_question_context(self) -> str | None:
        return self.question_context or self.prompt


class TutorInvocationResponse(BaseModel):
    analysis: str


class ErrorResponse(BaseModel):
    error: str
    details: list[str] = Field(default_factory=list)


def validate_tutor_invocation(payload: dict[str, Any]) -> TutorInvocationPayload:
    return TutorInvocationPayload.model_validate(payload)


def _image_folder_data_uris(image_folder: str) -> list[str]:
    folder = Path(image_folder).expanduser()
    if not folder.is_dir():
        raise ValueError(f"Image folder does not exist or is not a directory: {image_folder}")

    image_paths = sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_FORMATS
    )
    if not image_paths:
        supported = ", ".join(sorted(SUPPORTED_IMAGE_FORMATS))
        raise ValueError(f"Image folder contains no supported images ({supported}): {image_folder}")

    return [
        _image_file_data_uri(path, SUPPORTED_IMAGE_FORMATS[path.suffix.lower()])
        for path in image_paths
    ]


def _image_file_data_uri(path: Path, image_format: str) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/{image_format};base64,{encoded}"


def handle_tutor_invocation(payload: dict[str, Any]) -> dict[str, Any]:
    observability = LangfuseObservability()
    guardrail = RuntimeGuardrail()
    try:
        invocation = validate_tutor_invocation(payload)
    except ValidationError as exc:
        return ErrorResponse(
            error="Invalid tutor invocation payload.",
            details=[error["msg"] for error in exc.errors()],
        ).model_dump()
    try:
        image_data_uris = invocation.resolved_image_data_uris
    except ValueError as exc:
        return ErrorResponse(
            error="Invalid tutor invocation payload.",
            details=[str(exc)],
        ).model_dump()

    with observability.invocation_span(
        input_payload=invocation.model_dump(
            exclude={"image_data_uri", "image_data_uris", "image_folder", "media"}
        ),
        user_id=invocation.user_id,
        session_id=invocation.session_id,
        tags=invocation.tags,
        metadata=invocation.metadata,
    ) as span:
        input_guardrail = guardrail.check_input(
            question_context=invocation.resolved_question_context,
            image_data_uris=image_data_uris,
        )
        if not input_guardrail.allowed:
            response = ErrorResponse(
                error=input_guardrail.message or "Tutor invocation blocked by runtime guardrail.",
                details=[input_guardrail.action_reason]
                if input_guardrail.action_reason
                else [],
            ).model_dump()
            if span:
                span.update(output=response)
            observability.flush()
            return response

        analysis = run_tutor_workflow(
            image_data_uris=image_data_uris,
            question_context=invocation.resolved_question_context,
        )
        output_guardrail = guardrail.check_output(analysis)
        if not output_guardrail.allowed:
            analysis = (
                output_guardrail.message
                or "I cannot return that response because it was blocked by a runtime guardrail."
            )
        response = TutorInvocationResponse(analysis=analysis).model_dump()
        if span:
            span.update(output=response)
        observability.score_current_trace(invocation.evaluation_scores)
        observability.flush()
        return response
