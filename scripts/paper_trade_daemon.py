"""Paper Trade DAEMON — sürekli çalışan paper trader.

İki job:
  1. SIGNAL SCAN — UTC 00:05 her gün (1d bar kapanışı sonrası)
  2. POSITION MONITOR — saatlik (açık pozisyonların SL/TP/trail durumu)

Usage:
    python scripts/paper_trade_daemon.py            # daemon mod (Ctrl+C ile dur)
    python scripts/paper_trade_daemon.py --once     # bir kez çalış (test)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def run_signal_scan():
    """Daily signal scan + submit (paper_trade_daily.daily_run)."""
    print(f"\n{'='*80}")
    print(f"[{datetime.now(timezone.utc).isoformat()}] DAILY SIGNAL SCAN")
    print(f"{'='*80}")
    from scripts.paper_trade_daily import daily_run
    from datetime import timedelta
    target = datetime.now(timezone.utc) - timedelta(days=1)  # dün kapanışı
    daily_run(target, dry_run=False)


def run_position_monitor():
    """Position monitoring (saatlik)."""
    from scripts.paper_position_monitor import monitor_all_positions
    monitor_all_positions(verbose=True)


def equity_snapshot():
    """Günlük equity snapshot."""
    import json, uuid, duckdb
    state_path = ROOT / "logs" / "execution" / "paper_state.json"
    if not state_path.exists():
        return
    state = json.loads(state_path.read_text())
    equity = state.get('balances', {}).get('USDT', 0)
    open_pos = len(state.get('positions', []))
    realized = state.get('realized_pnl_total', 0)
    journal = ROOT / "data" / "paper_journal.duckdb"
    con = duckdb.connect(str(journal))
    con.execute("""
        INSERT INTO paper_equity_snapshots VALUES (?, ?, ?, ?, ?, ?)
    """, (uuid.uuid4().hex[:16], datetime.now(timezone.utc), equity, open_pos, realized, 0.0))
    con.commit()
    con.close()
    print(f"[SNAPSHOT] equity=${equity:.2f}, open_positions={open_pos}, realized_total=${realized:+.2f}")


def main_loop():
    """APScheduler ile daily + hourly job'lar."""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        print("apscheduler yüklü değil — pip install apscheduler")
        return

    sched = BlockingScheduler(timezone="UTC")
    # Daily signal scan: UTC 00:05
    sched.add_job(run_signal_scan, CronTrigger(hour=0, minute=5), id='signal_scan')
    # Position monitor: her saat :00
    sched.add_job(run_position_monitor, CronTrigger(minute=0), id='position_monitor')
    # Equity snapshot: UTC 23:55 her gün
    sched.add_job(equity_snapshot, CronTrigger(hour=23, minute=55), id='equity_snapshot')

    print(f"[{datetime.now(timezone.utc).isoformat()}] DAEMON started")
    print(f"  - Daily signal scan: UTC 00:05")
    print(f"  - Position monitor: every hour")
    print(f"  - Equity snapshot: UTC 23:55")
    print(f"  Ctrl+C to stop")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        print(f"\n[{datetime.now(timezone.utc).isoformat()}] DAEMON stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Bir kez çalış (test)")
    args = parser.parse_args()

    if args.once:
        # Test: scan + monitor + snapshot
        run_signal_scan()
        run_position_monitor()
        equity_snapshot()
    else:
        main_loop()
