from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import logging
import threading
from copy import deepcopy

import boto3

from jee_tutor.email.config import EmailConfig
from jee_tutor.email.models import EmailDeliveryOutcome, EmailDeliveryRequest, EmailDeliveryStatus


logger = logging.getLogger(__name__)


class EmailDeliveryCoordinator:
    def __init__(
        self,
        *,
        lambda_client=None,
        config: EmailConfig | None = None,
        delivery_store: dict[str, EmailDeliveryOutcome] | None = None,
        delivery_id_factory: Callable[[str | None, str, str], str] | None = None,
    ):
        self.lambda_client = lambda_client
        self.config = config or EmailConfig.from_env()
        self._delivery_store = delivery_store if delivery_store is not None else {}
        self._delivery_id_factory = delivery_id_factory or self._default_delivery_id
        self._lock = threading.Lock()

    def request_delivery(
        self,
        *,
        recipient_email: str,
        pdf_uri: str,
        invocation_id: str | None,
        idempotency_key: str | None,
    ) -> EmailDeliveryOutcome:
        if not recipient_email:
            return EmailDeliveryOutcome(status=EmailDeliveryStatus.NOT_REQUESTED)

        validation_errors = self.config.validate(require_delivery_function=True)
        if validation_errors:
            error = "; ".join(validation_errors)
            logger.warning("email_delivery_config_error error=%s", error)
            return EmailDeliveryOutcome(
                status=EmailDeliveryStatus.FAILED,
                error=error,
            )

        delivery_id = self._delivery_id_factory(idempotency_key, recipient_email, pdf_uri)
        with self._lock:
            existing = self._delivery_store.get(delivery_id)
            if existing is not None:
                logger.info(
                    "email_delivery_duplicate_suppressed delivery_id=%s invocation_id=%s",
                    delivery_id,
                    invocation_id or "unknown",
                )
                return deepcopy(existing)

            request = EmailDeliveryRequest(
                delivery_id=delivery_id,
                recipient_email=recipient_email,
                pdf_uri=pdf_uri,
                invocation_id=invocation_id,
                idempotency_key=idempotency_key,
                subject_key=self.config.subject_template,
                body_template_key=self.config.body_template,
                from_address_key=self.config.from_address,
            )

            try:
                response = self._lambda_client().invoke(
                    FunctionName=self.config.delivery_function_arn,
                    InvocationType="Event",
                    Payload=json.dumps(request.model_dump()).encode("utf-8"),
                )
                status_code = int(response.get("StatusCode", 0))
                if response.get("FunctionError"):
                    raise RuntimeError(f"Lambda function error: {response['FunctionError']}")
                if status_code not in {200, 202}:
                    raise RuntimeError(f"Unexpected Lambda status code: {status_code}")
                outcome = EmailDeliveryOutcome(
                    status=EmailDeliveryStatus.QUEUED,
                    delivery_id=delivery_id,
                )
                logger.info(
                    "email_delivery_invoked delivery_id=%s invocation_id=%s status_code=%s",
                    delivery_id,
                    invocation_id or "unknown",
                    status_code,
                )
            except Exception as exc:
                outcome = EmailDeliveryOutcome(
                    status=EmailDeliveryStatus.FAILED,
                    delivery_id=delivery_id,
                    error=f"{exc.__class__.__name__}: {exc or '[no message]'}",
                )
                logger.exception(
                    "email_delivery_async_invoke_failed delivery_id=%s invocation_id=%s error_type=%s",
                    delivery_id,
                    invocation_id or "unknown",
                    exc.__class__.__name__,
                )

            self._delivery_store[delivery_id] = outcome
            return deepcopy(outcome)

    def _lambda_client(self):
        if self.lambda_client is None:
            self.lambda_client = boto3.client("lambda")
        return self.lambda_client

    @staticmethod
    def _default_delivery_id(idempotency_key: str | None, recipient_email: str, pdf_uri: str) -> str:
        normalized = json.dumps(
            {
                "idempotency_key": idempotency_key or "",
                "recipient_email": recipient_email.strip().lower(),
                "pdf_uri": pdf_uri,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
