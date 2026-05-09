"""v0.9 DD reduction — ROI'yi koru, DD'yi dusur.

Mevcut: yillik +%53, DD -%80
Hedef: yillik +%45-55, DD -%50 ya da daha az

Denemeler:
  1. Tighter breakers (3/6/9 daily/weekly/monthly)
  2. Equity protection: -%30 DD'de risk yariya, -%50'de durdur
  3. Consecutive loss cool-down (3 kayip -> 5 gun dur)
  4. Vol-target sizing (yuksek vol gunlerde kucuk pos)
  5. Tighter correlation: max_concurrent 8 -> 5
  6. Strategy de-correlation: top 10 yerine en de-correlated 6
"""
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


def replay_protected(trades, risk_pct=0.030, max_concurrent=8, cooldown_days=3,
                     conf_min=0.20,
                     daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15,
                     equity_protect_30=False,    # -%30 DD'de risk yariya
                     equity_protect_50=False,    # -%50 DD'de tamamen dur
                     consecutive_loss_n=None,    # N ardisik kayip -> cool-down
                     consecutive_loss_pause=5,   # gun
                     vol_target=False,           # yuksek vol gunlerde kucuk
                     ):
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
    peak_equity = 10_000.0  # all-time peak

    def close_due(now):
        nonlocal cash, equity, peak_equity, consecutive_losses, cool_until
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
                    if consecutive_loss_n and consecutive_losses >= consecutive_loss_n:
                        cool_until = p["exit_ts"] + timedelta(days=consecutive_loss_pause)
                        consecutive_losses = 0
                else:
                    consecutive_losses = 0
            else: still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])

        # Cool-down check
        if cool_until and t["entry_ts"] < cool_until: continue

        # Equity protection: -%50 -> hard stop, -%30 -> half risk
        dd_from_peak = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
        risk_modifier = 1.0
        if equity_protect_50 and dd_from_peak >= 0.50: continue
        if equity_protect_30 and dd_from_peak >= 0.30: risk_modifier = 0.5

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
        risk_d = equity * risk_pct * risk_modifier
        # Vol-target: yuksek SL_pct (high vol bar) -> kucuk position
        if vol_target:
            target_sl_pct = 0.04  # %4 normal SL
            vol_factor = min(1.5, max(0.3, target_sl_pct / sl_pct))
            risk_d *= vol_factor
        notional = risk_d / sl_pct
        margin = notional / 3.0
        if margin > cash: continue
        cash -= margin
        last_entry[key] = t["entry_ts"]
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


