"""Tutor invocation application service."""

from typing import Any

from jee_tutor.invocation.service import TutorInvocationService
from jee_tutor.ports import (
    ArtifactWriterPort,
    EmailDeliveryPort,
    GuardrailPort,
    IdempotencyStorePort,
    ImageResolverPort,
    ObservabilityPort,
    StatusStorePort,
    TutorWorkflowPort,
)


class TutorInvocationApplicationService(TutorInvocationService):
    """Application boundary for tutor invocation orchestration.

    The implementation currently delegates to the compatibility service while
    exposing port-typed dependencies for new composition and tests.
    """

    def __init__(
        self,
        *,
        image_resolver: ImageResolverPort | None = None,
        guardrail: GuardrailPort | None = None,
        observability: ObservabilityPort | None = None,
        workflow: TutorWorkflowPort | None = None,
        artifact_writer: ArtifactWriterPort | None = None,
        email_coordinator: EmailDeliveryPort | None = None,
        idempotency_store: IdempotencyStorePort | None = None,
        status_store: StatusStorePort | None = None,
    ) -> None:
        super().__init__(
            image_resolver=image_resolver,  # type: ignore[arg-type]
            guardrail=guardrail,  # type: ignore[arg-type]
            observability=observability,  # type: ignore[arg-type]
            workflow=workflow,  # type: ignore[arg-type]
            artifact_writer=artifact_writer,  # type: ignore[arg-type]
            email_coordinator=email_coordinator,  # type: ignore[arg-type]
            idempotency_store=idempotency_store,  # type: ignore[arg-type]
            status_store=status_store,  # type: ignore[arg-type]
        )

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        return super().handle(payload)


__all__ = ["TutorInvocationApplicationService"]
