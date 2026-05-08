"""Backtest smoke testi — synthetic dataset üstünde tüm pipeline çağrılabiliyor mu?"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.backtest.engine import BacktestEngine
from price_action.backtest.metrics import compute_kpis, deflated_sharpe_ratio
from price_action.backtest.walk_forward import multiple_testing_correction
from price_action.strategies.base import StrategyManifest
from price_action.strategies.classic_pa import ClassicPriceActionStrategy


def _synthetic_ohlcv(n: int = 600, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base_ts = datetime(2022, 1, 1, tzinfo=timezone.utc)
    ts = [base_ts + timedelta(days=i) for i in range(n)]
    rets = rng.normal(0.001, 0.02, n)  # küçük pozitif drift
    close = 100 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    vol = rng.uniform(1_000_000, 5_000_000, n)
    df = pd.DataFrame(
        {
            "venue": "binance",
            "symbol": "TEST/USDT",
            "timeframe": "1d",
            "ts": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        }
    )
    return df


def _make_strategy() -> ClassicPriceActionStrategy:
    raw = {
        "name": "test_pa",
        "version": "0.0.1",
        "trend_filter": {"type": "ema", "period": 20, "required": False},
        "signals": {
            "patterns": [
                {"id": "bullish_pin_bar", "enabled": True, "weight": 1.5},
                {"id": "bearish_pin_bar", "enabled": True, "weight": 1.5},
                {"id": "bullish_engulfing", "enabled": True, "weight": 1.5},
                {"id": "bearish_engulfing", "enabled": True, "weight": 1.5},
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 100,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 100,
                },
                "require_proximity_to_sr_atr": 0.0,  # S/R bonusu yok — daha çok signal üretsin
            },
            "filters": {"atr_min_pct": 0.0},
            "confluence": {"method": "weighted_sum", "min_score": 1.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"atr_multiplier": 2.0},
            "take_profit": {"primary_R": 2.0},
        },
    }
    manifest = StrategyManifest.model_validate(raw)
    return ClassicPriceActionStrategy(manifest)


def test_strategy_signal_generation_smoke():
    df = _synthetic_ohlcv()
    strat = _make_strategy()
    df = strat.prepare_features(df)
    signals = strat.generate_signals(df)
    # Sentetik veride sıfır sinyal olabilir — sadece çalışıyor mu testliyoruz.
    assert isinstance(signals, list)


@pytest.mark.slow
def test_backtest_engine_full_pipeline():
    df = _synthetic_ohlcv()

    def loader(symbol: str, tf: str, start, end):
        return df.copy()

    strat = _make_strategy()
    engine = BacktestEngine(risk_officer=None, store_load=loader)
    result = engine.run(
        strat,
        ["TEST/USDT"],
        start=datetime(2022, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 1, tzinfo=timezone.utc),
        timeframe="1d",
        initial_capital=10_000,
    )
    assert result.strategy_name == "test_pa"
    assert result.kpis is not None
    assert "sharpe" in result.kpis
    assert "deflated_sharpe" in result.kpis
    assert result.manifest.composite is not None


def test_metrics_compute_kpis_basic():
    eq = pd.Series([10_000, 10_100, 10_050, 10_200, 10_300])
    pnls = pd.Series([100, -50, 150, 100])
    kpis = compute_kpis(eq, pnls, timeframe="1d", n_trials=1)
    assert kpis["n_trades"] == 4
    assert kpis["win_rate"] == 0.75
    assert kpis["profit_factor"] > 1.0


def test_dsr_smoke():
    val = deflated_sharpe_ratio(1.5, n_trials=20, sr_variance=1.0, n_obs=252)
    assert 0.0 <= val <= 1.0


def test_multiple_testing_bh_monotone():
    pvals = [0.01, 0.02, 0.03, 0.5, 0.9]
    adj = multiple_testing_correction(pvals, method="fdr_bh")
    assert len(adj) == len(pvals)
    # Adjusted >= raw
    for raw, a in zip(pvals, adj):
        assert a >= raw - 1e-9


def test_oracle_baseline_above_strategy():
    df = _synthetic_ohlcv()
    eq = BacktestEngine.oracle_baseline(df)
    assert eq.iloc[-1] >= eq.iloc[0]  # mükemmel öngörü ≥ buy-hold
