"""v0.9.1 - 2025-05 -> 2026-05 (1 yil) trade-by-trade detay raporu.

Production config (%3 risk, conf>=0.20, 3-loss cooldown).
Her trade icin: entry/exit fiyat, pozisyon $, P&L $, equity, R.
"""
from __future__ import annotations

import sys
import csv
from datetime import timedelta
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

from scripts.v09_optimize_top10 import _gather, TOP_10


def replay_with_detail(trades, risk_pct=0.030, conf_min=0.20, max_concurrent=8,
                      cooldown_days=3, daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15,
                      consecutive_loss_n=3, consecutive_loss_pause=5):
    """v0.9.1 production replay — her trade icin detay dondurur."""
    if not trades: return [], None
    trades = [t for t in trades if t["conf"] >= conf_min]
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0; cash = 10_000.0
    open_pos = []; eq_curve = [10_000.0]
    detail_log = []  # her acilan trade icin kayit
    daily_anchor = weekly_anchor = monthly_anchor = 10_000.0
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    blocked_until = None
    last_entry = {}
    consecutive_losses = 0
    cool_until = None
    peak_equity = 10_000.0
    trade_id = 0

    def close_due(now):
        nonlocal cash, equity, peak_equity, consecutive_losses, cool_until
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                peak_equity = max(peak_equity, equity)
                eq_curve.append(equity)
                # detay logu guncelle
                p["exit_equity"] = equity
                p["pnl_dollar"] = pnl
                if pnl < 0:
                    consecutive_losses += 1
                    if consecutive_loss_n and consecutive_losses >= consecutive_loss_n:
                        cool_until = p["exit_ts"] + timedelta(days=consecutive_loss_pause)
                        consecutive_losses = 0
                else:
                    consecutive_losses = 0
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])
        if cool_until and t["entry_ts"] < cool_until: continue
        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).days < cooldown_days: continue
        cd = t["entry_ts"].date(); cw = t["entry_ts"].isocalendar()[1]; cm = t["entry_ts"].month
        if cd != last_d: daily_anchor = equity; last_d = cd
        if cw != last_w: weekly_anchor = equity; last_w = cw
        if cm != last_m: monthly_anchor = equity; last_m = cm
        if blocked_until and t["entry_ts"] < blocked_until: continue
        if (daily_anchor - equity)/max(daily_anchor,1) >= daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=1); continue
        if (weekly_anchor - equity)/max(weekly_anchor,1) >= weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=7); continue
        if (monthly_anchor - equity)/max(monthly_anchor,1) >= monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=30); continue
        if len(open_pos) >= max_concurrent: continue

        sl_pct = abs(t["entry_price"] - t["initial_sl"])/t["entry_price"]
        if sl_pct <= 0: continue
        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        margin = notional / 3.0
        if margin > cash: continue

        # Exit price hesap: R-multiple ve entry/SL'den
        # Long: exit = entry + R * (entry - SL)
        # Short: exit = entry - R * (SL - entry)
        entry_p = t["entry_price"]; sl_p = t["initial_sl"]; R = t["R"]
        risk_per_unit = abs(entry_p - sl_p)
        if t["side"] == "long":
            exit_p = entry_p + R * risk_per_unit
        else:
            exit_p = entry_p - R * risk_per_unit

        # Coin miktari
        coin_qty = notional / entry_p

        trade_id += 1
        cash -= margin
        last_entry[key] = t["entry_ts"]
        pos = {
            "id": trade_id,
            "exit_ts": t["exit_ts"],
            "entry_ts": t["entry_ts"],
            "symbol": t["symbol"],
            "side": t["side"],
            "strategy": t["strategy"],
            "conf": t["conf"],
            "entry_price": entry_p,
            "sl_price": sl_p,
            "exit_price": exit_p,
            "coin_qty": coin_qty,
            "notional": notional,
            "margin": margin,
            "risk": risk_d,
            "R": R,
            "entry_equity": equity,
            "exit_equity": None,  # close_due'da set edilecek
            "pnl_dollar": None,
        }
        open_pos.append(pos)
        detail_log.append(pos)

    # acik pozisyonlari kapat
    for p in open_pos:
        pnl = p["risk"] * p["R"]
        cash += p["margin"] + pnl
        equity = cash
        eq_curve.append(equity)
        p["exit_equity"] = equity
        p["pnl_dollar"] = pnl

    return detail_log, {"final": equity, "trades": len(detail_log)}


