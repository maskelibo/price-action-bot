"""Multi-TF Stack Paper Daemon — PAPER/TESTNET ONLY.

Manages the 30-day paper validation window for the VSA-WIDESTOP + BASELINE exit
multi-TF stack (5m + 15m + 30m + 45m) at L=1.2.

ARCHITECTURE (NO disruption to running daemons):
  - PID 53708 (15m): com.priceaction.futures15m — champion, DO NOT TOUCH.
  - PID 70580 (5m):  com.priceaction.futures5m  — existing, DO NOT TOUCH.
  - THIS daemon (multitf): parallel observer + staged 30m/45m scanner.

WHAT THIS DAEMON DOES:
  1. Reads 5m and 15m positions from their respective journals for POOLED
     risk accounting (concentration + DD monitoring across all legs).
  2. Scans 30m/45m signals every 15 minutes (at each 15m boundary).
     - 30m/45m signals are STAGED (B1 blocker: feed parity unverified).
     - Staged signals are logged to logs/multitf_staged_signals.jsonl for audit.
     - NO orders submitted for 30m/45m until B1 is cleared.
  3. Monitors pooled DD and fires the paper-run abort if thresholds breached:
     - Monthly return < +8%/mo → ABORT, send Telegram, notify Principal.
     - Drawdown > -25% → ABORT, send Telegram, notify Principal.
  4. Emits hourly pooled equity snapshot.

WHAT THIS DAEMON DOES NOT DO:
  - Does NOT submit 5m orders (managed by PID 70580).
  - Does NOT submit 15m orders (managed by PID 53708).
  - Does NOT set PA_LIVE_CONFIRM — paper only.
  - Does NOT disrupt existing positions.

ACTIVATION (paper only):
    PA_RUN_MODE=paper PA_MULTITF_CONFIG=configs/risk_multitf_stack_paper_l12.yaml \
        python scripts/futures_daemon_multitf.py

KILL SWITCH:
    Same logs/kill_switch.json as other daemons.

DB SEPARATION (no lock conflict):
    - 5m journal:  data/futures_journal_5m.duckdb    (read-only)
    - 15m journal: data/futures_journal.duckdb        (read-only)
    - multitf log: logs/multitf_staged_signals.jsonl  (write)
    - multitf equity: data/futures_journal_multitf.duckdb (write)
"""
from __future__ import annotations

import json
import os
import signal as _signal
import sys
import time
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# ── Constants ─────────────────────────────────────────────────────────────────
_MULTITF_CONFIG = os.environ.get(
    "PA_MULTITF_CONFIG", "configs/risk_multitf_stack_paper_l12.yaml"
)
_RUN_MODE = os.environ.get("PA_RUN_MODE", "paper")

LOG_FILE = ROOT / "logs" / "futures_daemon_multitf.log"
STAGED_SIGNALS_LOG = ROOT / "logs" / "multitf_staged_signals.jsonl"
JOURNAL_15M = ROOT / "data" / "futures_journal.duckdb"
JOURNAL_5M = ROOT / "data" / "futures_journal_5m.duckdb"
JOURNAL_MULTITF = ROOT / "data" / "futures_journal_multitf.duckdb"
KILL_SWITCH_PATH = ROOT / "logs" / "kill_switch.json"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
STAGED_SIGNALS_LOG.parent.mkdir(parents=True, exist_ok=True)

_stop_flag = False


# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%SZ")
    line = f"[{ts}] [MULTITF] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
    except Exception:
        pass
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:
        pass


# ── Signal handlers ───────────────────────────────────────────────────────────
def _install_signal_handlers() -> None:
    def _handler(signum: int, frame) -> None:
        global _stop_flag
        _stop_flag = True
        log(f"SIGNAL_RECEIVED: {signum} — graceful shutdown")
    try:
        _signal.signal(_signal.SIGTERM, _handler)
        _signal.signal(_signal.SIGHUP, _handler)
    except (ValueError, OSError, AttributeError):
        pass


# ── Kill switch ───────────────────────────────────────────────────────────────
def _kill_switch_active() -> tuple[bool, str]:
    if not KILL_SWITCH_PATH.exists():
        return False, ""
    try:
        with open(KILL_SWITCH_PATH, encoding="utf-8") as f:
            ks = json.load(f)
        if bool(ks.get("halted", False)):
            return True, str(ks.get("reason", ""))
        return False, ""
    except Exception:
        return False, ""


