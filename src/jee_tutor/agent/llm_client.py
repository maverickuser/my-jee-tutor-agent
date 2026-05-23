from collections.abc import Callable
import logging
from typing import Any

from litellm import completion, completion_cost

from jee_tutor.agent.model_config import VisionModelConfig
from jee_tutor.agent.observability import LangfuseObservability
from jee_tutor.agent.prompt_provider import PromptProvider
from jee_tutor.agent.prompts import VISION_SYSTEM
from jee_tutor.agent.rate_limit import gemini_rate_limiter, is_gemini_model


CompletionFunction = Callable[..., dict]
logger = logging.getLogger(__name__)


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
                generation.update(
                    output=analysis,
                    **self._generation_accounting(response, model_settings.model),
                )
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

    @classmethod
    def _generation_accounting(cls, response: Any, model: str) -> dict[str, dict]:
        accounting: dict[str, dict] = {}
        usage_details = cls._usage_details(response)
        if usage_details:
            accounting["usage_details"] = usage_details

        cost_details = cls._cost_details(response, model)
        if cost_details:
            accounting["cost_details"] = cost_details

        return accounting

    @staticmethod
    def _usage_details(response: Any) -> dict[str, Any]:
        usage = _response_value(response, "usage")
        if not usage:
            return {}

        if isinstance(usage, dict):
            usage_dict = dict(usage)
        elif hasattr(usage, "model_dump"):
            usage_dict = usage.model_dump(exclude_none=True)
        else:
            usage_dict = {
                key: value
                for key, value in vars(usage).items()
                if value is not None and not key.startswith("_")
            }

        return {
            key: _compact_token_detail(value)
            for key, value in usage_dict.items()
            if value is not None
        }

    @staticmethod
    def _cost_details(response: Any, model: str) -> dict[str, float]:
        hidden_params = _response_value(response, "_hidden_params")
        if isinstance(hidden_params, dict):
            response_cost = hidden_params.get("response_cost")
            if isinstance(response_cost, int | float):
                return {"total": float(response_cost)}

        try:
            cost = completion_cost(completion_response=response, model=model)
        except Exception as exc:
            logger.warning(
                "completion_cost_calculation_failed model=%s error_type=%s error=%s",
                model,
                exc.__class__.__name__,
                exc or "[no message]",
                exc_info=True,
            )
            return {}

        if isinstance(cost, int | float):
            return {"total": float(cost)}
        return {}


def _response_value(response: Any, key: str) -> Any:
    if isinstance(response, dict):
        return response.get(key)
    return getattr(response, key, None)


def _compact_token_detail(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: nested for key, nested in value.items() if nested is not None}
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    if hasattr(value, "__dict__"):
        return {
            key: nested
            for key, nested in vars(value).items()
            if nested is not None and not key.startswith("_")
        }
    return value
