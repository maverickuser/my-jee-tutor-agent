import unittest
import sys
from unittest.mock import patch

from jee_tutor.handler import validate_tutor_invocation


class HandlerAndAppTest(unittest.TestCase):
    def test_validate_tutor_invocation_returns_model(self):
        payload = validate_tutor_invocation({"image_data_uri": "data:image/png;base64,ZmFrZQ=="})

        self.assertEqual(payload.image_data_uri, "data:image/png;base64,ZmFrZQ==")

    def test_invocation_models_do_not_import_profile_report_stack(self):
        sys.modules.pop("jee_tutor.profile.reporting", None)
        sys.modules.pop("jee_tutor.application.profile", None)

        from jee_tutor.invocation.models import AgentLLMCallRecord

        self.assertEqual(AgentLLMCallRecord.__name__, "AgentLLMCallRecord")
        self.assertNotIn("jee_tutor.profile.reporting", sys.modules)
        self.assertNotIn("jee_tutor.application.profile", sys.modules)

    def test_validate_tutor_invocation_accepts_agentcore_json_contract(self):
        payload = validate_tutor_invocation(
            {
                "task": "diagnose this attempt",
                "subject": "maths",
                "image_s3_prefix": "s3://attempt-bucket/maths/attempt-123/",
            }
        )

        self.assertEqual(payload.resolved_question_context, "diagnose this attempt")
        self.assertEqual(payload.image_s3_prefix, "s3://attempt-bucket/maths/attempt-123/")
        self.assertEqual(payload.subject, "maths")

    def test_validate_tutor_invocation_accepts_profile_without_image_source(self):
        payload = validate_tutor_invocation(
            {
                "task": "profile",
                "recipient_email": "student@example.com",
                "subject": "Physics",
            }
        )

        self.assertEqual(payload.task, "profile")
        self.assertEqual(payload.recipient_email, "student@example.com")
        self.assertIsNone(payload.image_s3_prefix)
        self.assertIsNone(payload.image_data_uri)

    def test_validate_tutor_invocation_still_rejects_diagnosis_without_image_source(self):
        with self.assertRaises(Exception):
            validate_tutor_invocation(
                {
                    "task": "diagnose this attempt",
                    "recipient_email": "student@example.com",
                    "subject": "Physics",
                }
            )

    def test_safe_trace_input_redacts_student_metadata_in_s3_prefix(self):
        payload = validate_tutor_invocation(
            {
                "image_s3_prefix": (
                    "s3://attempt-bucket/users/YWuzXTHQ/Mock_Student/tests/"
                    "MINOR_TEST_2_Paper_2/subjects/Physics/questions/"
                ),
                "recipient_email": "student@example.com",
            }
        )

        trace_input = payload.safe_trace_input()

        self.assertNotIn("recipient_email", trace_input)
        self.assertNotIn("YWuzXTHQ", trace_input["image_s3_prefix"])
        self.assertNotIn("Mock_Student", trace_input["image_s3_prefix"])
        self.assertNotIn("MINOR_TEST_2_Paper_2", trace_input["image_s3_prefix"])
        self.assertIn("[student-id]", trace_input["image_s3_prefix"])

    def test_validate_tutor_invocation_rejects_invalid_recipient_email(self):
        with self.assertRaises(Exception):
            validate_tutor_invocation(
                {
                    "image_s3_prefix": "s3://attempt-bucket/maths/attempt-123/",
                    "recipient_email": "not-an-email",
                }
            )

    def test_validate_tutor_invocation_rejects_legacy_extra_fields(self):
        with self.assertRaises(Exception):
            validate_tutor_invocation(
                {
                    "task": "diagnose this attempt",
                    "image_s3_prefix": "s3://attempt-bucket/maths/attempt-123/",
                    "image_folder": "/app/input/attempt-images",
                }
            )

    def test_agentcore_app_entrypoint_delegates_to_handler(self):
        with patch("jee_tutor.app.handle_agentcore_request", return_value={"analysis": "ok"}):
            from agentcore_app import invoke_tutor

            self.assertEqual(invoke_tutor({"image_data_uri": "x"}, None), {"analysis": "ok"})

    def test_agentcore_handler_dispatches_profile_report_task(self):
        with patch("jee_tutor.infrastructure.composition.build_student_profile_service") as build_profile:
            build_profile.return_value.handle.return_value = {"profile_status": "no_history"}
            from jee_tutor.handler import handle_agentcore_request

            response = handle_agentcore_request(
                {
                    "task": "profile",
                    "recipient_email": "student@example.com",
                    "subject": "Physics",
                }
            )

        self.assertEqual(response, {"profile_status": "no_history"})

    def test_agentcore_handler_dispatches_default_diagnosis_task(self):
        with patch("jee_tutor.infrastructure.composition.build_tutor_invocation_service") as build_tutor:
            build_tutor.return_value.handle.return_value = {"analysis": "ok"}
            from jee_tutor.handler import handle_agentcore_request

            response = handle_agentcore_request({"image_data_uri": "x"})

        self.assertEqual(response, {"analysis": "ok"})


if __name__ == "__main__":
    unittest.main()
