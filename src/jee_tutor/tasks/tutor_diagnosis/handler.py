from __future__ import annotations

from typing import Any


def handle_diagnosis_task(payload: dict[str, Any]) -> dict[str, Any]:
    from jee_tutor.infrastructure.composition import build_tutor_invocation_service

    return build_tutor_invocation_service().handle(payload)
