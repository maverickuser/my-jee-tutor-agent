from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import json
import logging
from typing import Any, Protocol, TYPE_CHECKING, Tuple

from jee_tutor.agent.diagnosis_output import parse_and_validate_diagnosis
from jee_tutor.agent.output_validation import OutputValidationError

if TYPE_CHECKING:
    from jee_tutor.agent.tools import VisionToolCallState


logger = logging.getLogger(__name__)


class GuardrailFailureCategory(StrEnum):
    EMPTY_OUTPUT = "empty_output"
    MISSING_TOOL_OBSERVATION = "missing_tool_observation"
    NON_JSON_OUTPUT = "non_json_output"
    CANONICAL_MISMATCH = "canonical_mismatch"
    SCHEMA_INVALID = "schema_invalid"
    QUESTION_COUNT_MISMATCH = "question_count_mismatch"
    QUESTION_NUMBER_MISMATCH = "question_number_mismatch"
    DUPLICATE_QUESTION_NUMBER = "duplicate_question_number"
    TAXONOMY_MISMATCH = "curriculum_taxonomy_mismatch"
    UNEXPECTED_ERROR = "unexpected_error"


class GuardrailRetryCategory(StrEnum):
    CACHED_FINALIZATION_RETRY = "cached_finalization_retry"
    SEMANTIC_VISION_RETRY = "semantic_vision_retry"
    NON_RETRYABLE = "non_retryable"


@dataclass(frozen=True)
class DiagnosisTaskGuardrailResult:
    passed: bool
    message: str
    failure_category: GuardrailFailureCategory | str | None = None
    retry_category: GuardrailRetryCategory | None = None
    canonical_match: bool | None = None
    schema_valid: bool | None = None
    actual_question_count: int | None = None
    details: dict[str, Any] | None = None

    def as_crewai_result(self) -> Tuple[bool, Any]:
        return self.passed, self.message


class CurriculumValidator(Protocol):
    def validate(self, diagnosis: Any) -> Any: ...


def build_diagnosis_task_guardrail(
    *,
    tool_call_state: VisionToolCallState,
    expected_image_count: int,
    expected_question_numbers: list[str | None] | None = None,
    taxonomy_validator: CurriculumValidator | Callable[[Any], Any] | None = None,
    invocation_id: str | None = None,
) -> Callable[[object], Tuple[bool, Any]]:
    def diagnosis_task_guardrail(output: object) -> Tuple[bool, Any]:
        result = evaluate_diagnosis_task_output(
            output,
            tool_call_state=tool_call_state,
            expected_image_count=expected_image_count,
            expected_question_numbers=expected_question_numbers,
            taxonomy_validator=taxonomy_validator,
            invocation_id=invocation_id,
        )
        return result.as_crewai_result()

    # CrewAI validates guardrail callbacks with inspect.signature() and does not
    # resolve postponed annotations from `from __future__ import annotations`.
    diagnosis_task_guardrail.__annotations__["return"] = Tuple[bool, Any]
    return diagnosis_task_guardrail


def evaluate_diagnosis_task_output(
    output: object,
    *,
    tool_call_state: VisionToolCallState,
    expected_image_count: int,
    expected_question_numbers: list[str | None] | None = None,
    taxonomy_validator: CurriculumValidator | Callable[[Any], Any] | None = None,
    invocation_id: str | None = None,
) -> DiagnosisTaskGuardrailResult:
    raw = extract_task_output_text(output)
    if not raw:
        result = DiagnosisTaskGuardrailResult(
            passed=False,
            message="Diagnosis task returned empty output.",
            failure_category=GuardrailFailureCategory.EMPTY_OUTPUT,
            retry_category=GuardrailRetryCategory.NON_RETRYABLE,
        )
        _log_guardrail_check(result, tool_call_state, expected_image_count, invocation_id)
        return result

    if not getattr(tool_call_state, "success", False) or not getattr(
        tool_call_state, "observation", None
    ):
        result = DiagnosisTaskGuardrailResult(
            passed=False,
            message="Diagnosis task completed without a successful vision tool observation.",
            failure_category=GuardrailFailureCategory.MISSING_TOOL_OBSERVATION,
            retry_category=GuardrailRetryCategory.NON_RETRYABLE,
        )
        _log_guardrail_check(result, tool_call_state, expected_image_count, invocation_id)
        return result

    if not raw.lstrip().startswith("{"):
        result = DiagnosisTaskGuardrailResult(
            passed=False,
            message=(
                "VALIDATION_ERROR: non_json_output. Return exactly the JSON observation "
                "from jee_question_vision_analyzer."
            ),
            failure_category=GuardrailFailureCategory.NON_JSON_OUTPUT,
            retry_category=GuardrailRetryCategory.CACHED_FINALIZATION_RETRY,
        )
        _log_guardrail_check(result, tool_call_state, expected_image_count, invocation_id)
        return result

    observation = str(tool_call_state.observation)
    observation_validation = _validate_observation(
        observation,
        expected_image_count=expected_image_count,
        expected_question_numbers=expected_question_numbers,
        taxonomy_validator=taxonomy_validator,
    )
    if not observation_validation.passed:
        _reject_observation(tool_call_state, str(observation_validation.failure_category))
        _log_guardrail_check(
            observation_validation,
            tool_call_state,
            expected_image_count,
            invocation_id,
        )
        return observation_validation

    try:
        canonical_output = canonical_json(raw)
        canonical_observation = canonical_json(observation)
    except Exception as exc:
        result = DiagnosisTaskGuardrailResult(
            passed=False,
            message=f"Diagnosis task output failed schema validation: {safe_error_summary(exc)}",
            failure_category=GuardrailFailureCategory.SCHEMA_INVALID,
            retry_category=GuardrailRetryCategory.CACHED_FINALIZATION_RETRY,
            schema_valid=False,
        )
        _log_guardrail_check(result, tool_call_state, expected_image_count, invocation_id)
        return result

    if canonical_output != canonical_observation:
        result = DiagnosisTaskGuardrailResult(
            passed=False,
            message=(
                "VALIDATION_ERROR: canonical_mismatch. Return exactly the JSON observation "
                "from jee_question_vision_analyzer."
            ),
            failure_category=GuardrailFailureCategory.CANONICAL_MISMATCH,
            retry_category=GuardrailRetryCategory.CACHED_FINALIZATION_RETRY,
            canonical_match=False,
            schema_valid=True,
            actual_question_count=observation_validation.actual_question_count,
        )
        _log_guardrail_check(result, tool_call_state, expected_image_count, invocation_id)
        return result

    result = DiagnosisTaskGuardrailResult(
        passed=True,
        message=raw,
        canonical_match=True,
        schema_valid=True,
        actual_question_count=observation_validation.actual_question_count,
    )
    _mark_observation_valid(tool_call_state)
    _log_guardrail_check(result, tool_call_state, expected_image_count, invocation_id)
    return result


