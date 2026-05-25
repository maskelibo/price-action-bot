"""Walk-forward runner.

Usage:
    python -m forex_bot.scripts.walk_forward --pair EURUSD --start 2022-01-01 --end 2026-01-01 --use-synthetic
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pandas as pd

from ..backtest.costs import CostModel
from ..backtest.engine import BacktestEngine, EngineConfig
from ..backtest.walk_forward import WalkForwardRunner
from ..data.synthetic import generate_synthetic_ohlcv
from ..risk.officer import RiskConfig, RiskOfficer
from ..signals.generator import SignalGenerator, GeneratorConfig
from ..strategies import (
    AsiaRangeFadeStrategy, EngulfingSessionStrategy, FVGFillStrategy,
    LondonBreakoutStrategy, NyOpenReversalStrategy, OBRetestContinuationStrategy,
    PinBarSessionStrategy, SMCLiquiditySweepStrategy,
)


def make_run_fn(pair: str):
    strategies = [cls() for cls in (LondonBreakoutStrategy, NyOpenReversalStrategy, AsiaRangeFadeStrategy,
                                     SMCLiquiditySweepStrategy, OBRetestContinuationStrategy,
                                     FVGFillStrategy, PinBarSessionStrategy, EngulfingSessionStrategy)]
    gen = SignalGenerator(pair=pair, strategies=strategies)

    def run_window(train_df: pd.DataFrame, test_df: pd.DataFrame) -> dict:
        signals = gen.generate(test_df)
        risk = RiskOfficer(RiskConfig())
        engine = BacktestEngine(risk, CostModel(), EngineConfig())
        res = engine.run(test_df, signals, pair=pair)
        return {**res.kpis, "n_signals": len(signals)}

    return run_window


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--pair", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--use-synthetic", action="store_true")
    args = p.parse_args(argv)
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    df = generate_synthetic_ohlcv(args.pair, args.start, args.end)
    runner = WalkForwardRunner(train_months=6, test_months=3)
    results = runner.run(df, pd.Timestamp(start), pd.Timestamp(end), make_run_fn(args.pair))
    print(f"WF windows = {len(results)}")
    pos = sum(1 for r in results if r.get("return_total_pct", 0) > 0)
    print(f"positive windows: {pos}/{len(results)}")
    for r in results:
        print(r)


if __name__ == "__main__":
    raise SystemExit(main())
