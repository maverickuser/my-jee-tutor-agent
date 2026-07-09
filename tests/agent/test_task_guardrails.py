import json
import unittest
from unittest.mock import Mock

from jee_tutor.agent.task_guardrails import (
    GuardrailFailureCategory,
    GuardrailRetryCategory,
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

        result = evaluate_diagnosis_task_output(
            diagnosis_json(),
            tool_call_state=successful_state(),
            expected_image_count=1,
            taxonomy_validator=lambda diagnosis: Result(),
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.failure_category, "unknown_topic")
        self.assertEqual(result.retry_category, GuardrailRetryCategory.SEMANTIC_VISION_RETRY)
        self.assertNotIn("subjects", result.message)


if __name__ == "__main__":
    unittest.main()
