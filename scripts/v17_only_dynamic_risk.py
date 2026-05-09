"""v1.7 SADECE dynamic risk testi — exit logic'i v1 ile ayni.

Onceki test'te 'smart exit' simulasyonum yanlIstI (original R zaten trailed).
Burada sadece DYNAMIC RISK degisikligini ayri test edelim:
  conf < 0.32  -> %1.0
  conf 0.32-0.42 -> %1.5
  conf 0.42-0.52 -> %2.0
  conf 0.52-0.58 -> %3.0
  conf >= 0.58 -> %4.0

Hipotez: yuksek conf trade'lere daha cok bas, dusuk conf'a az bas.
Eger expected R yuksek conf'da gercekten yuksekse, bu net pozitif olmali.
"""
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


def conf_to_risk(conf: float) -> float:
    """v1.8 — agresif tier (kullanici istegiyle %1-%8)"""
    if conf < 0.32: return 0.010   # %1
    if conf < 0.42: return 0.020   # %2
    if conf < 0.52: return 0.040   # %4
    if conf < 0.58: return 0.060   # %6
    return 0.080                   # %8 (yuksek conf — bas!)


def replay_dynamic_risk(trades, fund_annual=0.10, max_concurrent=5):
    """v1 ayni exit, ama dynamic risk."""
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
        cd = t["entry_ts"].date()
        cw = t["entry_ts"].isocalendar()[1]
        cm = t["entry_ts"].month
        if cd != last_d: daily_anchor = equity; last_d = cd
        if cw != last_w: weekly_anchor = equity; last_w = cw
        if cm != last_m: monthly_anchor = equity; last_m = cm
        if blocked_until and t["entry_ts"] < blocked_until: continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= 0.05:
            blocked_until = t["entry_ts"] + timedelta(days=1); continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= 0.10:
            blocked_until = t["entry_ts"] + timedelta(days=7); continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= 0.15:
            blocked_until = t["entry_ts"] + timedelta(days=30); continue
        if len(open_pos) >= max_concurrent: continue

        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0: continue

        # DYNAMIC RISK — tek degisiklik
        risk_pct = conf_to_risk(t["conf"])
        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        margin = notional / t["lev"]
        if margin > cash: continue
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
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd

    win = sum(1 for x in Rs if x > 0) / len(Rs) if Rs else 0
    return {"final": equity, "max_dd": max_dd, "trades": len(Rs), "wr": win}


def main():
    print("Trade'leri topluyor...")
    all_trades = _gather()
    print(f"Toplam {len(all_trades)} sinyal\n")
    if not all_trades:
        return

    # ONEMLI: Conf bazinda WR ve avg R analiz
    print("=" * 80)
    print("CONFIDENCE BAZINDA TRADE PERFORMANSI (sample analiz)")
    print("=" * 80)

    tiers = [
        ("0.00-0.32 (lev 1x, %1 risk)", lambda c: c < 0.32),
        ("0.32-0.42 (lev 2x, %2)",       lambda c: 0.32 <= c < 0.42),
        ("0.42-0.52 (lev 3x, %4)",       lambda c: 0.42 <= c < 0.52),
        ("0.52-0.58 (lev 4x, %6)",       lambda c: 0.52 <= c < 0.58),
        ("0.58+    (lev 5x, %8)",        lambda c: c >= 0.58),
    ]
    print(f"{'Tier':<35} {'sayI':>5} {'wins':>5} {'WR':>6} {'avg R':>7} {'sum R':>7}")
    for label, fn in tiers:
        ts = [t for t in all_trades if fn(t["conf"])]
        if not ts:
            print(f"{label:<35} {'0':>5}")
            continue
        wins = sum(1 for t in ts if t["R"] > 0)
        wr = wins/len(ts)
        avg_r = np.mean([t["R"] for t in ts])
        sum_r = sum(t["R"] for t in ts)
        print(f"{label:<35} {len(ts):>5} {wins:>5} {wr*100:>5.0f}% {avg_r:>+7.2f} {sum_r:>+7.1f}")

    print()
    print("=" * 80)
    print("DYNAMIC RISK vs FIXED %2 (5y tek senaryo)")
    print("=" * 80)
    r1 = replay(all_trades, version="v1")
    rd = replay_dynamic_risk(all_trades)
    ret1 = (r1["final"]/10000-1)*100
    retd = (rd["final"]/10000-1)*100
    print(f"v1 (sabit %2)   : ${r1['final']:,.0f} ({ret1:+.1f}%) DD {r1['max_dd']*100:+.1f}% WR {r1['wr']*100:.0f}%")
    print(f"v1+dyn (1-4%)   : ${rd['final']:,.0f} ({retd:+.1f}%) DD {rd['max_dd']*100:+.1f}% WR {rd['wr']*100:.0f}%")
    print(f"FARK            : {retd-ret1:+.1f}pp")

    # 3y rolling
    print()
    print("=" * 80)
    print("ROLLING 3-YIL: dynamic risk vs sabit")
    print("=" * 80)
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows_3y = []
    cur = start
    while cur + pd.Timedelta(days=3*365) <= end:
        windows_3y.append((cur, cur + pd.Timedelta(days=3*365)))
        cur = cur + pd.Timedelta(days=30)

    v1_total = vd_total = 0.0
    v1_wins = vd_wins = 0
    v1_dd = vd_dd = 0.0
    n = 0
    for ws, we in windows_3y:
        wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
        if len(wt) < 10: continue
        r1 = replay(wt, version="v1")
        rd = replay_dynamic_risk(wt)
        if r1 is None or rd is None: continue
        ret1 = (r1["final"]/10000-1)*100
        retd = (rd["final"]/10000-1)*100
        if retd > ret1: vd_wins += 1
        else: v1_wins += 1
        v1_total += ret1
        vd_total += retd
        v1_dd += r1["max_dd"]
        vd_dd += rd["max_dd"]
        n += 1

    print(f"  {n} pencere")
    print(f"  v1 (sabit)   kazandi: {v1_wins} ({100*v1_wins/n:.0f}%)")
    print(f"  v1+dyn       kazandi: {vd_wins} ({100*vd_wins/n:.0f}%)")
    print(f"  v1 ortalama 3y getiri:    {v1_total/n:+.2f}%")
    print(f"  v1+dyn ortalama 3y getiri: {vd_total/n:+.2f}%")
    print(f"  v1 ortalama maxDD:    {v1_dd*100/n:+.1f}%")
    print(f"  v1+dyn ortalama maxDD: {vd_dd*100/n:+.1f}%")
    if vd_total > v1_total:
        print(f"\n  KAZANAN: v1+dyn ({(vd_total-v1_total)/n:+.1f}pp ortalama)")
    else:
        print(f"\n  KAZANAN: v1 (sabit) ({(v1_total-vd_total)/n:+.1f}pp ortalama)")


if __name__ == "__main__":
    main()
