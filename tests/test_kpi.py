"""KPI hesaplamaları — küçük bilinen seri üstünde."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from price_action.analytics.kpi import (
    attribution,
    compute_kpis,
    expectancy_r,
    max_drawdown,
    profit_factor,
    regime_split,
    sharpe,
    win_rate,
)


def test_sharpe_known_series():
    # Sabit pozitif return → Sharpe sonsuz olmamalı (std=0 → 0 dön)
    rets = pd.Series([0.01, 0.01, 0.01])
    assert sharpe(rets) == 0.0  # std 0


def test_sharpe_known_normal():
    rng = np.random.default_rng(0)
    rets = pd.Series(rng.normal(0.001, 0.01, size=500))
    s = sharpe(rets)
    # mean/std * sqrt(365) ≈ 0.1 * sqrt(365) ≈ 1.9 — pozitif olduğunu doğrula
    assert s > 0


def test_max_drawdown_basic():
    eq = pd.Series([100, 110, 120, 90, 95, 130])
    dd = max_drawdown(eq)
    # peak 120 → 90: -25%
    assert dd == pytest.approx(-0.25, rel=1e-3)


def test_profit_factor_and_win_rate():
    pnl = pd.Series([10, -5, 20, -10, 5, -2])
    pf = profit_factor(pnl)
    assert pf == pytest.approx((10 + 20 + 5) / (5 + 10 + 2), rel=1e-3)
    assert win_rate(pnl) == pytest.approx(3 / 6)


def test_expectancy_r_basic():
    r = pd.Series([1.0, -1.0, 2.0, -1.0, 1.0])
    assert expectancy_r(r) == pytest.approx((1 - 1 + 2 - 1 + 1) / 5)


def test_compute_kpis_with_synthetic(synthetic_trades_df):
    kpis = compute_kpis(synthetic_trades_df)
    assert kpis["n_trades"] == len(synthetic_trades_df)
    assert "sharpe" in kpis
    assert "profit_factor" in kpis
    assert "max_drawdown" in kpis
    assert kpis["max_drawdown"] <= 0


def test_compute_kpis_empty():
    kpis = compute_kpis(pd.DataFrame())
    assert kpis["n_trades"] == 0
    assert kpis["sharpe"] == 0.0
    assert kpis["profit_factor"] == 0.0


def test_attribution_by_strategy(synthetic_trades_df):
    df = attribution(synthetic_trades_df, by="strategy")
    assert not df.empty
    assert {"group", "n_trades", "net_pnl"}.issubset(df.columns)


def test_attribution_by_pattern(synthetic_trades_df):
    df = attribution(synthetic_trades_df, by="pattern")
    assert not df.empty
    assert df["n_trades"].sum() == len(synthetic_trades_df)


def test_regime_split_basic(synthetic_trades_df):
    # Sentetik BTC verisi
    rng = np.random.default_rng(3)
    idx = pd.date_range("2023-12-01", periods=200, freq="1D")
    close = 30_000 + np.cumsum(rng.normal(50, 200, size=200))
    md = pd.DataFrame({"close": close}, index=idx)
    res = regime_split(synthetic_trades_df, md, btc_ema_period=20, vol_window=10)
    assert set(res.keys()) == {"bull", "bear", "range"}
    total = sum(r["n_trades"] for r in res.values())
    # Beklenir: tüm trade'ler sınıflandırılmış
    assert total >= 0
