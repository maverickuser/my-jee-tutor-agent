import unittest
from unittest.mock import Mock, patch

from scripts.run_agent_evals import _run_case_with_retries


class RunAgentEvalsTest(unittest.TestCase):
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
