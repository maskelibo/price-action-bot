"""Bollinger Band Continuation strategy (15m R4 Yol G).

Sprint: SEC-S5 Yol G (directional flip follow-up)
Pre-registration: memory/researcher/hypotheses/2026-05-17-bb-continuation-15m.md
Predecessor: bollinger_fade_mr (RED) - directional flip yan-bulgu

Rule summary (CONTINUATION - fade'in tersi):
  - BB(20, 2.0) outer band close-BEYOND at t-1 (true breakout, not wick touch)
    - Long:  close(t-1) > BB_upper(t-1)
    - Short: close(t-1) < BB_lower(t-1)
  - RSI(14) extreme at t-1 (v1: >75/<25 sikilastirilmis; v2: >70/<30 default)
  - NO ADX filter (regime-agnostik - momentum istegimiz)
  - Momentum candle confirm at t-1 (same direction body):
    - Long: close > open AND body >= body_ratio * range
    - Short: close < open AND body >= body_ratio * range
  - Entry: bar(t) open (t-1 close after decision -> lookahead-safe)
  - SL: structural 1.5x ATR(14)
  - TP: 1.2R

Key vs bollinger_fade_mr:
  1. Signal direction FLIPPED (upper close-beyond -> LONG, lower -> SHORT)
  2. NO ADX filter (continuation regime-agnostik)
  3. BB touch = close BEYOND (true break) vs wick TOUCH (extension test)
  4. Momentum body confirm vs reversal body/wick confirm

Reference patterns: bollinger_fade_mr.py (base template, signal flipped).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr


# =====================================================================
# Vectorized indicators (lookahead-free) - copied from bollinger_fade_mr
# =====================================================================

def _bollinger_bands(close: pd.Series, period: int = 20, n_std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Standard Bollinger Bands. Uses rolling mean/std up to and including t.

    Lookahead-safe: only past `period` bars.
    Returns (upper, mid, lower).
    """
    mid = close.rolling(period, min_periods=period).mean()
    sd = close.rolling(period, min_periods=period).std(ddof=1)
    upper = mid + n_std * sd
    lower = mid - n_std * sd
    return upper, mid, lower


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI. Lookahead-free (uses past bars only)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)


def _swing_sl(df: pd.DataFrame, direction: str, lookback: int = 10) -> pd.Series:
    """Structural SL: past `lookback` bars swing low/high (uses shift(1) -> safe).

    For CONTINUATION:
      - long: SL at swing_LOW of past bars (entry sits above; structure below)
      - short: SL at swing_HIGH of past bars (entry sits below; structure above)
    Same as fade structurally (SL always opposite of trade direction).
    """
    if direction == "long":
        return df["low"].shift(1).rolling(lookback, min_periods=1).min()
    return df["high"].shift(1).rolling(lookback, min_periods=1).max()


