"""HYP-NEW-5: Failed Breakout + BOS + Low-Volume Reclaim — REAL DATA Backtest.

10 symbols × 1d × 3y (real DuckDB data).
Per-symbol breakdown + portfolio aggregate.
Comparison vs engulfing baseline.
Decorrelation via R-multiple analysis.

Run:
    PYTHONPATH=src python scripts/run_failed_bo_bos_backtest.py
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# =====================================================================
# Data loader
# =====================================================================

def _load_symbol_ohlcv(
    symbol: str, tf: str = "1d", venue: str = "binance"
) -> pd.DataFrame:
    import duckdb
    db_path = ROOT / "data" / "market.duckdb"
    if not db_path.exists():
        return pd.DataFrame()
    con = duckdb.connect(str(db_path), read_only=True)
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
# Per-symbol runner
# =====================================================================

def _run_one_symbol(symbol: str, initial_capital: float = 10_000.0) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.failed_bo_bos_reclaim import (
        FailedBOBOSReclaimStrategy,
        _default_manifest,
    )

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    manifest = _default_manifest()
    strategy = FailedBOBOSReclaimStrategy(manifest)

    try:
        df_feats = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_feats)
    except Exception as exc:
        return {"symbol": symbol, "error": f"strategy error: {exc}"}

    long_sigs = [s for s in signals if s.direction == "long"]
    short_sigs = [s for s in signals if s.direction == "short"]

    def ohlcv_provider(_sym, _tf, _start, _end):
        return df_feats.copy()

    engine = BacktestEngine(risk_officer=None, store_load=None)
    try:
        result = engine.run(
            strategy,
            [symbol],
            start=df["ts"].iloc[0].to_pydatetime(),
            end=df["ts"].iloc[-1].to_pydatetime(),
            timeframe="1d",
            initial_capital=initial_capital,
            fees={"taker": 0.00075, "maker": -0.00010},
            slippage_bps=5.0,
            ohlcv_provider=ohlcv_provider,
        )
    except Exception as exc:
        return {"symbol": symbol, "error": f"engine error: {exc}"}

    k = result.kpis

    # Yearly breakdown from trades
    yearly = {}
    if not result.trades.empty:
        tdf = result.trades.copy()
        tdf["year"] = pd.to_datetime(tdf["exit_ts"]).dt.year
        for yr, grp in tdf.groupby("year"):
            yearly[str(yr)] = {
                "n": int(len(grp)),
                "pnl": float(grp["realized_pnl_usdt"].sum()),
                "wr": float((grp["realized_pnl_usdt"] > 0).mean()),
            }

    return {
        "symbol": symbol,
        "n_bars": int(len(df)),
        "first_ts": str(df["ts"].iloc[0].date()),
        "last_ts": str(df["ts"].iloc[-1].date()),
        "n_signals": int(len(signals)),
        "n_long_signals": int(len(long_sigs)),
        "n_short_signals": int(len(short_sigs)),
        "n_trades": int(result.n_trades),
        "win_rate": float(k.get("win_rate", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "expectancy": float(k.get("expectancy", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "sharpe": float(k.get("sharpe", 0.0)),
        "sortino": float(k.get("sortino", 0.0)),
        "cagr": float(k.get("cagr", 0.0)),
        "deflated_sharpe": float(k.get("deflated_sharpe", 0.0)),
        "net_pnl": float(k.get("net_pnl", k.get("equity_final", initial_capital) - initial_capital)),
        "equity_final": float(k.get("equity_final", initial_capital)),
        "elapsed_sec": float(result.elapsed_sec),
        "yearly": yearly,
        "trades_df": result.trades,  # keep in memory for decorrelation
    }


# =====================================================================
# Engulfing baseline (for comparison)
# =====================================================================

def _run_engulfing_baseline(symbol: str, initial_capital: float = 10_000.0) -> dict:
    """Run engulfing continuation baseline for comparison."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.base import StrategyManifest

    try:
        from price_action.strategies.classic_pa import ClassicPriceActionStrategy

        df = _load_symbol_ohlcv(symbol, tf="1d")
        if df.empty:
            return {"symbol": symbol, "error": "no data"}

        raw = {
            "name": "classic_pa_engulfing_baseline",
            "version": "1.0.0",
            "trend_filter": {"type": "ema", "period": 50, "required": True},
            "signals": {
                "patterns": [
                    {"id": "bullish_engulfing", "enabled": True, "weight": 1.5, "params": {}},
                    {"id": "bearish_engulfing", "enabled": True, "weight": 1.5, "params": {}},
                ],
                "structure": {
                    "swing": {"fractal_n": 2},
                    "support_resistance": {
                        "lookback_bars": 120,
                        "cluster_atr_multiplier": 0.5,
                        "min_touches": 2,
                        "max_age_bars": 120,
                    },
                    "require_proximity_to_sr_atr": 0.5,
                },
                "filters": {"atr_min_pct": 0.005},
                "confluence": {"method": "weighted_sum", "min_score": 1.5},
            },
            "risk": {
                "stop_loss": {"method": "atr", "atr_period": 14, "atr_multiplier": 2.0},
                "take_profit": {"method": "r_multiple", "primary_R": 2.0},
                "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
            },
        }
        manifest = StrategyManifest.model_validate(raw)
        strategy = ClassicPriceActionStrategy(manifest)

        df_feats = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_feats)

        def ohlcv_provider(_sym, _tf, _start, _end):
            return df_feats.copy()

        engine = BacktestEngine(risk_officer=None, store_load=None)
        result = engine.run(
            strategy, [symbol],
            start=df["ts"].iloc[0].to_pydatetime(),
            end=df["ts"].iloc[-1].to_pydatetime(),
            timeframe="1d",
            initial_capital=initial_capital,
            fees={"taker": 0.00075, "maker": -0.00010},
            slippage_bps=5.0,
            ohlcv_provider=ohlcv_provider,
        )
        k = result.kpis
        return {
            "symbol": symbol,
            "n_trades": int(result.n_trades),
            "win_rate": float(k.get("win_rate", 0.0)),
            "profit_factor": float(k.get("profit_factor", 0.0)),
            "cagr": float(k.get("cagr", 0.0)),
            "sharpe": float(k.get("sharpe", 0.0)),
            "max_drawdown": float(k.get("max_drawdown", 0.0)),
            "trades_df": result.trades,
        }
    except Exception as exc:
        return {"symbol": symbol, "error": str(exc)}


