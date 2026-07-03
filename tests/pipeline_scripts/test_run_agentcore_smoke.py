import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from scripts.run_agentcore_smoke import (  # noqa: E402
    IN_PROGRESS_ERROR,
    invoke_runtime,
    invoke_until_terminal,
    main,
)


class RunAgentCoreSmokeTest(unittest.TestCase):
    def test_runtime_invocation_uses_explicit_session_id(self):
        body = Mock()
        body.read.return_value = b'{"analysis":"ok"}'
        client = Mock()
        client.invoke_agent_runtime.return_value = {"response": body}

        response = invoke_runtime(
            client,
            "arn:runtime",
            "session-id-that-is-longer-than-thirty-three-characters",
            {"task": "test"},
        )

        self.assertEqual(response, {"analysis": "ok"})
        self.assertEqual(
            client.invoke_agent_runtime.call_args.kwargs["runtimeSessionId"],
            "session-id-that-is-longer-than-thirty-three-characters",
        )

    @patch("scripts.run_agentcore_smoke.invoke_runtime")
    def test_in_progress_response_is_polled_until_terminal(self, invoke):
        invoke.side_effect = [
            {"error": IN_PROGRESS_ERROR},
            {"analysis": "ok"},
        ]
        sleep = Mock()

        response, poll_count = invoke_until_terminal(
            Mock(),
            "arn:runtime",
            "session-id",
            {"task": "test"},
            poll_interval_seconds=5,
            poll_timeout_seconds=20,
            monotonic=Mock(side_effect=[100, 101]),
            sleep=sleep,
        )

        self.assertEqual(response, {"analysis": "ok"})
        self.assertEqual(poll_count, 1)
        sleep.assert_called_once_with(5)
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(invoke.call_args_list[0], invoke.call_args_list[1])

    @patch("scripts.run_agentcore_smoke.invoke_runtime")
    def test_in_progress_polling_stops_at_timeout(self, invoke):
        response = {"error": IN_PROGRESS_ERROR}
        invoke.return_value = response
        sleep = Mock()

        actual, poll_count = invoke_until_terminal(
            Mock(),
            "arn:runtime",
            "session-id",
            {"task": "test"},
            poll_interval_seconds=5,
            poll_timeout_seconds=20,
            monotonic=Mock(side_effect=[100, 120]),
            sleep=sleep,
        )

        self.assertEqual(actual, response)
        self.assertEqual(poll_count, 0)
        sleep.assert_not_called()
        invoke.assert_called_once()

    def test_failed_runtime_response_is_printed_and_written(self):
        response = {
            "error": "Unable to resolve invocation images.",
            "details": ["S3 access denied."],
            "runtime_commit_sha": "abc123",
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "smoke.json"
            with (
                patch(
                    "scripts.run_agentcore_smoke.invoke_runtime",
                    side_effect=[response, response],
                ) as invoke,
                patch(
                    "scripts.run_agentcore_smoke.boto3.client",
                    return_value=Mock(),
                ),
                patch(
                    "sys.argv",
                    [
                        "run_agentcore_smoke.py",
                        "--runtime-arn",
                        "arn:runtime",
                        "--image-s3-prefix",
                        "s3://eval-bucket/images/",
                        "--expected-sha",
                        "abc123",
                        "--output",
                        str(output),
                    ],
                ),
                patch("builtins.print") as print_mock,
            ):
                exit_code = main()

            report = json.loads(output.read_text())
            self.assertEqual(exit_code, 1)
            self.assertEqual(report["runtime_error_details"], ["S3 access denied."])
            self.assertEqual(report["failed_assertions"], ["runtime_returned_error"])
            self.assertEqual(report["in_progress_poll_count"], 0)
            self.assertIn("S3 access denied.", print_mock.call_args.args[0])
            session_ids = [call.args[2] for call in invoke.call_args_list]
            self.assertEqual(session_ids[0], session_ids[1])

    def test_pdf_assertions_are_skipped_when_artifact_not_requested(self):
        response = {
            "analysis": "Valid analysis",
            "runtime_commit_sha": "abc123",
        }
        client = Mock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "smoke.json"
            with (
                patch(
                    "scripts.run_agentcore_smoke.invoke_runtime",
                    side_effect=[response, response],
                ),
                patch(
                    "scripts.run_agentcore_smoke.boto3.client",
                    return_value=client,
                ) as client_factory,
                patch(
                    "sys.argv",
                    [
                        "run_agentcore_smoke.py",
                        "--runtime-arn",
                        "arn:runtime",
                        "--image-s3-prefix",
                        "s3://eval-bucket/images/",
                        "--expected-sha",
                        "abc123",
                        "--no-save-analysis-pdf",
                        "--output",
                        str(output),
                    ],
                ),
            ):
                exit_code = main()

            report = json.loads(output.read_text())
            self.assertEqual(exit_code, 0)
            self.assertFalse(report["artifact_requested"])
            self.assertFalse(report["artifact_created"])
            self.assertNotIn("pdf_uri_missing", report["failed_assertions"])
            client_factory.assert_called_once()
            (service_name,) = client_factory.call_args.args
            config = client_factory.call_args.kwargs["config"]
            self.assertEqual(service_name, "bedrock-agentcore")
            self.assertEqual(config.read_timeout, 900)
            self.assertEqual(config.connect_timeout, 10)
            self.assertEqual(
                config.retries,
                {"mode": "standard", "total_max_attempts": 1},
            )
            self.assertTrue(config.tcp_keepalive)


if __name__ == "__main__":
    unittest.main()