def main():
    print("=" * 110)
    print("v0.9.1 TRADE-BY-TRADE DETAY — 2025-05-09 -> 2026-05-09 (1 yil)")
    print("=" * 110)
    print("\nTopluyor (5y data, 1y filtreli)...")

    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])

    win_start = pd.Timestamp("2025-05-09", tz="UTC")
    win_end = pd.Timestamp("2026-05-09", tz="UTC")
    one_year = [t for t in all_trades if win_start <= t["entry_ts"] < win_end]
    print(f"1 yil pencere sinyal: {len(one_year)}\n")

    detail, summary = replay_with_detail(
        one_year, risk_pct=0.030, conf_min=0.20,
        consecutive_loss_n=3, consecutive_loss_pause=5,
    )
    print(f"Acilan trade: {len(detail)}, Final equity: ${summary['final']:,.2f}\n")

    # Tablo formatinda yazdir
    print(f"{'#':>3} {'tarih':<11} {'sembol':<10} {'yon':<5} {'strat':<22} "
          f"{'giris$':>10} {'SL$':>10} {'cikis$':>10} {'coin':>10} "
          f"{'pos$':>10} {'P&L$':>9} {'R':>6} {'equity$':>10}")
    print("-" * 165)
    for d in detail:
        date = d["entry_ts"].strftime("%Y-%m-%d")
        sym = d["symbol"].replace("/USDT", "")
        strat = d["strategy"][:22]
        print(
            f"{d['id']:>3} {date:<11} {sym:<10} {d['side']:<5} {strat:<22} "
            f"{d['entry_price']:>10.4f} {d['sl_price']:>10.4f} {d['exit_price']:>10.4f} "
            f"{d['coin_qty']:>10.4f} {d['notional']:>10.2f} "
            f"{d['pnl_dollar']:>+9.2f} {d['R']:>+6.2f} {d['exit_equity']:>10.2f}"
        )

    # CSV export
    csv_path = ROOT / "reports" / "v091_trades_2025_2026_detail.csv"
    csv_path.parent.mkdir(exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "entry_ts", "exit_ts", "symbol", "side", "strategy",
                   "conf", "entry_price", "sl_price", "exit_price", "coin_qty",
                   "notional", "margin", "risk_dollar", "R", "pnl_dollar",
                   "entry_equity", "exit_equity"])
        for d in detail:
            w.writerow([d["id"],
                       d["entry_ts"].strftime("%Y-%m-%d %H:%M"),
                       d["exit_ts"].strftime("%Y-%m-%d %H:%M"),
                       d["symbol"], d["side"], d["strategy"], f"{d['conf']:.3f}",
                       f"{d['entry_price']:.6f}", f"{d['sl_price']:.6f}",
                       f"{d['exit_price']:.6f}", f"{d['coin_qty']:.6f}",
                       f"{d['notional']:.2f}", f"{d['margin']:.2f}",
                       f"{d['risk']:.2f}", f"{d['R']:.4f}", f"{d['pnl_dollar']:.2f}",
                       f"{d['entry_equity']:.2f}", f"{d['exit_equity']:.2f}"])
    print(f"\nCSV: {csv_path}")

    # En iyi 5 ve en kotu 5 trade
    sorted_pnl = sorted(detail, key=lambda x: x["pnl_dollar"], reverse=True)
    print("\n# EN KARLI 5 TRADE:")
    for d in sorted_pnl[:5]:
        print(f"  {d['entry_ts'].strftime('%Y-%m-%d')} {d['symbol']:<10} {d['side']:<5} "
              f"R={d['R']:+.2f}  +${d['pnl_dollar']:,.2f}  ({d['strategy']})")
    print("\n# EN ZARARLI 5 TRADE:")
    for d in sorted_pnl[-5:]:
        print(f"  {d['entry_ts'].strftime('%Y-%m-%d')} {d['symbol']:<10} {d['side']:<5} "
              f"R={d['R']:+.2f}  ${d['pnl_dollar']:,.2f}  ({d['strategy']})")


if __name__ == "__main__":
    main()
