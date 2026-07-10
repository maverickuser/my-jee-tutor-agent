import json
import inspect
from typing import Any, Tuple, get_type_hints
import unittest
from unittest.mock import Mock

from jee_tutor.agent.task_guardrails import (
    GuardrailFailureCategory,
    GuardrailRetryCategory,
    build_diagnosis_task_guardrail,
    canonical_json,
    evaluate_diagnosis_task_output,
    extract_task_output_text,
)
from jee_tutor.agent.tools import VisionToolCallState, ToolExecutionStatus
from tests.agent.test_diagnosis_output import question


def diagnosis_json(*questions):
    return json.dumps({"questions": list(questions) or [question()]})


def successful_state(observation: str | None = None) -> VisionToolCallState:
    return VisionToolCallState(
        status=ToolExecutionStatus.SUCCEEDED,
        called=True,
        success=True,
        call_count=1,
        successful_call_count=1,
        execution_count=1,
        image_count=1,
        image_source="preloaded_invocation_images",
        observation=observation or diagnosis_json(),
    )


class DiagnosisTaskGuardrailTest(unittest.TestCase):
    def test_extract_task_output_prefers_raw_attribute(self):
        self.assertEqual(extract_task_output_text(Mock(raw=" value ")), "value")
        self.assertEqual(extract_task_output_text(" text "), "text")
        self.assertEqual(extract_task_output_text(None), "")

    def test_crewai_guardrail_callback_uses_required_return_annotation(self):
        guardrail = build_diagnosis_task_guardrail(
            tool_call_state=successful_state(),
            expected_image_count=1,
        )

        self.assertEqual(get_type_hints(guardrail)["return"], Tuple[bool, Any])
        self.assertEqual(inspect.signature(guardrail).return_annotation, Tuple[bool, Any])

    def test_canonical_json_ignores_object_key_order(self):
        self.assertEqual(canonical_json('{"b":2,"a":1}'), canonical_json('{"a":1,"b":2}'))

    def test_empty_output_is_non_retryable(self):
        result = evaluate_diagnosis_task_output(
            "",
            tool_call_state=successful_state(),
            expected_image_count=1,
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.message, "Diagnosis task returned empty output.")
        self.assertEqual(result.failure_category, GuardrailFailureCategory.EMPTY_OUTPUT)
        self.assertEqual(result.retry_category, GuardrailRetryCategory.NON_RETRYABLE)

    def test_failed_guardrail_emits_error_log(self):
        with self.assertLogs("jee_tutor.agent.task_guardrails", level="ERROR") as logs:
            result = evaluate_diagnosis_task_output(
                "",
                tool_call_state=successful_state(),
                expected_image_count=1,
                invocation_id="inv-123",
            )

        self.assertFalse(result.passed)
        self.assertTrue(any("crewai_task_guardrail_failed" in line for line in logs.output))
        self.assertTrue(any("invocation_id=inv-123" in line for line in logs.output))
        self.assertTrue(any("failure_category=empty_output" in line for line in logs.output))

    def test_successful_guardrail_does_not_emit_error_log(self):
        observation = diagnosis_json()
        with self.assertNoLogs("jee_tutor.agent.task_guardrails", level="ERROR"):
            result = evaluate_diagnosis_task_output(
                observation,
                tool_call_state=successful_state(observation),
                expected_image_count=1,
                expected_question_numbers=["6"],
            )

        self.assertTrue(result.passed)

    def test_missing_tool_observation_is_non_retryable(self):
        result = evaluate_diagnosis_task_output(
            diagnosis_json(),
            tool_call_state=VisionToolCallState(called=True),
            expected_image_count=1,
        )

        self.assertFalse(result.passed)
        self.assertEqual(
            result.message,
            "Diagnosis task completed without a successful vision tool observation.",
        )
        self.assertEqual(
            result.failure_category,
            GuardrailFailureCategory.MISSING_TOOL_OBSERVATION,
        )
        self.assertEqual(result.retry_category, GuardrailRetryCategory.NON_RETRYABLE)

    def test_non_json_final_output_uses_cached_finalization_retry(self):
        result = evaluate_diagnosis_task_output(
            "| Question Number | Chapter |",
            tool_call_state=successful_state(),
            expected_image_count=1,
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.failure_category, GuardrailFailureCategory.NON_JSON_OUTPUT)
        self.assertEqual(
            result.retry_category,
            GuardrailRetryCategory.CACHED_FINALIZATION_RETRY,
        )
        self.assertIn("Return exactly the JSON observation", result.message)

    def test_canonical_mismatch_uses_cached_finalization_retry(self):
        observation = diagnosis_json()
        modified = diagnosis_json(question(topic="Capacitors"))

        result = evaluate_diagnosis_task_output(
            modified,
            tool_call_state=successful_state(observation),
            expected_image_count=1,
            expected_question_numbers=["6"],
        )

        self.assertFalse(result.passed)
        self.assertEqual(
            result.failure_category,
            GuardrailFailureCategory.CANONICAL_MISMATCH,
        )
        self.assertEqual(
            result.retry_category,
            GuardrailRetryCategory.CACHED_FINALIZATION_RETRY,
        )
        self.assertFalse(result.canonical_match)

    def test_valid_output_passes_and_marks_observation_valid(self):
        observation = diagnosis_json()
        state = successful_state(observation)

        result = evaluate_diagnosis_task_output(
            observation,
            tool_call_state=state,
            expected_image_count=1,
            expected_question_numbers=["6"],
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.message, observation)
        self.assertTrue(state.observation_validated)
        self.assertFalse(state.observation_rejected)

    def test_invalid_observation_maps_count_to_semantic_retry(self):
        state = successful_state(diagnosis_json())

        result = evaluate_diagnosis_task_output(
            diagnosis_json(),
            tool_call_state=state,
            expected_image_count=2,
        )

        self.assertFalse(result.passed)
        self.assertEqual(
            result.failure_category,
            GuardrailFailureCategory.QUESTION_COUNT_MISMATCH,
        )
        self.assertEqual(result.retry_category, GuardrailRetryCategory.SEMANTIC_VISION_RETRY)
        self.assertTrue(state.observation_rejected)
        self.assertEqual(
            state.observation_rejection_category,
            GuardrailFailureCategory.QUESTION_COUNT_MISMATCH,
        )

    def test_invalid_observation_maps_question_number_to_semantic_retry(self):
        state = successful_state(diagnosis_json(question("7")))

        result = evaluate_diagnosis_task_output(
            diagnosis_json(question("7")),
            tool_call_state=state,
            expected_image_count=1,
            expected_question_numbers=["6"],
        )

        self.assertFalse(result.passed)
        self.assertEqual(
            result.failure_category,
            GuardrailFailureCategory.QUESTION_NUMBER_MISMATCH,
        )

    def test_invalid_observation_maps_duplicate_to_semantic_retry(self):
        state = successful_state(diagnosis_json(question("6"), question("6")))

        result = evaluate_diagnosis_task_output(
            diagnosis_json(question("6"), question("6")),
            tool_call_state=state,
            expected_image_count=2,
        )

        self.assertFalse(result.passed)
        self.assertEqual(
            result.failure_category,
            GuardrailFailureCategory.DUPLICATE_QUESTION_NUMBER,
        )

    def test_taxonomy_failure_is_semantic_retry_without_taxonomy_content(self):
        class Result:
            valid = False
            category = "unknown_topic"
            details = {
                "question_number": "36",
                "chapter": "Coordinate Geometry",
                "topic": "Unknown topic",
                "normalized_chapter": "coordinate geometry",
                "normalized_topic": "unknown topic",
                "taxonomy_version": "2026-02",
            }

        with self.assertLogs("jee_tutor.agent.task_guardrails", level="ERROR") as logs:
            result = evaluate_diagnosis_task_output(
                diagnosis_json(),
                tool_call_state=successful_state(),
                expected_image_count=1,
                taxonomy_validator=lambda diagnosis: Result(),
            )

        self.assertFalse(result.passed)
        self.assertEqual(result.failure_category, "unknown_topic")
        self.assertEqual(result.details, Result.details)
        self.assertEqual(result.retry_category, GuardrailRetryCategory.SEMANTIC_VISION_RETRY)
        self.assertNotIn("subjects", result.message)
        joined_logs = "\n".join(logs.output)
        self.assertIn("detail_question_number=36", joined_logs)
        self.assertIn("detail_chapter=Coordinate Geometry", joined_logs)
        self.assertIn("detail_topic=Unknown topic", joined_logs)
        self.assertIn("detail_normalized_topic=unknown topic", joined_logs)
        self.assertIn("detail_taxonomy_version=2026-02", joined_logs)


if __name__ == "__main__":
    unittest.main()
