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
        with patch("jee_tutor.app.handle_tutor_invocation", return_value={"analysis": "ok"}):
            from agentcore_app import invoke_tutor

            self.assertEqual(invoke_tutor({"image_data_uri": "x"}, None), {"analysis": "ok"})


if __name__ == "__main__":
    unittest.main()
