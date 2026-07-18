from typing import Any

from jee_tutor.logging_config import configure_logging
from jee_tutor.api.invocation import TutorInvocationPayload
from jee_tutor.application.profile import PROFILE_REPORT_TASK
from jee_tutor.infrastructure.composition import (
    build_student_profile_service,
    build_tutor_invocation_service,
)


configure_logging()


def validate_tutor_invocation(payload: dict[str, Any]) -> TutorInvocationPayload:
    return TutorInvocationPayload.model_validate(payload)


def handle_tutor_invocation(payload: dict[str, Any]) -> dict[str, Any]:
    return build_tutor_invocation_service().handle(payload)


def handle_agentcore_request(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("task") == PROFILE_REPORT_TASK:
        return build_student_profile_service().handle(payload)
    return handle_tutor_invocation(payload)
