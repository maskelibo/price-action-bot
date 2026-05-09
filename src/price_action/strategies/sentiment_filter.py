"""Fear & Greed Sentiment Filter stratejisi.

Bu modül iki bağımsız yetenek sunar:

1. SentimentFilterStrategy — standalone F&G sinyali
   - LONG : fng[t-1] < 25 AND price[t] > price[t-1]   (teyitli reversal)
   - SHORT: fng[t-1] > 75 AND price[t] < price[t-1]
   - Exit : F&G 40-60 neutral zone'a girdiğinde
   - SL   : 10-bar structural swing + 1 ATR
   - TP   : 2R

2. merge_fng_to_ohlcv() — OHLCV + F&G merge yardımcısı
   Left join on date (lookahead-free: fng_shifted=shift(1) otomatik).

3. filter_engulfing_with_fng() — Engulfing sinyallerini F&G ile filtrele
   long sinyallerini F&G[t-1] < long_max_fng iken geçir,
   short sinyallerini F&G[t-1] > short_min_fng iken geçir.

Lookahead güvencesi:
    merge_fng_to_ohlcv() içinde fng_value_lag = fng_value.shift(1)
    Bu, her bar için bir önceki günün F&G değerini kullanır.
    Bugünün F&G bugünün fiyatlarından hesaplandığı için SHIFT ZORUNLUDUR.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest


# =====================================================================
# Yardımcı fonksiyonlar
# =====================================================================

def merge_fng_to_ohlcv(
    df: pd.DataFrame,
    fng_df: pd.DataFrame,
    *,
    apply_shift: bool = True,
) -> pd.DataFrame:
    """OHLCV DataFrame'ine F&G değerlerini left join ile ekler.

    F&G, günlük fiyat verilerinden üretildiği için lookahead riski taşır.
    apply_shift=True (default) iken fng_value_lag = fng_value.shift(1) uygulanır
    — bu, t günü için t-1 günün F&G değerini kullanır (lookahead-free).

    Parameters
    ----------
    df:
        OHLCV DataFrame. 'ts' kolonu datetime UTC olmalı.
    fng_df:
        F&G DataFrame. Kolonlar: ts (datetime UTC), value (int), classification (str).
    apply_shift:
        True (default) → fng_value_lag = fng_value.shift(1). Lookahead önlenir.
        False → sadece testlerde veya araştırma amaçlı.

    Returns
    -------
    pd.DataFrame
        Orijinal df + 'fng_value' ve 'fng_value_lag' ve 'fng_classification' kolonları.
        Join başarısız olursa NaN döner (strateji graceful handle eder).
    """
    if fng_df is None or fng_df.empty:
        df = df.copy()
        df["fng_value"] = np.nan
        df["fng_value_lag"] = np.nan
        df["fng_classification"] = "Unknown"
        return df

    # Normalize OHLCV ts → UTC date
    # CRITICAL: convert to UTC BEFORE normalize() to avoid TZ-offset date shift
    # (Istanbul UTC+3: 2023-05-10 03:00+03 → UTC 00:00 → date 2023-05-10 correct)
    df = df.copy()
    df_ts = df["ts"]
    if not pd.api.types.is_datetime64_any_dtype(df_ts):
        df_ts = pd.to_datetime(df_ts, utc=True)
    elif df_ts.dt.tz is None:
        df_ts = df_ts.dt.tz_localize("UTC")
    else:
        df_ts = df_ts.dt.tz_convert("UTC")
    df["_date"] = df_ts.dt.normalize()  # now UTC midnight

    # Normalize F&G ts → date
    fng = fng_df[["ts", "value", "classification"]].copy()
    fng_ts = fng["ts"]
    if not pd.api.types.is_datetime64_any_dtype(fng_ts):
        fng_ts = pd.to_datetime(fng_ts, utc=True)
    elif fng_ts.dt.tz is None:
        fng_ts = fng_ts.dt.tz_localize("UTC")
    else:
        fng_ts = fng_ts.dt.tz_convert("UTC")
    fng["_date"] = fng_ts.dt.normalize()
    fng = fng.drop_duplicates("_date", keep="last")
    fng = fng.rename(columns={"value": "fng_value", "classification": "fng_classification"})

    merged = df.merge(fng[["_date", "fng_value", "fng_classification"]], on="_date", how="left")
    merged = merged.drop(columns=["_date"])

    # Lookahead protection — zorunlu shift
    if apply_shift:
        merged["fng_value_lag"] = merged["fng_value"].shift(1)
    else:
        merged["fng_value_lag"] = merged["fng_value"]

    return merged


def filter_engulfing_with_fng(
    signals: list[Signal],
    fng_df: pd.DataFrame,
    *,
    long_max_fng: float = 60.0,
    short_min_fng: float = 40.0,
) -> tuple[list[Signal], int]:
    """Engulfing sinyallerini F&G filtresiyle elek.

    Teori:
        - Long sinyal sadece F&G < long_max_fng iken geçer (greed zirvelerinden kaçın)
        - Short sinyal sadece F&G > short_min_fng iken geçer (fear dip'lerinden kaçın)
        F&G değeri: sinyal tarihinin bir önceki günü (lookahead-free).

    Parameters
    ----------
    signals:
        Engulfing veya başka bir stratejiden gelen Signal listesi.
    fng_df:
        F&G DataFrame: ts (datetime UTC), value (int), classification (str).
    long_max_fng:
        Long sinyaller için maksimum F&G eşiği. Default 60.
    short_min_fng:
        Short sinyaller için minimum F&G eşiği. Default 40.

    Returns
    -------
    tuple[list[Signal], int]
        (filtered_signals, n_rejected) — kaç sinyal elendi bilgisi.
    """
    if not signals:
        return [], 0

    if fng_df is None or fng_df.empty:
        logger.warning("fng_filter.empty_fng_df")
        return signals, 0

    # F&G lookup: date → lag değer (bir önceki gün)
    fng = fng_df[["ts", "value"]].copy()
    fng_ts = fng["ts"]
    if not pd.api.types.is_datetime64_any_dtype(fng_ts):
        fng_ts = pd.to_datetime(fng_ts, utc=True)
    elif fng_ts.dt.tz is None:
        fng_ts = fng_ts.dt.tz_localize("UTC")
    else:
        fng_ts = fng_ts.dt.tz_convert("UTC")
    fng["_date"] = fng_ts.dt.normalize()
    fng = fng.sort_values("_date")
    fng = fng.drop_duplicates("_date", keep="last")
    # Shift(1): her tarihin F&G değeri aslında bir önceki günün değeri
    fng["fng_lag"] = fng["value"].shift(1)
    fng_lookup: dict[pd.Timestamp, float] = dict(
        zip(fng["_date"], fng["fng_lag"])
    )

    passed: list[Signal] = []
    n_rejected = 0

    for sig in signals:
        sig_date = pd.Timestamp(sig.ts).tz_convert("UTC").normalize()
        fng_val = fng_lookup.get(sig_date, np.nan)

        if np.isnan(fng_val):
            # F&G bilinmiyorsa geçir (konservatif — sinyali reddetme)
            passed.append(sig)
            continue

        if sig.direction == "long" and fng_val >= long_max_fng:
            n_rejected += 1
            continue
        if sig.direction == "short" and fng_val <= short_min_fng:
            n_rejected += 1
            continue

        passed.append(sig)

    logger.bind(
        total=len(signals),
        passed=len(passed),
        rejected=n_rejected,
        long_max_fng=long_max_fng,
        short_min_fng=short_min_fng,
    ).info("fng_filter.applied")

    return passed, n_rejected


# =====================================================================
# ATR yardımcısı (local — strategies.classic_pa'ya bağımlılığı minimize et)
# =====================================================================

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _swing_sl(df: pd.DataFrame, direction: str, lookback: int = 10) -> pd.Series:
    if direction == "long":
        return df["low"].shift(1).rolling(lookback, min_periods=1).min()
    return df["high"].shift(1).rolling(lookback, min_periods=1).max()


# =====================================================================
# Default manifest
# =====================================================================

def _default_sentiment_manifest() -> StrategyManifest:
    raw: dict[str, Any] = {
        "name": "sentiment_filter",
        "version": "1.0.0",
        "description": "Crypto Fear & Greed standalone sentiment strategy",
        "trend_filter": {"type": "none", "period": 1, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "fng_extreme_fear_long",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "fng_long_threshold": 25,
                        "fng_exit_neutral_low": 40,
                        "fng_exit_neutral_high": 60,
                        "require_price_confirm": True,
                    },
                },
                {
                    "id": "fng_extreme_greed_short",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "fng_short_threshold": 75,
                        "fng_exit_neutral_low": 40,
                        "fng_exit_neutral_high": 60,
                        "require_price_confirm": True,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 10,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 10,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.003,
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# SentimentFilterStrategy
# =====================================================================

class SentimentFilterStrategy(Strategy):
    """Standalone Fear & Greed Index strateji.

    LONG  : fng_value_lag (=fng[t-1]) < fng_long_threshold (25)
             AND close[t] > close[t-1]   (fiyat teyidi)
    SHORT : fng_value_lag > fng_short_threshold (75)
             AND close[t] < close[t-1]
    Exit  : F&G 40-60 neutral zone'a girince (TP veya SL; SL=structural)
    SL    : 10-bar swing low/high + 1 ATR buffer
    TP    : 2R

    fng_df parametresini inject etmek için set_fng_data(df) kullan.
    """

    name = "sentiment_filter"

    def __init__(self, manifest: StrategyManifest | None = None) -> None:
        if manifest is None:
            manifest = _default_sentiment_manifest()
        super().__init__(manifest)
        self._fng_df: pd.DataFrame = pd.DataFrame(columns=["ts", "value", "classification"])

    def set_fng_data(self, fng_df: pd.DataFrame) -> None:
        """F&G verisini stratejiye enjekte et. Backtest öncesi çağrılmalı."""
        self._fng_df = fng_df.copy() if fng_df is not None else pd.DataFrame(
            columns=["ts", "value", "classification"]
        )

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # Drop pre-existing fng columns to avoid merge conflicts on re-call
        for _col in ("fng_value", "fng_value_lag", "fng_classification"):
            if _col in df.columns:
                df = df.drop(columns=[_col])

        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)
        df["struct_sl_long"] = _swing_sl(df, "long", lookback=10)
        df["struct_sl_short"] = _swing_sl(df, "short", lookback=10)

        # Merge F&G (shift(1) apply edilir — lookahead-free)
        df = merge_fng_to_ohlcv(df, self._fng_df, apply_shift=True)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "fng_value_lag" not in df.columns:
            df = self.prepare_features(df)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # Config parametreleri
        fng_long_thr = 25.0
        fng_short_thr = 75.0
        primary_R = 2.0
        for p in self.manifest.signals.patterns:
            if p.id == "fng_extreme_fear_long":
                fng_long_thr = float(p.params.get("fng_long_threshold", 25))
                primary_R = float(
                    self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
                )
            elif p.id == "fng_extreme_greed_short":
                fng_short_thr = float(p.params.get("fng_short_threshold", 75))

        atr_min = float(
            getattr(self.manifest.signals.filters, "atr_min_pct", 0.003) or 0.003
        )

        out: list[Signal] = []

        for i in range(1, len(df)):  # i=0 için t-1 yok, atla
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]

            close = float(row["close"])
            prev_close = float(prev_row["close"])
            atr = float(row.get("atr14") or 0.0)

            if atr <= 0 or np.isnan(atr):
                continue

            # ATR min filtresi
            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr_min > 0 and atr_pct < atr_min:
                continue

            fng_lag = row.get("fng_value_lag")
            if fng_lag is None or (isinstance(fng_lag, float) and np.isnan(fng_lag)):
                continue

            fng_val = float(fng_lag)
            ts = pd.Timestamp(row["ts"]).to_pydatetime()

            # --- LONG: extreme fear + upward price confirmation ---
            if fng_val < fng_long_thr and close > prev_close:
                sl_price = float(row.get("struct_sl_long") or (close - 2.0 * atr))
                if np.isnan(sl_price) or sl_price <= 0:
                    sl_price = close - 2.0 * atr
                sl_price = min(sl_price, close - 1.0 * atr)  # en az 1 ATR uzakta
                risk = close - sl_price
                if risk <= 0:
                    continue
                tp_price = close + primary_R * risk

                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="long",
                    pattern_id="fng_extreme_fear_long",
                    confluence_score=1.5,
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "fng_value_lag": fng_val,
                        "fng_threshold": fng_long_thr,
                        "atr14": atr,
                        "price_confirm": True,
                    },
                )
                out.append(sig)

            # --- SHORT: extreme greed + downward price confirmation ---
            elif fng_val > fng_short_thr and close < prev_close:
                sl_price = float(row.get("struct_sl_short") or (close + 2.0 * atr))
                if np.isnan(sl_price) or sl_price <= 0:
                    sl_price = close + 2.0 * atr
                sl_price = max(sl_price, close + 1.0 * atr)  # en az 1 ATR uzakta
                risk = sl_price - close
                if risk <= 0:
                    continue
                tp_price = close - primary_R * risk

                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="short",
                    pattern_id="fng_extreme_greed_short",
                    confluence_score=1.5,
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "fng_value_lag": fng_val,
                        "fng_threshold": fng_short_thr,
                        "atr14": atr,
                        "price_confirm": True,
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("sentiment_filter.signals.generated")
        return out
