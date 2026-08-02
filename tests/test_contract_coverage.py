import unittest

import jee_tutor.domain.curriculum as curriculum_contract
import jee_tutor.domain.diagnosis as diagnosis_contract
import jee_tutor.invocation as invocation_contract
from jee_tutor.privacy import redact_email, redact_student_metadata, redact_student_s3_path
from jee_tutor.profile.models import reject_sensitive_payload_keys
from jee_tutor.profile.parsing import parse_student_context_from_s3_path


class ContractCoverageTest(unittest.TestCase):
    def test_domain_contracts_export_public_types(self):
        self.assertIsNotNone(curriculum_contract.CurriculumTaxonomy)
        self.assertIsNotNone(curriculum_contract.CurriculumValidator)
        self.assertIsNotNone(diagnosis_contract.DiagnosisResponse)
        self.assertIsNotNone(diagnosis_contract.validate_analysis_output)

    def test_invocation_lazy_export_and_unknown_attribute(self):
        self.assertEqual(
            invocation_contract.TutorInvocationService.__name__,
            "TutorInvocationService",
        )
        with self.assertRaises(AttributeError):
            getattr(invocation_contract, "UnknownService")

    def test_parsing_rejects_blank_malformed_and_misaligned_paths(self):
        self.assertIsNone(parse_student_context_from_s3_path("  "))
        self.assertIsNone(parse_student_context_from_s3_path("s3:///missing-bucket"))
        self.assertIsNone(
            parse_student_context_from_s3_path(
                "users/id/name/extra/tests/test/subjects/Physics/questions"
            )
        )

    def test_privacy_helpers_cover_absent_invalid_and_sensitive_values(self):
        self.assertIsNone(redact_email(None))
        self.assertEqual(redact_email("not-an-email"), "[redacted-email]")
        payload = redact_student_metadata(
            {
                "email": None,
                "student_id": "student-1",
                "student_name": "Student",
                "test_name": "Test",
                "image_s3_prefix": None,
                "safe": "value",
            }
        )
        self.assertIsNone(payload["email"])
        self.assertEqual(payload["student_id"], "[redacted]")
        self.assertEqual(payload["safe"], "value")
        self.assertEqual(redact_student_s3_path("s3://bucket/no/student/path"), "s3://bucket/no/student/path")

        reject_sensitive_payload_keys({"safe": "value"})
        with self.assertRaisesRegex(ValueError, "Sensitive field"):
            reject_sensitive_payload_keys({"raw-model-response": "secret"})


if __name__ == "__main__":
    unittest.main()
