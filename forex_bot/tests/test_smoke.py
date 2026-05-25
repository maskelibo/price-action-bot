"""Smoke test — runs the full pipeline end-to-end with 3 months of synthetic data."""
from __future__ import annotations

from forex_bot.scripts.smoke_run import smoke_run


def test_smoke_completes():
    summary = smoke_run(start="2024-01-01", end="2024-04-01", pairs=["EURUSD"])
    assert "EURUSD" in summary
    assert "n_trades" in summary["EURUSD"]
