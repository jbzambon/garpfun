"""Structured logging setup.

Every module should call ``get_logger(__name__)`` rather than using the
stdlib ``logging`` module directly. Ingest modules (Phase 1+) must call
``log_fetch`` on every network request so raw downloads are auditable:
source, URL, retrieval timestamp, and a hash of the payload, per SPEC.md
principle #5 (deterministic and reproducible).
"""

from __future__ import annotations

import hashlib
import logging
import sys
from datetime import UTC, datetime
from typing import Any, cast

import structlog

_CONFIGURED = False


def configure_logging(*, level: int = logging.INFO, json: bool = False) -> None:
    """Configure structlog + stdlib logging. Idempotent.

    Parameters
    ----------
    level:
        Root log level.
    json:
        Emit newline-delimited JSON instead of a human-readable console
        renderer. Use ``json=True`` for pipeline/CI runs whose logs get
        parsed or archived; keep it ``False`` for interactive use.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a configured structlog logger, configuring on first use."""
    if not _CONFIGURED:
        configure_logging()
    # structlog.get_logger()'s return type is Any by design -- the actual
    # wrapper class is whatever was passed to configure() above.
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(name))


def hash_payload(payload: bytes) -> str:
    """Content hash used for content-addressed raw storage and log records."""
    return hashlib.sha256(payload).hexdigest()


def log_fetch(
    logger: Any,
    *,
    source: str,
    url: str,
    payload: bytes,
    retrieved_at: datetime | None = None,
    **extra: Any,
) -> str:
    """Log a data fetch with the fields principle #5 requires, and return
    the payload hash so callers can use it as a content-addressed filename.

    Parameters
    ----------
    logger:
        A structlog logger, typically from ``get_logger(__name__)``.
    source:
        Short identifier for the data source, e.g. ``"sec_edgar"``.
    url:
        The exact URL fetched.
    payload:
        The raw response bytes, hashed for the log record and for
        content-addressed storage under ``data/raw/``.
    retrieved_at:
        UTC timestamp of retrieval. Defaults to now.
    extra:
        Any additional fields to attach (e.g. ``status_code``, ``cik``).
    """
    retrieved_at = retrieved_at or datetime.now(UTC)
    digest = hash_payload(payload)
    logger.info(
        "data_fetch",
        source=source,
        url=url,
        retrieved_at=retrieved_at.isoformat(),
        payload_sha256=digest,
        payload_bytes=len(payload),
        **extra,
    )
    return digest
