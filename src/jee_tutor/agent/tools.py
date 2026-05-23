import logging

from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.prompts import VISION_TOOL_DESCRIPTION


logger = logging.getLogger(__name__)


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
        resolved_images, image_source = self._resolve_tool_images(image_data_uris or [])
        self._log_tool_context(
            image_source=image_source,
            image_count=len(resolved_images),
            user_prompt=user_prompt,
        )
        if not resolved_images:
            raise ValueError(
                "Vision analyzer received no images. Provide image_data_uri, image_data_uris, "
                "image_folder, image_s3_uri, image_s3_prefix, or media with type=image."
            )
        try:
            return self.llm_client.analyze_vision(resolved_images, user_prompt)
        except Exception as exc:
            logger.exception(
                "vision_analyzer_failed image_source=%s image_count=%s error_type=%s error=%s",
                image_source,
                len(resolved_images),
                exc.__class__.__name__,
                exc or "[no message]",
            )
            raise RuntimeError(
                "Vision analyzer failed after resolving "
                f"{len(resolved_images)} image(s) from {image_source}. "
                f"Upstream error: {exc.__class__.__name__}: {exc or '[no message]'}"
            ) from exc

    def _resolve_tool_images(self, image_data_uris: list[str]) -> tuple[list[str], str]:
        valid_images = [image for image in image_data_uris if image.startswith("data:image/")]
        if valid_images:
            return valid_images, "tool_input_data_uris"
        if self.preloaded_image_data_uris:
            return self.preloaded_image_data_uris, "preloaded_invocation_images"
        if image_data_uris:
            return image_data_uris, "tool_input_non_data_uris"
        return [], "empty_tool_input"

    @staticmethod
    def _log_tool_context(
        *,
        image_source: str,
        image_count: int,
        user_prompt: str,
    ) -> None:
        logger.info(
            "jee_question_vision_analyzer image_source=%s image_count=%s user_prompt_chars=%s",
            image_source,
            image_count,
            len(user_prompt),
        )


def build_vision_tool(
    llm_client: VisionLLMClient | None = None,
    image_data_uris: list[str] | None = None,
) -> VisionAnalysisTool:
    return VisionAnalysisTool(
        llm_client=llm_client or VisionLLMClient(),
        preloaded_image_data_uris=image_data_uris or [],
    )
