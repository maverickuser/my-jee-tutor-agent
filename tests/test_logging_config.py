import logging
import os
import unittest
from unittest.mock import patch

from jee_tutor.logging_config import StructuredJsonFormatter, configure_logging


class FakeNewRelicHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.add_filter_calls = 0

    def emit(self, record):
        return None

    def addFilter(self, filter):  # noqa: A003
        self.add_filter_calls += 1
        return super().addFilter(filter)


class LoggingConfigTest(unittest.TestCase):
    def setUp(self):
        self.root_logger = logging.getLogger()
        self.original_handlers = list(self.root_logger.handlers)
        self.original_filters = list(self.root_logger.filters)
        self.original_level = self.root_logger.level
        for handler in list(self.root_logger.handlers):
            self.root_logger.removeHandler(handler)
        for filter_ in list(self.root_logger.filters):
            self.root_logger.removeFilter(filter_)

    def tearDown(self):
        for handler in list(self.root_logger.handlers):
            self.root_logger.removeHandler(handler)
        for filter_ in list(self.root_logger.filters):
            self.root_logger.removeFilter(filter_)
        for handler in self.original_handlers:
            self.root_logger.addHandler(handler)
        for filter_ in self.original_filters:
            self.root_logger.addFilter(filter_)
        self.root_logger.setLevel(self.original_level)

    def test_configure_logging_adds_stdout_and_new_relic_handlers_once(self):
        new_relic_handler = FakeNewRelicHandler()
        with patch.dict(
            os.environ,
            {
                "JEE_TUTOR_LOG_LEVEL": "DEBUG",
                "JEE_TUTOR_SERVICE_NAME": "custom-service",
            },
            clear=False,
        ), patch("jee_tutor.logging_config.build_new_relic_handler", return_value=new_relic_handler), patch(
            "jee_tutor.logging_config.NewRelicLogHandler", FakeNewRelicHandler
        ):
            configure_logging()
            configure_logging()

        self.assertEqual(self.root_logger.level, logging.DEBUG)
        self.assertEqual(len(self.root_logger.handlers), 2)
        self.assertTrue(any(isinstance(h.formatter, StructuredJsonFormatter) for h in self.root_logger.handlers))
        self.assertEqual(new_relic_handler.add_filter_calls, 1)

    def test_configure_logging_skips_new_relic_when_disabled(self):
        with patch.dict(
            os.environ,
            {
                "JEE_TUTOR_LOG_LEVEL": "INFO",
                "JEE_TUTOR_SERVICE_NAME": "custom-service",
            },
            clear=False,
        ), patch("jee_tutor.logging_config.build_new_relic_handler", return_value=None):
            configure_logging()

        self.assertEqual(len(self.root_logger.handlers), 1)


if __name__ == "__main__":
    unittest.main()
