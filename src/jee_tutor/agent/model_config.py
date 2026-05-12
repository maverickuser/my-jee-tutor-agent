import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from jee_tutor.agent.config_loader import LLMConfig


@dataclass(frozen=True)
class ModelSettings:
    model: str
    api_key: str | None = None
    api_base: str | None = None
    aws_region_name: str | None = None
    completion_options: dict[str, Any] | None = None

    def to_litellm_kwargs(self) -> dict[str, Any]:
        kwargs = deepcopy(self.completion_options) if self.completion_options else {}
        kwargs["model"] = self.model
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.aws_region_name:
            kwargs["aws_region_name"] = self.aws_region_name
        return kwargs


class VisionModelConfig:
    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        config: LLMConfig | None = None,
    ):
        self.environ = environ if environ is not None else os.environ
        self.config = config or LLMConfig.load(self.environ.get("LLM_CONFIG_FILE"))

    def resolve(self) -> ModelSettings:
        model = self._setting("VISION_MODEL", "vision", "model", "openai/gpt-4o")
        api_base = self._setting("LITELLM_BASE_URL", "litellm", "api_base")
        completion_options = self.config.section("completion")

        if self._uses_aws_credentials(model):
            return ModelSettings(
                model=model,
                aws_region_name=self._setting("AWS_REGION", "aws", "region")
                or self.environ.get("AWS_DEFAULT_REGION"),
                completion_options=completion_options,
            )

        api_key = self._resolve_api_key(model)
        if not api_key:
            raise ValueError(
                "No API key configured for the selected VISION_MODEL. Set OPENAI_API_KEY, "
                "GOOGLE_API_KEY, or LITELLM_API_KEY."
            )

        return ModelSettings(
            model=model,
            api_key=api_key,
            api_base=api_base,
            completion_options=completion_options,
        )

    def _setting(
        self,
        env_key: str,
        config_section: str,
        config_key: str,
        default: str | None = None,
    ) -> str | None:
        return self.environ.get(env_key) or self.config.get(config_section, config_key, default)

    def _resolve_api_key(self, model: str) -> str | None:
        if model.startswith("openai/"):
            return self.environ.get("OPENAI_API_KEY") or self.environ.get("LITELLM_API_KEY")
        if model.startswith("gemini/") or model.startswith("google/"):
            return self.environ.get("GOOGLE_API_KEY") or self.environ.get("LITELLM_API_KEY")
        return self.environ.get("LITELLM_API_KEY")

    @staticmethod
    def _uses_aws_credentials(model: str) -> bool:
        return model.startswith("bedrock/") or model.startswith("amazon/")
