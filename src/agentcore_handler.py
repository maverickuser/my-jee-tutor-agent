from typing import Any

from invocation_models import TutorInvocationPayload
from tutor_invocation_service import TutorInvocationService


def validate_tutor_invocation(payload: dict[str, Any]) -> TutorInvocationPayload:
    return TutorInvocationPayload.model_validate(payload)


def handle_tutor_invocation(payload: dict[str, Any]) -> dict[str, Any]:
    return TutorInvocationService().handle(payload)
