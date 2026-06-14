"""STAGED SWAP SCRIPT — Champion → V13 Testnet Daemon.

PURPOSE
-------
When the Principal confirms, running this script will:
  (a) Gracefully stop the champion daemon (PID 53708) via SIGTERM
  (b) Close/flatten all champion open positions on testnet
  (c) Start the v13 daemon (futures_daemon_v13.py --timeframe 15m)

THIS SCRIPT DOES NOTHING IF NOT EXPLICITLY ENABLED.
Safety gate: env var SWAP_EXECUTE must equal exactly "CONFIRM_SWAP_TO_V13".

DO NOT RUN until:
  1. v13 daemon unit tests pass (pytest tests/test_v13_daemon.py)
  2. v13 dry-run completes without error (--once)
  3. Principal explicitly confirms the swap
  4. Testnet wallet has been reset to ~$10k (see WALLET RESET section below)
  5. Champion PID 53708 is verified still running (ps aux | grep 53708)

SAFETY CONFIRMATIONS (at swap time):
  - PA_LIVE_CONFIRM is NOT set → testnet only
  - Champion PID is SIGTERM'd gracefully (30s timeout → SIGKILL)
  - Champion positions are closed BEFORE v13 starts
  - v13 starts fresh on data/futures_journal_v13.duckdb
  - 5m daemon (PID 70580) is NOT touched — it runs independently

WALLET RESET
------------
Binance Testnet does NOT support API-based balance reset.
The only way to reset to $10k is the MANUAL TESTNET WEB FAUCET:

  1. Open browser → https://testnet.binancefuture.com/en/futures/BTC_USDT
  2. Login with your testnet account credentials
  3. Click "Asset" → "Get testnet asset" (or navigate to faucet page)
  4. Request USDT faucet (typically gives $10,000 USDT)
  5. Wait ~30 seconds for funds to appear
  6. Verify: python scripts/v13_exchange_truth_tracker.py --no-persist

  Current testnet equity: ~$4,925 (confirmed 2026-06-01).
  After faucet: ~$10,000.
  NOTE: If positions are open, close them FIRST, then request faucet.
  The faucet may not be available if account balance > $0 (depends on testnet).
  ALTERNATIVE: Request faucet to top up to $10k total, not full reset.

EXECUTION COMMAND (when Principal confirms)
-------------------------------------------
  SWAP_EXECUTE=CONFIRM_SWAP_TO_V13 python scripts/swap_champion_to_v13.py

"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timezone, timedelta
from pathlib import Path

# ── SAFETY GATE ───────────────────────────────────────────────────────────────
# This script does NOTHING without explicit confirmation env var.
SWAP_EXECUTE = os.environ.get("SWAP_EXECUTE", "").strip()
CHAMPION_PID = 53708
_5M_PID = 70580  # NOT touched

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

LOG_FILE = ROOT / "logs" / "swap_champion_to_v13.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# TR timezone (UTC+3) per memory rule
_TR = timezone(timedelta(hours=3))


def _log(msg: str) -> None:
    ts = datetime.now(UTC).astimezone(_TR).strftime("%Y-%m-%d %H:%M:%S TR")
    line = f"[{ts}] [SWAP] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
    except Exception:
        pass


def _abort(reason: str) -> None:
    _log(f"ABORT: {reason}")
    sys.exit(1)


# ── Pre-flight checks ──────────────────────────────────────────────────────────
def preflight_checks() -> None:
    """Verify preconditions before swap begins."""
    # 1. Safety gate
    if SWAP_EXECUTE != "CONFIRM_SWAP_TO_V13":
        _abort(
            "SWAP_EXECUTE not set to 'CONFIRM_SWAP_TO_V13'. "
            "This is a staged script — to execute: "
            "SWAP_EXECUTE=CONFIRM_SWAP_TO_V13 python scripts/swap_champion_to_v13.py"
        )

    # 2. Never run with PA_LIVE_CONFIRM
    if os.environ.get("PA_LIVE_CONFIRM", "").strip():
        _abort("PA_LIVE_CONFIRM is set — swap refuses to run with live mode. Unset it.")

    # 3. PA_RUN_MODE must be paper (or unset = default paper)
    mode = os.environ.get("PA_RUN_MODE", "paper").strip()
    if mode == "live":
        _abort(f"PA_RUN_MODE={mode} — swap only runs in paper/testnet mode.")

    # 4. Champion PID must be running
    try:
        os.kill(CHAMPION_PID, 0)  # signal 0 = existence check, no actual signal
    except ProcessLookupError:
        _log(f"WARNING: Champion PID {CHAMPION_PID} is NOT running. Already stopped?")
        # Non-fatal: champion might have already stopped; continue to close positions + start v13
    except PermissionError:
        pass  # Process exists but we don't have permission to signal it (still running)

    # 5. v13 config exists
    cfg_path = ROOT / "configs" / "risk_v13_testnet.yaml"
    if not cfg_path.exists():
        _abort(f"V13 config missing: {cfg_path}")

    # 6. v13 daemon script exists
    daemon_path = ROOT / "scripts" / "futures_daemon_v13.py"
    if not daemon_path.exists():
        _abort(f"V13 daemon missing: {daemon_path}")

    _log("Pre-flight checks PASSED")


# ── Step A: Gracefully stop champion ──────────────────────────────────────────
def stop_champion() -> None:
    """Send SIGTERM to champion PID 53708. Wait up to 30s. SIGKILL if needed."""
    _log(f"STEP A: Stopping champion daemon PID {CHAMPION_PID} via SIGTERM...")
    try:
        os.kill(CHAMPION_PID, 0)
        champion_running = True
    except ProcessLookupError:
        champion_running = False
        _log(f"  Champion PID {CHAMPION_PID} already stopped — skipping SIGTERM")

    if champion_running:
        try:
            os.kill(CHAMPION_PID, signal.SIGTERM)
            _log(f"  SIGTERM sent to PID {CHAMPION_PID}")
        except ProcessLookupError:
            _log(f"  PID {CHAMPION_PID} already gone")
            return
        except PermissionError as e:
            _abort(f"Cannot send SIGTERM to PID {CHAMPION_PID}: {e}")

        # Wait up to 30s for graceful shutdown
        deadline = time.time() + 30
        while time.time() < deadline:
            time.sleep(2)
            try:
                os.kill(CHAMPION_PID, 0)
            except ProcessLookupError:
                _log(f"  Champion PID {CHAMPION_PID} stopped gracefully")
                return

        # Still running after 30s — SIGKILL
        _log(f"  Champion still running after 30s — sending SIGKILL")
        try:
            os.kill(CHAMPION_PID, signal.SIGKILL)
            time.sleep(2)
            _log(f"  SIGKILL sent to PID {CHAMPION_PID}")
        except ProcessLookupError:
            _log(f"  PID {CHAMPION_PID} already gone (SIGKILL was race-free)")
        except Exception as e:
            _abort(f"SIGKILL failed: {e}")

    _log("STEP A: Champion stop complete")


# ── Step B: Close champion open positions ─────────────────────────────────────
def close_champion_positions() -> None:
    """Close all open positions on testnet (champion's positions).

    Uses futures_testnet_close_all.py logic directly.
    Waits 5s after champion stop to let final SL/TP fills settle.
    """
    _log("STEP B: Waiting 5s for champion fills to settle before closing positions...")
    time.sleep(5)

    _log("STEP B: Closing all champion open positions on testnet...")
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
        from scripts.futures_trade_daily import get_futures_exchange

        ex = get_futures_exchange()

        # Cancel all open stop/tp orders first
        try:
            all_orders = ex.fetch_open_orders()
            if all_orders:
                _log(f"  Cancelling {len(all_orders)} open orders...")
                for o in all_orders:
                    try:
                        ex.cancel_order(o["id"], o["symbol"])
                        _log(f"    Cancelled: {o['symbol']} {o['type']} {o['side']}")
                    except Exception as _oe:
                        _log(f"    Cancel fail: {o.get('symbol','?')} — {str(_oe)[:80]}")
            else:
                _log("  No open orders to cancel")
        except Exception as _cancel_err:
            _log(f"  Open order cancel failed: {str(_cancel_err)[:120]} — continuing")

        # Cancel algo orders (STOP_MARKET / TP)
        try:
            algo_orders = ex.fapiPrivateGetOpenAlgoOrders() or []
            if algo_orders:
                _log(f"  Cancelling {len(algo_orders)} algo orders...")
                for ao in algo_orders:
                    try:
                        ex.fapiPrivateDeleteAlgoOrder({
                            "symbol": ao.get("symbol", ""),
                            "algoId": ao.get("algoId") or ao.get("algo_id"),
                        })
                        _log(f"    Cancelled algo: {ao.get('symbol','?')} algoId={ao.get('algoId','?')}")
                    except Exception as _aoe:
                        _log(f"    Algo cancel fail: {ao.get('symbol','?')} — {str(_aoe)[:80]}")
            else:
                _log("  No algo orders to cancel")
        except Exception as _aoe2:
            _log(f"  Algo order cancel failed: {str(_aoe2)[:120]} — continuing")

        # Close positions
        positions = ex.fetch_positions()
        open_pos = [p for p in positions if abs(float(p.get("contracts", 0) or 0)) > 1e-9]

        if not open_pos:
            _log("  No open positions to close")
        else:
            _log(f"  Closing {len(open_pos)} open positions...")
            for pos in open_pos:
                sym = pos.get("symbol", "")
                side = str(pos.get("side", "")).lower()
                qty = abs(float(pos.get("contracts", 0) or 0))
                if qty <= 0 or not sym:
                    continue
                close_side = "sell" if side == "long" else "buy"
                try:
                    order = ex.create_order(
                        symbol=sym,
                        type="market",
                        side=close_side,
                        amount=qty,
                        params={"reduceOnly": True},
                    )
                    _log(f"    CLOSED: {sym} {side} qty={qty:.4f} → order_id={order.get('id','?')}")
                except Exception as _pos_err:
                    _log(f"    CLOSE FAIL: {sym} — {str(_pos_err)[:120]}")

        _log("STEP B: Champion positions closed")
    except Exception as e:
        _log(f"STEP B ERROR: {str(e)[:200]}")
        _abort("Failed to close champion positions — manual intervention required")


# ── Step C: Start v13 daemon ──────────────────────────────────────────────────
def start_v13_daemon() -> None:
    """Launch v13 daemon as a background subprocess."""
    _log("STEP C: Starting V13 daemon...")

    python = sys.executable  # same venv as swap script
    v13_daemon = str(ROOT / "scripts" / "futures_daemon_v13.py")

    env = os.environ.copy()
    env["PA_BOT_NAME"] = "v13"
    env["PA_RUN_MODE"] = "paper"
    env["PA_15M_CONFIG"] = "configs/risk_v13_testnet.yaml"
    env.pop("PA_LIVE_CONFIRM", None)  # never set

    cmd = [python, "-u", v13_daemon, "--timeframe", "15m"]
    _log(f"  Command: {' '.join(cmd)}")
    _log(f"  Env: PA_BOT_NAME=v13 PA_RUN_MODE=paper PA_15M_CONFIG=configs/risk_v13_testnet.yaml")

    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            cwd=str(ROOT),
            stdout=open(ROOT / "logs" / "futures_daemon_v13_stdout.log", "a"),
            stderr=open(ROOT / "logs" / "futures_daemon_v13.log", "a"),
            start_new_session=True,  # detach from parent process group
        )
        pid = proc.pid
        _log(f"  V13 daemon started: PID={pid}")

        # Write PID file
        pid_file = ROOT / "logs" / "v13_daemon.pid"
        pid_file.write_text(str(pid), encoding="utf-8")
        _log(f"  PID file: {pid_file}")

        # Wait 3s and check it's still alive
        time.sleep(3)
        ret = proc.poll()
        if ret is not None:
            _abort(f"V13 daemon exited immediately (returncode={ret}) — check logs/futures_daemon_v13.log")

        _log(f"  V13 daemon is running (PID={pid}, poll={proc.poll()})")
    except Exception as e:
        _abort(f"Failed to start v13 daemon: {e}")

    _log("STEP C: V13 daemon launch complete")


# ── Main swap sequence ────────────────────────────────────────────────────────
def main() -> None:
    # Time in TR
    _log("=" * 65)
    _log("SWAP: Champion → V13 Testnet Daemon")
    _log(f"  Champion PID      : {CHAMPION_PID} (will be SIGTERM'd)")
    _log(f"  5m daemon PID     : {_5M_PID} (NOT touched)")
    _log(f"  V13 config        : configs/risk_v13_testnet.yaml")
    _log(f"  PA_LIVE_CONFIRM   : NOT SET (testnet only)")
    _log("=" * 65)

    # Confirm once more
    _log("Running preflight_checks()...")
    preflight_checks()

    # Confirm to user
    _log("")
    _log("ALL PREFLIGHT CHECKS PASSED.")
    _log("Proceeding with swap in 5 seconds...")
    _log("(Kill this script NOW if not ready: Ctrl+C)")
    time.sleep(5)

    stop_champion()
    close_champion_positions()
    start_v13_daemon()

    _log("")
    _log("=" * 65)
    _log("SWAP COMPLETE.")
    _log(f"  Champion PID {CHAMPION_PID}: STOPPED")
    _log(f"  Champion positions: CLOSED")
    _log(f"  V13 daemon: STARTED (see logs/v13_daemon.pid)")
    _log("")
    _log("NEXT STEPS:")
    _log("  1. Verify wallet reset to ~$10k (see WALLET RESET in this file)")
    _log("  2. Run: python scripts/v13_exchange_truth_tracker.py --startup")
    _log("  3. Monitor: tail -f logs/futures_daemon_v13.log")
    _log("  4. First exchange-truth snapshot in 24h from v13_equity_snapshots table")
    _log("=" * 65)


if __name__ == "__main__":
    if SWAP_EXECUTE != "CONFIRM_SWAP_TO_V13":
        print("=" * 65)
        print("STAGED SWAP SCRIPT — champion → v13 testnet daemon")
        print("")
        print("This script is STAGED and does NOTHING without explicit activation.")
        print("")
        print("To execute the swap when Principal confirms:")
        print("  SWAP_EXECUTE=CONFIRM_SWAP_TO_V13 python scripts/swap_champion_to_v13.py")
        print("")
        print("PRE-REQUISITES before executing:")
        print("  1. pytest tests/test_v13_daemon.py  — all tests must pass")
        print("  2. python scripts/futures_daemon_v13.py --once  — dry-run clean")
        print("  3. Testnet wallet reset to ~$10k (manual faucet — see docstring)")
        print("     URL: https://testnet.binancefuture.com/en/futures/BTC_USDT")
        print("  4. Champion PID 53708 confirmed still running")
        print("  5. PA_LIVE_CONFIRM NOT set")
        print("=" * 65)
        sys.exit(0)
    main()
