import logging
import os
import unittest
from unittest.mock import Mock, patch

from jee_tutor.new_relic_logging import NewRelicLogConfig, NewRelicLogHandler, build_new_relic_handler


class NewRelicLoggingExtraTest(unittest.TestCase):
    def test_from_environment_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = NewRelicLogConfig.from_environment()

        self.assertFalse(config.enabled)
        self.assertEqual(config.secret_arn, "")
        self.assertEqual(config.region, "US")

    def test_emit_records_optional_context_and_serialization_failure(self):
        config = NewRelicLogConfig(enabled=True, secret_arn="arn", queue_capacity=1, batch_size=1)
        handler = NewRelicLogHandler(config, license_key="key", sender=lambda *_: None)
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
        record.correlation_id = "corr-1"
        record.trace_id = "trace-1"
        record.workflow_stage = "stage-1"
        record.terminal_outcome = "done"
        handler.emit(record)
        queued = handler.records.get_nowait()
        self.assertEqual(queued["correlation_id"], "corr-1")
        self.assertEqual(queued["trace_id"], "trace-1")
        self.assertEqual(queued["workflow_stage"], "stage-1")
        self.assertEqual(queued["terminal_outcome"], "done")

        with patch.object(handler.records, "put_nowait", side_effect=RuntimeError("boom")):
            handler.emit(record)
        self.assertGreaterEqual(handler.delivery_failure_count, 1)
        handler.close()

    def test_next_batch_and_close_are_idempotent(self):
        config = NewRelicLogConfig(enabled=True, secret_arn="arn", batch_size=2, shutdown_flush_seconds=0.1)
        handler = NewRelicLogHandler(config, license_key="key", sender=lambda *_: None)
        handler.records.put_nowait({"message": "a"})
        handler.records.put_nowait({"message": "b"})
        batch = handler._next_batch()
        self.assertEqual(len(batch), 2)
        handler.close()
        handler.close()

    def test_build_handler_success_path(self):
        secrets_client = Mock()
        secrets_client.get_secret_value.return_value = {"SecretString": "license-key"}
        config = NewRelicLogConfig(enabled=True, secret_arn="arn")
        handler = build_new_relic_handler(config, secrets_client=secrets_client, sender=lambda *_: None)
        self.assertIsInstance(handler, NewRelicLogHandler)
        handler.close()


if __name__ == "__main__":
    unittest.main()
