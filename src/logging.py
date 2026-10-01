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
