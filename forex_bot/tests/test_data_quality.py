"""Data quality + store tests."""
from __future__ import annotations

import pandas as pd

from forex_bot.data.quality import (
    count_duplicates, detect_internal_gaps, detect_ohlc_violations,
    filter_weekend, run_quality_checks,
)
from forex_bot.data.synthetic import generate_synthetic_ohlcv


def test_synthetic_no_ohlc_violations():
    df = generate_synthetic_ohlcv("EURUSD", "2024-01-01", "2024-02-01")
    v = detect_ohlc_violations(df)
    assert v == 0


def test_weekend_filter_removes_bars():
    df = generate_synthetic_ohlcv("EURUSD", "2024-01-01", "2024-01-15")
    n0 = len(df)
    df_f = filter_weekend(df)
    assert len(df_f) < n0


def test_quality_report():
    df = generate_synthetic_ohlcv("EURUSD", "2024-01-01", "2024-02-01")
    rep = run_quality_checks(df, "EURUSD", "15m")
    assert rep.rows > 0
    assert rep.ohlc_violations == 0


def test_duplicates_zero():
    df = generate_synthetic_ohlcv("EURUSD", "2024-01-01", "2024-01-15")
    assert count_duplicates(df) == 0
