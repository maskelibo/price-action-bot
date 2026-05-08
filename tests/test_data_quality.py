"""Data quality testleri — gap / duplicate / OHLC sanity / volume outlier."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.data.quality import (
    QualityReport,
    detect_duplicates,
    detect_gaps,
    detect_ohlc_violations,
    detect_price_jumps,
    detect_stale,
    detect_volume_outliers,
    run_quality_checks,
    write_daily_manifest,
)


def test_detect_gaps(gap_ohlcv: pd.DataFrame) -> None:
    n_gaps, examples = detect_gaps(gap_ohlcv, "1d")
    assert n_gaps == 2
    assert len(examples) == 2
    assert "2024-01-03" in examples[0]


def test_detect_no_gaps(random_ohlcv: pd.DataFrame) -> None:
    n_gaps, _ = detect_gaps(random_ohlcv, "1d")
    assert n_gaps == 0


def test_detect_duplicates(duplicate_ohlcv: pd.DataFrame) -> None:
    n_dup = detect_duplicates(duplicate_ohlcv)
    assert n_dup >= 2  # iki kayıt aynı PK


def test_detect_ohlc_violation_clean(random_ohlcv: pd.DataFrame) -> None:
    assert detect_ohlc_violations(random_ohlcv) == 0


def test_detect_ohlc_violation_dirty() -> None:
    df = pd.DataFrame(
        {
            "open": [100, 100],
            "high": [99, 105],   # ilk: high < open!
            "low":  [98, 99],
            "close":[101, 102],  # ilk: close > high
        }
    )
    assert detect_ohlc_violations(df) >= 1


def test_detect_volume_outliers() -> None:
    rng = np.random.default_rng(0)
    v = pd.Series(rng.normal(1000, 50, size=200))
    df = pd.DataFrame({"volume": v.tolist()})
    df.loc[100, "volume"] = 1_000_000  # büyük outlier
    assert detect_volume_outliers(df, z_threshold=8.0) >= 1


def test_detect_price_jumps() -> None:
    df = pd.DataFrame({"close": [100, 101, 200, 200.5]})
    assert detect_price_jumps(df, max_pct=0.30) >= 1


def test_detect_stale_when_old() -> None:
    df = pd.DataFrame({"ts": [pd.Timestamp("2020-01-01", tz="UTC")]})
    stale, age = detect_stale(df, "1d", now=datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert stale is True
    assert age and age > 0


def test_run_quality_checks_smoke(random_ohlcv: pd.DataFrame) -> None:
    rep = run_quality_checks(
        random_ohlcv,
        venue="binance",
        symbol="TEST/USDT",
        timeframe="1d",
        now=datetime(2023, 12, 31, tzinfo=timezone.utc),
    )
    assert isinstance(rep, QualityReport)
    assert rep.rows == len(random_ohlcv)
    assert rep.duplicates == 0
    assert rep.ohlc_violations == 0


def test_write_daily_manifest(tmp_path) -> None:
    rep = QualityReport(
        venue="binance",
        symbol="BTC/USDT",
        timeframe="1d",
        rows=10,
        start="2024-01-01",
        end="2024-01-10",
    )
    p = write_daily_manifest([rep], out_dir=tmp_path, date=datetime(2024, 5, 8, tzinfo=timezone.utc))
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "BTC/USDT" in text


# ---------------------------------------------------------------------------
# Store roundtrip (DuckDB) — local, no network
# ---------------------------------------------------------------------------
def test_store_upsert_and_read(tmp_path, random_ohlcv: pd.DataFrame) -> None:
    from price_action.data.store import OHLCVStore

    store = OHLCVStore(
        duckdb_path=tmp_path / "m.duckdb",
        parquet_root=tmp_path / "parquet",
    )
    n = store.upsert(random_ohlcv, also_parquet=True)
    assert n == len(random_ohlcv)
    df = store.read("TEST/USDT", "1d")
    assert len(df) == len(random_ohlcv)
    assert df["ts"].is_monotonic_increasing


def test_store_upsert_idempotent(tmp_path, random_ohlcv: pd.DataFrame) -> None:
    from price_action.data.store import OHLCVStore

    store = OHLCVStore(
        duckdb_path=tmp_path / "m.duckdb",
        parquet_root=tmp_path / "parquet",
    )
    store.upsert(random_ohlcv)
    store.upsert(random_ohlcv)  # tekrar
    df = store.read("TEST/USDT", "1d")
    assert len(df) == len(random_ohlcv)  # duplicate yok


@pytest.mark.integration
def test_ccxt_universe() -> None:  # pragma: no cover - integration
    """Sadece PA_RUN_INTEGRATION=1 iken çalışır."""
    from price_action.data.universe import build_universe

    insts = build_universe("manual")
    assert isinstance(insts, list)
