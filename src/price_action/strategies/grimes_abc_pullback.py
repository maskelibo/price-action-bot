"""Adam Grimes Two-Legged ABC Pullback — Trend Continuation strategy.

Konsept (Adam Grimes, "The Art and Science of Technical Analysis" 2012, Ch 7
"Trading Pullbacks"): "Two-legged pullbacks are the most common high-quality
trend-continuation setup. The second leg shakes out weak hands and provides
the better entry."

Pre-registered hipotez: HYP-2026-05-14-GRIMES-ABC-TWO-LEG (SEC25 backlog).
TEK pre-reg parametre seti — sweep YOK. Eşikler doğrudan pre-reg dokümanından.

Bullish ABC (LONG):
  1. Trend filtre: close[t] > EMA50[t] AND EMA50[t] > EMA50[t-10] (yukarı eğim).
  2. A-pivot: son 30 bar içinde fractal swing high (n=2) — trend son tepesi.
  3. A-leg pullback: A-pivot sonrası ilk swing low (a-low pivot).
  4. B-pivot (mini-rally): a-low sonrası swing high; B < A (lower-high).
  5. C-leg (deeper retrace): B sonrası swing low c-low; c-low > a-low VE
     c-low <= (B + a-low)/2 (B'ye göre daha derin ikinci bacak test).
  6. Reclaim trigger (bar t): c-low pivot bar sonrası fiyat B-pivot price'ı
     reclaim. close[t] >= B-price, bar t bullish (close > open), body_ratio >= 0.40.
  7. Entry: bar t+1 açılış LONG (decision_after_close=True).

  SL: c-low - 0.5 * ATR14[t].
  TP: A-pivot price (trend A'yı yeniden test eder), floor 2.0R.

Bearish ABC (SHORT, ayna): EMA50 düşüş eğimli, A swing low, a-high → B-pivot
(higher-low, B > A), C-leg higher → c-high, B reclaim downside trigger.

Lookahead-free audit:
  - Fractal n=2 swing detection t+2 forward bar gerektirir; sadece t-fractal_n
    veya daha eski (confirmed) swing'ler sorgulanır (k + fractal_n <= t).
  - Trigger bar t close'undan karar, entry t+1 open (decision_after_close=True).
  - df.shift(-1) decision path'inde YOK; tek shift(-n) fractal teyidi içindir
    ve sadece confirmed (geçmiş) swing'lere bakılır.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema


# Engineering SEC21 taxonomy hook
STRATEGY_CLASS = "trend_continuation"


def _fractal_low(low: pd.Series, n: int = 2) -> pd.Series:
    """N-bar fractal swing low; True at bar i if low[i] is strict min of
    [i-n..i+n]. Lookahead-free when only queried at bar i <= t-n (confirmed)."""
    left_min = low.shift(1).rolling(n, min_periods=n).min()
    right_min = low.shift(-n).rolling(n, min_periods=n).min()
    return ((low < left_min) & (low < right_min)).fillna(False)


def _fractal_high(high: pd.Series, n: int = 2) -> pd.Series:
    left_max = high.shift(1).rolling(n, min_periods=n).max()
    right_max = high.shift(-n).rolling(n, min_periods=n).max()
    return ((high > left_max) & (high > right_max)).fillna(False)


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "grimes_abc_pullback",
        "version": "1.0.0",
        "description": (
            "Adam Grimes two-legged ABC pullback — A swing pivot, B mini-rally "
            "lower-high, C deeper retrace, B-reclaim trigger. Trend-cont class."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "grimes_abc_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "a_lookback": 30,        # A-pivot son 30 bar içinde
                        "ema_slope_lag": 10,     # EMA50[t] > EMA50[t-10]
                        "fractal_n": 2,
                        "body_ratio_min": 0.40,  # reclaim bar body
                        "sl_atr_mult": 0.5,      # SL = c_low - 0.5*ATR
                        "tp_r_floor": 2.0,       # min TP = 2R
                        "atr_min_pct": 0.005,
                        "cooldown_bars": 10,
                    },
                },
                {
                    "id": "grimes_abc_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "a_lookback": 30,
                        "ema_slope_lag": 10,
                        "fractal_n": 2,
                        "body_ratio_min": 0.40,
                        "sl_atr_mult": 0.5,
                        "tp_r_floor": 2.0,
                        "atr_min_pct": 0.005,
                        "cooldown_bars": 10,
                    },
                },
            ],
            "filters": {
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "take_profit": {"primary_R": 2.0},
        },
    }
    return StrategyManifest.model_validate(raw)


class GrimesABCPullbackStrategy(Strategy):
    """Adam Grimes two-legged ABC pullback (trend continuation)."""

    name = "grimes_abc_pullback"

    def _get_param(self, pattern_id: str, key: str, default: Any) -> Any:
        for p in self.manifest.signals.patterns:
            if p.id == pattern_id:
                return p.params.get(key, default)
        return default

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        fractal_n = int(self._get_param("grimes_abc_long", "fractal_n", 2))

        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]
        df["ema50"] = _ema(df["close"], 50)

        df["bar_range"] = (df["high"] - df["low"]).clip(lower=1e-9)
        df["body"] = (df["close"] - df["open"]).abs()
        df["body_ratio"] = df["body"] / df["bar_range"]

        df["is_swing_low"] = _fractal_low(df["low"], n=fractal_n)
        df["is_swing_high"] = _fractal_high(df["high"], n=fractal_n)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "atr14" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        a_lookback = int(self._get_param("grimes_abc_long", "a_lookback", 30))
        ema_lag = int(self._get_param("grimes_abc_long", "ema_slope_lag", 10))
        fractal_n = int(self._get_param("grimes_abc_long", "fractal_n", 2))
        body_min = float(self._get_param("grimes_abc_long", "body_ratio_min", 0.40))
        sl_mult = float(self._get_param("grimes_abc_long", "sl_atr_mult", 0.5))
        tp_r_floor = float(self._get_param("grimes_abc_long", "tp_r_floor", 2.0))
        cooldown = int(self._get_param("grimes_abc_long", "cooldown_bars", 10))
        atr_min_pct = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)

        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "grimes_abc_long"), 2.0)
        short_w = next((p.weight for p in signals_cfg.patterns if p.id == "grimes_abc_short"), 2.0)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        opens = df["open"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        atrs = df["atr14"].to_numpy(dtype=float)
        atr_pct = df["atr_pct"].to_numpy(dtype=float)
        ema50 = df["ema50"].to_numpy(dtype=float)
        body_r = df["body_ratio"].to_numpy(dtype=float)
        sw_low = df["is_swing_low"].to_numpy(dtype=bool)
        sw_high = df["is_swing_high"].to_numpy(dtype=bool)
        ts_arr = df["ts"].to_numpy()
        n_bars = len(df)

        out: list[Signal] = []
        last_long_ts = -99
        last_short_ts = -99

        # EMA50 + slope lag + A-lookback + fractal forward bar.
        start_idx = max(a_lookback + fractal_n + 5, 55 + ema_lag)

        for t in range(start_idx, n_bars):
            atr_t = atrs[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and not np.isnan(atr_pct[t]) and atr_pct[t] < atr_min_pct:
                continue
            if np.isnan(ema50[t]) or np.isnan(ema50[t - ema_lag]):
                continue

            c_t, o_t = closes[t], opens[t]
            # confirmed-swing horizon: only pivots at k where k + fractal_n <= t
            t_conf = t - fractal_n

            # ================================================================
            # LONG: Grimes bullish ABC two-leg pullback
            #   A (swing high) -> a-low (swing low) -> B (swing high, B<A) ->
            #   c-low (swing low, deeper) -> reclaim B trigger at t
            # ================================================================
            if (t > last_long_ts + cooldown and c_t > ema50[t]
                    and ema50[t] > ema50[t - ema_lag]):
                # c-low: most recent confirmed swing low (the C-leg bottom)
                c_idx = -1
                for k in range(t_conf, max(0, t - 12) - 1, -1):
                    if sw_low[k]:
                        c_idx = k
                        break
                if c_idx >= 0:
                    # B-pivot: swing high above c-low (the mini-rally top)
                    b_idx = -1
                    for k in range(c_idx - 1, max(0, c_idx - 12) - 1, -1):
                        if sw_high[k]:
                            b_idx = k
                            break
                    if b_idx >= 0:
                        # a-low: swing low below B (the first-leg bottom)
                        a_low_idx = -1
                        for k in range(b_idx - 1, max(0, b_idx - 12) - 1, -1):
                            if sw_low[k]:
                                a_low_idx = k
                                break
                        if a_low_idx >= 0:
                            # A-pivot: swing high above a-low within a_lookback
                            a_idx = -1
                            for k in range(a_low_idx - 1, max(0, t - a_lookback) - 1, -1):
                                if sw_high[k]:
                                    a_idx = k
                                    break
                            if a_idx >= 0:
                                A = highs[a_idx]
                                a_low = lows[a_low_idx]
                                B = highs[b_idx]
                                c_low = lows[c_idx]
                                # Structural gates (pre-reg):
                                #  B < A (lower-high mini-rally)
                                #  c_low > a_low (higher-low, second leg holds)
                                #  c_low <= (B + a_low)/2 (deeper test vs B)
                                struct = (
                                    B < A and c_low > a_low
                                    and c_low <= 0.5 * (B + a_low)
                                )
                                # Reclaim trigger at t: close >= B, bullish bar
                                reclaim = (
                                    c_t >= B and c_t > o_t
                                    and body_r[t] >= body_min
                                )
                                if struct and reclaim:
                                    sl_price = c_low - sl_mult * atr_t
                                    entry_ref = c_t
                                    risk = entry_ref - sl_price
                                    if risk > 0:
                                        floor_tp = entry_ref + tp_r_floor * risk
                                        tp_price = max(A, floor_tp)
                                        score = long_w
                                        if score >= min_score:
                                            sig = self.emit_signal(
                                                ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                                                venue=venue, symbol=symbol, timeframe=timeframe,
                                                direction="long",
                                                pattern_id="grimes_abc_long",
                                                confluence_score=float(score),
                                                sl_price=float(sl_price),
                                                tp_price=float(tp_price),
                                                suggested_size_atr=1.0,
                                                metadata={
                                                    "A": float(A), "a_low": float(a_low),
                                                    "B": float(B), "c_low": float(c_low),
                                                    "A_idx_back": int(t - a_idx),
                                                    "c_idx_back": int(t - c_idx),
                                                    "retrace_depth": float(
                                                        (B - c_low) / (B - a_low)
                                                    ) if B > a_low else None,
                                                    "body_ratio": float(body_r[t]),
                                                },
                                            )
                                            out.append(sig)
                                            last_long_ts = t

            # ================================================================
            # SHORT: Grimes bearish ABC (mirror)
            #   A (swing low) -> a-high (swing high) -> B (swing low, B>A) ->
            #   c-high (swing high, deeper) -> reclaim B downside trigger at t
            # ================================================================
            if (t > last_short_ts + cooldown and c_t < ema50[t]
                    and ema50[t] < ema50[t - ema_lag]):
                c_idx = -1
                for k in range(t_conf, max(0, t - 12) - 1, -1):
                    if sw_high[k]:
                        c_idx = k
                        break
                if c_idx >= 0:
                    b_idx = -1
                    for k in range(c_idx - 1, max(0, c_idx - 12) - 1, -1):
                        if sw_low[k]:
                            b_idx = k
                            break
                    if b_idx >= 0:
                        a_high_idx = -1
                        for k in range(b_idx - 1, max(0, b_idx - 12) - 1, -1):
                            if sw_high[k]:
                                a_high_idx = k
                                break
                        if a_high_idx >= 0:
                            a_idx = -1
                            for k in range(a_high_idx - 1, max(0, t - a_lookback) - 1, -1):
                                if sw_low[k]:
                                    a_idx = k
                                    break
                            if a_idx >= 0:
                                A = lows[a_idx]
                                a_high = highs[a_high_idx]
                                B = lows[b_idx]
                                c_high = highs[c_idx]
                                struct = (
                                    B > A and c_high < a_high
                                    and c_high >= 0.5 * (B + a_high)
                                )
                                reclaim = (
                                    c_t <= B and c_t < o_t
                                    and body_r[t] >= body_min
                                )
                                if struct and reclaim:
                                    sl_price = c_high + sl_mult * atr_t
                                    entry_ref = c_t
                                    risk = sl_price - entry_ref
                                    if risk > 0:
                                        floor_tp = entry_ref - tp_r_floor * risk
                                        tp_price = min(A, floor_tp)
                                        score = short_w
                                        if score >= min_score:
                                            sig = self.emit_signal(
                                                ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                                                venue=venue, symbol=symbol, timeframe=timeframe,
                                                direction="short",
                                                pattern_id="grimes_abc_short",
                                                confluence_score=float(score),
                                                sl_price=float(sl_price),
                                                tp_price=float(tp_price),
                                                suggested_size_atr=1.0,
                                                metadata={
                                                    "A": float(A), "a_high": float(a_high),
                                                    "B": float(B), "c_high": float(c_high),
                                                    "A_idx_back": int(t - a_idx),
                                                    "c_idx_back": int(t - c_idx),
                                                    "retrace_depth": float(
                                                        (c_high - B) / (a_high - B)
                                                    ) if a_high > B else None,
                                                    "body_ratio": float(body_r[t]),
                                                },
                                            )
                                            out.append(sig)
                                            last_short_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("grimes_abc_pullback.signals.generated")
        return out
