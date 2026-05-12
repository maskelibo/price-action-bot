"""DD-optimized confidence-based dynamic leverage.

Hedef: Yıllık > %60 + DD < %40

Strateji:
- Tier'lı leverage (confidence-based)
- DD arttıkça max leverage cap azalt
- Daha sıkı daily/weekly breaker
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))


SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
           "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


def _gather_with_features():
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import (
        EngulfingContinuationStrategy, _default_manifest as engulf_manifest,
    )
    from price_action.signals.filters import rolling_sharpe
    from scripts.run_real_backtest import _load_symbol_ohlcv

    manifest = engulf_manifest()
    out = []
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        df = df.sort_values("ts").reset_index(drop=True)
        s = EngulfingContinuationStrategy(manifest)
        df_feats = s.prepare_features(df)
        df_feats["rolling_sharpe_60"] = rolling_sharpe(df_feats["close"], period=60)
        df_feats["body_ratio"] = (df_feats["close"] - df_feats["open"]).abs() / (df_feats["high"] - df_feats["low"]).replace(0, np.nan)
        ts_map = pd.to_datetime(df_feats["ts"], utc=True)
        def prov(*a, **k): return df_feats.copy()
        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(), end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d", initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010}, slippage_bps=5.0, ohlcv_provider=prov)
        for _, t in r.trades.iterrows():
            ts = pd.Timestamp(t["entry_ts"])
            if ts.tzinfo is None: ts = ts.tz_localize("UTC")
            mask = ts_map < ts
            if not mask.any(): continue
            idx = ts_map[mask].index[-1]
            er = float(df_feats["kaufman_er"].iloc[idx]) if "kaufman_er" in df_feats else 0
            rs60 = float(df_feats["rolling_sharpe_60"].iloc[idx]) if "rolling_sharpe_60" in df_feats else 0
            body_ratio = float(df_feats["body_ratio"].iloc[idx]) if "body_ratio" in df_feats else 0
            if np.isnan(rs60): rs60 = 0
            if np.isnan(body_ratio): body_ratio = 0
            out.append({
                "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
                "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                "R": float(t["realized_r_multiple"]), "symbol": sym,
                "confluence": float(t["confluence_score"]), "kaufman_er": er,
                "rolling_sharpe": rs60, "body_ratio": body_ratio,
            })
    out.sort(key=lambda x: x["entry_ts"])
    return out


def _confidence_score(t: dict) -> float:
    conf_norm = max(0.0, min(1.0, (t["confluence"] - 1.5) / 1.5))
    er_norm = max(0.0, min(1.0, t["kaufman_er"]))
    rs_norm = max(0.0, min(1.0, (t["rolling_sharpe"] + 1.0) / 2.0))
    body_norm = max(0.0, min(1.0, t["body_ratio"]))
    return 0.35 * conf_norm + 0.25 * er_norm + 0.25 * rs_norm + 0.15 * body_norm


def _conf_to_lev(conf: float, max_lev: float) -> float:
    if conf < 0.32: return min(1.0, max_lev)
    if conf < 0.42: return min(2.0, max_lev)
    if conf < 0.52: return min(3.0, max_lev)
    if conf < 0.58: return min(4.0, max_lev)
    return min(5.0, max_lev)


def _dd_to_max_lev(cur_dd: float, base_max_lev: float = 5.0) -> float:
    """DD arttıkça max leverage cap'i azalt."""
    if cur_dd < 0.10: return base_max_lev          # tam serbest
    if cur_dd < 0.20: return min(base_max_lev, 3.0)  # max lev 3x
    if cur_dd < 0.30: return min(base_max_lev, 2.0)  # max lev 2x
    if cur_dd < 0.40: return min(base_max_lev, 1.0)  # max lev 1x
    return 0.0  # halt — DD %40+'da hiç trade yok


