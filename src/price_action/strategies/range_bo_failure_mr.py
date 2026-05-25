"""Range Breakout Failure (Turtle Soup / Brooks FBO) MR strategy (15m R4 MR pool).

Sprint: SEC-S5 MR pool diversification (HYP-2026-05-17-range-bo-failure-15m).

Rule summary:
  - BB(20, 2.0) squeeze active at t-4 (BB_width <= percentile_25, lookback=200)
  - Bar(t-3) close OUTSIDE outer BB (failed breakout)
  - 1-3 bar reclaim window: close back inside BB by t-1
  - Bar(t-1) reversal candle in fade direction
  - Entry: bar(t) open
  - SL: structural 1.5x ATR
  - TP: 1.2R

Pre-registration: memory/researcher/hypotheses/2026-05-17-range-bo-failure-15m.md
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr


def _bollinger_bands(close: pd.Series, period: int = 20, n_std: float = 2.0):
    mid = close.rolling(period, min_periods=period).mean()
    sd = close.rolling(period, min_periods=period).std(ddof=1)
    upper = mid + n_std * sd
    lower = mid - n_std * sd
    return upper, mid, lower


def _bb_width_pctile_rank(bb_width: pd.Series, lookback: int = 200) -> pd.Series:
    """Rolling percentile rank (0..1) of BB_width. Lookahead-safe.

    rank=0.25 -> current is at 25th percentile (small width = squeeze candidate)
    """
    return bb_width.rolling(lookback, min_periods=max(20, lookback // 5)).apply(
        lambda x: (x < x[-1]).sum() / max(1, len(x) - 1), raw=True
    )


def _swing_sl(df: pd.DataFrame, direction: str, lookback: int = 10) -> pd.Series:
    if direction == "long":
        return df["low"].shift(1).rolling(lookback, min_periods=1).min()
    return df["high"].shift(1).rolling(lookback, min_periods=1).max()


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "range_bo_failure_mr",
        "version": "1.0.0",
        "description": (
            "Bollinger Squeeze + failed breakout + 1-3 bar reclaim + reversal. "
            "Turtle Soup / Brooks FBO (15m R4 MR pool, SEC-S5)."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "range_bof_long",
                    "enabled": True,
                    "weight": 2.5,
                    "params": {
                        "bb_period": 20,
                        "bb_std": 2.0,
                        "bb_width_pctile_lookback": 200,
                        "squeeze_pctile_thr": 0.25,
                        "reclaim_window": 3,
                    },
                },
                {
                    "id": "range_bof_short",
                    "enabled": True,
                    "weight": 2.5,
                    "params": {
                        "bb_period": 20,
                        "bb_std": 2.0,
                        "bb_width_pctile_lookback": 200,
                        "squeeze_pctile_thr": 0.25,
                        "reclaim_window": 3,
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


class RangeBOFailureMRStrategy(Strategy):
    """Bollinger squeeze + failed BO + reclaim + reversal fade.

    Long sequence (all checks lookahead-safe; entry at bar t open):
      - Squeeze active at t-4
      - close(t-3) < bb_lower(t-3)   -- failed down-BO
      - any close in (t-2 .. t-1) >= bb_lower (reclaim within 1-3 bars)
      - bar(t-1) bullish reversal (close>open AND close>prev_close)
    """

    name = "range_bo_failure_mr"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        long_params: dict[str, Any] = {}
        short_params: dict[str, Any] = {}
        for p in self.manifest.signals.patterns:
            if p.id == "range_bof_long":
                long_params = dict(p.params)
            elif p.id == "range_bof_short":
                short_params = dict(p.params)

        bb_period = int(long_params.get("bb_period", 20))
        bb_std = float(long_params.get("bb_std", 2.0))
        sq_lookback = int(long_params.get("bb_width_pctile_lookback", 200))
        sq_thr = float(long_params.get("squeeze_pctile_thr", 0.25))
        reclaim_window = int(long_params.get("reclaim_window", 3))

        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)

        upper, mid, lower = _bollinger_bands(df["close"], period=bb_period, n_std=bb_std)
        df["bb_upper"] = upper
        df["bb_mid"] = mid
        df["bb_lower"] = lower
        df["bb_width"] = upper - lower

        df["bb_width_pctile"] = _bb_width_pctile_rank(df["bb_width"], lookback=sq_lookback)
        df["squeeze_active"] = df["bb_width_pctile"] <= sq_thr

        # Failed BO flags at each bar
        df["bo_down"] = df["close"] < df["bb_lower"]
        df["bo_up"] = df["close"] > df["bb_upper"]
        df["inside_bb"] = (df["close"] >= df["bb_lower"]) & (df["close"] <= df["bb_upper"])

        # Reversal candles at bar t (will be shifted to t-1 for signal check)
        bullish = df["close"] > df["open"]
        bearish = df["close"] < df["open"]
        prev_close = df["close"].shift(1)
        df["bull_reversal"] = bullish & (df["close"] > prev_close)
        df["bear_reversal"] = bearish & (df["close"] < prev_close)

        # Composite setup at bar t-1 (entry t):
        # Need to look at squeeze at t-1-3 (= shift(4)), bo at t-1-2 (= shift(3))
        # reclaim in (t-1-1 .. t-1) = shift(2) or shift(1)
        # reversal at t-1 (= shift(1))
        # Implementation: per-bar masks built with shift, no for-loop
        sq_4back = df["squeeze_active"].shift(4).fillna(False).astype(bool)
        bo_down_3back = df["bo_down"].shift(3).fillna(False).astype(bool)
        bo_up_3back = df["bo_up"].shift(3).fillna(False).astype(bool)

        # Reclaim window = 1..reclaim_window bars after BO (i.e. shift(3-k) for k in 1..reclaim_window)
        # For reclaim_window=3 -> check shift(2), shift(1), shift(0)... but shift(0) is bar t (current),
        # we should ONLY use bars up to t-1. So shifts 2, 1.
        # Wait: BO at t-3. Reclaim window in {t-2, t-1}. We want at least one of those inside BB.
        # That's shift(2) and shift(1) when "bar t-1 is shift(1)".
        # If reclaim_window=3, we'd want t-2, t-1, t (bar t is forming) - exclude bar t for safety.
        # So practical window = min(reclaim_window, 2) bars before bar t.

        max_shift_back = min(reclaim_window, 2)
        reclaim_long_acc = pd.Series(False, index=df.index)
        reclaim_short_acc = pd.Series(False, index=df.index)
        for k in range(1, max_shift_back + 1):
            reclaim_long_acc = reclaim_long_acc | (df["close"] >= df["bb_lower"]).shift(k).fillna(False).astype(bool)
            reclaim_short_acc = reclaim_short_acc | (df["close"] <= df["bb_upper"]).shift(k).fillna(False).astype(bool)

        # Reversal candle at t-1
        rev_long_prev = df["bull_reversal"].shift(1).fillna(False).astype(bool)
        rev_short_prev = df["bear_reversal"].shift(1).fillna(False).astype(bool)

        df["long_setup_prev"] = sq_4back & bo_down_3back & reclaim_long_acc & rev_long_prev
        df["short_setup_prev"] = sq_4back & bo_up_3back & reclaim_short_acc & rev_short_prev

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
                    direction="long", pattern_id="range_bof_long",
                    confluence_score=2.5,
                    sl_price=float(sl_price), tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "bb_lower_prev": float(df["bb_lower"].iat[i - 1]),
                        "bb_width_pctile_prev": float(df["bb_width_pctile"].iat[i - 1] or 0),
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
                    direction="short", pattern_id="range_bof_short",
                    confluence_score=2.5,
                    sl_price=float(sl_price), tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "bb_upper_prev": float(df["bb_upper"].iat[i - 1]),
                        "bb_width_pctile_prev": float(df["bb_width_pctile"].iat[i - 1] or 0),
                        "atr14": atr,
                        "risk_r": float(risk),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("range_bo_failure_mr.signals.generated")
        return out
