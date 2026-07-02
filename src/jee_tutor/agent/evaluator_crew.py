from crewai import Agent, Crew, Process, Task
from crewai.llms.base_llm import BaseLLM


def build_final_evaluator_agent(llm: BaseLLM) -> Agent:
    return Agent(
        role="JEE diagnosis quality evaluator",
        goal="Evaluate grounding and diagnostic quality using only current images.",
        backstory="You independently audit diagnosis claims against visible evidence.",
        tools=[],
        llm=llm,
        allow_delegation=False,
        allow_code_execution=False,
        max_iter=1,
        max_retry_limit=0,
        verbose=False,
    )


def build_final_evaluation_task(agent: Agent) -> Task:
    return Task(
        description=(
            "Evaluate the supplied structured diagnosis against the current invocation images. "
            "Return only the required structured assessment and do not provide a decision."
        ),
        expected_output="A schema-valid evaluator assessment.",
        agent=agent,
        tools=[],
    )


def build_final_evaluator_crew(llm: BaseLLM) -> Crew:
    agent = build_final_evaluator_agent(llm)
    return Crew(
        agents=[agent],
        tasks=[build_final_evaluation_task(agent)],
        process=Process.sequential,
        memory=False,
        verbose=False,
    )
