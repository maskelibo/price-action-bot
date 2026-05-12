"""Engulfing Continuation 4h — Full Backtest.

Compares 4h variant against 1d baseline:
  - Per-symbol results
  - Aggregate (equal-weight) results
  - Yearly breakdown
  - DSR (López de Prado, multiple-testing correction)
  - Combined portfolio: 1d + 4h on shared $10K

1d baseline reference (from prior run):
  Trades: 166 | WinRate: ~44% | Sharpe: 0.37 | CAGR: ~68%/yr | DSR: 0.18

Usage:
    PYTHONPATH=src python scripts/run_engulfing_4h_backtest.py
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
# Data loading
# =====================================================================

def _load_symbol_ohlcv(symbol: str, tf: str = "4h", venue: str = "binance") -> pd.DataFrame:
    import duckdb
    db_path = ROOT / "data" / "market.duckdb"
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
# 4h manifest factory
# =====================================================================

def _make_4h_manifest():
    from price_action.strategies.engulfing_continuation_4h import _default_4h_manifest
    return _default_4h_manifest()


# =====================================================================
# 1d engulfing manifest (baseline)
# =====================================================================

def _make_1d_manifest():
    from price_action.strategies.engulfing_continuation import _default_manifest
    return _default_manifest()


# =====================================================================
# Per-symbol run helper
# =====================================================================

def _run_symbol(symbol: str, manifest, strategy_cls, tf: str, initial_capital: float = 10_000.0) -> dict:
    from price_action.backtest.engine import BacktestEngine

    df = _load_symbol_ohlcv(symbol, tf=tf)
    if df.empty:
        return {"symbol": symbol, "tf": tf, "error": "no data"}

    strategy = strategy_cls(manifest)
    df_feats = strategy.prepare_features(df)
    signals = strategy.generate_signals(df_feats)

    def ohlcv_provider(_sym, _tf, _start, _end):
        return df_feats.copy()

    engine = BacktestEngine(risk_officer=None, store_load=None)
    result = engine.run(
        strategy,
        [symbol],
        start=df["ts"].iloc[0].to_pydatetime(),
        end=df["ts"].iloc[-1].to_pydatetime(),
        timeframe=tf,
        initial_capital=initial_capital,
        fees={"taker": 0.00075, "maker": -0.00010},
        slippage_bps=5.0,
        ohlcv_provider=ohlcv_provider,
    )
    k = result.kpis
    return {
        "symbol": symbol,
        "tf": tf,
        "n_bars": len(df),
        "first_ts": str(df["ts"].iloc[0].date()),
        "last_ts": str(df["ts"].iloc[-1].date()),
        "n_signals": len(signals),
        "n_trades": result.n_trades,
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
        "elapsed_sec": result.elapsed_sec,
        "equity_curve": result.equity_curve,
        "trades_df": result.trades,
    }


# =====================================================================
# Yearly breakdown
# =====================================================================

def _yearly_breakdown(results: list[dict]) -> dict[int, dict]:
    """Aggregate net PnL and trade count by calendar year across all symbols."""
    by_year: dict[int, dict] = {}
    for r in results:
        if "error" in r or r.get("trades_df") is None:
            continue
        tdf = r["trades_df"]
        if tdf is None or tdf.empty or "exit_ts" not in tdf.columns:
            continue
        tdf = tdf.copy()
        tdf["exit_ts"] = pd.to_datetime(tdf["exit_ts"], utc=True)
        tdf["year"] = tdf["exit_ts"].dt.year
        for yr, grp in tdf.groupby("year"):
            yr = int(yr)
            if yr not in by_year:
                by_year[yr] = {"n_trades": 0, "net_pnl": 0.0, "wins": 0}
            by_year[yr]["n_trades"] += len(grp)
            by_year[yr]["net_pnl"] += float(grp["realized_pnl_usdt"].sum())
            by_year[yr]["wins"] += int((grp["realized_pnl_usdt"] > 0).sum())
    for yr, d in by_year.items():
        d["win_rate"] = d["wins"] / max(1, d["n_trades"])
    return by_year


# =====================================================================
# DSR computation (aggregate)
# =====================================================================

def _compute_aggregate_dsr(results: list[dict], n_trials: int = 1) -> float:
    from price_action.backtest.metrics import deflated_sharpe_ratio
    sharpe_vals = [r["sharpe"] for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    if not sharpe_vals:
        return 0.0
    avg_sr = float(np.mean(sharpe_vals))
    sr_var = float(np.var(sharpe_vals)) if len(sharpe_vals) > 1 else 1.0
    # n_obs = total 4h bars across all symbols / num symbols
    total_bars = sum(r.get("n_bars", 0) for r in results if "error" not in r)
    n_sym = max(1, len(sharpe_vals))
    n_obs = total_bars // n_sym
    return deflated_sharpe_ratio(
        avg_sr,
        n_trials=max(2, n_trials),
        sr_variance=max(sr_var, 0.01),
        n_obs=n_obs,
    )


# =====================================================================
# Aggregate stats printer
# =====================================================================

def _print_aggregate(results: list[dict], label: str, initial_capital: float = 10_000.0) -> dict:
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    print(f"\n{'='*75}")
    print(f"AGGREGATE — {label}")
    print("=" * 75)
    if not valid:
        print("  No valid symbols with trades.")
        return {}

    n_trades = sum(r["n_trades"] for r in valid)
    avg_win = sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades)
    net_pnl = sum(r["net_pnl"] for r in valid)
    starting_equity = initial_capital * len(valid)
    total_return = net_pnl / starting_equity
    avg_dd = sum(r["max_drawdown"] for r in valid) / len(valid)
    avg_sharpe = sum(r["sharpe"] for r in valid) / len(valid)
    avg_cagr = sum(r["cagr"] for r in valid) / len(valid)
    avg_pf = sum(r["profit_factor"] for r in valid) / len(valid)
    annual = (((1 + total_return) ** (1 / 3)) - 1) * 100 if total_return > -1 else float("-inf")
    dsr = _compute_aggregate_dsr(results, n_trials=2)

    print(f"  Sembol (gecen)     : {len(valid)}/{len(results)}")
    print(f"  Toplam trade       : {n_trades}")
    print(f"  Win rate (agg)     : {avg_win*100:.1f}%")
    print(f"  Net P&L            : ${net_pnl:+,.0f}")
    print(f"  Aggregate 3y ret   : {total_return*100:+.1f}%")
    print(f"  Annualized         : {annual:+.1f}%/yr")
    print(f"  Avg MaxDD          : {avg_dd*100:.1f}%")
    print(f"  Avg Sharpe         : {avg_sharpe:.3f}")
    print(f"  Avg CAGR           : {avg_cagr*100:.1f}%")
    print(f"  Avg PF             : {avg_pf:.2f}")
    print(f"  DSR (agg)          : {dsr:.4f}")

    return {
        "n_trades": n_trades, "win_rate": avg_win, "net_pnl": net_pnl,
        "annual_pct": annual, "max_drawdown": avg_dd,
        "sharpe": avg_sharpe, "cagr": avg_cagr, "pf": avg_pf, "dsr": dsr,
        "n_symbols": len(valid),
    }


# =====================================================================
# Combined portfolio (1d + 4h on shared $10K)
# =====================================================================

def _combined_portfolio(
    results_1d: list[dict],
    results_4h: list[dict],
    initial_capital: float = 10_000.0,
) -> None:
    """Merge 1d + 4h trades and compute combined stats on shared capital."""
    all_trades: list[pd.DataFrame] = []
    for r in results_1d + results_4h:
        tdf = r.get("trades_df")
        if tdf is not None and not tdf.empty:
            all_trades.append(tdf)
    if not all_trades:
        print("\n[COMBINED] No trades to combine.")
        return

    combined = pd.concat(all_trades, ignore_index=True)
    combined["exit_ts"] = pd.to_datetime(combined["exit_ts"], utc=True)
    combined = combined.sort_values("exit_ts")
    pnl = combined["realized_pnl_usdt"]
    net = float(pnl.sum())
    wins = int((pnl > 0).sum())
    total = len(pnl)
    win_r = wins / max(1, total)
    cum_eq = initial_capital + pnl.cumsum()
    dd_series = cum_eq / cum_eq.cummax() - 1.0
    max_dd = float(dd_series.min())

    # Simple annualized return over 3y
    total_ret = net / initial_capital
    annual = (((1 + total_ret) ** (1 / 3)) - 1) * 100 if total_ret > -1 else float("-inf")

    print(f"\n{'='*75}")
    print("COMBINED PORTFOLIO (1d Engulfing + 4h Engulfing, shared $10K)")
    print("=" * 75)
    print(f"  Toplam trade       : {total}")
    print(f"  Win rate           : {win_r*100:.1f}%")
    print(f"  Net P&L            : ${net:+,.0f}")
    print(f"  Annualized         : {annual:+.1f}%/yr")
    print(f"  Max DD             : {max_dd*100:.1f}%")
    print()
    if annual > 0 and max_dd > -0.50:
        print("  NOTE: Combined increases trade count but capital is shared.")
        print("  Calmar ratio may suffer if DD overlap is high.")
    else:
        print("  WARNING: Combined portfolio is net negative or DD > 50%.")


# =====================================================================
# Main
# =====================================================================

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
]

# 1d baseline reference (from prior engulfing_continuation backtest)
BASELINE_1D = {
    "trades": 166,
    "win_rate": 0.44,
    "sharpe": 0.37,
    "max_drawdown": -0.18,
    "annual_pct": 68.0,
    "dsr": 0.18,
    "label": "1d Engulfing (baseline)",
}


def main() -> int:
    from price_action.strategies.engulfing_continuation_4h import (
        EngulfingContinuation4HStrategy,
        _default_4h_manifest,
    )
    from price_action.strategies.engulfing_continuation import (
        EngulfingContinuationStrategy,
        _default_manifest as _1d_manifest,
    )

    print("=" * 75)
    print("ENGULFING CONTINUATION — 4h BACKTEST")
    print("Hypothesis: 2026-05-09-engulfing-4h-frequency")
    print("=" * 75)

    # ---- 4h run ----
    manifest_4h = _default_4h_manifest()
    results_4h: list[dict] = []
    print(f"\n[4h] Running {len(SYMBOLS)} symbols ...")
    for sym in SYMBOLS:
        try:
            r = _run_symbol(sym, manifest_4h, EngulfingContinuation4HStrategy, "4h")
            results_4h.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} bars={r['n_bars']:>5} sigs={r['n_signals']:>4} "
                    f"trades={r['n_trades']:>4} win={r['win_rate']*100:>5.1f}% "
                    f"DD={r['max_drawdown']*100:>5.1f}% "
                    f"Sharpe={r['sharpe']:>5.2f} CAGR={r['cagr']*100:>6.1f}% "
                    f"({r['elapsed_sec']:.1f}s)"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            results_4h.append({"symbol": sym, "tf": "4h", "error": str(exc)})

    agg_4h = _print_aggregate(results_4h, "4h Engulfing Continuation")

    # ---- Yearly breakdown (4h) ----
    yearly_4h = _yearly_breakdown(results_4h)
    if yearly_4h:
        print("\n--- YEARLY BREAKDOWN (4h) ---")
        for yr in sorted(yearly_4h.keys()):
            d = yearly_4h[yr]
            print(f"  {yr}: trades={d['n_trades']:>4}  net_pnl=${d['net_pnl']:>+9,.0f}  win={d['win_rate']*100:.1f}%")

    # ---- 1d run (for combined portfolio) ----
    print(f"\n[1d] Running {len(SYMBOLS)} symbols for combined portfolio ...")
    manifest_1d = _1d_manifest()
    results_1d: list[dict] = []
    for sym in SYMBOLS:
        try:
            r = _run_symbol(sym, manifest_1d, EngulfingContinuationStrategy, "1d")
            results_1d.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} bars={r['n_bars']:>5} sigs={r['n_signals']:>4} "
                    f"trades={r['n_trades']:>4} win={r['win_rate']*100:>5.1f}% "
                    f"DD={r['max_drawdown']*100:>5.1f}% "
                    f"Sharpe={r['sharpe']:>5.2f} CAGR={r['cagr']*100:>6.1f}% "
                    f"({r['elapsed_sec']:.1f}s)"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
            results_1d.append({"symbol": sym, "tf": "1d", "error": str(exc)})

    agg_1d = _print_aggregate(results_1d, "1d Engulfing Continuation (live run)")

    # ---- Combined portfolio ----
    _combined_portfolio(results_1d, results_4h, initial_capital=10_000.0)

    # ---- Comparison table ----
    print(f"\n{'='*75}")
    print("COMPARISON: 4h vs 1d Engulfing Continuation")
    print("=" * 75)
    rows = [
        ("Metric", "1d Baseline (ref)", "1d (live run)", "4h Strategy"),
        ("-" * 22, "-" * 18, "-" * 15, "-" * 15),
        ("Trades (3y, 10 sym)",
         str(BASELINE_1D["trades"]),
         str(agg_1d.get("n_trades", "N/A")),
         str(agg_4h.get("n_trades", "N/A"))),
        ("Win rate",
         f"{BASELINE_1D['win_rate']*100:.1f}%",
         f"{agg_1d.get('win_rate',0)*100:.1f}%",
         f"{agg_4h.get('win_rate',0)*100:.1f}%"),
        ("Avg Sharpe",
         f"{BASELINE_1D['sharpe']:.3f}",
         f"{agg_1d.get('sharpe',0):.3f}",
         f"{agg_4h.get('sharpe',0):.3f}"),
        ("Avg MaxDD",
         f"{BASELINE_1D['max_drawdown']*100:.1f}%",
         f"{agg_1d.get('max_drawdown',0)*100:.1f}%",
         f"{agg_4h.get('max_drawdown',0)*100:.1f}%"),
        ("Annualized return",
         f"{BASELINE_1D['annual_pct']:+.1f}%",
         f"{agg_1d.get('annual_pct',0):+.1f}%",
         f"{agg_4h.get('annual_pct',0):+.1f}%"),
        ("DSR",
         f"{BASELINE_1D['dsr']:.4f}",
         "N/A",
         f"{agg_4h.get('dsr',0):.4f}"),
    ]
    for row in rows:
        print(f"  {row[0]:<22} | {row[1]:<18} | {row[2]:<15} | {row[3]}")

    # ---- Verdict ----
    print(f"\n{'='*75}")
    print("VERDICT")
    print("=" * 75)
    dsr_4h = float(agg_4h.get("dsr", 0))
    wr_4h = float(agg_4h.get("win_rate", 0))
    ann_4h = float(agg_4h.get("annual_pct", 0))
    dd_4h = float(agg_4h.get("max_drawdown", 0))
    trades_4h = int(agg_4h.get("n_trades", 0))

    promote = (dsr_4h >= 0.35 and wr_4h >= 0.38 and ann_4h >= 25.0 and dd_4h >= -0.30)
    supplement = (dsr_4h >= 0.20 and ann_4h > 0 and not promote)
    reject = not promote and not supplement

    if promote:
        verdict = "PROMOTE — 4h as primary tradeable strategy"
        detail = (
            f"DSR {dsr_4h:.4f} (>0.35) + WinRate {wr_4h*100:.1f}% (>38%) + "
            f"CAGR {ann_4h:+.1f}% (>25%). Statistical significance improved. "
            "4h frequency resolves DSR marginal 0.18 issue."
        )
    elif supplement:
        verdict = "SUPPLEMENT — 4h adds trades alongside 1d, but not primary"
        detail = (
            f"DSR {dsr_4h:.4f} (>=0.20 but <0.35) or metrics borderline. "
            "Use 4h to boost signal count; keep 1d as primary timeframe."
        )
    else:
        verdict = "REJECT — noise wins, 4h edge insufficient"
        detail = (
            f"DSR {dsr_4h:.4f} (<0.20), WinRate {wr_4h*100:.1f}%, "
            f"CAGR {ann_4h:+.1f}%. Fee drag or noise destroys edge at 4h frequency."
        )

    print(f"\n  >> {verdict}")
    print(f"  {detail}")

    # DSR improvement analysis
    dsr_1d_ref = BASELINE_1D["dsr"]
    print(f"\n  DSR improvement: {dsr_1d_ref:.4f} (1d ref) -> {dsr_4h:.4f} (4h)")
    if dsr_4h > dsr_1d_ref:
        delta_pct = (dsr_4h - dsr_1d_ref) / max(dsr_1d_ref, 1e-6) * 100
        print(f"  DSR improved by {delta_pct:.1f}% with more samples.")
        if dsr_4h >= 0.35:
            print("  CRITICAL: More samples pushed DSR into tradeable territory.")
            print("  4h primary trade is statistically justified.")
        else:
            print("  Improvement insufficient for primary classification.")
    else:
        print("  DSR did NOT improve despite more trades — 4h edge is weaker per-trade.")

    # Save report
    report = {
        "run_ts": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "2026-05-09-engulfing-4h-frequency",
        "verdict": verdict,
        "agg_4h": {k: v for k, v in agg_4h.items() if not isinstance(v, (pd.Series, pd.DataFrame))},
        "agg_1d": {k: v for k, v in agg_1d.items() if not isinstance(v, (pd.Series, pd.DataFrame))},
        "baseline_1d_ref": BASELINE_1D,
        "yearly_4h": yearly_4h,
        "symbol_results_4h": [
            {k: v for k, v in r.items() if k not in ("equity_curve", "trades_df")}
            for r in results_4h
        ],
    }
    report_path = ROOT / "reports" / "backtests" / f"engulfing_4h_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")
    print(f"\nDetay rapor: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
