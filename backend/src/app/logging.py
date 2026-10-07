"""Structured logging configuration using structlog."""

import logging
import os
from typing import Any

import structlog


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
    # Matched by prefix, not by exact name. Silencing "httpx" and "httpcore"
    # was not enough: pydantic-ai vendors its own copies registered as
    # "httpx2" and "httpcore2", which kept logging request URLs at INFO long
    # after this was believed fixed. A prefix sweep covers the next vendored
    # copy too, and these libraries have nothing to say at INFO that is worth
    # the risk of a credential in a query string.
    for name in list(logging.root.manager.loggerDict) + ["httpx", "httpcore"]:
        if name.startswith(("httpx", "httpcore")):
            logging.getLogger(name).setLevel(logging.WARNING)
    # Registered after this runs, so set unconditionally as well.
    for name in ("httpx", "httpx2", "httpcore", "httpcore2"):
        logging.getLogger(name).setLevel(logging.WARNING)

    # pydantic-ai prints a five-line ASCII banner on first use, into the same
    # log a scheduled run writes. It offers this exact opt-out.
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


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
