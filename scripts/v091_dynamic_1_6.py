"""v0.9.1 - Dynamic risk %1-%6 (yuksek conf'a daha cok bas) - 1y test."""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
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


def conf_to_risk_dyn(conf: float) -> float:
    """Dynamic %1-%6 based on confidence score."""
    if conf < 0.32: return 0.010   # %1 — defensive
    if conf < 0.42: return 0.020   # %2
    if conf < 0.52: return 0.030   # %3
    if conf < 0.58: return 0.045   # %4.5
    return 0.060                   # %6 — yuksek conf, max bas


def replay_dyn(trades, max_concurrent=8, cooldown_days=3, conf_min=0.20,
               consecutive_loss_n=3, consecutive_loss_pause=5,
               daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15,
               risk_fn=None):
    if risk_fn is None: risk_fn = conf_to_risk_dyn
    if not trades: return None
    trades = [t for t in trades if t["conf"] >= conf_min]
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0; cash = 10_000.0
    open_pos = []; eq_curve = [10_000.0]; Rs = []
    daily_anchor = weekly_anchor = monthly_anchor = 10_000.0
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    blocked_until = None
    last_entry: dict[tuple, pd.Timestamp] = {}
    consecutive_losses = 0
    cool_until = None

    # Tier istatistik
    tier_stats = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}

    def tier_idx(conf):
        if conf < 0.32: return 0
        if conf < 0.42: return 1
        if conf < 0.52: return 2
        if conf < 0.58: return 3
        return 4

    def close_due(now):
        nonlocal cash, equity, consecutive_losses, cool_until
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                Rs.append(p["R"])
                eq_curve.append(equity)
                if pnl < 0:
                    consecutive_losses += 1
                    if consecutive_losses >= consecutive_loss_n:
                        cool_until = p["exit_ts"] + timedelta(days=consecutive_loss_pause)
                        consecutive_losses = 0
                else:
                    consecutive_losses = 0
            else: still.append(p)
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
        risk_pct = risk_fn(t["conf"])
        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        margin = notional / 3.0
        if margin > cash: continue
        cash -= margin
        last_entry[key] = t["entry_ts"]
        tier_stats[tier_idx(t["conf"])] += 1
        open_pos.append({"exit_ts": t["exit_ts"], "margin": margin, "risk": risk_d, "R": t["R"]})

    for p in open_pos:
        cash += p["margin"] + p["risk"] * p["R"]
        equity = cash; Rs.append(p["R"])
        eq_curve.append(equity)

    peak_v = eq_curve[0]; max_dd = 0
    for v in eq_curve:
        if v > peak_v: peak_v = v
        dd = (v - peak_v)/peak_v
        if dd < max_dd: max_dd = dd
    win = sum(1 for x in Rs if x > 0)/len(Rs) if Rs else 0
    return {"final": equity, "max_dd": max_dd, "trades": len(Rs), "wr": win,
            "tier_stats": tier_stats}


