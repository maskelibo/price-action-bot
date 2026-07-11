"""Focused tests for the pre-registered weekly XS-carry feasibility book."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from price_action.backtest.xs_carry import (
    XSCarryConfig,
    XSCarryData,
    build_weekly_returns,
    funding_rank_permutation_pvalue,
    newey_west_tstat,
    run_xs_carry_feasibility,
    summarize_returns,
)


def _funding_times(start: str, end: str) -> pd.DatetimeIndex:
    return pd.date_range(start, end, freq="8h", inclusive="left", tz="UTC")


def _synthetic_data(
    *,
    symbols: tuple[str, ...] = ("A", "B", "C", "D", "E", "F", "G", "H"),
    historical_rates: dict[str, float] | None = None,
    holding_rates: dict[str, float] | None = None,
    perp_multiplier: float = 1.0,
) -> XSCarryData:
    historical_rates = historical_rates or {
        symbol: (len(symbols) - i) * 0.0001 for i, symbol in enumerate(symbols)
    }
    holding_rates = holding_rates or historical_rates

    funding_rows: list[dict[str, object]] = []
    for symbol in symbols:
        for ts in _funding_times("2022-01-03", "2022-01-10"):
            funding_rows.append(
                {"symbol": symbol, "ts": ts, "funding_rate": historical_rates[symbol]}
            )
        # The book entered at Monday 00:00 earns the following 21 settlements.
        for ts in _funding_times("2022-01-10 08:00", "2022-01-17 08:00"):
            funding_rows.append({"symbol": symbol, "ts": ts, "funding_rate": holding_rates[symbol]})

    daily = pd.date_range("2021-12-01", "2022-01-17", freq="1D", tz="UTC")
    spot_rows: list[dict[str, object]] = []
    perp_rows: list[dict[str, object]] = []
    for i, symbol in enumerate(symbols):
        # Identical paths cancel exactly in a one-for-one spot/perp hedge.
        prices = 100.0 + i + np.arange(len(daily), dtype=float) * 0.25
        for ts, price in zip(daily, prices, strict=True):
            common = {
                "symbol": symbol,
                "ts": ts,
                "open": price,
                "close": price,
                "volume": 2_000_000.0,
            }
            spot_rows.append(common)
            perp_rows.append({**common, "open": price * perp_multiplier})

    return XSCarryData(
        funding=pd.DataFrame(funding_rows),
        spot=pd.DataFrame(spot_rows),
        perp=pd.DataFrame(perp_rows),
    )


def _one_week_config(**overrides: object) -> XSCarryConfig:
    params: dict[str, object] = {
        "start": "2022-01-10",
        "end": "2022-01-17",
        "oos_start": "2022-01-10",
        "k": 3,
        "min_liquidity_usd": 0.0,
        "permutations": 19,
        "perp_taker_fee_bps": 0.0,
        "spot_taker_fee_bps": 0.0,
        "slippage_bps_per_leg": 0.0,
        "borrow_apr": 0.0,
        "borrow_stress_apr": 0.0,
    }
    params.update(overrides)
    return XSCarryConfig(**params)


def test_weekly_rank_uses_strictly_trailing_funding_not_holding_week() -> None:
    historical = {
        "A": 8e-4,
        "B": 7e-4,
        "C": 6e-4,
        "D": 5e-4,
        "E": 4e-4,
        "F": 3e-4,
        "G": 2e-4,
        "H": 1e-4,
    }
    holding = {symbol: -rate for symbol, rate in historical.items()}
    periods = build_weekly_returns(
        _synthetic_data(historical_rates=historical, holding_rates=holding),
        _one_week_config(),
    )

    assert len(periods) == 1
    assert periods.iloc[0]["top_symbols"] == ("A", "B", "C")
    assert periods.iloc[0]["bottom_symbols"] == ("H", "G", "F")
    assert periods.iloc[0]["funding_settlements_min"] == 21


def test_identical_spot_and_perp_paths_cancel_price_direction() -> None:
    periods = build_weekly_returns(_synthetic_data(), _one_week_config())

    assert periods.iloc[0]["hedged_price_return"] == pytest.approx(0.0, abs=1e-15)
    # With pair-leg notional 1/(2k), earned funding is half the top-bottom spread.
    expected = 0.5 * 21 * ((8e-4 + 7e-4 + 6e-4) / 3 - (3e-4 + 2e-4 + 1e-4) / 3)
    assert periods.iloc[0]["funding_return"] == pytest.approx(expected)
    assert periods.iloc[0]["gross_return"] == pytest.approx(expected)


def test_full_turnover_cost_and_short_spot_borrow_are_equity_scaled() -> None:
    zero = {symbol: 0.0 for symbol in tuple("ABCDEFGH")}
    config = _one_week_config(
        perp_taker_fee_bps=5.0,
        spot_taker_fee_bps=5.0,
        slippage_bps_per_leg=3.0,
        borrow_apr=0.15,
    )
    periods = build_weekly_returns(
        _synthetic_data(historical_rates=zero, holding_rates=zero),
        config,
    )

    # Total perp notional=1 and spot notional=1: 10bp round trip on each,
    # plus 3bp slippage on gross=2. Short-spot notional is half of equity.
    expected_trading = 0.001 + 0.001 + 0.0006
    expected_borrow = 0.15 * 0.5 * 7.0 / 365.2425
    assert periods.iloc[0]["trading_cost"] == pytest.approx(expected_trading)
    assert periods.iloc[0]["borrow_cost"] == pytest.approx(expected_borrow)
    assert periods.iloc[0]["net_return"] == pytest.approx(-expected_trading - expected_borrow)


def test_complete_week_with_too_few_liquid_symbols_is_cash_not_dropped() -> None:
    periods = build_weekly_returns(
        _synthetic_data(),
        _one_week_config(min_liquidity_usd=10**15),
    )

    assert len(periods) == 1
    assert periods.iloc[0]["book_active"] is False or not periods.iloc[0]["book_active"]
    assert periods.iloc[0]["top_symbols"] == ()
    assert periods.iloc[0]["net_return"] == 0.0


def test_metrics_use_compounded_equity_base_and_calendar_annualization() -> None:
    weekly = pd.DataFrame(
        {
            "start": pd.date_range("2022-01-03", periods=4, freq="7D", tz="UTC"),
            "end": pd.date_range("2022-01-10", periods=4, freq="7D", tz="UTC"),
            "net_return": [0.10, -0.20, 0.10, 0.05],
            "btc_return": [0.02, -0.03, 0.01, 0.0],
        }
    )
    metrics = summarize_returns(weekly, return_col="net_return")

    equity = np.asarray([1.0, 1.10, 0.88, 0.968, 1.0164])
    expected_dd = abs(np.min(equity / np.maximum.accumulate(equity) - 1.0))
    expected_sharpe = (
        np.mean(weekly["net_return"])
        / np.std(weekly["net_return"], ddof=1)
        * math.sqrt(365.2425 / 7.0)
    )
    assert metrics["maxdd_equity_base_pct"] == pytest.approx(expected_dd * 100.0)
    assert metrics["calendar_sharpe"] == pytest.approx(expected_sharpe)


def test_newey_west_tstat_is_finite_and_detects_positive_mean() -> None:
    rng = np.random.default_rng(7)
    returns = pd.Series(0.01 + rng.normal(0.0, 0.005, 180))
    tstat, lag = newey_west_tstat(returns)

    assert lag >= 1
    assert math.isfinite(tstat)
    assert tstat > 2.0


def test_rank_permutation_is_seeded_and_uses_add_one_pvalue() -> None:
    data = _synthetic_data()
    config = _one_week_config(permutations=19, random_seed=42)
    periods = build_weekly_returns(data, config)

    first = funding_rank_permutation_pvalue(data, config, periods)
    second = funding_rank_permutation_pvalue(data, config, periods)

    assert first == second
    assert first["pvalue"] >= 1.0 / 20.0
    assert first["n_permutations"] == 19


def test_end_to_end_result_is_never_promotion_eligible() -> None:
    config = _one_week_config(permutations=9)
    result = run_xs_carry_feasibility(_synthetic_data(), config)
    payload = result.to_dict()

    assert payload["status"] == "FEASIBILITY_NOT_PROMOTION"
    assert payload["promotion_eligible"] is False
    assert "not delisting-inclusive" in " ".join(payload["limitations"])
    assert len(payload["reproducibility"]["data_hash_sha256"]) == 64
    assert len(payload["reproducibility"]["config_hash_sha256"]) == 64
    assert set(payload["robustness"]["leave_one_symbol_out_oos_sharpe"]) == set("ABCDEFGH")
