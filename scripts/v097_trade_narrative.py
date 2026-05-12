"""v0.9.7 — Trade-by-trade narrative log.

BALANCED v0.9.7 preset (en son production aday) ile 2023-01-01 -> simdi backtest,
her trade'i Turkce narrative formatinda anlat:
  - Pozisyon: X coin x fiyat = $Y, equity %Z, leverage 3x
  - Risk: $X (equity %Y)
  - SL: fiyat, %X uzaklik
  - Cikis: fiyat, %X hareket
  - Sonuc: kazanc/kayip $X (R=+N), equity etki
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig
from scripts.v09_optimize_top10 import _gather, TOP_10
from scripts.v096_backtest_2023 import replay_with_log


def main():
    print("=" * 110)
    print("v0.9.7 TRADE-BY-TRADE NARRATIVE — BALANCED preset, 2023-01-01 -> 2026-05-12")
    print("=" * 110)

    print("\nTrade topluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])

    start = pd.Timestamp("2023-01-01", tz="UTC")
    end = pd.Timestamp("2026-05-12", tz="UTC")
    window = [t for t in all_trades if start <= t["entry_ts"] < end]
    print(f"Pencere sinyal: {len(window)}\n")

    cfg = ProductionConfig.from_yaml("configs/risk_balanced.yaml")
    result = replay_with_log(window, cfg)
    if result is None:
        print("NO RESULT"); return

    log = sorted(result["log"], key=lambda x: x["entry_ts"])

    print(f"Toplam trade: {len(log)}  |  Final equity: ${result['final']:,.2f}")
    print(f"Yillik (3.36y compound): {((result['final']/10_000)**(1/3.36)-1)*100:+.2f}%")
    print(f"Max DD: {result['max_dd']*100:+.1f}%  |  WR: {result['wr']*100:.1f}%")
    print()
    print("=" * 110)
    print("ISLEMLERIN TEK TEK DOKUMU")
    print("=" * 110)

    # Equity timeline icin
    eq_at = 10_000.0  # baslangic
    LEV = 3.0  # backtest leverage assumption (cross margin)

    for i, p in enumerate(log, 1):
        date_in = p["entry_ts"].strftime("%Y-%m-%d")
        date_out = p["exit_ts"].strftime("%Y-%m-%d")
        days_held = (p["exit_ts"] - p["entry_ts"]).days
        sym = p["symbol"].replace("/USDT", "")
        side_tr = "LONG" if p["side"] == "long" else "SHORT"
        strat = p["strategy"]
        entry_p = p["entry_price"]
        notional = p["notional"]
        risk = p["risk"]
        R = p["R"]
        pnl = p["pnl"]
        exit_eq = p["exit_equity"]

        # Pozisyon miktari (coin sayisi)
        qty = notional / entry_p
        # Exit price hesap (R-multiple'den)
        # long: exit = entry + R * (entry - SL)
        # SL pct ~ risk / notional (cunku risk = notional * sl_pct)
        sl_pct = risk / notional if notional > 0 else 0
        if p["side"] == "long":
            sl_price = entry_p * (1 - sl_pct)
            exit_price = entry_p + R * (entry_p - sl_price)
        else:
            sl_price = entry_p * (1 + sl_pct)
            exit_price = entry_p - R * (sl_price - entry_p)
        move_pct = (exit_price - entry_p) / entry_p * 100
        if p["side"] == "short":
            move_pct = -move_pct  # short icin lehe hareket pozitif

        # Equity giris anindaki
        eq_pre = eq_at
        eq_at = exit_eq
        eq_change_pct = pnl / eq_pre * 100 if eq_pre > 0 else 0

        # Notional / equity orani
        notional_pct = notional / eq_pre * 100 if eq_pre > 0 else 0
        margin_used = notional / LEV
        margin_pct = margin_used / eq_pre * 100 if eq_pre > 0 else 0

        result_emoji = "KAR" if R > 0 else "ZARAR"
        result_sign = "+" if pnl >= 0 else ""

        print(f"\n#{i:>3} | {date_in} → {date_out} ({days_held}g) | {sym} {side_tr} | {strat}")
        print(f"      Pozisyon : {qty:.4f} {sym} × ${entry_p:,.4f} = ${notional:,.2f}")
        print(f"                 (equity ${eq_pre:,.0f}'nin %{notional_pct:.1f}'i, margin ${margin_used:,.0f} = %{margin_pct:.1f} @ {LEV:.0f}x lev)")
        print(f"      Risk     : ${risk:,.2f} (equity %{risk/eq_pre*100:.2f})")
        print(f"      SL       : ${sl_price:,.4f} (entry'den %{sl_pct*100:.2f} uzakta)")
        print(f"      Cikis    : ${exit_price:,.4f} ({result_sign}{move_pct:+.2f}% lehe hareket)")
        print(f"      Sonuc    : {result_emoji} {result_sign}${abs(pnl):,.2f} (R={R:+.2f}, equity etki %{eq_change_pct:+.2f})")
        print(f"      Yeni eq  : ${exit_eq:,.2f}")

    # Final ozet
    print()
    print("=" * 110)
    print("AYLIK OZET")
    print("=" * 110)
    monthly = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0})
    for p in log:
        ym = p["exit_ts"].strftime("%Y-%m")
        monthly[ym]["n"] += 1
        monthly[ym]["pnl"] += p["pnl"]
        if p["R"] > 0: monthly[ym]["wins"] += 1
    print(f"  {'Ay':<10} {'Trade':>6} {'Win':>4} {'WR':>5} {'P&L':>10}")
    for ym, s in sorted(monthly.items()):
        wr = s['wins'] / s['n'] * 100 if s['n'] else 0
        print(f"  {ym:<10} {s['n']:>6} {s['wins']:>4} {wr:>4.0f}% {s['pnl']:>+9,.0f}")

    # CSV
    out_csv = ROOT / "reports" / "v097_balanced_trades_narrative.csv"
    out_csv.parent.mkdir(exist_ok=True)
    import csv
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#","tarih_giris","tarih_cikis","gun","sembol","yon","strateji",
                   "giris_fiyat","sl_fiyat","cikis_fiyat","coin_qty","notional_$","margin_$","risk_$","R","pnl_$","equity_$"])
        eq_running = 10_000.0
        for i, p in enumerate(log, 1):
            qty = p["notional"]/p["entry_price"]
            sl_pct = p["risk"]/p["notional"] if p["notional"]>0 else 0
            if p["side"] == "long":
                sl = p["entry_price"]*(1-sl_pct)
                ex = p["entry_price"]+p["R"]*(p["entry_price"]-sl)
            else:
                sl = p["entry_price"]*(1+sl_pct)
                ex = p["entry_price"]-p["R"]*(sl-p["entry_price"])
            days = (p["exit_ts"]-p["entry_ts"]).days
            margin = p["notional"]/3.0
            w.writerow([i, p["entry_ts"].strftime("%Y-%m-%d"), p["exit_ts"].strftime("%Y-%m-%d"),
                       days, p["symbol"], p["side"], p["strategy"],
                       f"{p['entry_price']:.4f}", f"{sl:.4f}", f"{ex:.4f}",
                       f"{qty:.6f}", f"{p['notional']:.2f}", f"{margin:.2f}",
                       f"{p['risk']:.2f}", f"{p['R']:.4f}", f"{p['pnl']:.2f}",
                       f"{p['exit_equity']:.2f}"])
    print(f"\nCSV: {out_csv}")


if __name__ == "__main__":
    main()
