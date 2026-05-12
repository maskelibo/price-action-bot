"""v0.8 Autonomous research — multi-target engine + tum stratejilerin taranmasi.

Hedefler:
  1. Tum 25 stratejiyi yeni multi-target engine'de yeniden test
  2. En iyi 7 stratejiyi sec
  3. Top 3/5/7 portfoy denemesi
  4. Best config 3y rolling stress test
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


SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
           "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


ALL_STRATS = [
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
    ("pin_bar_round_numbers", "PinBarRoundNumbersStrategy"),
    ("obv_engulfing_confluence", "OBVEngulfingConfluenceStrategy"),
    ("morning_evening_star", "MorningEveningStarStrategy"),
    ("equal_highs_sweep", "EqualHighsSweepStrategy"),
    ("three_methods", "ThreeMethodsStrategy"),
    ("three_black_crows", "ThreeBlackCrowsStrategy"),
    ("three_white_soldiers", "ThreeWhiteSoldiersStrategy"),
    ("ii_breakout", "IIBreakoutStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("pin_bar_htf_sr", "PinBarHtfSrStrategy"),
    ("ob_mitigation_strict", "OBMitigationStrictStrategy"),
    ("smc_orderblock", "SMCOrderBlockStrategy"),
    ("brooks_h2_l2", "BrooksH2L2Strategy"),
    ("crows_buying_climax", "CrowsBuyingClimaxStrategy"),
    ("vsa_climax_test", "VsaClimaxTestStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("naked_poc_mr", "NakedPocMrStrategy"),
    ("donchian_breakout", "DonchianBreakoutStrategy"),
    ("wyckoff_phase_d", "WyckoffPhaseDStrategy"),
    ("wyckoff_spring_vsa", "WyckoffSpringVsaStrategy"),
    ("failed_bo_bos_reclaim", "FailedBoBosReclaimStrategy"),
    ("liquidation_fade", "LiquidationFadeStrategy"),
]


def _gather(module_name, class_name):
    from price_action.backtest.engine import BacktestEngine
    from scripts.run_real_backtest import _load_symbol_ohlcv
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn: return []
        s = cls(manifest_fn())
    except Exception:
        return []
    out = []
    for sym in SYMBOLS:
        try:
            df = _load_symbol_ohlcv(sym, tf="1d")
            if df is None or df.empty: continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym; df["venue"] = "binance"; df["timeframe"] = "1d"
            def prov(*a, **k): return df.copy()
            e = BacktestEngine(risk_officer=None, store_load=None)
            r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(),
                     end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d",
                     initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010},
                     slippage_bps=5.0, ohlcv_provider=prov)
            for _, t in r.trades.iterrows():
                conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
                ts_e = pd.Timestamp(t["entry_ts"])
                if ts_e.tzinfo is None: ts_e = ts_e.tz_localize("UTC")
                ts_x = pd.Timestamp(t["exit_ts"])
                if ts_x.tzinfo is None: ts_x = ts_x.tz_localize("UTC")
                out.append({
                    "entry_ts": ts_e, "exit_ts": ts_x,
                    "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]), "symbol": sym, "side": str(t["side"]),
                    "conf": conf, "strategy": module_name,
                })
        except Exception:
            continue
    return out


def replay(trades, risk_pct=0.02, max_concurrent=8, cooldown_days=3):
    if not trades: return None
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0; cash = 10_000.0
    open_pos = []; eq_curve = [10_000.0]; Rs = []
    daily_anchor = weekly_anchor = monthly_anchor = 10_000.0
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    blocked_until = None
    last_entry: dict[tuple, pd.Timestamp] = {}

    def close_due(now):
        nonlocal cash, equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                Rs.append(p["R"])
                eq_curve.append(equity)
            else: still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])
        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).days < cooldown_days: continue
        cd = t["entry_ts"].date(); cw = t["entry_ts"].isocalendar()[1]; cm = t["entry_ts"].month
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
        risk_d = equity * risk_pct
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

    peak = eq_curve[0]; max_dd = 0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak)/peak
        if dd < max_dd: max_dd = dd
    win = sum(1 for x in Rs if x > 0)/len(Rs) if Rs else 0
    avg_r = np.mean(Rs) if Rs else 0
    return {"final": equity, "max_dd": max_dd, "trades": len(Rs), "wr": win, "avg_r": avg_r}


def main():
    print("=" * 90)
    print("v0.8 AUTONOMOUS RESEARCH — multi-target engine taraniyor")
    print("=" * 90)

    print(f"\n{'Strateji':<32} {'sinyal':>7} {'final$':>10} {'yIllIk':>8} {'maxDD':>7} {'WR':>5} {'avgR':>6}")
    print("-" * 80)

    sresults = {}
    for module_name, class_name in ALL_STRATS:
        if module_name in sresults: continue
        trs = _gather(module_name, class_name)
        if not trs or len(trs) < 10:
            print(f"{module_name:<32} {'<10':>7}")
            continue
        r = replay(trs, risk_pct=0.02)
        if r is None: continue
        ann = ((r["final"]/10000)**(1/5)-1)*100
        print(f"{module_name:<32} {len(trs):>7} {r['final']:>10,.0f} {ann:>+7.2f}% {r['max_dd']*100:>+6.1f}% {r['wr']*100:>4.0f}% {r['avg_r']:>+5.2f}")
        sresults[module_name] = {"trades": trs, "ann": ann, "dd": r["max_dd"], "wr": r["wr"], "n": len(trs)}

    print("\n# EN IYI 10 STRATEJI")
    sorted_strats = sorted(sresults.items(), key=lambda x: x[1]["ann"], reverse=True)[:10]
    for i, (name, info) in enumerate(sorted_strats, 1):
        print(f"  {i:>2}. {name:<32} yIllIk {info['ann']:>+6.1f}%  WR {info['wr']*100:.0f}%  n={info['n']}")

    # Portfoy denemeleri (top 3 / 5 / 7)
    def make_combined(top_n):
        out = []
        for name, info in sorted_strats[:top_n]:
            out.extend(info["trades"])
        out.sort(key=lambda x: x["entry_ts"])
        return out

    print("\n# PORTFOY KOMBINASYONLARI")
    print(f"{'Senaryo':<28} {'sinyal':>7} {'final$':>10} {'yIllIk':>8} {'DD':>6} {'WR':>4} {'r-adj':>6}")
    print("-" * 75)
    scenarios = [
        ("Top 3 sabit %1", make_combined(3), 0.010),
        ("Top 3 sabit %1.5", make_combined(3), 0.015),
        ("Top 3 sabit %2", make_combined(3), 0.020),
        ("Top 5 sabit %1", make_combined(5), 0.010),
        ("Top 5 sabit %1.5", make_combined(5), 0.015),
        ("Top 5 sabit %2", make_combined(5), 0.020),
        ("Top 7 sabit %1", make_combined(7), 0.010),
        ("Top 7 sabit %1.5", make_combined(7), 0.015),
        ("Top 7 sabit %2", make_combined(7), 0.020),
        ("Top 10 sabit %1", make_combined(10), 0.010),
        ("Top 10 sabit %1.5", make_combined(10), 0.015),
    ]
    best = None
    best_ann = None
    for name, ts, risk in scenarios:
        r = replay(ts, risk_pct=risk)
        if r is None: continue
        ann = ((r["final"]/10000)**(1/5)-1)*100
        ra = ann / abs(r["max_dd"]*100) if r["max_dd"] else 0
        print(f"{name:<28} {r['trades']:>7} {r['final']:>10,.0f} {ann:>+7.2f}% {r['max_dd']*100:>+5.0f}% {r['wr']*100:>3.0f}% {ra:>5.2f}")
        if best is None or ra > best[1]:
            best = (name, ra, ann, r, ts, risk)
        if best_ann is None or ann > best_ann[1]:
            best_ann = (name, ann, r, ts, risk)

    if best:
        print(f"\n# EN IYI RISK-ADJUSTED: {best[0]}")
        print(f"  Yillik: {best[2]:+.2f}% | DD: {best[3]['max_dd']*100:+.1f}% | risk-adj: {best[1]:.2f}")
        print(f"  $10K -> 5y -> ${best[3]['final']:,.0f}")
    if best_ann:
        print(f"\n# EN YUKSEK YILLIK: {best_ann[0]}")
        print(f"  Yillik: {best_ann[1]:+.2f}% | DD: {best_ann[2]['max_dd']*100:+.1f}%")
        print(f"  $10K -> 5y -> ${best_ann[2]['final']:,.0f}")
        if best_ann[1] >= 50:
            print(f"  ⭐ HEDEF (%50 yillik) ULASILDI!")


if __name__ == "__main__":
    main()
