"""PHOENIX-SCALP v1.0 Orchestrator.

Watch ingest logs; when 15m 5y backfill completes, trigger full 13-pencere
walk-forward backtest. When 5m ingest completes (10 sym × 5y), trigger
5m preview run.

Run in background:
  python scripts/sec31_scalp_orchestrator.py > logs/scalp_orchestrator.log 2>&1 &

Heartbeat every 60s. Stops automatically once both backtests have launched.
"""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LOG_5M = ROOT / "logs" / "sec31_ingest_5m.log"
LOG_15M = ROOT / "logs" / "sec31_ingest_15m_backfill.log"

SENTINEL_5M_DONE = "DONE  total_rows="          # sec31_ingest_5m.py end-of-run
SENTINEL_15M_DONE = "DONE  total_new_rows="     # sec31_ingest_15m_backfill.py end-of-run

OUT_BACKTEST_15M = ROOT / "logs" / "sec31_backtest_15m_full5y.log"
OUT_PREVIEW_5M = ROOT / "logs" / "sec32_preview_5m.log"

POLL_S = 60
STALE_LIMIT_S = 600  # 10 dk hareket yoksa "dead/hung" varsay

launched_15m = False
launched_5m = False


def _has_sentinel(log_path: Path, sentinel: str) -> bool:
    if not log_path.exists():
        return False
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if sentinel in line:
                    return True
    except OSError:
        return False
    return False


def _log_stale(log_path: Path) -> bool:
    """True if log exists and hasn't been written to in STALE_LIMIT_S."""
    if not log_path.exists():
        return False
    age = time.time() - log_path.stat().st_mtime
    return age > STALE_LIMIT_S


def _print(msg: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    print(f"[{ts}] {msg}", flush=True)


def _launch(script: str, out_log: Path) -> subprocess.Popen[bytes]:
    cmd = [sys.executable, str(ROOT / "scripts" / script)]
    fh = out_log.open("wb")
    proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=str(ROOT))
    return proc


def main() -> int:
    global launched_15m, launched_5m
    _print("orchestrator.start")
    _print(f"  watch 5m log: {LOG_5M}")
    _print(f"  watch 15m log: {LOG_15M}")
    iteration = 0
    while True:
        iteration += 1

        # 5m preview trigger
        if not launched_5m and _has_sentinel(LOG_5M, SENTINEL_5M_DONE):
            _print("5m_ingest.complete -> launch 5m preview")
            try:
                proc = _launch("sec32_phoenix_scalp_5m_rolling.py", OUT_PREVIEW_5M)
                _print(f"  5m preview pid={proc.pid} -> {OUT_PREVIEW_5M}")
                launched_5m = True
            except Exception as e:
                _print(f"  5m launch FAILED: {e}")

        # 15m full backtest trigger
        if not launched_15m and _has_sentinel(LOG_15M, SENTINEL_15M_DONE):
            _print("15m_backfill.complete -> launch 15m full 5y backtest")
            try:
                proc = _launch("sec31_phoenix_scalp_15m_rolling.py", OUT_BACKTEST_15M)
                _print(f"  15m backtest pid={proc.pid} -> {OUT_BACKTEST_15M}")
                launched_15m = True
            except Exception as e:
                _print(f"  15m launch FAILED: {e}")

        if launched_15m and launched_5m:
            _print("orchestrator.done both_launched")
            return 0

        # Stale checks (heartbeat warning)
        if iteration % 10 == 0:
            if not launched_5m and _log_stale(LOG_5M):
                _print(f"WARN: 5m log stale > {STALE_LIMIT_S}s (process may be dead)")
            if not launched_15m and _log_stale(LOG_15M):
                _print(f"WARN: 15m log stale > {STALE_LIMIT_S}s (process may be dead)")

        if iteration % 5 == 0:
            _print(f"heartbeat iter={iteration} launched_5m={launched_5m} launched_15m={launched_15m}")

        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
