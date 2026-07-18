import unittest
from unittest.mock import patch

from jee_tutor.handler import validate_tutor_invocation


class HandlerAndAppTest(unittest.TestCase):
    def test_validate_tutor_invocation_returns_model(self):
        payload = validate_tutor_invocation({"image_data_uri": "data:image/png;base64,ZmFrZQ=="})

        self.assertEqual(payload.image_data_uri, "data:image/png;base64,ZmFrZQ==")

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
        with patch("jee_tutor.handler.build_student_profile_service") as build_profile:
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


if __name__ == "__main__":
    unittest.main()