# =====================================================================
# Decorrelation analysis
# =====================================================================

def _compute_decorrelation(
    fbo_results: list[dict],
    eng_results: list[dict],
) -> dict:
    """Compare R-multiple distributions between FBO-BOS-Reclaim and Engulfing.

    Correlation of exit timestamps: if exits cluster at different times,
    strategies are decorrelated.
    """
    fbo_rmults: list[float] = []
    eng_rmults: list[float] = []
    fbo_exit_ts: list[pd.Timestamp] = []
    eng_exit_ts: list[pd.Timestamp] = []

    for r in fbo_results:
        tdf = r.get("trades_df")
        if tdf is not None and not tdf.empty and "realized_r_multiple" in tdf.columns:
            fbo_rmults.extend(tdf["realized_r_multiple"].dropna().tolist())
            fbo_exit_ts.extend(pd.to_datetime(tdf["exit_ts"]).tolist())

    for r in eng_results:
        tdf = r.get("trades_df")
        if tdf is not None and not tdf.empty and "realized_r_multiple" in tdf.columns:
            eng_rmults.extend(tdf["realized_r_multiple"].dropna().tolist())
            eng_exit_ts.extend(pd.to_datetime(tdf["exit_ts"]).tolist())

    result = {
        "fbo_n_trades": len(fbo_rmults),
        "eng_n_trades": len(eng_rmults),
        "fbo_mean_r": float(np.mean(fbo_rmults)) if fbo_rmults else 0.0,
        "eng_mean_r": float(np.mean(eng_rmults)) if eng_rmults else 0.0,
        "fbo_wr": float(np.mean([r > 0 for r in fbo_rmults])) if fbo_rmults else 0.0,
        "eng_wr": float(np.mean([r > 0 for r in eng_rmults])) if eng_rmults else 0.0,
    }

    # Temporal overlap: what % of FBO exit dates coincide with engulfing exits (same day)?
    if fbo_exit_ts and eng_exit_ts:
        eng_dates = set(pd.Timestamp(ts).date() for ts in eng_exit_ts)
        fbo_dates = [pd.Timestamp(ts).date() for ts in fbo_exit_ts]
        overlap = sum(1 for d in fbo_dates if d in eng_dates) / len(fbo_dates)
        result["temporal_overlap_pct"] = float(overlap)
        result["temporal_decorrelation"] = float(1.0 - overlap)
    else:
        result["temporal_overlap_pct"] = 0.0
        result["temporal_decorrelation"] = 1.0

    return result


# =====================================================================
# Main
# =====================================================================

