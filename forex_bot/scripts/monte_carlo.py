"""Monte Carlo shuffle over a completed backtest.

Usage:
    python -m forex_bot.scripts.monte_carlo --pair EURUSD --start 2022-01-01 --end 2026-01-01 --use-synthetic --iter 1000
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from ..backtest.costs import CostModel
from ..backtest.engine import BacktestEngine, EngineConfig
from ..backtest.monte_carlo import monte_carlo_shuffle
from ..data.synthetic import generate_synthetic_ohlcv
from ..risk.officer import RiskConfig, RiskOfficer
from ..signals.generator import SignalGenerator
from ..strategies import LondonBreakoutStrategy, NyOpenReversalStrategy, AsiaRangeFadeStrategy


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--pair", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--use-synthetic", action="store_true")
    p.add_argument("--iter", type=int, default=1000)
    args = p.parse_args(argv)
    df = generate_synthetic_ohlcv(args.pair, args.start, args.end)
    strategies = [LondonBreakoutStrategy(), NyOpenReversalStrategy(), AsiaRangeFadeStrategy()]
    gen = SignalGenerator(pair=args.pair, strategies=strategies)
    signals = gen.generate(df)
    res = BacktestEngine(RiskOfficer(RiskConfig()), CostModel(), EngineConfig()).run(df, signals, pair=args.pair)
    print(f"trades = {res.n_trades}")
    if res.n_trades:
        mc = monte_carlo_shuffle(res.trades, n_iter=args.iter, initial=res.initial_balance)
        print(mc)


if __name__ == "__main__":
    raise SystemExit(main())
