import unittest
from contextlib import contextmanager

from jee_tutor.agent.guardrails import GuardrailCheck
from jee_tutor.application.invocation import TutorInvocationApplicationService
from jee_tutor.email.models import EmailDeliveryOutcome, EmailDeliveryStatus
from jee_tutor.invocation.image_inputs import ResolvedImage


class FakeImageResolver:
    def resolve_images(self, *, image_data_uri, image_s3_prefix):
        return [ResolvedImage(data_uri=image_data_uri or "data:image/png;base64,ZmFrZQ==")]


class FakeGuardrail:
    def check_input(self, *, question_context, image_data_uris):
        return GuardrailCheck(allowed=True)

    def check_output(self, text):
        return GuardrailCheck(allowed=True)


class FakeObservability:
    @contextmanager
    def invocation_span(self, *, input_payload, metadata=None):
        yield None


class FakeArtifactWriter:
    def write_for_invocation(self, *, analysis_markdown, invocation):
        raise AssertionError("artifact writer should not be called for direct image input")


class FakeEmailCoordinator:
    def request_delivery(self, *, recipient_email, pdf_uri, invocation_id, idempotency_key):
        return EmailDeliveryOutcome(status=EmailDeliveryStatus.NOT_REQUESTED)


class FakeIdempotencyStore:
    def claim(self, key, payload):
        raise AssertionError("idempotency store should not be called without a key")

    def complete(self, key, response):
        raise AssertionError("idempotency store should not be called without a key")

    def abandon(self, key):
        raise AssertionError("idempotency store should not be called without a key")


class FakeStatusStore:
    def __init__(self):
        self.records = []

    def upsert_invocation(self, record):
        self.records.append(record)

    def update_invocation(self, invocation_id, **updates):
        self.records.append((invocation_id, updates))

    def append_llm_call(self, invocation_id, call):
        self.records.append((invocation_id, call))


class ApplicationPortsTest(unittest.TestCase):
    def test_invocation_application_runs_with_fake_ports(self):
        status_store = FakeStatusStore()
        service = TutorInvocationApplicationService(
            image_resolver=FakeImageResolver(),
            guardrail=FakeGuardrail(),
            observability=FakeObservability(),
            workflow=lambda **kwargs: "analysis",
            artifact_writer=FakeArtifactWriter(),
            email_coordinator=FakeEmailCoordinator(),
            idempotency_store=FakeIdempotencyStore(),
            status_store=status_store,
        )

        response = service.handle(
            {
                "image_data_uri": "data:image/png;base64,ZmFrZQ==",
                "save_analysis_pdf": False,
            }
        )

        self.assertEqual(response["analysis"], "analysis")
        self.assertNotIn("email_status", response)
        self.assertGreaterEqual(len(status_store.records), 3)


if __name__ == "__main__":
    unittest.main()
