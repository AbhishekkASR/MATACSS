"""Centralized structured logging helpers for API and worker runtime events."""

from __future__ import annotations

import contextvars
import logging
import logging.config
import re
from uuid import uuid4

_CORRELATION_ID = contextvars.ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Return the active request or job correlation ID."""
    value = _CORRELATION_ID.get()
    return value or "-"


def set_correlation_id(value: str | None) -> contextvars.Token[str]:
    """Bind a correlation ID to the current async task context."""
    correlation_id = value or uuid4().hex
    return _CORRELATION_ID.set(correlation_id)


def reset_correlation_id(token: contextvars.Token[str]) -> None:
    """Release the current correlation ID after request or job scope ends."""
    _CORRELATION_ID.reset(token)


def sanitize_log_value(value: str | None) -> str:
    """Redact sensitive values before they are emitted to logs."""
    if value is None:
        return ""
    text = str(value)
    redacted = text
    patterns = (
        (r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+", r"\1[REDACTED]"),
        (r"(?i)(password\s*[:=]\s*)[^,\s]+", r"\1[REDACTED]"),
        (r"(?i)(secret\s*[:=]\s*)[^,\s]+", r"\1[REDACTED]"),
        (r"(?i)(token\s*[:=]\s*)[^,\s]+", r"\1[REDACTED]"),
        (r"(?i)(jwt\s*[:=]\s*)[^,\s]+", r"\1[REDACTED]"),
        (r"(?i)(api[_-]?key\s*[:=]\s*)[^,\s]+", r"\1[REDACTED]"),
    )
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def sanitize_exception_message(exc: BaseException | None) -> str:
    """Return a safe error summary without exposing credentials or runtime payloads."""
    if exc is None:
        return "unknown error"
    message = str(exc)
    if not message:
        return exc.__class__.__name__
    return sanitize_log_value(message) or exc.__class__.__name__


class CorrelationIdFilter(logging.Filter):
    """Attach the active correlation ID to each log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        if not hasattr(record, "event"):
            record.event = "log"
        return True


def configure_logging(settings: object) -> None:
    """Configure logging from the app settings object."""
    level_name = str(getattr(settings, "log_level", "INFO")).upper()
    log_level = getattr(logging, level_name, logging.INFO)
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "correlation": {
                    "()": CorrelationIdFilter,
                }
            },
            "formatters": {
                "standard": {
                    "format": "%(asctime)s %(levelname)s %(name)s correlation_id=%(correlation_id)s event=%(event)s %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "stream": "ext://sys.stdout",
                    "filters": ["correlation"],
                }
            },
            "root": {
                "handlers": ["console"],
                "level": log_level,
            },
        }
    )