def main():
    print("=" * 90)
    print("v0.9 DD REDUCTION — ROI koru, DD dusur")
    print("=" * 90)

    print("\nTopluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)}\n")

    print(f"{'Senaryo':<55} {'sinyal':>7} {'final$':>10} {'yIllIk':>8} {'DD':>6} {'r-adj':>6}")
    print("-" * 100)

    scenarios = [
        # Baseline (v0.9)
        ("BASELINE risk%3 conf>=0.2",
         dict(risk_pct=0.030, conf_min=0.20)),

        # Tighter breakers
        ("Tighter breakers 3/6/9",
         dict(risk_pct=0.030, conf_min=0.20, daily_dd=0.03, weekly_dd=0.06, monthly_dd=0.09)),
        ("Tighter breakers 4/8/12",
         dict(risk_pct=0.030, conf_min=0.20, daily_dd=0.04, weekly_dd=0.08, monthly_dd=0.12)),

        # Equity protection
        ("Equity protect -30 (yari risk)",
         dict(risk_pct=0.030, conf_min=0.20, equity_protect_30=True)),
        ("Equity protect -50 (hard stop)",
         dict(risk_pct=0.030, conf_min=0.20, equity_protect_50=True)),
        ("Equity protect -30 + -50",
         dict(risk_pct=0.030, conf_min=0.20, equity_protect_30=True, equity_protect_50=True)),

        # Cool-down on consecutive losses
        ("3 ardisik kayip -> 5 gun dur",
         dict(risk_pct=0.030, conf_min=0.20, consecutive_loss_n=3, consecutive_loss_pause=5)),
        ("4 ardisik kayip -> 7 gun dur",
         dict(risk_pct=0.030, conf_min=0.20, consecutive_loss_n=4, consecutive_loss_pause=7)),

        # Vol-target
        ("Vol-target sizing",
         dict(risk_pct=0.030, conf_min=0.20, vol_target=True)),

        # Concurrent reduction
        ("max_concurrent 5 (8'den)",
         dict(risk_pct=0.030, conf_min=0.20, max_concurrent=5)),

        # COMBO
        ("COMBO: -30 protect + 3-loss cool + vol-target",
         dict(risk_pct=0.030, conf_min=0.20, equity_protect_30=True,
              consecutive_loss_n=3, consecutive_loss_pause=5, vol_target=True)),
        ("COMBO: 4/8/12 + -30 protect + 3-loss + vol-target + max5",
         dict(risk_pct=0.030, conf_min=0.20, daily_dd=0.04, weekly_dd=0.08, monthly_dd=0.12,
              equity_protect_30=True, consecutive_loss_n=3, consecutive_loss_pause=5,
              vol_target=True, max_concurrent=5)),

        # Risk reduce
        ("risk %2.5 + -30 protect",
         dict(risk_pct=0.025, conf_min=0.20, equity_protect_30=True)),
        ("risk %2.5 + COMBO",
         dict(risk_pct=0.025, conf_min=0.20, daily_dd=0.04, weekly_dd=0.08, monthly_dd=0.12,
              equity_protect_30=True, consecutive_loss_n=3, vol_target=True)),

        # Yeni varyasyonlar — 3-loss cool-down ile combo
        ("3-loss + -30 protect",
         dict(risk_pct=0.030, conf_min=0.20, consecutive_loss_n=3, consecutive_loss_pause=5,
              equity_protect_30=True)),
        ("3-loss + -40 protect (yari risk)",
         dict(risk_pct=0.030, conf_min=0.20, consecutive_loss_n=3, consecutive_loss_pause=5,
              equity_protect_30=True, equity_protect_50=False)),
        ("3-loss + 2 loss daha (5 daha kati)",
         dict(risk_pct=0.030, conf_min=0.20, consecutive_loss_n=2, consecutive_loss_pause=7)),
        ("3-loss + tighter breakers 4/8/12",
         dict(risk_pct=0.030, conf_min=0.20, consecutive_loss_n=3, consecutive_loss_pause=5,
              daily_dd=0.04, weekly_dd=0.08, monthly_dd=0.12)),
        ("3-loss + risk %2.5",
         dict(risk_pct=0.025, conf_min=0.20, consecutive_loss_n=3, consecutive_loss_pause=5)),
        ("3-loss + risk %2.0",
         dict(risk_pct=0.020, conf_min=0.20, consecutive_loss_n=3, consecutive_loss_pause=5)),
        ("3-loss + max_concurrent 6",
         dict(risk_pct=0.030, conf_min=0.20, consecutive_loss_n=3, consecutive_loss_pause=5,
              max_concurrent=6)),
        ("3-loss + cooldown 7day same-sym",
         dict(risk_pct=0.030, conf_min=0.20, consecutive_loss_n=3, consecutive_loss_pause=5,
              cooldown_days=7)),
    ]

    best_balance = None
    for name, kwargs in scenarios:
        r = replay_protected(all_trades, **kwargs)
        if r is None: continue
        ann = ((r["final"]/10000)**(1/5)-1)*100
        ra = ann / abs(r["max_dd"]*100) if r["max_dd"] else 0
        print(f"{name:<55} {r['trades']:>7} {r['final']:>10,.0f} {ann:>+7.2f}% {r['max_dd']*100:>+5.0f}% {ra:>5.2f}")
        # Best balance: yillik >= 40 AND DD >= -60
        if ann >= 40 and r["max_dd"] >= -0.60:
            if best_balance is None or ann > best_balance[1]:
                best_balance = (name, ann, r, kwargs)

    if best_balance:
        print(f"\n# BEST BALANCE (yillik >=40% AND DD >=-60%): {best_balance[0]}")
        print(f"  yIllIk {best_balance[1]:+.2f}%  DD {best_balance[2]['max_dd']*100:+.1f}%")
        print(f"  $10K -> 5y -> ${best_balance[2]['final']:,.0f}")


if __name__ == "__main__":
    main()
