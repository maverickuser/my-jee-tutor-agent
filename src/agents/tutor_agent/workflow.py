from typing import Optional

from agents.tutor_agent.crew import build_tutor_crew
from agents.tutor_agent.llm_client import VisionLLMClient
from agents.tutor_agent.prompt_provider import PromptProvider


DEFAULT_QUESTION_CONTEXT = "No additional context provided."


def run_tutor_workflow(
    image_data_uri: str | None = None,
    image_data_uris: list[str] | None = None,
    question_context: Optional[str] = None,
    llm_client: VisionLLMClient | None = None,
    prompt_provider: PromptProvider | None = None,
) -> str:
    resolved_image_data_uris = image_data_uris or ([image_data_uri] if image_data_uri else [])
    crew = build_tutor_crew(llm_client, prompt_provider, resolved_image_data_uris)
    result = crew.kickoff(
        inputs={
            "image_data_uris": "[preloaded in vision tool]",
            "image_count": len(resolved_image_data_uris),
            "question_context": question_context or DEFAULT_QUESTION_CONTEXT,
        }
    )
    return str(result).strip()
