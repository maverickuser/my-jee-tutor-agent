from jee_tutor.invocation.image_inputs import ImageInputResolver
from jee_tutor.invocation.models import (
    ErrorResponse,
    TutorInvocationPayload,
    TutorInvocationResponse,
)

__all__ = [
    "ErrorResponse",
    "ImageInputResolver",
    "TutorInvocationPayload",
    "TutorInvocationResponse",
    "TutorInvocationService",
]


def __getattr__(name):
    if name == "TutorInvocationService":
        from jee_tutor.invocation.service import TutorInvocationService

        return TutorInvocationService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