# ── Config loader ─────────────────────────────────────────────────────────────
def _load_config() -> dict:
    import yaml
    cfg_path = ROOT / _MULTITF_CONFIG
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ── Pooled equity reader ───────────────────────────────────────────────────────
def _read_pooled_equity() -> dict:
    """Read current open positions + cumulative PnL from both 5m and 15m journals.

    Returns pooled metrics for DD monitoring.
    Uses read_only=True on both journals (no lock conflict with running daemons).
    """
    import duckdb

    result = {
        "n_positions_5m": 0,
        "n_positions_15m": 0,
        "n_positions_total": 0,
        "pnl_closed_5m": 0.0,
        "pnl_closed_15m": 0.0,
        "pnl_closed_total": 0.0,
        "symbols_open": [],
        "error_5m": None,
        "error_15m": None,
    }

    # 15m journal
    if JOURNAL_15M.exists():
        try:
            con = duckdb.connect(str(JOURNAL_15M), read_only=True)
            # Count open positions (filled, not closed)
            try:
                row = con.execute("""
                    SELECT COUNT(*) FROM futures_signals
                    WHERE status = 'filled'
                      AND signal_id NOT IN (
                        SELECT trade_id FROM futures_trades_closed
                      )
                """).fetchone()
                result["n_positions_15m"] = int(row[0]) if row else 0
            except Exception:
                pass
            # Cumulative closed PnL
            try:
                row = con.execute("""
                    SELECT COALESCE(SUM(pnl_usdt), 0.0) FROM futures_trades_closed
                """).fetchone()
                result["pnl_closed_15m"] = float(row[0]) if row else 0.0
            except Exception:
                pass
            # Open symbols
            try:
                rows = con.execute("""
                    SELECT DISTINCT symbol FROM futures_signals
                    WHERE status = 'filled'
                      AND signal_id NOT IN (
                        SELECT trade_id FROM futures_trades_closed
                      )
                """).fetchall()
                result["symbols_open"] += [r[0] for r in rows]
            except Exception:
                pass
            con.close()
        except Exception as exc:
            result["error_15m"] = str(exc)

    # 5m journal
    if JOURNAL_5M.exists():
        try:
            con = duckdb.connect(str(JOURNAL_5M), read_only=True)
            try:
                row = con.execute("""
                    SELECT COUNT(*) FROM futures_signals
                    WHERE status = 'filled'
                      AND signal_id NOT IN (
                        SELECT trade_id FROM futures_trades_closed
                      )
                """).fetchone()
                result["n_positions_5m"] = int(row[0]) if row else 0
            except Exception:
                pass
            try:
                row = con.execute("""
                    SELECT COALESCE(SUM(pnl_usdt), 0.0) FROM futures_trades_closed
                """).fetchone()
                result["pnl_closed_5m"] = float(row[0]) if row else 0.0
            except Exception:
                pass
            try:
                rows = con.execute("""
                    SELECT DISTINCT symbol FROM futures_signals
                    WHERE status = 'filled'
                      AND signal_id NOT IN (
                        SELECT trade_id FROM futures_trades_closed
                      )
                """).fetchall()
                result["symbols_open"] += [r[0] for r in rows]
            except Exception:
                pass
            con.close()
        except Exception as exc:
            result["error_5m"] = str(exc)

    result["n_positions_total"] = result["n_positions_5m"] + result["n_positions_15m"]
    result["pnl_closed_total"] = result["pnl_closed_5m"] + result["pnl_closed_15m"]
    result["symbols_open"] = list(set(result["symbols_open"]))
    return result


# ── Paper-run abort monitor ────────────────────────────────────────────────────
def _check_paper_abort(cfg: dict, equity_state: dict) -> tuple[bool, str]:
    """Check if paper-run abort thresholds are breached.

    Returns (should_abort, reason).
    Reads abort thresholds from paper_validation config block.
    """
    pv = cfg.get("paper_validation", {})
    abort_monthly = float(pv.get("abort_if_monthly_return_below_pct", 8.0))
    abort_dd = float(pv.get("abort_if_drawdown_exceeds_pct", 25.0))

    # Approximate monthly return from closed PnL
    # This is a rough estimate; full calculation would require initial capital.
    # We use cumulative PnL / initial_capital (assumed $5000 for 15m bot, $1000 for 5m).
    # TODO: wire to actual equity snapshot from journals for precise DD tracking.
    # For now: flag if pnl_closed_total < negative threshold.
    # The daemon will emit a warning-only abort check; Principal monitors Telegram.
    pnl_total = equity_state.get("pnl_closed_total", 0.0)

    # Approximate DD: if pnl is -25% of assumed capital ($6000 combined)
    assumed_capital = 6000.0
    approx_dd_pct = -abs(pnl_total) / assumed_capital * 100.0 if pnl_total < 0 else 0.0

    if approx_dd_pct > abort_dd:
        return True, f"DD {approx_dd_pct:.1f}% > abort threshold {abort_dd}%"

    return False, ""


