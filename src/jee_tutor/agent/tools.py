import logging
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum

from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.prompts import VISION_TOOL_DESCRIPTION


logger = logging.getLogger(__name__)


class ToolExecutionStatus(StrEnum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class ExceptionSnapshot:
    error_type: str
    message: str

    @classmethod
    def from_exception(cls, exc: Exception) -> "ExceptionSnapshot":
        message = str(exc).strip() or "[no message]"
        return cls(error_type=exc.__class__.__name__, message=message[:500])

    def reconstruct(self) -> RuntimeError:
        return RuntimeError(f"Cached vision analyzer failure: {self.error_type}: {self.message}")


@dataclass
class VisionToolCallState:
    status: ToolExecutionStatus = ToolExecutionStatus.NOT_STARTED
    called: bool = False
    success: bool = False
    call_count: int = 0
    successful_call_count: int = 0
    execution_count: int = 0
    image_count: int = 0
    image_source: str = ""
    error: str | None = None
    first_error: str | None = None
    observation: str | None = None
    error_snapshot: ExceptionSnapshot | None = None
    transport_attempt_count: int = 0
    waiter_timeout_seconds: float = 30.0
    _condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.Lock()),
        repr=False,
    )

    @property
    def request_count(self) -> int:
        return self.call_count

    @property
    def successful_execution_count(self) -> int:
        return self.successful_call_count


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
    expected_question_numbers: list[str | None] = Field(default_factory=list, exclude=True)
    call_state: VisionToolCallState = Field(
        default_factory=VisionToolCallState,
        exclude=True,
    )

    def _run(
        self,
        image_data_uris: list[str] | None = None,
    ) -> str:
        should_execute = self._claim_execution()
        if not should_execute:
            return self._wait_for_or_replay()

        resolved_images, image_source = self._resolve_tool_images(image_data_uris or [])
        self._log_tool_context(
            image_source=image_source,
            image_count=len(resolved_images),
        )
        self.call_state.image_count = len(resolved_images)
        self.call_state.image_source = image_source
        if not resolved_images:
            error = ValueError(
                "Vision analyzer received no images. Provide image_data_uri or image_s3_prefix "
                "in the invocation payload."
            )
            self._cache_failure(error)
            raise error
        try:
            if self.expected_question_numbers:
                analysis = self.llm_client.analyze_vision(
                    resolved_images,
                    expected_question_numbers=self.expected_question_numbers,
                )
            else:
                analysis = self.llm_client.analyze_vision(resolved_images)
            with self.call_state._condition:
                self.call_state.transport_attempt_count = getattr(
                    self.llm_client,
                    "transport_attempt_count",
                    0,
                )
                self.call_state.status = ToolExecutionStatus.SUCCEEDED
                self.call_state.success = True
                self.call_state.successful_call_count += 1
                self.call_state.error = None
                self.call_state.observation = analysis
                self.call_state._condition.notify_all()
            return analysis
        except Exception as exc:
            self.call_state.transport_attempt_count = getattr(
                self.llm_client,
                "transport_attempt_count",
                0,
            )
            self._cache_failure(exc)
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

    def _claim_execution(self) -> bool:
        with self.call_state._condition:
            self.call_state.called = True
            self.call_state.call_count += 1
            if self.call_state.status == ToolExecutionStatus.NOT_STARTED:
                self.call_state.status = ToolExecutionStatus.RUNNING
                self.call_state.execution_count += 1
                return True
            return False

    def _wait_for_or_replay(self) -> str:
        deadline = time.monotonic() + self.call_state.waiter_timeout_seconds
        with self.call_state._condition:
            while self.call_state.status == ToolExecutionStatus.RUNNING:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for the in-flight vision analysis.")
                self.call_state._condition.wait(timeout=remaining)
            if (
                self.call_state.status == ToolExecutionStatus.SUCCEEDED
                and self.call_state.observation is not None
            ):
                return self.call_state.observation
            if self.call_state.error_snapshot is not None:
                raise self.call_state.error_snapshot.reconstruct()
            raise RuntimeError("Vision analyzer reached an invalid memoization state.")

    def _cache_failure(self, exc: Exception) -> None:
        snapshot = ExceptionSnapshot.from_exception(exc)
        with self.call_state._condition:
            self.call_state.status = ToolExecutionStatus.FAILED
            self.call_state.success = False
            self.call_state.error_snapshot = snapshot
            self.call_state.error = f"{snapshot.error_type}: {snapshot.message}"
            if self.call_state.first_error is None:
                self.call_state.first_error = self.call_state.error
            self.call_state._condition.notify_all()

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
    expected_question_numbers: list[str | None] | None = None,
) -> VisionAnalysisTool:
    return VisionAnalysisTool(
        result_as_answer=True,
        llm_client=llm_client or VisionLLMClient(),
        preloaded_image_data_uris=image_data_uris or [],
        expected_question_numbers=expected_question_numbers or [],
        call_state=call_state or VisionToolCallState(),
    )
