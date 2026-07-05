from __future__ import annotations

from email.message import EmailMessage
from email.utils import parseaddr
import logging
from urllib.parse import urlparse

import boto3


logger = logging.getLogger(__name__)


class SesEmailSender:
    def __init__(self, *, ses_client=None):
        self.ses_client = ses_client

    def send(
        self,
        *,
        from_address: str,
        recipient_email: str,
        subject: str,
        body_html: str,
        attachment_bytes: bytes,
        attachment_filename: str,
    ) -> dict[str, object]:
        _from_name, from_email = parseaddr(from_address)
        source_address = from_email or from_address.strip()
        if "@" not in source_address:
            raise ValueError("from_address must include a valid email address.")
        message = EmailMessage()
        message["From"] = from_address
        message["To"] = recipient_email
        message["Subject"] = subject
        message.set_content("Your analysis PDF is attached.")
        message.add_alternative(body_html, subtype="html")
        message.add_attachment(
            attachment_bytes,
            maintype="application",
            subtype="pdf",
            filename=attachment_filename,
        )
        raw_message = message.as_bytes()
        response = self._ses_client().send_raw_email(
            Source=source_address,
            Destinations=[recipient_email],
            RawMessage={"Data": raw_message},
        )
        logger.info(
            "email_ses_send source=%s recipient_domain=%s bytes=%s",
            source_address,
            recipient_email.split("@", 1)[-1] if "@" in recipient_email else "unknown",
            len(raw_message),
        )
        return response

    def _ses_client(self):
        if self.ses_client is None:
            self.ses_client = boto3.client("ses")
        return self.ses_client


def attachment_filename_from_pdf_uri(pdf_uri: str) -> str:
    path = urlparse(pdf_uri).path.lstrip("/")
    filename = path.rsplit("/", 1)[-1] if path else "analysis.pdf"
    if not filename.lower().endswith(".pdf"):
        return f"{filename}.pdf"
    return filename
