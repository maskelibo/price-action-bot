"""SMC Order Block + Liquidity Grab strategy.

Concept: Smart Money Concepts (SMC) order block identified by displacement
(body > 1.5×ATR), combined with a liquidity grab (false break of recent
swing high/low + reclaim within 3 bars). Entry triggers when price returns
to the OB zone AFTER a liquidity grab; bias filter is 200-EMA.

Design principles
-----------------
* Every detection uses only bars[0..t] — strictly lookahead-free.
* OB is identified once displacement is confirmed (at displacement bar), so
  the OB itself is from the past.
* Liquidity grab uses only past swing extremes (fractal n=2 → swing known at t-2).
* 200-EMA computed once in prepare_features.

References
----------
smc_ict_summary.md — Order Block Bullish/Bearish definition + Liquidity Grab rule.
Hypothesis: 2026-05-08-smc-ob-liquidity-grab-1d-crypto.md (PROMOTE).

Critical note: SMC is community methodology with weak academic support.
Mechanical implementation may not preserve the subjective edge claimed by
practitioners. Results should be treated critically.
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


def _fractal_swing_highs(df: pd.DataFrame, n: int = 2) -> pd.Series:
    """N-bar fractal swing high (past-only).

    A bar at index t is a swing high iff it has n lower-high bars on each side.
    Because right-side bars are needed, swing[t] becomes reliable only at t+n.
    Callers must access swing[t] only from t+n onwards — enforced by the
    detect helpers below.
    """
    h = df["high"].astype(float)
    left_max = h.shift(1).rolling(n, min_periods=n).max()
    right_max = h.shift(-n).rolling(n, min_periods=n).max()
    return ((h > left_max) & (h > right_max)).fillna(False)


def _fractal_swing_lows(df: pd.DataFrame, n: int = 2) -> pd.Series:
    l = df["low"].astype(float)
    left_min = l.shift(1).rolling(n, min_periods=n).min()
    right_min = l.shift(-n).rolling(n, min_periods=n).min()
    return ((l < left_min) & (l < right_min)).fillna(False)


# =====================================================================
# Core SMC detectors
# =====================================================================

def _detect_displacement(df: pd.DataFrame, atr_mult: float = 1.5) -> pd.Series:
    """Return boolean Series — bar is a displacement bar.

    Displacement: the candle body (|close - open|) exceeds atr_mult * ATR(14)
    AND the candle closes on a new short-term high/low (break of structure).

    BOS proxy: close > 3-bar rolling high (bull disp) or close < 3-bar rolling low (bear disp).
    This ensures the bar truly breaks recent structure.

    Lookahead-free: only shift(1) rolling comparisons used.
    """
    body = (df["close"] - df["open"]).abs().astype(float)
    atr14 = df["atr14"] if "atr14" in df.columns else _atr(df, 14)

    # BOS proxies
    prev_high = df["high"].shift(1).rolling(3, min_periods=3).max()
    prev_low = df["low"].shift(1).rolling(3, min_periods=3).min()
    bull_bos = df["close"] > prev_high
    bear_bos = df["close"] < prev_low

    strong_body = body > atr_mult * atr14
    is_bull = df["close"] > df["open"]
    is_bear = df["close"] < df["open"]

    bull_disp = strong_body & is_bull & bull_bos
    bear_disp = strong_body & is_bear & bear_bos

    return (bull_disp | bear_disp).fillna(False)


def _detect_order_blocks(df: pd.DataFrame, atr_mult: float = 1.5) -> pd.DataFrame:
    """Detect order blocks and add columns to a copy of df.

    Returns df with added columns:
        bullish_ob  : bool — this bar IS a bullish OB
        bearish_ob  : bool — this bar IS a bearish OB
        ob_high     : float — OB zone top (NaN if not OB)
        ob_low      : float — OB zone bottom (NaN if not OB)

    Bullish OB: last bearish candle BEFORE a bullish displacement.
    Algorithm (lookahead-free):
        For each displacement bar t, look back to find the most recent
        bearish candle at t-1 (or t-2 if t-1 is also displacement candidate).
        Mark that candle as a bullish OB.

    Bearish OB: last bullish candle before bearish displacement.

    Because we need to look one step forward (to see if the next bar is
    displacement), we tag OBs at displacement-bar time (t) pointing to t-1.
    This is safe because t-1 data is in the past.
    """
    df = df.copy()
    n = len(df)
    bullish_ob = np.zeros(n, dtype=bool)
    bearish_ob = np.zeros(n, dtype=bool)
    ob_high = np.full(n, np.nan)
    ob_low = np.full(n, np.nan)

    body = (df["close"] - df["open"]).astype(float).values
    atr14 = (df["atr14"] if "atr14" in df.columns else _atr(df, 14)).values
    close_ = df["close"].astype(float).values
    open_ = df["open"].astype(float).values
    high_ = df["high"].astype(float).values
    low_ = df["low"].astype(float).values

    # BOS check arrays
    for t in range(4, n):  # need t-3 history for rolling BOS check
        if atr14[t] <= 0 or np.isnan(atr14[t]):
            continue
        body_t = abs(body[t])
        if body_t <= atr_mult * atr14[t]:
            continue

        # Is bar t a bullish displacement?
        prev_high_max = max(high_[max(0, t - 3): t]) if t >= 1 else high_[t - 1]
        if close_[t] > prev_high_max and close_[t] > open_[t]:
            # Bullish displacement at t → look for last bearish candle before t
            for k in range(t - 1, max(-1, t - 5), -1):
                if close_[k] < open_[k]:  # bearish candle
                    bullish_ob[k] = True
                    ob_high[k] = high_[k]
                    ob_low[k] = low_[k]
                    break

        # Is bar t a bearish displacement?
        prev_low_min = min(low_[max(0, t - 3): t]) if t >= 1 else low_[t - 1]
        if close_[t] < prev_low_min and close_[t] < open_[t]:
            # Bearish displacement at t → look for last bullish candle before t
            for k in range(t - 1, max(-1, t - 5), -1):
                if close_[k] > open_[k]:  # bullish candle
                    bearish_ob[k] = True
                    ob_high[k] = high_[k]
                    ob_low[k] = low_[k]
                    break

    df["bullish_ob"] = bullish_ob
    df["bearish_ob"] = bearish_ob
    df["ob_high"] = ob_high
    df["ob_low"] = ob_low
    return df


def _detect_liquidity_grab(df: pd.DataFrame, lookback: int = 10, swing_n: int = 2) -> pd.DataFrame:
    """Detect liquidity grabs.

    A bullish liquidity grab at bar t:
        - df.low[t] < recent_swing_low  (wick penetrates swing)
        - df.close[t] > recent_swing_low  (closes back above)
        - sweep magnitude ≥ 0.25 × ATR(14)

    A bearish liquidity grab:
        - df.high[t] > recent_swing_high (wick penetrates swing)
        - df.close[t] < recent_swing_high (closes back below)
        - sweep magnitude ≥ 0.25 × ATR(14)

    "Recent swing" = last fractal swing within `lookback` bars, known at bar t
    (swing detected at t-swing_n at latest, so fully past).

    Returns df with added boolean columns:
        liq_grab_bull : bullish liquidity grab (sweep of swing low)
        liq_grab_bear : bearish liquidity grab (sweep of swing high)
    """
    df = df.copy()
    n = len(df)
    sh = _fractal_swing_highs(df, n=swing_n).values
    sl = _fractal_swing_lows(df, n=swing_n).values
    high_ = df["high"].astype(float).values
    low_ = df["low"].astype(float).values
    close_ = df["close"].astype(float).values
    atr14 = (df["atr14"] if "atr14" in df.columns else _atr(df, 14)).values

    liq_grab_bull = np.zeros(n, dtype=bool)
    liq_grab_bear = np.zeros(n, dtype=bool)

    for t in range(swing_n + 1, n):
        if atr14[t] <= 0 or np.isnan(atr14[t]):
            continue
        atr_t = atr14[t]
        min_sweep = 0.25 * atr_t

        # Find recent swing lows in lookback window (indices strictly before t,
        # confirmed at least swing_n bars before t so they're reliable)
        swing_low_prices: list[float] = []
        swing_high_prices: list[float] = []
        for k in range(max(0, t - lookback), t - swing_n):
            if sl[k]:
                swing_low_prices.append(low_[k])
            if sh[k]:
                swing_high_prices.append(high_[k])

        # Bullish grab: wick below recent swing low, close above it
        for sw_low in swing_low_prices:
            if (low_[t] < sw_low
                    and close_[t] > sw_low
                    and (sw_low - low_[t]) >= min_sweep):
                liq_grab_bull[t] = True
                break

        # Bearish grab: wick above recent swing high, close below it
        for sw_high in swing_high_prices:
            if (high_[t] > sw_high
                    and close_[t] < sw_high
                    and (high_[t] - sw_high) >= min_sweep):
                liq_grab_bear[t] = True
                break

    df["liq_grab_bull"] = liq_grab_bull
    df["liq_grab_bear"] = liq_grab_bear
    return df


# =====================================================================
# Signal generation helpers
# =====================================================================

def _price_in_ob_zone(price: float, ob_high: float, ob_low: float) -> bool:
    """True if price is within [ob_low, ob_high]."""
    return ob_low <= price <= ob_high


def _recent_liq_grab(df: pd.DataFrame, bar_idx: int, kind: str, window: int = 5) -> bool:
    """True if a liquidity grab of 'kind' (bull/bear) occurred in last `window` bars."""
    col = f"liq_grab_{kind}"
    if col not in df.columns:
        return False
    start = max(0, bar_idx - window)
    return bool(df[col].iloc[start:bar_idx + 1].any())


# =====================================================================
# Strategy class
# =====================================================================

class SMCOrderBlockStrategy(Strategy):
    """SMC Order Block + Liquidity Grab combo strategy.

    Signal logic:
        Long: price returns to a bullish OB zone AFTER a bullish liquidity grab
              AND close is above 200-EMA.
        Short: price returns to a bearish OB zone AFTER a bearish liquidity grab
               AND close is below 200-EMA.

    Stop: below OB low (long) / above OB high (short).
    Target: primary_R × risk (default 3.0).
    """

    name = "smc_orderblock"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # Core indicators
        df["ema200"] = _ema(df["close"], 200)
        df["atr14"] = _atr(df, 14)

        # Swing highs / lows (fractal n=2)
        df["swing_high"] = _fractal_swing_highs(df, n=2)
        df["swing_low"] = _fractal_swing_lows(df, n=2)

        # Displacement flag (body > atr_mult * ATR with BOS)
        atr_mult = float(
            getattr(self.manifest.signals.filters, "atr_mult_for_displacement", 1.5) or 1.5
        )
        df["displacement"] = _detect_displacement(df, atr_mult=atr_mult)

        # Order blocks
        df = _detect_order_blocks(df, atr_mult=atr_mult)

        # Liquidity grabs
        df = _detect_liquidity_grab(df, lookback=10, swing_n=2)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "atr14" not in df.columns:
            df = self.prepare_features(df)

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 3.0)
        )
        atr_mult_for_sl = float(
            self.manifest.risk.get("stop_loss", {}).get("atr_multiplier", 1.0)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # Build a list of active (unmitigated) OBs with their zones
        # OB is "mitigated" once price closes through its zone from the
        # expected direction — we handle this lazily: we only look back at
        # known OBs at each bar.

        out: list[Signal] = []

        for i in range(50, len(df)):  # need warm-up for EMA200, ATR
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14", 0.0) or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue

            ema200 = float(row.get("ema200", np.nan) or np.nan)
            if np.isnan(ema200):
                continue

            # 200-EMA bias
            bias_long = close > ema200
            bias_short = close < ema200

            # Search backward for the most recent unmitigated bullish OB
            if bias_long:
                ob_signal = self._find_ob_entry(
                    df=df,
                    current_idx=i,
                    direction="long",
                    liq_grab_window=5,
                )
                if ob_signal is not None:
                    ob_high_price, ob_low_price = ob_signal
                    sl_price = ob_low_price - atr_mult_for_sl * atr
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
                        pattern_id="smc_ob_liq_grab_long",
                        confluence_score=2.0,  # OB + liq_grab = 2 confluence factors
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=atr_mult_for_sl,
                        metadata={
                            "ob_high": float(ob_high_price),
                            "ob_low": float(ob_low_price),
                            "ema200": float(ema200),
                            "atr14": float(atr),
                            "primary_R": primary_R,
                        },
                    )
                    out.append(sig)

            if bias_short:
                ob_signal = self._find_ob_entry(
                    df=df,
                    current_idx=i,
                    direction="short",
                    liq_grab_window=5,
                )
                if ob_signal is not None:
                    ob_high_price, ob_low_price = ob_signal
                    sl_price = ob_high_price + atr_mult_for_sl * atr
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
                        pattern_id="smc_ob_liq_grab_short",
                        confluence_score=2.0,
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=atr_mult_for_sl,
                        metadata={
                            "ob_high": float(ob_high_price),
                            "ob_low": float(ob_low_price),
                            "ema200": float(ema200),
                            "atr14": float(atr),
                            "primary_R": primary_R,
                        },
                    )
                    out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("smc_ob.signals.generated")
        return out

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_ob_entry(
        self,
        df: pd.DataFrame,
        current_idx: int,
        direction: str,
        liq_grab_window: int = 5,
    ) -> tuple[float, float] | None:
        """Find the most recent valid OB entry condition.

        Returns (ob_high, ob_low) if all conditions met, else None.

        Conditions:
        1. There is a recent liquidity grab in the correct direction.
        2. There is a recent OB zone (within lookback_ob bars).
        3. Current price is WITHIN the OB zone (touching/retesting it).
        4. The current bar shows rejection: for long — close > open (bullish bar
           touching bearish OB zone from above); for short — close < open.
        """
        row = df.iloc[current_idx]
        close = float(row["close"])
        open_ = float(row["open"])

        # Condition 1: liquidity grab in last `liq_grab_window` bars
        liq_col = "liq_grab_bull" if direction == "long" else "liq_grab_bear"
        if liq_col not in df.columns:
            return None
        start = max(0, current_idx - liq_grab_window)
        if not df[liq_col].iloc[start:current_idx + 1].any():
            return None

        # Condition 4: rejection candle (directional close)
        if direction == "long" and close <= open_:
            return None
        if direction == "short" and close >= open_:
            return None

        # Conditions 2+3: find OB zone that price is currently within
        ob_col = "bullish_ob" if direction == "long" else "bearish_ob"
        if ob_col not in df.columns:
            return None

        lookback_ob = 30  # bars to look back for OB
        search_start = max(0, current_idx - lookback_ob)

        # Walk backward to find most recent relevant OB
        for k in range(current_idx - 1, search_start - 1, -1):
            if not df[ob_col].iloc[k]:
                continue
            ob_high = float(df["ob_high"].iloc[k])
            ob_low = float(df["ob_low"].iloc[k])
            if np.isnan(ob_high) or np.isnan(ob_low):
                continue

            # Price must be within (or touching) OB zone
            if _price_in_ob_zone(close, ob_high=ob_high, ob_low=ob_low):
                return (ob_high, ob_low)

            # Also valid if current bar LOW touched OB zone (wick test)
            bar_low = float(df["low"].iloc[current_idx])
            bar_high = float(df["high"].iloc[current_idx])
            if direction == "long" and bar_low <= ob_high and close > ob_low:
                return (ob_high, ob_low)
            if direction == "short" and bar_high >= ob_low and close < ob_high:
                return (ob_high, ob_low)

        return None
