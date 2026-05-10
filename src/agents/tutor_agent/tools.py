from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from agents.tutor_agent.llm_client import VisionLLMClient
from agents.tutor_agent.prompts import VISION_TOOL_DESCRIPTION


DEFAULT_VISION_USER_PROMPT = (
    "Analyze the provided IIT JEE question attempt image(s). For each question that is "
    "wrong, unattempted, or partially correct, return a markdown table with columns: "
    "| Question Number | Chapter | Topic | What You Thought | Why That Thought Is Wrong | "
    "Exact Concept Gap | What You Must Deep-Dive |"
)


class VisionInput(BaseModel):
    image_data_uris: list[str] = Field(
        ...,
        description="Data URIs containing the uploaded question images.",
    )
    user_prompt: str = Field(
        default=DEFAULT_VISION_USER_PROMPT,
        description="The pedagogical instructions the vision model must follow.",
    )


class VisionAnalysisTool(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "jee_question_vision_analyzer"
    description: str = VISION_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = VisionInput
    llm_client: VisionLLMClient = Field(default_factory=VisionLLMClient, exclude=True)

    def _run(
        self, image_data_uris: list[str], user_prompt: str = DEFAULT_VISION_USER_PROMPT
    ) -> str:
        return self.llm_client.analyze_vision(image_data_uris, user_prompt)


def build_vision_tool(llm_client: VisionLLMClient | None = None) -> VisionAnalysisTool:
    return VisionAnalysisTool(llm_client=llm_client or VisionLLMClient())
