"""HYP-NEW-5: Failed Breakout + Bullish BOS + Low-Volume Reclaim Confirmation.

Edge mechanism:
  Brooks "Failed Breakout" trap (n-bar low penetration, 1-3 bar reclaim) occurring
  WITHIN a bullish BOS (Break of Structure) context, where the reclaim bar shows
  low volume (VSA no-supply) = institutional re-accumulation signature.

  Mirror short side: bearish BOS + failed BO up + low-vol reclaim down.

Three-concept confluence:
  1. Brooks Failed Breakout — trap mechanics (institutional stop-hunt + reversal)
  2. SMC/ICT BOS — structural break confirming uptrend context
  3. VSA No-Supply — low-volume reclaim = supply exhausted, institutions absorbing

Mechanical rules (long):
  1. Bullish BOS active: close > prior swing high (HH) within last 30 bars
  2. Failed breakout: price breaks BELOW recent swing low (n=10) within last 1-3 bars
  3. Reclaim bar: price closes BACK above swing low within next 1-3 bars
  4. Low-volume: reclaim bar volume < 0.7 * SMA(20)
  5. Entry: next bar open (post-reclaim)
  6. SL: failed BO extreme low - 0.5 * ATR(14)
  7. TP: 2.5R primary

Symmetric short: bearish BOS (close < prior swing low) + failed BO up + low-vol reclaim down.
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
)


# =====================================================================
# Helper functions
# =====================================================================

def _vol_sma(volume: pd.Series, window: int = 20) -> pd.Series:
    """Rolling volume SMA (lookahead-free)."""
    return volume.astype(float).rolling(window, min_periods=max(5, window // 4)).mean()


def _swing_highs_lookahead_free(df: pd.DataFrame, n: int = 3) -> pd.Series:
    """n-bar fractal swing highs, fully lookahead-free.

    A bar at position t is a swing high if high[t] > all highs in [t-n..t-1].
    We do NOT look forward — this is strictly left-side only for live use.
    Confirmed at bar t (known at bar t).
    """
    h = df["high"].astype(float)
    left_max = h.shift(1).rolling(n, min_periods=n).max()
    return (h > left_max).fillna(False).astype(bool)


def _swing_lows_lookahead_free(df: pd.DataFrame, n: int = 3) -> pd.Series:
    """n-bar fractal swing lows, fully lookahead-free (left-side only)."""
    l = df["low"].astype(float)
    left_min = l.shift(1).rolling(n, min_periods=n).min()
    return (l < left_min).fillna(False).astype(bool)


def _detect_bullish_bos(
    df: pd.DataFrame,
    lookback: int = 30,
    swing_n: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """Bullish Break of Structure (BOS) detector.

    BOS at bar t if:
      - close[t] > rolling_max(high, lookback)[t-1]
        i.e., close breaks above the highest high of the prior lookback bars.

    This is the most robust mechanical BOS definition:
    - Lookahead-free: rolling max uses shift(1) so bar t's own high is excluded.
    - Works on all market regimes (trending, ranging).
    - Matches literature: "close above prior swing high region" = structural break.

    BOS carries forward for `lookback` bars (BOS remains "active" for trend context).

    Returns:
      bos_active (bool Series): True while in BOS context
      bos_level (float Series): The high level that was broken (set at BOS bar)
    """
    # Rolling max of prior lookback bars' highs (shift(1) = strict past-only)
    prior_max_high = (
        df["high"].astype(float)
        .shift(1)
        .rolling(lookback, min_periods=max(5, lookback // 4))
        .max()
    )
    closes = df["close"].astype(float)

    bos_confirmed = (closes > prior_max_high).fillna(False)
    bos_level_arr = prior_max_high.where(bos_confirmed)

    # Carry forward: BOS active for next `lookback` bars after confirmation
    bos_active_arr = np.zeros(len(df), dtype=bool)
    bos_conf_np = bos_confirmed.to_numpy()
    last_bos_t = -1
    for t in range(len(df)):
        if bos_conf_np[t]:
            last_bos_t = t
        if last_bos_t >= 0 and (t - last_bos_t) <= lookback:
            bos_active_arr[t] = True

    return (
        pd.Series(bos_active_arr, index=df.index, name="bos_active"),
        bos_level_arr.rename("bos_level"),
    )


def _detect_bearish_bos(
    df: pd.DataFrame,
    lookback: int = 30,
    swing_n: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """Bearish BOS: close < rolling_min(low, lookback)[t-1].

    Lookahead-free: prior-only rolling min.
    BOS carries forward for `lookback` bars.

    Returns:
      bos_active, bos_level (the low level that was broken)
    """
    prior_min_low = (
        df["low"].astype(float)
        .shift(1)
        .rolling(lookback, min_periods=max(5, lookback // 4))
        .min()
    )
    closes = df["close"].astype(float)

    bos_confirmed = (closes < prior_min_low).fillna(False)
    bos_level_arr = prior_min_low.where(bos_confirmed)

    bos_active_arr = np.zeros(len(df), dtype=bool)
    bos_conf_np = bos_confirmed.to_numpy()
    last_bos_t = -1
    for t in range(len(df)):
        if bos_conf_np[t]:
            last_bos_t = t
        if last_bos_t >= 0 and (t - last_bos_t) <= lookback:
            bos_active_arr[t] = True

    return (
        pd.Series(bos_active_arr, index=df.index, name="bear_bos_active"),
        bos_level_arr.rename("bear_bos_level"),
    )


def _detect_failed_breakout_long(
    df: pd.DataFrame,
    n: int = 10,
    max_reclaim_bars: int = 3,
    max_bo_bars: int = 3,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Failed breakout long setup detector.

    Detects the RECLAIM bar of a bearish failed breakout:
      Phase 1 (Breakout): Within last max_bo_bars, price breaks BELOW recent n-bar swing low
        - low[j] < rolling_min(low, n)[j-1] (new n-bar low)
      Phase 2 (Reclaim): Within max_reclaim_bars after the breakout bar,
        - close[k] > that same swing low level (close back above)
      Phase 3 (No-supply volume): checked separately

    Returns:
      reclaim_confirmed (bool): bar where reclaim is confirmed
      failed_bo_low (float): the extreme low of the failed breakout bar
      swing_low_level (float): the swing low level that was violated then reclaimed
    """
    n_bars = len(df)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)

    # Rolling min of low over n bars (strictly prior to bar t)
    swing_low_ref = df["low"].shift(1).rolling(n, min_periods=max(3, n // 2)).min().to_numpy()

    reclaim_flags = np.zeros(n_bars, dtype=bool)
    failed_bo_low_arr = np.full(n_bars, np.nan)
    swing_low_arr = np.full(n_bars, np.nan)

    for t in range(n + 1, n_bars):
        # Look for a breakout bar in [t-max_bo_bars-max_reclaim_bars .. t-1]
        # Use the swing_low_ref AT the breakout bar (not at t) to avoid contamination
        search_start = max(n, t - max_bo_bars - max_reclaim_bars)
        for bo_bar in range(search_start, t):
            bo_sl_level = swing_low_ref[bo_bar]
            if np.isnan(bo_sl_level):
                continue
            # Breakout: bar's low goes below the rolling min at that point in time
            if lows[bo_bar] < bo_sl_level:
                extreme_low = lows[bo_bar]
                # Reclaim: within next max_reclaim_bars, close back above bo_sl_level
                for reclaim_offset in range(1, max_reclaim_bars + 1):
                    reclaim_bar = bo_bar + reclaim_offset
                    if reclaim_bar >= n_bars:
                        break
                    if closes[reclaim_bar] > bo_sl_level:
                        # Reclaim confirmed at reclaim_bar
                        if reclaim_bar == t:
                            reclaim_flags[t] = True
                            failed_bo_low_arr[t] = extreme_low
                            swing_low_arr[t] = bo_sl_level
                        break
                if reclaim_flags[t]:
                    break

    return (
        pd.Series(reclaim_flags, index=df.index, name="fbo_long_reclaim"),
        pd.Series(failed_bo_low_arr, index=df.index, name="fbo_long_extreme_low"),
        pd.Series(swing_low_arr, index=df.index, name="fbo_long_sw_level"),
    )


def _detect_failed_breakout_short(
    df: pd.DataFrame,
    n: int = 10,
    max_reclaim_bars: int = 3,
    max_bo_bars: int = 3,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Failed breakout short setup: price breaks ABOVE n-bar swing high then reclaims below.

    Returns:
      reclaim_confirmed (bool): bar where reclaim is confirmed (close < swing high)
      failed_bo_high (float): extreme high of failed breakout bar
      swing_high_level (float): the swing high level that was violated then reclaimed
    """
    n_bars = len(df)
    highs = df["high"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)

    swing_high_ref = df["high"].shift(1).rolling(n, min_periods=max(3, n // 2)).max().to_numpy()

    reclaim_flags = np.zeros(n_bars, dtype=bool)
    failed_bo_high_arr = np.full(n_bars, np.nan)
    swing_high_arr = np.full(n_bars, np.nan)

    for t in range(n + 1, n_bars):
        search_start = max(n, t - max_bo_bars - max_reclaim_bars)
        for bo_bar in range(search_start, t):
            bo_sh_level = swing_high_ref[bo_bar]
            if np.isnan(bo_sh_level):
                continue
            # Breakout: bar's high exceeds the rolling max at that point in time
            if highs[bo_bar] > bo_sh_level:
                extreme_high = highs[bo_bar]
                for reclaim_offset in range(1, max_reclaim_bars + 1):
                    reclaim_bar = bo_bar + reclaim_offset
                    if reclaim_bar >= n_bars:
                        break
                    if closes[reclaim_bar] < bo_sh_level:
                        if reclaim_bar == t:
                            reclaim_flags[t] = True
                            failed_bo_high_arr[t] = extreme_high
                            swing_high_arr[t] = bo_sh_level
                        break
                if reclaim_flags[t]:
                    break

    return (
        pd.Series(reclaim_flags, index=df.index, name="fbo_short_reclaim"),
        pd.Series(failed_bo_high_arr, index=df.index, name="fbo_short_extreme_high"),
        pd.Series(swing_high_arr, index=df.index, name="fbo_short_sw_level"),
    )


def _low_volume_reclaim(
    volume: pd.Series,
    vol_ratio: float = 0.7,
    sma_period: int = 20,
) -> pd.Series:
    """Low-volume bar: volume < vol_ratio * SMA(sma_period).

    VSA no-supply: institutional absorbing, supply exhausted.
    Returns bool Series.
    """
    vsma = _vol_sma(volume, window=sma_period)
    return (volume.astype(float) < vol_ratio * vsma).fillna(False).astype(bool)


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "failed_bo_bos_reclaim",
        "version": "1.0.0",
        "description": (
            "HYP-NEW-5: Brooks Failed BO + SMC BOS + VSA No-Supply Reclaim. "
            "3-concept confluence: trap mechanics + structural break + volume confirmation."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "failed_bo_bos_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "bos_lookback": 30,
                        "swing_n": 3,
                        "fbo_n": 10,
                        "max_reclaim_bars": 3,
                        "vol_ratio": 0.7,
                        "vol_sma_period": 20,
                        "tp_r": 2.5,
                        "sl_atr_mult": 0.5,
                    },
                },
                {
                    "id": "failed_bo_bos_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "bos_lookback": 30,
                        "swing_n": 3,
                        "fbo_n": 10,
                        "max_reclaim_bars": 3,
                        "vol_ratio": 0.7,
                        "vol_sma_period": 20,
                        "tp_r": 2.5,
                        "sl_atr_mult": 0.5,
                    },
                },
            ],
            "filters": {
                "atr_min_pct": 0.005,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
            },
        },
        "risk": {
            "stop_loss": {"method": "atr", "atr_period": 14, "atr_multiplier": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 2.5},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 60,
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy class
# =====================================================================

class FailedBOBOSReclaimStrategy(Strategy):
    """HYP-NEW-5: Failed Breakout + Bullish BOS + Low-Volume Reclaim.

    Long side:
      - Bullish BOS active (close > prior swing high in last 30 bars)
      - Failed breakout below recent swing low (n=10)
      - Reclaim bar closes back above swing low within 1-3 bars
      - Reclaim bar volume < 0.7 * SMA(20) [VSA no-supply]
      - Entry: next bar open
      - SL: failed BO extreme low - 0.5*ATR
      - TP: 2.5R

    Short side (mirror):
      - Bearish BOS active (close < prior swing low in last 30 bars)
      - Failed breakout above recent swing high (n=10)
      - Reclaim bar closes back below swing high within 1-3 bars
      - Reclaim bar volume < 0.7 * SMA(20)
      - Entry: next bar open (short)
      - SL: failed BO extreme high + 0.5*ATR
      - TP: 2.5R
    """

    def __init__(self, manifest: StrategyManifest) -> None:
        super().__init__(manifest)
        self._log = logger.bind(strategy=self.name)

        # Extract params from manifest
        long_cfg = next(
            (p.params for p in manifest.signals.patterns if p.id == "failed_bo_bos_long"),
            {},
        )
        short_cfg = next(
            (p.params for p in manifest.signals.patterns if p.id == "failed_bo_bos_short"),
            {},
        )

        self.bos_lookback: int = int(long_cfg.get("bos_lookback", 30))
        self.swing_n: int = int(long_cfg.get("swing_n", 3))
        self.fbo_n: int = int(long_cfg.get("fbo_n", 10))
        self.max_reclaim_bars: int = int(long_cfg.get("max_reclaim_bars", 3))
        self.vol_ratio: float = float(long_cfg.get("vol_ratio", 0.7))
        self.vol_sma_period: int = int(long_cfg.get("vol_sma_period", 20))
        self.tp_r: float = float(long_cfg.get("tp_r", 2.5))
        self.sl_atr_mult: float = float(long_cfg.get("sl_atr_mult", 0.5))

        # Short side uses same params by default
        self.short_enabled: bool = any(
            p.id == "failed_bo_bos_short" and p.enabled
            for p in manifest.signals.patterns
        )

    # ------------------------------------------------------------------
    # Feature preparation
    # ------------------------------------------------------------------

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute all required features: ATR, volume SMA, BOS flags, FBO flags."""
        df = df.copy()
        if df.empty:
            return df

        # Core indicators
        df["atr14"] = _atr(df, period=14)
        df["ema200"] = _ema(df["close"].astype(float), period=200)
        df["vol_sma20"] = _vol_sma(df["volume"], window=self.vol_sma_period)
        df["low_vol"] = _low_volume_reclaim(
            df["volume"], vol_ratio=self.vol_ratio, sma_period=self.vol_sma_period
        )

        # Bullish BOS
        bull_bos_active, bull_bos_level = _detect_bullish_bos(
            df, lookback=self.bos_lookback, swing_n=self.swing_n
        )
        df["bull_bos_active"] = bull_bos_active
        df["bull_bos_level"] = bull_bos_level

        # Bearish BOS
        bear_bos_active, bear_bos_level = _detect_bearish_bos(
            df, lookback=self.bos_lookback, swing_n=self.swing_n
        )
        df["bear_bos_active"] = bear_bos_active
        df["bear_bos_level"] = bear_bos_level

        # Failed breakout long (failed breakdown — price drops below swing low then reclaims)
        fbo_long_reclaim, fbo_long_extreme_low, fbo_long_sw_level = _detect_failed_breakout_long(
            df, n=self.fbo_n, max_reclaim_bars=self.max_reclaim_bars
        )
        df["fbo_long_reclaim"] = fbo_long_reclaim
        df["fbo_long_extreme_low"] = fbo_long_extreme_low
        df["fbo_long_sw_level"] = fbo_long_sw_level

        # Failed breakout short (failed breakup — price rises above swing high then reclaims)
        fbo_short_reclaim, fbo_short_extreme_high, fbo_short_sw_level = _detect_failed_breakout_short(
            df, n=self.fbo_n, max_reclaim_bars=self.max_reclaim_bars
        )
        df["fbo_short_reclaim"] = fbo_short_reclaim
        df["fbo_short_extreme_high"] = fbo_short_extreme_high
        df["fbo_short_sw_level"] = fbo_short_sw_level

        # Combined signal flags
        df["signal_long"] = (
            df["bull_bos_active"]
            & df["fbo_long_reclaim"]
            & df["low_vol"]
        )
        df["signal_short"] = (
            df["bear_bos_active"]
            & df["fbo_short_reclaim"]
            & df["low_vol"]
        ) if self.short_enabled else pd.Series(False, index=df.index)

        return df

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Generate signals from prepared features. Entry at next bar open."""
        if df.empty:
            return []

        signals: list[Signal] = []
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "binance"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        n = len(df)
        atr_vals = df["atr14"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)

        long_flags = df["signal_long"].to_numpy(dtype=bool)
        short_flags = df["signal_short"].to_numpy(dtype=bool) if self.short_enabled else np.zeros(n, dtype=bool)

        fbo_long_extreme_low = df["fbo_long_extreme_low"].to_numpy(dtype=float)
        fbo_short_extreme_high = df["fbo_short_extreme_high"].to_numpy(dtype=float)

        # Warmup: need at least bos_lookback + fbo_n bars
        warmup = self.bos_lookback + self.fbo_n + self.vol_sma_period

        for i in range(warmup, n - 1):
            atr_i = float(atr_vals[i])
            if np.isnan(atr_i) or atr_i <= 0:
                continue

            # --- Long signal ---
            if long_flags[i]:
                extreme_low = float(fbo_long_extreme_low[i])
                if np.isnan(extreme_low):
                    continue

                sl = extreme_low - self.sl_atr_mult * atr_i
                entry_approx = float(closes[i])  # next bar open (approximate)
                risk = abs(entry_approx - sl)
                if risk <= 0:
                    continue
                tp = entry_approx + self.tp_r * risk

                sig = self.emit_signal(
                    ts=df["ts"].iloc[i],
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="long",
                    pattern_id="failed_bo_bos_long",
                    confluence_score=2.0,
                    sl_price=sl,
                    tp_price=tp,
                    suggested_size_atr=1.0,
                    metadata={
                        "atr14": atr_i,
                        "extreme_low": extreme_low,
                        "tp_r": self.tp_r,
                        "bull_bos_active": True,
                        "low_vol_reclaim": True,
                    },
                )
                signals.append(sig)

            # --- Short signal ---
            if short_flags[i]:
                extreme_high = float(fbo_short_extreme_high[i])
                if np.isnan(extreme_high):
                    continue

                sl = extreme_high + self.sl_atr_mult * atr_i
                entry_approx = float(closes[i])
                risk = abs(sl - entry_approx)
                if risk <= 0:
                    continue
                tp = entry_approx - self.tp_r * risk

                sig = self.emit_signal(
                    ts=df["ts"].iloc[i],
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="short",
                    pattern_id="failed_bo_bos_short",
                    confluence_score=2.0,
                    sl_price=sl,
                    tp_price=tp,
                    suggested_size_atr=1.0,
                    metadata={
                        "atr14": atr_i,
                        "extreme_high": extreme_high,
                        "tp_r": self.tp_r,
                        "bear_bos_active": True,
                        "low_vol_reclaim": True,
                    },
                )
                signals.append(sig)

        self._log.bind(
            symbol=symbol, n_signals=len(signals),
            long_count=sum(1 for s in signals if s.direction == "long"),
            short_count=sum(1 for s in signals if s.direction == "short"),
        ).info("failed_bo_bos.generate_signals.done")

        return signals
