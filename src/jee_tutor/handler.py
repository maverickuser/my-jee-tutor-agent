from typing import Any

from jee_tutor.logging_config import configure_logging
from jee_tutor.invocation.models import TutorInvocationPayload
from jee_tutor.invocation.service import TutorInvocationService


configure_logging()


def validate_tutor_invocation(payload: dict[str, Any]) -> TutorInvocationPayload:
    return TutorInvocationPayload.model_validate(payload)


def handle_tutor_invocation(payload: dict[str, Any]) -> dict[str, Any]:
    return TutorInvocationService().handle(payload)
