from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.prompt_provider import PromptProvider


def run_tutor_workflow(
    image_data_uri: str | None = None,
    image_data_uris: list[str] | None = None,
    question_context: str | None = None,
    llm_client: VisionLLMClient | None = None,
    prompt_provider: PromptProvider | None = None,
) -> str:
    resolved_image_data_uris = image_data_uris or ([image_data_uri] if image_data_uri else [])
    if not resolved_image_data_uris:
        raise ValueError("Tutor workflow received no images to analyze.")

    vision_client = llm_client or VisionLLMClient(
        prompt_provider=prompt_provider or PromptProvider()
    )
    return vision_client.analyze_vision(resolved_image_data_uris).strip()
