from __future__ import annotations

import logging
import os
import sys


DEFAULT_SERVICE_NAME = "jee-tutor-agent"
DEFAULT_LOG_FORMAT = (
    "%(asctime)s %(levelname)s service=%(service_name)s logger=%(name)s %(message)s"
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
    root_logger.addFilter(ServiceNameFilter(service_name))
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.addFilter(ServiceNameFilter(service_name))
        handler.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT))
        root_logger.addHandler(handler)

    root_logger.setLevel(level)
