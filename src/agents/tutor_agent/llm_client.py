from litellm import completion

from agents.tutor_agent.model_config import VisionModelConfig
from agents.tutor_agent.observability import LangfuseObservability
from agents.tutor_agent.prompt_provider import PromptProvider
from agents.tutor_agent.prompts import VISION_SYSTEM


class VisionLLMClient:
    def __init__(
        self,
        model_config: VisionModelConfig | None = None,
        observability: LangfuseObservability | None = None,
        prompt_provider: PromptProvider | None = None,
    ):
        self.model_config = model_config or VisionModelConfig()
        self.observability = observability or LangfuseObservability()
        self.prompt_provider = prompt_provider or PromptProvider(
            observability=self.observability
        )

    def analyze_vision(self, image_data_uris: list[str] | str, user_prompt: str) -> str:
        model_settings = self.model_config.resolve()
        system_prompt = self.prompt_provider.get(VISION_SYSTEM)
        resolved_image_data_uris = (
            [image_data_uris] if isinstance(image_data_uris, str) else image_data_uris
        )
        user_content = [{"type": "text", "text": user_prompt}]
        user_content.extend(
            {
                "type": "image_url",
                "image_url": {"url": image_data_uri},
            }
            for image_data_uri in resolved_image_data_uris
        )

        request_kwargs = {
            **model_settings.to_litellm_kwargs(),
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt.text,
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
        }

        with self.observability.generation_span(
            model=model_settings.model,
            input_payload=self._redacted_generation_input(request_kwargs),
            prompt=system_prompt.langfuse_prompt,
        ) as generation:
            response = completion(**request_kwargs)
            analysis = response["choices"][0]["message"]["content"].strip()
            if generation:
                generation.update(output=analysis)
            return analysis

    @staticmethod
    def _redacted_generation_input(request_kwargs: dict) -> dict:
        redacted = {
            key: value
            for key, value in request_kwargs.items()
            if key not in {"api_key", "messages"}
        }
        redacted["messages"] = "[redacted: contains image payload]"
        return redacted
