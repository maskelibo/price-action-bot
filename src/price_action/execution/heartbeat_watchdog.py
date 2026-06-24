"""Lockless heartbeat watchdog using file mtime.

Design:
  - Writer: atomic touch() to heartbeat file every N seconds (no DB lock)
  - Reader: check file mtime delta; if > timeout → trigger emergency flatten
  - Fallback: keep DuckDB heartbeat for backward compatibility & audit trail
  - File location: data/dms_heartbeat_<service_name>.txt (per-service)

Atomicity: Python pathlib.Path.touch() is atomic on POSIX + Windows.
If tempfile write fails, old file untouched (fail-safe).

Timeout triggers:
  - file missing → timeout (first write hasn't happened yet, daemon starting)
  - file mtime > timeout → last touch was > timeout ago
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional


class HeartbeatWatchdog:
    """Lockless file-based heartbeat + mtime watchdog."""

    def __init__(
        self,
        service_name: str = "execution",
        heartbeat_file: Path | str | None = None,
    ) -> None:
        """
        Args:
            service_name: daemon service identifier (used for log filename)
            heartbeat_file: path to heartbeat file. If None, uses default location.
        """
        self.service_name = service_name
        if heartbeat_file:
            self._heartbeat_file = Path(heartbeat_file)
        else:
            root = Path(__file__).resolve().parents[3]  # G24 fix: Price Action kökü (eskiden parents[4]=projeler — proje dışı)
            self._heartbeat_file = root / "data" / f"dms_heartbeat_{service_name}.txt"

        # Ensure parent dir exists
        self._heartbeat_file.parent.mkdir(parents=True, exist_ok=True)

    def ping(self) -> bool:
        """
        Write heartbeat (atomic touch).

        Returns:
            True if write successful, False if error occurred.
        """
        try:
            # atomic touch() — updates mtime to current time
            self._heartbeat_file.touch()
            return True
        except Exception:
            return False

    def seconds_since_heartbeat(self) -> float:
        """
        Time elapsed since last heartbeat write.

        Returns:
            Seconds elapsed. Returns infinity if file doesn't exist.
        """
        if not self._heartbeat_file.exists():
            return float("inf")

        try:
            mtime = self._heartbeat_file.stat().st_mtime
            return time.time() - mtime
        except OSError:
            # File disappeared between exists() and stat()
            return float("inf")

    def is_stale(self, timeout_sec: float) -> bool:
        """
        Check if heartbeat is stale (dead man's switch triggered).

        Args:
            timeout_sec: timeout threshold in seconds

        Returns:
            True if elapsed > timeout, False otherwise.
        """
        elapsed = self.seconds_since_heartbeat()
        return elapsed > timeout_sec

    def reset_heartbeat_file(self) -> None:
        """Delete heartbeat file (for graceful shutdown/cleanup)."""
        try:
            if self._heartbeat_file.exists():
                self._heartbeat_file.unlink()
        except OSError:
            pass

    @property
    def heartbeat_file(self) -> Path:
        """Return heartbeat file path."""
        return self._heartbeat_file
