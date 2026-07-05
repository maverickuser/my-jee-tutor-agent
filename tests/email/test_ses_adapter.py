import unittest
from unittest.mock import Mock

from jee_tutor.email.ses_adapter import SesEmailSender, attachment_filename_from_pdf_uri


class SesAdapterTest(unittest.TestCase):
    def test_attachment_filename_from_pdf_uri_handles_common_paths(self):
        self.assertEqual(
            attachment_filename_from_pdf_uri("s3://bucket/folder/report.pdf"),
            "report.pdf",
        )
        self.assertEqual(
            attachment_filename_from_pdf_uri("s3://bucket/folder/report"),
            "report.pdf",
        )
        self.assertEqual(
            attachment_filename_from_pdf_uri("s3://bucket/"),
            "analysis.pdf",
        )

    def test_send_uses_ses_raw_email(self):
        ses_client = Mock()
        ses_client.send_raw_email.return_value = {"MessageId": "msg-123"}
        sender = SesEmailSender(ses_client=ses_client)

        response = sender.send(
            from_address="Koncept Agent App <sociusnest@gmail.com>",
            recipient_email="student@example.com",
            subject="Report",
            body_html="<p>Hello</p>",
            attachment_bytes=b"pdf-bytes",
            attachment_filename="report.pdf",
        )

        self.assertEqual(response["MessageId"], "msg-123")
        ses_client.send_raw_email.assert_called_once()
        self.assertEqual(ses_client.send_raw_email.call_args.kwargs["Source"], "sociusnest@gmail.com")
        raw_message = ses_client.send_raw_email.call_args.kwargs["RawMessage"]["Data"]
        self.assertIn(b"Koncept Agent App <sociusnest@gmail.com>", raw_message)
        self.assertIn(b"student@example.com", raw_message)
        self.assertIn(b"report.pdf", raw_message)


if __name__ == "__main__":
    unittest.main()
