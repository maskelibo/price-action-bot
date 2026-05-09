"""Order Block Mitigation Entry — Strict Parameters (SMC H-4).

Concept (SMC)
-------------
Bullish OB = the last bearish candle BEFORE a bullish displacement move.
When price returns (mitigates) into the OB zone, a reversal pattern
(engulfing OR pin bar) that closes ABOVE the OB zone triggers a long entry.
Mirror logic for bearish OB / short entries.

Mechanical rules (strictly tighter than smc_orderblock.py)
-----------------------------------------------------------
1. Displacement bar: |body| > 1.5×ATR(14)  AND  close_direction_strong
       Strong direction: bull_disp → close > 3-bar rolling high (BOS proxy)
                         bear_disp → close < 3-bar rolling low  (BOS proxy)
   Additionally we require the displacement BODY > ATR * displacement_body_mult
   (default 1.5) — the original SMC requirement.

2. OB identification: for a BULLISH displacement bar at t, the OB is the
   LAST bearish candle (close < open) found scanning backwards from t-1
   (window up to 5 bars).  OB zone = [OB_low, OB_high].

3. Mitigation: price re-enters the OB zone (any of bar's high/low touches zone).
   Detection: low[t] <= OB_high AND high[t] >= OB_low (zone touched by the bar).

4. Rejection pattern INSIDE or at the OB zone (same mitigation bar or the
   bar AFTER first touch):
       - Bullish engulfing: close > open (bullish), body > prev_body, zit renk
       - OR pin bar (hammer): lower_wick > 2×body, small upper wick (< body)
   The rejection bar must CLOSE ABOVE OB_high (for long) / BELOW OB_low (for short).
   This is the key stricter requirement vs. smc_orderblock.py.

5. Entry: next bar open (bar after rejection bar).
   In a vectorized backtest, signals are emitted at the rejection bar's close
   and entered at the following open. We mark the rejection bar as the signal.

6. Stop: OB_low - 0.5×ATR(14)  (long)  |  OB_high + 0.5×ATR(14)  (short)

7. Target: 3R (risk × 3.0)

8. Bias filter: 200-EMA — long signals only above EMA200, shorts below.

9. OB invalidation: OB is marked "mitigated/broken" once price CLOSES below
   OB_low (long) or above OB_high (short). After invalidation the OB is
   discarded and will not generate further signals.

10. Max OB age: 60 bars. OBs older than this are discarded.

Key differences vs. smc_orderblock.py
--------------------------------------
  * NO liquidity grab requirement (different setup; OB mitigation is standalone)
  * Rejection bar MUST close outside the OB zone (above OB_high for long)
    — smc_orderblock only required directional close within zone
  * Stricter engulfing OR pin bar check (dual pattern gate)
  * SL = OB_low - 0.5 ATR  (smc_orderblock used OB_low - 1.0 ATR)
  * TP = 3R (same SMC default)
  * OB expiry: 60 bars (smc_orderblock used 30 bars lookback)

References
----------
knowledge/books/market_structure_order_flow.md — §4.1 Bullish OB, §4.2 Bearish OB
Hypothesis H-4: OB Mitigation Entry (BTC 1D)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest


# =====================================================================
# Low-level helpers (vectorized, lookahead-free)
# =====================================================================

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.astype(float).ewm(span=period, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


# =====================================================================
# OB detection (strict)
# =====================================================================

def _detect_ob_strict(
    df: pd.DataFrame,
    displacement_body_mult: float = 1.5,
    ob_search_window: int = 5,
) -> pd.DataFrame:
    """Detect bullish and bearish order blocks (strict definition).

    For each displacement bar t:
      - Bull displacement (body > mult×ATR, bullish, closes above 3-bar high):
            OB = last bearish candle in t-1..t-ob_search_window
      - Bear displacement (body > mult×ATR, bearish, closes below 3-bar low):
            OB = last bullish candle in t-1..t-ob_search_window

    Adds columns:
        bull_ob_formed    : bool — this bar IS a bullish OB
        bear_ob_formed    : bool — this bar IS a bearish OB
        bull_ob_high, bull_ob_low : float (OB zone, NaN if not an OB)
        bear_ob_high, bear_ob_low : float
        bull_ob_disp_idx  : int — index of the displacement bar that created this OB
        bear_ob_disp_idx  : int

    Strictly lookahead-free: OB at bar k is tagged at displacement time t > k.
    We write into the OB bar's row using the displacement bar's ATR/context,
    but only use data from bars <= t.
    """
    df = df.copy()
    n = len(df)

    body = (df["close"] - df["open"]).astype(float).values
    atr14 = df["atr14"].astype(float).values
    close_ = df["close"].astype(float).values
    open_ = df["open"].astype(float).values
    high_ = df["high"].astype(float).values
    low_ = df["low"].astype(float).values

    bull_ob_formed = np.zeros(n, dtype=bool)
    bear_ob_formed = np.zeros(n, dtype=bool)
    bull_ob_high = np.full(n, np.nan)
    bull_ob_low = np.full(n, np.nan)
    bear_ob_high = np.full(n, np.nan)
    bear_ob_low = np.full(n, np.nan)
    bull_ob_disp_idx = np.full(n, -1, dtype=int)
    bear_ob_disp_idx = np.full(n, -1, dtype=int)

    for t in range(4, n):
        atr_t = atr14[t]
        if atr_t <= 0 or np.isnan(atr_t):
            continue

        body_abs = abs(body[t])
        if body_abs <= displacement_body_mult * atr_t:
            continue  # body not large enough for displacement

        # BOS proxy: rolling 3-bar prior extreme
        prev_high_max = max(high_[max(0, t - 3): t])
        prev_low_min = min(low_[max(0, t - 3): t])

        # Bullish displacement?
        if body[t] > 0 and close_[t] > prev_high_max:
            # Search backward for the last bearish candle
            for k in range(t - 1, max(-1, t - ob_search_window - 1), -1):
                if body[k] < 0:  # bearish: close < open
                    if not bull_ob_formed[k]:  # don't overwrite
                        bull_ob_formed[k] = True
                        bull_ob_high[k] = high_[k]
                        bull_ob_low[k] = low_[k]
                        bull_ob_disp_idx[k] = t
                    break

        # Bearish displacement?
        if body[t] < 0 and close_[t] < prev_low_min:
            # Search backward for the last bullish candle
            for k in range(t - 1, max(-1, t - ob_search_window - 1), -1):
                if body[k] > 0:  # bullish: close > open
                    if not bear_ob_formed[k]:
                        bear_ob_formed[k] = True
                        bear_ob_high[k] = high_[k]
                        bear_ob_low[k] = low_[k]
                        bear_ob_disp_idx[k] = t
                    break

    df["bull_ob_formed"] = bull_ob_formed
    df["bear_ob_formed"] = bear_ob_formed
    df["bull_ob_high"] = bull_ob_high
    df["bull_ob_low"] = bull_ob_low
    df["bear_ob_high"] = bear_ob_high
    df["bear_ob_low"] = bear_ob_low
    df["bull_ob_disp_idx"] = bull_ob_disp_idx
    df["bear_ob_disp_idx"] = bear_ob_disp_idx
    return df


# =====================================================================
# Rejection pattern detectors
# =====================================================================

def _is_bullish_engulfing(
    o_curr: float,
    c_curr: float,
    o_prev: float,
    c_prev: float,
    body_ratio_min: float = 0.4,
    high_curr: float = np.nan,
    low_curr: float = np.nan,
) -> bool:
    """Strict bullish engulfing: current bullish body wraps previous bearish body.

    Requirements:
      - Current: close > open (bullish)
      - Previous: close < open (bearish) — opposite color
      - Current body wraps previous body: open <= prev_close AND close >= prev_open
      - body_ratio >= body_ratio_min (body / range)
    """
    if c_curr <= o_curr:
        return False  # must be bullish
    if c_prev >= o_prev:
        return False  # prev must be bearish
    if o_curr > c_prev or c_curr < o_prev:
        return False  # must wrap
    bar_range = high_curr - low_curr if not (np.isnan(high_curr) or np.isnan(low_curr)) else abs(c_curr - o_curr)
    if bar_range <= 0:
        return False
    body_ratio = abs(c_curr - o_curr) / bar_range
    return body_ratio >= body_ratio_min


def _is_bearish_engulfing(
    o_curr: float,
    c_curr: float,
    o_prev: float,
    c_prev: float,
    body_ratio_min: float = 0.4,
    high_curr: float = np.nan,
    low_curr: float = np.nan,
) -> bool:
    """Strict bearish engulfing."""
    if c_curr >= o_curr:
        return False
    if c_prev <= o_prev:
        return False
    if o_curr < c_prev or c_curr > o_prev:
        return False
    bar_range = high_curr - low_curr if not (np.isnan(high_curr) or np.isnan(low_curr)) else abs(c_curr - o_curr)
    if bar_range <= 0:
        return False
    body_ratio = abs(c_curr - o_curr) / bar_range
    return body_ratio >= body_ratio_min


def _is_bullish_pin(
    o: float,
    h: float,
    l: float,
    c: float,
    min_wick_body_ratio: float = 2.0,
) -> bool:
    """Hammer/bullish pin bar.

    Lower wick > min_wick_body_ratio × body
    Upper wick < body (small upper shadow)
    Body > 0 (close > open preferred but not required — hammer can be bearish body)
    """
    body = abs(c - o)
    if body <= 0:
        return False
    bar_range = h - l
    if bar_range <= 0:
        return False
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    return (
        lower_wick >= min_wick_body_ratio * body
        and upper_wick < body
        and lower_wick / bar_range >= 0.5  # lower wick at least 50% of range
    )


def _is_bearish_pin(
    o: float,
    h: float,
    l: float,
    c: float,
    min_wick_body_ratio: float = 2.0,
) -> bool:
    """Shooting star / bearish pin bar."""
    body = abs(c - o)
    if body <= 0:
        return False
    bar_range = h - l
    if bar_range <= 0:
        return False
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    return (
        upper_wick >= min_wick_body_ratio * body
        and lower_wick < body
        and upper_wick / bar_range >= 0.5
    )


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "ob_mitigation_strict",
        "version": "1.0.0",
        "description": (
            "SMC Order Block Mitigation Entry — strict: displacement > 1.5×ATR, "
            "OB zone re-entry, engulfing/pin rejection closing OUTSIDE zone, 3R target."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "ob_mit_long",
                    "enabled": True,
                    "weight": 3.0,
                    "params": {
                        "displacement_body_mult": 1.5,
                        "ob_search_window": 5,
                        "ob_max_age_bars": 60,
                        "body_ratio_min": 0.4,
                        "pin_wick_body_ratio": 2.0,
                        "sl_atr_buffer": 0.5,
                    },
                },
                {
                    "id": "ob_mit_short",
                    "enabled": True,
                    "weight": 3.0,
                    "params": {
                        "displacement_body_mult": 1.5,
                        "ob_search_window": 5,
                        "ob_max_age_bars": 60,
                        "body_ratio_min": 0.4,
                        "pin_wick_body_ratio": 2.0,
                        "sl_atr_buffer": 0.5,
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
                "atr_min_pct": 0.003,
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 3.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {
                "method": "ob_boundary",
                "atr_buffer": 0.5,
            },
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 250,
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy class
# =====================================================================

class OBMitigationStrictStrategy(Strategy):
    """SMC Order Block Mitigation Entry — Strict.

    Long entry:
        1. Bullish displacement identified (body > 1.5×ATR, BOS proxy).
        2. Last bearish candle before displacement = bullish OB (zone saved).
        3. Price re-enters OB zone (low <= OB_high AND high >= OB_low).
        4. Rejection bar inside OB zone: bullish engulfing OR pin bar.
        5. Rejection bar CLOSES above OB_high (mandatory close-outside).
        6. Signal emitted; entry = next bar open.
        7. SL = OB_low - 0.5×ATR; TP = 3R.
        8. Filter: close > EMA200.

    Short entry: symmetric mirror.

    Key stricter rules vs. smc_orderblock.py:
      * No liquidity grab requirement
      * Rejection bar MUST close OUTSIDE the OB zone
      * Dual pattern gate (engulfing OR pin)
      * Tighter SL buffer (0.5 ATR vs 1.0 ATR)
    """

    name = "ob_mitigation_strict"

    # Max OB lookback (bars)
    _OB_MAX_AGE = 60

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        df["ema200"] = _ema(df["close"], 200)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)

        # Volume z-score (60 bar)
        vol = df["volume"].astype(float)
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Displacement body multiplier from manifest
        disp_mult = self._get_param("displacement_body_mult", 1.5)
        ob_window = int(self._get_param("ob_search_window", 5))

        # OB detection
        df = _detect_ob_strict(df, displacement_body_mult=disp_mult, ob_search_window=ob_window)

        return df

    def _get_param(self, key: str, default: Any) -> Any:
        """Extract param from first enabled pattern, else default."""
        for p in self.manifest.signals.patterns:
            if p.enabled and key in p.params:
                return p.params[key]
        return default

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "atr14" not in df.columns:
            df = self.prepare_features(df)

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 3.0)
        )
        sl_atr_buffer = float(self._get_param("sl_atr_buffer", 0.5))
        body_ratio_min = float(self._get_param("body_ratio_min", 0.4))
        pin_wick_ratio = float(self._get_param("pin_wick_body_ratio", 2.0))
        ob_max_age = int(self._get_param("ob_max_age_bars", self._OB_MAX_AGE))
        atr_min_pct = float(
            getattr(self.manifest.signals.filters, "atr_min_pct", 0.003) or 0.003
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # Extract arrays for fast access
        close_ = df["close"].astype(float).values
        open_ = df["open"].astype(float).values
        high_ = df["high"].astype(float).values
        low_ = df["low"].astype(float).values
        atr14_ = df["atr14"].astype(float).values
        ema200_ = df["ema200"].astype(float).values
        atr_pct_ = df["atr_pct"].astype(float).values

        bull_ob_formed_ = df["bull_ob_formed"].values
        bear_ob_formed_ = df["bear_ob_formed"].values
        bull_ob_high_ = df["bull_ob_high"].astype(float).values
        bull_ob_low_ = df["bull_ob_low"].astype(float).values
        bear_ob_high_ = df["bear_ob_high"].astype(float).values
        bear_ob_low_ = df["bear_ob_low"].astype(float).values
        bull_ob_disp_idx_ = df["bull_ob_disp_idx"].astype(int).values
        bear_ob_disp_idx_ = df["bear_ob_disp_idx"].astype(int).values

        n = len(df)
        out: list[Signal] = []

        # Track which OBs have been invalidated (closed through)
        bull_ob_invalidated: set[int] = set()
        bear_ob_invalidated: set[int] = set()

        # Signal dedup: emit at most 1 signal per (direction, ob_bar_idx)
        bull_ob_signaled: set[int] = set()
        bear_ob_signaled: set[int] = set()

        for i in range(50, n):
            atr = atr14_[i]
            if atr <= 0 or np.isnan(atr):
                continue

            # ATR pct filter
            if atr_pct_[i] < atr_min_pct:
                continue

            # 200-EMA bias
            ema200 = ema200_[i]
            if np.isnan(ema200):
                continue

            bias_long = close_[i] > ema200
            bias_short = close_[i] < ema200

            # Current bar OHLC
            c = close_[i]
            o = open_[i]
            h = high_[i]
            l = low_[i]

            # Previous bar OHLC (for engulfing check)
            if i > 0:
                c_prev = close_[i - 1]
                o_prev = open_[i - 1]
            else:
                c_prev = o_prev = np.nan

            # ----------------------------------------------------------------
            # LONG: look for unmitigated bullish OBs in lookback window
            # ----------------------------------------------------------------
            if bias_long:
                for k in range(max(0, i - ob_max_age), i):
                    if not bull_ob_formed_[k]:
                        continue
                    if k in bull_ob_invalidated:
                        continue
                    if k in bull_ob_signaled:
                        continue

                    # OB must have been "created" before current bar
                    # (displacement bar index is bull_ob_disp_idx_[k])
                    disp_t = bull_ob_disp_idx_[k]
                    if disp_t >= i:
                        continue  # displacement not yet confirmed — skip (lookahead safety)

                    ob_high = bull_ob_high_[k]
                    ob_low = bull_ob_low_[k]
                    if np.isnan(ob_high) or np.isnan(ob_low):
                        continue

                    # Check if OB has been invalidated (price closed below ob_low)
                    # Scan from disp_t+1 to i-1 for close below ob_low
                    invalidated = False
                    for j in range(disp_t + 1, i):
                        if close_[j] < ob_low:
                            invalidated = True
                            break
                    if invalidated:
                        bull_ob_invalidated.add(k)
                        continue

                    # Mitigation check: does current bar touch OB zone?
                    zone_touched = (l <= ob_high) and (h >= ob_low)
                    if not zone_touched:
                        continue

                    # Rejection pattern check (current bar):
                    #   Option A: Bullish engulfing
                    engulf_ok = _is_bullish_engulfing(
                        o, c, o_prev, c_prev,
                        body_ratio_min=body_ratio_min,
                        high_curr=h, low_curr=l,
                    )
                    #   Option B: Bullish pin bar (hammer)
                    pin_ok = _is_bullish_pin(o, h, l, c, min_wick_body_ratio=pin_wick_ratio)

                    if not (engulf_ok or pin_ok):
                        continue

                    # Critical: close must be ABOVE OB_high (close outside zone)
                    if c <= ob_high:
                        continue

                    # All conditions met — emit signal
                    sl_price = ob_low - sl_atr_buffer * atr
                    risk = c - sl_price
                    if risk <= 0:
                        continue
                    tp_price = c + primary_R * risk

                    pattern_id = (
                        "ob_mit_long_engulf" if engulf_ok else "ob_mit_long_pin"
                    )
                    ts = pd.Timestamp(df["ts"].iloc[i]).to_pydatetime()
                    sig = self.emit_signal(
                        ts=ts,
                        venue=venue,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="long",
                        pattern_id=pattern_id,
                        confluence_score=3.0,
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=sl_atr_buffer,
                        metadata={
                            "ob_bar_idx": int(k),
                            "ob_high": float(ob_high),
                            "ob_low": float(ob_low),
                            "disp_idx": int(disp_t),
                            "atr14": float(atr),
                            "ema200": float(ema200),
                            "pattern": "engulfing" if engulf_ok else "pin",
                            "primary_R": primary_R,
                        },
                    )
                    out.append(sig)
                    bull_ob_signaled.add(k)
                    break  # one signal per bar (most recent valid OB)

            # ----------------------------------------------------------------
            # SHORT: look for unmitigated bearish OBs
            # ----------------------------------------------------------------
            if bias_short:
                for k in range(max(0, i - ob_max_age), i):
                    if not bear_ob_formed_[k]:
                        continue
                    if k in bear_ob_invalidated:
                        continue
                    if k in bear_ob_signaled:
                        continue

                    disp_t = bear_ob_disp_idx_[k]
                    if disp_t >= i:
                        continue

                    ob_high = bear_ob_high_[k]
                    ob_low = bear_ob_low_[k]
                    if np.isnan(ob_high) or np.isnan(ob_low):
                        continue

                    # Invalidation: close above ob_high
                    invalidated = False
                    for j in range(disp_t + 1, i):
                        if close_[j] > ob_high:
                            invalidated = True
                            break
                    if invalidated:
                        bear_ob_invalidated.add(k)
                        continue

                    # Mitigation check
                    zone_touched = (l <= ob_high) and (h >= ob_low)
                    if not zone_touched:
                        continue

                    # Rejection pattern
                    engulf_ok = _is_bearish_engulfing(
                        o, c, o_prev, c_prev,
                        body_ratio_min=body_ratio_min,
                        high_curr=h, low_curr=l,
                    )
                    pin_ok = _is_bearish_pin(o, h, l, c, min_wick_body_ratio=pin_wick_ratio)

                    if not (engulf_ok or pin_ok):
                        continue

                    # Critical: close must be BELOW OB_low (close outside zone)
                    if c >= ob_low:
                        continue

                    # All conditions met
                    sl_price = ob_high + sl_atr_buffer * atr
                    risk = sl_price - c
                    if risk <= 0:
                        continue
                    tp_price = c - primary_R * risk

                    pattern_id = (
                        "ob_mit_short_engulf" if engulf_ok else "ob_mit_short_pin"
                    )
                    ts = pd.Timestamp(df["ts"].iloc[i]).to_pydatetime()
                    sig = self.emit_signal(
                        ts=ts,
                        venue=venue,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="short",
                        pattern_id=pattern_id,
                        confluence_score=3.0,
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=sl_atr_buffer,
                        metadata={
                            "ob_bar_idx": int(k),
                            "ob_high": float(ob_high),
                            "ob_low": float(ob_low),
                            "disp_idx": int(disp_t),
                            "atr14": float(atr),
                            "ema200": float(ema200),
                            "pattern": "engulfing" if engulf_ok else "pin",
                            "primary_R": primary_R,
                        },
                    )
                    out.append(sig)
                    bear_ob_signaled.add(k)
                    break

        self._log.bind(n=len(out), bars=len(df)).info("ob_mit_strict.signals.generated")
        return out
