"""v0.9.1 fix sweep — onerilerin tek tek ve combo etkileri.

Onerileri:
  Fix1: Same-day max 2 yeni pozisyon
  Fix2: Cooldown reset esiği R>=1.0 (net P&L bazli)
  Fix3: brooks_failed_breakout drop (asimetri)
  Fix4: equal_highs_sweep + cvd_spike_fade drop (1y negatif)
  Fix5: Pozisyon cap notional/equity <= 0.5x
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path
from collections import defaultdict

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

from scripts.v09_optimize_top10 import _gather, TOP_10


def replay_fixed(trades, risk_pct=0.030, max_concurrent=8, cooldown_days=3,
                 conf_min=0.20, daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15,
                 consecutive_loss_n=3, consecutive_loss_pause=5,
                 # YENI fix parametreleri:
                 same_day_max=None,           # Fix1: gun basina max yeni poz
                 cooldown_min_r=None,         # Fix2: sayac reset icin min R
                 drop_strategies=None,        # Fix3+4: cikarilacak stratejiler
                 max_notional_ratio=None,     # Fix5: notional/equity cap
                 ):
    if not trades: return None
    drop_strategies = drop_strategies or set()
    trades = [t for t in trades if t["conf"] >= conf_min and t["strategy"] not in drop_strategies]
    if not trades: return None
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0; cash = 10_000.0
    open_pos = []; eq_curve = [10_000.0]; Rs = []
    daily_anchor = weekly_anchor = monthly_anchor = 10_000.0
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    blocked_until = None
    last_entry = {}
    consecutive_losses = 0
    consec_r_buffer = []  # son N trade'in R toplami (Fix2)
    cool_until = None
    peak_equity = 10_000.0
    same_day_count: dict = defaultdict(int)  # Fix1

    def close_due(now):
        nonlocal cash, equity, peak_equity, consecutive_losses, cool_until, consec_r_buffer
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                peak_equity = max(peak_equity, equity)
                Rs.append(p["R"])
                eq_curve.append(equity)
                if pnl < 0:
                    consecutive_losses += 1
                    consec_r_buffer.append(p["R"])
                    if consecutive_loss_n and consecutive_losses >= consecutive_loss_n:
                        cool_until = p["exit_ts"] + timedelta(days=consecutive_loss_pause)
                        consecutive_losses = 0
                        consec_r_buffer = []
                else:
                    # Fix2: kazanc sayaci sifirlasin mi?
                    if cooldown_min_r is not None:
                        # son birikmis kayiplari telafi eden bir kazanc olmali
                        # eger bu kazanc R'si > kayiplar topluyorsa sifirla
                        net_r = sum(consec_r_buffer) + p["R"]
                        if p["R"] >= cooldown_min_r or net_r >= 0:
                            consecutive_losses = 0
                            consec_r_buffer = []
                        # else: sayac devam
                    else:
                        consecutive_losses = 0
                        consec_r_buffer = []
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])
        if cool_until and t["entry_ts"] < cool_until: continue

        # Fix1: same-day cap
        d_key = t["entry_ts"].date()
        if same_day_max is not None and same_day_count[d_key] >= same_day_max: continue

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

        # Fix5: notional cap
        if max_notional_ratio is not None:
            cap = equity * max_notional_ratio
            if notional > cap:
                notional = cap
                risk_d = notional * sl_pct  # risk azalir

        margin = notional / 3.0
        if margin > cash: continue
        cash -= margin
        last_entry[key] = t["entry_ts"]
        same_day_count[d_key] += 1
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
    return {"final": equity, "max_dd": max_dd, "trades": len(Rs), "wr": win}


def run_window(all_trades, start, end, label):
    print(f"\n{'='*100}")
    print(f"{label}")
    print('='*100)
    window = [t for t in all_trades if start <= t["entry_ts"] < end]
    print(f"Sinyal: {len(window)}")

    yil = (end - start).days / 365.25

    scenarios = [
        ("BASELINE (v0.9.1 mevcut)",                 dict()),
        ("Fix1: same-day max 2",                      dict(same_day_max=2)),
        ("Fix1: same-day max 3",                      dict(same_day_max=3)),
        ("Fix2: cooldown min R=1.0",                  dict(cooldown_min_r=1.0)),
        ("Fix2: cooldown net-R>=0",                   dict(cooldown_min_r=999)),  # asla tekli kazancla sifirlanmaz
        ("Fix3: drop brooks_failed_breakout",         dict(drop_strategies={"brooks_failed_breakout"})),
        ("Fix4: drop equal_highs_sweep",              dict(drop_strategies={"equal_highs_sweep"})),
        ("Fix4: drop equal_highs + cvd",              dict(drop_strategies={"equal_highs_sweep","cvd_spike_fade"})),
        ("Fix5: notional cap 0.5x",                   dict(max_notional_ratio=0.5)),
        ("Fix5: notional cap 0.3x",                   dict(max_notional_ratio=0.3)),
        ("",                                           None),
        ("COMBO A: same-day2 + smart-cooldown",       dict(same_day_max=2, cooldown_min_r=999)),
        ("COMBO B: A + drop equal_highs",             dict(same_day_max=2, cooldown_min_r=999,
                                                          drop_strategies={"equal_highs_sweep","cvd_spike_fade"})),
        ("COMBO C: B + notional cap 0.5x",            dict(same_day_max=2, cooldown_min_r=999,
                                                          drop_strategies={"equal_highs_sweep","cvd_spike_fade"},
                                                          max_notional_ratio=0.5)),
        ("COMBO D: same-day3 + smart-cd + cap0.5",    dict(same_day_max=3, cooldown_min_r=999,
                                                          max_notional_ratio=0.5)),
        ("COMBO E: HEPSI sıkı (same-day2+all fixes)", dict(same_day_max=2, cooldown_min_r=999,
                                                          drop_strategies={"equal_highs_sweep","cvd_spike_fade","brooks_failed_breakout"},
                                                          max_notional_ratio=0.5)),
    ]

    print(f"\n{'Senaryo':<48} {'trade':>6} {'final$':>10} {'getiri%':>9} {'yillik%':>9} {'maxDD':>7} {'WR':>5}")
    print("-" * 100)
    for name, kwargs in scenarios:
        if kwargs is None:
            print("-" * 100); continue
        r = replay_fixed(window, **kwargs)
        if r is None:
            print(f"  {name:<48} (sonuc yok)")
            continue
        ret = (r["final"]/10000-1)*100
        ann = ((r["final"]/10000)**(1/yil)-1)*100
        print(f"  {name:<48} {r['trades']:>6} {r['final']:>10,.0f} {ret:>+8.1f}% {ann:>+8.1f}% {r['max_dd']*100:>+5.0f}% {r['wr']*100:>4.0f}%")


def main():
    print("=" * 100)
    print("v0.9.1 FIX SWEEP — onerilerin tek tek ve combo etkileri")
    print("=" * 100)
    print("\nTopluyor (5y data)...")

    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam 5y sinyal: {len(all_trades)}")

    # 1y window (out-of-sample son 1y)
    run_window(all_trades,
               pd.Timestamp("2025-05-09", tz="UTC"),
               pd.Timestamp("2026-05-09", tz="UTC"),
               "1Y OUT-OF-SAMPLE (2025-05 -> 2026-05)")

    # Tum 5y
    if all_trades:
        run_window(all_trades,
                   all_trades[0]["entry_ts"],
                   pd.Timestamp("2026-05-09", tz="UTC"),
                   "5Y FULL (in-sample)")


if __name__ == "__main__":
    main()
