import unittest

from jee_tutor.profile.evidence import ProfileEvidenceLoader
from jee_tutor.profile.models import (
    ProfileReportRequest,
    StudentDiagnosisMetadata,
    StructuredDiagnosisQuestionEvidence,
    StructuredDiagnosisReport,
)
from jee_tutor.profile.storage import (
    InMemoryStudentDiagnosisMetadataStore,
    InMemoryStructuredDiagnosisArtifactStore,
)


def report(report_id: str, subject: str = "Physics") -> StructuredDiagnosisReport:
    return StructuredDiagnosisReport(
        diagnosis_report_id=report_id,
        student_id="YWuzXTHQ",
        student_name="Mock_Student",
        subject=subject,
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


def metadata(report_id: str, subject: str = "Physics", email: str = "student@example.com"):
    return StudentDiagnosisMetadata(
        student_id="YWuzXTHQ",
        email=email,
        student_name="Mock_Student",
        subject=subject,
        test_name="MINOR_TEST_2_Paper_2",
        diagnosis_report_id=report_id,
        diagnosis_date="2026-07-18T10:00:00+00:00",
        diagnosis_json_s3_uri=f"s3://bucket/{report_id}.json",
        question_count=1,
    )


class ProfileEvidenceLoadingTest(unittest.TestCase):
    def test_loads_metadata_by_email_subject_and_builds_compact_evidence(self):
        metadata_store = InMemoryStudentDiagnosisMetadataStore()
        artifact_store = InMemoryStructuredDiagnosisArtifactStore()
        metadata_store.put_metadata(metadata("physics-1"))
        metadata_store.put_metadata(metadata("maths-1", subject="Maths"))
        metadata_store.put_metadata(metadata("other-1", email="other@example.com"))
        artifact_store.write_report(s3_uri="s3://bucket/physics-1.json", report=report("physics-1"))

        result = ProfileEvidenceLoader(
            metadata_store=metadata_store,
            artifact_store=artifact_store,
        ).load(ProfileReportRequest(email="student@example.com", subject="Physics"))

        self.assertFalse(result.no_history)
        self.assertEqual([item.evidence_id for item in result.evidence_items], ["physics-1:q1"])
        self.assertEqual(
            result.evidence_items[0].evidence_reference,
            "2026-07-18 : MINOR_TEST_2_Paper_2 : Q1",
        )
        self.assertEqual(result.evidence_items[0].test_name, "MINOR_TEST_2_Paper_2")
        self.assertEqual(result.evidence_items[0].exact_concept_gap, "Projectile components")
        self.assertNotIn("email", result.evidence_items[0].model_dump())

    def test_load_returns_handled_no_history_response(self):
        result = ProfileEvidenceLoader(
            metadata_store=InMemoryStudentDiagnosisMetadataStore(),
            artifact_store=InMemoryStructuredDiagnosisArtifactStore(),
        ).load(ProfileReportRequest(email="student@example.com", subject="Physics"))

        self.assertTrue(result.no_history)
        self.assertIn("No diagnosis history", result.message or "")

    def test_load_rejects_metadata_question_count_mismatch(self):
        metadata_store = InMemoryStudentDiagnosisMetadataStore()
        artifact_store = InMemoryStructuredDiagnosisArtifactStore()
        bad_metadata = metadata("physics-1").model_copy(update={"question_count": 2})
        metadata_store.put_metadata(bad_metadata)
        artifact_store.write_report(s3_uri="s3://bucket/physics-1.json", report=report("physics-1"))

        with self.assertRaisesRegex(ValueError, "question count"):
            ProfileEvidenceLoader(
                metadata_store=metadata_store,
                artifact_store=artifact_store,
            ).load(ProfileReportRequest(email="student@example.com", subject="Physics"))


if __name__ == "__main__":
    unittest.main()
