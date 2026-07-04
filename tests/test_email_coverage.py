import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

from jee_tutor.email.config import EmailConfig
from jee_tutor.email.delivery import EmailDeliveryCoordinator
from jee_tutor.email.models import EmailDeliveryStatus
from jee_tutor.email.ses_adapter import SesEmailSender, attachment_filename_from_pdf_uri
from jee_tutor.email.worker import EmailDeliveryWorker, handle_email_delivery


class EmailCoverageTest(unittest.TestCase):
    def test_email_config_env_and_validation(self):
        with patch.dict(
            os.environ,
            {
                "EMAIL_FROM_ADDRESS": " analysis@example.com ",
                "EMAIL_SUBJECT_TEMPLATE": " Report ",
                "EMAIL_BODY_TEMPLATE": " <p>Hi</p> ",
                "EMAIL_REGION": " ",
                "EMAIL_DELIVERY_PROVIDER": " ",
                "EMAIL_DELIVERY_FUNCTION_ARN": " ",
            },
            clear=False,
        ):
            config = EmailConfig.from_env()

        self.assertEqual(config.from_address, "analysis@example.com")
        self.assertEqual(config.subject_template, "Report")
        self.assertEqual(config.body_template, "<p>Hi</p>")
        self.assertIsNone(config.region)
        self.assertEqual(config.delivery_provider, "lambda")
        self.assertIsNone(config.delivery_function_arn)
        self.assertEqual(
            config.validate(require_delivery_function=True),
            ["EMAIL_DELIVERY_FUNCTION_ARN is required when using lambda delivery."],
        )

    def test_delivery_coordinator_queued_and_duplicate_paths(self):
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
            recipient_email="Student@Example.Com",
            pdf_uri="s3://attempt-bucket/maths/report.pdf",
            invocation_id="attempt-123",
            idempotency_key="attempt-123",
        )
        duplicate = coordinator.request_delivery(
            recipient_email="student@example.com",
            pdf_uri="s3://attempt-bucket/maths/report.pdf",
            invocation_id="attempt-123",
            idempotency_key="attempt-123",
        )

        self.assertEqual(outcome.status, EmailDeliveryStatus.QUEUED)
        self.assertEqual(duplicate.status, EmailDeliveryStatus.QUEUED)
        lambda_client.invoke.assert_called_once()

    def test_delivery_coordinator_branching(self):
        coordinator = EmailDeliveryCoordinator(
            config=EmailConfig(
                from_address="noreply@example.com",
                subject_template="Analysis report",
                body_template="Attached is the PDF.",
                delivery_function_arn="arn:aws:lambda:ap-south-1:123:function:send-email",
            ),
        )
        self.assertEqual(
            coordinator.request_delivery(
                recipient_email="",
                pdf_uri="s3://attempt-bucket/maths/report.pdf",
                invocation_id="attempt-123",
                idempotency_key="attempt-123",
            ).status,
            EmailDeliveryStatus.NOT_REQUESTED,
        )

        invalid = EmailDeliveryCoordinator(
            config=EmailConfig(from_address="", subject_template="", body_template=""),
        ).request_delivery(
            recipient_email="student@example.com",
            pdf_uri="s3://attempt-bucket/maths/report.pdf",
            invocation_id="attempt-123",
            idempotency_key="attempt-123",
        )
        self.assertEqual(invalid.status, EmailDeliveryStatus.FAILED)

        function_error_client = Mock()
        function_error_client.invoke.return_value = {"StatusCode": 202, "FunctionError": "Unhandled"}
        function_error = EmailDeliveryCoordinator(
            lambda_client=function_error_client,
            config=EmailConfig(
                from_address="noreply@example.com",
                subject_template="Analysis report",
                body_template="Attached is the PDF.",
                delivery_function_arn="arn:aws:lambda:ap-south-1:123:function:send-email",
            ),
        ).request_delivery(
            recipient_email="student@example.com",
            pdf_uri="s3://attempt-bucket/maths/report.pdf",
            invocation_id="attempt-123",
            idempotency_key="attempt-123",
        )
        self.assertEqual(function_error.status, EmailDeliveryStatus.FAILED)

        bad_status_client = Mock()
        bad_status_client.invoke.return_value = {"StatusCode": 500}
        bad_status = EmailDeliveryCoordinator(
            lambda_client=bad_status_client,
            config=EmailConfig(
                from_address="noreply@example.com",
                subject_template="Analysis report",
                body_template="Attached is the PDF.",
                delivery_function_arn="arn:aws:lambda:ap-south-1:123:function:send-email",
            ),
        ).request_delivery(
            recipient_email="student@example.com",
            pdf_uri="s3://attempt-bucket/maths/report.pdf",
            invocation_id="attempt-123",
            idempotency_key="attempt-123",
        )
        self.assertEqual(bad_status.status, EmailDeliveryStatus.FAILED)

        with patch("jee_tutor.email.delivery.boto3.client", return_value=Mock()):
            default_client = EmailDeliveryCoordinator(
                config=EmailConfig(
                    from_address="noreply@example.com",
                    subject_template="Analysis report",
                    body_template="Attached is the PDF.",
                    delivery_function_arn="arn:aws:lambda:ap-south-1:123:function:send-email",
                ),
            )
            self.assertIsNotNone(default_client._lambda_client())

        self.assertEqual(
            EmailDeliveryCoordinator._default_delivery_id(
                "attempt-123",
                "Student@Example.Com",
                "s3://attempt-bucket/maths/report.pdf",
            ),
            EmailDeliveryCoordinator._default_delivery_id(
                "attempt-123",
                "student@example.com",
                "s3://attempt-bucket/maths/report.pdf",
            ),
        )

    def test_ses_sender_and_attachment_filename(self):
        ses_client = Mock()
        ses_client.send_raw_email.return_value = {"MessageId": "msg-123"}
        sender = SesEmailSender(ses_client=ses_client)
        response = sender.send(
            from_address="analysis@example.com",
            recipient_email="student@example.com",
            subject="Report",
            body_html="<p>Hello</p>",
            attachment_bytes=b"pdf-bytes",
            attachment_filename=attachment_filename_from_pdf_uri("s3://bucket/folder/report"),
        )

        self.assertEqual(response["MessageId"], "msg-123")
        self.assertEqual(attachment_filename_from_pdf_uri("s3://bucket/folder/report"), "report.pdf")
        self.assertEqual(attachment_filename_from_pdf_uri("s3://bucket/"), "analysis.pdf")
        ses_client.send_raw_email.assert_called_once()

    def test_worker_success_failure_duplicate_and_invalid_event(self):
        s3_client = Mock()
        s3_client.get_object.return_value = {"Body": Mock(read=Mock(return_value=b"pdf-bytes"))}
        ses_sender = Mock()
        ses_sender.send.return_value = {"MessageId": "msg-123"}
        worker = EmailDeliveryWorker(
            config=EmailConfig(
                from_address="noreply@example.com",
                subject_template="Analysis report {delivery_id}",
                body_template="Attached {pdf_uri} for {recipient_email}",
            ),
            s3_client=s3_client,
            ses_sender=ses_sender,
        )

        success_event = {
            "delivery_id": "delivery-123",
            "recipient_email": "student@example.com",
            "pdf_uri": "s3://attempt-bucket/maths/report.pdf",
            "invocation_id": "attempt-123",
            "idempotency_key": "attempt-123",
            "subject_key": "Analysis report",
            "body_template_key": "Attached is the PDF.",
            "from_address_key": "noreply@example.com",
        }
        success = worker.handle(success_event)
        duplicate = worker.handle(success_event)
        invalid = worker.handle({"delivery_id": "delivery-123"})

        self.assertEqual(success["status"], EmailDeliveryStatus.SUCCEEDED.value)
        self.assertEqual(duplicate["status"], EmailDeliveryStatus.SUCCEEDED.value)
        self.assertEqual(invalid["status"], EmailDeliveryStatus.FAILED.value)
        ses_sender.send.assert_called_once()

        failing_worker = EmailDeliveryWorker(
            config=EmailConfig(from_address="", subject_template="", body_template=""),
            s3_client=s3_client,
            ses_sender=ses_sender,
        )
        config_failure = failing_worker.handle(success_event)
        self.assertEqual(config_failure["status"], EmailDeliveryStatus.FAILED.value)

        s3_fail_worker = EmailDeliveryWorker(
            config=EmailConfig(
                from_address="noreply@example.com",
                subject_template="Analysis report",
                body_template="Attached is the PDF.",
            ),
            s3_client=Mock(get_object=Mock(side_effect=RuntimeError("s3 unavailable"))),
            ses_sender=Mock(),
        )
        s3_failure = s3_fail_worker.handle(success_event)
        self.assertEqual(s3_failure["status"], EmailDeliveryStatus.FAILED.value)

        fake_boto3 = types.SimpleNamespace(client=Mock(return_value=s3_client))
        with patch.dict(sys.modules, {"boto3": fake_boto3}):
            worker_without_client = EmailDeliveryWorker(
                config=EmailConfig(
                    from_address="noreply@example.com",
                    subject_template="Analysis report",
                    body_template="Attached is the PDF.",
                ),
                ses_sender=ses_sender,
            )
            worker_without_client.handle(success_event)

        wrapper_response = handle_email_delivery(
            {
                "delivery_id": "delivery-123",
                "recipient_email": "student@example.com",
                "pdf_uri": "s3://attempt-bucket/maths/report.pdf",
                "subject_key": "Analysis report",
                "body_template_key": "Attached is the PDF.",
                "from_address_key": "noreply@example.com",
            }
        )
        self.assertEqual(wrapper_response["status"], EmailDeliveryStatus.FAILED.value)


if __name__ == "__main__":
    unittest.main()
