import unittest
from unittest.mock import Mock

from jee_tutor.agent.guardrails import GuardrailCheck
from jee_tutor.invocation.idempotency import InvocationIdempotencyStore
from jee_tutor.invocation.image_inputs import ResolvedImage
from jee_tutor.invocation.service import TutorInvocationService


class AllowGuardrail:
    def check_input(self, **_kwargs):
        return GuardrailCheck(allowed=True)

    def check_output(self, _analysis):
        return GuardrailCheck(allowed=True)


class IdempotencyTest(unittest.TestCase):
    def setUp(self):
        self.store = InvocationIdempotencyStore()
        self.resolver = Mock()
        self.resolver.resolve_images.return_value = [
            ResolvedImage(data_uri="data:image/png;base64,ZmFrZQ==")
        ]
        self.workflow = Mock(return_value="analysis")
        self.service = TutorInvocationService(
            image_resolver=self.resolver,
            guardrail=AllowGuardrail(),
            workflow=self.workflow,
            artifact_writer=Mock(),
            idempotency_store=self.store,
        )
        self.payload = {
            "image_data_uri": "data:image/png;base64,ZmFrZQ==",
            "save_analysis_pdf": False,
            "include_evaluation_metadata": False,
            "idempotency_key": "attempt-123",
        }

    def test_completed_invocation_is_returned_without_duplicate_analysis(self):
        first = self.service.handle(self.payload)
        second = self.service.handle(self.payload)

        self.assertEqual(first, {"analysis": "analysis"})
        self.assertEqual(second, first)
        self.workflow.assert_called_once()
        self.resolver.resolve_images.assert_called_once()

    def test_in_progress_invocation_is_not_started_again(self):
        normalized_payload = {
            "task": None,
            "subject": None,
            "image_s3_prefix": None,
            "image_data_uri": "data:image/png;base64,ZmFrZQ==",
            "save_analysis_pdf": False,
            "include_evaluation_metadata": False,
            "idempotency_key": "attempt-123",
        }
        self.store.claim("attempt-123", normalized_payload)

        response = self.service.handle(self.payload)

        self.assertEqual(response["error"], "Tutor invocation is already in progress.")
        self.workflow.assert_not_called()

    def test_reused_key_with_different_payload_is_rejected(self):
        self.service.handle(self.payload)

        response = self.service.handle(
            {
                **self.payload,
                "image_data_uri": "data:image/png;base64,ZGlmZmVyZW50",
            }
        )

        self.assertIn("different payload", response["error"])
        self.workflow.assert_called_once()

    def test_expired_key_can_be_acquired_again(self):
        now = [100.0]
        store = InvocationIdempotencyStore(
            ttl_seconds=10.0,
            monotonic=lambda: now[0],
        )
        payload = {"image_data_uri": "data:image/png;base64,ZmFrZQ=="}

        self.assertEqual(store.claim("key", payload).status, "acquired")
        now[0] = 111.0
        self.assertEqual(store.claim("key", payload).status, "acquired")

    def test_unexpected_failure_abandons_claim(self):
        self.service._handle_validated_invocation = Mock(side_effect=RuntimeError("unexpected"))

        with self.assertRaisesRegex(RuntimeError, "unexpected"):
            self.service.handle(self.payload)

        normalized_payload = {
            "task": None,
            "subject": None,
            "image_s3_prefix": None,
            "image_data_uri": "data:image/png;base64,ZmFrZQ==",
            "save_analysis_pdf": False,
            "idempotency_key": "attempt-123",
        }
        self.assertEqual(
            self.store.claim("attempt-123", normalized_payload).status,
            "acquired",
        )


if __name__ == "__main__":
    unittest.main()
