"""Backtest using REAL Dukascopy tick-derived 15m bars from DuckDB store.

Auto-detects all pairs in store and runs backtest with 3 risk profiles.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from ..backtest.costs import CostModel
from ..backtest.engine import BacktestEngine, EngineConfig
from ..backtest.monte_carlo import monte_carlo_shuffle
from ..data.store import OHLCVStore
from ..news.guard import NewsGuard
from ..reporting.compare_crypto import write_comparison_report
from ..reporting.html_report import write_html_report
from ..risk.officer import RiskConfig, RiskOfficer
from ..settings import DUCKDB_PATH, PARQUET_DIR, REPORTS_DIR
from ..signals.generator import GeneratorConfig, SignalGenerator
from ..strategies import (
    AsiaRangeFadeStrategy, EngulfingSessionStrategy, FVGFillStrategy,
    LondonBreakoutStrategy, NyOpenReversalStrategy, OBRetestContinuationStrategy,
    PinBarSessionStrategy, SMCLiquiditySweepStrategy,
)

PROFILES = {
    "retail_1x30":     RiskConfig(risk_per_trade_pct=0.015, leverage_max=30.0,  max_open_positions=6),
    "pro_1x200":       RiskConfig(risk_per_trade_pct=0.025, leverage_max=200.0, max_open_positions=8),
    "crypto_eq_1x500": RiskConfig(risk_per_trade_pct=0.030, leverage_max=500.0, max_open_positions=10),
}

STRATS = (
    LondonBreakoutStrategy, NyOpenReversalStrategy, AsiaRangeFadeStrategy,
    SMCLiquiditySweepStrategy, OBRetestContinuationStrategy,
    FVGFillStrategy, PinBarSessionStrategy, EngulfingSessionStrategy,
)


def list_pairs():
    conn = duckdb.connect(str(DUCKDB_PATH))
    df = conn.execute(
        "SELECT pair, COUNT(*) AS bars, MIN(ts) AS first, MAX(ts) AS last "
        "FROM forex_ohlcv WHERE timeframe='15m' GROUP BY pair ORDER BY pair"
    ).df()
    return df


def run_one(pair: str, df: pd.DataFrame, risk_cfg: RiskConfig):
    strategies = [cls() for cls in STRATS]
    news = NewsGuard()
    gen = SignalGenerator(pair=pair, strategies=strategies, config=GeneratorConfig(), news_guard=news)
    signals = gen.generate(df)
    engine = BacktestEngine(RiskOfficer(risk_cfg), CostModel(), EngineConfig(), news_guard=news)
    result = engine.run(df, signals, pair=pair, timeframe="15m")
    return result, len(signals)


def main():
    pairs_df = list_pairs()
    if pairs_df.empty:
        print("NO pairs in DuckDB. Run dukascopy_concurrent first.")
        return
    print("=== Pairs in DuckDB (real Dukascopy tick-derived 15m bars) ===")
    print(pairs_df)
    print()
    store = OHLCVStore(DUCKDB_PATH, PARQUET_DIR)
    summary = {}
    for profile_name, risk_cfg in PROFILES.items():
        print(f"\n=== profile {profile_name} ===")
        per_pair = []
        for _, row in pairs_df.iterrows():
            pair = row["pair"]
            df = store.read_ohlcv(pair, "15m")
            if df.empty:
                continue
            result, n_signals = run_one(pair, df, risk_cfg)
            r = {
                "pair": pair, "bars": len(df), "n_signals": n_signals,
                "n_trades": result.n_trades, "initial": result.initial_balance,
                "final": result.final_balance, **result.kpis,
            }
            print(f"  [{profile_name}/{pair}] bars={len(df):5d} signals={n_signals:3d} "
                  f"trades={result.n_trades:3d} ROI={r.get('return_total_pct',0):7.2f}% "
                  f"DD={r.get('max_dd_pct',0):6.2f}% WR={r.get('win_rate',0):.2f} "
                  f"PF={r.get('profit_factor',0):.2f}")
            per_pair.append(r)
        if not per_pair:
            continue
        keys = ["return_total_pct", "cagr_pct", "max_dd_pct", "sharpe", "win_rate", "profit_factor"]
        agg = {"n_trades": sum(r["n_trades"] for r in per_pair), "n_pairs": len(per_pair)}
        for k in keys:
            vals = [r.get(k) for r in per_pair if r.get(k) is not None]
            if vals:
                agg[k] = sum(vals) / len(vals)
        agg["portfolio_roi_pct"] = (sum(r["final"] for r in per_pair) / max(1, sum(r["initial"] for r in per_pair)) - 1.0) * 100.0
        print(f"  [{profile_name}] AGG: portfolio_ROI={agg['portfolio_roi_pct']:.2f}% mean_ROI={agg.get('return_total_pct',0):.2f}% mean_DD={agg.get('max_dd_pct',0):.2f}% mean_WR={agg.get('win_rate',0):.2f} mean_PF={agg.get('profit_factor',0):.2f}")
        summary[profile_name] = {"per_pair": per_pair, "aggregate": agg}

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_json = REPORTS_DIR / f"forex_real_dukascopy_{ts}.json"
    out_json.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {out_json}")
    return summary


if __name__ == "__main__":
    main()
