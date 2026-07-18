from __future__ import annotations

from typing import Any

from jee_tutor.tasks.student_profile import handle_profile_task, is_profile_task
from jee_tutor.tasks.tutor_diagnosis import handle_diagnosis_task


def handle_agentcore_task(payload: dict[str, Any]) -> dict[str, Any]:
    if is_profile_task(payload.get("task")):
        return handle_profile_task(payload)
    return handle_diagnosis_task(payload)
