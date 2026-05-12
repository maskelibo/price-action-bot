"""Engulfing MTF (1d + 4h confluence) backtest.

Karsilastirma:
  A) Engulfing baseline  (1d only, production manifest)
  B) Engulfing + 4h confluence (bu script)
  C) Production A         (engulfing + confidence-based dynamic leverage)
  D) Production A + 4h   (en iyi kombo: MTF + dynamic leverage)

10 USDT sembol * 1d * 3y.
4h always-in confluence filter (Brooks 3-bar trend confirmation).

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_engulfing_mtf_backtest.py
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
]

INITIAL_CAPITAL = 10_000.0
FEES = {"taker": 0.00075, "maker": -0.00010}
SLIPPAGE_BPS = 5.0


# =====================================================================
# Data loading
# =====================================================================

def _load_ohlcv(symbol: str, tf: str, venue: str = "binance") -> pd.DataFrame:
    import duckdb
    con = duckdb.connect(str(ROOT / "data" / "market.duckdb"), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM ohlcv "
        "WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts",
        [venue, symbol, tf],
    ).fetchdf()
    con.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["symbol"] = symbol
    df["timeframe"] = tf
    df["venue"] = venue
    return df


# =====================================================================
# Engulfing baseline manifest (orijinal)
# =====================================================================

def _baseline_manifest():
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "engulfing_continuation",
        "version": "1.0.0",
        "description": "Baseline: engulfing 1d only",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {"id": "bullish_engulfing_cont", "enabled": True, "weight": 1.5,
                 "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5}},
                {"id": "bearish_engulfing_cont", "enabled": True, "weight": 1.5,
                 "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5}},
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {"lookback_bars": 120, "cluster_atr_multiplier": 0.5,
                                       "min_touches": 2, "max_age_bars": 120},
                "require_proximity_to_sr_atr": 0.5,
            },
            "filters": {"atr_min_pct": 0.005, "volume_zscore_min": 0.0,
                        "kaufman_er_period": 14, "kaufman_er_min": 0.20, "bear_regime_size_factor": 0.5},
            "confluence": {"method": "weighted_sum", "min_score": 1.5, "bonus_if_at_sr": 0.5},
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# MTF manifest (engulfing + 4h filter)
# =====================================================================

def _mtf_manifest():
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "engulfing_mtf",
        "version": "1.0.0",
        "description": "Engulfing 1d + 4h Brooks always-in confluence",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {"id": "bullish_engulfing_cont", "enabled": True, "weight": 1.5,
                 "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5}},
                {"id": "bearish_engulfing_cont", "enabled": True, "weight": 1.5,
                 "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5}},
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {"lookback_bars": 120, "cluster_atr_multiplier": 0.5,
                                       "min_touches": 2, "max_age_bars": 120},
                "require_proximity_to_sr_atr": 0.5,
            },
            "filters": {
                "atr_min_pct": 0.005, "volume_zscore_min": 0.0,
                "kaufman_er_period": 14, "kaufman_er_min": 0.20, "bear_regime_size_factor": 0.5,
                # 4h MTF parametreler
                "h4_lookback": 6,
                "h4_n_confirm": 3,
                "h4_strong_close_pct": 0.90,
                "h4_confirm_boost": 1.3,
                "h4_reject_against": True,
            },
            "confluence": {"method": "weighted_sum", "min_score": 1.5, "bonus_if_at_sr": 0.5},
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Per-symbol backtester
# =====================================================================

def _run_baseline(symbol: str, manifest) -> dict:
    """Engulfing baseline (1d only)."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy

    df = _load_ohlcv(symbol, "1d")
    if df.empty:
        return {"symbol": symbol, "error": "no 1d data"}

    s = EngulfingContinuationStrategy(manifest)
    df_f = s.prepare_features(df)

    engine = BacktestEngine(risk_officer=None, store_load=None)
    result = engine.run(
        s, [symbol],
        start=df["ts"].iloc[0].to_pydatetime(), end=df["ts"].iloc[-1].to_pydatetime(),
        timeframe="1d", initial_capital=INITIAL_CAPITAL, fees=FEES, slippage_bps=SLIPPAGE_BPS,
        ohlcv_provider=lambda *a, **k: df_f.copy(),
    )
    k = result.kpis
    cagr = float(k.get("cagr", 0.0))
    raw_net = float(k.get("net_pnl", 0.0))
    net = raw_net if raw_net != 0.0 else INITIAL_CAPITAL * ((1 + cagr) ** 3 - 1)
    return {
        "symbol": symbol, "n_bars": len(df), "n_trades": result.n_trades,
        "win_rate": float(k.get("win_rate", 0.0)), "profit_factor": float(k.get("profit_factor", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)), "sharpe": float(k.get("sharpe", 0.0)),
        "cagr": cagr, "net_pnl": net,
        "elapsed_sec": result.elapsed_sec,
    }


