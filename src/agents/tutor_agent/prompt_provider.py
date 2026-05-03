from dataclasses import dataclass
from typing import Any

from agents.tutor_agent.config_loader import LLMConfig
from agents.tutor_agent.observability import LangfuseObservability
from agents.tutor_agent.prompts import LOCAL_PROMPT_FALLBACKS


@dataclass(frozen=True)
class ResolvedPrompt:
    key: str
    text: str
    langfuse_prompt: Any | None = None


class PromptProvider:
    def __init__(
        self,
        config: LLMConfig | None = None,
        observability: LangfuseObservability | None = None,
    ):
        self.config = config or LLMConfig.load()
        self.observability = observability or LangfuseObservability(self.config)

    def get(self, key: str) -> ResolvedPrompt:
        fallback = LOCAL_PROMPT_FALLBACKS[key]
        prompt_name = self.config.get("langfuse.prompts", key)
        text, langfuse_prompt = self.observability.get_text_prompt(prompt_name, fallback)
        return ResolvedPrompt(key=key, text=text, langfuse_prompt=langfuse_prompt)
