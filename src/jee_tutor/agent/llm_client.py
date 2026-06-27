from collections.abc import Callable
import logging
from typing import Any

from litellm import completion, completion_cost

from jee_tutor.agent.model_config import VisionModelConfig
from jee_tutor.agent.observability import LangfuseObservability
from jee_tutor.agent.prompt_provider import PromptProvider
from jee_tutor.agent.prompts import VISION_SYSTEM, VISION_USER
from jee_tutor.agent.rate_limit import (
    exception_status_code,
    gemini_rate_limiter,
    is_gemini_model,
)


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
        completion_fn: CompletionFunction | None = None,
    ):
        self.model_config = model_config or VisionModelConfig()
        self.observability = observability or LangfuseObservability()
        self.prompt_provider = prompt_provider or PromptProvider(observability=self.observability)
        self.message_factory = message_factory or VisionMessageFactory()
        self.completion_fn = completion_fn or completion

    def analyze_vision(
        self,
        image_data_uris: list[str] | str,
        user_prompt: str | None = None,
    ) -> str:
        model_settings = self.model_config.resolve()
        system_prompt = self.prompt_provider.get(VISION_SYSTEM)
        if user_prompt is None:
            user_prompt_text = self.prompt_provider.get(VISION_USER).text
        else:
            user_prompt_text = user_prompt

        request_kwargs = {
            **model_settings.to_litellm_kwargs(),
            "messages": self.message_factory.build(
                system_prompt=system_prompt.text,
                user_prompt=user_prompt_text,
                image_data_uris=image_data_uris,
            ),
        }
        request_kwargs = self._stateless_completion_kwargs(request_kwargs)

        response = self._complete_with_rate_limit(
            model_settings.model,
            request_kwargs,
            prompt=system_prompt.langfuse_prompt,
        )
        return response["choices"][0]["message"]["content"].strip()

    def _complete_with_rate_limit(
        self,
        model: str,
        request_kwargs: dict,
        *,
        prompt: Any = None,
    ) -> dict:
        if is_gemini_model(model):
            return gemini_rate_limiter.call_attempts(
                lambda attempt: self._complete_attempt(
                    model,
                    request_kwargs,
                    prompt=prompt,
                    attempt=attempt,
                    max_attempts=gemini_rate_limiter.max_attempts,
                )
            )
        return self._complete_attempt(
            model,
            request_kwargs,
            prompt=prompt,
            attempt=1,
            max_attempts=1,
        )

    def _complete_attempt(
        self,
        model: str,
        request_kwargs: dict,
        *,
        prompt: Any,
        attempt: int,
        max_attempts: int,
    ) -> dict:
        timeout_seconds = request_kwargs.get("timeout")
        logger.info(
            "llm_attempt=%s max_attempts=%s timeout_seconds=%s model=%s",
            attempt,
            max_attempts,
            timeout_seconds,
            model,
        )
        metadata = {
            "attempt": attempt,
            "max_attempts": max_attempts,
            "timeout_seconds": timeout_seconds,
        }
        with self.observability.generation_span(
            model=model,
            input_payload=self._redacted_generation_input(request_kwargs),
            prompt=prompt,
            metadata=metadata,
        ) as generation:
            try:
                response = self.completion_fn(**request_kwargs)
            except Exception as exc:
                if generation:
                    generation.update(
                        output={
                            "error_type": exc.__class__.__name__,
                            "status_code": exception_status_code(exc),
                        }
                    )
                raise

            analysis = response["choices"][0]["message"]["content"].strip()
            if generation:
                generation.update(
                    output=analysis,
                    **self._generation_accounting(response, model),
                )
            return response

    @staticmethod
    def _stateless_completion_kwargs(request_kwargs: dict) -> dict:
        stateless_kwargs = dict(request_kwargs)
        stateless_kwargs["caching"] = False
        stateless_kwargs["cache"] = {"no-cache": True}
        stateless_kwargs["num_retries"] = 0

        for key in ["cached_content", "cachedContent", "preset_cache_key"]:
            stateless_kwargs.pop(key, None)

        extra_body = stateless_kwargs.get("extra_body")
        if isinstance(extra_body, dict):
            stateless_extra_body = dict(extra_body)
            for key in ["cached_content", "cachedContent"]:
                stateless_extra_body.pop(key, None)
            stateless_kwargs["extra_body"] = stateless_extra_body

        return stateless_kwargs

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

        compacted = {
            key: _compact_token_detail(value)
            for key, value in usage_dict.items()
            if value is not None
        }
        normalized = {
            key: value
            for key, value in compacted.items()
            if key not in {"prompt_tokens", "completion_tokens", "total_tokens"}
        }
        aliases = {
            "prompt_tokens": "input",
            "completion_tokens": "output",
            "total_tokens": "total",
        }
        for source_key, target_key in aliases.items():
            if target_key not in normalized and source_key in compacted:
                normalized[target_key] = compacted[source_key]
        return normalized

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