def extract_task_output_text(output: object) -> str:
    raw = getattr(output, "raw", None)
    if isinstance(raw, str):
        return raw.strip()
    if raw is not None:
        return str(raw).strip()
    if output is None:
        return ""
    return str(output).strip()


def canonical_json(value: str) -> str:
    return json.dumps(json.loads(value), sort_keys=True, separators=(",", ":"))


def safe_error_summary(exc: Exception) -> str:
    message = str(exc).strip() or "[no message]"
    return f"{exc.__class__.__name__}: {message[:240]}"


def _validate_observation(
    observation: str,
    *,
    expected_image_count: int,
    expected_question_numbers: list[str | None] | None,
    taxonomy_validator: CurriculumValidator | Callable[[Any], Any] | None,
) -> DiagnosisTaskGuardrailResult:
    try:
        diagnosis = parse_and_validate_diagnosis(
            observation,
            expected_image_count=expected_image_count,
            expected_question_numbers=expected_question_numbers,
        )
    except OutputValidationError as exc:
        category = _category_from_output_validation(exc)
        return DiagnosisTaskGuardrailResult(
            passed=False,
            message=(
                f"VALIDATION_ERROR: {category}. Re-run the vision analyzer once "
                "for the current invocation images."
            ),
            failure_category=category,
            retry_category=GuardrailRetryCategory.SEMANTIC_VISION_RETRY,
            schema_valid=False,
        )

    taxonomy_result = _validate_taxonomy(taxonomy_validator, diagnosis)
    if taxonomy_result is not None:
        return taxonomy_result

    return DiagnosisTaskGuardrailResult(
        passed=True,
        message=observation,
        schema_valid=True,
        actual_question_count=len(diagnosis.questions),
    )


def _category_from_output_validation(exc: OutputValidationError) -> GuardrailFailureCategory:
    text = " ".join([str(exc), *getattr(exc, "details", [])]).casefold()
    if "duplicate" in text:
        return GuardrailFailureCategory.DUPLICATE_QUESTION_NUMBER
    if "question number" in text or "image order" in text:
        return GuardrailFailureCategory.QUESTION_NUMBER_MISMATCH
    if "count" in text:
        return GuardrailFailureCategory.QUESTION_COUNT_MISMATCH
    return GuardrailFailureCategory.SCHEMA_INVALID