def main():
    print("=" * 80)
    print("v0.9.1 + DYNAMIC RISK 1-6 — 1y test (2025-05 -> 2026-05)")
    print("=" * 80)

    print("\nTopluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])

    win_start = pd.Timestamp("2025-05-09", tz="UTC")
    win_end = pd.Timestamp("2026-05-09", tz="UTC")
    one_year = [t for t in all_trades if win_start <= t["entry_ts"] < win_end]
    print(f"1y sinyal: {len(one_year)}\n")

    # Tier dagilimi (filtre oncesi)
    print("# Confidence tier dagilimi (1y, conf>=0.20 sonra):")
    eligible = [t for t in one_year if t["conf"] >= 0.20]
    tiers = [
        ("0.20-0.32 (lev 1x, %1)", lambda c: 0.20 <= c < 0.32),
        ("0.32-0.42 (lev 2x, %2)", lambda c: 0.32 <= c < 0.42),
        ("0.42-0.52 (lev 3x, %3)", lambda c: 0.42 <= c < 0.52),
        ("0.52-0.58 (lev 4x, %4.5)", lambda c: 0.52 <= c < 0.58),
        ("0.58+    (lev 5x, %6)", lambda c: c >= 0.58),
    ]
    for label, fn in tiers:
        ts = [t for t in eligible if fn(t["conf"])]
        if not ts:
            print(f"  {label:<32} 0 sinyal")
            continue
        wins = sum(1 for t in ts if t["R"] > 0)
        avg_r = np.mean([t["R"] for t in ts])
        sum_r = sum(t["R"] for t in ts)
        print(f"  {label:<32} {len(ts):>4} sinyal, WR {100*wins/len(ts):>3.0f}%, avg R {avg_r:>+5.2f}, sum R {sum_r:>+6.1f}")
    print()

    print("=" * 80)
    print("# 1y SONUCLAR (sabit vs dynamic risk)")
    print("=" * 80)
    print(f"{'Senaryo':<35} {'final$':>10} {'getiri%':>9} {'DD':>6} {'WR':>4} {'trade':>5}")
    print("-" * 75)

    # Sabit risk benchmarks
    for risk in [0.010, 0.015, 0.020, 0.025, 0.030]:
        rr = replay_dyn(one_year, risk_fn=lambda c, r=risk: r)
        if rr is None: continue
        rret = (rr["final"]/10000-1)*100
        print(f"{'Sabit %' + f'{risk*100:.1f}':<35} {rr['final']:>10,.0f} {rret:>+8.1f}% {rr['max_dd']*100:>+5.0f}% {rr['wr']*100:>3.0f}% {rr['trades']:>5}")

    # Dynamic %1-%6
    print()
    rr = replay_dyn(one_year, risk_fn=conf_to_risk_dyn)
    if rr:
        rret = (rr["final"]/10000-1)*100
        print(f"{'DYNAMIC %1-%6 ⭐':<35} {rr['final']:>10,.0f} {rret:>+8.1f}% {rr['max_dd']*100:>+5.0f}% {rr['wr']*100:>3.0f}% {rr['trades']:>5}")
        print()
        print(f"# Dynamic %1-%6 detay:")
        print(f"  Final: ${rr['final']:,.2f}")
        print(f"  1y getiri: {rret:+.2f}%")
        print(f"  Max DD: {rr['max_dd']*100:+.1f}%")
        print(f"  WR: {rr['wr']*100:.1f}%")
        print(f"  $10K -> 1y -> ${rr['final']:,.0f}")
        print(f"  $200 -> 1y -> ${200 * rr['final']/10000:,.0f}")
        print(f"\n# Tier dagilimi (kaç trade hangi tier'da acildi):")
        ts = rr["tier_stats"]
        labels = ["%1 (0.20-0.32)", "%2 (0.32-0.42)", "%3 (0.42-0.52)", "%4.5 (0.52-0.58)", "%6 (0.58+)"]
        for i in range(5):
            print(f"  Tier {labels[i]:<18}: {ts.get(i, 0):>3} trade")

    # Alternatif tier'lar
    print()
    print("# Alternatif dynamic tier'lar:")
    print(f"{'Senaryo':<35} {'final$':>10} {'getiri%':>9} {'DD':>6} {'WR':>4}")
    print("-" * 75)
    # FINE-GRAINED: 0.32-0.42 i 4 alt tiere bol
    def fg_1_6(c):
        # 0.32-0.34: %1
        # 0.34-0.36: %2
        # 0.36-0.38: %3
        # 0.38-0.40: %4
        # 0.40-0.42: %5
        # 0.42+    : %6
        if c < 0.32: return 0.010
        if c < 0.34: return 0.015
        if c < 0.36: return 0.025
        if c < 0.38: return 0.035
        if c < 0.40: return 0.045
        if c < 0.42: return 0.055
        return 0.060

    def fg_15_6(c):
        # Daha defansif
        if c < 0.32: return 0.015
        if c < 0.34: return 0.020
        if c < 0.36: return 0.025
        if c < 0.38: return 0.035
        if c < 0.40: return 0.045
        return 0.060

    alt_tiers = [
        ("%1-%4 (orig)", lambda c: 0.010 if c < 0.32 else (0.015 if c < 0.42 else (0.020 if c < 0.52 else (0.030 if c < 0.58 else 0.040)))),
        ("%1-%6 KABA (USER)", conf_to_risk_dyn),
        ("%1-%6 FINE-GRAINED ⭐", fg_1_6),
        ("%1.5-%6 FINE-GRAINED", fg_15_6),
        ("%1-%6 daha agresif (cutoffs 0.34/0.36/0.38)", lambda c: 0.010 if c < 0.32 else (0.020 if c < 0.34 else (0.040 if c < 0.36 else (0.060 if c >= 0.36 else 0.060)))),
    ]
    for name, fn in alt_tiers:
        rr = replay_dyn(one_year, risk_fn=fn)
        if rr is None: continue
        rret = (rr["final"]/10000-1)*100
        print(f"{name:<35} {rr['final']:>10,.0f} {rret:>+8.1f}% {rr['max_dd']*100:>+5.0f}% {rr['wr']*100:>3.0f}%")


if __name__ == "__main__":
    main()
