import unittest
from unittest.mock import Mock, patch

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

    def test_request_delivery_returns_not_requested_without_recipient(self):
        coordinator = EmailDeliveryCoordinator(
            config=EmailConfig(
                from_address="noreply@example.com",
                subject_template="Analysis report",
                body_template="Attached is the PDF.",
                delivery_function_arn="arn:aws:lambda:ap-south-1:123:function:send-email",
            ),
        )

        outcome = coordinator.request_delivery(
            recipient_email="",
            pdf_uri="s3://attempt-bucket/maths/report.pdf",
            invocation_id="attempt-123",
            idempotency_key="attempt-123",
        )

        self.assertEqual(outcome.status, EmailDeliveryStatus.NOT_REQUESTED)

    def test_request_delivery_reports_config_errors(self):
        coordinator = EmailDeliveryCoordinator(
            config=EmailConfig(
                from_address="",
                subject_template="",
                body_template="",
                delivery_function_arn=None,
            ),
        )

        outcome = coordinator.request_delivery(
            recipient_email="student@example.com",
            pdf_uri="s3://attempt-bucket/maths/report.pdf",
            invocation_id="attempt-123",
            idempotency_key="attempt-123",
        )

        self.assertEqual(outcome.status, EmailDeliveryStatus.FAILED)
        self.assertIn("EMAIL_FROM_ADDRESS is required.", outcome.error)

    def test_request_delivery_handles_lambda_function_error_and_status(self):
        lambda_client = Mock()
        lambda_client.invoke.return_value = {"StatusCode": 202, "FunctionError": "Unhandled"}
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
        self.assertIn("Lambda function error", outcome.error)

    def test_request_delivery_handles_unexpected_status_code(self):
        lambda_client = Mock()
        lambda_client.invoke.return_value = {"StatusCode": 500}
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
        self.assertIn("Unexpected Lambda status code", outcome.error)

    def test_request_delivery_uses_default_lambda_client_when_missing(self):
        lambda_client = Mock()
        lambda_client.invoke.return_value = {"StatusCode": 202}
        with patch("jee_tutor.email.delivery.boto3.client", return_value=lambda_client):
            coordinator = EmailDeliveryCoordinator(
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
        lambda_client.invoke.assert_called_once()

    def test_default_delivery_id_normalizes_email(self):
        digest_a = EmailDeliveryCoordinator._default_delivery_id(
            "attempt-123",
            "Student@Example.Com",
            "s3://attempt-bucket/maths/report.pdf",
        )
        digest_b = EmailDeliveryCoordinator._default_delivery_id(
            "attempt-123",
            "student@example.com",
            "s3://attempt-bucket/maths/report.pdf",
        )

        self.assertEqual(digest_a, digest_b)


if __name__ == "__main__":
    unittest.main()
