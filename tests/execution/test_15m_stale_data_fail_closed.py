"""Stale scanner data must not fan out fresh per-symbol Binance clients."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from price_action.data import store as store_module
from scripts import futures_trade_15m as trade_15m


def test_stale_symbol_is_skipped_without_direct_ccxt_fallback(monkeypatch) -> None:
    old_ts = pd.Timestamp(datetime.now(UTC) - timedelta(hours=2))

    class _Store:
        def read(self, *_args, **_kwargs):
            return pd.DataFrame(
                {
                    "ts": [old_ts],
                    "open": [1.0],
                    "high": [1.0],
                    "low": [1.0],
                    "close": [1.0],
                    "volume": [1.0],
                }
            )

    monkeypatch.setattr(store_module, "OHLCVStore", _Store)
    monkeypatch.setattr(
        trade_15m,
        "_TOP_4_15M",
        [("must_not_run", "MustNotRun")],
    )

    result = trade_15m._scan_symbol("BTC/USDT", pd.Timestamp(datetime.now(UTC)))

    assert result == []
    assert not hasattr(trade_15m, "_fetch_fresh_bars_ccxt")
