"""Backtest paketi — engine, walk-forward, metrics, report."""
from __future__ import annotations

from price_action.backtest.engine import BacktestEngine, BacktestResult
from price_action.backtest.metrics import compute_kpis
from price_action.backtest.slippage import (
    SlippageModel,
    build_slippage_map,
    build_slippage_model,
    FALLBACK_SLIPPAGE_BPS,
)
from price_action.backtest.walk_forward import WalkForward, WFResult, multiple_testing_correction

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "SlippageModel",
    "WFResult",
    "WalkForward",
    "build_slippage_map",
    "build_slippage_model",
    "compute_kpis",
    "FALLBACK_SLIPPAGE_BPS",
    "multiple_testing_correction",
]
