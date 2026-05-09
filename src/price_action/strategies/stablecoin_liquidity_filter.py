"""Stablecoin Liquidity Filter — H22.

HYPOTHESIS:
    USDT + USDC toplam market cap'in 30 günlük büyümesi, kripto
    piyasasına giren/çıkan "dry powder" miktarını proxy eder.

    Stable supply ↑ (growth > 0)  → fresh capital incoming  → bullish
    Stable supply ↓ (growth ≤ 0)  → redemptions / risk-off  → bearish long setup

    Filtre kuralı:
        LONG signal → sadece stable_growth_30d[t-1] > growth_min geçer
        (growth_min default = 0.0, yani net büyüme yeterli)

Lookahead garantisi:
    compute_stable_growth() → shift(1) uygular.
    filter_signals_by_liquidity() → lookup tablosunda shift(1) önceden uygulanmış.

    Bu, her bar için T-1 günün stable growth değerini kullanır;
    bugünün kapanışından türetilen sinyal bugünün stable değerini göremez.

Usage:
    from price_action.strategies.stablecoin_liquidity_filter import (
        compute_stable_growth,
        filter_signals_by_liquidity,
        build_stable_growth_lookup,
    )
    stable_df = build_combined_supply_series(raw_df)
    growth_df = compute_stable_growth(stable_df, lookback=30)
    filtered, stats = filter_signals_by_liquidity(signals, growth_df)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger


# =====================================================================
# Stats & rejection record
# =====================================================================

class StableRejectedSignal(NamedTuple):
    """Signal blocked by the stablecoin liquidity filter."""
    signal: Signal
    stable_growth: float | None   # lagged growth value at signal date


@dataclass
class StableFilterStats:
    """Summary from one filter_signals_by_liquidity() call."""
    total: int = 0
    passed: int = 0
    rejected_no_growth: int = 0   # growth ≤ growth_min
    skipped_no_data: int = 0      # growth NaN → conservative pass

    @property
    def n_rejected(self) -> int:
        return self.rejected_no_growth

    @property
    def rejection_rate(self) -> float:
        return self.n_rejected / max(1, self.total)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "rejected_no_growth": self.rejected_no_growth,
            "skipped_no_data": self.skipped_no_data,
            "n_rejected": self.n_rejected,
            "rejection_rate": self.rejection_rate,
        }


# =====================================================================
# Core computation
# =====================================================================

def compute_stable_growth(
    df: pd.DataFrame,
    lookback: int = 30,
    *,
    supply_col: str = "total_stable_mcap",
    apply_shift: bool = True,
) -> pd.DataFrame:
    """Stablecoin total supply'ının rolling pct_change hesaplar.

    Parameters
    ----------
    df:
        build_combined_supply_series() çıktısı.
        Beklenen kolonlar: ts (datetime UTC), total_stable_mcap (float).
    lookback:
        Pct change penceresi (gün). Default 30.
    supply_col:
        Kaynak kolon adı. Default "total_stable_mcap".
    apply_shift:
        True (default) → growth_lag = growth.shift(1). Lookahead önlenir.
        False → sadece testlerde veya araştırma.

    Returns
    -------
    pd.DataFrame
        Giriş df + iki yeni kolon:
        - 'stable_growth_30d'     : raw pct_change (lookahead risk var — sadece analiz için)
        - 'stable_growth_30d_lag' : shift(1) uygulanmış — TRADE LOGIC BUNU KULLANIMALI
    """
    if df is None or df.empty:
        out = pd.DataFrame(columns=["ts", "stable_growth_30d", "stable_growth_30d_lag"])
        return out

    result = df.copy()

    if supply_col not in result.columns:
        logger.warning(
            "stable_growth.missing_col",
            extra={"col": supply_col, "available": list(result.columns)},
        )
        result["stable_growth_30d"] = np.nan
        result["stable_growth_30d_lag"] = np.nan
        return result

    # Ensure ts sorted (critical for rolling/shift correctness)
    result = result.sort_values("ts").reset_index(drop=True)

    # pct_change(lookback): (today - lookback_days_ago) / lookback_days_ago
    supply = result[supply_col].replace(0, np.nan)
    result["stable_growth_30d"] = supply.pct_change(periods=lookback)

    if apply_shift:
        # Lookahead-free: signal at T uses growth computed up to T-1
        result["stable_growth_30d_lag"] = result["stable_growth_30d"].shift(1)
    else:
        result["stable_growth_30d_lag"] = result["stable_growth_30d"]

    logger.bind(
        rows=len(result),
        lookback=lookback,
        non_null=int(result["stable_growth_30d_lag"].notna().sum()),
    ).info("stable_growth.computed")

    return result


# =====================================================================
# Lookup builder (O(N) build, O(1) lookup)
# =====================================================================

def build_stable_growth_lookup(
    growth_df: pd.DataFrame,
    *,
    lag_col: str = "stable_growth_30d_lag",
) -> dict[pd.Timestamp, float]:
    """Build a date → lagged stable_growth lookup dict.

    Parameters
    ----------
    growth_df:
        compute_stable_growth() çıktısı. 'ts' ve 'stable_growth_30d_lag' içermeli.
    lag_col:
        Kullanılacak lagged kolon adı.

    Returns
    -------
    dict mapping UTC-midnight Timestamp → stable_growth_30d[t-1] value.
    """
    if growth_df is None or growth_df.empty:
        return {}

    if lag_col not in growth_df.columns:
        logger.warning("stable_growth.lookup.missing_lag_col", extra={"col": lag_col})
        return {}

    tmp = growth_df[["ts", lag_col]].copy()

    # Normalize ts → UTC midnight
    ts_col = tmp["ts"]
    if not pd.api.types.is_datetime64_any_dtype(ts_col):
        ts_col = pd.to_datetime(ts_col, utc=True)
    elif ts_col.dt.tz is None:
        ts_col = ts_col.dt.tz_localize("UTC")
    else:
        ts_col = ts_col.dt.tz_convert("UTC")

    tmp["_date"] = ts_col.dt.normalize()
    tmp = tmp.sort_values("_date").drop_duplicates("_date", keep="last")

    return dict(zip(tmp["_date"], tmp[lag_col]))


# =====================================================================
# Signal filter
# =====================================================================

def filter_signals_by_liquidity(
    signals: list[Signal],
    stable_df: pd.DataFrame,
    *,
    growth_min: float = 0.0,
    long_only: bool = True,
) -> tuple[list[Signal], StableFilterStats, list[StableRejectedSignal]]:
    """Engulfing sinyallerini stablecoin supply büyümesi ile filtrele.

    Teori:
        - LONG signal geçer: stable_growth_30d[t-1] > growth_min
          (sermaye sisteme giriyor — long için elverişli ortam)
        - SHORT signal: long_only=True ise filtrelenmez (short için
          stable drain bearish, ancak bu filtre longs için tasarlandı)

    Lookahead:
        stable_df'nin 'stable_growth_30d_lag' kolonu zaten shift(1)
        içeriyor (compute_stable_growth tarafından uygulandı).
        Bu fonksiyon ek shift uygulamaz.

    Parameters
    ----------
    signals:
        Engulfing veya başka bir stratejiden gelen Signal listesi.
    stable_df:
        compute_stable_growth() çıktısı.
        'ts' ve 'stable_growth_30d_lag' kolonları gerekli.
    growth_min:
        Long için gereken minimum stable growth. Default 0.0 (pozitif büyüme).
    long_only:
        True (default) → short sinyaller filtrelenmez.
        False → short için de growth < 0 gerektir (experimental).

    Returns
    -------
    tuple[list[Signal], StableFilterStats, list[StableRejectedSignal]]
        (filtered_signals, stats, rejections)
    """
    stats = StableFilterStats()
    rejections: list[StableRejectedSignal] = []

    if not signals:
        return [], stats, rejections

    if stable_df is None or stable_df.empty:
        logger.warning("stable_filter.empty_df — passing all signals (conservative)")
        stats.total = len(signals)
        stats.passed = len(signals)
        stats.skipped_no_data = len(signals)
        return signals, stats, rejections

    # Build lookup once
    lookup = build_stable_growth_lookup(stable_df)

    if not lookup:
        logger.warning("stable_filter.empty_lookup — passing all signals (conservative)")
        stats.total = len(signals)
        stats.passed = len(signals)
        stats.skipped_no_data = len(signals)
        return signals, stats, rejections

    passed: list[Signal] = []
    stats.total = len(signals)

    for sig in signals:
        # Normalize signal date → UTC midnight
        sig_ts = pd.Timestamp(sig.ts)
        if sig_ts.tzinfo is None:
            sig_ts = sig_ts.tz_localize("UTC")
        else:
            sig_ts = sig_ts.tz_convert("UTC")
        sig_date = sig_ts.normalize()

        # Shorts: pass through unless long_only=False
        if sig.direction == "short":
            if long_only:
                passed.append(sig)
                continue
            # Experimental: short only when growth is negative (drain)
            growth_val_raw = lookup.get(sig_date, np.nan)
            growth_val = float(growth_val_raw) if not (
                isinstance(growth_val_raw, float) and np.isnan(growth_val_raw)
            ) else None

            if growth_val is None:
                stats.skipped_no_data += 1
                passed.append(sig)  # conservative
                continue

            if growth_val <= 0.0:
                passed.append(sig)  # short when stable shrinking
            else:
                stats.rejected_no_growth += 1
                rejections.append(StableRejectedSignal(sig, growth_val))
            continue

        # --- LONG gate ---
        growth_val_raw = lookup.get(sig_date, np.nan)
        is_nan = isinstance(growth_val_raw, float) and np.isnan(growth_val_raw)

        if is_nan:
            # Unknown date → conservative: pass
            stats.skipped_no_data += 1
            passed.append(sig)
            continue

        growth_val = float(growth_val_raw)

        if growth_val > growth_min:
            passed.append(sig)
        else:
            stats.rejected_no_growth += 1
            rejections.append(StableRejectedSignal(sig, growth_val))

    stats.passed = len(passed)

    logger.bind(
        total=stats.total,
        passed=stats.passed,
        rejected=stats.n_rejected,
        skipped_no_data=stats.skipped_no_data,
        growth_min=growth_min,
        long_only=long_only,
    ).info("stable_filter.applied")

    return passed, stats, rejections
