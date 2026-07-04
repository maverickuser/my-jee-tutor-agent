from __future__ import annotations

import logging
import threading
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from jee_tutor.artifacts.writer import AnalysisArtifactWriter
from jee_tutor.email.config import EmailConfig
from jee_tutor.email.models import EmailDeliveryEvent, EmailDeliveryOutcome, EmailDeliveryStatus
from jee_tutor.email.ses_adapter import SesEmailSender, attachment_filename_from_pdf_uri
from jee_tutor.logging_config import configure_logging


configure_logging()


logger = logging.getLogger(__name__)


class EmailDeliveryWorker:
    def __init__(
        self,
        *,
        config: EmailConfig | None = None,
        s3_client=None,
        ses_sender: SesEmailSender | None = None,
        delivery_store: dict[str, EmailDeliveryOutcome] | None = None,
    ):
        self.config = config or EmailConfig.from_env()
        self.s3_client = s3_client
        self.ses_sender = ses_sender or SesEmailSender()
        self._delivery_store = delivery_store if delivery_store is not None else {}
        self._lock = threading.Lock()

    def handle(self, event: dict[str, Any]) -> dict[str, Any]:
        try:
            delivery_event = EmailDeliveryEvent.model_validate(event)
        except ValidationError as exc:
            logger.warning(
                "email_delivery_invalid_event validation_errors=%s",
                [error["msg"] for error in exc.errors()],
            )
            outcome = EmailDeliveryOutcome(
                status=EmailDeliveryStatus.FAILED,
                error="Invalid email delivery event.",
            )
            return outcome.model_dump(exclude_none=True, mode="json")

        with self._lock:
            existing = self._delivery_store.get(delivery_event.delivery_id)
            if existing is not None:
                logger.info(
                    "email_delivery_worker_duplicate delivery_id=%s",
                    delivery_event.delivery_id,
                )
                return deepcopy(existing).model_dump(exclude_none=True, mode="json")

            try:
                config_errors = self.config.validate()
                if config_errors:
                    raise ValueError("; ".join(config_errors))
                bucket, key = AnalysisArtifactWriter._parse_s3_uri(delivery_event.pdf_uri)
                pdf_bytes = self._s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
                response = self.ses_sender.send(
                    from_address=self.config.from_address,
                    recipient_email=delivery_event.recipient_email,
                    subject=self._render_subject(delivery_event),
                    body_html=self._render_body(delivery_event),
                    attachment_bytes=pdf_bytes,
                    attachment_filename=attachment_filename_from_pdf_uri(delivery_event.pdf_uri),
                )
                logger.info(
                    "email_delivery_worker_succeeded delivery_id=%s pdf_uri=%s request_id=%s",
                    delivery_event.delivery_id,
                    delivery_event.pdf_uri,
                    response.get("MessageId", "unknown"),
                )
                outcome = EmailDeliveryOutcome(
                    status=EmailDeliveryStatus.SUCCEEDED,
                    delivery_id=delivery_event.delivery_id,
                )
            except Exception as exc:
                logger.exception(
                    "email_delivery_worker_failed delivery_id=%s pdf_uri=%s error_type=%s",
                    delivery_event.delivery_id,
                    delivery_event.pdf_uri,
                    exc.__class__.__name__,
                )
                outcome = EmailDeliveryOutcome(
                    status=EmailDeliveryStatus.FAILED,
                    delivery_id=delivery_event.delivery_id,
                    error=f"{exc.__class__.__name__}: {exc or '[no message]'}",
                )

            self._delivery_store[delivery_event.delivery_id] = outcome
            return outcome.model_dump(exclude_none=True, mode="json")

    def _s3_client(self):
        if self.s3_client is None:
            import boto3

            self.s3_client = boto3.client("s3")
        return self.s3_client

    def _render_subject(self, event: EmailDeliveryEvent) -> str:
        return self.config.subject_template.format(
            recipient_email=event.recipient_email,
            pdf_uri=event.pdf_uri,
            delivery_id=event.delivery_id,
        )

    def _render_body(self, event: EmailDeliveryEvent) -> str:
        return self.config.body_template.format(
            recipient_email=event.recipient_email,
            pdf_uri=event.pdf_uri,
            delivery_id=event.delivery_id,
        )


def handle_email_delivery(event: dict[str, Any], _context: Any | None = None) -> dict[str, Any]:
    return EmailDeliveryWorker().handle(event)
