from typing import Optional

from agents.tutor_agent.crew import build_tutor_crew
from agents.tutor_agent.llm_client import VisionLLMClient
from agents.tutor_agent.prompt_provider import PromptProvider


DEFAULT_QUESTION_CONTEXT = "No additional context provided."


def run_tutor_workflow(
    image_data_uri: str,
    question_context: Optional[str] = None,
    llm_client: VisionLLMClient | None = None,
    prompt_provider: PromptProvider | None = None,
) -> str:
    crew = build_tutor_crew(llm_client, prompt_provider)
    result = crew.kickoff(
        inputs={
            "image_data_uri": image_data_uri,
            "question_context": question_context or DEFAULT_QUESTION_CONTEXT,
        }
    )
    return str(result).strip()
