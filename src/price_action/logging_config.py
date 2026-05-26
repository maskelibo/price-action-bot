"""Merkezi loglama — loguru tabanlı, JSON çıktı opsiyonel.

Tüm modüller `from price_action.logging_config import logger` ile alır.

QUIET MODE: `PA_LOG_QUIET=1` env'i set edilirse stdout'a log basılmaz
(yalnızca dosyaya). Backtest çıktısını okumayı kolaylaştırmak için.

SEC58.H6 — Log rotation verification + disk monitoring:
  - rotation: 200 MB (15m high-volume TF)
  - retention: 14 days
  - compression: gz (disk efficiency)
  - disk monitor: warn at 80%, crit at 95% usage
"""
from __future__ import annotations

import json
import os
import shutil
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
    # FIX 2026-05-26 (L1): tüm log timestamps UTC. Önceden record["time"]
    # local timezone'du; futures_daemon UTC ile karışıyordu (post-mortem
    # zorlaşıyordu).
    from datetime import timezone as _tz
    ts_utc = record["time"].astimezone(_tz.utc) if record["time"].tzinfo else record["time"]
    payload = {
        "ts": ts_utc.isoformat(),
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


def _get_disk_usage(path: Path) -> tuple[float, float]:
    """Diski kullanılan % ve boş alan GB döner. (usage_pct, free_gb)"""
    try:
        stat = shutil.disk_usage(path)
        usage_pct = (stat.used / stat.total) * 100.0
        free_gb = stat.free / (1024 ** 3)
        return usage_pct, free_gb
    except Exception:
        return 0.0, 0.0  # fallback


def _check_disk_health(log_dir: Path) -> None:
    """Disk sağlığını kontrol et; warning/critical alarm yayınla.

    SEC58.H6 — Disk monitor:
      - 80-95% usage: WARN alarm
      - >= 95% usage: CRIT alarm
    """
    usage_pct, free_gb = _get_disk_usage(log_dir)

    if usage_pct >= 95.0:
        # CRITICAL — disk almost full
        _logger.critical(
            "DISK_FULL_CRIT",
            extra={
                "disk_usage_pct": round(usage_pct, 1),
                "free_gb": round(free_gb, 2),
                "log_dir": str(log_dir),
            },
        )
    elif usage_pct >= 80.0:
        # WARNING — disk getting full
        _logger.warning(
            "DISK_FULL_WARN",
            extra={
                "disk_usage_pct": round(usage_pct, 1),
                "free_gb": round(free_gb, 2),
                "log_dir": str(log_dir),
            },
        )


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

    # Dosya log — SEC58.H6 rotation verification
    log_file: Path = s.logs_dir / "app.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Disk health check
    _check_disk_health(log_file.parent)

    _logger.add(
        log_file,
        level=s.log_level,
        rotation="200 MB",  # SEC54 ME-EL-04: 15m TF 4x daha çok log üretir (50→200MB)
        retention="14 days",
        compression="gz",
        enqueue=True,
    )


configure()
logger = _logger
