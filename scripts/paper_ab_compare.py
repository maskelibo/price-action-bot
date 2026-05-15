"""ATLAS vs PHOENIX paper A/B karşılaştırma dashboard.

Usage:
    python scripts/paper_ab_compare.py
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
import duckdb


def get_bot_summary(bot_name: str) -> dict:
    state_path = ROOT / "logs" / "execution" / f"paper_state_{bot_name}.json"
    journal = ROOT / "data" / f"paper_journal_{bot_name}.duckdb"
    out = {"bot": bot_name.upper(), "exists": False}
    if not state_path.exists() or not journal.exists():
        return out
    out["exists"] = True
    state = json.loads(state_path.read_text())
    out["equity"] = state.get("balances", {}).get("USDT", 0)
    out["open_positions"] = len(state.get("positions", []))
    out["realized_pnl"] = state.get("realized_pnl_total", 0)
    out["start_ts"] = state.get("start_ts", "")
    try:
        con = duckdb.connect(str(journal), read_only=True)
        out["n_signals"] = con.execute("SELECT COUNT(*) FROM paper_signals").fetchone()[0]
        out["n_trades_closed"] = con.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        out["n_equity_snapshots"] = con.execute("SELECT COUNT(*) FROM paper_equity_snapshots").fetchone()[0]
        last_eq = con.execute("SELECT equity FROM paper_equity_snapshots ORDER BY ts DESC LIMIT 1").fetchone()
        out["last_snapshot_equity"] = last_eq[0] if last_eq else None
        con.close()
    except Exception as e:
        out["journal_err"] = str(e)
    return out


def main():
    print("=" * 90)
    print(f"📊 ATLAS vs PHOENIX Paper A/B Dashboard — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 90)
    atlas = get_bot_summary("atlas")
    phoenix = get_bot_summary("phoenix")

    print(f"\n🏛️  ATLAS (v2.0.3 — wyckoff dahil, 11 strateji)")
    print("-" * 90)
    if not atlas["exists"]:
        print("  ❌ State veya journal yok — başlatılmamış.")
    else:
        print(f"  Equity:           ${atlas['equity']:,.2f}")
        print(f"  Open positions:   {atlas['open_positions']}")
        print(f"  Realized PnL:     ${atlas['realized_pnl']:+,.2f}")
        print(f"  Signals scanned:  {atlas.get('n_signals', 0)}")
        print(f"  Trades closed:    {atlas.get('n_trades_closed', 0)}")
        print(f"  Equity snapshots: {atlas.get('n_equity_snapshots', 0)}")
        print(f"  Start:            {atlas['start_ts']}")

    print(f"\n🔥 PHOENIX (v2.0.4 — wyckoff DISABLED, 10 strateji)")
    print("-" * 90)
    if not phoenix["exists"]:
        print("  ❌ State veya journal yok — başlatılmamış.")
    else:
        print(f"  Equity:           ${phoenix['equity']:,.2f}")
        print(f"  Open positions:   {phoenix['open_positions']}")
        print(f"  Realized PnL:     ${phoenix['realized_pnl']:+,.2f}")
        print(f"  Signals scanned:  {phoenix.get('n_signals', 0)}")
        print(f"  Trades closed:    {phoenix.get('n_trades_closed', 0)}")
        print(f"  Equity snapshots: {phoenix.get('n_equity_snapshots', 0)}")
        print(f"  Start:            {phoenix['start_ts']}")

    if atlas["exists"] and phoenix["exists"]:
        print(f"\n📊 DELTA (PHOENIX − ATLAS)")
        print("-" * 90)
        eq_d = phoenix["equity"] - atlas["equity"]
        pnl_d = phoenix["realized_pnl"] - atlas["realized_pnl"]
        print(f"  Equity delta:     ${eq_d:+,.2f}")
        print(f"  Realized delta:   ${pnl_d:+,.2f}")
        print(f"  Trade count delta: {phoenix.get('n_trades_closed', 0) - atlas.get('n_trades_closed', 0):+d}")
        if atlas["equity"] > 0:
            pct = (phoenix["equity"] - atlas["equity"]) / atlas["equity"] * 100
            print(f"  Equity edge %:    {pct:+.2f}%")

    print("\n" + "=" * 90)
    print("Backtest expectations:")
    print(f"  ATLAS:   yıllık +%134.3 / DD -%42.5 / r-adj 3.16  (memory baseline +%239.5)")
    print(f"  PHOENIX: yıllık +%200.3 / DD -%32.0 / r-adj 6.26  (+%66pp uplift over ATLAS)")
    print("Paper test hedef: 90 gün, ardından promotion karar.")
    print("=" * 90)


if __name__ == "__main__":
    main()
