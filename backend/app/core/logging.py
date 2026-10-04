"""Structured logging setup for FinCortext.

Provides a consistent, readable console format. Secrets must never be
logged; provider failures are logged with context but never crash unrelated
modules.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False

# Keys whose values must never appear in log output.
_REDACTED_KEYS = {"api_key", "apikey", "key", "token", "secret", "password", "authorization"}


class SecretFilter(logging.Filter):
    """Best-effort redaction of obvious secret patterns in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            lowered = message.lower()
            for key in _REDACTED_KEYS:
                if key in lowered and "=" in message:
                    # Redact `key=value` occurrences.
                    import re

                    pattern = re.compile(
                        rf"({key}\s*[=:]\s*)(\S+)", re.IGNORECASE
                    )
                    message = pattern.sub(r"\1***", message)
            if message != record.getMessage():
                record.msg = message
                record.args = None
        except Exception:  # pragma: no cover - redaction must never fail logging
            pass
        return True


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging once. Safe to call multiple times."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler.addFilter(SecretFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    try:
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
    except Exception:
        root.setLevel(logging.INFO)

    # Reduce noise from chatty third-party loggers.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("peewee").setLevel(logging.ERROR)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger."""
    if not name.startswith("fincortext"):
        name = f"fincortext.{name}"
    return logging.getLogger(name)


__all__ = ["configure_logging", "get_logger"]