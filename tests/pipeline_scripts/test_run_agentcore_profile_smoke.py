import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from scripts.run_agentcore_profile_smoke import (  # noqa: E402
    _head_s3_uri,
    _load_s3_json,
    main,
)


class Body:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self):
        return self.payload


class RunAgentCoreProfileSmokeTest(unittest.TestCase):
    def test_load_s3_json_rejects_invalid_uri_and_loads_valid_json(self):
        s3_client = Mock()
        s3_client.get_object.return_value = {"Body": Body(b'{"subject":"Physics"}')}

        with self.assertRaisesRegex(ValueError, "Invalid S3 URI"):
            _load_s3_json("not-s3")

        with patch("scripts.run_agentcore_profile_smoke.boto3.client", return_value=s3_client):
            payload = _load_s3_json("s3://bucket/path/report.json")

        self.assertEqual(payload, {"subject": "Physics"})
        self.assertEqual(s3_client.get_object.call_args.kwargs["Bucket"], "bucket")
        self.assertEqual(s3_client.get_object.call_args.kwargs["Key"], "path/report.json")

    def test_head_s3_uri_rejects_invalid_uri_and_heads_valid_uri(self):
        s3_client = Mock()

        with self.assertRaisesRegex(ValueError, "Invalid S3 URI"):
            _head_s3_uri("not-s3")

        with patch("scripts.run_agentcore_profile_smoke.boto3.client", return_value=s3_client):
            _head_s3_uri("s3://bucket/path/report.pdf")

        s3_client.head_object.assert_called_once_with(Bucket="bucket", Key="path/report.pdf")

    def test_profile_smoke_reuses_diagnosis_json_and_invokes_profile_without_image_path(self):
        runtime_client = Mock()
        s3_client = Mock()
        first_response = {
            "profile_status": "succeeded",
            "profile_markdown": "# Physics Longitudinal Profile",
            "profile_artifact_status": "succeeded",
            "profile_pdf_uri": "s3://profile-bucket/student/profile_report.pdf",
            "profile_markdown_uri": "s3://profile-bucket/student/profile_report.md",
            "profile_json_uri": "s3://profile-bucket/student/profile_report.json",
            "profile_artifact_errors": [],
            "runtime_commit_sha": "abc123",
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "profile-smoke.json"
            diagnosis_smoke = Path(directory) / "diagnosis-smoke.json"
            diagnosis_smoke.write_text(
                json.dumps(
                    {
                        "diagnosis_json_uri": (
                            "s3://eval-bucket/cd-evals-images/Physics_analysis.json"
                        )
                    }
                )
            )
            with (
                patch("scripts.run_agentcore_profile_smoke.uuid.uuid4", return_value="run-1"),
                patch(
                    "scripts.run_agentcore_profile_smoke.boto3.client",
                    side_effect=lambda service, **_kwargs: (
                        runtime_client if service == "bedrock-agentcore" else s3_client
                    ),
                ),
                patch("scripts.run_agentcore_profile_smoke._load_s3_json", return_value=diagnosis_report()),
                patch("scripts.run_agentcore_profile_smoke._put_metadata") as put_metadata,
                patch("scripts.run_agentcore_profile_smoke._embedding_count", return_value=2),
                patch(
                    "scripts.run_agentcore_profile_smoke.invoke_until_terminal",
                    side_effect=[(first_response, 0), (first_response, 0)],
                ) as invoke,
                patch(
                    "sys.argv",
                    [
                        "run_agentcore_profile_smoke.py",
                        "--runtime-arn",
                        "arn:runtime",
                        "--metadata-table-name",
                        "metadata-table",
                        "--embedding-table-name",
                        "embedding-table",
                        "--diagnosis-smoke-report",
                        str(diagnosis_smoke),
                        "--expected-sha",
                        "abc123",
                        "--output",
                        str(output),
                    ],
                ),
            ):
                exit_code = main()
                report = json.loads(output.read_text())

        self.assertEqual(exit_code, 0)
        self.assertTrue(report["gate_passed"])
        self.assertEqual(
            report["diagnosis_json_uri"],
            "s3://eval-bucket/cd-evals-images/Physics_analysis.json",
        )
        self.assertEqual(report["embedding_record_count"], 2)
        self.assertEqual(report["profile_artifact_status"], "succeeded")
        self.assertEqual(
            report["profile_pdf_uri"],
            "s3://profile-bucket/student/profile_report.pdf",
        )
        s3_client.head_object.assert_called_once_with(
            Bucket="profile-bucket",
            Key="student/profile_report.pdf",
        )
        put_metadata.assert_called_once()
        metadata_item = put_metadata.call_args.args[1]
        self.assertEqual(metadata_item["email"], "cd-profile-smoke-run-1@example.com")
        self.assertEqual(
            metadata_item["diagnosis_json_s3_uri"],
            "s3://eval-bucket/cd-evals-images/Physics_analysis.json",
        )
        payload = invoke.call_args_list[0].args[3]
        self.assertEqual(payload["task"], "profile")
        self.assertEqual(payload["recipient_email"], "cd-profile-smoke-run-1@example.com")
        self.assertNotIn("image_s3_prefix", payload)

    def test_profile_smoke_fails_when_diagnosis_smoke_has_no_json_uri(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "profile-smoke.json"
            diagnosis_smoke = Path(directory) / "diagnosis-smoke.json"
            diagnosis_smoke.write_text(json.dumps({"gate_passed": True}))
            with (
                patch("scripts.run_agentcore_profile_smoke.uuid.uuid4", return_value="run-1"),
                patch("scripts.run_agentcore_profile_smoke.boto3.client", return_value=Mock()),
                patch(
                    "sys.argv",
                    [
                        "run_agentcore_profile_smoke.py",
                        "--runtime-arn",
                        "arn:runtime",
                        "--metadata-table-name",
                        "metadata-table",
                        "--embedding-table-name",
                        "embedding-table",
                        "--diagnosis-smoke-report",
                        str(diagnosis_smoke),
                        "--expected-sha",
                        "abc123",
                        "--output",
                        str(output),
                    ],
                ),
            ):
                exit_code = main()
                report = json.loads(output.read_text())

        self.assertEqual(exit_code, 1)
        self.assertIn("diagnosis_json_uri_missing", report["failed_assertions"])

    def test_profile_smoke_fails_when_embeddings_are_not_created(self):
        response = {
            "profile_status": "succeeded",
            "profile_markdown": "# Physics Longitudinal Profile",
            "profile_artifact_status": "succeeded",
            "profile_pdf_uri": "s3://profile-bucket/student/profile_report.pdf",
            "runtime_commit_sha": "abc123",
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "profile-smoke.json"
            diagnosis_smoke = Path(directory) / "diagnosis-smoke.json"
            diagnosis_smoke.write_text(
                json.dumps({"diagnosis_json_uri": "s3://eval-bucket/report.json"})
            )
            with (
                patch("scripts.run_agentcore_profile_smoke.uuid.uuid4", return_value="run-1"),
                patch("scripts.run_agentcore_profile_smoke.boto3.client", return_value=Mock()),
                patch("scripts.run_agentcore_profile_smoke._load_s3_json", return_value=diagnosis_report()),
                patch("scripts.run_agentcore_profile_smoke._put_metadata"),
                patch("scripts.run_agentcore_profile_smoke._embedding_count", return_value=0),
                patch("scripts.run_agentcore_profile_smoke._head_s3_uri"),
                patch(
                    "scripts.run_agentcore_profile_smoke.invoke_until_terminal",
                    side_effect=[(response, 0), (response, 0)],
                ),
                patch(
                    "sys.argv",
                    [
                        "run_agentcore_profile_smoke.py",
                        "--runtime-arn",
                        "arn:runtime",
                        "--metadata-table-name",
                        "metadata-table",
                        "--embedding-table-name",
                        "embedding-table",
                        "--diagnosis-smoke-report",
                        str(diagnosis_smoke),
                        "--expected-sha",
                        "abc123",
                        "--output",
                        str(output),
                    ],
                ),
            ):
                exit_code = main()
                report = json.loads(output.read_text())

        self.assertEqual(exit_code, 1)
        self.assertIn("profile_embeddings_missing", report["failed_assertions"])

    def test_profile_smoke_fails_when_profile_pdf_is_not_returned(self):
        response = {
            "profile_status": "succeeded",
            "profile_markdown": "# Physics Longitudinal Profile",
            "profile_artifact_status": "disabled",
            "runtime_commit_sha": "abc123",
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "profile-smoke.json"
            diagnosis_smoke = Path(directory) / "diagnosis-smoke.json"
            diagnosis_smoke.write_text(
                json.dumps({"diagnosis_json_uri": "s3://eval-bucket/report.json"})
            )
            with (
                patch("scripts.run_agentcore_profile_smoke.uuid.uuid4", return_value="run-1"),
                patch("scripts.run_agentcore_profile_smoke.boto3.client", return_value=Mock()),
                patch("scripts.run_agentcore_profile_smoke._load_s3_json", return_value=diagnosis_report()),
                patch("scripts.run_agentcore_profile_smoke._put_metadata"),
                patch("scripts.run_agentcore_profile_smoke._embedding_count", return_value=2),
                patch(
                    "scripts.run_agentcore_profile_smoke.invoke_until_terminal",
                    side_effect=[(response, 0), (response, 0)],
                ),
                patch(
                    "sys.argv",
                    [
                        "run_agentcore_profile_smoke.py",
                        "--runtime-arn",
                        "arn:runtime",
                        "--metadata-table-name",
                        "metadata-table",
                        "--embedding-table-name",
                        "embedding-table",
                        "--diagnosis-smoke-report",
                        str(diagnosis_smoke),
                        "--expected-sha",
                        "abc123",
                        "--output",
                        str(output),
                    ],
                ),
            ):
                exit_code = main()
                report = json.loads(output.read_text())

        self.assertEqual(exit_code, 1)
        self.assertIn("profile_artifact_not_succeeded", report["failed_assertions"])
        self.assertIn("profile_pdf_uri_missing", report["failed_assertions"])


def diagnosis_report() -> dict:
    return {
        "diagnosis_report_id": "report-1",
        "student_id": "student-1",
        "student_name": "CD_Smoke",
        "subject": "Physics",
        "test_name": "CD_SMOKE",
        "diagnosis_date": "2026-07-18T00:00:00+00:00",
        "questions": [
            {
                "question_number": "1",
                "chapter": "Kinematics",
                "topic": "Projectile Motion",
                "what_you_thought": "You treated components as one speed.",
                "why_that_thought_is_wrong": "Projectile motion requires components.",
                "exact_concept_gap": "Projectile components",
                "what_you_must_deep_dive": "Practice x and y component equations.",
            },
            {
                "question_number": "2",
                "chapter": "Kinematics",
                "topic": "Projectile Motion",
                "what_you_thought": "You used a one-dimensional shortcut.",
                "why_that_thought_is_wrong": "The trajectory is two-dimensional.",
                "exact_concept_gap": "Projectile components",
                "what_you_must_deep_dive": "Review range and time-of-flight derivations.",
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
