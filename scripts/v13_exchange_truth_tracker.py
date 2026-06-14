"""V13 Exchange-Truth Daily Equity Tracker.

Reads PnL/equity DIRECTLY from Binance testnet exchange API endpoints.
Does NOT read from the journal (journal drifts — phantom/qty-drift/double-count history).

Sources of truth:
  1. fapiPrivateGetIncome(incomeType='REALIZED_PNL')  — actual closed trade PnL
  2. fapiPrivateGetIncome(incomeType='COMMISSION')     — actual fees paid
  3. fetch_positions()                                 — live unrealized PnL
  4. fetch_balance()                                   — wallet balance

Output:
  data/v13_exchange_truth.duckdb  (v13_equity_snapshots table)
  Printed snapshot to stdout/log

Usage:
  # Daemon cron (run daily at 22:00 UTC or on-demand):
  python scripts/v13_exchange_truth_tracker.py

  # Also run at v13 daemon startup:
  python scripts/v13_exchange_truth_tracker.py --startup
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

DB_PATH = ROOT / "data" / "v13_exchange_truth.duckdb"


def _get_v13_start_ts() -> int:
    """Return v13 start timestamp as Unix milliseconds.

    Reads from v13_meta table in v13_exchange_truth.duckdb.
    Falls back to 2026-06-03T00:00:00Z if not recorded.
    """
    import duckdb

    fallback_ms = int(datetime(2026, 6, 3, 0, 0, 0, tzinfo=UTC).timestamp() * 1000)
    if not DB_PATH.exists():
        return fallback_ms
    try:
        con = duckdb.connect(str(DB_PATH), read_only=True)
        row = con.execute(
            "SELECT value FROM v13_meta WHERE key = 'v13_start_ts'"
        ).fetchone()
        con.close()
        if row:
            ts = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            return int(ts.timestamp() * 1000)
    except Exception:
        pass
    return fallback_ms


def fetch_v13_exchange_snapshot() -> dict:
    """Fetch v13 PnL snapshot directly from exchange.

    Returns dict with keys:
      wallet_balance, realized_pnl, commission, unrealized_pnl,
      total_net, n_positions, ts, snap_id
    """
    from scripts.futures_trade_daily import get_futures_exchange

    ex = get_futures_exchange()
    snap = {
        "snap_id": uuid.uuid4().hex[:16],
        "ts": datetime.now(UTC),
        "wallet_balance": 0.0,
        "realized_pnl": 0.0,
        "commission": 0.0,
        "unrealized_pnl": 0.0,
        "total_net": 0.0,
        "n_positions": 0,
        "notes": "",
        "errors": [],
    }

    since_ms = _get_v13_start_ts()

    # 1. Realized PnL (exchange income — all closed trades since v13 start)
    try:
        income_batches = []
        limit = 1000
        start = since_ms
        while True:
            batch = ex.fapiPrivateGetIncome({
                "incomeType": "REALIZED_PNL",
                "startTime": start,
                "limit": limit,
            })
            if not batch:
                break
            income_batches.extend(batch)
            if len(batch) < limit:
                break
            # Paginate: next startTime = last ts + 1ms
            start = int(batch[-1].get("time", start)) + 1
            if start <= since_ms:
                break
        snap["realized_pnl"] = sum(float(i.get("income", 0)) for i in income_batches)
    except Exception as _e:
        snap["errors"].append(f"realized_pnl_fetch: {str(_e)[:120]}")

    # 2. Commission (actual fees paid since v13 start)
    try:
        fee_batches = []
        start = since_ms
        limit = 1000
        while True:
            batch = ex.fapiPrivateGetIncome({
                "incomeType": "COMMISSION",
                "startTime": start,
                "limit": limit,
            })
            if not batch:
                break
            fee_batches.extend(batch)
            if len(batch) < limit:
                break
            start = int(batch[-1].get("time", start)) + 1
            if start <= since_ms:
                break
        snap["commission"] = sum(float(f.get("income", 0)) for f in fee_batches)
    except Exception as _e:
        snap["errors"].append(f"commission_fetch: {str(_e)[:120]}")

    # 3. Unrealized PnL (open positions mark-to-market)
    try:
        positions = ex.fetch_positions()
        open_pos = [p for p in positions if abs(float(p.get("contracts", 0) or 0)) > 1e-9]
        snap["unrealized_pnl"] = sum(
            float(p.get("unrealizedPnl", 0) or 0) for p in open_pos
        )
        snap["n_positions"] = len(open_pos)
    except Exception as _e:
        snap["errors"].append(f"positions_fetch: {str(_e)[:120]}")

    # 4. Wallet balance
    try:
        bal = ex.fetch_balance()
        usdt = bal.get("USDT", {})
        snap["wallet_balance"] = float(usdt.get("total", 0) or 0)
    except Exception as _e:
        snap["errors"].append(f"balance_fetch: {str(_e)[:120]}")

    # Net total: realized + unrealized + commission (commission is negative = cost)
    snap["total_net"] = snap["realized_pnl"] + snap["unrealized_pnl"] + snap["commission"]
    snap["notes"] = (
        f"since={datetime.fromtimestamp(since_ms/1000, tz=UTC).strftime('%Y-%m-%dT%H:%MZ')} "
        f"errors={snap['errors']}"
    ) if snap["errors"] else (
        f"since={datetime.fromtimestamp(since_ms/1000, tz=UTC).strftime('%Y-%m-%dT%H:%MZ')}"
    )

    return snap


def persist_snapshot(snap: dict) -> None:
    """Write snapshot to v13_exchange_truth.duckdb."""
    import duckdb

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    try:
        # Ensure tables exist (idempotent)
        con.execute("""
            CREATE TABLE IF NOT EXISTS v13_equity_snapshots (
                snap_id         VARCHAR PRIMARY KEY,
                ts              TIMESTAMP,
                wallet_balance  DOUBLE,
                realized_pnl    DOUBLE,
                commission      DOUBLE,
                unrealized_pnl  DOUBLE,
                total_net       DOUBLE,
                n_positions     INTEGER,
                notes           VARCHAR
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS v13_meta (
                key   VARCHAR PRIMARY KEY,
                value VARCHAR
            )
        """)
        con.execute(
            """
            INSERT INTO v13_equity_snapshots
            (snap_id, ts, wallet_balance, realized_pnl, commission,
             unrealized_pnl, total_net, n_positions, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snap["snap_id"],
                snap["ts"],
                snap["wallet_balance"],
                snap["realized_pnl"],
                snap["commission"],
                snap["unrealized_pnl"],
                snap["total_net"],
                snap["n_positions"],
                snap["notes"],
            ),
        )
        con.commit()
    finally:
        con.close()


