from crewai import Crew, Process

from agents.tutor_agent.factories import build_diagnosis_task, build_tutor_agent
from agents.tutor_agent.llm_client import VisionLLMClient
from agents.tutor_agent.prompt_provider import PromptProvider
from agents.tutor_agent.tools import build_vision_tool


def build_tutor_crew(
    llm_client: VisionLLMClient | None = None,
    prompt_provider: PromptProvider | None = None,
    image_data_uris: list[str] | None = None,
) -> Crew:
    prompts = prompt_provider or PromptProvider()
    vision_llm_client = llm_client or VisionLLMClient(prompt_provider=prompts)
    vision_tool = build_vision_tool(vision_llm_client, image_data_uris)
    tutor_agent = build_tutor_agent(vision_tool, prompts)
    diagnosis_task = build_diagnosis_task(tutor_agent, prompts)

    return Crew(
        agents=[tutor_agent],
        tasks=[diagnosis_task],
        process=Process.sequential,
        verbose=True,
    )