def _run_mtf(symbol: str, manifest) -> dict:
    """Engulfing + 4h MTF confluence."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_mtf import EngulfingMTFStrategy

    df_1d = _load_ohlcv(symbol, "1d")
    if df_1d.empty:
        return {"symbol": symbol, "error": "no 1d data"}

    df_4h = _load_ohlcv(symbol, "4h")
    if df_4h.empty:
        df_4h = None

    s = EngulfingMTFStrategy(manifest)
    # Pre-cache 4h data (avoid DB reads during backtest)
    s._df_4h_cache[f"binance:{symbol}"] = df_4h

    df_f = s.prepare_features(df_1d)

    engine = BacktestEngine(risk_officer=None, store_load=None)
    result = engine.run(
        s, [symbol],
        start=df_1d["ts"].iloc[0].to_pydatetime(), end=df_1d["ts"].iloc[-1].to_pydatetime(),
        timeframe="1d", initial_capital=INITIAL_CAPITAL, fees=FEES, slippage_bps=SLIPPAGE_BPS,
        ohlcv_provider=lambda *a, **k: df_f.copy(),
    )
    k = result.kpis
    cagr = float(k.get("cagr", 0.0))
    raw_net = float(k.get("net_pnl", 0.0))
    net = raw_net if raw_net != 0.0 else INITIAL_CAPITAL * ((1 + cagr) ** 3 - 1)

    # Count 4h verdict stats from signals
    sigs = s.generate_signals(df_f)
    h4_verdicts = [s_sig.metadata.get("h4_verdict", "neutral") for s_sig in sigs]
    h4_confirm = h4_verdicts.count("confirm")
    h4_against = h4_verdicts.count("against")
    h4_neutral = h4_verdicts.count("neutral")

    return {
        "symbol": symbol, "n_bars": len(df_1d), "n_trades": result.n_trades,
        "win_rate": float(k.get("win_rate", 0.0)), "profit_factor": float(k.get("profit_factor", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)), "sharpe": float(k.get("sharpe", 0.0)),
        "cagr": cagr, "net_pnl": net,
        "h4_confirm": h4_confirm, "h4_against": h4_against, "h4_neutral": h4_neutral,
        "elapsed_sec": result.elapsed_sec,
    }


# =====================================================================
# Production A dynamic leverage replay (from confidence_dynamic_leverage)
# =====================================================================

def _confidence_score(t: dict) -> float:
    """Same blend as confidence_dynamic_leverage.py."""
    conf_norm = max(0.0, min(1.0, (t["confluence"] - 1.5) / 1.5))
    er_norm = max(0.0, min(1.0, t["kaufman_er"]))
    rs_norm = max(0.0, min(1.0, (t["rolling_sharpe"] + 1.0) / 2.0))
    body_norm = max(0.0, min(1.0, t["body_ratio"]))
    return 0.35 * conf_norm + 0.25 * er_norm + 0.25 * rs_norm + 0.15 * body_norm


def _confidence_to_leverage(conf: float, max_lev: float = 5.0) -> float:
    if conf < 0.32: return 1.0
    if conf < 0.42: return 2.0
    if conf < 0.52: return 3.0
    if conf < 0.58: return 4.0
    return min(5.0, max_lev)


def _replay_with_leverage(trades: list[dict], risk_pct: float = 0.02, max_lev: float = 5.0,
                          funding_annual: float = 0.10) -> dict:
    """Dynamic leverage replay (Production A logic)."""
    if not trades:
        return {"final": INITIAL_CAPITAL, "trades": 0, "max_dd": 0.0, "annual_pct": 0.0}

    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = cash = INITIAL_CAPITAL
    open_pos: list[dict] = []
    eq_curve = [INITIAL_CAPITAL]
    n_taken = 0
    funding_per_day = funding_annual / 365

    def close_due(now):
        nonlocal cash, equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                fund = p["margin"] * p["leverage"] * funding_per_day * holding
                pnl = p["risk"] * p["R"] * p["leverage"] - fund
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                eq_curve.append(equity)
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])

        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / max(t["entry_price"], 1e-9)
        if sl_pct <= 0:
            continue
        conf = _confidence_score(t)
        lev = _confidence_to_leverage(conf, max_lev=max_lev)
        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        margin = notional / lev
        if margin > cash or len(open_pos) >= 5:
            continue
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

    peak = INITIAL_CAPITAL
    max_dd = 0.0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd

    total_ret = equity / INITIAL_CAPITAL - 1
    annual = ((1 + total_ret) ** (1 / 3) - 1) * 100
    return {"final": equity, "trades": n_taken, "max_dd": max_dd, "annual_pct": annual}


def _gather_trades_for_prod_a(strategy_cls, manifest, symbol: str, tf: str = "1d",
                               extra_kwargs: dict | None = None) -> list[dict]:
    """Trade listesi topla (Production A replay icin)."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.signals.filters import rolling_sharpe

    df = _load_ohlcv(symbol, tf)
    if df.empty:
        return []
    df = df.sort_values("ts").reset_index(drop=True)

    kwargs = extra_kwargs or {}
    s = strategy_cls(manifest, **kwargs)
    if hasattr(s, "_df_4h_cache"):
        df_4h = _load_ohlcv(symbol, "4h")
        s._df_4h_cache[f"binance:{symbol}"] = df_4h if not df_4h.empty else None

    df_f = s.prepare_features(df)
    df_f["rolling_sharpe_60"] = rolling_sharpe(df_f["close"], period=60)
    df_f["body_ratio"] = (df_f["close"] - df_f["open"]).abs() / (
        df_f["high"] - df_f["low"]
    ).replace(0, np.nan)
    ts_map = pd.to_datetime(df_f["ts"], utc=True)

    engine = BacktestEngine(risk_officer=None, store_load=None)
    r = engine.run(
        s, [symbol],
        start=df["ts"].iloc[0].to_pydatetime(), end=df["ts"].iloc[-1].to_pydatetime(),
        timeframe=tf, initial_capital=INITIAL_CAPITAL, fees=FEES, slippage_bps=SLIPPAGE_BPS,
        ohlcv_provider=lambda *a, **k: df_f.copy(),
    )

    trades = []
    for _, t in r.trades.iterrows():
        ts = pd.Timestamp(t["entry_ts"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        mask = ts_map < ts
        if not mask.any():
            continue
        idx = ts_map[mask].index[-1]
        cs = float(t.get("confluence_score", 1.5))
        er = float(df_f["kaufman_er"].iloc[idx]) if "kaufman_er" in df_f else 0
        rs60 = float(df_f["rolling_sharpe_60"].iloc[idx]) if "rolling_sharpe_60" in df_f else 0
        br = float(df_f["body_ratio"].iloc[idx]) if "body_ratio" in df_f else 0
        if np.isnan(rs60): rs60 = 0
        if np.isnan(br): br = 0

        trades.append({
            "entry_ts": ts, "exit_ts": pd.Timestamp(t["exit_ts"]).tz_localize("UTC")
                if pd.Timestamp(t["exit_ts"]).tzinfo is None else pd.Timestamp(t["exit_ts"]),
            "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
            "R": float(t["realized_r_multiple"]),
            "confluence": cs, "kaufman_er": er, "rolling_sharpe": rs60, "body_ratio": br,
        })
    return trades


# =====================================================================
# Aggregate helper
# =====================================================================

def _aggregate(results: list[dict], label: str) -> dict:
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    if not valid:
        return {"label": label, "valid": 0}
    n_trades = sum(r["n_trades"] for r in valid)
    net_pnl = sum(r["net_pnl"] for r in valid)
    starting = INITIAL_CAPITAL * len(valid)
    total_ret = net_pnl / starting
    annual = (((1 + total_ret) ** (1 / 3)) - 1) * 100
    avg_dd = sum(r["max_drawdown"] for r in valid) / len(valid)
    avg_sharpe = sum(r["sharpe"] for r in valid) / len(valid)
    avg_wr = sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades)
    avg_cagr = sum(r["cagr"] for r in valid) / len(valid)
    return {
        "label": label, "valid": len(valid), "n_trades": n_trades,
        "annual_pct": annual, "avg_dd_pct": avg_dd * 100, "avg_sharpe": avg_sharpe,
        "avg_win_rate": avg_wr * 100, "avg_cagr": avg_cagr * 100, "net_pnl": net_pnl,
    }


def _print_aggregate(agg: dict) -> None:
    if agg.get("valid", 0) == 0:
        print(f"  {agg['label']}: hicbir sembolde trade yok")
        return
    print(f"  {'Metrik':<25} {'Deger':>12}")
    print(f"  {'Semboller (gecen)':<25} {agg['valid']:>12}/{len(SYMBOLS)}")
    print(f"  {'Toplam trade':<25} {agg['n_trades']:>12}")
    print(f"  {'Avg win rate':<25} {agg['avg_win_rate']:>11.1f}%")
    print(f"  {'Net P&L':<25} ${agg['net_pnl']:>+11,.0f}")
    print(f"  {'Yillik (3y annualized)':<25} {agg['annual_pct']:>+11.2f}%")
    print(f"  {'Avg MaxDD':<25} {agg['avg_dd_pct']:>11.1f}%")
    print(f"  {'Avg Sharpe':<25} {agg['avg_sharpe']:>12.2f}")
    print(f"  {'Avg CAGR':<25} {agg['avg_cagr']:>+11.2f}%")


# =====================================================================
# Main
# =====================================================================

def main() -> int:
    print("=" * 70)
    print("=== Engulfing MTF Backtest — 1d + 4h Confluence ===")
    print(f"  {len(SYMBOLS)} sembol | 1d | 3y | kapital: ${INITIAL_CAPITAL:,.0f}/sembol")
    print("=" * 70)

    # ---- A: Engulfing Baseline (1d only) ----
    print("\n--- A: Engulfing Baseline (1d only) ---")
    baseline_manifest = _baseline_manifest()
    baseline_results = []
    for sym in SYMBOLS:
        try:
            r = _run_baseline(sym, baseline_manifest)
            baseline_results.append(r)
            if "error" in r:
                print(f"  {sym:<12} FAIL: {r['error']}")
            else:
                print(f"  {sym:<12} trades={r['n_trades']:>3} wr={r['win_rate']*100:>5.1f}% "
                      f"dd={r['max_drawdown']*100:>4.1f}% cagr={r['cagr']*100:>+6.1f}%")
        except Exception as exc:
            print(f"  {sym:<12} EXC: {exc}")
            baseline_results.append({"symbol": sym, "error": str(exc)})

    agg_baseline = _aggregate(baseline_results, "Baseline (1d only)")
    print("\n  [AGGREGATE]")
    _print_aggregate(agg_baseline)

    # ---- B: Engulfing + 4h MTF confluence ----
    print("\n--- B: Engulfing + 4h MTF Confluence ---")
    mtf_manifest = _mtf_manifest()
    mtf_results = []
    for sym in SYMBOLS:
        try:
            r = _run_mtf(sym, mtf_manifest)
            mtf_results.append(r)
            if "error" in r:
                print(f"  {sym:<12} FAIL: {r['error']}")
            else:
                h4_str = f"4h[+{r.get('h4_confirm',0)}/x{r.get('h4_against',0)}/~{r.get('h4_neutral',0)}]"
                print(f"  {sym:<12} trades={r['n_trades']:>3} wr={r['win_rate']*100:>5.1f}% "
                      f"dd={r['max_drawdown']*100:>4.1f}% cagr={r['cagr']*100:>+6.1f}% {h4_str}")
        except Exception as exc:
            print(f"  {sym:<12} EXC: {exc}")
            traceback.print_exc()
            mtf_results.append({"symbol": sym, "error": str(exc)})

    agg_mtf = _aggregate(mtf_results, "MTF (1d + 4h)")
    print("\n  [AGGREGATE]")
    _print_aggregate(agg_mtf)

    # ---- C: Production A — Dynamic Leverage (baseline strategy) ----
    print("\n--- C: Production A — Dynamic Leverage (1d baseline + conf leverage) ---")
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy
    all_baseline_trades = []
    for sym in SYMBOLS:
        try:
            trades = _gather_trades_for_prod_a(EngulfingContinuationStrategy, baseline_manifest, sym)
            all_baseline_trades.extend(trades)
        except Exception as exc:
            print(f"  {sym:<12} EXC: {exc}")

    prod_a_result = _replay_with_leverage(all_baseline_trades, risk_pct=0.02, max_lev=5.0)
    print(f"  Toplam trade : {prod_a_result['trades']}")
    print(f"  Yillik       : {prod_a_result['annual_pct']:>+.2f}%")
    print(f"  MaxDD        : {prod_a_result['max_dd']*100:>+.1f}%")
    print(f"  Final equity : ${prod_a_result['final']:>,.0f}")

    # ---- D: Production A + 4h confluence ----
    print("\n--- D: Production A + 4h confluence (best combo) ---")
    from price_action.strategies.engulfing_mtf import EngulfingMTFStrategy
    all_mtf_trades = []
    for sym in SYMBOLS:
        try:
            trades = _gather_trades_for_prod_a(EngulfingMTFStrategy, mtf_manifest, sym)
            all_mtf_trades.extend(trades)
        except Exception as exc:
            print(f"  {sym:<12} EXC: {exc}")
            traceback.print_exc()

    prod_d_result = _replay_with_leverage(all_mtf_trades, risk_pct=0.02, max_lev=5.0)
    print(f"  Toplam trade : {prod_d_result['trades']}")
    print(f"  Yillik       : {prod_d_result['annual_pct']:>+.2f}%")
    print(f"  MaxDD        : {prod_d_result['max_dd']*100:>+.1f}%")
    print(f"  Final equity : ${prod_d_result['final']:>,.0f}")

    # ---- Comparison Table ----
    print("\n" + "=" * 70)
    print("KARSILASTIRMA TABLOSU")
    print("=" * 70)
    headers = f"  {'Strateji':<35} {'Yillik%':>9} {'MaxDD%':>8} {'Trades':>7} {'WinRate':>9}"
    print(headers)
    print("  " + "-" * 68)

    rows = [
        ("A) Baseline (1d only)",
         agg_baseline.get("annual_pct", 0), agg_baseline.get("avg_dd_pct", 0),
         agg_baseline.get("n_trades", 0), agg_baseline.get("avg_win_rate", 0)),
        ("B) MTF (1d + 4h confluence)",
         agg_mtf.get("annual_pct", 0), agg_mtf.get("avg_dd_pct", 0),
         agg_mtf.get("n_trades", 0), agg_mtf.get("avg_win_rate", 0)),
        ("C) Production A (baseline + dyn lev)",
         prod_a_result["annual_pct"], prod_a_result["max_dd"] * 100,
         prod_a_result["trades"], agg_baseline.get("avg_win_rate", 0)),
        ("D) Prod A + 4h (best combo)",
         prod_d_result["annual_pct"], prod_d_result["max_dd"] * 100,
         prod_d_result["trades"], agg_mtf.get("avg_win_rate", 0)),
    ]
    for label, ann, dd, tr, wr in rows:
        print(f"  {label:<35} {ann:>+8.2f}% {dd:>7.1f}% {tr:>7} {wr:>8.1f}%")

    # ---- 4h Filter Analysis ----
    valid_mtf = [r for r in mtf_results if "error" not in r]
    if valid_mtf:
        total_confirm = sum(r.get("h4_confirm", 0) for r in valid_mtf)
        total_against = sum(r.get("h4_against", 0) for r in valid_mtf)
        total_neutral = sum(r.get("h4_neutral", 0) for r in valid_mtf)
        total_4h = total_confirm + total_against + total_neutral
        print("\n  4h FILTER ANALIZI:")
        if total_4h > 0:
            print(f"  4h confirm (boost x1.3) : {total_confirm:>4} ({total_confirm/total_4h*100:>4.1f}%)")
            print(f"  4h against (rejected)   : {total_against:>4} ({total_against/total_4h*100:>4.1f}%)")
            print(f"  4h neutral  (unchanged) : {total_neutral:>4} ({total_neutral/total_4h*100:>4.1f}%)")

    # ---- VERDICT ----
    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)
    baseline_ann = agg_baseline.get("annual_pct", 0)
    mtf_ann = agg_mtf.get("annual_pct", 0)
    prod_a_ann = prod_a_result["annual_pct"]
    prod_d_ann = prod_d_result["annual_pct"]

    mtf_vs_baseline = mtf_ann - baseline_ann
    prod_d_vs_prod_a = prod_d_ann - prod_a_ann

    print(f"  MTF vs Baseline       : {mtf_vs_baseline:>+.2f}% yillik fark")
    print(f"  Prod A+4h vs Prod A   : {prod_d_vs_prod_a:>+.2f}% yillik fark")

    if prod_d_vs_prod_a >= 10.0 and prod_d_result["max_dd"] <= prod_a_result["max_dd"] * 1.05:
        verdict = "REPLACE"
        verdict_detail = "Production A'yi REPLACE et — 4h confluence +%{:.1f} getiri artisi + benzer risk.".format(prod_d_vs_prod_a)
    elif prod_d_vs_prod_a >= 2.0 or (prod_d_result["max_dd"] < prod_a_result["max_dd"] * 0.90 and prod_d_ann >= prod_a_ann * 0.95):
        verdict = "SUPPLEMENT"
        verdict_detail = "Production A'ya 4h confluence EKLE — yeni Production variant."
    elif prod_d_vs_prod_a < -5.0 or (mtf_ann < baseline_ann - 3.0):
        verdict = "REJECT"
        verdict_detail = "4h confluence GÜRÜLTÜ ekliyor, edge azalıyor. Mevcut Production A'da kal."
    else:
        verdict = "SUPPLEMENT"
        verdict_detail = "Marginal fark. A/B testi ile daha fazla veri topla, sonra karar ver."

    print(f"\n  VERDICT: {verdict}")
    print(f"  {verdict_detail}")

    # Noise vs Edge analizi
    if total_4h > 0:
        reject_rate = total_against / total_4h * 100
        if reject_rate > 40:
            print(f"\n  NOT: 4h filter sinyallerin %{reject_rate:.1f}'ini eliyor — cok agresif.")
            print("  h4_n_confirm dusur (2'ye) veya h4_reject_against=False ile test et.")
        elif reject_rate < 5:
            print(f"\n  NOT: 4h filter sadece %{reject_rate:.1f} reddediyor — cok zayif filtre.")

    # Save report
    report = {
        "date": str(datetime.now(timezone.utc).date()),
        "baseline": agg_baseline,
        "mtf": agg_mtf,
        "prod_a": prod_a_result,
        "prod_a_plus_4h": prod_d_result,
        "verdict": verdict,
    }
    report_path = ROOT / "reports" / "backtests" / f"engulfing_mtf_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")
    print(f"\n  Detay rapor: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
