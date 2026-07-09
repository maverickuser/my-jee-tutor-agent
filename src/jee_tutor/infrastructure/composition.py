"""Composition root for configured tutor runtime services."""

from jee_tutor.application.invocation import TutorInvocationApplicationService


def build_tutor_invocation_service() -> TutorInvocationApplicationService:
    """Build the default tutor invocation application service."""

    return TutorInvocationApplicationService()


__all__ = ["build_tutor_invocation_service"]
