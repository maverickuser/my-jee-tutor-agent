from __future__ import annotations

from typing import Any


PROFILE_REPORT_TASK = "profile"


def handle_profile_task(payload: dict[str, Any]) -> dict[str, Any]:
    from jee_tutor.infrastructure.composition import build_student_profile_service

    return build_student_profile_service().handle(payload)
