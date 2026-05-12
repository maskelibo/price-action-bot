"""v1.7 — Dynamic risk + Smart trailing exit.

ESKI v1:
  - Risk per trade: SABIT %2
  - Exit: 1R'da %50 kapan, kalan trail

YENI v1.7:
  1. DYNAMIC RISK (confidence-based):
     conf < 0.32  -> %1.0  (defensive, dusuk guven)
     conf 0.32-0.42 -> %1.5
     conf 0.42-0.52 -> %2.0  (default)
     conf 0.52-0.58 -> %3.0  (yuksek guven)
     conf >= 0.58 -> %4.0  (mukemmel sinyal — bas)

  2. SMART EXIT (3-asamali, runner agirlikli):
     1R   -> sadece %30 kapan (yarisi degil, ucte bir)
     2R   -> %30 daha kapan (toplam %60 lock)
     %40 RUNNER -> sIkI trailing
       peak - 2×ATR (eski 3×ATR yerine)
       yani fiyat dustugu anda kapanir, peak'e yakin cikis

User dedi: "hizli giden trendden inmemek lazim, belli kisimda yarisi kapanir
TP alirsin, sonra baya artinca dusmeye yakin kapanir"
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
    """Confidence -> risk_per_trade (% of equity)."""
    if conf < 0.32: return 0.010   # %1
    if conf < 0.42: return 0.015   # %1.5
    if conf < 0.52: return 0.020   # %2
    if conf < 0.58: return 0.030   # %3
    return 0.040                   # %4


def replay_v17(trades, fund_annual=0.10, max_concurrent=5):
    """v1.7 replay — dynamic risk + smart exit.

    Trade'in R degerini 3 segmente bol:
      seg1: %30 @ 1R = +0.3R
      seg2: %30 @ 2R = +0.6R
      seg3: %40 trailing peak'e yakin

    Eski v1: tek R sonucu = realized_r_multiple
    Yeni v1.7: simulate exit_R based on trade outcome:
      Eger original R < 1: kayip senaryo, tam R uygulanir (trade SL hit oldu)
      Eger 1 <= R < 2: 1R partial alir kalan R-0.7×original
      Eger R >= 2: 1R + 2R partials + runner peak~original*0.85
    """
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

    def _smart_R(orig_R):
        """Original R'yi smart exit'e gore ceviri."""
        if orig_R < 1.0:
            # Trade kaybetti veya 1R'a ulasamadi -> orijinal R
            return orig_R
        elif orig_R < 2.0:
            # 1R'a ulasti, %30 kapandi (+0.3R), kalan %70 trail ile geri dondu
            # Asli runner peak ~ orig_R, simdi cikis ~ orig_R * 0.85 (sIkI trail)
            return 0.30 * 1.0 + 0.70 * (orig_R * 0.85)
        else:
            # 2R+'ya ulasti
            seg1 = 0.30 * 1.0   # 1R'da %30
            seg2 = 0.30 * 2.0   # 2R'da %30
            # Runner: peak - 2×ATR. Eski R'nin %85'i tahmini.
            seg3 = 0.40 * (orig_R * 0.85)
            return seg1 + seg2 + seg3

    def close_due(now):
        nonlocal cash, equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                f = p["margin"] * p["lev"] * fund_d * holding
                # Smart exit R uygulanir
                smart_R = _smart_R(p["orig_R"])
                pnl = p["risk"] * smart_R * p["lev"] - f
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                Rs.append(smart_R)
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

        # DYNAMIC RISK (confidence-based) — v1.7 yenilik
        risk_pct = conf_to_risk(t["conf"])
        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        margin = notional / t["lev"]
        if margin > cash: continue
        cash -= margin
        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "margin": margin, "risk": risk_d, "orig_R": t["R"], "lev": t["lev"],
            "risk_pct": risk_pct,
        })

    for p in open_pos:
        holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
        f = p["margin"] * p["lev"] * fund_d * holding
        smart_R = _smart_R(p["orig_R"])
        cash += p["margin"] + p["risk"] * smart_R * p["lev"] - f
        equity = cash
        Rs.append(smart_R)
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
    print("Trade'leri topluyor (5y)...")
    all_trades = _gather()
    print(f"Toplam {len(all_trades)} sinyal\n")
    if not all_trades:
        return

    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]

    # Test 1: Tum 5y senaryo
    print("=" * 80)
    print("TEST 1: TUM 5y verisi tek senaryo")
    print("=" * 80)
    r1 = replay(all_trades, version="v1")
    r17 = replay_v17(all_trades)
    print(f"v1 (orig)    : ${r1['final']:,.0f} ({(r1['final']/10000-1)*100:+.1f}%) DD {r1['max_dd']*100:+.1f}% WR {r1['wr']*100:.0f}%")
    print(f"v1.7 (smart) : ${r17['final']:,.0f} ({(r17['final']/10000-1)*100:+.1f}%) DD {r17['max_dd']*100:+.1f}% WR {r17['wr']*100:.0f}%")
    delta = (r17["final"] - r1["final"]) / r1["final"] * 100
    print(f"FARK: {delta:+.1f}% (v1.7 vs v1)")

    # Test 2: Rolling 3-yil
    print()
    print("=" * 80)
    print("TEST 2: Rolling 3-YIL pencereler")
    print("=" * 80)

    windows_3y = []
    cur = start
    while cur + pd.Timedelta(days=3*365) <= end:
        windows_3y.append((cur, cur + pd.Timedelta(days=3*365)))
        cur = cur + pd.Timedelta(days=30)

    print(f"\n{len(windows_3y)} pencere\n")
    print(f"{'Pencere (3y)':<28} {'v1 ret':>9} {'v1.7 ret':>9} {'fark':>8} {'kazanan':<8}")
    print("-" * 75)

    v1_total = v17_total = 0.0
    v1_wins = v17_wins = 0
    n = 0
    for ws, we in windows_3y:
        wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
        if len(wt) < 10: continue
        r1 = replay(wt, version="v1")
        r17 = replay_v17(wt)
        if r1 is None or r17 is None: continue
        ret1 = (r1["final"]/10000 - 1) * 100
        ret17 = (r17["final"]/10000 - 1) * 100
        winner = "v1.7" if ret17 > ret1 else "v1"
        if winner == "v1.7": v17_wins += 1
        else: v1_wins += 1
        v1_total += ret1
        v17_total += ret17
        n += 1
        label = f"{ws.date()}->{we.date()}"
        print(f"{label:<28} {ret1:>+8.1f}% {ret17:>+8.1f}% {ret17-ret1:>+7.1f}%   {winner}")

    print()
    print(f"  v1   kazandi: {v1_wins}/{n}")
    print(f"  v1.7 kazandi: {v17_wins}/{n}")
    print(f"  v1   ortalama: {v1_total/n:+.2f}%")
    print(f"  v1.7 ortalama: {v17_total/n:+.2f}%")
    print(f"  Fark: {(v17_total-v1_total)/n:+.2f}pp")

    # Test 3: Rolling 12-ay (kisa pencere kontrolu)
    print()
    print("=" * 80)
    print("TEST 3: Rolling 12-AY pencereler (kontrol)")
    print("=" * 80)

    windows_1y = []
    cur = start
    while cur + pd.Timedelta(days=365) <= end:
        windows_1y.append((cur, cur + pd.Timedelta(days=365)))
        cur = cur + pd.Timedelta(days=30)

    v1_total = v17_total = 0.0
    v1_wins = v17_wins = 0
    n = 0
    for ws, we in windows_1y:
        wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
        if len(wt) < 5: continue
        r1 = replay(wt, version="v1")
        r17 = replay_v17(wt)
        if r1 is None or r17 is None: continue
        ret1 = (r1["final"]/10000 - 1) * 100
        ret17 = (r17["final"]/10000 - 1) * 100
        if ret17 > ret1: v17_wins += 1
        else: v1_wins += 1
        v1_total += ret1
        v17_total += ret17
        n += 1

    print(f"  {n} pencere")
    print(f"  v1   kazandi: {v1_wins} ({100*v1_wins/n:.0f}%)")
    print(f"  v1.7 kazandi: {v17_wins} ({100*v17_wins/n:.0f}%)")
    print(f"  v1   ort yillik: {v1_total/n:+.2f}%")
    print(f"  v1.7 ort yillik: {v17_total/n:+.2f}%")


if __name__ == "__main__":
    main()
