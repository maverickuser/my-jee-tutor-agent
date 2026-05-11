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
        default_factory=list,
        description=(
            "Optional image data URIs. The tool uses preloaded invocation images when this "
            "field is omitted or CrewAI supplies placeholder filenames."
        ),
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
    preloaded_image_data_uris: list[str] = Field(default_factory=list, exclude=True)

    def _run(
        self,
        image_data_uris: list[str] | None = None,
        user_prompt: str = DEFAULT_VISION_USER_PROMPT,
    ) -> str:
        resolved_images = self._resolve_tool_images(image_data_uris or [])
        return self.llm_client.analyze_vision(resolved_images, user_prompt)

    def _resolve_tool_images(self, image_data_uris: list[str]) -> list[str]:
        valid_images = [image for image in image_data_uris if image.startswith("data:image/")]
        if valid_images:
            return valid_images
        if self.preloaded_image_data_uris:
            return self.preloaded_image_data_uris
        return image_data_uris


def build_vision_tool(
    llm_client: VisionLLMClient | None = None,
    image_data_uris: list[str] | None = None,
) -> VisionAnalysisTool:
    return VisionAnalysisTool(
        llm_client=llm_client or VisionLLMClient(),
        preloaded_image_data_uris=image_data_uris or [],
    )