def replay(trades, risk_pct=0.02, base_max_lev=5.0, dd_scaling=True,
           daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15,
           funding_annual=0.10, max_concurrent=5):
    if not trades:
        return {"final": 10_000.0, "trades": 0, "max_dd": 0, "lev_dist": {}}

    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    peak_equity = 10_000.0
    open_pos = []
    n_taken = 0
    halt_dd = 0
    eq_curve = [10_000.0]
    lev_dist = {1.0: 0, 2.0: 0, 3.0: 0, 4.0: 0, 5.0: 0}
    funding_per_day = funding_annual / 365

    daily_anchor = 10_000.0
    weekly_anchor = 10_000.0
    monthly_anchor = 10_000.0
    last_day = trades[0]["entry_ts"].date()
    last_week = trades[0]["entry_ts"].isocalendar()[1]
    last_month = trades[0]["entry_ts"].month
    blocked_until = None

    def close_due(now):
        nonlocal cash, equity, peak_equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                fund = p["margin"] * p["leverage"] * funding_per_day * holding
                pnl = p["risk"] * p["R"] * p["leverage"] - fund
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                if equity > peak_equity: peak_equity = equity
                eq_curve.append(equity)
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])

        # DD scaling
        cur_dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
        if dd_scaling:
            max_lev = _dd_to_max_lev(cur_dd, base_max_lev=base_max_lev)
        else:
            max_lev = base_max_lev
        if max_lev <= 0:
            halt_dd += 1
            continue

        cur_day = t["entry_ts"].date()
        cur_week = t["entry_ts"].isocalendar()[1]
        cur_month = t["entry_ts"].month
        if cur_day != last_day: daily_anchor = equity; last_day = cur_day
        if cur_week != last_week: weekly_anchor = equity; last_week = cur_week
        if cur_month != last_month: monthly_anchor = equity; last_month = cur_month

        if blocked_until and t["entry_ts"] < blocked_until: continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=1); continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=7); continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=30); continue

        if len(open_pos) >= max_concurrent: continue
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0: continue

        conf = _confidence_score(t)
        lev = _conf_to_lev(conf, max_lev=max_lev)
        if lev <= 0: continue
        lev_dist[lev] = lev_dist.get(lev, 0) + 1

        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        margin = notional / lev
        if margin > cash: continue
        cash -= margin
        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "margin": margin, "risk": risk_d, "R": t["R"], "leverage": lev,
        })
        n_taken += 1

    for p in open_pos:
        holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
        fund = p["margin"] * p["leverage"] * funding_per_day * holding
        cash += p["margin"] + p["risk"] * p["R"] * p["leverage"] - fund
        equity = cash
        eq_curve.append(equity)

    peak = eq_curve[0]
    max_dd = 0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd

    return {"final": equity, "trades": n_taken, "max_dd": max_dd, "lev_dist": lev_dist, "halt_dd": halt_dd}


def main():
    print("Trades + features topluyor...")
    trades = _gather_with_features()
    print(f"Toplam {len(trades)} trade\n")
    if not trades: return

    start = trades[0]["entry_ts"]
    print(f"{'Konfig':<55} {'Yil1':>7} {'Yil2':>7} {'Yil3':>7} {'Compound':>11} {'Yillik':>9} {'maxDD':>7} {'haltDD':>7}")
    print("-" * 130)

    configs = [
        ("R%2 lev 1-5x — DD scaling OFF, breaker normal", 0.02, 5.0, False, 0.05, 0.10, 0.15),
        ("R%2 lev 1-5x — DD scaling ON, breaker normal",  0.02, 5.0, True,  0.05, 0.10, 0.15),
        ("R%2 lev 1-5x — DD scaling ON, breaker tight",   0.02, 5.0, True,  0.03, 0.07, 0.12),
        ("R%2 lev 1-4x — DD scaling ON, breaker tight",   0.02, 4.0, True,  0.03, 0.07, 0.12),
        ("R%2 lev 1-3x — DD scaling ON, breaker tight",   0.02, 3.0, True,  0.03, 0.07, 0.12),
        ("R%3 lev 1-5x — DD scaling ON, breaker normal",  0.03, 5.0, True,  0.05, 0.10, 0.15),
        ("R%3 lev 1-5x — DD scaling ON, breaker tight",   0.03, 5.0, True,  0.03, 0.07, 0.12),
        ("R%3 lev 1-4x — DD scaling ON, breaker tight",   0.03, 4.0, True,  0.03, 0.07, 0.12),
        ("R%3 lev 1-3x — DD scaling ON, breaker tight",   0.03, 3.0, True,  0.03, 0.07, 0.12),
    ]

    for label, risk, max_lev, dd_scale, dd_d, dd_w, dd_m in configs:
        eq_compound = 10_000.0
        yearly = []
        worst_dd = 0.0
        total_halt = 0
        for yr in range(3):
            ws = start + timedelta(days=365 * yr)
            we = start + timedelta(days=365 * (yr + 1))
            wt = [t for t in trades if ws <= t["entry_ts"] < we]
            r = replay(wt, risk_pct=risk, base_max_lev=max_lev, dd_scaling=dd_scale, daily_dd=dd_d, weekly_dd=dd_w, monthly_dd=dd_m)
            ret = r["final"] / 10_000 - 1
            yearly.append(ret)
            eq_compound *= (1 + ret)
            if r["max_dd"] < worst_dd: worst_dd = r["max_dd"]
            total_halt += r["halt_dd"]
        annual = ((eq_compound / 10_000) ** (1/3) - 1) * 100
        cells = " ".join(f"{(y*100):>+5.1f}%" for y in yearly)
        print(f"{label:<55} {cells} ${eq_compound:>9,.0f} {annual:>+7.2f}% {worst_dd*100:>+5.1f}% {total_halt:>7}")

    print()
    print("HEDEF: yıllık > %50, DD < %40")
    print("haltDD: trade-time'da DD %40+ → trade SKIP edildi")


if __name__ == "__main__":
    main()
