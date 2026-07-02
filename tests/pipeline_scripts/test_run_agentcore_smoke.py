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
            self.assertIn("runtime_returned_error", report["failed_assertions"])
            self.assertIn("S3 access denied.", print_mock.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
