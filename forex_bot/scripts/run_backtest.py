"""Full forex backtest harness.

Usage:
    python -m forex_bot.scripts.run_backtest --pair EURUSD --start 2022-01-01 --end 2026-01-01 --use-synthetic
    python -m forex_bot.scripts.run_backtest --all --start 2022-01-01 --end 2026-01-01
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..backtest.costs import CostModel
from ..backtest.engine import BacktestEngine, EngineConfig
from ..data.store import OHLCVStore
from ..data.synthetic import generate_synthetic_ohlcv
from ..news.guard import NewsGuard
from ..reporting.html_report import write_html_report
from ..risk.officer import RiskConfig, RiskOfficer
from ..settings import DUCKDB_PATH, PAIRS, PARQUET_DIR, REPORTS_DIR
from ..signals.generator import SignalGenerator, GeneratorConfig
from ..strategies import (
    AsiaRangeFadeStrategy, EngulfingSessionStrategy, FVGFillStrategy,
    LondonBreakoutStrategy, NyOpenReversalStrategy, OBRetestContinuationStrategy,
    PinBarSessionStrategy, SMCLiquiditySweepStrategy,
)


STRATEGY_REGISTRY = {
    "london_breakout": LondonBreakoutStrategy,
    "ny_open_reversal": NyOpenReversalStrategy,
    "asia_range_fade": AsiaRangeFadeStrategy,
    "smc_liquidity_sweep": SMCLiquiditySweepStrategy,
    "ob_retest_continuation": OBRetestContinuationStrategy,
    "fvg_fill": FVGFillStrategy,
    "pin_bar_session": PinBarSessionStrategy,
    "engulfing_session": EngulfingSessionStrategy,
}


def run_for_pair(pair: str, start: datetime, end: datetime, use_synthetic: bool = False) -> dict:
    if use_synthetic:
        df = generate_synthetic_ohlcv(pair, start.isoformat(), end.isoformat(), timeframe="15m")
    else:
        store = OHLCVStore(DUCKDB_PATH, PARQUET_DIR)
        df = store.read_ohlcv(pair, "15m", pd.Timestamp(start), pd.Timestamp(end))
        if df.empty:
            print(f"[{pair}] no data in store; falling back to synthetic")
            df = generate_synthetic_ohlcv(pair, start.isoformat(), end.isoformat(), timeframe="15m")

    strategies = [cls() for cls in STRATEGY_REGISTRY.values()]
    news = NewsGuard()
    gen = SignalGenerator(pair=pair, strategies=strategies, config=GeneratorConfig(), news_guard=news)
    signals = gen.generate(df)
    print(f"[{pair}] generated {len(signals)} signals from {len(df)} bars")
    risk = RiskOfficer(RiskConfig())
    engine = BacktestEngine(risk, CostModel(), EngineConfig(), news_guard=news)
    result = engine.run(df, signals, pair=pair)
    out_html = REPORTS_DIR / f"forex_{pair}_{datetime.utcnow():%Y%m%d_%H%M%S}.html"
    write_html_report(out_html, f"Forex Bot — {pair}", result.trades, result.equity_curve,
                      result.initial_balance, result.final_balance)
    print(f"[{pair}] wrote {out_html}")
    return {"pair": pair, "kpis": result.kpis, "n_trades": result.n_trades,
            "final_balance": result.final_balance, "report": str(out_html)}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--pair", default=None)
    p.add_argument("--all", action="store_true")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--use-synthetic", action="store_true")
    args = p.parse_args(argv)
    pairs = PAIRS if args.all else [args.pair] if args.pair else []
    if not pairs:
        return 2
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    all_results = []
    for pair in pairs:
        all_results.append(run_for_pair(pair, start, end, args.use_synthetic))
    out_json = REPORTS_DIR / f"forex_all_kpis_{datetime.utcnow():%Y%m%d_%H%M%S}.json"
    out_json.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    print(f"[ALL] wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
