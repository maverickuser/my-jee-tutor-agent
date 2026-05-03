from crewai import Agent, Task

from agents.tutor_agent.prompt_provider import PromptProvider
from agents.tutor_agent.prompts import (
    TUTOR_AGENT_ROLE,
    DIAGNOSIS_TASK_DESCRIPTION,
    DIAGNOSIS_TASK_EXPECTED_OUTPUT,
    TUTOR_AGENT_BACKSTORY,
    TUTOR_AGENT_GOAL,
)
from agents.tutor_agent.tools import VisionAnalysisTool


def build_tutor_agent(
    vision_tool: VisionAnalysisTool,
    prompt_provider: PromptProvider | None = None,
) -> Agent:
    prompts = prompt_provider or PromptProvider()
    return Agent(
        role=TUTOR_AGENT_ROLE,
        goal=prompts.get(TUTOR_AGENT_GOAL).text,
        backstory=prompts.get(TUTOR_AGENT_BACKSTORY).text,
        tools=[vision_tool],
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
