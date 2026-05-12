from collections.abc import Callable

from litellm import completion

from jee_tutor.agent.model_config import VisionModelConfig
from jee_tutor.agent.observability import LangfuseObservability
from jee_tutor.agent.prompt_provider import PromptProvider
from jee_tutor.agent.prompts import VISION_SYSTEM
from jee_tutor.agent.rate_limit import gemini_rate_limiter, is_gemini_model


CompletionFunction = Callable[..., dict]


class VisionMessageFactory:
    def build(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        image_data_uris: list[str] | str,
    ) -> list[dict]:
        return [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": self._user_content(user_prompt, image_data_uris),
            },
        ]

    def _user_content(
        self,
        user_prompt: str,
        image_data_uris: list[str] | str,
    ) -> list[dict]:
        content = [{"type": "text", "text": user_prompt}]
        content.extend(
            {
                "type": "image_url",
                "image_url": {"url": image_data_uri},
            }
            for image_data_uri in self._normalize_images(image_data_uris)
        )
        return content

    @staticmethod
    def _normalize_images(image_data_uris: list[str] | str) -> list[str]:
        return [image_data_uris] if isinstance(image_data_uris, str) else image_data_uris


class VisionLLMClient:
    def __init__(
        self,
        model_config: VisionModelConfig | None = None,
        observability: LangfuseObservability | None = None,
        prompt_provider: PromptProvider | None = None,
        message_factory: VisionMessageFactory | None = None,
        completion_fn: CompletionFunction = completion,
    ):
        self.model_config = model_config or VisionModelConfig()
        self.observability = observability or LangfuseObservability()
        self.prompt_provider = prompt_provider or PromptProvider(observability=self.observability)
        self.message_factory = message_factory or VisionMessageFactory()
        self.completion_fn = completion_fn

    def analyze_vision(self, image_data_uris: list[str] | str, user_prompt: str) -> str:
        model_settings = self.model_config.resolve()
        system_prompt = self.prompt_provider.get(VISION_SYSTEM)

        request_kwargs = {
            **model_settings.to_litellm_kwargs(),
            "messages": self.message_factory.build(
                system_prompt=system_prompt.text,
                user_prompt=user_prompt,
                image_data_uris=image_data_uris,
            ),
        }

        with self.observability.generation_span(
            model=model_settings.model,
            input_payload=self._redacted_generation_input(request_kwargs),
            prompt=system_prompt.langfuse_prompt,
        ) as generation:
            response = self._complete_with_rate_limit(model_settings.model, request_kwargs)
            analysis = response["choices"][0]["message"]["content"].strip()
            if generation:
                generation.update(output=analysis)
            return analysis

    def _complete_with_rate_limit(self, model: str, request_kwargs: dict) -> dict:
        if is_gemini_model(model):
            return gemini_rate_limiter.call(self.completion_fn, **request_kwargs)
        return self.completion_fn(**request_kwargs)

    @staticmethod
    def _redacted_generation_input(request_kwargs: dict) -> dict:
        redacted = {
            key: value
            for key, value in request_kwargs.items()
            if key not in {"api_key", "messages"}
        }
        redacted["messages"] = "[redacted: contains image payload]"
        return redacted
