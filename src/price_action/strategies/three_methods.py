"""Rising Three Methods / Falling Three Methods continuation stratejisi.

Bulkowski rank: 10/103  — %74 bullish continuation rate (Rising Three Methods)
Mirror: Falling Three Methods (short taraf, %72 continuation rate, rank 11/103)

Referans: candlestick_statistics.md §4.11–4.12 (H-C6)

Pattern mekanigi (Rising Three Methods — LONG):
  Bar 1: Büyük BULLISH bar
          - gövde >= %50 bar range (trend bar)
          - Consolidation öncesi güçlü momentum
  Bar 2-4: 3 küçük BEARISH (veya neutral) bar — pullback / konsolidasyon
          - Her birinin low >= Bar1.low (Bar 1 range içinde)
          - Her birinin high <= Bar1.high (Bar 1 range içinde)
          - Gövde <= %35 Bar1 range (küçük bar kriteri)
  Bar 5: Büyük BULLISH bar — devam teyidi
          - close > Bar1.close (Bar 1 kapanışını geçiyor)
          - gövde >= %50 kendi range'i

  Giriş: Bar 5 kapanışından sonraki bar açılışı (Bar 6 open)
  Stop : min(Bar2.low, Bar3.low, Bar4.low) — konsolidasyon dibi
         veya Bar1.low (hangisi düşükse)
  Hedef: 2.5R

Falling Three Methods (SHORT) — mirror:
  Bar 1: Büyük BEARISH bar
  Bar 2-4: 3 küçük BULLISH (veya neutral) bar — Bar 1 range içinde
  Bar 5: Büyük BEARISH bar, close < Bar1.close
  Giriş: Bar 6 açılışı (short)
  Stop : max(Bar2.high, Bar3.high, Bar4.high) veya Bar1.high
  Hedef: 2.5R
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# Shared helpers
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
    _kaufman_efficiency_ratio,
    _rolling_sharpe,
)


# =====================================================================
# Pattern detection helpers
# =====================================================================

def _rising_three_methods(
    df: pd.DataFrame,
    bar1_body_ratio_min: float = 0.50,
    consolidation_body_ratio_max: float = 0.35,
    bar5_body_ratio_min: float = 0.50,
    require_bars_inside_bar1: bool = True,
) -> pd.Series:
    """Rising Three Methods pattern — lookahead-free.

    t bari = Bar 5 (pattern tamamlanma bari).
    t-4 = Bar 1, t-3 = Bar 2, t-2 = Bar 3, t-1 = Bar 4, t = Bar 5.

    Returns boolean Series indexed on df.index.
    True olduğu bar = Bar 5 (signal bar); entry bir sonraki bar açılışında.
    """
    o = df["open"]
    h = df["high"]
    l = df["low"]
    c = df["close"]

    # Bar 5 (t=gecerli)
    rng5 = (h - l).replace(0, np.nan)
    body5 = (c - o)
    body5_abs = body5.abs()

    # Bar 4 (t-1)
    o4, h4, l4, c4 = o.shift(1), h.shift(1), l.shift(1), c.shift(1)
    rng4 = (h4 - l4).replace(0, np.nan)
    body4 = (c4 - o4)

    # Bar 3 (t-2)
    o3, h3, l3, c3 = o.shift(2), h.shift(2), l.shift(2), c.shift(2)
    rng3 = (h3 - l3).replace(0, np.nan)
    body3 = (c3 - o3)

    # Bar 2 (t-3)
    o2, h2, l2, c2 = o.shift(3), h.shift(3), l.shift(3), c.shift(3)
    rng2 = (h2 - l2).replace(0, np.nan)
    body2 = (c2 - o2)

    # Bar 1 (t-4)
    o1, h1, l1, c1 = o.shift(4), h.shift(4), l.shift(4), c.shift(4)
    rng1 = (h1 - l1).replace(0, np.nan)
    body1 = (c1 - o1)
    body1_abs = body1.abs()

    # --- Bar 1 kuralları ---
    # Bullish bar
    bar1_bullish = body1 > 0
    # Gövde >= %50 range
    bar1_body_ok = body1_abs >= bar1_body_ratio_min * rng1

    # --- Bar 2-4 kuralları (konsolidasyon) ---
    bar1_range = rng1

    # Her konsolidasyon barı küçük gövdeli
    consol_body_limit = consolidation_body_ratio_max * bar1_range
    bar2_small = body2.abs() <= consol_body_limit
    bar3_small = body3.abs() <= consol_body_limit
    bar4_small = body4.abs() <= consol_body_limit
    all_small = bar2_small & bar3_small & bar4_small

    if require_bars_inside_bar1:
        # Bar 2-4 CLOSE'ları Bar 1 tam range içinde kalmalı (low <= close <= high).
        # High/low wick containment crypto'da çok kısıtlayıcı; close-based daha pratik.
        # Ek olarak: hiçbir konsolidasyon barının low'u Bar1.open'ın altına inmemeli
        # (Bar1 open = bullish bar için lower bound).
        bar1_lower_bound = o1  # Bar1 açılış = bullish bar için alt sınır
        bar2_inside = (c2 >= bar1_lower_bound) & (c2 <= h1)
        bar3_inside = (c3 >= bar1_lower_bound) & (c3 <= h1)
        bar4_inside = (c4 >= bar1_lower_bound) & (c4 <= h1)
        all_inside = bar2_inside & bar3_inside & bar4_inside
    else:
        all_inside = pd.Series(True, index=df.index)

    # Konsolidasyon barları bearish veya nötr olmalı (gövde <= 0)
    # "Nötr" = doji veya küçük gövde — gövde yönü genellikle bearish ama strict değil
    # Bulkowski tanımında "küçük bearish/neutral" diyor; gövde yönünü zorunlu kılmıyoruz
    # ama en az 2/3'ünün bearish olması beklenir
    bar2_bearish_or_neutral = body2 <= (0.15 * bar1_range)  # Hafif pozitif kabul edilebilir
    bar3_bearish_or_neutral = body3 <= (0.15 * bar1_range)
    bar4_bearish_or_neutral = body4 <= (0.15 * bar1_range)
    majority_bearish = (
        bar2_bearish_or_neutral.astype(int)
        + bar3_bearish_or_neutral.astype(int)
        + bar4_bearish_or_neutral.astype(int)
    ) >= 2

    # --- Bar 5 kuralları ---
    # Bullish bar
    bar5_bullish = body5 > 0
    # Gövde >= %50 kendi range'i
    bar5_body_ok = body5_abs >= bar5_body_ratio_min * rng5
    # Close > Bar1 close (kritik: konsolidasyon kırıldı)
    bar5_breaks_bar1 = c > c1

    # --- Tüm koşullar ---
    pattern = (
        bar1_bullish
        & bar1_body_ok
        & all_small
        & all_inside
        & majority_bearish
        & bar5_bullish
        & bar5_body_ok
        & bar5_breaks_bar1
    )
    return pattern.fillna(False)


def _falling_three_methods(
    df: pd.DataFrame,
    bar1_body_ratio_min: float = 0.50,
    consolidation_body_ratio_max: float = 0.35,
    bar5_body_ratio_min: float = 0.50,
    require_bars_inside_bar1: bool = True,
) -> pd.Series:
    """Falling Three Methods pattern — mirror of Rising Three Methods (short).

    t bari = Bar 5 (pattern tamamlanma bari).
    t-4 = Bar 1 (büyük bearish), t-3/t-2/t-1 = Bar 2-4 (küçük bullish/nötr),
    t = Bar 5 (büyük bearish, close < Bar1.close).

    Lookahead-free.
    """
    o = df["open"]
    h = df["high"]
    l = df["low"]
    c = df["close"]

    # Bar 5 (t)
    rng5 = (h - l).replace(0, np.nan)
    body5 = (o - c)  # pozitif = bearish
    body5_abs = body5.abs()

    # Bar 4 (t-1)
    o4, h4, l4, c4 = o.shift(1), h.shift(1), l.shift(1), c.shift(1)
    rng4 = (h4 - l4).replace(0, np.nan)
    body4 = (o4 - c4)

    # Bar 3 (t-2)
    o3, h3, l3, c3 = o.shift(2), h.shift(2), l.shift(2), c.shift(2)
    rng3 = (h3 - l3).replace(0, np.nan)
    body3 = (o3 - c3)

    # Bar 2 (t-3)
    o2, h2, l2, c2 = o.shift(3), h.shift(3), l.shift(3), c.shift(3)
    rng2 = (h2 - l2).replace(0, np.nan)
    body2 = (o2 - c2)

    # Bar 1 (t-4)
    o1, h1, l1, c1 = o.shift(4), h.shift(4), l.shift(4), c.shift(4)
    rng1 = (h1 - l1).replace(0, np.nan)
    body1 = (o1 - c1)  # pozitif = bearish
    body1_abs = body1.abs()

    # --- Bar 1 kuralları ---
    bar1_bearish = body1 > 0
    bar1_body_ok = body1_abs >= bar1_body_ratio_min * rng1

    # --- Bar 2-4 kuralları ---
    bar1_range = rng1
    consol_body_limit = consolidation_body_ratio_max * bar1_range

    bar2_small = body2.abs() <= consol_body_limit
    bar3_small = body3.abs() <= consol_body_limit
    bar4_small = body4.abs() <= consol_body_limit
    all_small = bar2_small & bar3_small & bar4_small

    if require_bars_inside_bar1:
        # Bar 2-4 CLOSE'ları Bar 1 tam range içinde kalmalı.
        # Falling Three: Bar1 bearish — bar1_open = upper bound, bar1_close = lower bound.
        bar1_upper_bound = o1  # Bar1 açılış = bearish bar için üst sınır
        bar2_inside = (c2 >= l1) & (c2 <= bar1_upper_bound)
        bar3_inside = (c3 >= l1) & (c3 <= bar1_upper_bound)
        bar4_inside = (c4 >= l1) & (c4 <= bar1_upper_bound)
        all_inside = bar2_inside & bar3_inside & bar4_inside
    else:
        all_inside = pd.Series(True, index=df.index)

    # Konsolidasyon barları bullish veya nötr olmalı (gövde <= 0 = bullish için pozitif c>o)
    bar2_bullish_or_neutral = (c2 - o2) <= (0.15 * bar1_range)
    bar3_bullish_or_neutral = (c3 - o3) <= (0.15 * bar1_range)
    bar4_bullish_or_neutral = (c4 - o4) <= (0.15 * bar1_range)
    majority_bullish = (
        bar2_bullish_or_neutral.astype(int)
        + bar3_bullish_or_neutral.astype(int)
        + bar4_bullish_or_neutral.astype(int)
    ) >= 2

    # --- Bar 5 kuralları ---
    bar5_bearish = body5 > 0
    bar5_body_ok = body5_abs >= bar5_body_ratio_min * rng5
    # Close < Bar1 close (konsolidasyon kırıldı — aşağı)
    bar5_breaks_bar1 = c < c1

    pattern = (
        bar1_bearish
        & bar1_body_ok
        & all_small
        & all_inside
        & majority_bullish
        & bar5_bearish
        & bar5_body_ok
        & bar5_breaks_bar1
    )
    return pattern.fillna(False)


def _consolidation_sl_long(df: pd.DataFrame) -> pd.Series:
    """Long SL: min(Bar2.low, Bar3.low, Bar4.low) ve Bar1.low'ı da dahil et.

    t bari = Bar 5 (pattern bari). Bar1 = t-4, Bar2..4 = t-3..t-1.
    """
    l1 = df["low"].shift(4)
    l2 = df["low"].shift(3)
    l3 = df["low"].shift(2)
    l4 = df["low"].shift(1)
    consol_low = pd.concat([l2, l3, l4], axis=1).min(axis=1)
    return pd.concat([l1, consol_low], axis=1).min(axis=1)


def _consolidation_sl_short(df: pd.DataFrame) -> pd.Series:
    """Short SL: max(Bar2.high, Bar3.high, Bar4.high) ve Bar1.high'ı da dahil et.

    t bari = Bar 5 (pattern bari).
    """
    h1 = df["high"].shift(4)
    h2 = df["high"].shift(3)
    h3 = df["high"].shift(2)
    h4 = df["high"].shift(1)
    consol_high = pd.concat([h2, h3, h4], axis=1).max(axis=1)
    return pd.concat([h1, consol_high], axis=1).max(axis=1)


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "three_methods",
        "version": "1.0.0",
        "description": (
            "Rising Three Methods (long) + Falling Three Methods (short). "
            "Bulkowski rank 10-11/103 — %74/%72 continuation rate. "
            "Continuation pattern: flag-variant in candlestick form."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "rising_three_methods",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "bar1_body_ratio_min": 0.50,
                        "consolidation_body_ratio_max": 0.35,
                        "bar5_body_ratio_min": 0.50,
                        "require_bars_inside_bar1": True,
                    },
                },
                {
                    "id": "falling_three_methods",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "bar1_body_ratio_min": 0.50,
                        "consolidation_body_ratio_max": 0.35,
                        "bar5_body_ratio_min": 0.50,
                        "require_bars_inside_bar1": True,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 120,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 120,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.15,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "consolidation_extreme"},
            "take_profit": {"method": "r_multiple", "primary_R": 2.5},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class ThreeMethodsStrategy(Strategy):
    """Rising Three Methods (long) + Falling Three Methods (short).

    Pattern: 5-bar continuation — güçlü trend bar + 3-bar konsolidasyon + teyit barı.
    Bulkowski: Rising %74, Falling %72 continuation rate.

    Entry: Bar 5 kapanışından sonraki bar açılışı (Bar 6 open)
    Stop:  Konsolidasyon minimum low (long) / maximum high (short)
    Target: 2.5R (Bulkowski avg move 6.1% — agresif ama justified)

    Engulfing'den dekorelasyon:
    - Continuation pattern (trend devam), engulfing reversal'dır.
    - 5-bar window vs 2-bar — tamamen farklı piyasa yapısı.
    - Aynı anda tetiklenme ihtimali düşük.
    """

    name = "three_methods"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # EMAs
        df["ema20"] = _ema(df["close"], 20)
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)

        # ATR
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Volume z-score (60 bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Pattern parametrelerini manifest'ten çek
        rtm_cfg: dict[str, Any] = {}
        ftm_cfg: dict[str, Any] = {}
        for p in self.manifest.signals.patterns:
            if p.id == "rising_three_methods":
                rtm_cfg = p.params
            elif p.id == "falling_three_methods":
                ftm_cfg = p.params

        # Rising Three Methods flag
        df["rtm_signal"] = _rising_three_methods(
            df,
            bar1_body_ratio_min=float(rtm_cfg.get("bar1_body_ratio_min", 0.50)),
            consolidation_body_ratio_max=float(rtm_cfg.get("consolidation_body_ratio_max", 0.35)),
            bar5_body_ratio_min=float(rtm_cfg.get("bar5_body_ratio_min", 0.50)),
            require_bars_inside_bar1=bool(rtm_cfg.get("require_bars_inside_bar1", True)),
        )

        # Falling Three Methods flag
        df["ftm_signal"] = _falling_three_methods(
            df,
            bar1_body_ratio_min=float(ftm_cfg.get("bar1_body_ratio_min", 0.50)),
            consolidation_body_ratio_max=float(ftm_cfg.get("consolidation_body_ratio_max", 0.35)),
            bar5_body_ratio_min=float(ftm_cfg.get("bar5_body_ratio_min", 0.50)),
            require_bars_inside_bar1=bool(ftm_cfg.get("require_bars_inside_bar1", True)),
        )

        # Stop levels (konsolidasyon extremes)
        df["rtm_stop"] = _consolidation_sl_long(df)   # long SL = konsolidasyon min low
        df["ftm_stop"] = _consolidation_sl_short(df)  # short SL = konsolidasyon max high

        # Kaufman ER
        er_period = int(
            getattr(self.manifest.signals.filters, "kaufman_er_period", 14) or 14
        )
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Rolling Sharpe
        df["rolling_sharpe"] = _rolling_sharpe(df["close"], period=60)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "rtm_signal" not in df.columns:
            df = self.prepare_features(df)

        filters = self.manifest.signals.filters
        confluence = self.manifest.signals.confluence

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.5)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        _atr_min_raw = getattr(filters, "atr_min_pct", None)
        atr_min = float(_atr_min_raw) if _atr_min_raw is not None else 0.005
        _er_min_raw = getattr(filters, "kaufman_er_min", None)
        er_min = float(_er_min_raw) if _er_min_raw is not None else 0.15
        min_score = float(confluence.min_score)

        # Pattern weights
        rtm_weight = 2.0
        ftm_weight = 2.0
        for p in self.manifest.signals.patterns:
            if not p.enabled:
                continue
            if p.id == "rising_three_methods":
                rtm_weight = p.weight
            elif p.id == "falling_three_methods":
                ftm_weight = p.weight

        out: list[Signal] = []
        for i in range(len(df)):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue

            # ATR pct filter
            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr_min > 0 and atr_pct < atr_min:
                continue

            # Kaufman ER filter
            er = float(row.get("kaufman_er") or 0.0)
            if er_min > 0 and er < er_min:
                continue

            # --- Rising Three Methods (LONG) ---
            if bool(row.get("rtm_signal", False)):
                score = rtm_weight
                if score >= min_score:
                    sl_price = float(row.get("rtm_stop") or 0.0)
                    if np.isnan(sl_price) or sl_price <= 0 or sl_price >= close:
                        sl_price = close - 3.0 * atr
                    # Ensure at least 0.5 ATR below close
                    sl_price = min(sl_price, close - 0.5 * atr)
                    risk = close - sl_price
                    if risk <= 0:
                        continue
                    tp_price = close + primary_R * risk

                    ts = pd.Timestamp(row["ts"]).to_pydatetime()
                    sig = self.emit_signal(
                        ts=ts,
                        venue=venue,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="long",
                        pattern_id="rising_three_methods",
                        confluence_score=score,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        suggested_size_atr=1.0,
                        metadata={
                            "atr14": atr,
                            "kaufman_er": er,
                            "ema50": float(row.get("ema50") or 0.0),
                            "rtm_stop_raw": float(row.get("rtm_stop") or 0.0),
                            "pattern": "rising_three_methods",
                            "bulkowski_continuation_rate": 0.74,
                        },
                    )
                    out.append(sig)

            # --- Falling Three Methods (SHORT) ---
            if bool(row.get("ftm_signal", False)):
                score = ftm_weight
                if score >= min_score:
                    sl_price = float(row.get("ftm_stop") or 0.0)
                    if np.isnan(sl_price) or sl_price <= 0 or sl_price <= close:
                        sl_price = close + 3.0 * atr
                    # Ensure at least 0.5 ATR above close
                    sl_price = max(sl_price, close + 0.5 * atr)
                    risk = sl_price - close
                    if risk <= 0:
                        continue
                    tp_price = close - primary_R * risk

                    ts = pd.Timestamp(row["ts"]).to_pydatetime()
                    sig = self.emit_signal(
                        ts=ts,
                        venue=venue,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="short",
                        pattern_id="falling_three_methods",
                        confluence_score=score,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        suggested_size_atr=1.0,
                        metadata={
                            "atr14": atr,
                            "kaufman_er": er,
                            "ema50": float(row.get("ema50") or 0.0),
                            "ftm_stop_raw": float(row.get("ftm_stop") or 0.0),
                            "pattern": "falling_three_methods",
                            "bulkowski_continuation_rate": 0.72,
                        },
                    )
                    out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("three_methods.signals.generated")
        return out
