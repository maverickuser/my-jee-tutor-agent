"""Model configuration shared by profile embedding adjudication."""

from __future__ import annotations

from copy import deepcopy
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jee_tutor.agent.config_loader import LLMConfig
from jee_tutor.agent.model_config import DEFAULT_LLM_TIMEOUT_SECONDS


DEFAULT_PROFILE_CLASSIFIER_MODEL = "gemini/gemini-2.5-pro"


class ProfileClassifierModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    api_key: str | None = None
    api_base: str | None = None
    completion_options: dict[str, Any] | None = None

    def to_litellm_kwargs(self) -> dict[str, Any]:
        kwargs = deepcopy(self.completion_options) if self.completion_options else {}
        kwargs["model"] = self.model
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        return kwargs


class ProfileClassifierModelConfig:
    def __init__(
        self,
        *,
        environ: dict[str, str] | None = None,
        config: Any | None = None,
    ):
        self.environ = environ or os.environ
        self.config = config or LLMConfig.load()

    def resolve(self) -> ProfileClassifierModelSettings:
        model = (
            self.environ.get("PROFILE_SEMANTIC_CLUSTER_MODEL")
            or _config_get(self.config, "semantic_clustering", "model")
            or DEFAULT_PROFILE_CLASSIFIER_MODEL
        )
        completion_options = _config_section(self.config, "completion")
        completion_options.setdefault("timeout", DEFAULT_LLM_TIMEOUT_SECONDS)
        return ProfileClassifierModelSettings(
            model=model,
            api_key=_api_key_for_model(model, self.environ),
            api_base=self.environ.get("LITELLM_BASE_URL")
            or _config_get(self.config, "litellm", "api_base"),
            completion_options=completion_options,
        )


def _api_key_for_model(model: str, environ: dict[str, str]) -> str | None:
    normalized = model.casefold()
    if normalized.startswith("openai/"):
        return environ.get("OPENAI_API_KEY") or environ.get("LITELLM_API_KEY")
    if normalized.startswith("gemini/"):
        return environ.get("GOOGLE_API_KEY") or environ.get("LITELLM_API_KEY")
    return environ.get("LITELLM_API_KEY") or None


def _config_section(config: Any, section: str) -> dict[str, Any]:
    if hasattr(config, "section"):
        return config.section(section)
    value = config.get(section, {})
    return dict(value) if isinstance(value, dict) else {}


def _config_get(
    config: Any,
    section: str,
    key: str,
    default: Any = None,
) -> Any:
    if hasattr(config, "section"):
        return config.get(section, key, default)
    value = config.get(section, {})
    if not isinstance(value, dict):
        return default
    return value.get(key, default)


__all__ = [
    "ProfileClassifierModelConfig",
    "ProfileClassifierModelSettings",
]
