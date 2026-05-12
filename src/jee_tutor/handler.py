from typing import Any

from jee_tutor.invocation.models import TutorInvocationPayload
from jee_tutor.invocation.service import TutorInvocationService


def validate_tutor_invocation(payload: dict[str, Any]) -> TutorInvocationPayload:
    return TutorInvocationPayload.model_validate(payload)


def handle_tutor_invocation(payload: dict[str, Any]) -> dict[str, Any]:
    return TutorInvocationService().handle(payload)
