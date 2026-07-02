import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from scripts.run_agentcore_smoke import main  # noqa: E402


class RunAgentCoreSmokeTest(unittest.TestCase):
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
            self.assertIn("S3 access denied.", print_mock.call_args.args[0])

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
            client_factory.assert_called_once_with("bedrock-agentcore")


if __name__ == "__main__":
    unittest.main()