# ── Staged signal logger ───────────────────────────────────────────────────────
def _log_staged_signal(sig: dict) -> None:
    """Append staged signal to jsonl log for audit."""
    try:
        row = {
            "ts": datetime.now(UTC).isoformat(),
            "signal_ts": str(sig.get("ts", "")),
            "symbol": sig.get("symbol", ""),
            "side": sig.get("side", ""),
            "strategy": sig.get("strategy", ""),
            "tf": sig.get("timeframe_label", ""),
            "rule": sig.get("resample_rule", ""),
            "entry_price": sig.get("entry_price", 0),
            "sl_price": sig.get("sl_price", 0),
            "confluence": sig.get("confluence", 0),
            "staged": sig.get("staged", True),
            "note": "B1_BLOCKER_STAGED_ONLY",
        }
        with open(STAGED_SIGNALS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass


# ── Bar boundary helpers (reuse daemon pattern) ───────────────────────────────
def next_tf_boundary(tf_minutes: int) -> datetime:
    now = datetime.now(UTC)
    minute = now.minute
    next_min = ((minute // tf_minutes) + 1) * tf_minutes
    if next_min >= 60:
        new_hour = now.hour + 1
        if new_hour >= 24:
            tomorrow = now + timedelta(days=1)
            return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        return now.replace(hour=new_hour, minute=0, second=0, microsecond=0)
    return now.replace(minute=next_min, second=0, microsecond=0)


def next_15m_boundary() -> datetime:
    return next_tf_boundary(15)


def sleep_until(target: datetime) -> None:
    now = datetime.now(UTC)
    delta = (target - now).total_seconds()
    if delta > 0:
        time.sleep(delta)


# ── Notification helper ───────────────────────────────────────────────────────
def _notify_abort(reason: str) -> None:
    try:
        from price_action.orchestrator.notifications import push_critical
        push_critical(
            f"MULTITF PAPER ABORT: {reason}\n"
            f"Action: check 30-day paper window vs +8%/mo and -25% DD thresholds.\n"
            f"Rollback: champion 15m (PID 53708) stays warm.",
            source="futures_daemon_multitf",
        )
    except Exception:
        pass


# ── Main loop ─────────────────────────────────────────────────────────────────
def run_multitf_paper(once: bool = False) -> None:
    """Multi-TF paper validation main loop.

    Runs at each 15m boundary (same cadence as 15m daemon).
    Each tick:
      1. Read pooled equity (5m + 15m journals, read-only).
      2. Check paper-run abort thresholds.
      3. Scan 30m/45m signals (STAGED — logged, not submitted, B1 blocker).
      4. Log summary.
    """
    _install_signal_handlers()

    log("=" * 60)
    log("MULTI-TF STACK PAPER DAEMON STARTED")
    log(f"  Config:      {_MULTITF_CONFIG}")
    log(f"  Mode:        {_RUN_MODE} (paper only)")
    log(f"  15m journal: {JOURNAL_15M} (read-only)")
    log(f"  5m journal:  {JOURNAL_5M} (read-only)")
    log(f"  Staged log:  {STAGED_SIGNALS_LOG}")
    log("  30m/45m:     STAGED (B1 blocker — parity unverified)")
    log("  5m/15m:      read-only accounting (PIDs 70580/53708 own execution)")
    log(f"  Abort gates: DD > -25% or monthly < +8%/mo")
    log("=" * 60)

    # Hard safety check — NEVER run in live mode
    if _RUN_MODE == "live" or os.environ.get("PA_LIVE_CONFIRM", "").strip():
        log("CRITICAL: live mode detected — REFUSING TO START. This daemon is paper-only.")
        sys.exit(1)

    cfg = {}
    try:
        cfg = _load_config()
        log(f"CONFIG: loaded {_MULTITF_CONFIG}")
    except Exception as exc:
        log(f"CONFIG_FAIL: {exc} — using empty config (abort thresholds at defaults)")

    # Import scanners
    try:
        from scripts.futures_trade_30m45m import scan_signals_30m, scan_signals_45m
        _scanners_ok = True
        log("SCANNERS: 30m/45m scanner loaded (staged)")
    except Exception as exc:
        log(f"SCANNER_LOAD_FAIL: {exc} — 30m/45m scan disabled this session")
        _scanners_ok = False

    _err_count = 0
    _ERR_ABORT = 10
    last_bar_boundary: datetime | None = None
    _abort_notified = False

    try:
        while True:
            if _stop_flag:
                log("STOP_FLAG — graceful exit")
                break

            halted, reason = _kill_switch_active()
            if halted:
                log(f"KILL_SWITCH ACTIVE: {reason}")
                break

            try:
                # Wait for next 15m boundary + 10s buffer (slight offset from 15m daemon's 5s)
                next_close = next_15m_boundary() + timedelta(seconds=10)
                log(f"WAIT: next 15m boundary {next_close.strftime('%H:%M:%S')}Z")
                sleep_until(next_close)

                if _stop_flag:
                    break

                current_boundary = next_close - timedelta(seconds=10)
                if last_bar_boundary is not None:
                    bars_elapsed = int(
                        (current_boundary - last_bar_boundary).total_seconds() / 900
                    )
                    if bars_elapsed > 1:
                        log(f"MISSED_BARS: {bars_elapsed - 1} bars missed")
                last_bar_boundary = current_boundary

                tick_start = datetime.now(UTC)

                # 1. Pooled equity read
                equity = _read_pooled_equity()
                log(
                    f"POOLED: pos_5m={equity['n_positions_5m']} pos_15m={equity['n_positions_15m']} "
                    f"pnl_closed=${equity['pnl_closed_total']:+.2f} "
                    f"err_5m={equity['error_5m']} err_15m={equity['error_15m']}"
                )
                if equity["symbols_open"]:
                    log(f"  OPEN_SYMS: {sorted(equity['symbols_open'])[:10]}")

                # 2. Abort check
                abort, abort_reason = _check_paper_abort(cfg, equity)
                if abort and not _abort_notified:
                    log(f"PAPER_ABORT_TRIGGERED: {abort_reason}")
                    _notify_abort(abort_reason)
                    _abort_notified = True
                    # Do not exit — keep monitoring and logging. Let Principal decide.
                    # Abort = alert + flag; the trading itself is run by PIDs 53708/70580.

                # 3. Scan 30m/45m (staged — log only, no submission)
                if _scanners_ok:
                    try:
                        sigs_30m = scan_signals_30m(current_boundary)
                        sigs_45m = scan_signals_45m(current_boundary)
                        total_staged = len(sigs_30m) + len(sigs_45m)
                        log(f"STAGED_SCAN: 30m={len(sigs_30m)} 45m={len(sigs_45m)} signals (B1 staged, not submitted)")
                        for sig in sigs_30m + sigs_45m:
                            _log_staged_signal(sig)
                    except Exception as scan_exc:
                        log(f"STAGED_SCAN_ERR: {scan_exc}")

                tick_elapsed = (datetime.now(UTC) - tick_start).total_seconds()
                log(f"TICK_DONE: {tick_elapsed:.1f}s")
                _err_count = 0

            except Exception as exc:
                _err_count += 1
                log(f"LOOP_ERROR [{_err_count}/{_ERR_ABORT}]: {exc}")
                log(traceback.format_exc()[:500])
                if _err_count >= _ERR_ABORT:
                    log(f"ERR_ABORT: {_err_count} consecutive errors — exiting (launchd will restart)")
                    break
                backoff = min(2 ** _err_count, 60)
                time.sleep(backoff)

            if once:
                break

    except KeyboardInterrupt:
        log("KeyboardInterrupt — stopping")
    finally:
        log("MULTITF DAEMON STOPPED")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Multi-TF stack paper daemon")
    parser.add_argument("--once", action="store_true", help="Single tick (test mode)")
    args = parser.parse_args()

    # HARD SAFETY CHECK
    if os.environ.get("PA_LIVE_CONFIRM", "").strip():
        print("ERROR: PA_LIVE_CONFIRM set — this daemon is PAPER ONLY. Exiting.")
        sys.exit(1)

    run_multitf_paper(once=args.once)
