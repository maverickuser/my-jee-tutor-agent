from jee_tutor.agent.crew import build_tutor_crew
from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.output_validation import OutputValidationError, validate_markdown_analysis
from jee_tutor.agent.prompt_provider import PromptProvider
from jee_tutor.agent.tools import VisionToolCallState


DEFAULT_QUESTION_CONTEXT = "No additional context provided."


def run_tutor_workflow(
    image_data_uri: str | None = None,
    image_data_uris: list[str] | None = None,
    question_context: str | None = None,
    expected_question_numbers: list[str | None] | None = None,
    llm_client: VisionLLMClient | None = None,
    prompt_provider: PromptProvider | None = None,
) -> str:
    resolved_image_data_uris = image_data_uris or ([image_data_uri] if image_data_uri else [])
    if not resolved_image_data_uris:
        raise ValueError("Tutor workflow received no images to analyze.")

    tool_call_state = VisionToolCallState()
    crew = build_tutor_crew(
        llm_client=llm_client,
        prompt_provider=prompt_provider,
        image_data_uris=resolved_image_data_uris,
        tool_call_state=tool_call_state,
    )
    result = crew.kickoff(
        inputs={
            "image_data_uris": "[preloaded in vision tool]",
            "image_count": len(resolved_image_data_uris),
            "question_context": question_context or DEFAULT_QUESTION_CONTEXT,
        }
    )
    analysis = str(result).strip()
    _validate_vision_tool_call(tool_call_state, len(resolved_image_data_uris))
    validate_markdown_analysis(
        analysis,
        expected_image_count=len(resolved_image_data_uris),
        expected_question_numbers=expected_question_numbers
        if expected_question_numbers is not None
        else [None] * len(resolved_image_data_uris),
    )
    return analysis


def _validate_vision_tool_call(
    tool_call_state: VisionToolCallState,
    expected_image_count: int,
) -> None:
    if not tool_call_state.called:
        raise OutputValidationError(
            "CrewAI did not call the vision analysis tool.",
            ["Vision tool called: False."],
        )
    if tool_call_state.call_count != 1:
        raise OutputValidationError(
            "CrewAI did not call the vision analysis tool exactly once.",
            [f"Vision tool call count: {tool_call_state.call_count}."],
        )
    if not tool_call_state.success:
        raise OutputValidationError(
            "Vision analysis tool did not complete successfully.",
            [
                "Vision tool called: True.",
                f"Vision tool error: {tool_call_state.error or '[unknown]'}",
            ],
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
