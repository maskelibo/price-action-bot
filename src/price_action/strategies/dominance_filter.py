"""BTC Dominance Altcoin Rotation Filter — H22.

Alt season filtresi: BTC.D 30-bar trend negatifken alt long sinyallerine izin ver.

Fonksiyonlar:
    compute_btc_d_trend(btcd_df, lookback=30)
        Rolling linear slope of BTC.D (lookahead-free, shift(1) applied).
        Negatif slope → BTC.D düşüyor → alt season.

    filter_alt_signals_by_btc_d(signals, btcd_df, btc_d_trend_max=0.0)
        Alt long sinyallerini BTC.D trend filtresinden geçir.
        BTC sembolü her zaman filtersız geçer.
        Short sinyalleri filtreden muaf (BTC.D filtresi sadece alt longlara uygulanır).

Lookahead güvencesi:
    compute_btc_d_trend() içinde slope hesabı shift(1) ile t-1 günün verisini kullanır.
    t günündeki karar için t-1 gününün BTC.D trend'i kullanılır.

BTC symbol muafiyeti:
    BTC'nin dominance'ının yükselmesi BTC'nin outperform ettiğini gösterir.
    Bu durumda BTC long sinyalleri bloklanmamalı — filter SADECE alt sinyallere uygulanır.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger


# ---------------------------------------------------------------------------
# BTC symbol detection (compound_sentiment_filter ile uyumlu)
# ---------------------------------------------------------------------------

_BTC_SYMBOLS: frozenset[str] = frozenset([
    "BTC/USDT", "BTC/USD", "BTC/BUSD", "BTC/USDC",
    "BTCUSDT", "BTCUSD", "BTC",
])


def _is_btc(symbol: str) -> bool:
    """True if the symbol is Bitcoin (dominance filter exempt)."""
    return symbol.upper().strip() in _BTC_SYMBOLS


# ---------------------------------------------------------------------------
# BTC.D trend computation
# ---------------------------------------------------------------------------

def compute_btc_d_trend(
    btcd_df: pd.DataFrame,
    lookback: int = 30,
) -> pd.DataFrame:
    """BTC dominance üzerinde rolling linear slope hesapla.

    Lookahead-free:
        t günü için slope, [t-lookback .. t-1] verisi üzerinden hesaplanır.
        `btcd_df` sıralanır; slope shift(1) ile geciktirilir.

    Slope yorumu:
        slope > 0 → BTC.D yükseliyor → BTC dominant → alt season YOK
        slope < 0 → BTC.D düşüyor   → alt season VAR

    Parameters
    ----------
    btcd_df:
        DataFrame. Beklenen kolonlar: ts (datetime UTC), btc_dominance (float).
    lookback:
        Kaç bar üzerinden slope hesaplanacak.

    Returns
    -------
    pd.DataFrame
        Girdi df + şu kolonlar:
        - btcd_slope      : t günündeki raw slope (henüz shift uygulanmamış)
        - btcd_slope_lag  : lookahead-free slope = shift(1) → karar için BUNU kullan
        - btcd_trend_neg  : bool, slope_lag < 0  (alt season rejimi)
    """
    if btcd_df is None or btcd_df.empty:
        empty = pd.DataFrame(columns=["ts", "btc_dominance", "btcd_slope",
                                       "btcd_slope_lag", "btcd_trend_neg"])
        return empty

    required = {"ts", "btc_dominance"}
    missing = required - set(btcd_df.columns)
    if missing:
        raise ValueError(f"btcd_df eksik kolon(lar): {missing}")

    df = btcd_df[["ts", "btc_dominance"]].copy()

    # Normalize ts → UTC midnight
    ts_col = df["ts"]
    if not pd.api.types.is_datetime64_any_dtype(ts_col):
        ts_col = pd.to_datetime(ts_col, utc=True)
    elif ts_col.dt.tz is None:
        ts_col = ts_col.dt.tz_localize("UTC")
    else:
        ts_col = ts_col.dt.tz_convert("UTC")
    df["ts"] = ts_col.dt.normalize()

    df = df.sort_values("ts").reset_index(drop=True)
    df = df.drop_duplicates(subset=["ts"], keep="last")

    dom = df["btc_dominance"].values.astype(float)
    n = len(dom)
    slopes = np.full(n, np.nan)

    # Rolling OLS slope: cov(x, y) / var(x) where x = [0,1,...,lookback-1]
    # Vectorized for speed
    x = np.arange(lookback, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()

    for i in range(lookback - 1, n):
        window = dom[i - lookback + 1: i + 1]
        if np.any(np.isnan(window)):
            continue
        y_mean = window.mean()
        cov = ((x - x_mean) * (window - y_mean)).sum()
        slopes[i] = cov / x_var if x_var != 0 else 0.0

    df["btcd_slope"] = slopes

    # Lookahead protection: shift(1) — t günü için t-1'in slope'unu kullan
    df["btcd_slope_lag"] = df["btcd_slope"].shift(1)
    df["btcd_trend_neg"] = df["btcd_slope_lag"] < 0.0

    return df


# ---------------------------------------------------------------------------
# Filter stats
# ---------------------------------------------------------------------------

@dataclass
class DominanceFilterStats:
    """Filter istatistikleri."""
    total: int = 0
    passed: int = 0
    rejected_btcd: int = 0      # BTC.D yükseliyor → alt long bloklandı
    btc_exempt: int = 0         # BTC sembolü → filtre atlandı
    no_data: int = 0            # BTC.D verisi yok → geçirildi (konservatif)
    short_exempt: int = 0       # Short sinyal → filtre uygulanmadı

    @property
    def rejection_rate(self) -> float:
        return self.rejected_btcd / max(1, self.total)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "rejected_btcd": self.rejected_btcd,
            "btc_exempt": self.btc_exempt,
            "no_data": self.no_data,
            "short_exempt": self.short_exempt,
            "rejection_rate": self.rejection_rate,
        }


# ---------------------------------------------------------------------------
# Core filter
# ---------------------------------------------------------------------------

def filter_alt_signals_by_btc_d(
    signals: list[Signal],
    btcd_df: pd.DataFrame,
    *,
    btc_d_trend_max: float = 0.0,
    lookback: int = 30,
) -> tuple[list[Signal], DominanceFilterStats]:
    """Altcoin long sinyallerini BTC.D trend filtresinden geçir.

    Kural:
        - BTC sembolü → her zaman geçer (muaf)
        - Short sinyal → her zaman geçer (BTC.D sadece long filtre)
        - Alt long sinyal:
            - BTC.D slope_lag < btc_d_trend_max (default 0.0) → GEÇER (alt season)
            - BTC.D slope_lag >= btc_d_trend_max → BLOKLANIR (BTC dominant)
            - BTC.D verisi yok (NaN) → GEÇER (konservatif)

    Lookahead garantisi:
        compute_btc_d_trend() shift(1) uyguladığı için t günündeki karar
        t-1 günün verisini kullanır.

    Parameters
    ----------
    signals:
        Ham engulfing sinyalleri.
    btcd_df:
        BTC dominance DataFrame: ts (UTC), btc_dominance (float).
    btc_d_trend_max:
        Slope eşiği. default 0.0 → negatif trend zorunlu.
        Pozitif yapılırsa filtre gevşer (hafif yükselen trendde de geçer).
    lookback:
        compute_btc_d_trend() için lookback.

    Returns
    -------
    tuple[list[Signal], DominanceFilterStats]
        (filtered_signals, stats)
    """
    stats = DominanceFilterStats()
    stats.total = len(signals)

    if not signals:
        return [], stats

    # Boş BTC.D verisi → konservatif: tüm sinyalleri geçir
    if btcd_df is None or btcd_df.empty:
        logger.warning("dominance_filter.empty_btcd_df — all signals passed")
        stats.passed = len(signals)
        stats.no_data = len(signals)
        return list(signals), stats

    # Compute trend (with shift(1))
    trend_df = compute_btc_d_trend(btcd_df, lookback=lookback)
    if trend_df.empty or "btcd_slope_lag" not in trend_df.columns:
        logger.warning("dominance_filter.trend_compute_failed — all signals passed")
        stats.passed = len(signals)
        stats.no_data = len(signals)
        return list(signals), stats

    # Build date → slope_lag lookup
    slope_lookup: dict[pd.Timestamp, float] = {}
    for _, row in trend_df.iterrows():
        ts_key = pd.Timestamp(row["ts"])
        if ts_key.tzinfo is None:
            ts_key = ts_key.tz_localize("UTC")
        slope_val = row["btcd_slope_lag"]
        if not (isinstance(slope_val, float) and np.isnan(slope_val)):
            slope_lookup[ts_key] = float(slope_val)

    passed: list[Signal] = []

    for sig in signals:
        # BTC muafiyeti
        if _is_btc(sig.symbol):
            passed.append(sig)
            stats.btc_exempt += 1
            continue

        # Short muafiyeti (BTC.D filtresi sadece alt long'lar için)
        if sig.direction != "long":
            passed.append(sig)
            stats.short_exempt += 1
            continue

        # Alt long: BTC.D trend kontrolü
        sig_ts = pd.Timestamp(sig.ts)
        if sig_ts.tzinfo is None:
            sig_ts = sig_ts.tz_localize("UTC")
        else:
            sig_ts = sig_ts.tz_convert("UTC")
        sig_date = sig_ts.normalize()

        slope_val = slope_lookup.get(sig_date, np.nan)

        if isinstance(slope_val, float) and np.isnan(slope_val):
            # Veri yok → konservatif: geçir
            passed.append(sig)
            stats.no_data += 1
            continue

        if slope_val < btc_d_trend_max:
            # Alt season: BTC.D düşüyor → geçir
            passed.append(sig)
        else:
            # BTC dominant: blokla
            stats.rejected_btcd += 1

    stats.passed = len(passed)

    logger.bind(
        total=stats.total,
        passed=stats.passed,
        rejected_btcd=stats.rejected_btcd,
        btc_exempt=stats.btc_exempt,
        no_data=stats.no_data,
        short_exempt=stats.short_exempt,
        btc_d_trend_max=btc_d_trend_max,
        lookback=lookback,
    ).info("dominance_filter.applied")

    return passed, stats


# ---------------------------------------------------------------------------
# Combined filter: F&G + BTC.D
# ---------------------------------------------------------------------------

def filter_engulfing_fng_and_btcd(
    signals: list[Signal],
    fng_df: pd.DataFrame | None,
    btcd_df: pd.DataFrame | None,
    *,
    long_max_fng: float = 60.0,
    short_min_fng: float = 40.0,
    btc_d_trend_max: float = 0.0,
    btcd_lookback: int = 30,
) -> tuple[list[Signal], dict]:
    """Engulfing sinyallerini F&G + BTC.D bileşik filtreden geçir.

    Uygulama sırası:
        1. F&G filtresi (tüm semboller, her iki yön)
        2. BTC.D filtresi (sadece alt long sinyalleri)

    Parameters
    ----------
    signals:
        Ham engulfing sinyalleri.
    fng_df:
        Fear & Greed DataFrame. None → F&G filtresi atlanır.
    btcd_df:
        BTC dominance DataFrame. None → BTC.D filtresi atlanır.
    long_max_fng:
        F&G long eşiği (default 60).
    short_min_fng:
        F&G short eşiği (default 40).
    btc_d_trend_max:
        BTC.D slope eşiği (default 0.0 = negatif trend zorunlu).
    btcd_lookback:
        BTC.D slope lookback (default 30 bar).

    Returns
    -------
    tuple[list[Signal], dict]
        (filtered_signals, stats_dict)
        stats_dict içerir: fng_stats, btcd_stats, total_rejected, rejection_rate
    """
    from price_action.strategies.sentiment_filter import filter_engulfing_with_fng

    # Stage 1: F&G filter
    if fng_df is not None and not fng_df.empty:
        after_fng, n_fng_rejected = filter_engulfing_with_fng(
            signals, fng_df,
            long_max_fng=long_max_fng,
            short_min_fng=short_min_fng,
        )
        fng_stats = {"n_rejected": n_fng_rejected, "n_passed": len(after_fng)}
    else:
        after_fng = list(signals)
        fng_stats = {"n_rejected": 0, "n_passed": len(signals)}

    # Stage 2: BTC.D filter (alt longs only)
    if btcd_df is not None and not btcd_df.empty:
        after_btcd, btcd_filter_stats = filter_alt_signals_by_btc_d(
            after_fng, btcd_df,
            btc_d_trend_max=btc_d_trend_max,
            lookback=btcd_lookback,
        )
        btcd_stats = btcd_filter_stats.to_dict()
    else:
        after_btcd = list(after_fng)
        btcd_stats = DominanceFilterStats(total=len(after_fng), passed=len(after_fng)).to_dict()

    total = len(signals)
    total_rejected = total - len(after_btcd)
    stats_dict = {
        "total_input": total,
        "total_passed": len(after_btcd),
        "total_rejected": total_rejected,
        "rejection_rate": total_rejected / max(1, total),
        "fng": fng_stats,
        "btcd": btcd_stats,
    }

    logger.bind(
        total=total,
        passed=len(after_btcd),
        total_rejected=total_rejected,
    ).info("combined_filter.applied")

    return after_btcd, stats_dict
