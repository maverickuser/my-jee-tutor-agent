import json
import logging

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.agent.crew import build_tutor_crew
from jee_tutor.agent.diagnosis_output import (
    parse_and_validate_diagnosis,
    render_and_validate_diagnosis,
)
from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.output_validation import OutputValidationError, validate_markdown_analysis
from jee_tutor.agent.prompt_provider import PromptProvider
from jee_tutor.agent.tools import VisionToolCallState, build_vision_tool


logger = logging.getLogger(__name__)


class CrewObservationMismatchError(OutputValidationError):
    pass


class DiagnosisMarkdown(str):
    diagnosis: object

    def __new__(cls, value: str, diagnosis: object) -> "DiagnosisMarkdown":
        instance = super().__new__(cls, value)
        instance.diagnosis = diagnosis
        return instance


def run_tutor_workflow(
    image_data_uri: str | None = None,
    image_data_uris: list[str] | None = None,
    question_context: str | None = None,
    expected_question_numbers: list[str | None] | None = None,
    llm_client: VisionLLMClient | None = None,
    prompt_provider: PromptProvider | None = None,
    react_enabled: bool | None = None,
) -> str:
    resolved_image_data_uris = image_data_uris or ([image_data_uri] if image_data_uri else [])
    if not resolved_image_data_uris:
        raise ValueError("Tutor workflow received no images to analyze.")

    prompts = prompt_provider or PromptProvider()
    vision_client = llm_client or VisionLLMClient(prompt_provider=prompts)
    tool_call_state = VisionToolCallState()
    configured_react = bool(LLMConfig.load().get("react_diagnosis", "enabled", False))
    use_react = (
        react_enabled
        if react_enabled is not None
        else configured_react and llm_client is None
    )
    if use_react:
        crew = build_tutor_crew(
            llm_client=vision_client,
            prompt_provider=prompts,
            image_data_uris=resolved_image_data_uris,
            tool_call_state=tool_call_state,
            expected_question_numbers=expected_question_numbers,
        )
        crew_result = crew.kickoff()
        analysis = _crew_output_text(crew_result)
        observation = tool_call_state.observation
        if observation is None or _normalized_json(analysis) != _normalized_json(observation):
            raise CrewObservationMismatchError(
                "CrewAI final answer did not preserve the vision tool observation.",
                ["Validation category: crew_observation_mismatch."],
            )
    else:
        vision_tool = build_vision_tool(
            vision_client,
            resolved_image_data_uris,
            tool_call_state,
        )
        if hasattr(vision_tool, "expected_question_numbers"):
            vision_tool.expected_question_numbers = expected_question_numbers or []
        analysis = vision_tool.run_preloaded().strip()
    _validate_vision_tool_call(tool_call_state, len(resolved_image_data_uris))
    logger.info(
        "diagnosis_operation_counts crew_kickoff_count=%s "
        "vision_tool_request_count=%s vision_tool_execution_count=%s "
        "vision_tool_success_count=%s vision_transport_attempt_count=%s",
        int(use_react),
        tool_call_state.request_count,
        tool_call_state.execution_count,
        tool_call_state.successful_execution_count,
        tool_call_state.transport_attempt_count,
    )
    if analysis.lstrip().startswith("{"):
        diagnosis = parse_and_validate_diagnosis(
            analysis,
            expected_image_count=len(resolved_image_data_uris),
            expected_question_numbers=expected_question_numbers,
        )
        return DiagnosisMarkdown(
            render_and_validate_diagnosis(
                diagnosis,
                expected_question_numbers=expected_question_numbers,
            ),
            diagnosis,
        )
    validate_markdown_analysis(
        analysis,
        expected_image_count=len(resolved_image_data_uris),
        expected_question_numbers=expected_question_numbers
        if expected_question_numbers is not None
        else [None] * len(resolved_image_data_uris),
    )
    return analysis


def _crew_output_text(result: object) -> str:
    raw = getattr(result, "raw", None)
    return (raw if isinstance(raw, str) else str(result)).strip()


def _normalized_json(value: str) -> str | None:
    try:
        return json.dumps(json.loads(value), sort_keys=True, separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        return None


def _validate_vision_tool_call(
    tool_call_state: VisionToolCallState,
    expected_image_count: int,
) -> None:
    if not tool_call_state.called:
        raise OutputValidationError(
            "Workflow did not call the vision analysis tool.",
            ["Vision tool called: False."],
        )
    if not tool_call_state.success:
        raise OutputValidationError(
            "Vision analysis tool did not complete successfully.",
            [
                "Vision tool called: True.",
                "Vision tool error: "
                f"{tool_call_state.first_error or tool_call_state.error or '[unknown]'}",
            ],
        )
    if tool_call_state.execution_count not in {0, 1}:
        raise OutputValidationError(
            "Workflow executed the vision analysis tool more than once.",
            [f"Vision tool execution count: {tool_call_state.execution_count}."],
        )
    if tool_call_state.successful_call_count != 1:
        raise OutputValidationError(
            "Vision analysis tool did not complete successfully exactly once.",
            [
                "Vision tool successful call count: "
                f"{tool_call_state.successful_call_count}."
            ],
        )
    if tool_call_state.image_source != "preloaded_invocation_images":
        raise OutputValidationError(
            "Vision analysis tool did not use preloaded invocation images.",
            [
                f"Vision tool image source: {tool_call_state.image_source or '[unknown]'}.",
                "Expected image source: preloaded_invocation_images.",
            ],
        )
    if tool_call_state.image_count != expected_image_count:
        raise OutputValidationError(
            "Vision analysis tool image count does not match resolved image count.",
            [
                f"Resolved image count: {expected_image_count}.",
                f"Vision tool image count: {tool_call_state.image_count}.",
            ],
        )
