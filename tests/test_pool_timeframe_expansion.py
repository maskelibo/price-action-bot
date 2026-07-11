"""30m/1h/4h pool expansion contract tests.

These tests keep the research pool builder and the shared Signal contract in
sync.  A timeframe is not usable merely because ``bot_factory`` accepts its
name; strategies must also be able to emit a validated Signal for it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest
from scripts.build_pool_1h import resample_15m

from price_action.contracts import Signal
from price_action.strategies.manifest_loader import normalize_tf


def _bars(n: int = 16) -> pd.DataFrame:
    ts = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    values = [float(i + 1) for i in range(n)]
    return pd.DataFrame(
        {
            "ts": ts,
            "open": values,
            "high": [v + 1.0 for v in values],
            "low": [v - 1.0 for v in values],
            "close": [v + 0.5 for v in values],
            "volume": [10.0] * n,
        }
    )


@pytest.mark.parametrize(
    ("target_tf", "expected_bars"),
    [("30m", 8), ("1h", 4), ("4h", 1)],
)
def test_resample_15m_supports_expansion_timeframes(target_tf: str, expected_bars: int) -> None:
    out, stats = resample_15m(_bars(), target_tf)

    assert len(out) == expected_bars
    assert stats["n_complete"] == expected_bars
    assert stats["n_dropped"] == 0
    assert out.iloc[0]["open"] == 1.0
    assert out.iloc[0]["volume"] == 10.0 * {"30m": 2, "1h": 4, "4h": 16}[target_tf]


def test_resample_drops_incomplete_target_bucket() -> None:
    bars = _bars(8).drop(index=3).reset_index(drop=True)

    out, stats = resample_15m(bars, "1h")

    assert len(out) == 1
    assert stats == {"n_src": 7, "n_buckets": 2, "n_complete": 1, "n_dropped": 1}
    assert out.iloc[0]["ts"] == pd.Timestamp("2026-01-01 01:00:00+00:00")


def test_signal_contract_accepts_30m() -> None:
    signal = Signal(
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        venue="binance",
        symbol="BTC/USDT",
        timeframe="30m",
        direction="long",
        pattern_id="test",
        confluence_score=1.0,
        sl_price=99.0,
        tp_price=102.0,
        suggested_size_atr=1.0,
    )

    assert signal.timeframe == "30m"


@pytest.mark.parametrize("alias", ["30m", "30min", "30minute"])
def test_manifest_loader_normalizes_30m_aliases(alias: str) -> None:
    assert normalize_tf(alias) == "30m"
