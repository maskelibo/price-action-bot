"""RSI Extreme Mean-Reversion strategy (15m R4 MR pool).

Sprint: SEC-S5 MR pool diversification (HYP-2026-05-17-rsi-extreme-mr-15m).

Rule summary:
  - RSI(14) extreme at t-1 (<25 long / >75 short)
  - ATR%-percentile<=30 (last 200 bars) - range regime detector
  - Reversal candle at t-1:
      long: hammer (lower_wick >= 1.5*body AND upper_wick <= 0.5*body AND bullish)
      short: shooting-star (upper_wick >= 1.5*body AND lower_wick <= 0.5*body AND bearish)
  - Bar(t-1) recovery: close > prev_low (long) / close < prev_high (short)
  - Entry: bar(t) open
  - SL: structural 1.5x ATR
  - TP: 1.2R

Pre-registration: memory/researcher/hypotheses/2026-05-17-rsi-extreme-mr-15m.md
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI. Lookahead-free."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)


def _atr_pct_percentile_rank(atr_pct: pd.Series, lookback: int = 200) -> pd.Series:
    """Rolling percentile rank (0..1) of atr_pct over last `lookback` bars.

    Lookahead-safe: rolling uses [t-lookback+1 .. t] inclusive.
    rank=0.30 means current atr_pct is at the 30th percentile of the window.
    """
    return atr_pct.rolling(lookback, min_periods=max(20, lookback // 5)).apply(
        lambda x: (x < x[-1]).sum() / max(1, len(x) - 1), raw=True
    )


def _swing_sl(df: pd.DataFrame, direction: str, lookback: int = 10) -> pd.Series:
    if direction == "long":
        return df["low"].shift(1).rolling(lookback, min_periods=1).min()
    return df["high"].shift(1).rolling(lookback, min_periods=1).max()


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "rsi_extreme_mr",
        "version": "1.0.0",
        "description": (
            "RSI(14) extreme (<25 / >75) + ATR%-percentile range regime + "
            "hammer/shooting-star reversal. Mean-reversion fade (15m R4 MR pool, SEC-S5)."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "rsi_ext_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "rsi_period": 14,
                        "rsi_oversold": 25.0,
                        "atr_pct_pctile_lookback": 200,
                        "atr_pct_pctile_thr": 0.30,
                        "wick_dom_ratio": 1.5,
                        "wick_opposite_max": 0.5,
                    },
                },
                {
                    "id": "rsi_ext_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "rsi_period": 14,
                        "rsi_overbought": 75.0,
                        "atr_pct_pctile_lookback": 200,
                        "atr_pct_pctile_thr": 0.30,
                        "wick_dom_ratio": 1.5,
                        "wick_opposite_max": 0.5,
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


class RSIExtremeMRStrategy(Strategy):
    """RSI extreme + range regime + hammer/shooting-star reversal fade.

    Lookahead-safe: all setup conditions use bar(t-1), entry at bar(t) open.
    """

    name = "rsi_extreme_mr"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        long_params: dict[str, Any] = {}
        short_params: dict[str, Any] = {}
        for p in self.manifest.signals.patterns:
            if p.id == "rsi_ext_long":
                long_params = dict(p.params)
            elif p.id == "rsi_ext_short":
                short_params = dict(p.params)

        rsi_period = int(long_params.get("rsi_period", 14))
        rsi_os = float(long_params.get("rsi_oversold", 25.0))
        rsi_ob = float(short_params.get("rsi_overbought", 75.0))
        atr_pctile_lb = int(long_params.get("atr_pct_pctile_lookback", 200))
        atr_pctile_thr = float(long_params.get("atr_pct_pctile_thr", 0.30))
        wick_dom = float(long_params.get("wick_dom_ratio", 1.5))
        wick_opp_max = float(long_params.get("wick_opposite_max", 0.5))

        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)
        df["rsi"] = _rsi(df["close"], period=rsi_period)

        # ATR% percentile rank (rolling lookback=200)
        df["atr_pct_pctile"] = _atr_pct_percentile_rank(df["atr_pct"], lookback=atr_pctile_lb)
        df["range_regime"] = df["atr_pct_pctile"] <= atr_pctile_thr

        # Candle anatomy
        body = (df["close"] - df["open"]).abs()
        lower_wick = (df[["open", "close"]].min(axis=1) - df["low"]).clip(lower=0)
        upper_wick = (df["high"] - df[["open", "close"]].max(axis=1)).clip(lower=0)
        body_safe = body.replace(0, np.nan)
        wlo = (lower_wick / body_safe).fillna(0)
        wup = (upper_wick / body_safe).fillna(0)

        bullish = df["close"] > df["open"]
        bearish = df["close"] < df["open"]

        df["hammer"] = (wlo >= wick_dom) & (wup <= wick_opp_max) & bullish
        df["shooting_star"] = (wup >= wick_dom) & (wlo <= wick_opp_max) & bearish

        # Recovery: close > prev_low (long) / close < prev_high (short)
        df["recover_long"] = df["close"] > df["low"].shift(1)
        df["recover_short"] = df["close"] < df["high"].shift(1)

        # Composite setup at t-1
        df["long_setup_prev"] = (
            (df["rsi"] < rsi_os).shift(1).fillna(False).astype(bool)
            & df["range_regime"].shift(1).fillna(False).astype(bool)
            & df["hammer"].shift(1).fillna(False).astype(bool)
            & df["recover_long"].shift(1).fillna(False).astype(bool)
        )
        df["short_setup_prev"] = (
            (df["rsi"] > rsi_ob).shift(1).fillna(False).astype(bool)
            & df["range_regime"].shift(1).fillna(False).astype(bool)
            & df["shooting_star"].shift(1).fillna(False).astype(bool)
            & df["recover_short"].shift(1).fillna(False).astype(bool)
        )

        df["struct_sl_long"] = _swing_sl(df, "long", lookback=10)
        df["struct_sl_short"] = _swing_sl(df, "short", lookback=10)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "rsi" not in df.columns:
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

        for i in range(1, n):
            row = df.iloc[i]
            atr = float(row.get("atr14") or 0.0)
            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr <= 0 or np.isnan(atr) or atr_pct < atr_min:
                continue
            open_ = float(row["open"])
            if open_ <= 0:
                continue

            if bool(row.get("long_setup_prev", False)):
                struct = float(row.get("struct_sl_long") or 0.0)
                sl_struct = struct if struct > 0 and not np.isnan(struct) else (open_ - atr_mult * atr)
                sl_atr = open_ - atr_mult * atr
                sl_price = min(sl_struct, sl_atr)
                sl_price = min(sl_price, open_ - 0.5 * atr)
                risk = open_ - sl_price
                if risk <= 0:
                    continue
                tp_price = open_ + primary_R * risk
                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts, venue=venue, symbol=symbol, timeframe=timeframe,
                    direction="long", pattern_id="rsi_ext_long",
                    confluence_score=2.0,
                    sl_price=float(sl_price), tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "rsi_prev": float(df["rsi"].iat[i - 1]),
                        "atr_pct_pctile_prev": float(df["atr_pct_pctile"].iat[i - 1] or 0),
                        "atr14": atr,
                        "risk_r": float(risk),
                    },
                )
                out.append(sig)

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
                    direction="short", pattern_id="rsi_ext_short",
                    confluence_score=2.0,
                    sl_price=float(sl_price), tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "rsi_prev": float(df["rsi"].iat[i - 1]),
                        "atr_pct_pctile_prev": float(df["atr_pct_pctile"].iat[i - 1] or 0),
                        "atr14": atr,
                        "risk_r": float(risk),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("rsi_extreme_mr.signals.generated")
        return out
