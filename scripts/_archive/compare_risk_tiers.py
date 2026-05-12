"""3 risk tier karsilastirma — 1-4, 1-6, 1-8."""
from __future__ import annotations

import io
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

from scripts.bot_v2_multi_window import _gather, replay


def make_replay(tier_fn, fund_annual=0.10, max_concurrent=5):
    def _replay(trades):
        if not trades: return None
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
        def close_due(now):
            nonlocal cash, equity
            still = []
            for p in open_pos:
                if p["exit_ts"] <= now:
                    holding = (p["exit_ts"] - p["entry_ts"]).total_seconds()/86400
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
            cd = t["entry_ts"].date()
            cw = t["entry_ts"].isocalendar()[1]
            cm = t["entry_ts"].month
            if cd != last_d: daily_anchor = equity; last_d = cd
            if cw != last_w: weekly_anchor = equity; last_w = cw
            if cm != last_m: monthly_anchor = equity; last_m = cm
            if blocked_until and t["entry_ts"] < blocked_until: continue
            if (daily_anchor - equity)/max(daily_anchor,1) >= 0.05:
                blocked_until = t["entry_ts"] + timedelta(days=1); continue
            if (weekly_anchor - equity)/max(weekly_anchor,1) >= 0.10:
                blocked_until = t["entry_ts"] + timedelta(days=7); continue
            if (monthly_anchor - equity)/max(monthly_anchor,1) >= 0.15:
                blocked_until = t["entry_ts"] + timedelta(days=30); continue
            if len(open_pos) >= max_concurrent: continue
            sl_pct = abs(t["entry_price"] - t["initial_sl"])/t["entry_price"]
            if sl_pct <= 0: continue
            risk_pct = tier_fn(t["conf"])
            risk_d = equity * risk_pct
            notional = risk_d / sl_pct
            margin = notional / t["lev"]
            if margin > cash: continue
            cash -= margin
            open_pos.append({"entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
                             "margin": margin, "risk": risk_d, "R": t["R"], "lev": t["lev"]})
        for p in open_pos:
            holding = (p["exit_ts"] - p["entry_ts"]).total_seconds()/86400
            f = p["margin"] * p["lev"] * fund_d * holding
            cash += p["margin"] + p["risk"] * p["R"] - f
            equity = cash
            Rs.append(p["R"])
            eq_curve.append(equity)
        peak = eq_curve[0]
        max_dd = 0
        for v in eq_curve:
            if v > peak: peak = v
            dd = (v - peak)/peak
            if dd < max_dd: max_dd = dd
        win = sum(1 for x in Rs if x > 0)/len(Rs) if Rs else 0
        return {"final": equity, "max_dd": max_dd, "trades": len(Rs), "wr": win}
    return _replay


def t_static(c): return 0.02
def t_1_4(c):
    if c < 0.32: return 0.010
    if c < 0.42: return 0.015
    if c < 0.52: return 0.020
    if c < 0.58: return 0.030
    return 0.040
def t_1_6(c):
    if c < 0.32: return 0.010
    if c < 0.42: return 0.020
    if c < 0.52: return 0.030
    if c < 0.58: return 0.045
    return 0.060
def t_1_8(c):
    if c < 0.32: return 0.010
    if c < 0.42: return 0.020
    if c < 0.52: return 0.040
    if c < 0.58: return 0.060
    return 0.080


def main():
    print("Trade'leri topluyor...")
    all_trades = _gather()
    print(f"Toplam {len(all_trades)} sinyal\n")
    if not all_trades:
        return

    tiers = [
        ("v1 sabit %2",     make_replay(t_static)),
        ("v1+dyn 1-4%",     make_replay(t_1_4)),
        ("v1+dyn 1-6%",     make_replay(t_1_6)),
        ("v1+dyn 1-8%",     make_replay(t_1_8)),
    ]

    # 5y tek
    print("=" * 80)
    print("5Y TEK SENARYO")
    print("=" * 80)
    print(f"{'Tier':<22} {'Final$':>10} {'Toplam %':>10} {'YIllIk %':>10} {'maxDD':>7} {'WR%':>5}")
    print("-" * 75)
    for name, fn in tiers:
        r = fn(all_trades)
        if r is None: continue
        ret = (r["final"]/10000-1)*100
        ann = ((r["final"]/10000)**(1/5)-1)*100
        print(f"{name:<22} {r['final']:>10,.0f} {ret:>+9.1f}% {ann:>+9.2f}% {r['max_dd']*100:>+6.1f}% {r['wr']*100:>4.0f}%")

    # 3y rolling
    print()
    print("=" * 80)
    print("3-YIL ROLLING (23 pencere)")
    print("=" * 80)
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3*365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3*365)))
        cur = cur + pd.Timedelta(days=30)

    print(f"{'Tier':<22} {'ort 3y%':>10} {'ort yIllIk':>10} {'ort DD':>8} {'risk-adj':>9}")
    print("-" * 70)
    for name, fn in tiers:
        rets = []
        anns = []
        dds = []
        for ws, we in windows:
            wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
            if len(wt) < 10: continue
            r = fn(wt)
            if r is None: continue
            rets.append((r["final"]/10000-1)*100)
            anns.append(((r["final"]/10000)**(1/3)-1)*100)
            dds.append(r["max_dd"]*100)
        avg_ret = np.mean(rets)
        avg_ann = np.mean(anns)
        avg_dd = np.mean(dds)
        risk_adj = avg_ann / abs(avg_dd) if avg_dd else 0
        print(f"{name:<22} {avg_ret:>+9.1f}% {avg_ann:>+9.1f}% {avg_dd:>+7.1f}% {risk_adj:>9.2f}")

    # 1y rolling — kisa pencere kontrolu
    print()
    print("=" * 80)
    print("12-AY ROLLING (48 pencere)")
    print("=" * 80)
    windows_1y = []
    cur = start
    while cur + pd.Timedelta(days=365) <= end:
        windows_1y.append((cur, cur + pd.Timedelta(days=365)))
        cur = cur + pd.Timedelta(days=30)
    print(f"{'Tier':<22} {'ort yIllIk':>10} {'ort DD':>8} {'risk-adj':>9}")
    print("-" * 60)
    for name, fn in tiers:
        rets = []
        dds = []
        for ws, we in windows_1y:
            wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
            if len(wt) < 5: continue
            r = fn(wt)
            if r is None: continue
            rets.append((r["final"]/10000-1)*100)
            dds.append(r["max_dd"]*100)
        avg_ret = np.mean(rets)
        avg_dd = np.mean(dds)
        risk_adj = avg_ret / abs(avg_dd) if avg_dd else 0
        print(f"{name:<22} {avg_ret:>+9.1f}% {avg_dd:>+7.1f}% {risk_adj:>9.2f}")


if __name__ == "__main__":
    main()