def print_snapshot(snap: dict) -> None:
    """Print human-readable snapshot (TR time per memory rule: UTC+3)."""
    # Memory: always report time in TR (UTC+3)
    from datetime import timezone, timedelta
    TR = timezone(timedelta(hours=3))
    ts_tr = snap["ts"].astimezone(TR).strftime("%Y-%m-%d %H:%M TR")

    print(f"[V13 EXCHANGE TRUTH] {ts_tr}")
    print(f"  Wallet balance  : ${snap['wallet_balance']:>10.2f}")
    print(f"  Realized PnL    : ${snap['realized_pnl']:>+10.2f}  (exchange REALIZED_PNL income)")
    print(f"  Commission paid : ${snap['commission']:>+10.2f}  (actual fees)")
    print(f"  Unrealized PnL  : ${snap['unrealized_pnl']:>+10.2f}  ({snap['n_positions']} open positions)")
    print(f"  TOTAL NET       : ${snap['total_net']:>+10.2f}  (realized + unrealized + fees)")
    print(f"  snap_id={snap['snap_id']}")
    if snap.get("errors"):
        print(f"  ERRORS: {snap['errors']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="V13 exchange-truth tracker")
    parser.add_argument("--startup", action="store_true", help="Startup snapshot (tag as startup)")
    parser.add_argument("--no-persist", action="store_true", help="Print only, don't write DB")
    args = parser.parse_args()

    print(f"[V13 EXCHANGE TRUTH] Fetching from Binance testnet exchange...")
    snap = fetch_v13_exchange_snapshot()

    if args.startup:
        snap["notes"] = "startup_snapshot | " + snap.get("notes", "")

    print_snapshot(snap)

    if not args.no_persist:
        persist_snapshot(snap)
        print(f"  [saved to {DB_PATH}]")
    else:
        print("  [--no-persist: not saved]")


if __name__ == "__main__":
    main()
