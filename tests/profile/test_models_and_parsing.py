import unittest
from pydantic import ValidationError

from jee_tutor.profile.models import (
    StudentDiagnosisMetadata,
    StructuredDiagnosisQuestionEvidence,
    StructuredDiagnosisReport,
    metadata_from_report,
)
from jee_tutor.profile.parsing import parse_student_context_from_s3_path
from jee_tutor.profile.privacy import redact_email, redact_student_metadata
from jee_tutor.profile.storage import (
    InMemoryStudentDiagnosisMetadataStore,
    InMemoryStructuredDiagnosisArtifactStore,
)


class ProfileModelsAndParsingTest(unittest.TestCase):
    def test_parse_student_context_from_canonical_s3_key(self):
        context = parse_student_context_from_s3_path(
            "users/YWuzXTHQ/Mock_Student/tests/MINOR_TEST_2_Paper_2/"
            "subjects/Physics/questions/Question_1.png"
        )

        self.assertIsNotNone(context)
        assert context is not None
        self.assertIsNone(context.bucket)
        self.assertEqual(context.student_id, "YWuzXTHQ")
        self.assertEqual(context.student_name, "Mock_Student")
        self.assertEqual(context.test_name, "MINOR_TEST_2_Paper_2")
        self.assertEqual(context.subject, "Physics")
        self.assertEqual(
            context.questions_prefix,
            "users/YWuzXTHQ/Mock_Student/tests/MINOR_TEST_2_Paper_2/subjects/Physics/questions",
        )

    def test_parse_student_context_from_canonical_s3_uri_prefix(self):
        context = parse_student_context_from_s3_path(
            "s3://attempt-bucket/users/YWuzXTHQ/Mock_Student/tests/"
            "MINOR_TEST_2_Paper_2/subjects/Physics/questions/"
        )

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.bucket, "attempt-bucket")
        self.assertEqual(context.student_id, "YWuzXTHQ")
        self.assertEqual(context.subject, "Physics")

    def test_parse_student_context_rejects_noncanonical_path(self):
        self.assertIsNone(
            parse_student_context_from_s3_path("users/YWuzXTHQ/tests/MINOR/subjects/Physics/questions/")
        )

    def test_metadata_validates_required_fields_email_s3_paths_and_question_count(self):
        metadata = StudentDiagnosisMetadata(
            student_id="YWuzXTHQ",
            email="Student@Example.COM",
            student_name="Mock_Student",
            subject="Physics",
            test_name="MINOR_TEST_2_Paper_2",
            diagnosis_report_id="report-1",
            diagnosis_date="2026-07-18T10:00:00+00:00",
            diagnosis_json_s3_uri="s3://bucket/report.json",
            analysis_pdf_s3_uri="s3://bucket/report.pdf",
            question_count=8,
        )

        self.assertEqual(metadata.email, "student@example.com")
        self.assertEqual(metadata.question_count, 8)

        with self.assertRaises(ValidationError):
            StudentDiagnosisMetadata(
                student_id="YWuzXTHQ",
                email="bad",
                student_name="Mock_Student",
                subject="Physics",
                test_name="MINOR_TEST_2_Paper_2",
                diagnosis_report_id="report-1",
                diagnosis_date="2026-07-18T10:00:00+00:00",
                diagnosis_json_s3_uri="not-s3",
                question_count=0,
            )

    def test_structured_report_metadata_excludes_recipient_email_from_question_evidence(self):
        report = StructuredDiagnosisReport(
            diagnosis_report_id="report-1",
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

        metadata = metadata_from_report(
            report=report,
            email="student@example.com",
            diagnosis_json_s3_uri="s3://bucket/report.json",
        )

        self.assertEqual(metadata.question_count, 1)
        self.assertNotIn("email", report.questions[0].model_dump())

    def test_redaction_helpers_hide_email_and_student_path_segments(self):
        self.assertEqual(redact_email("student@example.com"), "s***@example.com")

        redacted = redact_student_metadata(
            {
                "recipient_email": "student@example.com",
                "image_s3_prefix": (
                    "s3://bucket/users/YWuzXTHQ/Mock_Student/tests/"
                    "MINOR_TEST_2_Paper_2/subjects/Physics/questions/"
                ),
            }
        )

        self.assertEqual(redacted["recipient_email"], "s***@example.com")
        self.assertIn("[student-id]", redacted["image_s3_prefix"])
        self.assertIn("[student-name]", redacted["image_s3_prefix"])

    def test_in_memory_metadata_store_queries_by_email_and_subject(self):
        store = InMemoryStudentDiagnosisMetadataStore()
        physics = StudentDiagnosisMetadata(
            student_id="YWuzXTHQ",
            email="student@example.com",
            student_name="Mock_Student",
            subject="Physics",
            test_name="MINOR_TEST_2_Paper_2",
            diagnosis_report_id="physics-1",
            diagnosis_date="2026-07-18T10:00:00+00:00",
            diagnosis_json_s3_uri="s3://bucket/physics.json",
            question_count=2,
        )
        maths = physics.model_copy(
            update={
                "subject": "Maths",
                "diagnosis_report_id": "maths-1",
                "diagnosis_json_s3_uri": "s3://bucket/maths.json",
            }
        )
        other_student = physics.model_copy(
            update={
                "email": "other@example.com",
                "diagnosis_report_id": "physics-2",
                "diagnosis_json_s3_uri": "s3://bucket/other.json",
            }
        )

        store.put_metadata(physics)
        store.put_metadata(maths)
        store.put_metadata(other_student)

        self.assertEqual(
            [record.diagnosis_report_id for record in store.query_by_email_subject(
                email="STUDENT@example.com",
                subject="physics",
            )],
            ["physics-1"],
        )

    def test_in_memory_artifact_store_writes_and_loads_structured_report(self):
        store = InMemoryStructuredDiagnosisArtifactStore()
        report = StructuredDiagnosisReport(
            diagnosis_report_id="report-1",
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

        store.write_report(s3_uri="s3://bucket/report.json", report=report)

        self.assertEqual(
            store.load_report(s3_uri="s3://bucket/report.json").diagnosis_report_id,
            "report-1",
        )


if __name__ == "__main__":
    unittest.main()
