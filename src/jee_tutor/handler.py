from typing import Any

from jee_tutor.logging_config import configure_logging
from jee_tutor.api.invocation import TutorInvocationPayload
from jee_tutor.tasks.router import handle_agentcore_task
from jee_tutor.tasks.student_profile import is_profile_task
from jee_tutor.infrastructure.execution_profile import (
    CdExecutionProfileAuthenticator,
    ExecutionProfileAuthorizationError,
    resolve_execution_profile,
)
from jee_tutor.model_routing import (
    ExecutionProfile,
    resolve_model_bundle,
    use_model_bundle,
)


configure_logging()


def validate_tutor_invocation(payload: dict[str, Any]) -> TutorInvocationPayload:
    return TutorInvocationPayload.model_validate(payload)


def handle_tutor_invocation(
    payload: dict[str, Any],
    *,
    execution_profile: ExecutionProfile | None = None,
) -> dict[str, Any]:
    if execution_profile is not None:
        with use_model_bundle(resolve_model_bundle(execution_profile)):
            return _handle_tutor_invocation(payload)
    return _handle_tutor_invocation(payload)


def _handle_tutor_invocation(payload: dict[str, Any]) -> dict[str, Any]:
    if is_profile_task(payload.get("task")):
        return handle_agentcore_task(payload)

    from jee_tutor.infrastructure.composition import build_tutor_invocation_service

    return build_tutor_invocation_service().handle(payload)


def handle_agentcore_request(
    payload: dict[str, Any],
    *,
    request_headers: dict[str, str] | None = None,
    authenticator: CdExecutionProfileAuthenticator | None = None,
) -> dict[str, Any]:
    try:
        execution_profile = resolve_execution_profile(
            payload=payload,
            request_headers=request_headers,
            authenticator=authenticator,
        )
    except ExecutionProfileAuthorizationError as exc:
        return {
            "error": "Unauthorized execution profile.",
            "details": [str(exc)],
        }
    with use_model_bundle(resolve_model_bundle(execution_profile)):
        return handle_agentcore_task(payload)