def _validate_taxonomy(
    taxonomy_validator: CurriculumValidator | Callable[[Any], Any] | None,
    diagnosis: Any,
) -> DiagnosisTaskGuardrailResult | None:
    if taxonomy_validator is None:
        return None
    try:
        if callable(taxonomy_validator) and not hasattr(taxonomy_validator, "validate"):
            result = taxonomy_validator(diagnosis)
        else:
            result = taxonomy_validator.validate(diagnosis)  # type: ignore[union-attr]
    except Exception as exc:
        category = getattr(exc, "category", GuardrailFailureCategory.TAXONOMY_MISMATCH)
        return DiagnosisTaskGuardrailResult(
            passed=False,
            message=(
                f"VALIDATION_ERROR: {category}. The diagnosis topic must match the "
                "approved JEE curriculum taxonomy. Re-run the vision analyzer once and "
                "choose chapter/topic labels from the approved taxonomy."
            ),
            failure_category=str(category),
            retry_category=GuardrailRetryCategory.SEMANTIC_VISION_RETRY,
            schema_valid=True,
            actual_question_count=len(diagnosis.questions),
            details=getattr(exc, "details", None),
        )
    valid = bool(getattr(result, "valid", result is None or result is True))
    if valid:
        return None
    category = getattr(result, "category", GuardrailFailureCategory.TAXONOMY_MISMATCH)
    return DiagnosisTaskGuardrailResult(
        passed=False,
        message=(
            f"VALIDATION_ERROR: {category}. The diagnosis topic must match the "
            "approved JEE curriculum taxonomy. Re-run the vision analyzer once and "
            "choose chapter/topic labels from the approved taxonomy."
        ),
        failure_category=str(category),
        retry_category=GuardrailRetryCategory.SEMANTIC_VISION_RETRY,
        schema_valid=True,
        actual_question_count=len(diagnosis.questions),
        details=getattr(result, "details", None),
    )


def _reject_observation(tool_call_state: VisionToolCallState, category: str) -> None:
    reject = getattr(tool_call_state, "reject_observation", None)
    if callable(reject):
        reject(category)
        return
    setattr(tool_call_state, "observation_rejected", True)
    setattr(tool_call_state, "observation_rejection_category", category)


def _mark_observation_valid(tool_call_state: VisionToolCallState) -> None:
    mark_valid = getattr(tool_call_state, "mark_observation_valid", None)
    if callable(mark_valid):
        mark_valid()
        return
    setattr(tool_call_state, "observation_validated", True)
    setattr(tool_call_state, "observation_rejected", False)


def _log_guardrail_check(
    result: DiagnosisTaskGuardrailResult,
    tool_call_state: VisionToolCallState,
    expected_image_count: int,
    invocation_id: str | None,
) -> None:
    invocation_id_value = invocation_id or "unknown"
    task_name = "diagnosis_task"
    guardrail_name = "diagnosis_task_output_contract"
    tool_call_count = getattr(tool_call_state, "request_count", getattr(tool_call_state, "call_count", 0))
    tool_execution_count = getattr(tool_call_state, "execution_count", 0)
    tool_success = getattr(tool_call_state, "success", False)
    tool_observation_present = bool(getattr(tool_call_state, "observation", None))
    detail_question_number = _detail(result, "question_number")
    detail_chapter = _detail(result, "chapter")
    detail_topic = _detail(result, "topic")
    detail_normalized_chapter = _detail(result, "normalized_chapter")
    detail_normalized_topic = _detail(result, "normalized_topic")
    detail_taxonomy_version = _detail(result, "taxonomy_version")

    logger.info(
        "crewai_task_guardrail_check event=%s invocation_id=%s task_name=%s "
        "guardrail_name=%s result=%s failure_category=%s retry_category=%s "
        "expected_image_count=%s actual_question_count=%s "
        "expected_question_number_count=%s tool_call_count=%s tool_execution_count=%s "
        "tool_success=%s tool_observation_present=%s canonical_match=%s schema_valid=%s",
        "crewai_task_guardrail_check",
        invocation_id_value,
        task_name,
        guardrail_name,
        "passed" if result.passed else "failed",
        result.failure_category,
        result.retry_category,
        expected_image_count,
        result.actual_question_count,
        expected_image_count,
        tool_call_count,
        tool_execution_count,
        tool_success,
        tool_observation_present,
        result.canonical_match,
        result.schema_valid,
    )
    if not result.passed:
        logger.error(
            "crewai_task_guardrail_failed event=%s invocation_id=%s task_name=%s "
            "guardrail_name=%s failure_category=%s retry_category=%s "
            "expected_image_count=%s actual_question_count=%s "
            "expected_question_number_count=%s tool_call_count=%s tool_execution_count=%s "
            "tool_success=%s tool_observation_present=%s canonical_match=%s schema_valid=%s "
            "detail_question_number=%s detail_chapter=%s detail_topic=%s "
            "detail_normalized_chapter=%s detail_normalized_topic=%s detail_taxonomy_version=%s",
            "crewai_task_guardrail_failed",
            invocation_id_value,
            task_name,
            guardrail_name,
            result.failure_category,
            result.retry_category,
            expected_image_count,
            result.actual_question_count,
            expected_image_count,
            tool_call_count,
            tool_execution_count,
            tool_success,
            tool_observation_present,
            result.canonical_match,
            result.schema_valid,
            detail_question_number,
            detail_chapter,
            detail_topic,
            detail_normalized_chapter,
            detail_normalized_topic,
            detail_taxonomy_version,
        )


def _detail(result: DiagnosisTaskGuardrailResult, key: str) -> Any:
    return result.details.get(key) if isinstance(result.details, dict) else None
