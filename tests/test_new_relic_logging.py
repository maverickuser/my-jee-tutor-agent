import logging
import threading
import time
import unittest
import os
from unittest.mock import Mock, patch

from jee_tutor.new_relic_logging import (
    NewRelicLogConfig,
    NewRelicLogHandler,
    build_new_relic_handler,
    redact_log_value,
)


class FakeSecrets:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error
        self.calls = []

    def get_secret_value(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"SecretString": self.value}


class NewRelicLoggingTest(unittest.TestCase):
    def test_redacts_images_credentials_and_signed_urls(self):
        value = (
            "student@example.com data:image/png;base64,QUJD api_key=secret "
            "https://example.test/x?X-Amz-Signature=abc"
        )
        redacted = redact_log_value(value)
        self.assertNotIn("QUJD", redacted)
        self.assertNotIn("secret", redacted)
        self.assertNotIn("Signature", redacted)
        self.assertNotIn("student@example.com", redacted)

    def test_disabled_and_secret_failure_fail_open(self):
        disabled = build_new_relic_handler(
            NewRelicLogConfig(enabled=False, secret_arn="arn"),
            secrets_client=FakeSecrets("key"),
        )
        self.assertIsNone(disabled)
        failed = build_new_relic_handler(
            NewRelicLogConfig(enabled=True, secret_arn="arn"),
            secrets_client=FakeSecrets(error=RuntimeError("denied")),
        )
        self.assertIsNone(failed)

    def test_emit_only_enqueues_and_worker_batches(self):
        delivered = []
        delivery_event = threading.Event()

        def sender(batch, key, timeout):
            delivered.extend(batch)
            delivery_event.set()

        handler = build_new_relic_handler(
            NewRelicLogConfig(
                enabled=True,
                secret_arn="arn",
                batch_size=10,
                shutdown_flush_seconds=1,
            ),
            secrets_client=FakeSecrets("license"),
            sender=sender,
        )
        self.assertIsNotNone(handler)
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
        started = time.monotonic()
        handler.emit(record)
        self.assertLess(time.monotonic() - started, 0.1)
        self.assertTrue(delivery_event.wait(1))
        handler.close()
        self.assertEqual(delivered[0]["message"], "hello")

    def test_queue_overflow_and_delivery_failure_do_not_raise(self):
        blocker = threading.Event()

        def failing_sender(batch, key, timeout):
            blocker.wait(0.05)
            raise TimeoutError("slow")

        handler = NewRelicLogHandler(
            NewRelicLogConfig(
                enabled=True,
                secret_arn="arn",
                queue_capacity=1,
                retry_count=0,
                shutdown_flush_seconds=0.2,
            ),
            license_key="license",
            sender=failing_sender,
        )
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
        for _ in range(20):
            handler.emit(record)
        blocker.set()
        handler.close()
        self.assertGreater(handler.dropped_count + handler.delivery_failure_count, 0)

    def test_environment_config_empty_secret_and_http_sender(self):
        with patch.dict(
            os.environ,
            {
                "NEW_RELIC_LOG_ENABLED": "true",
                "NEW_RELIC_LICENSE_KEY_SECRET_ARN": "arn",
                "NEW_RELIC_REGION": "EU",
            },
            clear=False,
        ):
            config = NewRelicLogConfig.from_environment()
        self.assertTrue(config.enabled)
        self.assertEqual(config.region, "EU")
        self.assertIsNone(
            build_new_relic_handler(
                config,
                secrets_client=FakeSecrets(" "),
            )
        )

        handler = NewRelicLogHandler(
            config,
            license_key="key",
            sender=lambda *_: None,
        )
        response = Mock()
        response.status = 202
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("jee_tutor.new_relic_logging.urllib.request.urlopen", return_value=response):
            handler._send([{"message": "canary"}], "key", 1)
        response.status = 500
        with (
            patch("jee_tutor.new_relic_logging.urllib.request.urlopen", return_value=response),
            self.assertRaises(RuntimeError),
        ):
            handler._send([{"message": "canary"}], "key", 1)
        handler.close()
