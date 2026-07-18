import unittest

from jee_tutor.application.profile import PROFILE_REPORT_TASK, StudentProfileApplicationService
from jee_tutor.profile.models import (
    StudentDiagnosisMetadata,
    StructuredDiagnosisQuestionEvidence,
    StructuredDiagnosisReport,
)
from jee_tutor.profile.storage import (
    InMemoryStudentDiagnosisMetadataStore,
    InMemoryStructuredDiagnosisArtifactStore,
)


def report(report_id: str) -> StructuredDiagnosisReport:
    return StructuredDiagnosisReport(
        diagnosis_report_id=report_id,
        student_id="YWuzXTHQ",
        student_name="Mock_Student",
        subject="Physics",
        test_name="MINOR_TEST_2_Paper_2",
        diagnosis_date="2026-07-18T10:00:00+00:00",
        questions=[
            StructuredDiagnosisQuestionEvidence(
                question_number="1",
                chapter="Kinematics",
                topic="Projectile motion",
                what_you_thought="You likely used constant speed.",
                why_that_thought_is_wrong="Vertical acceleration changes velocity.",
                exact_concept_gap="Projectile components",
                what_you_must_deep_dive="Resolve horizontal and vertical motion.",
            )
        ],
    )


def metadata(report_id: str) -> StudentDiagnosisMetadata:
    return StudentDiagnosisMetadata(
        student_id="YWuzXTHQ",
        email="student@example.com",
        student_name="Mock_Student",
        subject="Physics",
        test_name="MINOR_TEST_2_Paper_2",
        diagnosis_report_id=report_id,
        diagnosis_date="2026-07-18T10:00:00+00:00",
        diagnosis_json_s3_uri=f"s3://bucket/{report_id}.json",
        question_count=1,
    )


class StudentProfileApplicationServiceTest(unittest.TestCase):
    def test_profile_request_returns_no_history_without_metadata(self):
        service = StudentProfileApplicationService(
            metadata_store=InMemoryStudentDiagnosisMetadataStore(),
            artifact_store=InMemoryStructuredDiagnosisArtifactStore(),
        )

        response = service.handle(
            {
                "task": PROFILE_REPORT_TASK,
                "recipient_email": "student@example.com",
                "subject": "Physics",
            }
        )

        self.assertEqual(response["profile_status"], "no_history")

    def test_profile_request_generates_written_profile_from_history(self):
        metadata_store = InMemoryStudentDiagnosisMetadataStore()
        artifact_store = InMemoryStructuredDiagnosisArtifactStore()
        for report_id in ["r1", "r2"]:
            metadata_store.put_metadata(metadata(report_id))
            artifact_store.write_report(s3_uri=f"s3://bucket/{report_id}.json", report=report(report_id))
        service = StudentProfileApplicationService(
            metadata_store=metadata_store,
            artifact_store=artifact_store,
        )

        response = service.handle(
            {
                "task": PROFILE_REPORT_TASK,
                "recipient_email": "student@example.com",
                "subject": "Physics",
            }
        )

        self.assertEqual(response["profile_status"], "succeeded")
        self.assertIn("Physics Longitudinal Profile", response["profile_markdown"])
        self.assertIn("Projectile components", response["profile_markdown"])


if __name__ == "__main__":
    unittest.main()
