"""Brooks Double Bottom Bull Flag / Double Top Bear Flag — Trend Continuation strategy.

Konsept (Al Brooks "10 Best Price Action Patterns", Trading Price Action Trends 2012):
  - Double Bottom Bull Flag: trend yonunde 2 swing low (price ~equal, within 3%),
    intermediate B-pivot (mini rally), tight flag consolidation flag breakout above
    M-neckline. Brooks "measured move" target = (M - L_avg) bonus on entry.
  - Double Top Bear Flag: mirror in downtrend.

Bullish DB Bull Flag (LONG):
  - close[t] > EMA50[t]                           (uptrend bias)
  - Swing low L1 at t-K, K in [10, 40] (fractal n=2)
  - Swing low L2 at t-J, J in [3, 12], K > J
  - |L1 - L2| / L1 < 0.03                         (3% equal-price gate, "double bottom")
  - Intermediate pivot M = max(close[t-K..t-J])   (neckline)
  - Tight flag: last C bars (C in [3, 8]):
        (max(high[t-C+1..t]) - min(low[t-C+1..t])) / atr14[t] < 4.0
        AND min(close[t-C+1..t]) >= M                       (closes above neckline)
        AND max(high[t-C+1..t-1]) <= M + 1.5*atr14[t]       (flag NOT broken yet)
  - Breakout trigger bar t:
        close[t] > max(high[t-C..t-1])            (breaks flag high)
        close[t] > open[t]                        (bullish)
        body_ratio[t] >= 0.40
  - Cooldown 10 bar same side

Bearish DT Bear Flag (SHORT, mirror).

Targets:
  - SL: LONG: L2 - 0.5*ATR14[t]; SHORT: H2 + 0.5*ATR14[t]
  - TP: Brooks measured move = entry + (M - L_avg) for LONG, entry - (H_avg - M)
    for SHORT. Floor 2.0R.

Lookahead-free audit:
  - Fractal n=2 swing detection requires t+2 forward bars → uses shift to align,
    only L1/L2 with confirmed swing-status at t (i.e., swing detected at t-2 or
    earlier).
  - All rolling lookbacks shift(1) appropriate. Entry at t+1 open
    (decision_after_close=True).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema


# Engineering SEC21 taxonomy hook
STRATEGY_CLASS = "trend_continuation"


def _fractal_low(low: pd.Series, n: int = 2) -> pd.Series:
    """N-bar fractal swing low; True at bar i if low[i] is strict min of
    [i-n..i+n] window. Lookahead-free because we only query swing status at
    bar t-n or earlier (confirmed swing).
    """
    left_min = low.shift(1).rolling(n, min_periods=n).min()
    right_min = low.shift(-n).rolling(n, min_periods=n).min()
    return ((low < left_min) & (low < right_min)).fillna(False)


def _fractal_high(high: pd.Series, n: int = 2) -> pd.Series:
    left_max = high.shift(1).rolling(n, min_periods=n).max()
    right_max = high.shift(-n).rolling(n, min_periods=n).max()
    return ((high > left_max) & (high > right_max)).fillna(False)


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "brooks_db_bull_flag",
        "version": "1.0.0",
        "description": (
            "Brooks Double Bottom Bull Flag / Double Top Bear Flag — two-pivot "
            "reversal-into-continuation with tight flag breakout. Trend-cont class."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "db_bull_flag_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "k_min": 10,                # swing #1 lookback min
                        "k_max": 40,                # swing #1 lookback max
                        "j_min": 3,                 # swing #2 lookback min
                        "j_max": 12,                # swing #2 lookback max
                        "equal_pct": 0.03,          # |L1-L2|/L1 < 3%
                        "flag_bars": 5,             # tight flag consolidation bars
                        "flag_rng_atr": 4.0,        # flag range / atr14 < 4.0
                        "body_ratio_min": 0.40,     # breakout bar body
                        "sl_atr_mult": 0.5,         # SL = L2 - 0.5*ATR
                        "tp_r_floor": 2.0,          # min TP = 2R
                        "fractal_n": 2,
                        "atr_min_pct": 0.005,
                        "cooldown_bars": 10,
                    },
                },
                {
                    "id": "dt_bear_flag_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "k_min": 10,
                        "k_max": 40,
                        "j_min": 3,
                        "j_max": 12,
                        "equal_pct": 0.03,
                        "flag_bars": 5,
                        "flag_rng_atr": 4.0,
                        "body_ratio_min": 0.40,
                        "sl_atr_mult": 0.5,
                        "tp_r_floor": 2.0,
                        "fractal_n": 2,
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


class BrooksDBBullFlagStrategy(Strategy):
    """Brooks Double Bottom Bull Flag / Double Top Bear Flag (trend continuation)."""

    name = "brooks_db_bull_flag"

    def _get_param(self, pattern_id: str, key: str, default: Any) -> Any:
        for p in self.manifest.signals.patterns:
            if p.id == pattern_id:
                return p.params.get(key, default)
        return default

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        fractal_n = int(self._get_param("db_bull_flag_long", "fractal_n", 2))
        flag_bars = int(self._get_param("db_bull_flag_long", "flag_bars", 5))

        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]
        df["ema50"] = _ema(df["close"], 50)

        # Bar geometry
        df["bar_range"] = (df["high"] - df["low"]).clip(lower=1e-9)
        df["body"] = (df["close"] - df["open"]).abs()
        df["body_ratio"] = df["body"] / df["bar_range"]

        # Fractal pivots (n=2 default)
        df["is_swing_low"] = _fractal_low(df["low"], n=fractal_n)
        df["is_swing_high"] = _fractal_high(df["high"], n=fractal_n)

        # Flag-bars rolling stats (high/low) for tight-range gate
        # NOTE: these include bar t (so when checked at bar t they are not lookahead;
        # we only use them when t = trigger bar)
        df[f"flag_hh{flag_bars}"] = df["high"].rolling(flag_bars, min_periods=flag_bars).max()
        df[f"flag_ll{flag_bars}"] = df["low"].rolling(flag_bars, min_periods=flag_bars).min()
        df[f"flag_close_min{flag_bars}"] = df["close"].rolling(flag_bars, min_periods=flag_bars).min()
        # Flag high BEFORE current bar (for breakout comparison)
        df[f"flag_hh{flag_bars}_prior"] = (
            df["high"].rolling(flag_bars, min_periods=flag_bars).max().shift(1)
        )
        df[f"flag_ll{flag_bars}_prior"] = (
            df["low"].rolling(flag_bars, min_periods=flag_bars).min().shift(1)
        )

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "atr14" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        # Long params
        k_min = int(self._get_param("db_bull_flag_long", "k_min", 10))
        k_max = int(self._get_param("db_bull_flag_long", "k_max", 40))
        j_min = int(self._get_param("db_bull_flag_long", "j_min", 3))
        j_max = int(self._get_param("db_bull_flag_long", "j_max", 12))
        equal_pct = float(self._get_param("db_bull_flag_long", "equal_pct", 0.03))
        flag_bars = int(self._get_param("db_bull_flag_long", "flag_bars", 5))
        flag_rng_atr = float(self._get_param("db_bull_flag_long", "flag_rng_atr", 4.0))
        body_min = float(self._get_param("db_bull_flag_long", "body_ratio_min", 0.40))
        sl_mult = float(self._get_param("db_bull_flag_long", "sl_atr_mult", 0.5))
        tp_r_floor = float(self._get_param("db_bull_flag_long", "tp_r_floor", 2.0))
        fractal_n = int(self._get_param("db_bull_flag_long", "fractal_n", 2))
        cooldown = int(self._get_param("db_bull_flag_long", "cooldown_bars", 10))
        atr_min_pct = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)

        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "db_bull_flag_long"), 2.0)
        short_w = next((p.weight for p in signals_cfg.patterns if p.id == "dt_bear_flag_short"), 2.0)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # Cache arrays
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
        flag_hh_prior = df[f"flag_hh{flag_bars}_prior"].to_numpy(dtype=float)
        flag_ll_prior = df[f"flag_ll{flag_bars}_prior"].to_numpy(dtype=float)
        flag_hh = df[f"flag_hh{flag_bars}"].to_numpy(dtype=float)
        flag_ll = df[f"flag_ll{flag_bars}"].to_numpy(dtype=float)
        flag_close_min = df[f"flag_close_min{flag_bars}"].to_numpy(dtype=float)
        ts_arr = df["ts"].to_numpy()
        n_bars = len(df)

        out: list[Signal] = []
        last_long_ts = -99
        last_short_ts = -99

        # Need EMA50 + fractal_n forward bars + k_max history. Start at k_max + 5.
        start_idx = max(k_max + fractal_n + 5, 55)

        for t in range(start_idx, n_bars):
            atr_t = atrs[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and not np.isnan(atr_pct[t]) and atr_pct[t] < atr_min_pct:
                continue
            if np.isnan(ema50[t]):
                continue
            if np.isnan(flag_hh_prior[t]) or np.isnan(flag_hh[t]):
                continue

            c_t, o_t = closes[t], opens[t]
            atr_pct_t = atr_pct[t]

            # ============================================================
            # LONG: Double Bottom Bull Flag
            # ============================================================
            if t > last_long_ts + cooldown and c_t > ema50[t]:
                # Look for two swing lows L1 (older) and L2 (recent)
                # L1 in [t-k_max .. t-k_min], L2 in [t-j_max .. t-j_min], confirmed swing
                # Swing low confirmed at fractal_n bars after the swing bar.
                # So we can use sw_low[i] where i <= t-fractal_n.

                # Find most recent swing low L2 within j window
                l2_idx = -1
                l2_min_search = max(0, t - j_max)
                l2_max_search = max(0, t - max(j_min, fractal_n))
                for k in range(l2_max_search, l2_min_search - 1, -1):
                    if k + fractal_n > t:
                        continue  # swing not yet confirmed
                    if sw_low[k]:
                        l2_idx = k
                        break

                if l2_idx >= 0:
                    # Find L1 swing low within K window (older than L2)
                    l1_idx = -1
                    l1_min_search = max(0, t - k_max)
                    l1_max_search = max(0, min(t - k_min, l2_idx - 1))
                    for k in range(l1_max_search, l1_min_search - 1, -1):
                        if k + fractal_n > t:
                            continue
                        if sw_low[k]:
                            l1_idx = k
                            break

                    if l1_idx >= 0 and l1_idx < l2_idx:
                        L1 = lows[l1_idx]
                        L2 = lows[l2_idx]
                        # Double-bottom equality gate (|L1-L2|/L1 < equal_pct)
                        if L1 > 0 and abs(L1 - L2) / L1 < equal_pct:
                            # Intermediate pivot M = max(close[l1_idx+1 .. l2_idx-1])
                            if l2_idx - l1_idx >= 2:
                                M_range = closes[l1_idx + 1: l2_idx]
                                if len(M_range) > 0:
                                    M = float(np.max(M_range))
                                    L_avg = 0.5 * (L1 + L2)
                                    # M must be above L_avg (real rally between)
                                    if M > L_avg:
                                        # Tight flag check (last `flag_bars` bars including t)
                                        # flag_hh[t] = max(high[t-flag_bars+1..t])
                                        # flag_ll[t] = min(low[t-flag_bars+1..t])
                                        # flag_close_min[t] = min(close[t-flag_bars+1..t])
                                        # flag_hh_prior[t] = max(high[t-flag_bars..t-1])
                                        flag_rng = flag_hh[t] - flag_ll[t]
                                        # Conditions:
                                        # (a) flag range < flag_rng_atr * atr14
                                        # (b) all closes in flag >= M (closes above neckline)
                                        # (c) flag prior high <= M + 1.5*atr14 (flag NOT broken yet)
                                        # (d) breakout bar t: close > flag prior high
                                        # (e) bullish: close > open, body_ratio >= body_min
                                        flag_tight = flag_rng / atr_t < flag_rng_atr
                                        closes_above_neck = flag_close_min[t] >= M
                                        flag_unbroken = flag_hh_prior[t] <= M + 1.5 * atr_t
                                        breakout = c_t > flag_hh_prior[t]
                                        bullish_bar = c_t > o_t and body_r[t] >= body_min

                                        if (flag_tight and closes_above_neck and
                                            flag_unbroken and breakout and bullish_bar):
                                            # SL: L2 - sl_mult * ATR
                                            sl_price = L2 - sl_mult * atr_t
                                            entry_ref = c_t
                                            risk = entry_ref - sl_price
                                            if risk > 0:
                                                # Measured move TP
                                                mm_tp = entry_ref + (M - L_avg)
                                                # Floor 2R
                                                floor_tp = entry_ref + tp_r_floor * risk
                                                tp_price = max(mm_tp, floor_tp)
                                                score = long_w
                                                if score >= min_score:
                                                    sig = self.emit_signal(
                                                        ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                                                        venue=venue, symbol=symbol, timeframe=timeframe,
                                                        direction="long",
                                                        pattern_id="db_bull_flag_long",
                                                        confluence_score=float(score),
                                                        sl_price=float(sl_price),
                                                        tp_price=float(tp_price),
                                                        suggested_size_atr=1.0,
                                                        metadata={
                                                            "L1": float(L1),
                                                            "L2": float(L2),
                                                            "L1_idx_back": int(t - l1_idx),
                                                            "L2_idx_back": int(t - l2_idx),
                                                            "neckline_M": float(M),
                                                            "equal_pct": float(abs(L1 - L2) / L1),
                                                            "measured_move_R": float((M - L_avg) / risk) if risk > 0 else None,
                                                            "flag_range_atr": float(flag_rng / atr_t),
                                                            "body_ratio": float(body_r[t]),
                                                        },
                                                    )
                                                    out.append(sig)
                                                    last_long_ts = t

            # ============================================================
            # SHORT: Double Top Bear Flag (mirror)
            # ============================================================
            if t > last_short_ts + cooldown and c_t < ema50[t]:
                h2_idx = -1
                h2_min_search = max(0, t - j_max)
                h2_max_search = max(0, t - max(j_min, fractal_n))
                for k in range(h2_max_search, h2_min_search - 1, -1):
                    if k + fractal_n > t:
                        continue
                    if sw_high[k]:
                        h2_idx = k
                        break

                if h2_idx >= 0:
                    h1_idx = -1
                    h1_min_search = max(0, t - k_max)
                    h1_max_search = max(0, min(t - k_min, h2_idx - 1))
                    for k in range(h1_max_search, h1_min_search - 1, -1):
                        if k + fractal_n > t:
                            continue
                        if sw_high[k]:
                            h1_idx = k
                            break

                    if h1_idx >= 0 and h1_idx < h2_idx:
                        H1 = highs[h1_idx]
                        H2 = highs[h2_idx]
                        if H1 > 0 and abs(H1 - H2) / H1 < equal_pct:
                            if h2_idx - h1_idx >= 2:
                                M_range = closes[h1_idx + 1: h2_idx]
                                if len(M_range) > 0:
                                    M = float(np.min(M_range))
                                    H_avg = 0.5 * (H1 + H2)
                                    if M < H_avg:
                                        flag_rng = flag_hh[t] - flag_ll[t]
                                        # All closes in flag below neckline
                                        flag_close_max = df[f"flag_hh{flag_bars}"].iloc[t]  # this is high max not close
                                        # We need the close max for "all closes <= M". Compute on-the-fly:
                                        flag_start = max(0, t - flag_bars + 1)
                                        closes_flag = closes[flag_start: t + 1]
                                        closes_below_neck = bool(np.all(closes_flag <= M))
                                        flag_tight = flag_rng / atr_t < flag_rng_atr
                                        flag_unbroken = flag_ll_prior[t] >= M - 1.5 * atr_t
                                        breakout = c_t < flag_ll_prior[t]
                                        bearish_bar = c_t < o_t and body_r[t] >= body_min

                                        if (flag_tight and closes_below_neck and
                                            flag_unbroken and breakout and bearish_bar):
                                            sl_price = H2 + sl_mult * atr_t
                                            entry_ref = c_t
                                            risk = sl_price - entry_ref
                                            if risk > 0:
                                                mm_tp = entry_ref - (H_avg - M)
                                                floor_tp = entry_ref - tp_r_floor * risk
                                                tp_price = min(mm_tp, floor_tp)
                                                score = short_w
                                                if score >= min_score:
                                                    sig = self.emit_signal(
                                                        ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                                                        venue=venue, symbol=symbol, timeframe=timeframe,
                                                        direction="short",
                                                        pattern_id="dt_bear_flag_short",
                                                        confluence_score=float(score),
                                                        sl_price=float(sl_price),
                                                        tp_price=float(tp_price),
                                                        suggested_size_atr=1.0,
                                                        metadata={
                                                            "H1": float(H1),
                                                            "H2": float(H2),
                                                            "H1_idx_back": int(t - h1_idx),
                                                            "H2_idx_back": int(t - h2_idx),
                                                            "neckline_M": float(M),
                                                            "equal_pct": float(abs(H1 - H2) / H1),
                                                            "measured_move_R": float((H_avg - M) / risk) if risk > 0 else None,
                                                            "flag_range_atr": float(flag_rng / atr_t),
                                                            "body_ratio": float(body_r[t]),
                                                        },
                                                    )
                                                    out.append(sig)
                                                    last_short_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("brooks_db_bull_flag.signals.generated")
        return out
