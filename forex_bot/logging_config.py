"""Logging with secret redaction + rotation.

Redacts: api_key, password, token, access_token, secret, client_secret.
Rotates: 200 MB / 14 day retention / gz compression.
"""
from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path
from typing import Optional

from .settings import LOGS_DIR

_REDACT_KEYS = re.compile(
    r"(api[_-]?key|password|token|access[_-]?token|secret|client[_-]?secret)\s*[=:]\s*([^\s,;}]+)",
    re.IGNORECASE,
)


def _redact(msg: str) -> str:
    return _REDACT_KEYS.sub(r"\1=***", str(msg))


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = super().format(record)
        return _redact(out)


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[Path] = None,
    max_bytes: int = 200 * 1024 * 1024,
    backup_count: int = 14,
) -> logging.Logger:
    """Initialize root logger with secret redaction + size rotation."""
    if log_file is None:
        log_file = LOGS_DIR / "forex_bot.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = "%(asctime)s %(levelname)s %(name)s | %(message)s"

    ch = logging.StreamHandler()
    ch.setFormatter(RedactingFormatter(fmt))
    root.addHandler(ch)

    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8",
    )
    fh.setFormatter(RedactingFormatter(fmt))
    root.addHandler(fh)

    return root
