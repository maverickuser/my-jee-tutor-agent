from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator

from agents.tutor_agent import run_tutor_workflow
from agents.tutor_agent.guardrails import RuntimeGuardrail
from agents.tutor_agent.observability import EvaluationScore, LangfuseObservability


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
        if self.image_data_uri or self.image_from_media:
            return self
        raise ValueError(
            "Missing image payload. Send image_data_uri, or media with "
            "type=image, format, and base64 data."
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
    def resolved_question_context(self) -> str | None:
        return self.question_context or self.prompt


class TutorInvocationResponse(BaseModel):
    analysis: str


class ErrorResponse(BaseModel):
    error: str
    details: list[str] = Field(default_factory=list)


def validate_tutor_invocation(payload: dict[str, Any]) -> TutorInvocationPayload:
    return TutorInvocationPayload.model_validate(payload)


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

    with observability.invocation_span(
        input_payload=invocation.model_dump(exclude={"image_data_uri", "media"}),
        user_id=invocation.user_id,
        session_id=invocation.session_id,
        tags=invocation.tags,
        metadata=invocation.metadata,
    ) as span:
        input_guardrail = guardrail.check_input(
            question_context=invocation.resolved_question_context,
            image_data_uri=invocation.resolved_image_data_uri,
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
            image_data_uri=invocation.resolved_image_data_uri,
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
