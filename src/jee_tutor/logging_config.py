from __future__ import annotations

import logging
import os
import json
import sys

from jee_tutor.new_relic_logging import NewRelicLogHandler, build_new_relic_handler, redact_log_value


DEFAULT_SERVICE_NAME = "jee-tutor-agent"
DEFAULT_LOG_FORMAT = (
    "%(asctime)s %(levelname)s service=%(service_name)s logger=%(name)s %(message)s"
)


class StructuredJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": self.formatTime(record, self.datefmt),
                "severity": record.levelname,
                "service": getattr(record, "service_name", DEFAULT_SERVICE_NAME),
                "environment": os.getenv("APP_ENVIRONMENT", "unknown"),
                "commit_sha": os.getenv("JEE_TUTOR_GIT_SHA", "unknown"),
                "logger": record.name,
                "message": redact_log_value(record.getMessage()),
            },
            separators=(",", ":"),
        )


class ServiceNameFilter(logging.Filter):
    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.service_name = self.service_name
        return True


def configure_logging() -> None:
    """Configure application logging for container stdout collection."""
    level_name = os.getenv("JEE_TUTOR_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    service_name = os.getenv("JEE_TUTOR_SERVICE_NAME", DEFAULT_SERVICE_NAME)

    root_logger = logging.getLogger()
    if not any(isinstance(existing_filter, ServiceNameFilter) for existing_filter in root_logger.filters):
        root_logger.addFilter(ServiceNameFilter(service_name))

    has_stdout_handler = any(
        isinstance(handler, logging.StreamHandler) and isinstance(handler.formatter, StructuredJsonFormatter)
        for handler in root_logger.handlers
    )
    if not has_stdout_handler:
        handler = logging.StreamHandler(sys.stdout)
        handler.addFilter(ServiceNameFilter(service_name))
        handler.setFormatter(StructuredJsonFormatter())
        root_logger.addHandler(handler)

    has_new_relic_handler = any(isinstance(handler, NewRelicLogHandler) for handler in root_logger.handlers)
    if not has_new_relic_handler:
        new_relic_handler = build_new_relic_handler()
        if new_relic_handler:
            new_relic_handler.addFilter(ServiceNameFilter(service_name))
            root_logger.addHandler(new_relic_handler)
            root_logger.info("new_relic_deployment_canary outcome=initialized")

    root_logger.setLevel(level)
