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
    """Signal scan + submit — her dakika tetiklenir, cache'li.

    1d bar tabanlı bot: sinyaller sadece UTC 00:00 bar kapanışında değişir.
    Cache mantığı: bugünkü tarih için zaten tarama yapıldıysa instant skip.
    Bu sayede her dakika tetik olur ama gerçek scan günde 1 kez.
    """
    import json
    _bot = os.environ.get("PA_BOT_NAME", "default").lower()
    last_scan_path = ROOT / "logs" / "execution" / f"last_scan_{_bot}.json"
    today_utc = datetime.now(timezone.utc).date().isoformat()

    # Cache check: bugün zaten taradık mı?
    if last_scan_path.exists():
        try:
            last = json.loads(last_scan_path.read_text())
            if last.get("date") == today_utc:
                return  # Bugün zaten taradık, instant skip
        except Exception:
            pass

    # Yeni 1d bar — scan yap
    print(f"\n{'='*80}")
    print(f"[{datetime.now(timezone.utc).isoformat()}] DAILY SIGNAL SCAN ({_bot.upper()})")
    print(f"{'='*80}")
    from scripts.paper_trade_daily import daily_run
    from datetime import timedelta
    target = datetime.now(timezone.utc) - timedelta(days=1)  # dün kapanışı
    daily_run(target, dry_run=False)

    # Cache güncelle
    last_scan_path.parent.mkdir(parents=True, exist_ok=True)
    last_scan_path.write_text(json.dumps({
        "date": today_utc,
        "ts": datetime.now(timezone.utc).isoformat(),
        "bot": _bot,
    }))


def run_position_monitor():
    """Position monitoring — her dakika tetiklenir (SL/TP latency 60dk → 1dk)."""
    from scripts.paper_position_monitor import monitor_all_positions
    monitor_all_positions(verbose=False)  # her dakika spam yapmasın


def equity_snapshot():
    """Günlük equity snapshot."""
    import json, uuid, duckdb
    # Multi-bot support
    _bot = os.environ.get("PA_BOT_NAME", "").lower()
    if _bot == "atlas":
        state_path = ROOT / "logs" / "execution" / "paper_state_atlas.json"
        journal = ROOT / "data" / "paper_journal_atlas.duckdb"
    elif _bot == "phoenix":
        state_path = ROOT / "logs" / "execution" / "paper_state_phoenix.json"
        journal = ROOT / "data" / "paper_journal_phoenix.duckdb"
    else:
        state_path = ROOT / "logs" / "execution" / "paper_state.json"
        journal = ROOT / "data" / "paper_journal.duckdb"
    if not state_path.exists():
        return
    state = json.loads(state_path.read_text())
    equity = state.get('balances', {}).get('USDT', 0)
    open_pos = len(state.get('positions', []))
    realized = state.get('realized_pnl_total', 0)
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
    # Signal scan: HER DAKİKA tetiklenir, cache'li (yeni 1d bar varsa scan, yoksa skip)
    sched.add_job(run_signal_scan, CronTrigger(minute='*'), id='signal_scan')
    # Position monitor: HER DAKİKA (SL/TP latency 60dk → 1dk)
    sched.add_job(run_position_monitor, CronTrigger(minute='*'), id='position_monitor')
    # Equity snapshot: UTC 23:55 her gün
    sched.add_job(equity_snapshot, CronTrigger(hour=23, minute=55), id='equity_snapshot')

    print(f"[{datetime.now(timezone.utc).isoformat()}] DAEMON started")
    print(f"  - Signal scan: HER DAKİKA (cache'li — gerçek scan yeni 1d bar geldiğinde)")
    print(f"  - Position monitor: HER DAKİKA (SL/TP hızlı yakalanır)")
    print(f"  - Equity snapshot: UTC 23:55 (günlük)")
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
