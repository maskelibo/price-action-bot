"""Alt-data → OHLCV merge helpers.

Bu modül funding rate, open interest ve liquidation proxy kolonlarını
OHLCV DataFrame'ine LEFT JOIN eder.

Garantiler:
  - No forward-fill (eksik alt-data → NaN, downstream karar verir)
  - UTC consistent (her iki taraf normalize edilir)
  - Idempotent: aynı input → aynı output
  - Replay-safe

Kullanım:
    from price_action.data.alt_data.merge import (
        merge_funding_to_ohlcv_1d,
        merge_oi_to_ohlcv,
        merge_all_alt_data,
    )

    # 1d OHLCV için:
    df = merge_all_alt_data(ohlcv_df, symbol="BTCUSDT")
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from price_action.logging_config import logger
from price_action.settings import ROOT_DIR

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_utc(s: pd.Series) -> pd.Series:
    """pd.Series of timestamps → UTC tz-aware. Naive treated as UTC."""
    if not pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s, utc=True, errors="coerce")
    if s.dt.tz is None:
        return s.dt.tz_localize("UTC")
    return s.dt.tz_convert("UTC")


def _day_floor(ts_series: pd.Series) -> pd.Series:
    """Truncate timestamp to UTC calendar day (midnight)."""
    ts = _ensure_utc(ts_series)
    return ts.dt.normalize()


# ---------------------------------------------------------------------------
# Funding rate merge (8h → 1d aggregated)
# ---------------------------------------------------------------------------

def merge_funding_to_ohlcv_1d(
    ohlcv_df: pd.DataFrame,
    symbol: str,
    *,
    venue: str = "binance",
    funding_db_path: Path | None = None,
    agg_method: str = "mean",
) -> pd.DataFrame:
    """Funding rate (8h) → 1d aggregated → OHLCV LEFT JOIN.

    Columns added:
        funding_rate_1d   : daily mean (or last/max) funding rate
        funding_anomaly   : True if any 8h bar was anomalous that day

    No forward-fill: days with no funding data → NaN funding_rate_1d.

    Args:
        ohlcv_df: 1d OHLCV DataFrame (ts, open, high, low, close, volume)
        symbol: e.g. "BTCUSDT"
        venue: "binance"
        funding_db_path: None → data/funding_rates.duckdb
        agg_method: 'mean' | 'last' | 'max' (daily aggregation)
    """
    try:
        from price_action.data.alt_data.funding_rate_ingest import FundingRateStore, resample_to_daily
    except ImportError:
        logger.error("merge_funding: FundingRateStore import fail")
        ohlcv_df = ohlcv_df.copy()
        ohlcv_df["funding_rate_1d"] = float("nan")
        ohlcv_df["funding_anomaly"] = False
        return ohlcv_df

    store = FundingRateStore(funding_db_path)
    fr_df = store.read(symbol, venue=venue)

    if fr_df.empty:
        logger.warning(
            "merge_funding.no_data",
            extra={"symbol": symbol, "venue": venue,
                   "hint": "Run scripts/sec25_alt_data_ingest.py first"},
        )
        ohlcv_df = ohlcv_df.copy()
        ohlcv_df["funding_rate_1d"] = float("nan")
        ohlcv_df["funding_anomaly"] = False
        return ohlcv_df

    # Resample 8h → 1d
    fr_daily = resample_to_daily(fr_df, agg_funding=agg_method)
    fr_daily = fr_daily[fr_daily["symbol"] == symbol].copy()
    fr_daily["_day"] = _day_floor(fr_daily["ts"])
    fr_daily = fr_daily.rename(columns={"anomaly_flag": "funding_anomaly"})
    fr_daily = fr_daily[["_day", "funding_rate_1d", "funding_anomaly"]].drop_duplicates("_day")

    # Join on calendar day
    ohlcv = ohlcv_df.copy()
    ohlcv["_day"] = _day_floor(ohlcv["ts"])
    merged = ohlcv.merge(fr_daily, on="_day", how="left")
    merged = merged.drop(columns=["_day"])

    nan_count = merged["funding_rate_1d"].isna().sum()
    if nan_count > 0:
        logger.info(
            "merge_funding.nan_rows",
            extra={"symbol": symbol, "nan_count": nan_count,
                   "note": "No forward-fill — NaN surfaces missing data"},
        )

    return merged


# ---------------------------------------------------------------------------
# Open interest merge
# ---------------------------------------------------------------------------

def merge_oi_to_ohlcv(
    ohlcv_df: pd.DataFrame,
    symbol: str,
    *,
    venue: str = "bybit",
    oi_db_path: Path | None = None,
) -> pd.DataFrame:
    """Open interest (daily) → OHLCV LEFT JOIN.

    Columns added:
        oi_contracts    : raw OI (contracts)
        oi_pct_change   : daily OI % change
        oi_z_30d        : 30-day rolling z-score of OI
        oi_anomaly      : True if daily OI change > 50%

    No forward-fill: days with no OI data → NaN.
    """
    try:
        from price_action.data.alt_data.open_interest_ingest import OIStore
    except ImportError:
        logger.error("merge_oi: OIStore import fail")
        ohlcv_df = ohlcv_df.copy()
        for col in ["oi_contracts", "oi_pct_change", "oi_z_30d", "oi_anomaly"]:
            ohlcv_df[col] = float("nan")
        return ohlcv_df

    store = OIStore(oi_db_path)
    oi_df = store.read(symbol, venue=venue)

    if oi_df.empty:
        logger.warning(
            "merge_oi.no_data",
            extra={"symbol": symbol, "venue": venue,
                   "hint": "Run scripts/sec25_alt_data_ingest.py first"},
        )
        ohlcv_df = ohlcv_df.copy()
        for col in ["oi_contracts", "oi_pct_change", "oi_z_30d", "oi_anomaly"]:
            ohlcv_df[col] = float("nan")
        return ohlcv_df

    oi = oi_df.copy()
    oi["_day"] = _day_floor(oi["ts"])
    oi = oi.rename(columns={"anomaly_flag": "oi_anomaly"})
    keep_cols = ["_day", "oi_contracts", "oi_pct_change", "oi_z_30d", "oi_anomaly"]
    keep_cols = [c for c in keep_cols if c in oi.columns]
    oi = oi[keep_cols].drop_duplicates("_day")

    ohlcv = ohlcv_df.copy()
    ohlcv["_day"] = _day_floor(ohlcv["ts"])
    merged = ohlcv.merge(oi, on="_day", how="left")
    merged = merged.drop(columns=["_day"])

    nan_count = merged["oi_contracts"].isna().sum() if "oi_contracts" in merged.columns else len(merged)
    if nan_count > 0:
        logger.info(
            "merge_oi.nan_rows",
            extra={"symbol": symbol, "nan_count": nan_count,
                   "note": "No forward-fill — OI NaN = gap in data"},
        )

    return merged


# ---------------------------------------------------------------------------
# Liquidation proxy merge (computed from OHLCV, no DB needed)
# ---------------------------------------------------------------------------

def add_liquidation_proxy(
    ohlcv_df: pd.DataFrame,
    *,
    vol_z_threshold: float = 2.0,
    atr_z_threshold: float = 1.5,
    rolling_window: int = 30,
) -> pd.DataFrame:
    """OHLCV'ye liquidation proxy kolonları ekle (DB gerekmez).

    liquidation_proxy.compute_liquidation_proxy wrapper'ı.
    """
    from price_action.data.alt_data.liquidation_proxy import compute_liquidation_proxy
    return compute_liquidation_proxy(
        ohlcv_df,
        vol_z_threshold=vol_z_threshold,
        atr_z_threshold=atr_z_threshold,
        rolling_window=rolling_window,
    )


# ---------------------------------------------------------------------------
# Combined merge
# ---------------------------------------------------------------------------

def merge_all_alt_data(
    ohlcv_df: pd.DataFrame,
    symbol: str,
    *,
    funding_venue: str = "binance",
    oi_venue: str = "bybit",
    funding_db_path: Path | None = None,
    oi_db_path: Path | None = None,
    include_funding: bool = True,
    include_oi: bool = True,
    include_liq_proxy: bool = True,
    liq_proxy_kwargs: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Tüm alt-data kaynaklarını OHLCV'ye ekle.

    Boru hattı:
        OHLCV
          → + funding_rate_1d, funding_anomaly    (DuckDB, LEFT JOIN)
          → + oi_contracts, oi_pct_change, oi_z_30d, oi_anomaly  (DuckDB, LEFT JOIN)
          → + liq_proxy_long, liq_proxy_short, liq_proxy_score   (computed, no DB)

    No forward-fill at any step.
    Missing source → NaN columns (graceful degradation).

    Args:
        ohlcv_df: 1d OHLCV DataFrame
        symbol: Binance format (e.g. "BTCUSDT")
        include_*: hangi alt-data katmanları ekleneceğini kontrol eder
        liq_proxy_kwargs: compute_liquidation_proxy'ye geçilecek parametreler

    Returns:
        Zenginleştirilmiş DataFrame (kopya).
    """
    df = ohlcv_df.copy()

    if include_funding:
        try:
            df = merge_funding_to_ohlcv_1d(
                df, symbol, venue=funding_venue, funding_db_path=funding_db_path
            )
        except Exception as exc:
            logger.warning("merge_all.funding_fail", extra={"symbol": symbol, "err": str(exc)[:200]})
            df["funding_rate_1d"] = float("nan")
            df["funding_anomaly"] = False

    if include_oi:
        try:
            df = merge_oi_to_ohlcv(
                df, symbol, venue=oi_venue, oi_db_path=oi_db_path
            )
        except Exception as exc:
            logger.warning("merge_all.oi_fail", extra={"symbol": symbol, "err": str(exc)[:200]})
            for col in ["oi_contracts", "oi_pct_change", "oi_z_30d", "oi_anomaly"]:
                df[col] = float("nan")

    if include_liq_proxy:
        try:
            kwargs = liq_proxy_kwargs or {}
            df = add_liquidation_proxy(df, **kwargs)
        except Exception as exc:
            logger.warning("merge_all.liq_proxy_fail", extra={"symbol": symbol, "err": str(exc)[:200]})
            for col in ["liq_proxy_long", "liq_proxy_short", "liq_proxy_score"]:
                df[col] = float("nan")

    return df


