import unittest
from unittest.mock import Mock, patch

from scripts.run_agent_evals import _run_case_with_retries, _score_markdown_table_case


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


if __name__ == "__main__":
    unittest.main()
