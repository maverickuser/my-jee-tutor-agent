import json
import unittest
from unittest.mock import Mock

from jee_tutor.profile.artifacts import (
    ProfileReportArtifactConfig,
    ProfileReportArtifactWriter,
)
from jee_tutor.profile.reporting import ProfileReportOutput


class FakePdfRenderer:
    def __init__(self, error=None):
        self.error = error

    def render(self, markdown: str) -> bytes:
        if self.error:
            raise self.error
        return b"%PDF " + markdown.encode("utf-8")


class ProfileReportArtifactWriterTest(unittest.TestCase):
    def test_writer_uploads_pdf_markdown_and_json_under_student_profile_path(self):
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
            profile_report=profile_report(),
            profile_markdown="# Physics Longitudinal Profile",
        )

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(
            result.pdf_uri,
            (
                "s3://report-bucket/profile-output/So-yZ0Ge/SIDDHARTH_MITTAL/"
                "profile_reports/Physics_profile_report.pdf"
            ),
        )
        self.assertEqual(
            result.markdown_uri,
            (
                "s3://report-bucket/profile-output/So-yZ0Ge/SIDDHARTH_MITTAL/"
                "profile_reports/Physics_profile_report.md"
            ),
        )
        self.assertEqual(
            result.json_uri,
            (
                "s3://report-bucket/profile-output/So-yZ0Ge/SIDDHARTH_MITTAL/"
                "profile_reports/Physics_profile_report.json"
            ),
        )
        self.assertEqual(s3_client.put_object.call_count, 3)
        keys = [call.kwargs["Key"] for call in s3_client.put_object.call_args_list]
        self.assertEqual(
            keys,
            [
                "profile-output/So-yZ0Ge/SIDDHARTH_MITTAL/profile_reports/Physics_profile_report.pdf",
                "profile-output/So-yZ0Ge/SIDDHARTH_MITTAL/profile_reports/Physics_profile_report.md",
                "profile-output/So-yZ0Ge/SIDDHARTH_MITTAL/profile_reports/Physics_profile_report.json",
            ],
        )
        json_body = s3_client.put_object.call_args_list[2].kwargs["Body"]
        self.assertEqual(json.loads(json_body), profile_report().model_dump(mode="json"))

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
            profile_report=profile_report(),
            profile_markdown="# Profile",
        )

        self.assertEqual(result.status, "disabled")
        s3_client.put_object.assert_not_called()

    def test_pdf_failure_still_uploads_markdown_and_json(self):
        s3_client = Mock()
        writer = ProfileReportArtifactWriter(
            config=ProfileReportArtifactConfig(bucket="report-bucket", prefix="profiles"),
            s3_client=s3_client,
            pdf_renderer=FakePdfRenderer(RuntimeError("no tex")),
        )

        result = writer.write(
            student_id="student",
            student_name="Student",
            subject="Physics",
            profile_report=profile_report(),
            profile_markdown="# Profile",
        )

        self.assertEqual(result.status, "partial")
        self.assertIsNone(result.pdf_uri)
        self.assertIsNotNone(result.markdown_uri)
        self.assertIsNotNone(result.json_uri)
        self.assertEqual(
            result.errors,
            ["Failed to write profile report PDF: RuntimeError: no tex"],
        )


def profile_report() -> ProfileReportOutput:
    return ProfileReportOutput(
        subject="Physics",
        overall_summary="The student has a recurring projectile motion gap.",
        recurring_gaps=["Projectile components: recurring across reports."],
        broader_related_patterns=[],
        chapter_topic_weakness_map=["Kinematics / Projectile Motion"],
        isolated_gaps=[],
        study_priorities=["Practice component resolution."],
        teacher_intervention_notes=["Review vector decomposition."],
        evidence_appendix=["r1:q1"],
    )


if __name__ == "__main__":
    unittest.main()
