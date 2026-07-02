from collections.abc import Sequence
from typing import Any

from crewai import Agent, LLM, Task
from crewai.llms.base_llm import BaseLLM

from jee_tutor.agent.model_config import VisionModelConfig
from jee_tutor.agent.prompt_provider import PromptProvider
from jee_tutor.agent.prompts import (
    TUTOR_AGENT_ROLE,
    DIAGNOSIS_TASK_DESCRIPTION,
    TUTOR_AGENT_BACKSTORY,
    TUTOR_AGENT_GOAL,
)
from jee_tutor.agent.rate_limit import gemini_rate_limiter, is_gemini_model
from jee_tutor.agent.tools import VisionAnalysisTool


MANDATORY_VISION_TOOL_INSTRUCTION = """

MANDATORY RUNTIME STEP:
- Before producing any final answer, call `jee_question_vision_analyzer` exactly once as the
  first action.
- Call it with an empty JSON object. The current invocation images are preloaded.
- Do not infer, reconstruct, or answer any question before the tool observation is returned.
- Treat the tool observation as the only source of question content.
- Return the tool observation byte-for-byte without rewriting, reordering, or adding content.
- A duplicate request only replays the same observation and cannot produce a different answer.
- If the tool fails, do not produce a generic or guessed answer.
"""

MANDATORY_VISION_TOOL_ACTION = """Thought: I must analyze the preloaded invocation images.
Action: jee_question_vision_analyzer
Action Input: {}"""

STRUCTURED_OBSERVATION_EXPECTED_OUTPUT = """The final answer must be exactly the JSON
observation returned by `jee_question_vision_analyzer`. Return it byte-for-byte without
rewriting, reordering, adding, removing, repairing, or converting any field. Do not return
Markdown or commentary."""


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
) -> Agent:
    prompts = prompt_provider or PromptProvider()
    tools = [vision_tool]
    agent_llm = MandatoryVisionToolLLM(llm or build_crewai_llm())
    return Agent(
        role=TUTOR_AGENT_ROLE,
        goal=prompts.get(TUTOR_AGENT_GOAL).text,
        backstory=prompts.get(TUTOR_AGENT_BACKSTORY).text,
        tools=tools,
        llm=agent_llm,
        verbose=False,
        allow_delegation=False,
        max_iter=3,
        max_retry_limit=0,
        allow_code_execution=False,
    )


def build_diagnosis_task(
    tutor_agent: Agent,
    vision_tool: VisionAnalysisTool,
    prompt_provider: PromptProvider | None = None,
) -> Task:
    prompts = prompt_provider or PromptProvider()
    description = (
        prompts.get(DIAGNOSIS_TASK_DESCRIPTION).text.rstrip()
        + MANDATORY_VISION_TOOL_INSTRUCTION
    )
    return Task(
        description=description,
        expected_output=STRUCTURED_OBSERVATION_EXPECTED_OUTPUT,
        agent=tutor_agent,
        tools=[vision_tool],
    )


def build_crewai_llm(model_config: VisionModelConfig | None = None) -> LLM | BaseLLM:
    settings = (model_config or VisionModelConfig()).resolve()
    kwargs = settings.to_litellm_kwargs()
    model = kwargs.pop("model")
    llm = LLM(model=model, **kwargs)
    if is_gemini_model(model):
        return RateLimitedLLM(llm)
    return llm


class MandatoryVisionToolLLM(BaseLLM):
    """Force CrewAI's first ReAct step to execute the preloaded vision tool."""

    def __init__(self, llm: LLM | BaseLLM, max_calls: int = 2):
        model = _first_string_attribute(llm, "model", "model_name", "deployment_name", "name")
        temperature = _first_numeric_attribute(llm, "temperature")
        super().__init__(model=model or str(llm), temperature=temperature)
        self.llm = llm
        self.stop = _normalize_stop_sequences(getattr(llm, "stop", []))
        self._vision_tool_requested = False
        self.max_calls = max_calls
        self.call_count = 0

    def call(
        self,
        messages: Any,
        tools: list[dict] | None = None,
        callbacks: list[Any] | None = None,
        available_functions: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        self.call_count += 1
        if self.call_count > self.max_calls:
            raise OrchestrationCallBudgetError(
                f"CrewAI diagnosis exceeded its {self.max_calls}-call orchestration budget."
            )
        if not self._vision_tool_requested:
            self._vision_tool_requested = True
            return MANDATORY_VISION_TOOL_ACTION
        return self.llm.call(
            messages,
            tools=tools,
            callbacks=callbacks,
            available_functions=available_functions,
            **kwargs,
        )

    def supports_stop_words(self) -> bool:
        supports_stop_words = getattr(self.llm, "supports_stop_words", None)
        return bool(supports_stop_words()) if callable(supports_stop_words) else False

    def supports_function_calling(self) -> bool:
        supports_function_calling = getattr(self.llm, "supports_function_calling", None)
        return bool(supports_function_calling()) if callable(supports_function_calling) else False

    def get_context_window_size(self) -> int:
        get_context_window_size = getattr(self.llm, "get_context_window_size", None)
        if callable(get_context_window_size):
            return int(get_context_window_size())
        return super().get_context_window_size()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.llm, name)


class OrchestrationCallBudgetError(RuntimeError):
    pass


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
        **kwargs: Any,
    ) -> Any:
        try:
            return gemini_rate_limiter.call(
                self.llm.call,
                messages,
                tools=tools,
                callbacks=callbacks,
                available_functions=available_functions,
                **kwargs,
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
