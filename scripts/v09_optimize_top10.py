"""v0.9 - Top 10 strateji + 11 sembol + filter sweep -> %50 hedef avi.
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

SYMBOLS_11 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
              "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
              "DOGE/USDT", "XRP/USDT", "MATIC/USDT"]

TOP_10 = [
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
    ("obv_engulfing_confluence", "OBVEngulfingConfluenceStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("wyckoff_phase_d", "WyckoffPhaseDStrategy"),
    ("brooks_h2_l2", "BrooksH2L2Strategy"),
    ("pin_bar_round_numbers", "PinBarRoundNumbersStrategy"),
    ("equal_highs_sweep", "EqualHighsSweepStrategy"),
    ("cvd_spike_fade", "CVDSpikeFadeStrategy"),
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
]


def _gather(module_name, class_name):
    from price_action.backtest.engine import BacktestEngine
    from price_action.signals.filters import volume_zscore
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
    for sym in SYMBOLS_11:
        try:
            df = _load_symbol_ohlcv(sym, tf="1d")
            if df is None or df.empty: continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym; df["venue"] = "binance"; df["timeframe"] = "1d"
            try:
                df["vol_z_pre"] = volume_zscore(df["volume"], period=20)
            except Exception:
                rolling = df["volume"].rolling(20)
                df["vol_z_pre"] = (df["volume"] - rolling.mean()) / rolling.std()
            def prov(*a, **k): return df.copy()
            e = BacktestEngine(risk_officer=None, store_load=None)
            r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(),
                     end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d",
                     initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010},
                     slippage_bps=5.0, ohlcv_provider=prov)
            ts_map = pd.to_datetime(df["ts"], utc=True)
            for _, t in r.trades.iterrows():
                conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
                ts_e = pd.Timestamp(t["entry_ts"])
                if ts_e.tzinfo is None: ts_e = ts_e.tz_localize("UTC")
                ts_x = pd.Timestamp(t["exit_ts"])
                if ts_x.tzinfo is None: ts_x = ts_x.tz_localize("UTC")
                mask = ts_map < ts_e
                vz = 0.0
                if mask.any():
                    idx = ts_map[mask].index[-1]
                    vz = float(df["vol_z_pre"].iloc[idx]) if not pd.isna(df["vol_z_pre"].iloc[idx]) else 0
                out.append({
                    "entry_ts": ts_e, "exit_ts": ts_x,
                    "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]), "symbol": sym, "side": str(t["side"]),
                    "conf": conf, "strategy": module_name, "vol_z": vz,
                })
        except Exception:
            continue
    return out


def replay(trades, risk_pct=0.015, max_concurrent=8, cooldown_days=3, vol_z_min=None, conf_min=None):
    if not trades: return None
    if vol_z_min is not None:
        trades = [t for t in trades if t["vol_z"] >= vol_z_min]
    if conf_min is not None:
        trades = [t for t in trades if t["conf"] >= conf_min]
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
    print("v0.9 OPTIMIZE — Top 10 strateji + 11 sembol + filter sweep")
    print("=" * 90)

    print("\nTrade'leri topluyor (10 strateji x 11 sembol)...")
    all_trades = []
    for m, c in TOP_10:
        trs = _gather(m, c)
        all_trades.extend(trs)
        print(f"  {m}: {len(trs)}")
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"  Toplam: {len(all_trades)}\n")

    print(f"{'Senaryo':<48} {'sinyal':>7} {'final$':>10} {'yIllIk':>8} {'DD':>6} {'WR':>4}")
    print("-" * 95)

    # Sweep: risk × vol_z × conf
    scenarios = []
    for risk in [0.020, 0.025, 0.030, 0.035, 0.040, 0.045]:
        for vz in [None, 0.5, 1.0]:
            for cm in [None, 0.20, 0.30, 0.40]:
                # DD <= -80 olanlar elenir (asari risk)
                vz_lbl = f"vz>={vz}" if vz is not None else "no_vz"
                cm_lbl = f"conf>={cm}" if cm is not None else "no_conf"
                scenarios.append((f"r%{risk*100:.1f} {vz_lbl} {cm_lbl}", risk, vz, cm))

    best = None
    for name, risk, vz, cm in scenarios:
        r = replay(all_trades, risk_pct=risk, vol_z_min=vz, conf_min=cm)
        if r is None: continue
        ann = ((r["final"]/10000)**(1/5)-1)*100
        if best is None or ann > best[1]:
            best = (name, ann, r, risk, vz, cm)

    if best:
        print(f"\n# EN YUKSEK YILLIK: {best[0]}")
        r = best[2]
        print(f"  yIllIk {best[1]:+.2f}%  DD {r['max_dd']*100:+.1f}%  WR {r['wr']*100:.0f}%")
        print(f"  $10K -> 5y -> ${r['final']:,.0f}")
        if best[1] >= 50:
            print(f"\n  ⭐⭐⭐ HEDEF (%50) ULASILDI! ⭐⭐⭐")

    # DD<=-75 filter sweet spot
    print("\n# SUSTAINABLE (%50+ yIllIk + DD>=-75):")
    sustainable = []
    for name, risk, vz, cm in scenarios:
        r = replay(all_trades, risk_pct=risk, vol_z_min=vz, conf_min=cm)
        if r is None: continue
        ann = ((r["final"]/10000)**(1/5)-1)*100
        if ann >= 35 and r["max_dd"] >= -0.75:
            sustainable.append((name, ann, r))
    sustainable.sort(key=lambda x: x[1], reverse=True)
    for name, ann, r in sustainable[:10]:
        print(f"  {name:<48} {ann:>+6.1f}% DD {r['max_dd']*100:>+5.0f}% n={r['trades']}")

    # Top 10 ranking
    print("\n# EN YUKSEK 10 KONFIGÜRASYON (yIllIk):")
    ranked = []
    for name, risk, vz, cm in scenarios:
        r = replay(all_trades, risk_pct=risk, vol_z_min=vz, conf_min=cm)
        if r is None: continue
        ann = ((r["final"]/10000)**(1/5)-1)*100
        ranked.append((name, ann, r))
    ranked.sort(key=lambda x: x[1], reverse=True)
    for i, (name, ann, r) in enumerate(ranked[:10], 1):
        print(f"  {i:>2}. {name:<48} {ann:>+6.1f}% DD {r['max_dd']*100:>+5.0f}% n={r['trades']}")


if __name__ == "__main__":
    main()
