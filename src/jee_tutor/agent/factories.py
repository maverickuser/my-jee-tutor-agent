from collections.abc import Sequence
from typing import Any

from crewai import Agent, LLM, Task
from crewai.llms.base_llm import BaseLLM

from jee_tutor.agent.model_config import VisionModelConfig
from jee_tutor.agent.prompt_provider import PromptProvider
from jee_tutor.agent.prompts import (
    TUTOR_AGENT_ROLE,
    DIAGNOSIS_TASK_DESCRIPTION,
    DIAGNOSIS_TASK_EXPECTED_OUTPUT,
    TUTOR_AGENT_BACKSTORY,
    TUTOR_AGENT_GOAL,
)
from jee_tutor.agent.rate_limit import gemini_rate_limiter, is_gemini_model
from jee_tutor.agent.tools import VisionAnalysisTool


def _first_string_attribute(obj: Any, *names: str) -> str | None:
    for name in names:
        value = getattr(obj, name, None)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def _first_numeric_attribute(obj: Any, *names: str) -> float | int | None:
    for name in names:
        value = getattr(obj, name, None)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return value
    return None


def _normalize_stop_sequences(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(item) for item in value if item is not None]
    return []


def _provider_from_model(model: str) -> str | None:
    if "/" not in model:
        return None
    return model.split("/", 1)[0]


def _format_llm_failure(
    *,
    operation: str,
    model: str,
    exc: Exception,
    support_note: str | None = None,
) -> str:
    parts = [f"{operation} failed for model={model}"]
    provider = _provider_from_model(model)
    if provider:
        parts.append(f"provider={provider}")

    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        parts.append(f"status_code={status_code}")

    message = str(exc) or "[no message]"
    parts.append(f"{exc.__class__.__name__}: {message}")

    litellm_debug_info = getattr(exc, "litellm_debug_info", None)
    if isinstance(litellm_debug_info, str) and litellm_debug_info.strip():
        parts.append(f"litellm_debug_info={litellm_debug_info.strip()}")

    cause = exc.__cause__ or exc.__context__
    if cause is not None:
        cause_message = str(cause) or "[no message]"
        parts.append(f"cause={cause.__class__.__name__}: {cause_message}")

    if support_note:
        parts.append(support_note)

    return ". ".join(parts) + "."


def build_tutor_agent(
    vision_tool: VisionAnalysisTool,
    prompt_provider: PromptProvider | None = None,
    llm: Any | None = None,
    extra_tools: list[Any] | None = None,
) -> Agent:
    prompts = prompt_provider or PromptProvider()
    tools = [vision_tool]
    tools.extend(extra_tools or [])
    return Agent(
        role=TUTOR_AGENT_ROLE,
        goal=prompts.get(TUTOR_AGENT_GOAL).text,
        backstory=prompts.get(TUTOR_AGENT_BACKSTORY).text,
        tools=tools,
        llm=llm or build_crewai_llm(),
        verbose=True,
        allow_delegation=False,
    )


def build_diagnosis_task(
    tutor_agent: Agent,
    prompt_provider: PromptProvider | None = None,
) -> Task:
    prompts = prompt_provider or PromptProvider()
    return Task(
        description=prompts.get(DIAGNOSIS_TASK_DESCRIPTION).text,
        expected_output=prompts.get(DIAGNOSIS_TASK_EXPECTED_OUTPUT).text,
        agent=tutor_agent,
    )


def build_crewai_llm(model_config: VisionModelConfig | None = None) -> LLM | BaseLLM:
    settings = (model_config or VisionModelConfig()).resolve()
    kwargs = settings.to_litellm_kwargs()
    model = kwargs.pop("model")
    llm = LLM(model=model, **kwargs)
    if is_gemini_model(model):
        return RateLimitedLLM(llm)
    return llm


class RateLimitedLLM(BaseLLM):
    def __init__(self, llm: LLM):
        model = _first_string_attribute(llm, "model", "model_name", "deployment_name", "name")
        temperature = _first_numeric_attribute(llm, "temperature")
        super().__init__(model=model or str(llm), temperature=temperature)
        self.llm = llm
        self.stop = _normalize_stop_sequences(getattr(llm, "stop", []))

    def call(
        self,
        messages: Any,
        tools: list[dict] | None = None,
        callbacks: list[Any] | None = None,
        available_functions: dict[str, Any] | None = None,
    ) -> Any:
        try:
            return gemini_rate_limiter.call(
                self.llm.call,
                messages,
                tools=tools,
                callbacks=callbacks,
                available_functions=available_functions,
            )
        except Exception as exc:
            raise RuntimeError(self._format_call_failure(exc)) from exc

    def supports_stop_words(self) -> bool:
        supports_stop_words = getattr(self.llm, "supports_stop_words", None)
        if callable(supports_stop_words):
            try:
                return bool(supports_stop_words())
            except Exception:
                return super().supports_stop_words()
        return super().supports_stop_words()

    def supports_function_calling(self) -> bool:
        supports_function_calling = getattr(self.llm, "supports_function_calling", None)
        if callable(supports_function_calling):
            try:
                return bool(supports_function_calling())
            except Exception:
                return False
        return False

    def get_context_window_size(self) -> int:
        get_context_window_size = getattr(self.llm, "get_context_window_size", None)
        if callable(get_context_window_size):
            try:
                return int(get_context_window_size())
            except Exception:
                return super().get_context_window_size()
        return super().get_context_window_size()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.llm, name)

    def _format_call_failure(self, exc: Exception) -> str:
        support_note = None
        if is_gemini_model(self.model):
            support_note = self._function_calling_support_note()
        return _format_llm_failure(
            operation="CrewAI agent LLM call",
            model=self.model,
            exc=exc,
            support_note=support_note,
        )

    def _function_calling_support_note(self) -> str | None:
        try:
            supports_function_calling = self.supports_function_calling()
        except Exception:
            return None

        if supports_function_calling:
            return None

        return (
            "LiteLLM reports supports_function_calling=False for this model. "
            "If the failure happens while selecting tools, switch to a "
            "function-calling-capable model or pass a dedicated "
            "function_calling_llm."
        )
