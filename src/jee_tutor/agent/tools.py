import logging
from dataclasses import dataclass

from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.prompts import VISION_TOOL_DESCRIPTION


logger = logging.getLogger(__name__)


@dataclass
class VisionToolCallState:
    called: bool = False
    success: bool = False
    call_count: int = 0
    successful_call_count: int = 0
    image_count: int = 0
    image_source: str = ""
    error: str | None = None
    first_error: str | None = None


class VisionInput(BaseModel):
    image_data_uris: list[str] = Field(
        default_factory=list,
        description=(
            "Optional image data URIs. Leave this as an empty list to analyze the "
            "preloaded invocation images."
        ),
    )


class VisionAnalysisTool(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "jee_question_vision_analyzer"
    description: str = (
        f"{VISION_TOOL_DESCRIPTION} Call this tool with an empty JSON object, "
        "for example {}. The uploaded attempt images are already preloaded."
    )
    args_schema: type[BaseModel] = VisionInput
    llm_client: VisionLLMClient = Field(default_factory=VisionLLMClient, exclude=True)
    preloaded_image_data_uris: list[str] = Field(default_factory=list, exclude=True)
    call_state: VisionToolCallState = Field(
        default_factory=VisionToolCallState,
        exclude=True,
    )

    def _run(
        self,
        image_data_uris: list[str] | None = None,
    ) -> str:
        self.call_state.called = True
        self.call_state.call_count += 1
        if self.call_state.call_count > 1:
            duplicate_error = "Vision analyzer must be called exactly once per workflow."
            self.call_state.error = duplicate_error
            if self.call_state.first_error is None:
                self.call_state.first_error = duplicate_error
            raise RuntimeError(duplicate_error)

        resolved_images, image_source = self._resolve_tool_images(image_data_uris or [])
        self._log_tool_context(
            image_source=image_source,
            image_count=len(resolved_images),
        )
        self.call_state.image_count = len(resolved_images)
        self.call_state.image_source = image_source
        if not resolved_images:
            self.call_state.error = "Vision analyzer received no images."
            self.call_state.first_error = self.call_state.error
            raise ValueError(
                "Vision analyzer received no images. Provide image_data_uri or image_s3_prefix "
                "in the invocation payload."
            )
        try:
            analysis = self.llm_client.analyze_vision(resolved_images)
            self.call_state.success = True
            self.call_state.successful_call_count += 1
            self.call_state.error = None
            return analysis
        except Exception as exc:
            self.call_state.error = f"{exc.__class__.__name__}: {exc or '[no message]'}"
            if self.call_state.first_error is None:
                self.call_state.first_error = self.call_state.error
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

    def run_preloaded(self) -> str:
        return self._run()

    def _resolve_tool_images(self, image_data_uris: list[str]) -> tuple[list[str], str]:
        if self.preloaded_image_data_uris:
            if image_data_uris:
                logger.warning(
                    "ignoring_tool_supplied_images_for_preloaded_invocation "
                    "tool_image_count=%s preloaded_image_count=%s",
                    len(image_data_uris),
                    len(self.preloaded_image_data_uris),
                )
            return self.preloaded_image_data_uris, "preloaded_invocation_images"

        valid_images = [image for image in image_data_uris if image.startswith("data:image/")]
        if valid_images:
            return valid_images, "tool_input_data_uris"
        if image_data_uris:
            return image_data_uris, "tool_input_non_data_uris"
        return [], "empty_tool_input"

    @staticmethod
    def _log_tool_context(
        *,
        image_source: str,
        image_count: int,
    ) -> None:
        logger.info(
            "jee_question_vision_analyzer image_source=%s image_count=%s",
            image_source,
            image_count,
        )


def build_vision_tool(
    llm_client: VisionLLMClient | None = None,
    image_data_uris: list[str] | None = None,
    call_state: VisionToolCallState | None = None,
) -> VisionAnalysisTool:
    return VisionAnalysisTool(
        result_as_answer=True,
        llm_client=llm_client or VisionLLMClient(),
        preloaded_image_data_uris=image_data_uris or [],
        call_state=call_state or VisionToolCallState(),
    )
