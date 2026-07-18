import unittest
from unittest.mock import patch

from jee_tutor.api.invocation import TutorInvocationPayload
from jee_tutor.application.invocation import TutorInvocationApplicationService
from jee_tutor.infrastructure.composition import build_tutor_invocation_service


class CompositionTest(unittest.TestCase):
    def test_api_contract_imports_existing_payload_model(self):
        payload = TutorInvocationPayload.model_validate(
            {"image_data_uri": "data:image/png;base64,ZmFrZQ=="}
        )

        self.assertEqual(payload.image_data_uri, "data:image/png;base64,ZmFrZQ==")

    def test_composition_builds_application_service(self):
        service = build_tutor_invocation_service()

        self.assertIsInstance(service, TutorInvocationApplicationService)

    def test_handler_delegates_to_composition_root(self):
        with patch("jee_tutor.infrastructure.composition.build_tutor_invocation_service") as build:
            build.return_value.handle.return_value = {"analysis": "ok"}

            from jee_tutor.handler import handle_tutor_invocation

            self.assertEqual(handle_tutor_invocation({"image_data_uri": "x"}), {"analysis": "ok"})
            build.return_value.handle.assert_called_once_with({"image_data_uri": "x"})


if __name__ == "__main__":
    unittest.main()
