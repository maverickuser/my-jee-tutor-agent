from collections.abc import Callable
import logging
from typing import Any

from pydantic import ValidationError

from jee_tutor.artifacts.writer import AnalysisArtifactWriter
from jee_tutor.agent import run_tutor_workflow
from jee_tutor.agent.guardrails import RuntimeGuardrail
from jee_tutor.agent.observability import LangfuseObservability
from jee_tutor.invocation.image_inputs import ImageInputResolver
from jee_tutor.invocation.models import (
    ErrorResponse,
    TutorInvocationPayload,
    TutorInvocationResponse,
)


TutorWorkflow = Callable[..., str]
logger = logging.getLogger(__name__)
PDF_WAIT_MINUTES = 5
PDF_WAIT_MESSAGE_TEMPLATE = (
    "Your analysis PDF will be available at {pdf_uri}. Please wait 5 minutes before opening it."
)


class TutorInvocationService:
    def __init__(
        self,
        *,
        image_resolver: ImageInputResolver | None = None,
        guardrail: RuntimeGuardrail | None = None,
        observability: LangfuseObservability | None = None,
        workflow: TutorWorkflow | None = None,
        artifact_writer: AnalysisArtifactWriter | None = None,
    ):
        self.image_resolver = image_resolver or ImageInputResolver()
        self.guardrail = guardrail or RuntimeGuardrail()
        self.observability = observability or LangfuseObservability()
        self.workflow = workflow or run_tutor_workflow
        self.artifact_writer = artifact_writer or AnalysisArtifactWriter()

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "agent_invocation metric_name=agent.invocations metric_value=1 metric_unit=Count"
        )
        try:
            invocation = TutorInvocationPayload.model_validate(payload)
        except ValidationError as exc:
            logger.warning(
                "invalid_tutor_invocation_payload validation_errors=%s",
                [error["msg"] for error in exc.errors()],
            )
            return self._error_response(
                "Invalid tutor invocation payload.",
                [error["msg"] for error in exc.errors()],
            )

        try:
            image_data_uris = self.image_resolver.resolve(
                image_data_uri=invocation.image_data_uri,
                image_data_uris=invocation.image_data_uris,
                image_folder=invocation.image_folder,
                image_s3_uri=invocation.image_s3_uri,
                image_s3_prefix=invocation.image_s3_prefix,
                media=invocation.media,
            )
        except ValueError as exc:
            logger.warning("invalid_tutor_invocation_payload error=%s", exc)
            return self._error_response("Invalid tutor invocation payload.", [str(exc)])
        except Exception as exc:
            logger.exception(
                "tutor_image_resolution_error error_type=%s error=%s",
                exc.__class__.__name__,
                exc or "[no message]",
            )
            return self._error_response(
                "Tutor invocation failed while resolving image inputs.",
                self._image_resolution_error_details(exc, invocation),
            )

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
                logger.warning(
                    "tutor_invocation_blocked_by_input_guardrail reason=%s",
                    input_guardrail.action_reason,
                )
                response = self._error_response(
                    input_guardrail.message or "Tutor invocation blocked by runtime guardrail.",
                    [input_guardrail.action_reason] if input_guardrail.action_reason else [],
                )
                self._finish_invocation(span, response, invocation)
                return response

            try:
                analysis = str(self._run_workflow(invocation, image_data_uris))
            except Exception as exc:
                response = self._error_response(
                    "Tutor workflow failed while analyzing images.",
                    self._workflow_error_details(exc, image_data_uris, invocation),
                )
                logger.exception(
                    "tutor_workflow_error "
                    "image_count=%s error_type=%s error=%s",
                    len(image_data_uris),
                    exc.__class__.__name__,
                    exc or "[no message]",
                )
                self._finish_invocation(span, response, invocation)
                return response

            output_guardrail = self.guardrail.check_output(analysis)
            if not output_guardrail.allowed:
                logger.warning(
                    "tutor_invocation_output_blocked_by_guardrail reason=%s",
                    output_guardrail.action_reason,
                )
                analysis = (
                    output_guardrail.message
                    or "I cannot return that response because it was blocked by a runtime guardrail."
                )

            response = self._success_response(analysis, invocation)
            self._finish_invocation(span, response, invocation)
            return response

    def _run_workflow(
        self,
        invocation: TutorInvocationPayload,
        image_data_uris: list[str],
    ) -> str:
        return self.workflow(
            image_data_uris=image_data_uris,
            question_context=invocation.resolved_question_context,
        )

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

    def _success_response(
        self,
        analysis: str,
        invocation: TutorInvocationPayload,
    ) -> dict[str, Any]:
        analysis_pdf_uri = None
        analysis_markdown_uri = None
        artifact_errors: list[str] = []
        if invocation.save_analysis_pdf:
            try:
                artifact_result = self.artifact_writer.write_for_invocation(
                    analysis_markdown=analysis,
                    invocation=invocation,
                )
                analysis_pdf_uri = artifact_result.pdf_uri
                analysis_markdown_uri = artifact_result.markdown_uri
                artifact_errors.extend(artifact_result.errors)
            except Exception as exc:
                artifact_errors.append(
                    f"Failed to write analysis artifacts: {exc.__class__.__name__}: "
                    f"{exc or '[no message]'}"
                )
                logger.exception(
                    "analysis_artifact_error error_type=%s error=%s",
                    exc.__class__.__name__,
                    exc or "[no message]",
                )

        return TutorInvocationResponse(
            analysis=analysis,
            message=self._pdf_wait_message(analysis_pdf_uri),
            pdf_wait_minutes=self._pdf_wait_minutes(analysis_pdf_uri),
            analysis_pdf_uri=analysis_pdf_uri,
            analysis_markdown_uri=analysis_markdown_uri,
            artifact_errors=artifact_errors,
        ).model_dump(exclude_none=True, exclude_defaults=True)

    @staticmethod
    def _pdf_wait_message(analysis_pdf_uri: str | None) -> str | None:
        if not analysis_pdf_uri:
            return None
        return PDF_WAIT_MESSAGE_TEMPLATE.format(pdf_uri=analysis_pdf_uri)

    @staticmethod
    def _pdf_wait_minutes(analysis_pdf_uri: str | None) -> int | None:
        if not analysis_pdf_uri:
            return None
        return PDF_WAIT_MINUTES

    @staticmethod
    def _workflow_error_details(
        exc: Exception,
        image_data_uris: list[str],
        invocation: TutorInvocationPayload,
    ) -> list[str]:
        return [
            f"Resolved image count: {len(image_data_uris)}.",
            f"Question context provided: {bool(invocation.resolved_question_context)}.",
            f"Exception type: {exc.__class__.__name__}.",
            f"Exception message: {exc or '[no message]'}",
        ]

    @staticmethod
    def _image_resolution_error_details(
        exc: Exception,
        invocation: TutorInvocationPayload,
    ) -> list[str]:
        image_sources = [
            source
            for source, value in (
                ("image_data_uri", invocation.image_data_uri),
                ("image_data_uris", invocation.image_data_uris),
                ("image_folder", invocation.image_folder),
                ("image_s3_uri", invocation.image_s3_uri),
                ("image_s3_prefix", invocation.image_s3_prefix),
                ("media", invocation.media),
            )
            if value
        ]
        return [
            f"Image sources provided: {', '.join(image_sources) or 'none'}.",
            f"Exception type: {exc.__class__.__name__}.",
            f"Exception message: {exc or '[no message]'}",
        ]
