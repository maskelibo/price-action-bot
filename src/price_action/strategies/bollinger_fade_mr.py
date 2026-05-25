"""Bollinger Fade Mean-Reversion strategy (15m R4 MR pool).

Sprint: SEC-S5 MR pool diversification (HYP-2026-05-17-bollinger-fade-mr-15m).

Rule summary:
  - BB(20, 2.0) outer band touch at t-1
  - RSI(14) extreme at t-1 (<30 long / >70 short)
  - ADX(14) < 20 at t-1 (range regime)
  - Reversal candle confirm at t-1 (bullish/bearish or wick-dominated)
  - Entry: bar(t) open (t-1 close after decision -> lookahead-safe)
  - SL: structural 1.5x ATR(14)
  - TP: 1.2R
  - Confluence: 2.0 base + 0.5 bonus

Pre-registration: memory/researcher/hypotheses/2026-05-17-bollinger-fade-mr-15m.md
Reference patterns: vsa_climax_test.py, engulfing_continuation.py
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr


# =====================================================================
# Vectorized indicators (lookahead-free)
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


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ADX (Average Directional Index). Lookahead-free.

    Computes +DI, -DI, then ADX as smoothed |+DI - -DI| / (+DI + -DI).
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat(
        [
            (high - low).abs(),
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr_w = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    plus_di = 100.0 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=1.0 / period, adjust=False, min_periods=period
    ).mean() / atr_w.replace(0.0, np.nan)
    minus_di = 100.0 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=1.0 / period, adjust=False, min_periods=period
    ).mean() / atr_w.replace(0.0, np.nan)

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    return adx.fillna(0.0)


def _swing_sl(df: pd.DataFrame, direction: str, lookback: int = 10) -> pd.Series:
    """Structural SL: past `lookback` bars swing low/high (uses shift(1) -> safe)."""
    if direction == "long":
        return df["low"].shift(1).rolling(lookback, min_periods=1).min()
    return df["high"].shift(1).rolling(lookback, min_periods=1).max()


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "bollinger_fade_mr",
        "version": "1.0.0",
        "description": (
            "Bollinger Band outer touch + RSI extreme + ADX range + reversal "
            "candle confirm. Mean-reversion fade (15m R4 MR pool, SEC-S5)."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "bb_fade_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "bb_period": 20,
                        "bb_std": 2.0,
                        "rsi_period": 14,
                        "rsi_oversold": 30.0,
                        "adx_period": 14,
                        "adx_threshold": 20.0,
                        "wick_ratio_min": 2.0,
                    },
                },
                {
                    "id": "bb_fade_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "bb_period": 20,
                        "bb_std": 2.0,
                        "rsi_period": 14,
                        "rsi_overbought": 70.0,
                        "adx_period": 14,
                        "adx_threshold": 20.0,
                        "wick_ratio_min": 2.0,
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
                "min_score": 1.5,
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

class BollingerFadeMRStrategy(Strategy):
    """Bollinger fade in range regime.

    Long:  bar(t-1) low <= BB_lower AND RSI<30 AND ADX<20 AND bullish reversal
    Short: bar(t-1) high >= BB_upper AND RSI>70 AND ADX<20 AND bearish reversal
    Entry: bar(t) open
    SL:    structural swing (long: min(swing_low(10), entry - 1.5*ATR))
    TP:    1.2R
    """

    name = "bollinger_fade_mr"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # Pattern params
        long_params: dict[str, Any] = {}
        short_params: dict[str, Any] = {}
        for p in self.manifest.signals.patterns:
            if p.id == "bb_fade_long":
                long_params = dict(p.params)
            elif p.id == "bb_fade_short":
                short_params = dict(p.params)

        bb_period = int(long_params.get("bb_period", 20))
        bb_std = float(long_params.get("bb_std", 2.0))
        rsi_period = int(long_params.get("rsi_period", 14))
        rsi_os = float(long_params.get("rsi_oversold", 30.0))
        rsi_ob = float(short_params.get("rsi_overbought", 70.0))
        adx_period = int(long_params.get("adx_period", 14))
        adx_thr = float(long_params.get("adx_threshold", 20.0))
        wick_ratio = float(long_params.get("wick_ratio_min", 2.0))

        # Indicators
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)

        upper, mid, lower = _bollinger_bands(df["close"], period=bb_period, n_std=bb_std)
        df["bb_upper"] = upper
        df["bb_mid"] = mid
        df["bb_lower"] = lower

        df["rsi"] = _rsi(df["close"], period=rsi_period)
        df["adx"] = _adx(df, period=adx_period)

        # Reversal candle: bullish body OR strong lower wick (hammer-like)
        body = (df["close"] - df["open"]).abs()
        lower_wick = (df[["open", "close"]].min(axis=1) - df["low"]).clip(lower=0)
        upper_wick = (df["high"] - df[["open", "close"]].max(axis=1)).clip(lower=0)

        body_safe = body.replace(0, np.nan)
        df["wick_lower_dom"] = (lower_wick / body_safe).fillna(0)
        df["wick_upper_dom"] = (upper_wick / body_safe).fillna(0)

        bullish_body = df["close"] > df["open"]
        bearish_body = df["close"] < df["open"]

        df["bull_reversal"] = bullish_body | (df["wick_lower_dom"] >= wick_ratio)
        df["bear_reversal"] = bearish_body | (df["wick_upper_dom"] >= wick_ratio)

        # Band touch (low touches lower band / high touches upper band)
        df["touch_lower"] = df["low"] <= df["bb_lower"]
        df["touch_upper"] = df["high"] >= df["bb_upper"]

        # Range regime
        df["range_regime"] = df["adx"] < adx_thr

        # RSI extremes
        df["rsi_oversold"] = df["rsi"] < rsi_os
        df["rsi_overbought"] = df["rsi"] > rsi_ob

        # Composite long/short condition AT t-1 (use shift so decision uses prior bar)
        # Lookahead-safe: signal fires at bar t, all conditions use t-1
        df["long_setup_prev"] = (
            df["touch_lower"].shift(1).fillna(False).astype(bool)
            & df["rsi_oversold"].shift(1).fillna(False).astype(bool)
            & df["range_regime"].shift(1).fillna(False).astype(bool)
            & df["bull_reversal"].shift(1).fillna(False).astype(bool)
        )
        df["short_setup_prev"] = (
            df["touch_upper"].shift(1).fillna(False).astype(bool)
            & df["rsi_overbought"].shift(1).fillna(False).astype(bool)
            & df["range_regime"].shift(1).fillna(False).astype(bool)
            & df["bear_reversal"].shift(1).fillna(False).astype(bool)
        )

        # Structural SL levels (uses shift(1) inside)
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
                struct = float(row.get("struct_sl_long") or 0.0)
                sl_struct = struct if struct > 0 and not np.isnan(struct) else (open_ - atr_mult * atr)
                sl_atr = open_ - atr_mult * atr
                sl_price = min(sl_struct, sl_atr)  # tighter of the two
                sl_price = min(sl_price, open_ - 0.5 * atr)  # safety: at least 0.5 ATR risk
                risk = open_ - sl_price
                if risk <= 0:
                    continue
                tp_price = open_ + primary_R * risk
                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts, venue=venue, symbol=symbol, timeframe=timeframe,
                    direction="long", pattern_id="bb_fade_long",
                    confluence_score=2.0,
                    sl_price=float(sl_price), tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "bb_lower_prev": float(df["bb_lower"].iat[i - 1]),
                        "rsi_prev": float(df["rsi"].iat[i - 1]),
                        "adx_prev": float(df["adx"].iat[i - 1]),
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
                    direction="short", pattern_id="bb_fade_short",
                    confluence_score=2.0,
                    sl_price=float(sl_price), tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "bb_upper_prev": float(df["bb_upper"].iat[i - 1]),
                        "rsi_prev": float(df["rsi"].iat[i - 1]),
                        "adx_prev": float(df["adx"].iat[i - 1]),
                        "atr14": atr,
                        "risk_r": float(risk),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("bollinger_fade_mr.signals.generated")
        return out
