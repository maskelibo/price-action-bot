"""Merkezi loglama — loguru tabanlı, JSON çıktı opsiyonel.

Tüm modüller `from price_action.logging_config import logger` ile alır.

QUIET MODE: `PA_LOG_QUIET=1` env'i set edilirse stdout'a log basılmaz
(yalnızca dosyaya). Backtest çıktısını okumayı kolaylaştırmak için.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from loguru import logger as _logger

from .settings import get_settings

_REDACT_KEYS = {
    "api_key", "api_secret", "password", "token", "secret",
    "anthropic_api_key", "telegram_bot_token", "youtube_api_key",
}


def _redact(payload: dict) -> dict:
    """Hassas alanları maskele."""
    out = {}
    for k, v in payload.items():
        if any(s in k.lower() for s in _REDACT_KEYS):
            out[k] = "***"
        elif isinstance(v, dict):
            out[k] = _redact(v)
        else:
            out[k] = v
    return out


def _json_sink(message) -> None:
    record = message.record
    payload = {
        "ts": record["time"].isoformat(),
        "level": record["level"].name,
        "logger": record["name"],
        "msg": record["message"],
        "module": record["module"],
        "function": record["function"],
        "line": record["line"],
    }
    if record["extra"]:
        payload["extra"] = _redact(dict(record["extra"]))
    if record["exception"] is not None:
        payload["exception"] = str(record["exception"])
    sys.stdout.write(json.dumps(payload, default=str, ensure_ascii=False) + "\n")


def configure() -> None:
    """Settings'e göre loguru'yu yapılandır."""
    s = get_settings()
    _logger.remove()
    # PA_LOG_QUIET=1 -> stdout sink atla, sadece dosyaya log.
    quiet = os.getenv("PA_LOG_QUIET", "").strip() in ("1", "true", "yes", "on")
    if not quiet:
        if s.log_format == "json":
            _logger.add(_json_sink, level=s.log_level, enqueue=True)
        else:
            _logger.add(
                sys.stderr,
                level=s.log_level,
                format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                       "<level>{level: <8}</level> | "
                       "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                       "{message}",
                enqueue=True,
            )

    # Dosya log
    log_file: Path = s.logs_dir / "app.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    _logger.add(
        log_file,
        level=s.log_level,
        rotation="50 MB",
        retention="14 days",
        compression="gz",
        enqueue=True,
    )


configure()
logger = _logger