# =====================================================================
# Default manifest (v1 - sikilastirilmis high-quality)
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "bb_band_continuation",
        "version": "1.0.0",
        "description": (
            "BB outer band CLOSE-BEYOND + RSI extreme + momentum candle. "
            "Trigger-direction CONTINUATION (15m R4 Yol G, SEC-S5 followup, v1)."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "bb_cont_long",
                    "enabled": True,
                    "weight": 2.5,
                    "params": {
                        "bb_period": 20,
                        "bb_std": 2.0,
                        "rsi_period": 14,
                        "rsi_overbought": 75.0,  # v1 sikilastirilmis
                        "body_ratio_min": 0.5,   # body >= 50% range
                    },
                },
                {
                    "id": "bb_cont_short",
                    "enabled": True,
                    "weight": 2.5,
                    "params": {
                        "bb_period": 20,
                        "bb_std": 2.0,
                        "rsi_period": 14,
                        "rsi_oversold": 25.0,  # v1 sikilastirilmis
                        "body_ratio_min": 0.5,
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
                "min_score": 2.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "atr", "atr_multiplier": 1.5, "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 1.2},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 220,
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10_000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


def _v2_manifest() -> StrategyManifest:
    """Pre-reg fallback: v2 thresholds (RSI 70/30 default, body 0.4).

    Used if v1 n < 500 (sample density fallback per pre-registration).
    """
    raw = {
        "name": "bb_band_continuation",
        "version": "1.0.0-v2",
        "description": (
            "BB outer band CLOSE-BEYOND + RSI extreme + momentum candle. "
            "v2 (RSI 70/30, body 0.4) - sample density fallback per pre-reg."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "bb_cont_long",
                    "enabled": True,
                    "weight": 2.5,
                    "params": {
                        "bb_period": 20,
                        "bb_std": 2.0,
                        "rsi_period": 14,
                        "rsi_overbought": 70.0,  # v2 default
                        "body_ratio_min": 0.4,   # v2 body floor
                    },
                },
                {
                    "id": "bb_cont_short",
                    "enabled": True,
                    "weight": 2.5,
                    "params": {
                        "bb_period": 20,
                        "bb_std": 2.0,
                        "rsi_period": 14,
                        "rsi_oversold": 30.0,
                        "body_ratio_min": 0.4,
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
                "min_score": 2.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "atr", "atr_multiplier": 1.5, "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 1.2},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 220,
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10_000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy
# =====================================================================

class BBBandContinuationStrategy(Strategy):
    """BB close-beyond + RSI extreme + momentum candle CONTINUATION.

    Long:  bar(t-1) close > BB_upper AND RSI>thr AND momentum bullish body
    Short: bar(t-1) close < BB_lower AND RSI<thr AND momentum bearish body
    Entry: bar(t) open
    SL:    structural (long: min(swing_low(10), entry - 1.5*ATR))
    TP:    1.2R
    """

    name = "bb_band_continuation"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # Pattern params
        long_params: dict[str, Any] = {}
        short_params: dict[str, Any] = {}
        for p in self.manifest.signals.patterns:
            if p.id == "bb_cont_long":
                long_params = dict(p.params)
            elif p.id == "bb_cont_short":
                short_params = dict(p.params)

        bb_period = int(long_params.get("bb_period", 20))
        bb_std = float(long_params.get("bb_std", 2.0))
        rsi_period = int(long_params.get("rsi_period", 14))
        rsi_ob = float(long_params.get("rsi_overbought", 75.0))
        rsi_os = float(short_params.get("rsi_oversold", 25.0))
        body_ratio_long = float(long_params.get("body_ratio_min", 0.5))
        body_ratio_short = float(short_params.get("body_ratio_min", 0.5))

        # Indicators (lookahead-safe; pure rolling on close/high/low)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)

        upper, mid, lower = _bollinger_bands(df["close"], period=bb_period, n_std=bb_std)
        df["bb_upper"] = upper
        df["bb_mid"] = mid
        df["bb_lower"] = lower

        df["rsi"] = _rsi(df["close"], period=rsi_period)

        # Momentum candle bodies
        body = (df["close"] - df["open"]).abs()
        rng = (df["high"] - df["low"]).clip(lower=1e-12)
        df["body_ratio"] = body / rng

        bullish_body = df["close"] > df["open"]
        bearish_body = df["close"] < df["open"]

        df["bull_momentum"] = bullish_body & (df["body_ratio"] >= body_ratio_long)
        df["bear_momentum"] = bearish_body & (df["body_ratio"] >= body_ratio_short)

        # CLOSE BEYOND BB (continuation break)
        # Long: close > upper (above the wall, momentum push)
        # Short: close < lower
        df["close_above_upper"] = df["close"] > df["bb_upper"]
        df["close_below_lower"] = df["close"] < df["bb_lower"]

        # RSI extreme
        df["rsi_overbought"] = df["rsi"] > rsi_ob
        df["rsi_oversold"] = df["rsi"] < rsi_os

        # Composite setup at t-1; entry bar t (lookahead-safe: ALL conditions
        # use shift(1) -> bar t signal depends only on prior bar data)
        df["long_setup_prev"] = (
            df["close_above_upper"].shift(1).fillna(False).astype(bool)
            & df["rsi_overbought"].shift(1).fillna(False).astype(bool)
            & df["bull_momentum"].shift(1).fillna(False).astype(bool)
        )
        df["short_setup_prev"] = (
            df["close_below_lower"].shift(1).fillna(False).astype(bool)
            & df["rsi_oversold"].shift(1).fillna(False).astype(bool)
            & df["bear_momentum"].shift(1).fillna(False).astype(bool)
        )

        # Structural SL levels (uses shift(1) inside _swing_sl -> safe)
        df["struct_sl_long"] = _swing_sl(df, "long", lookback=10)
        df["struct_sl_short"] = _swing_sl(df, "short", lookback=10)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "bb_upper" not in df.columns:
            df = self.prepare_features(df)

        filters = self.manifest.signals.filters
        atr_min = float(getattr(filters, "atr_min_pct", 0.003) or 0.003)
        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 1.2)
        )
        sl_cfg = self.manifest.risk.get("stop_loss", {}) or {}
        atr_mult = float(sl_cfg.get("atr_multiplier", 1.5))

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "15m"

        out: list[Signal] = []
        n = len(df)

        for i in range(1, n):  # i=0: no prior bar
            row = df.iloc[i]
            atr = float(row.get("atr14") or 0.0)
            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr <= 0 or np.isnan(atr) or atr_pct < atr_min:
                continue
            open_ = float(row["open"])
            if open_ <= 0:
                continue

            # LONG: bar(t-1) setup -> entry at bar(t) open
            if bool(row.get("long_setup_prev", False)):
                # For continuation LONG, SL below entry. Use:
                # - structural: nearest swing_low(10) (below entry)
                # - ATR floor: entry - 1.5*ATR
                # Choose the tighter (closer to entry) one for better R
                struct = float(row.get("struct_sl_long") or 0.0)
                sl_struct = struct if struct > 0 and not np.isnan(struct) else (open_ - atr_mult * atr)
                sl_atr = open_ - atr_mult * atr
                # Use the LOWER (further) one for safety; momentum break needs room
                # Actually: continuation entries should give MORE room (not less) since
                # we're entering AFTER a strong push. Use the further (more conservative) SL.
                sl_price = min(sl_struct, sl_atr)
                # Safety: at least 0.5 ATR risk to avoid micro-stops
                sl_price = min(sl_price, open_ - 0.5 * atr)
                risk = open_ - sl_price
                if risk <= 0:
                    continue
                tp_price = open_ + primary_R * risk
                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts, venue=venue, symbol=symbol, timeframe=timeframe,
                    direction="long", pattern_id="bb_cont_long",
                    confluence_score=2.5,
                    sl_price=float(sl_price), tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "bb_upper_prev": float(df["bb_upper"].iat[i - 1]),
                        "rsi_prev": float(df["rsi"].iat[i - 1]),
                        "body_ratio_prev": float(df["body_ratio"].iat[i - 1]),
                        "atr14": atr,
                        "risk_r": float(risk),
                    },
                )
                out.append(sig)

            # SHORT: bar(t-1) setup
            if bool(row.get("short_setup_prev", False)):
                struct = float(row.get("struct_sl_short") or 0.0)
                sl_struct = struct if struct > 0 and not np.isnan(struct) else (open_ + atr_mult * atr)
                sl_atr = open_ + atr_mult * atr
                sl_price = max(sl_struct, sl_atr)
                sl_price = max(sl_price, open_ + 0.5 * atr)
                risk = sl_price - open_
                if risk <= 0:
                    continue
                tp_price = open_ - primary_R * risk
                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts, venue=venue, symbol=symbol, timeframe=timeframe,
                    direction="short", pattern_id="bb_cont_short",
                    confluence_score=2.5,
                    sl_price=float(sl_price), tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "bb_lower_prev": float(df["bb_lower"].iat[i - 1]),
                        "rsi_prev": float(df["rsi"].iat[i - 1]),
                        "body_ratio_prev": float(df["body_ratio"].iat[i - 1]),
                        "atr14": atr,
                        "risk_r": float(risk),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("bb_band_continuation.signals.generated")
        return out
