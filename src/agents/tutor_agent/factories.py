from typing import Any

from crewai import Agent, LLM, Task

from agents.tutor_agent.model_config import VisionModelConfig
from agents.tutor_agent.prompt_provider import PromptProvider
from agents.tutor_agent.prompts import (
    TUTOR_AGENT_ROLE,
    DIAGNOSIS_TASK_DESCRIPTION,
    DIAGNOSIS_TASK_EXPECTED_OUTPUT,
    TUTOR_AGENT_BACKSTORY,
    TUTOR_AGENT_GOAL,
)
from agents.tutor_agent.rate_limit import gemini_rate_limiter, is_gemini_model
from agents.tutor_agent.tools import VisionAnalysisTool


def build_tutor_agent(
    vision_tool: VisionAnalysisTool,
    prompt_provider: PromptProvider | None = None,
    llm: Any | None = None,
) -> Agent:
    prompts = prompt_provider or PromptProvider()
    return Agent(
        role=TUTOR_AGENT_ROLE,
        goal=prompts.get(TUTOR_AGENT_GOAL).text,
        backstory=prompts.get(TUTOR_AGENT_BACKSTORY).text,
        tools=[vision_tool],
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


def build_crewai_llm(model_config: VisionModelConfig | None = None) -> LLM:
    settings = (model_config or VisionModelConfig()).resolve()
    kwargs = settings.to_litellm_kwargs()
    model = kwargs.pop("model")
    llm = LLM(model=model, **kwargs)
    if is_gemini_model(model):
        return RateLimitedLLM(llm)
    return llm


class RateLimitedLLM:
    def __init__(self, llm: LLM):
        self.llm = llm

    def call(self, *args: Any, **kwargs: Any) -> Any:
        return gemini_rate_limiter.call(self.llm.call, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.llm, name)
