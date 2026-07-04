from collections.abc import Callable
import logging
from typing import Any
import os

from pydantic import ValidationError

from jee_tutor.artifacts.writer import AnalysisArtifactWriter
from jee_tutor.agent import run_tutor_workflow
from jee_tutor.agent.guardrails import RuntimeGuardrail
from jee_tutor.agent.observability import LangfuseObservability
from jee_tutor.agent.output_validation import OutputValidationError
from jee_tutor.email.delivery import EmailDeliveryCoordinator
from jee_tutor.email.models import EmailDeliveryOutcome, EmailDeliveryStatus
from jee_tutor.invocation.idempotency import (
    InvocationIdempotencyStore,
    invocation_idempotency_store,
)
from jee_tutor.invocation.image_inputs import ImageInputResolver, ResolvedImage
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
        email_coordinator: EmailDeliveryCoordinator | None = None,
        idempotency_store: InvocationIdempotencyStore | None = None,
    ):
        self.image_resolver = image_resolver or ImageInputResolver()
        self.guardrail = guardrail or RuntimeGuardrail()
        self.observability = observability or LangfuseObservability()
        self.workflow = workflow or run_tutor_workflow
        self.artifact_writer = artifact_writer or AnalysisArtifactWriter()
        self.email_coordinator = email_coordinator or EmailDeliveryCoordinator()
        self.idempotency_store = idempotency_store or invocation_idempotency_store

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

        if invocation.idempotency_key:
            claim = self.idempotency_store.claim(
                invocation.idempotency_key,
                invocation.model_dump(),
            )
            if claim.status == "completed":
                return claim.response or {}
            if claim.status == "in_progress":
                return self._error_response(
                    "Tutor invocation is already in progress.",
                    ["Retry later using the same idempotency_key."],
                )
            if claim.status == "conflict":
                return self._error_response(
                    "Idempotency key was already used with a different payload.",
                    ["Use a new idempotency_key for a different request."],
                )

        try:
            response = self._handle_validated_invocation(invocation)
        except Exception:
            if invocation.idempotency_key:
                self.idempotency_store.abandon(invocation.idempotency_key)
            raise

        if invocation.idempotency_key:
            self.idempotency_store.complete(invocation.idempotency_key, response)
        return response

    def _handle_validated_invocation(
        self,
        invocation: TutorInvocationPayload,
    ) -> dict[str, Any]:
        try:
            resolved_images = self.image_resolver.resolve_images(
                image_data_uri=invocation.image_data_uri,
                image_s3_prefix=invocation.image_s3_prefix,
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

        return self._run_guarded_workflow(invocation, resolved_images)

    def _run_guarded_workflow(
        self,
        invocation: TutorInvocationPayload,
        resolved_images: list[ResolvedImage],
    ) -> dict[str, Any]:
        image_data_uris = [image.data_uri for image in resolved_images]
        with self.observability.invocation_span(
            input_payload=invocation.safe_trace_input(),
            metadata={"subject": invocation.subject} if invocation.subject else None,
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
                workflow_result = self._run_workflow(invocation, resolved_images)
                analysis = str(workflow_result)
            except Exception as exc:
                response = self._error_response(
                    "Tutor workflow failed while analyzing images.",
                    self._workflow_error_details(exc, resolved_images, invocation),
                )
                logger.exception(
                    "tutor_workflow_error image_count=%s error_type=%s error=%s",
                    len(resolved_images),
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

            response = self._success_response(
                analysis,
                invocation,
            )
            self._finish_invocation(span, response, invocation)
            return response

    def _run_workflow(
        self,
        invocation: TutorInvocationPayload,
        resolved_images: list[ResolvedImage],
    ) -> str:
        return self.workflow(
            image_data_uris=[image.data_uri for image in resolved_images],
            question_context=invocation.resolved_question_context,
            expected_question_numbers=[image.question_number for image in resolved_images],
        )

    def _finish_invocation(
        self,
        span: Any,
        response: dict[str, Any],
        invocation: TutorInvocationPayload,
    ) -> None:
        if span:
            span.update(output=response)

    @staticmethod
    def _error_response(error: str, details: list[str] | None = None) -> dict[str, Any]:
        return ErrorResponse(
            error=error,
            details=details or [],
            runtime_commit_sha=TutorInvocationService._runtime_commit_sha(),
        ).model_dump(exclude_none=True)

    def _success_response(
        self,
        analysis: str,
        invocation: TutorInvocationPayload,
    ) -> dict[str, Any]:
        analysis_pdf_uri = None
        analysis_markdown_uri = None
        artifact_errors: list[str] = []
        if invocation.should_write_analysis_pdf:
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

        email_outcome = self._request_email_delivery(
            invocation=invocation,
            analysis_pdf_uri=analysis_pdf_uri,
        )

        return TutorInvocationResponse(
            analysis=analysis,
            message=self._pdf_wait_message(analysis_pdf_uri),
            pdf_wait_minutes=self._pdf_wait_minutes(analysis_pdf_uri),
            analysis_pdf_uri=analysis_pdf_uri,
            analysis_markdown_uri=analysis_markdown_uri,
            artifact_errors=artifact_errors,
            email_status=email_outcome.status.value,
            email_delivery_id=email_outcome.delivery_id,
            email_error=email_outcome.error,
            runtime_commit_sha=self._runtime_commit_sha(),
        ).model_dump(exclude_none=True, exclude_defaults=True)

    def _request_email_delivery(
        self,
        *,
        invocation: TutorInvocationPayload,
        analysis_pdf_uri: str | None,
    ) -> EmailDeliveryOutcome:
        if not invocation.recipient_email:
            return EmailDeliveryOutcome(status=EmailDeliveryStatus.NOT_REQUESTED)

        if not analysis_pdf_uri:
            error = "Email delivery requires a stored PDF artifact."
            logger.warning(
                "email_delivery_missing_pdf recipient_domain=%s",
                invocation.recipient_email.split("@", 1)[-1] if "@" in invocation.recipient_email else "unknown",
            )
            return EmailDeliveryOutcome(
                status=EmailDeliveryStatus.FAILED,
                error=error,
            )

        try:
            return self.email_coordinator.request_delivery(
                recipient_email=invocation.recipient_email,
                pdf_uri=analysis_pdf_uri,
                invocation_id=invocation.idempotency_key,
                idempotency_key=invocation.idempotency_key,
            )
        except Exception as exc:
            logger.exception(
                "email_delivery_runtime_error error_type=%s error=%s",
                exc.__class__.__name__,
                exc or "[no message]",
            )
            return EmailDeliveryOutcome(
                status=EmailDeliveryStatus.FAILED,
                error=f"{exc.__class__.__name__}: {exc or '[no message]'}",
            )

    @staticmethod
    def _runtime_commit_sha() -> str | None:
        value = os.getenv("JEE_TUTOR_GIT_SHA", "").strip()
        return value if value and value != "unknown" else None

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
        resolved_images: list[ResolvedImage],
        invocation: TutorInvocationPayload,
    ) -> list[str]:
        details = [
            f"Resolved image count: {len(resolved_images)}.",
            f"Question context provided: {bool(invocation.resolved_question_context)}.",
            f"Expected question numbers: {TutorInvocationService._format_expected_questions(resolved_images)}.",
            f"Exception type: {exc.__class__.__name__}.",
            f"Exception message: {exc or '[no message]'}",
        ]
        if isinstance(exc, OutputValidationError):
            details.extend(exc.details)
        return details

    @staticmethod
    def _format_expected_questions(resolved_images: list[ResolvedImage]) -> str:
        if not resolved_images:
            return "[none]"
        return ", ".join(
            image.question_number
            if image.question_number is not None
            else f"[missing:{image.file_name or 'inline'}]"
            for image in resolved_images
        )

    @staticmethod
    def _image_resolution_error_details(
        exc: Exception,
        invocation: TutorInvocationPayload,
    ) -> list[str]:
        image_sources = [
            source
            for source, value in (
                ("image_data_uri", invocation.image_data_uri),
                ("image_s3_prefix", invocation.image_s3_prefix),
            )
            if value
        ]
        return [
            f"Image sources provided: {', '.join(image_sources) or 'none'}.",
            f"Exception type: {exc.__class__.__name__}.",
            f"Exception message: {exc or '[no message]'}",
        ]
