"""Structured logging configuration using structlog."""

import logging
import structlog
from typing import Any


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for the application."""
    structlog.configure(
        processors=[
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure Python logging to work with structlog
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(message)s",
    )

    # httpx logs every request at INFO as a full URL, query string included.
    # SerpAPI takes its credential as a query parameter, so running at INFO
    # wrote the API key into the log file in plaintext, once per search:
    #
    #   INFO:httpx:HTTP Request: GET https://serpapi.com/search?...&api_key=...
    #
    # Logs get pasted into issues and shipped to aggregators, so this is a
    # credential leak rather than an untidy line. Requests we care about are
    # logged by the callers with the parameters they chose to record, so
    # nothing is lost by silencing the library's own copy.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.typing.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


def log_event(
    logger: structlog.typing.BoundLogger,
    event: str,
    level: str = "info",
    **context: Any,
) -> None:
    """Log a structured event with context."""
    log_func = getattr(logger, level)
    log_func(event, **context)
