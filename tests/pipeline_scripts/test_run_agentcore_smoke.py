import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from scripts.run_agentcore_smoke import (  # noqa: E402
    IN_PROGRESS_ERROR,
    _quality_gate_evidence,
    invoke_runtime,
    invoke_until_terminal,
    main,
    markdown_data_row_count,
)


class RunAgentCoreSmokeTest(unittest.TestCase):
    def test_markdown_data_row_count(self):
        analysis = (
            "| Question Number | Topic |\n"
            "| --- | --- |\n"
            "| 1 | Friction |\n"
            "| 2 | Rotation |\n"
            "| 3 | Electrostatics |"
        )

        self.assertEqual(markdown_data_row_count(analysis), 3)

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

    def test_quality_gate_evidence_includes_controlled_react_and_artifact_safety(self):
        evidence = _quality_gate_evidence()

        self.assertTrue(evidence["controlled_react"]["task_guardrail_required"])
        self.assertEqual(evidence["controlled_react"]["max_real_vision_executions"], 2)
        self.assertTrue(evidence["artifact_safety"]["artifact_replay_checked"])

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
        details = [f"Bounded runtime detail {index}." for index in range(25)]
        response = {
            "error": "Unable to resolve invocation images.",
            "details": details,
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
                        "--expected-image-count",
                        "1",
                        "--output",
                        str(output),
                    ],
                ),
                patch("builtins.print") as print_mock,
            ):
                exit_code = main()

            report = json.loads(output.read_text())
            self.assertEqual(exit_code, 1)
            self.assertEqual(report["runtime_error_details"], details[:20])
            self.assertEqual(report["failed_assertions"], ["runtime_returned_error"])
            self.assertEqual(report["in_progress_poll_count"], 0)
            self.assertIn("Bounded runtime detail 19.", print_mock.call_args.args[0])
            self.assertNotIn("Bounded runtime detail 20.", print_mock.call_args.args[0])
            session_ids = [call.args[2] for call in invoke.call_args_list]
            self.assertEqual(session_ids[0], session_ids[1])

    def test_smoke_fails_when_analysis_row_count_does_not_match_images(self):
        response = {
            "analysis": ("| Question Number |\n| --- |\n| 1 |\n| 2 |"),
            "runtime_commit_sha": "abc123",
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "smoke.json"
            with (
                patch(
                    "scripts.run_agentcore_smoke.invoke_runtime",
                    side_effect=[response, response],
                ),
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
                        "--expected-image-count",
                        "3",
                        "--no-save-analysis-pdf",
                        "--output",
                        str(output),
                    ],
                ),
            ):
                exit_code = main()

            report = json.loads(output.read_text())
            self.assertEqual(exit_code, 1)
            self.assertEqual(report["analysis_data_row_count"], 2)
            self.assertEqual(report["expected_image_count"], 3)
            self.assertIn("analysis_row_count_mismatch", report["failed_assertions"])

    def test_pdf_assertions_are_skipped_when_artifact_not_requested(self):
        response = {
            "analysis": "| Question Number |\n| --- |\n| 1 |",
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
                        "--expected-image-count",
                        "1",
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
            self.assertEqual(report["analysis_data_row_count"], 1)
            self.assertEqual(report["expected_image_count"], 1)
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

    def test_pdf_metadata_is_unchanged_after_idempotent_replay(self):
        response = {
            "analysis": "| Question Number |\n| --- |\n| 1 |",
            "analysis_pdf_uri": "s3://eval-bucket/report.pdf",
            "runtime_commit_sha": "abc123",
        }
        artifact_head = {
            "LastModified": datetime.fromtimestamp(200, tz=timezone.utc),
            "ETag": '"etag-1"',
        }
        runtime_client = Mock()
        s3_client = Mock()
        s3_client.head_object.side_effect = [artifact_head, artifact_head]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "smoke.json"
            with (
                patch(
                    "scripts.run_agentcore_smoke.invoke_runtime",
                    side_effect=[response, response],
                ),
                patch(
                    "scripts.run_agentcore_smoke.boto3.client",
                    side_effect=lambda service, **_kwargs: (
                        runtime_client if service == "bedrock-agentcore" else s3_client
                    ),
                ),
                patch("scripts.run_agentcore_smoke.time.time", return_value=100),
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
                        "--expected-image-count",
                        "1",
                        "--output",
                        str(output),
                    ],
                ),
            ):
                exit_code = main()

            report = json.loads(output.read_text())
            self.assertEqual(exit_code, 0)
            self.assertTrue(report["artifact_last_modified_unchanged"])
            self.assertTrue(report["artifact_etag_unchanged"])
            self.assertEqual(s3_client.head_object.call_count, 2)

    def test_smoke_fails_when_replay_rewrites_pdf(self):
        response = {
            "analysis": "| Question Number |\n| --- |\n| 1 |",
            "analysis_pdf_uri": "s3://eval-bucket/report.pdf",
            "runtime_commit_sha": "abc123",
        }
        first_head = {
            "LastModified": datetime.fromtimestamp(200, tz=timezone.utc),
            "ETag": '"etag-1"',
        }
        replay_head = {
            "LastModified": datetime.fromtimestamp(201, tz=timezone.utc),
            "ETag": '"etag-2"',
        }
        s3_client = Mock()
        s3_client.head_object.side_effect = [first_head, replay_head]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "smoke.json"
            with (
                patch(
                    "scripts.run_agentcore_smoke.invoke_runtime",
                    side_effect=[response, response],
                ),
                patch(
                    "scripts.run_agentcore_smoke.boto3.client",
                    side_effect=lambda service, **_kwargs: (
                        Mock() if service == "bedrock-agentcore" else s3_client
                    ),
                ),
                patch("scripts.run_agentcore_smoke.time.time", return_value=100),
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
                        "--expected-image-count",
                        "1",
                        "--output",
                        str(output),
                    ],
                ),
            ):
                exit_code = main()

            report = json.loads(output.read_text())
            self.assertEqual(exit_code, 1)
            self.assertFalse(report["artifact_last_modified_unchanged"])
            self.assertFalse(report["artifact_etag_unchanged"])
            self.assertIn(
                "artifact_rewritten_on_idempotent_replay",
                report["failed_assertions"],
            )


if __name__ == "__main__":
    unittest.main()
