from crewai import Crew, Process

from jee_tutor.agent.factories import build_diagnosis_task, build_tutor_agent
from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.prompt_provider import PromptProvider
from jee_tutor.agent.tools import VisionToolCallState, build_vision_tool
from jee_tutor.invocation.status_store import InvocationStatusStore


def build_tutor_crew(
    llm_client: VisionLLMClient | None = None,
    prompt_provider: PromptProvider | None = None,
    image_data_uris: list[str] | None = None,
    tool_call_state: VisionToolCallState | None = None,
    expected_question_numbers: list[str | None] | None = None,
    invocation_id: str | None = None,
    status_store: InvocationStatusStore | None = None,
) -> Crew:
    prompts = prompt_provider or PromptProvider()
    vision_llm_client = llm_client or VisionLLMClient(prompt_provider=prompts)
    if expected_question_numbers is None:
        vision_tool = build_vision_tool(
            vision_llm_client,
            image_data_uris,
            tool_call_state,
            invocation_id=invocation_id,
            status_store=status_store,
        )
    else:
        vision_tool = build_vision_tool(
            vision_llm_client,
            image_data_uris,
            tool_call_state,
            expected_question_numbers,
            invocation_id=invocation_id,
            status_store=status_store,
        )
    tutor_agent = build_tutor_agent(vision_tool, prompts)
    diagnosis_task = build_diagnosis_task(tutor_agent, vision_tool, prompts)

    return Crew(
        agents=[tutor_agent],
        tasks=[diagnosis_task],
        process=Process.sequential,
        verbose=False,
    )
