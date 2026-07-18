"""Composition root for configured tutor runtime services."""

from jee_tutor.application.invocation import TutorInvocationApplicationService
from jee_tutor.application.profile import StudentProfileApplicationService


def build_tutor_invocation_service() -> TutorInvocationApplicationService:
    """Build the default tutor invocation application service."""

    return TutorInvocationApplicationService()


def build_student_profile_service() -> StudentProfileApplicationService:
    """Build the default student profile application service."""

    return StudentProfileApplicationService()

__all__ = ["build_student_profile_service", "build_tutor_invocation_service"]
