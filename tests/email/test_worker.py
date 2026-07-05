import unittest
from unittest.mock import Mock, patch

from jee_tutor.email.config import EmailConfig
from jee_tutor.email.models import EmailDeliveryStatus
from jee_tutor.email.worker import EmailDeliveryWorker, handle_email_delivery


class EmailDeliveryWorkerTest(unittest.TestCase):
    def test_handle_sends_email_and_returns_succeeded(self):
        s3_client = Mock()
        s3_client.get_object.return_value = {"Body": Mock(read=Mock(return_value=b"pdf-bytes"))}
        ses_sender = Mock()
        ses_sender.send.return_value = {"MessageId": "msg-123"}
        worker = EmailDeliveryWorker(
            config=EmailConfig(
                from_address="noreply@example.com",
                subject_template="Analysis report",
                body_template="Attached is the PDF.",
            ),
            s3_client=s3_client,
            ses_sender=ses_sender,
        )

        response = worker.handle(
            {
                "delivery_id": "delivery-123",
                "recipient_email": "student@example.com",
                "pdf_uri": "s3://attempt-bucket/maths/report.pdf",
                "invocation_id": "attempt-123",
                "idempotency_key": "attempt-123",
                "subject_key": "Analysis report",
                "body_template_key": "Attached is the PDF.",
                "from_address_key": "noreply@example.com",
            }
        )

        self.assertEqual(response["status"], EmailDeliveryStatus.SUCCEEDED.value)
        ses_sender.send.assert_called_once()

    def test_handle_suppresses_duplicate_delivery_ids(self):
        s3_client = Mock()
        s3_client.get_object.return_value = {"Body": Mock(read=Mock(return_value=b"pdf-bytes"))}
        ses_sender = Mock()
        ses_sender.send.return_value = {"MessageId": "msg-123"}
        worker = EmailDeliveryWorker(
            config=EmailConfig(
                from_address="noreply@example.com",
                subject_template="Analysis report",
                body_template="Attached is the PDF.",
            ),
            s3_client=s3_client,
            ses_sender=ses_sender,
        )
        event = {
            "delivery_id": "delivery-123",
            "recipient_email": "student@example.com",
            "pdf_uri": "s3://attempt-bucket/maths/report.pdf",
            "invocation_id": "attempt-123",
            "idempotency_key": "attempt-123",
            "subject_key": "Analysis report",
            "body_template_key": "Attached is the PDF.",
            "from_address_key": "noreply@example.com",
        }

        first = worker.handle(event)
        second = worker.handle(event)

        self.assertEqual(first, second)
        ses_sender.send.assert_called_once()

    def test_handle_email_delivery_wrapper(self):
        response = handle_email_delivery(
            {
                "delivery_id": "delivery-123",
                "recipient_email": "student@example.com",
                "pdf_uri": "s3://attempt-bucket/maths/report.pdf",
                "subject_key": "Analysis report",
                "body_template_key": "Attached is the PDF.",
                "from_address_key": "noreply@example.com",
            }
        )

        self.assertEqual(response["status"], EmailDeliveryStatus.FAILED.value)

    def test_handle_returns_failed_for_invalid_event(self):
        worker = EmailDeliveryWorker(
            config=EmailConfig(
                from_address="noreply@example.com",
                subject_template="Analysis report",
                body_template="Attached is the PDF.",
            ),
        )

        response = worker.handle({"delivery_id": "delivery-123"})

        self.assertEqual(response["status"], EmailDeliveryStatus.FAILED.value)
        self.assertIn("Invalid email delivery event.", response["error"])

    def test_handle_returns_failed_when_config_invalid(self):
        s3_client = Mock()
        ses_sender = Mock()
        worker = EmailDeliveryWorker(
            config=EmailConfig(
                from_address="",
                subject_template="",
                body_template="",
            ),
            s3_client=s3_client,
            ses_sender=ses_sender,
        )

        response = worker.handle(
            {
                "delivery_id": "delivery-123",
                "recipient_email": "student@example.com",
                "pdf_uri": "s3://attempt-bucket/maths/report.pdf",
                "invocation_id": "attempt-123",
                "idempotency_key": "attempt-123",
                "subject_key": "Analysis report",
                "body_template_key": "Attached is the PDF.",
                "from_address_key": "noreply@example.com",
            }
        )

        self.assertEqual(response["status"], EmailDeliveryStatus.FAILED.value)
        self.assertIn("EMAIL_FROM_ADDRESS is required.", response["error"])
        s3_client.get_object.assert_not_called()
        ses_sender.send.assert_not_called()

    def test_handle_returns_failed_when_s3_or_ses_raises(self):
        s3_client = Mock()
        s3_client.get_object.side_effect = RuntimeError("s3 unavailable")
        ses_sender = Mock()
        worker = EmailDeliveryWorker(
            config=EmailConfig(
                from_address="noreply@example.com",
                subject_template="Analysis report",
                body_template="Attached is the PDF.",
            ),
            s3_client=s3_client,
            ses_sender=ses_sender,
        )

        response = worker.handle(
            {
                "delivery_id": "delivery-123",
                "recipient_email": "student@example.com",
                "pdf_uri": "s3://attempt-bucket/maths/report.pdf",
                "invocation_id": "attempt-123",
                "idempotency_key": "attempt-123",
                "subject_key": "Analysis report",
                "body_template_key": "Attached is the PDF.",
                "from_address_key": "noreply@example.com",
            }
        )

        self.assertEqual(response["status"], EmailDeliveryStatus.FAILED.value)
        self.assertIn("s3 unavailable", response["error"])
        ses_sender.send.assert_not_called()

    def test_handle_uses_default_s3_client_when_missing(self):
        s3_client = Mock()
        s3_client.get_object.return_value = {"Body": Mock(read=Mock(return_value=b"pdf-bytes"))}
        ses_sender = Mock()
        ses_sender.send.return_value = {"MessageId": "msg-123"}
        with patch("boto3.client", return_value=s3_client):
            worker = EmailDeliveryWorker(
                config=EmailConfig(
                    from_address="noreply@example.com",
                    subject_template="Analysis report",
                    body_template="Attached is the PDF.",
                ),
                ses_sender=ses_sender,
            )
            response = worker.handle(
                {
                    "delivery_id": "delivery-123",
                    "recipient_email": "student@example.com",
                    "pdf_uri": "s3://attempt-bucket/maths/report.pdf",
                    "invocation_id": "attempt-123",
                    "idempotency_key": "attempt-123",
                    "subject_key": "Analysis report",
                    "body_template_key": "Attached is the PDF.",
                    "from_address_key": "noreply@example.com",
                }
            )

        self.assertEqual(response["status"], EmailDeliveryStatus.SUCCEEDED.value)
        s3_client.get_object.assert_called_once()


if __name__ == "__main__":
    unittest.main()
