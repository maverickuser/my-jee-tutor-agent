from typing import Any

from jee_tutor.logging_config import configure_logging
from jee_tutor.api.invocation import TutorInvocationPayload
from jee_tutor.tasks.router import handle_agentcore_task


configure_logging()


def validate_tutor_invocation(payload: dict[str, Any]) -> TutorInvocationPayload:
    return TutorInvocationPayload.model_validate(payload)


def handle_tutor_invocation(payload: dict[str, Any]) -> dict[str, Any]:
    from jee_tutor.infrastructure.composition import build_tutor_invocation_service

    return build_tutor_invocation_service().handle(payload)


def handle_agentcore_request(payload: dict[str, Any]) -> dict[str, Any]:
    return handle_agentcore_task(payload)
