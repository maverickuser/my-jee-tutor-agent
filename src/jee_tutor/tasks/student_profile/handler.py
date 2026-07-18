from __future__ import annotations

from typing import Any


PROFILE_REPORT_TASK = "profile"
PROFILE_REPORT_TASK_ALIASES = frozenset(
    {
        PROFILE_REPORT_TASK,
        "profile_report",
        "student_profile",
        "student_profile_report",
        "task_profile",
    }
)


def is_profile_task(task: object) -> bool:
    if not isinstance(task, str):
        return False
    normalized = task.strip().casefold().replace("-", "_").replace(" ", "_")
    return normalized in PROFILE_REPORT_TASK_ALIASES


def handle_profile_task(payload: dict[str, Any]) -> dict[str, Any]:
    from jee_tutor.infrastructure.composition import build_student_profile_service

    return build_student_profile_service().handle(payload)