def main() -> int:
    symbols = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
        "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    ]
    initial_capital = 10_000.0

    print("=" * 75)
    print("HYP-NEW-5: Failed BO + BOS + Low-Volume Reclaim — REAL DATA Backtest")
    print("10 symbols × 1d × 3y | REAL DuckDB data")
    print("=" * 75)
    print()

    # ---- Run FBO-BOS-Reclaim strategy ----
    print("=== FAILED BO + BOS + LOW-VOL RECLAIM (HYP-NEW-5) ===")
    print(f"{'Symbol':<12} {'Bars':>4} {'Sigs':>4} {'Trades':>6} {'WR%':>6} "
          f"{'PF':>5} {'DD%':>6} {'Sharpe':>7} {'CAGR%':>7} {'PnL':>8}")
    print("-" * 75)

    fbo_results: list[dict] = []
    for sym in symbols:
        try:
            r = _run_one_symbol(sym, initial_capital)
            fbo_results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r['n_bars']:>4} {r['n_signals']:>4} "
                    f"{r['n_trades']:>6} {r['win_rate']*100:>5.1f}% "
                    f"{r['profit_factor']:>5.2f} {r['max_drawdown']*100:>5.1f}% "
                    f"{r['sharpe']:>7.2f} {r['cagr']*100:>6.1f}% "
                    f"${r['net_pnl']:>+7.0f}"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            fbo_results.append({"symbol": sym, "error": str(exc)})

    # ---- Per-symbol yearly breakdown ----
    print("\n=== YEARLY BREAKDOWN (FBO-BOS-Reclaim) ===")
    for r in fbo_results:
        if "error" in r or not r.get("yearly"):
            continue
        print(f"  {r['symbol']}:")
        for yr, stats in sorted(r["yearly"].items()):
            print(f"    {yr}: n={stats['n']:>3}, PnL=${stats['pnl']:>+7.0f}, WR={stats['wr']*100:.0f}%")

    # ---- FBO Portfolio aggregate ----
    valid_fbo = [r for r in fbo_results if "error" not in r and r.get("n_trades", 0) > 0]
    print("\n" + "=" * 75)
    print("FBO-BOS-RECLAIM PORTFOLIO AGGREGATE (equal-weight)")
    print("=" * 75)

    fbo_agg = {}
    if valid_fbo:
        n_trades_total = sum(r["n_trades"] for r in valid_fbo)
        avg_wr = sum(r["win_rate"] * r["n_trades"] for r in valid_fbo) / max(1, n_trades_total)
        net_pnl = sum(r["net_pnl"] for r in valid_fbo)
        starting_equity = initial_capital * len(valid_fbo)
        total_return = net_pnl / starting_equity
        avg_dd = sum(r["max_drawdown"] for r in valid_fbo) / len(valid_fbo)
        avg_sharpe = sum(r["sharpe"] for r in valid_fbo) / len(valid_fbo)
        avg_cagr = sum(r["cagr"] for r in valid_fbo) / len(valid_fbo)
        avg_pf = sum(r["profit_factor"] for r in valid_fbo) / len(valid_fbo)
        annual = (((1 + total_return) ** (1 / 3)) - 1) * 100

        print(f"  Symbols (valid)        : {len(valid_fbo)}/{len(symbols)}")
        print(f"  Total trades           : {n_trades_total}")
        print(f"  Long signals           : {sum(r.get('n_long_signals',0) for r in valid_fbo)}")
        print(f"  Short signals          : {sum(r.get('n_short_signals',0) for r in valid_fbo)}")
        print(f"  Aggregate win rate     : {avg_wr*100:.1f}%")
        print(f"  Aggregate net P&L      : ${net_pnl:+,.0f}")
        print(f"  Total return (3y)      : {total_return*100:+.1f}%")
        print(f"  Annualized return      : {annual:+.1f}%")
        print(f"  Avg MaxDD              : {avg_dd*100:.1f}%")
        print(f"  Avg Sharpe             : {avg_sharpe:.2f}")
        print(f"  Avg CAGR               : {avg_cagr*100:.1f}%")
        print(f"  Avg Profit Factor      : {avg_pf:.2f}")

        fbo_agg = {
            "n_symbols": len(valid_fbo),
            "n_trades": n_trades_total,
            "win_rate": avg_wr,
            "net_pnl": net_pnl,
            "total_return_3y": total_return,
            "annual_return": annual / 100,
            "avg_max_dd": avg_dd,
            "avg_sharpe": avg_sharpe,
            "avg_cagr": avg_cagr,
            "avg_pf": avg_pf,
        }

    # ---- Engulfing baseline ----
    print("\n=== ENGULFING BASELINE (for comparison) ===")
    print(f"{'Symbol':<12} {'Trades':>6} {'WR%':>6} {'PF':>5} {'DD%':>6} {'Sharpe':>7} {'CAGR%':>7}")
    print("-" * 55)

    eng_results: list[dict] = []
    for sym in symbols:
        try:
            r = _run_engulfing_baseline(sym, initial_capital)
            eng_results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r['n_trades']:>6} {r['win_rate']*100:>5.1f}% "
                    f"{r['profit_factor']:>5.2f} {r['max_drawdown']*100:>5.1f}% "
                    f"{r['sharpe']:>7.2f} {r['cagr']*100:>6.1f}%"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
            eng_results.append({"symbol": sym, "error": str(exc)})

    # ---- Decorrelation ----
    print("\n=== DECORRELATION ANALYSIS ===")
    try:
        deconn = _compute_decorrelation(fbo_results, eng_results)
        print(f"  FBO-BOS trades         : {deconn['fbo_n_trades']}")
        print(f"  Engulfing trades       : {deconn['eng_n_trades']}")
        print(f"  FBO mean R-multiple    : {deconn['fbo_mean_r']:+.3f}")
        print(f"  Engulfing mean R-mult  : {deconn['eng_mean_r']:+.3f}")
        print(f"  FBO win rate           : {deconn['fbo_wr']*100:.1f}%")
        print(f"  Engulfing win rate     : {deconn['eng_wr']*100:.1f}%")
        print(f"  Temporal overlap       : {deconn['temporal_overlap_pct']*100:.1f}%")
        print(f"  Temporal decorrelation : {deconn['temporal_decorrelation']*100:.1f}%")
        if deconn["temporal_overlap_pct"] < 0.30:
            print("  -> HIGH decorrelation (< 30% exit-date overlap)")
        elif deconn["temporal_overlap_pct"] < 0.55:
            print("  -> MODERATE decorrelation (30-55% exit-date overlap)")
        else:
            print("  -> LOW decorrelation (> 55% exit-date overlap)")
    except Exception as exc:
        print(f"  Decorrelation error: {exc}")
        deconn = {}

    # ---- Comparison table ----
    print("\n=== FBO-BOS-RECLAIM vs ENGULFING COMPARISON ===")
    valid_eng = [r for r in eng_results if "error" not in r and r.get("n_trades", 0) > 0]
    if valid_eng and valid_fbo:
        eng_avg_wr = sum(r["win_rate"] * r["n_trades"] for r in valid_eng) / max(
            1, sum(r["n_trades"] for r in valid_eng)
        )
        eng_avg_cagr = sum(r["cagr"] for r in valid_eng) / len(valid_eng)
        eng_avg_sharpe = sum(r["sharpe"] for r in valid_eng) / len(valid_eng)
        eng_avg_dd = sum(r["max_drawdown"] for r in valid_eng) / len(valid_eng)

        print(f"  {'Metric':<20} {'FBO-BOS-Reclaim':>18} {'Engulfing':>12} {'Delta':>8}")
        print(f"  {'-'*60}")

        metrics = [
            ("Win Rate", fbo_agg.get("win_rate", 0) * 100, eng_avg_wr * 100, "%"),
            ("Avg CAGR", fbo_agg.get("avg_cagr", 0) * 100, eng_avg_cagr * 100, "%"),
            ("Avg Sharpe", fbo_agg.get("avg_sharpe", 0), eng_avg_sharpe, ""),
            ("Avg MaxDD", fbo_agg.get("avg_max_dd", 0) * 100, eng_avg_dd * 100, "%"),
            ("N Trades", fbo_agg.get("n_trades", 0), sum(r["n_trades"] for r in valid_eng), ""),
        ]
        for name, fbo_val, eng_val, unit in metrics:
            delta = fbo_val - eng_val
            delta_str = f"{delta:+.1f}{unit}" if unit else f"{delta:+.0f}"
            print(f"  {name:<20} {fbo_val:>15.1f}{unit} {eng_val:>10.1f}{unit} {delta_str:>8}")

    # ---- VERDICT ----
    print("\n" + "=" * 75)
    print("VERDICT: HYP-NEW-5 Failed BO + BOS + Low-Volume Reclaim")
    print("=" * 75)

    if not valid_fbo:
        verdict = "INCONCLUSIVE — No valid results (data issue?)"
        recommendation = "DEFER"
    else:
        wr = fbo_agg.get("win_rate", 0)
        pf = fbo_agg.get("avg_pf", 0)
        dd = fbo_agg.get("avg_max_dd", 0)
        sharpe = fbo_agg.get("avg_sharpe", 0)
        annual = fbo_agg.get("annual_return", 0)
        n_tr = fbo_agg.get("n_trades", 0)

        reasons = []
        positives = []
        negatives = []

        if n_tr < 30:
            negatives.append(f"LOW SAMPLE SIZE: only {n_tr} total trades across 10 symbols (underpowered)")
        else:
            positives.append(f"Adequate sample: {n_tr} trades")

        if wr >= 0.65:
            positives.append(f"WIN RATE {wr*100:.1f}% >= 65% threshold (literature: 70-78%)")
        elif wr >= 0.55:
            reasons.append(f"Win rate {wr*100:.1f}% below 65% target but > 55%")
        else:
            negatives.append(f"LOW WIN RATE: {wr*100:.1f}% (target 70-78%)")

        if pf >= 1.5:
            positives.append(f"PROFIT FACTOR {pf:.2f} >= 1.5")
        elif pf >= 1.2:
            reasons.append(f"Profit factor {pf:.2f} marginal (target >= 1.5)")
        else:
            negatives.append(f"LOW PROFIT FACTOR: {pf:.2f}")

        if dd <= 0.20:
            positives.append(f"MaxDD {dd*100:.1f}% within 20% target")
        else:
            negatives.append(f"HIGH DRAWDOWN: {dd*100:.1f}% (target <= 20%)")

        if sharpe >= 1.5:
            positives.append(f"Sharpe {sharpe:.2f} >= 1.5")
        elif sharpe >= 0.8:
            reasons.append(f"Sharpe {sharpe:.2f} below 1.5 target")
        else:
            negatives.append(f"LOW SHARPE: {sharpe:.2f}")

        # Verdict logic
        n_pass = (
            (wr >= 0.65) +
            (pf >= 1.5) +
            (dd <= 0.20) +
            (sharpe >= 1.5) +
            (n_tr >= 30)
        )

        if n_pass >= 4 and n_tr >= 30:
            recommendation = "PROMOTE"
            verdict = "STRONG EDGE — 3-concept confluence confirmed on real data."
        elif n_pass >= 3 and n_tr >= 20:
            recommendation = "PROMOTE (conditional)"
            verdict = "MARGINAL-TO-STRONG EDGE — Promote with portfolio monitoring."
        elif n_pass >= 2 and n_tr >= 15:
            recommendation = "DEFER"
            verdict = "MARGINAL EDGE — More data/parameter refinement needed."
        elif n_tr < 20:
            recommendation = "DEFER (sample too small)"
            verdict = "UNDERPOWERED — Insufficient trade count for statistical confidence."
        else:
            recommendation = "REJECT"
            verdict = "NO EDGE — Real data fails to confirm theoretical edge."

        print(f"  Recommendation : {recommendation}")
        print(f"  Summary        : {verdict}")
        print()
        print("  Positives:")
        for p in positives:
            print(f"    + {p}")
        if reasons:
            print("  Cautions:")
            for r in reasons:
                print(f"    ~ {r}")
        if negatives:
            print("  Negatives:")
            for neg in negatives:
                print(f"    - {neg}")

        print()
        print("  Critical question: 3-concept synergy real data edge?")
        if wr >= 0.60 and pf >= 1.2:
            print("  -> YES: Brooks + SMC + VSA confluence shows POSITIVE expectancy on real crypto.")
            print("     Edge mechanism validated: trap mechanics work within BOS + no-supply context.")
        elif wr >= 0.50 and pf >= 1.0:
            print("  -> MAYBE: Positive expectancy but below literature expectations.")
            print("     Consider: longer lookback, relaxed volume threshold, or higher timeframe BOS.")
        else:
            print("  -> NO: Real data does not support theoretical 70-78% WR claim.")
            print("     Possible causes: 1d crypto too fast for 3-bar reclaim window;")
            print("     BOS + FBO co-occurrence too rare; volume filter too strict.")

    print("=" * 75)

    # ---- Save report ----
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = ROOT / "reports" / "backtests" / f"hyp_new5_failed_bo_bos_{ts_str}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove non-serializable fields
    save_fbo = [{k: v for k, v in r.items() if k != "trades_df"} for r in fbo_results]
    save_eng = [{k: v for k, v in r.items() if k != "trades_df"} for r in eng_results]

    report = {
        "hypothesis": "HYP-NEW-5",
        "title": "Failed BO + BOS + Low-Volume Reclaim",
        "generated": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "fbo_results": save_fbo,
        "eng_results": save_eng,
        "fbo_aggregate": fbo_agg,
        "decorrelation": deconn,
        "recommendation": recommendation,
    }
    report_path.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")
    print(f"\nReport saved: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
