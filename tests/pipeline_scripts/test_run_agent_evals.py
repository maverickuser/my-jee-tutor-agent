import unittest
from unittest.mock import Mock, patch

from scripts.run_agent_evals import (
    _enforce_eval_gate,
    _image_input_payload,
    _retryable_response_error_reason,
    _run_case,
    _run_case_with_retries,
    _score_markdown_table_case,
)


class RunAgentEvalsTest(unittest.TestCase):
    def test_score_markdown_table_case_passes_required_columns_and_rows(self):
        case = {
            "id": "coaching_structure",
            "type": "markdown_table",
            "required_columns": [
                "Question Number",
                "Chapter",
                "Topic",
                "What You Thought",
                "Why That Thought Is Wrong",
                "Exact Concept Gap",
                "What You Must Deep-Dive",
            ],
            "min_required_columns": 7,
            "min_data_rows": 1,
        }
        response = {
            "analysis": (
                "| Question Number | Chapter | Topic | What You Thought | "
                "Why That Thought Is Wrong | Exact Concept Gap | What You Must Deep-Dive |\n"
                "| --- | --- | --- | --- | --- | --- | --- |\n"
                "| Q1 | Parabola | Focal chord | Used area directly | Missed chord relation | "
                "Focal chord geometry | Revise focal chord properties |"
            )
        }

        result = _score_markdown_table_case(case, response)

        self.assertTrue(result["passed"])
        self.assertEqual(result["data_row_count"], 1)
        self.assertEqual(len(result["matched_columns"]), 7)

    def test_score_markdown_table_case_fails_missing_columns(self):
        case = {
            "id": "coaching_structure",
            "type": "markdown_table",
            "required_columns": ["Question Number", "Chapter", "Exact Concept Gap"],
            "min_required_columns": 3,
            "min_data_rows": 1,
        }
        response = {"analysis": ("| Question Number | Chapter |\n| --- | --- |\n| Q1 | Parabola |")}

        result = _score_markdown_table_case(case, response)

        self.assertFalse(result["passed"])
        self.assertEqual(result["matched_columns"], ["Question Number", "Chapter"])

    def test_run_case_retries_retryable_errors(self):
        case = {"id": "case-1", "type": "analysis"}
        sleep = Mock()

        with patch(
            "scripts.run_agent_evals._run_case",
            side_effect=[
                Exception("APIConnectionError: Server disconnected without sending a response."),
                {"id": "case-1", "type": "analysis", "passed": True},
            ],
        ) as run_case:
            result = _run_case_with_retries(
                case,
                "images",
                max_attempts=3,
                backoff_seconds=10.0,
                sleep=sleep,
            )

        self.assertTrue(result["passed"])
        self.assertEqual(run_case.call_count, 2)
        sleep.assert_called_once_with(10.0)

    def test_run_case_returns_failed_result_after_retry_exhaustion(self):
        case = {"id": "case-1", "type": "analysis"}

        with patch(
            "scripts.run_agent_evals._run_case",
            side_effect=Exception("APIConnectionError: Server disconnected"),
        ):
            result = _run_case_with_retries(
                case,
                "images",
                max_attempts=2,
                backoff_seconds=10.0,
                sleep=Mock(),
            )

        self.assertFalse(result["passed"])
        self.assertTrue(result["skipped"])
        self.assertTrue(result["transient_error"])
        self.assertEqual(result["id"], "case-1")
        self.assertEqual(result["exception_type"], "Exception")
        self.assertIn("2 attempt", result["reason"])

    def test_retryable_handler_error_response_is_detected(self):
        response = {
            "error": "Tutor workflow failed while analyzing images.",
            "details": [
                "Resolved image count: 1.",
                "Exception type: APIConnectionError.",
                "Exception message: Server disconnected without sending a response.",
            ],
        }

        reason = _retryable_response_error_reason(response)

        self.assertIsNotNone(reason)
        self.assertIn("workflow failed before producing analysis", reason)

    def test_workflow_failure_without_transient_provider_details_is_not_retryable(self):
        response = {
            "error": "Tutor workflow failed while analyzing images.",
            "details": [
                "Resolved image count: 1.",
                "Question context provided: True.",
                "Exception type: RuntimeError.",
                "Exception message: [no message]",
            ],
        }

        reason = _retryable_response_error_reason(response)

        self.assertIsNone(reason)

    def test_run_case_scores_deterministic_workflow_failure_as_failed(self):
        case = {
            "id": "coaching_structure",
            "type": "markdown_table",
            "task": "diagnose wrong answers",
        }
        response = {
            "error": "Tutor workflow failed while analyzing images.",
            "details": ["Exception message: [no message]"],
        }

        with patch("jee_tutor.handler.handle_tutor_invocation", return_value=response):
            result = _run_case(case, "images")

        self.assertFalse(result["passed"])
        self.assertNotIn("skipped", result)

    def test_eval_gate_fails_when_any_case_is_skipped(self):
        with self.assertRaisesRegex(SystemExit, "skipped 1 case"):
            _enforce_eval_gate(score=1.0, min_score=0.75, skipped=1)

    def test_eval_gate_accepts_complete_run_above_threshold(self):
        _enforce_eval_gate(score=1.0, min_score=0.75, skipped=0)

    def test_eval_gate_fails_complete_run_below_threshold(self):
        with self.assertRaisesRegex(SystemExit, "below required"):
            _enforce_eval_gate(score=0.5, min_score=0.75, skipped=0)

    def test_non_retryable_handler_error_response_is_not_transient(self):
        response = {
            "error": "Invalid tutor invocation payload.",
            "details": ["At least one image input is required."],
        }

        self.assertIsNone(_retryable_response_error_reason(response))

    def test_image_s3_prefix_overrides_local_fixture_data_uri(self):
        self.assertEqual(
            _image_input_payload(
                image_folder="tests/fixtures/image_folder",
                image_s3_prefix="s3://state-bucket/cd-evals-images/",
            ),
            {"image_s3_prefix": "s3://state-bucket/cd-evals-images/"},
        )

    def test_run_case_sends_s3_prefix_payload(self):
        case = {
            "id": "coaching_structure",
            "type": "markdown_table",
            "task": "diagnose wrong answers",
            "required_columns": ["Question Number"],
            "min_required_columns": 1,
            "min_data_rows": 1,
        }
        response = {
            "analysis": "| Question Number |\n| --- |\n| Q1 |",
        }

        with patch("jee_tutor.handler.handle_tutor_invocation", return_value=response) as handler:
            result = _run_case(case, {"image_s3_prefix": "s3://state-bucket/cd-evals-images/"})

        self.assertTrue(result["passed"])
        handler.assert_called_once()
        payload = handler.call_args.args[0]
        self.assertEqual(payload["image_s3_prefix"], "s3://state-bucket/cd-evals-images/")
        self.assertEqual(payload["task"], "diagnose wrong answers")
        self.assertFalse(payload["save_analysis_pdf"])
        self.assertNotIn("image_data_uri", payload)


if __name__ == "__main__":
    unittest.main()
