"""End-to-end backtest engine smoke tests."""
from __future__ import annotations

import pandas as pd
import pytest

from forex_bot.backtest.costs import CostModel
from forex_bot.backtest.engine import BacktestEngine, EngineConfig
from forex_bot.backtest.monte_carlo import monte_carlo_shuffle
from forex_bot.data.synthetic import generate_synthetic_ohlcv
from forex_bot.news.guard import NewsGuard
from forex_bot.risk.officer import RiskConfig, RiskOfficer
from forex_bot.signals.generator import GeneratorConfig, SignalGenerator
from forex_bot.strategies import (
    AsiaRangeFadeStrategy, EngulfingSessionStrategy, LondonBreakoutStrategy,
    NyOpenReversalStrategy, PinBarSessionStrategy, SMCLiquiditySweepStrategy,
)


@pytest.fixture
def df():
    return generate_synthetic_ohlcv("EURUSD", "2024-01-01", "2024-04-01")


def test_engine_runs(df):
    strategies = [LondonBreakoutStrategy(), NyOpenReversalStrategy(), PinBarSessionStrategy(),
                  EngulfingSessionStrategy()]
    gen = SignalGenerator(pair="EURUSD", strategies=strategies, config=GeneratorConfig(use_news_guard=False))
    signals = gen.generate(df)
    engine = BacktestEngine(RiskOfficer(RiskConfig()), CostModel(), EngineConfig())
    res = engine.run(df, signals, pair="EURUSD")
    assert res.initial_balance == 10_000.0
    assert isinstance(res.trades, pd.DataFrame)
    assert res.equity_curve.notna().all()


def test_engine_zero_signals_safe(df):
    engine = BacktestEngine(RiskOfficer(RiskConfig()), CostModel(), EngineConfig())
    res = engine.run(df, [], pair="EURUSD")
    assert res.n_trades == 0
    assert res.final_balance == res.initial_balance


def test_monte_carlo_returns(df):
    strategies = [LondonBreakoutStrategy(), NyOpenReversalStrategy()]
    gen = SignalGenerator(pair="EURUSD", strategies=strategies, config=GeneratorConfig(use_news_guard=False))
    sig = gen.generate(df)
    engine = BacktestEngine(RiskOfficer(RiskConfig()), CostModel(), EngineConfig())
    res = engine.run(df, sig, pair="EURUSD")
    if res.n_trades > 5:
        mc = monte_carlo_shuffle(res.trades, n_iter=100, initial=res.initial_balance)
        assert "p5_roi" in mc and "p95_roi" in mc
