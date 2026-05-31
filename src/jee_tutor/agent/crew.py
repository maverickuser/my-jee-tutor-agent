from crewai import Crew, Process

from jee_tutor.agent.factories import build_diagnosis_task, build_tutor_agent
from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.prompt_provider import PromptProvider
from jee_tutor.agent.tools import build_vision_tool
from jee_tutor.concepts.tool import ConceptGraphTool


def build_tutor_crew(
    llm_client: VisionLLMClient | None = None,
    prompt_provider: PromptProvider | None = None,
    image_data_uris: list[str] | None = None,
    concept_graph_tool: ConceptGraphTool | None = None,
) -> Crew:
    prompts = prompt_provider or PromptProvider()
    vision_llm_client = llm_client or VisionLLMClient(prompt_provider=prompts)
    vision_tool = build_vision_tool(vision_llm_client, image_data_uris)
    tutor_agent = build_tutor_agent(
        vision_tool,
        prompts,
        extra_tools=[concept_graph_tool] if concept_graph_tool else None,
    )
    diagnosis_task = build_diagnosis_task(tutor_agent, prompts)

    return Crew(
        agents=[tutor_agent],
        tasks=[diagnosis_task],
        process=Process.sequential,
        verbose=True,
    )
