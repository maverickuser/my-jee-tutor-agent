from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from agents.tutor_agent.llm_client import VisionLLMClient
from agents.tutor_agent.prompts import VISION_TOOL_DESCRIPTION


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
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "jee_question_vision_analyzer"
    description: str = VISION_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = VisionInput
    llm_client: VisionLLMClient = Field(default_factory=VisionLLMClient, exclude=True)

    def _run(self, image_data_uri: str, user_prompt: str) -> str:
        return self.llm_client.analyze_vision(image_data_uri, user_prompt)


def build_vision_tool(llm_client: VisionLLMClient | None = None) -> VisionAnalysisTool:
    return VisionAnalysisTool(llm_client=llm_client or VisionLLMClient())
