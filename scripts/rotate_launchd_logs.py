"""Launchd log rotation (M1 fix — 2026-05-26).

launchd stdout/stderr log'ları rotate edilmiyordu. Bu script:
- logs/launchd/*.log dosyalarını size threshold'a göre rotate eder
- Eski rotate'leri retention günü sonrası siler
- gzip ile sıkıştırır (disk %85+ tasarruf)

Cron: scheduler `_job_rotate_logs` saatlik çağırır.
"""
from __future__ import annotations

import gzip
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_LOG_DIR = Path("/Users/peyman/price-action-bot/logs/launchd")
_ROTATE_SIZE_MB = 50      # Bu boyutu geçenler rotate
_RETENTION_DAYS = 14      # 14 günden eski .gz dosyalar silinir
_MAX_TOTAL_MB = 1024      # Toplam logs/ > 1GB ise zorla rotate


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _rotate_one(log_path: Path) -> bool:
    """Tek dosyayı rotate et: .log → .log.YYYYMMDD-HHMMSS.gz."""
    try:
        size_mb = log_path.stat().st_size / 1024 / 1024
        if size_mb < _ROTATE_SIZE_MB:
            return False
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        archive = log_path.parent / f"{log_path.name}.{ts}.gz"
        with log_path.open("rb") as f_in, gzip.open(archive, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
        # Truncate original (process still has fd, must not delete)
        log_path.write_bytes(b"")
        _log(f"ROTATED: {log_path.name} ({size_mb:.1f}MB) → {archive.name}")
        return True
    except Exception as exc:
        _log(f"ROTATE_FAIL: {log_path.name}: {exc}")
        return False


def _cleanup_old() -> int:
    """Retention günü sonrası .gz dosyaları sil."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
    deleted = 0
    for archive in _LOG_DIR.glob("*.log.*.gz"):
        try:
            mtime = datetime.fromtimestamp(archive.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                archive.unlink()
                _log(f"DELETED_OLD: {archive.name} (age {(datetime.now(timezone.utc) - mtime).days}d)")
                deleted += 1
        except Exception as exc:
            _log(f"CLEANUP_FAIL: {archive.name}: {exc}")
    return deleted


def main() -> int:
    if not _LOG_DIR.exists():
        _log(f"LOG_DIR_MISSING: {_LOG_DIR}")
        return 0

    # 1) Tekil rotate (size threshold)
    rotated = 0
    for log_path in _LOG_DIR.glob("*.log"):
        if _rotate_one(log_path):
            rotated += 1

    # 2) Eski .gz'leri sil
    deleted = _cleanup_old()

    # 3) Toplam boyut kontrolü (acil rotate)
    total_mb = sum(
        f.stat().st_size for f in _LOG_DIR.rglob("*") if f.is_file()
    ) / 1024 / 1024
    if total_mb > _MAX_TOTAL_MB:
        _log(f"TOTAL_EXCEED: {total_mb:.0f}MB > {_MAX_TOTAL_MB}MB — emergency rotate all")
        for log_path in _LOG_DIR.glob("*.log"):
            # Force rotate even if small
            try:
                ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                archive = log_path.parent / f"{log_path.name}.{ts}.emergency.gz"
                with log_path.open("rb") as f_in, gzip.open(archive, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
                log_path.write_bytes(b"")
                _log(f"EMERGENCY_ROTATED: {log_path.name}")
            except Exception as exc:
                _log(f"EMERGENCY_FAIL: {log_path.name}: {exc}")

    _log(f"DONE: rotated={rotated}, deleted={deleted}, total_mb={total_mb:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
