import unittest
from unittest.mock import Mock

from jee_tutor.email.config import EmailConfig
from jee_tutor.email.delivery import EmailDeliveryCoordinator
from jee_tutor.email.models import EmailDeliveryStatus


class EmailDeliveryCoordinatorTest(unittest.TestCase):
    def test_request_delivery_invokes_lambda_once_and_returns_queued(self):
        lambda_client = Mock()
        lambda_client.invoke.return_value = {"StatusCode": 202}
        coordinator = EmailDeliveryCoordinator(
            lambda_client=lambda_client,
            config=EmailConfig(
                from_address="noreply@example.com",
                subject_template="Analysis report",
                body_template="Attached is the PDF.",
                delivery_function_arn="arn:aws:lambda:ap-south-1:123:function:send-email",
            ),
        )

        outcome = coordinator.request_delivery(
            recipient_email="student@example.com",
            pdf_uri="s3://attempt-bucket/maths/report.pdf",
            invocation_id="attempt-123",
            idempotency_key="attempt-123",
        )

        self.assertEqual(outcome.status, EmailDeliveryStatus.QUEUED)
        self.assertIsNotNone(outcome.delivery_id)
        lambda_client.invoke.assert_called_once()

    def test_request_delivery_suppresses_duplicate_delivery_ids(self):
        lambda_client = Mock()
        lambda_client.invoke.return_value = {"StatusCode": 202}
        coordinator = EmailDeliveryCoordinator(
            lambda_client=lambda_client,
            config=EmailConfig(
                from_address="noreply@example.com",
                subject_template="Analysis report",
                body_template="Attached is the PDF.",
                delivery_function_arn="arn:aws:lambda:ap-south-1:123:function:send-email",
            ),
        )

        first = coordinator.request_delivery(
            recipient_email="student@example.com",
            pdf_uri="s3://attempt-bucket/maths/report.pdf",
            invocation_id="attempt-123",
            idempotency_key="attempt-123",
        )
        second = coordinator.request_delivery(
            recipient_email="student@example.com",
            pdf_uri="s3://attempt-bucket/maths/report.pdf",
            invocation_id="attempt-123",
            idempotency_key="attempt-123",
        )

        self.assertEqual(first, second)
        lambda_client.invoke.assert_called_once()

    def test_request_delivery_returns_failed_when_lambda_raises(self):
        lambda_client = Mock()
        lambda_client.invoke.side_effect = RuntimeError("lambda unavailable")
        coordinator = EmailDeliveryCoordinator(
            lambda_client=lambda_client,
            config=EmailConfig(
                from_address="noreply@example.com",
                subject_template="Analysis report",
                body_template="Attached is the PDF.",
                delivery_function_arn="arn:aws:lambda:ap-south-1:123:function:send-email",
            ),
        )

        outcome = coordinator.request_delivery(
            recipient_email="student@example.com",
            pdf_uri="s3://attempt-bucket/maths/report.pdf",
            invocation_id="attempt-123",
            idempotency_key="attempt-123",
        )

        self.assertEqual(outcome.status, EmailDeliveryStatus.FAILED)
        self.assertIn("lambda unavailable", outcome.error)


if __name__ == "__main__":
    unittest.main()