# ---------------------------------------------------------------------------
# Column coverage report
# ---------------------------------------------------------------------------

def alt_data_coverage(df: pd.DataFrame, symbol: str = "") -> dict[str, Any]:
    """Merge sonrası alt-data kolon doluluk raporu.

    Her kolon için:
        - total_rows
        - non_nan_count
        - coverage_pct
        - first_date / last_date (non-NaN)

    Downstream strateji aktivasyonu için kullanılır.
    """
    alt_cols = [
        "funding_rate_1d", "funding_anomaly",
        "oi_contracts", "oi_pct_change", "oi_z_30d", "oi_anomaly",
        "liq_proxy_long", "liq_proxy_short", "liq_proxy_score",
        "volume_z", "atr14", "bar_range_ratio",
    ]
    n = len(df)
    report: dict[str, Any] = {"symbol": symbol, "total_rows": n, "columns": {}}

    for col in alt_cols:
        if col not in df.columns:
            report["columns"][col] = {"status": "missing"}
            continue

        non_nan = df[col].notna().sum()
        cov = round(non_nan / n * 100, 2) if n > 0 else 0.0
        non_nan_mask = df[col].notna()

        first_date = None
        last_date = None
        if non_nan > 0 and "ts" in df.columns:
            ts_series = _ensure_utc(df["ts"])
            first_date = str(ts_series[non_nan_mask].min())
            last_date = str(ts_series[non_nan_mask].max())

        report["columns"][col] = {
            "non_nan_count": int(non_nan),
            "coverage_pct": cov,
            "first_date": first_date,
            "last_date": last_date,
        }

    return report
