import os
from typing import Optional

from crewai import Agent, Crew, Process, Task
from crewai.tools import BaseTool
from litellm import completion
from pydantic import BaseModel, Field


class VisionInput(BaseModel):
    image_data_uri: str = Field(
        ...,
        description="A data URI containing the uploaded question image.",
    )
    user_prompt: str = Field(
        ...,
        description="The pedagogical instructions the vision model must follow.",
    )


class VisionAnalysisTool(BaseTool):
    name: str = "jee_question_vision_analyzer"
    description: str = (
        "Analyzes an uploaded IIT JEE question attempt image with a vision-capable LLM "
        "and returns coaching-style feedback."
    )
    args_schema: type[BaseModel] = VisionInput

    def _resolve_model_settings(self) -> dict:
        model = os.getenv("VISION_MODEL", "openai/gpt-4o")
        api_base = os.getenv("LITELLM_BASE_URL")

        if model.startswith("openai/"):
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LITELLM_API_KEY")
        elif model.startswith("gemini/") or model.startswith("google/"):
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("LITELLM_API_KEY")
        else:
            api_key = os.getenv("LITELLM_API_KEY")

        if not api_key:
            raise ValueError(
                "No API key configured for the selected VISION_MODEL. Set OPENAI_API_KEY, "
                "GOOGLE_API_KEY, or LITELLM_API_KEY."
            )

        settings = {
            "model": model,
            "api_key": api_key,
        }
        if api_base:
            settings["api_base"] = api_base

        return settings

    def _run(self, image_data_uri: str, user_prompt: str) -> str:
        model_settings = self._resolve_model_settings()

        request_kwargs = {
            **model_settings,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an elite IIT JEE instructor for Physics, Chemistry, "
                        "and Mathematics. Diagnose the student's thinking, distinguish "
                        "between conceptual and calculation mistakes, and teach with "
                        "helpful hints instead of revealing the final answer outright."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_uri},
                        },
                    ],
                },
            ],
            "temperature": 0.2,
        }

        response = completion(**request_kwargs)
        return response["choices"][0]["message"]["content"].strip()


def build_tutor_crew() -> Crew:
    vision_tool = VisionAnalysisTool()

    tutor_agent = Agent(
        role="IIT JEE Instructor",
        goal=(
            "Help the student understand why their attempt failed and guide them "
            "toward the right next step without directly solving the whole problem."
        ),
        backstory=(
            "You are a veteran IIT JEE faculty member who can read handwritten "
            "work, recognize exam patterns, and tailor hints to student mistakes."
        ),
        tools=[vision_tool],
        verbose=True,
        allow_delegation=False,
    )

    diagnosis_task = Task(
        description=(
            "Use the provided question image to identify the topic, infer the student's "
            "mistake, and produce a short teaching note. You must use the "
            "jee_question_vision_analyzer tool to inspect the uploaded image.\n\n"
            "Follow this structure exactly:\n"
            "1. Subject and topic\n"
            "2. Error type: conceptual or calculation\n"
            "3. Evidence from the attempt\n"
            "4. Two to three hints that move the student forward\n"
            "5. One recommended revision habit\n\n"
            "Image payload: {image_data_uri}\n"
            "Optional context: {question_context}"
        ),
        expected_output=(
            "A concise, coaching-style analysis that diagnoses the error and provides "
            "useful hints without revealing the complete final answer."
        ),
        agent=tutor_agent,
    )

    return Crew(
        agents=[tutor_agent],
        tasks=[diagnosis_task],
        process=Process.sequential,
        verbose=True,
    )


def run_tutor_workflow(
    image_data_uri: str,
    question_context: Optional[str] = None,
) -> str:
    crew = build_tutor_crew()
    result = crew.kickoff(
        inputs={
            "image_data_uri": image_data_uri,
            "question_context": question_context or "No additional context provided.",
        }
    )
    return str(result).strip()
