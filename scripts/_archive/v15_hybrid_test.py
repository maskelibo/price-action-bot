"""v1.5 hybrid — sadece zararsiz fix'leri al.

v1 cok agresif, v2 cok kisitli. v1.5 ortayi bul:
  + max_notional_pct %50 (BNB hata onler, getiri kaybi yok)
  + 200-EMA conflict skip (BEAR icin mantikli)
  + kaufman_er_min 0.20 (chop koru)
  - confidence_min 0.42 ATILDI (cok kesiyor)
  - cooldown ATILDI (genel zararli)
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

from datetime import timedelta
from scripts.bot_v2_multi_window import _gather


def replay_v15(trades, base_risk_pct=0.02, fund_annual=0.10, max_concurrent=5):
    """v1.5 hybrid replay."""
    if not trades:
        return None
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    open_pos = []
    eq_curve = [10_000.0]
    Rs = []
    fund_d = fund_annual / 365

    daily_anchor = weekly_anchor = monthly_anchor = 10_000.0
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    blocked_until = None

    skip_ema200 = skip_er = skip_notional = 0

    def close_due(now):
        nonlocal cash, equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                f = p["margin"] * p["lev"] * fund_d * holding
                pnl = p["risk"] * p["R"] - f
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                Rs.append(p["R"])
                eq_curve.append(equity)
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])

        # v1.5 FIX 1: 200-EMA conflict
        if t["side"] == "short" and t.get("close_at_entry", 0) > t.get("ema200_at_entry", 0):
            skip_ema200 += 1
            continue
        if t["side"] == "long" and t.get("close_at_entry", 0) < t.get("ema200_at_entry", 1e9):
            skip_ema200 += 1
            continue
        # v1.5 FIX 2: Kaufman ER min 0.20 (v2'de 0.25, v1.5'te gevsek)
        if t["kaufman_er"] < 0.20:
            skip_er += 1
            continue

        cd = t["entry_ts"].date()
        cw = t["entry_ts"].isocalendar()[1]
        cm = t["entry_ts"].month
        if cd != last_d:
            daily_anchor = equity; last_d = cd
        if cw != last_w:
            weekly_anchor = equity; last_w = cw
        if cm != last_m:
            monthly_anchor = equity; last_m = cm
        if blocked_until and t["entry_ts"] < blocked_until:
            continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= 0.05:
            blocked_until = t["entry_ts"] + timedelta(days=1); continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= 0.10:
            blocked_until = t["entry_ts"] + timedelta(days=7); continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= 0.15:
            blocked_until = t["entry_ts"] + timedelta(days=30); continue
        if len(open_pos) >= max_concurrent:
            continue

        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue
        risk_d = equity * base_risk_pct
        notional = risk_d / sl_pct
        margin = notional / t["lev"]

        # v1.5 FIX 3: max notional %50 cap
        max_notional = equity * 0.50
        if notional > max_notional:
            notional = max_notional
            margin = notional / t["lev"]
            risk_d = notional * sl_pct
            skip_notional += 1

        if margin > cash:
            continue
        cash -= margin
        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "margin": margin, "risk": risk_d, "R": t["R"], "lev": t["lev"],
        })

    for p in open_pos:
        holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
        f = p["margin"] * p["lev"] * fund_d * holding
        cash += p["margin"] + p["risk"] * p["R"] - f
        equity = cash
        Rs.append(p["R"])
        eq_curve.append(equity)

    peak = eq_curve[0]
    max_dd = 0
    for v in eq_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd

    win = sum(1 for x in Rs if x > 0) / len(Rs) if Rs else 0
    return {
        "final": equity, "max_dd": max_dd, "trades": len(Rs), "wr": win,
        "skip_ema200": skip_ema200, "skip_er": skip_er, "skip_notional": skip_notional,
    }


def main():
    print("Trade'leri topluyor (5y)...")
    all_trades = _gather()
    print(f"Toplam {len(all_trades)} sinyal\n")

    if not all_trades:
        return

    # Rolling 12-month windows
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    print(f"Veri araligi: {start.date()} -> {end.date()}\n")

    windows = []
    cur = start
    while cur + pd.Timedelta(days=365) <= end:
        win_end = cur + pd.Timedelta(days=365)
        windows.append((cur, win_end))
        cur = cur + pd.Timedelta(days=30)

    # Replay v1, v2, v15 her pencerede
    from scripts.bot_v2_multi_window import replay as replay_v12

    print(f"{'Pencere':<26} {'v1 ret%':>8} {'v2 ret%':>8} {'v1.5 ret%':>9} {'kazanan':<8}")
    print("-" * 80)

    v1_wins = v2_wins = v15_wins = 0
    v1_total = v2_total = v15_total = 0.0
    v1_dd = v2_dd = v15_dd = 0.0
    v1_wr = v2_wr = v15_wr = 0.0
    n = 0

    for ws, we in windows:
        wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
        if len(wt) < 5:
            continue
        r1 = replay_v12(wt, version="v1")
        r2 = replay_v12(wt, version="v2")
        r15 = replay_v15(wt)
        if r1 is None or r2 is None or r15 is None:
            continue

        ret1 = (r1["final"] / 10_000 - 1) * 100
        ret2 = (r2["final"] / 10_000 - 1) * 100
        ret15 = (r15["final"] / 10_000 - 1) * 100

        best = max(ret1, ret2, ret15)
        if best == ret1:
            winner = "v1"; v1_wins += 1
        elif best == ret2:
            winner = "v2"; v2_wins += 1
        else:
            winner = "v1.5"; v15_wins += 1

        v1_total += ret1
        v2_total += ret2
        v15_total += ret15
        v1_dd += r1["max_dd"]
        v2_dd += r2["max_dd"]
        v15_dd += r15["max_dd"]
        v1_wr += r1["wr"]
        v2_wr += r2["wr"]
        v15_wr += r15["wr"]
        n += 1

        label = f"{ws.date()}->{we.date()}"
        print(f"{label:<26} {ret1:>+7.1f}% {ret2:>+7.1f}% {ret15:>+8.1f}%   {winner}")

    print()
    print("=" * 80)
    print(f"3'lu KARSILASTIRMA — {n} pencere")
    print("=" * 80)
    print(f"  v1 (orig)  kazandi: {v1_wins} ({100*v1_wins/n:.0f}%)")
    print(f"  v2 (5fix)  kazandi: {v2_wins} ({100*v2_wins/n:.0f}%)")
    print(f"  v1.5 (3fix) kazandi: {v15_wins} ({100*v15_wins/n:.0f}%)")
    print()
    print(f"Ortalama 12-ay getiri:")
    print(f"  v1   : {v1_total/n:+.2f}%")
    print(f"  v2   : {v2_total/n:+.2f}%")
    print(f"  v1.5 : {v15_total/n:+.2f}%")
    print()
    print(f"Ortalama maxDD:")
    print(f"  v1   : {v1_dd*100/n:+.1f}%")
    print(f"  v2   : {v2_dd*100/n:+.1f}%")
    print(f"  v1.5 : {v15_dd*100/n:+.1f}%")
    print()
    print(f"Ortalama WR:")
    print(f"  v1   : {v1_wr*100/n:.1f}%")
    print(f"  v2   : {v2_wr*100/n:.1f}%")
    print(f"  v1.5 : {v15_wr*100/n:.1f}%")
    print()
    print(f"Risk-adjusted (return / |DD|):")
    print(f"  v1   : {(v1_total/n) / abs(v1_dd*100/n):.2f}")
    print(f"  v2   : {(v2_total/n) / abs(v2_dd*100/n):.2f}")
    print(f"  v1.5 : {(v15_total/n) / abs(v15_dd*100/n):.2f}")


if __name__ == "__main__":
    main()
