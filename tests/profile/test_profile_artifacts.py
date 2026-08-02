import unittest
from unittest.mock import Mock, patch

from jee_tutor.profile.artifacts import (
    ProfileReportArtifactConfig,
    ProfileReportArtifactWriter,
)


class FakePdfRenderer:
    def __init__(self, error=None):
        self.error = error

    def render(self, markdown: str) -> bytes:
        if self.error:
            raise self.error
        return b"%PDF " + markdown.encode("utf-8")


class ProfileReportArtifactWriterTest(unittest.TestCase):
    def test_writer_uploads_only_pdf_at_required_student_profile_path(self):
        s3_client = Mock()
        writer = ProfileReportArtifactWriter(
            config=ProfileReportArtifactConfig(
                bucket="report-bucket",
                prefix="profile-output",
                region="ap-south-1",
            ),
            s3_client=s3_client,
            pdf_renderer=FakePdfRenderer(),
        )

        result = writer.write(
            student_id="So-yZ0Ge",
            student_name="SIDDHARTH MITTAL",
            subject="Physics",
            profile_markdown="# Physics profile",
        )

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(
            result.pdf_uri,
            "s3://report-bucket/profile-output/SIDDHARTH_MITTAL+So-yZ0Ge/Physics/Physics_profile_report.pdf",
        )
        s3_client.put_object.assert_called_once_with(
            Bucket="report-bucket",
            Key=(
                "profile-output/SIDDHARTH_MITTAL+So-yZ0Ge/"
                "Physics/Physics_profile_report.pdf"
            ),
            Body=b"%PDF # Physics profile",
            ContentType="application/pdf",
        )

    def test_writer_is_disabled_without_bucket(self):
        s3_client = Mock()
        writer = ProfileReportArtifactWriter(
            config=ProfileReportArtifactConfig(bucket=""),
            s3_client=s3_client,
        )

        result = writer.write(
            student_id="student",
            student_name="Student",
            subject="Physics",
            profile_markdown="# Profile",
        )

        self.assertEqual(result.status, "disabled")
        self.assertEqual(result.errors, [])
        s3_client.put_object.assert_not_called()

    def test_pdf_failure_returns_one_structured_failure(self):
        writer = ProfileReportArtifactWriter(
            config=ProfileReportArtifactConfig(bucket="report-bucket"),
            s3_client=Mock(),
            pdf_renderer=FakePdfRenderer(RuntimeError("no tex")),
        )

        result = writer.write(
            student_id="student",
            student_name="Student",
            subject="Physics",
            profile_markdown="# Profile",
        )

        self.assertEqual(result.status, "failed")
        self.assertIsNone(result.pdf_uri)
        self.assertEqual(
            result.errors,
            ["Failed to write profile report PDF: RuntimeError: no tex"],
        )

    def test_invalid_path_component_is_rejected_before_upload(self):
        writer = ProfileReportArtifactWriter(
            config=ProfileReportArtifactConfig(bucket="report-bucket"),
            s3_client=Mock(),
            pdf_renderer=FakePdfRenderer(),
        )
        with self.assertRaisesRegex(ValueError, "blank after sanitization"):
            writer.write(
                student_id="...",
                student_name="Student",
                subject="Physics",
                profile_markdown="# Profile",
            )

    def test_writer_builds_s3_client_lazily(self):
        s3_client = Mock()
        with patch("jee_tutor.profile.artifacts.boto3.client", return_value=s3_client) as factory:
            writer = ProfileReportArtifactWriter(
                config=ProfileReportArtifactConfig(bucket="report-bucket", region="ap-south-1"),
                pdf_renderer=FakePdfRenderer(),
            )
            writer.write(
                student_id="student",
                student_name="Student",
                subject="Physics",
                profile_markdown="# Profile",
            )
        factory.assert_called_once_with("s3", region_name="ap-south-1")


if __name__ == "__main__":
    unittest.main()
