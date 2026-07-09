import logging
from datetime import datetime, timezone
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from jee_tutor.agent.diagnosis_output import (
    DiagnosisResponse,
    parse_and_validate_diagnosis,
)
from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.output_validation import REQUIRED_MARKDOWN_COLUMNS, OutputValidationError
from jee_tutor.agent.prompts import VISION_TOOL_DESCRIPTION
from jee_tutor.application.vision import VisionDiagnosisService
from jee_tutor.invocation.models import AgentLLMCallRecord, AgentLLMCallStatus
from jee_tutor.invocation.status_store import InvocationStatusStore


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
    observation_validated: bool = False
    observation_rejected: bool = False
    observation_rejection_category: str | None = None
    semantic_retry_count: int = 0
    semantic_retry_budget: int = 1
    cached_replay_count: int = 0
    observation_replaced_count: int = 0
    semantic_retry_exhausted_count: int = 0
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

    @property
    def semantic_retry_budget_remaining(self) -> int:
        return max(self.semantic_retry_budget - self.semantic_retry_count, 0)

    def mark_observation_valid(self) -> None:
        self.observation_validated = True
        self.observation_rejected = False
        self.observation_rejection_category = None

    def reject_observation(self, category: str) -> None:
        self.observation_validated = False
        self.observation_rejected = True
        self.observation_rejection_category = category
        logger.info(
            "vision_observation_rejected category=%s semantic_retry_budget_remaining=%s",
            category,
            self.semantic_retry_budget_remaining,
        )

    def can_replay_cached_observation(self) -> bool:
        return (
            self.status == ToolExecutionStatus.SUCCEEDED
            and self.observation is not None
            and not self.observation_rejected
        )

    def can_execute_semantic_retry(self) -> bool:
        return (
            self.status == ToolExecutionStatus.SUCCEEDED
            and self.observation is not None
            and self.observation_rejected
            and self.semantic_retry_count < self.semantic_retry_budget
        )

    def begin_execution(self) -> None:
        self.status = ToolExecutionStatus.RUNNING
        self.execution_count += 1

    def begin_semantic_retry(self) -> None:
        self.semantic_retry_count += 1
        self.begin_execution()
        logger.info(
            "vision_semantic_retry_started semantic_retry_count=%s "
            "semantic_retry_budget=%s rejection_category=%s",
            self.semantic_retry_count,
            self.semantic_retry_budget,
            self.observation_rejection_category,
        )

    def mark_execution_success(self, observation: str, transport_attempt_count: int) -> None:
        replacing_rejected_observation = self.observation_rejected
        self.transport_attempt_count = transport_attempt_count
        self.status = ToolExecutionStatus.SUCCEEDED
        self.success = True
        self.successful_call_count += 1
        self.error = None
        self.error_snapshot = None
        self.observation = observation
        self.observation_validated = False
        self.observation_rejected = False
        self.observation_rejection_category = None
        if replacing_rejected_observation:
            self.observation_replaced_count += 1
            logger.info(
                "vision_observation_replaced observation_replaced_count=%s",
                self.observation_replaced_count,
            )


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
    max_images_per_call: int = Field(default=3, exclude=True)
    invocation_id: str | None = Field(default=None, exclude=True)
    status_store: Any = Field(default=None, exclude=True)
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
            analysis = self._analyze_images_in_batches(resolved_images)
            with self.call_state._condition:
                self.call_state.mark_execution_success(
                    analysis,
                    getattr(self.llm_client, "transport_attempt_count", 0),
                )
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

    def _analyze_images_in_batches(self, resolved_images: list[str]) -> str:
        batch_sizes = [
            len(resolved_images[start : start + self.max_images_per_call])
            for start in range(0, len(resolved_images), self.max_images_per_call)
        ]
        batch_index = 0

        def analyze_batch(
            batch_images: list[str],
            batch_expected_question_numbers: list[str | None] | None,
        ) -> str:
            nonlocal batch_index
            current_batch_index = batch_index
            batch_index += 1
            return self._analyze_batch(
                batch_images,
                batch_expected_question_numbers,
                batch_index=current_batch_index,
            )

        batch_outputs = VisionDiagnosisService(analyze_batch).analyze(
            resolved_images,
            expected_question_numbers=self.expected_question_numbers,
            max_images_per_call=self.max_images_per_call,
        )
        return self._merge_batch_outputs(batch_outputs, batch_sizes, len(resolved_images))

    def _analyze_batch(
        self,
        resolved_images: list[str],
        expected_question_numbers: list[str | None] | None,
        *,
        batch_index: int,
    ) -> str:
        started_at = datetime.now(timezone.utc)
        if expected_question_numbers:
            try:
                result = self.llm_client.analyze_vision(
                    resolved_images,
                    expected_question_numbers=expected_question_numbers,
                )
            except Exception as exc:
                self._record_llm_call(
                    started_at=started_at,
                    ended_at=datetime.now(timezone.utc),
                    batch_index=batch_index,
                    batch_size=len(resolved_images),
                    attempt_number=max(getattr(self.llm_client, "transport_attempt_count", 1), 1),
                    status=AgentLLMCallStatus.FAILED,
                    error_type=exc.__class__.__name__,
                    error_message=str(exc) or "[no message]",
                )
                raise
            self._record_llm_call(
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
                batch_index=batch_index,
                batch_size=len(resolved_images),
                attempt_number=max(getattr(self.llm_client, "transport_attempt_count", 1), 1),
                status=AgentLLMCallStatus.SUCCEEDED,
            )
            return result
        try:
            result = self.llm_client.analyze_vision(resolved_images)
        except Exception as exc:
            self._record_llm_call(
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
                batch_index=batch_index,
                batch_size=len(resolved_images),
                attempt_number=max(getattr(self.llm_client, "transport_attempt_count", 1), 1),
                status=AgentLLMCallStatus.FAILED,
                error_type=exc.__class__.__name__,
                error_message=str(exc) or "[no message]",
            )
            raise
        self._record_llm_call(
            started_at=started_at,
            ended_at=datetime.now(timezone.utc),
            batch_index=batch_index,
            batch_size=len(resolved_images),
            attempt_number=max(getattr(self.llm_client, "transport_attempt_count", 1), 1),
            status=AgentLLMCallStatus.SUCCEEDED,
        )
        return result

    def _record_llm_call(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
        batch_index: int,
        batch_size: int,
        attempt_number: int,
        status: AgentLLMCallStatus,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if self.status_store is None or self.invocation_id is None:
            return
        duration_ms = max(int((ended_at - started_at).total_seconds() * 1000), 0)
        model_name = (
            getattr(self.llm_client, "model", None)
            or getattr(self.llm_client, "model_name", None)
            or getattr(self.llm_client, "deployment_name", None)
            or getattr(self.llm_client, "name", None)
            or "unknown"
        )
        provider = model_name.split("/", 1)[0] if "/" in model_name else "unknown"
        self.status_store.append_llm_call(
            self.invocation_id,
            AgentLLMCallRecord(
                llm_call_id=uuid.uuid4().hex,
                batch_index=batch_index,
                batch_size=batch_size,
                model=model_name,
                provider=provider,
                purpose="vision_analysis",
                status=status,
                attempt_number=attempt_number,
                started_at=started_at.isoformat(),
                ended_at=ended_at.isoformat(),
                duration_ms=duration_ms,
                error_type=error_type,
                error_message=error_message,
            ),
        )

    def _merge_batch_outputs(
        self,
        batch_outputs: list[str],
        batch_sizes: list[int],
        expected_image_count: int,
    ) -> str:
        if not batch_outputs:
            raise RuntimeError("Vision analyzer produced no batch outputs.")

        if all(self._looks_like_json(output) for output in batch_outputs):
            questions = []
            for output, batch_size in zip(batch_outputs, batch_sizes, strict=True):
                diagnosis = parse_and_validate_diagnosis(
                    output,
                    expected_image_count=batch_size,
                )
                questions.extend(diagnosis.questions)
            merged = DiagnosisResponse(questions=questions)
            if len(merged.questions) != expected_image_count:
                raise OutputValidationError(
                    "Batched structured diagnosis question count mismatch.",
                    [
                        f"Resolved image count: {expected_image_count}.",
                        f"Actual question count: {len(merged.questions)}.",
                    ],
                )
            return merged.model_dump_json()

        if all(self._looks_like_markdown(output) for output in batch_outputs):
            headers: list[str] | None = None
            rows: list[list[str]] = []
            for output in batch_outputs:
                parsed_headers, parsed_rows = self._parse_markdown_table(output)
                headers = headers or parsed_headers
                rows.extend(parsed_rows)
            return self._render_markdown_table(headers or REQUIRED_MARKDOWN_COLUMNS, rows)

        if len(batch_outputs) == 1:
            return batch_outputs[0]

        raise OutputValidationError(
            "Batched vision outputs must all be JSON or markdown tables.",
            [
                f"Resolved image count: {expected_image_count}.",
                f"Batch count: {len(batch_outputs)}.",
            ],
        )

    def _claim_execution(self) -> bool:
        with self.call_state._condition:
            self.call_state.called = True
            self.call_state.call_count += 1
            if self.call_state.status == ToolExecutionStatus.NOT_STARTED:
                self.call_state.begin_execution()
                return True
            if self.call_state.can_execute_semantic_retry():
                self.call_state.begin_semantic_retry()
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
                and self.call_state.can_replay_cached_observation()
            ):
                self.call_state.cached_replay_count += 1
                return self.call_state.observation
            if (
                self.call_state.status == ToolExecutionStatus.SUCCEEDED
                and self.call_state.observation_rejected
            ):
                self.call_state.semantic_retry_exhausted_count += 1
                logger.warning(
                    "vision_semantic_retry_exhausted category=%s "
                    "semantic_retry_count=%s semantic_retry_budget=%s",
                    self.call_state.observation_rejection_category,
                    self.call_state.semantic_retry_count,
                    self.call_state.semantic_retry_budget,
                )
                raise RuntimeError(
                    "Vision analyzer semantic retry budget exhausted for rejected "
                    f"observation: {self.call_state.observation_rejection_category or 'unknown'}"
                )
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

    @staticmethod
    def _looks_like_json(output: str) -> bool:
        return output.lstrip().startswith("{")

    @staticmethod
    def _looks_like_markdown(output: str) -> bool:
        stripped = output.lstrip()
        return stripped.startswith("|") and stripped.count("\n") >= 2

    @staticmethod
    def _parse_markdown_table(markdown: str) -> tuple[list[str], list[list[str]]]:
        table_lines = [
            line.strip()
            for line in markdown.splitlines()
            if line.strip().startswith("|") and "|" in line.strip()[1:]
        ]
        if len(table_lines) < 3:
            raise OutputValidationError("Analysis output is not a markdown table.")
        headers = VisionAnalysisTool._split_markdown_row(table_lines[0])
        rows = [
            cells
            for cells in (VisionAnalysisTool._split_markdown_row(line) for line in table_lines[2:])
            if cells and not VisionAnalysisTool._is_separator_cells(cells)
        ]
        return headers, rows

    @staticmethod
    def _render_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
        header_cells = headers or REQUIRED_MARKDOWN_COLUMNS
        lines = [
            "| " + " | ".join(header_cells) + " |",
            "| " + " | ".join("---" for _ in header_cells) + " |",
        ]
        for row in rows:
            cells = [VisionAnalysisTool._escape_markdown_cell(cell) for cell in row]
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines)

    @staticmethod
    def _split_markdown_row(line: str) -> list[str]:
        cells: list[str] = []
        current: list[str] = []
        escaped = False
        for character in line.strip().strip("|"):
            if escaped:
                current.append(character)
                escaped = False
            elif character == "\\":
                current.append(character)
                escaped = True
            elif character == "|":
                cells.append("".join(current).strip())
                current = []
            else:
                current.append(character)
        cells.append("".join(current).strip())
        return cells

    @staticmethod
    def _is_separator_cells(cells: list[str]) -> bool:
        import re

        return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)

    @staticmethod
    def _escape_markdown_cell(value: str) -> str:
        import re

        normalized = re.sub(r"\s*\r?\n\s*", " ", value.strip())
        return normalized.replace("\\", "\\\\").replace("|", "\\|")


def build_vision_tool(
    llm_client: VisionLLMClient | None = None,
    image_data_uris: list[str] | None = None,
    call_state: VisionToolCallState | None = None,
    expected_question_numbers: list[str | None] | None = None,
    max_images_per_call: int = 3,
    invocation_id: str | None = None,
    status_store: InvocationStatusStore | None = None,
) -> VisionAnalysisTool:
    return VisionAnalysisTool(
        result_as_answer=True,
        llm_client=llm_client or VisionLLMClient(),
        preloaded_image_data_uris=image_data_uris or [],
        expected_question_numbers=expected_question_numbers or [],
        max_images_per_call=max_images_per_call,
        invocation_id=invocation_id,
        status_store=status_store,
        call_state=call_state or VisionToolCallState(),
    )
