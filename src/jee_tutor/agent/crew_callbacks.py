from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from jee_tutor.agent.tools import VisionToolCallState
from jee_tutor.invocation.status_store import InvocationStatusStore


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CrewCallbackContext:
    invocation_id: str | None
    expected_image_count: int
    expected_question_numbers: list[str | None]
    tool_call_state: VisionToolCallState
    status_store: InvocationStatusStore | None = None


@dataclass(frozen=True)
class CrewCallbacks:
    before_kickoff_callbacks: list[Callable]
    after_kickoff_callbacks: list[Callable]
    task_callback: Callable | None = None
    step_callback: Callable | None = None


def build_crew_callbacks(context: CrewCallbackContext) -> CrewCallbacks:
    _validate_context(context)
    return CrewCallbacks(
        before_kickoff_callbacks=[_before_kickoff(context)],
        after_kickoff_callbacks=[_after_kickoff(context)],
        task_callback=_task_callback(context),
        step_callback=None,
    )


def _validate_context(context: CrewCallbackContext) -> None:
    if context.expected_image_count < 0:
        raise ValueError("expected_image_count must be non-negative.")
    if context.expected_question_numbers is None:
        raise ValueError("expected_question_numbers must be provided.")


def _before_kickoff(context: CrewCallbackContext) -> Callable:
    def callback(inputs: dict[str, Any] | None = None) -> dict[str, Any] | None:
        try:
            logger.info(
                "crewai_kickoff_started metric_name=crewai.kickoff.started "
                "metric_value=1 invocation_id=%s expected_image_count=%s "
                "expected_question_number_count=%s react_mode=%s crew_name=%s "
                "task_name=%s agent_name=%s",
                context.invocation_id or "unknown",
                context.expected_image_count,
                len(context.expected_question_numbers),
                "controlled",
                _safe_name(inputs, "crew_name"),
                _safe_name(inputs, "task_name"),
                _safe_name(inputs, "agent_name"),
            )
            _append_event(
                context,
                {
                    "event": "CREW_STARTED",
                    "expected_image_count": context.expected_image_count,
                    "expected_question_number_count": len(context.expected_question_numbers),
                    "react_mode": "controlled",
                },
            )
        except Exception:
            logger.exception("crewai_before_kickoff_callback_failed")
        return inputs

    return callback


def _after_kickoff(context: CrewCallbackContext) -> Callable:
    def callback(output: Any) -> Any:
        try:
            raw_output = getattr(output, "raw", None)
            output_text = raw_output if isinstance(raw_output, str) else str(output)
            logger.info(
                "crewai_kickoff_completed metric_name=crewai.kickoff.completed "
                "metric_value=1 invocation_id=%s output_length=%s "
                "vision_tool_request_count=%s vision_tool_execution_count=%s "
                "vision_tool_success_count=%s vision_tool_failure_count=%s "
                "vision_tool_cached_replay_count=%s vision_observation_rejected_count=%s "
                "vision_observation_replaced_count=%s",
                context.invocation_id or "unknown",
                len(output_text),
                context.tool_call_state.request_count,
                context.tool_call_state.execution_count,
                context.tool_call_state.successful_execution_count,
                int(bool(context.tool_call_state.error)),
                context.tool_call_state.cached_replay_count,
                int(context.tool_call_state.observation_rejected),
                context.tool_call_state.observation_replaced_count,
            )
            _append_event(
                context,
                {
                    "event": "CREW_COMPLETED",
                    "output_length": len(output_text),
                    "tool_request_count": context.tool_call_state.request_count,
                    "tool_execution_count": context.tool_call_state.execution_count,
                    "tool_success_count": context.tool_call_state.successful_execution_count,
                    "tool_cached_replay_count": context.tool_call_state.cached_replay_count,
                    "observation_replaced_count": context.tool_call_state.observation_replaced_count,
                },
            )
        except Exception:
            logger.exception("crewai_after_kickoff_callback_failed")
        return output

    return callback


def _task_callback(context: CrewCallbackContext) -> Callable:
    def callback(task_output: Any) -> Any:
        try:
            raw_output = getattr(task_output, "raw", None)
            output_text = raw_output if isinstance(raw_output, str) else str(task_output)
            task_name = (
                getattr(getattr(task_output, "task", None), "name", None)
                or getattr(task_output, "name", None)
                or "diagnosis_task"
            )
            logger.info(
                "crewai_task_completed metric_name=crewai.task.completed metric_value=1 "
                "invocation_id=%s task_name=%s output_length=%s "
                "tool_request_count=%s tool_execution_count=%s tool_success=%s "
                "guardrail_validated=%s guardrail_rejected=%s guardrail_failure_category=%s",
                context.invocation_id or "unknown",
                task_name,
                len(output_text),
                context.tool_call_state.request_count,
                context.tool_call_state.execution_count,
                context.tool_call_state.success,
                context.tool_call_state.observation_validated,
                context.tool_call_state.observation_rejected,
                context.tool_call_state.observation_rejection_category,
            )
            _append_event(
                context,
                {
                    "event": "TASK_COMPLETED",
                    "task_name": task_name,
                    "output_length": len(output_text),
                    "tool_request_count": context.tool_call_state.request_count,
                    "tool_execution_count": context.tool_call_state.execution_count,
                    "guardrail_validated": context.tool_call_state.observation_validated,
                    "guardrail_rejected": context.tool_call_state.observation_rejected,
                    "guardrail_failure_category": (
                        context.tool_call_state.observation_rejection_category
                    ),
                },
            )
        except Exception:
            logger.exception("crewai_task_callback_failed")
        return task_output

    return callback


def _safe_name(inputs: dict[str, Any] | None, key: str) -> str:
    if not isinstance(inputs, dict):
        return "unknown"
    value = inputs.get(key)
    if value is None:
        return "unknown"
    return str(value)[:120]


def _append_event(context: CrewCallbackContext, event: dict[str, Any]) -> None:
    if not context.status_store or not context.invocation_id:
        return
    append_event = getattr(context.status_store, "append_event", None)
    if not callable(append_event):
        return
    append_event(context.invocation_id, event)
