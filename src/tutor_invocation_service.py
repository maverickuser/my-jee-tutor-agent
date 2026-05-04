from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from agents.tutor_agent import run_tutor_workflow
from agents.tutor_agent.guardrails import RuntimeGuardrail
from agents.tutor_agent.observability import LangfuseObservability
from image_inputs import ImageInputResolver
from invocation_models import ErrorResponse, TutorInvocationPayload, TutorInvocationResponse


TutorWorkflow = Callable[..., str]


class TutorInvocationService:
    def __init__(
        self,
        *,
        image_resolver: ImageInputResolver | None = None,
        guardrail: RuntimeGuardrail | None = None,
        observability: LangfuseObservability | None = None,
        workflow: TutorWorkflow | None = None,
    ):
        self.image_resolver = image_resolver or ImageInputResolver()
        self.guardrail = guardrail or RuntimeGuardrail()
        self.observability = observability or LangfuseObservability()
        self.workflow = workflow or run_tutor_workflow

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            invocation = TutorInvocationPayload.model_validate(payload)
        except ValidationError as exc:
            return self._error_response(
                "Invalid tutor invocation payload.",
                [error["msg"] for error in exc.errors()],
            )

        try:
            image_data_uris = self.image_resolver.resolve(
                image_data_uri=invocation.image_data_uri,
                image_data_uris=invocation.image_data_uris,
                image_folder=invocation.image_folder,
                media=invocation.media,
            )
        except ValueError as exc:
            return self._error_response("Invalid tutor invocation payload.", [str(exc)])

        return self._run_guarded_workflow(invocation, image_data_uris)

    def _run_guarded_workflow(
        self,
        invocation: TutorInvocationPayload,
        image_data_uris: list[str],
    ) -> dict[str, Any]:
        with self.observability.invocation_span(
            input_payload=invocation.safe_trace_input(),
            user_id=invocation.user_id,
            session_id=invocation.session_id,
            tags=invocation.tags,
            metadata=invocation.metadata,
        ) as span:
            input_guardrail = self.guardrail.check_input(
                question_context=invocation.resolved_question_context,
                image_data_uris=image_data_uris,
            )
            if not input_guardrail.allowed:
                response = self._error_response(
                    input_guardrail.message
                    or "Tutor invocation blocked by runtime guardrail.",
                    [input_guardrail.action_reason] if input_guardrail.action_reason else [],
                )
                self._finish_invocation(span, response, invocation)
                return response

            analysis = self.workflow(
                image_data_uris=image_data_uris,
                question_context=invocation.resolved_question_context,
            )
            output_guardrail = self.guardrail.check_output(analysis)
            if not output_guardrail.allowed:
                analysis = (
                    output_guardrail.message
                    or "I cannot return that response because it was blocked by a runtime guardrail."
                )

            response = TutorInvocationResponse(analysis=analysis).model_dump()
            self._finish_invocation(span, response, invocation)
            return response

    def _finish_invocation(
        self,
        span: Any,
        response: dict[str, Any],
        invocation: TutorInvocationPayload,
    ) -> None:
        if span:
            span.update(output=response)
        self.observability.score_current_trace(invocation.evaluation_scores)
        self.observability.flush()

    @staticmethod
    def _error_response(error: str, details: list[str] | None = None) -> dict[str, Any]:
        return ErrorResponse(error=error, details=details or []).model_dump()
