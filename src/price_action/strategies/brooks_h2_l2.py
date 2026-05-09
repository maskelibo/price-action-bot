"""Brooks H2/L2 Two-Legged Pullback stratejisi.

Brooks'un en guvenilir setup'i: bull/bear trendde ABC two-legged pullback,
ikinci bacak sonunda trend yonune continuation entry.

Pattern (mekanik):
  - Trend     : 50-EMA + son 10 bar always-in teyidi
  - Leg A     : Trend ters yonunde 3+ bar consecutive (pullback baslangici)
  - Leg B     : Trend yonunde 1-3 bar (kucuk bounce — A'yi tam geri almaz)
  - Leg C     : Trend ters yonunde 3+ bar (ikinci pullback)
  - Entry     : Leg C'nin son bari trend yonunde kapanis yaparsa
                bir sonraki barda entry (bar kapanisi sonrasi karar)
  - SL        : Leg C swing point (long icin en dusuk low, short icin en yuksek
                high) - 0.5 ATR
  - TP        : 2R primary

Brooks'un edge iddiasi: ~%65-75 win rate, EV ~+0.8-1.2 R/trade.
Kaynak: brooks_deep_catalog.md -> H2 / L2 bolumu.

Manifest yoksa dahili default kullanilir.
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
    _fractal_swings,
    _kaufman_efficiency_ratio,
    _always_in_flags,
    _rolling_sharpe,
)


# =====================================================================
# H2/L2 pattern detection (vektorel, lookahead-free)
# =====================================================================

def _count_consecutive_direction(close: pd.Series, direction: int) -> pd.Series:
    """Her bar icin, o bar dahil geri sayilan consecutive `direction` bar sayisi.

    direction = +1 : bullish bars (close > prev_close)
    direction = -1 : bearish bars (close < prev_close)

    Lookahead-free: t bari icin sadece t ve oncesi bilgi kullanilir.
    """
    move = (close.diff() * direction > 0).astype(int)
    # Cumulative run-length encode: her run'da sayac sifirlanir
    result = np.zeros(len(close), dtype=int)
    count = 0
    for i in range(len(close)):
        if move.iloc[i] == 1:
            count += 1
        else:
            count = 0
        result[i] = count
    return pd.Series(result, index=close.index, name=f"consec_{direction}")


def _detect_h2_l2(
    df: pd.DataFrame,
    trend_col: str = "trend_long",
    *,
    leg_min_bars: int = 3,
    bounce_max_bars: int = 3,
    max_lookback: int = 25,
    atr_col: str = "atr14",
    sl_atr_buffer: float = 0.5,
    primary_R: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """H2/L2 two-legged pullback detection.

    H2 (bull trend): ABC pullback — A down, B up (partial), C down, entry on bull close.
    L2 (bear trend): ABC pullback — A up, B down (partial), C up, entry on bear close.

    Dondurulen:
        h2_signal   : H2 long signal (bool, bar'da)
        l2_signal   : L2 short signal (bool, bar'da)
        h2_sl       : H2 stop loss fiyati
        h2_tp       : H2 take profit fiyati
        l2_sl       : L2 stop loss fiyati
        l2_tp       : L2 take profit fiyati

    Lookahead-free: t bari icin sadece t ve oncesi bar kullanilir.
    Algoritma: her bar icin max_lookback bari geriye tarayarak ABC duzeni arar.
    """
    closes = df["close"].to_numpy(dtype=float)
    opens = df["open"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    atrs = df[atr_col].to_numpy(dtype=float)
    trend_long = df[trend_col].to_numpy(dtype=bool)

    n = len(df)
    h2_signal = np.zeros(n, dtype=bool)
    l2_signal = np.zeros(n, dtype=bool)
    h2_sl_arr = np.full(n, np.nan)
    h2_tp_arr = np.full(n, np.nan)
    l2_sl_arr = np.full(n, np.nan)
    l2_tp_arr = np.full(n, np.nan)

    for i in range(max_lookback + 6, n):
        atr = atrs[i]
        if np.isnan(atr) or atr <= 0:
            continue
        close_i = closes[i]
        open_i = opens[i]

        # --- H2: Bull trend, two-legged pullback long ---
        # Current bar must be a bull close (trend yonunde kapaniyor)
        if close_i > open_i:
            # Scan backwards for ABC (down-up-down) structure
            # Leg C ends at bar i (bull reversal bar at bottom of C)
            # We look backwards: find leg C (consecutive down bars ending at i-1 or earlier)
            # then leg B (consecutive up bars), then leg A (consecutive down bars)

            # Step 1: Find end of Leg C — bars before i going down
            c_bars = 0
            c_low = lows[i]  # include current bar's low for SL
            j = i - 1
            while j >= max(0, i - max_lookback) and c_bars < 15:
                if closes[j] < closes[j - 1] if j > 0 else False:
                    c_bars += 1
                    c_low = min(c_low, lows[j])
                    j -= 1
                else:
                    break

            if c_bars >= leg_min_bars - 1:
                b_end_idx = j  # leg B ends here

                # Step 2: Find leg B (up bars) — partial bounce
                b_bars = 0
                k = b_end_idx
                while k >= max(0, i - max_lookback) and b_bars < bounce_max_bars + 2:
                    if closes[k] > closes[k - 1] if k > 0 else False:
                        b_bars += 1
                        k -= 1
                    else:
                        break

                if 1 <= b_bars <= bounce_max_bars + 1:
                    a_end_idx = k  # leg A ends here

                    # Step 3: Find leg A (down bars)
                    a_bars = 0
                    m = a_end_idx
                    while m >= max(0, i - max_lookback) and a_bars < 15:
                        if closes[m] < closes[m - 1] if m > 0 else False:
                            a_bars += 1
                            m -= 1
                        else:
                            break

                    if a_bars >= leg_min_bars - 1:
                        # Check trend at the bar BEFORE leg A started (pre-pullback context)
                        pre_pullback_idx = max(0, m)
                        pre_trend_long = trend_long[pre_pullback_idx]
                        if pre_trend_long:
                            # Valid H2 setup
                            sl_price = c_low - sl_atr_buffer * atr
                            sl_price = min(sl_price, close_i - 0.5 * atr)
                            risk = close_i - sl_price
                            if risk > 0:
                                tp_price = close_i + primary_R * risk
                                h2_signal[i] = True
                                h2_sl_arr[i] = sl_price
                                h2_tp_arr[i] = tp_price

        # --- L2: Bear trend, two-legged pullback short ---
        # Current bar must be a bear close
        if close_i < open_i:
            # Scan backwards for ABC (up-down-up) structure
            c_bars = 0
            c_high = highs[i]
            j = i - 1
            while j >= max(0, i - max_lookback) and c_bars < 15:
                if closes[j] > closes[j - 1] if j > 0 else False:
                    c_bars += 1
                    c_high = max(c_high, highs[j])
                    j -= 1
                else:
                    break

            if c_bars >= leg_min_bars - 1:
                b_end_idx = j

                b_bars = 0
                k = b_end_idx
                while k >= max(0, i - max_lookback) and b_bars < bounce_max_bars + 2:
                    if closes[k] < closes[k - 1] if k > 0 else False:
                        b_bars += 1
                        k -= 1
                    else:
                        break

                if 1 <= b_bars <= bounce_max_bars + 1:
                    a_end_idx = k

                    a_bars = 0
                    m = a_end_idx
                    while m >= max(0, i - max_lookback) and a_bars < 15:
                        if closes[m] > closes[m - 1] if m > 0 else False:
                            a_bars += 1
                            m -= 1
                        else:
                            break

                    if a_bars >= leg_min_bars - 1:
                        # Check trend at bar BEFORE leg A started (pre-pullback context)
                        pre_pullback_idx = max(0, m)
                        pre_trend_short = not trend_long[pre_pullback_idx]
                        if pre_trend_short:
                            # Valid L2 setup
                            sl_price = c_high + sl_atr_buffer * atr
                            sl_price = max(sl_price, close_i + 0.5 * atr)
                            risk = sl_price - close_i
                            if risk > 0:
                                tp_price = close_i - primary_R * risk
                                l2_signal[i] = True
                                l2_sl_arr[i] = sl_price
                                l2_tp_arr[i] = tp_price

    return (
        pd.Series(h2_signal, index=df.index, name="h2_signal"),
        pd.Series(l2_signal, index=df.index, name="l2_signal"),
        pd.Series(h2_sl_arr, index=df.index, name="h2_sl"),
        pd.Series(h2_tp_arr, index=df.index, name="h2_tp"),
        pd.Series(l2_sl_arr, index=df.index, name="l2_sl"),
        pd.Series(l2_tp_arr, index=df.index, name="l2_tp"),
    )


def _trend_direction(
    df: pd.DataFrame,
    ema_col: str = "ema50",
    n_bars: int = 10,
) -> tuple[pd.Series, pd.Series]:
    """Trend yonu: 50-EMA + son n_bars'ta majority close direction.

    Long  : close > ema50 AND son n_bars'ta >= 6 bullish close
    Short : close < ema50 AND son n_bars'ta >= 6 bearish close

    Lookahead-free: sadece t bari ve oncesi kullanilir.
    """
    close = df["close"]
    ema = df[ema_col]
    bull_bars = (close > close.shift(1)).rolling(n_bars, min_periods=5).sum()
    bear_bars = (close < close.shift(1)).rolling(n_bars, min_periods=5).sum()
    trend_long = (close > ema) & (bull_bars >= n_bars * 0.6)
    trend_short = (close < ema) & (bear_bars >= n_bars * 0.6)
    return trend_long.fillna(False), trend_short.fillna(False)


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "brooks_h2_l2",
        "version": "1.0.0",
        "description": (
            "Brooks H2/L2 two-legged pullback — ABC corrective, "
            "entry on trend-direction bar at Leg C terminus"
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "h2_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "leg_min_bars": 3,
                        "bounce_max_bars": 3,
                        "max_lookback": 25,
                        "sl_atr_buffer": 0.5,
                    },
                },
                {
                    "id": "l2_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "leg_min_bars": 3,
                        "bounce_max_bars": 3,
                        "max_lookback": 25,
                        "sl_atr_buffer": 0.5,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 100,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 100,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.004,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.15,
                "always_in_required": False,
                "bear_regime_size_factor": 0.75,
                "trend_n_bars": 10,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "leg_c_extreme", "atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class BrooksH2L2Strategy(Strategy):
    """Brooks H2/L2 two-legged pullback continuation strategy.

    Trend    : 50-EMA direction + 10-bar majority closes
    Pattern  : ABC two-legged pullback (Leg A down, Leg B bounce, Leg C down)
               detected at bar close (lookahead-free)
    Entry    : Bar that shows trend-direction close after Leg C
    Stop     : Leg C extreme + 0.5 ATR buffer
    Target   : 2R primary
    """

    name = "brooks_h2_l2"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # EMAs
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)

        # ATR
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Volume z-score
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Kaufman ER
        filters_cfg = self.manifest.signals.filters
        er_period = int(getattr(filters_cfg, "kaufman_er_period", 14) or 14)
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Brooks always-in flags
        ai_n = int(getattr(filters_cfg, "always_in_n_confirm", 3) or 3)
        long_ai, short_ai = _always_in_flags(df, n_confirm=ai_n)
        df["always_in_long"] = long_ai
        df["always_in_short"] = short_ai

        # Rolling Sharpe
        rs_period = int(getattr(filters_cfg, "rolling_sharpe_period", 60) or 60)
        df["rolling_sharpe"] = _rolling_sharpe(df["close"], period=rs_period)

        # Trend direction
        n_bars = int(getattr(filters_cfg, "trend_n_bars", 10) or 10)
        trend_long, trend_short = _trend_direction(df, ema_col="ema50", n_bars=n_bars)
        df["trend_long"] = trend_long
        df["trend_short"] = trend_short

        # H2/L2 pattern detection — get params from manifest
        p_cfg = [p.params for p in self.manifest.signals.patterns if p.id == "h2_long"]
        params = p_cfg[0] if p_cfg else {}
        leg_min = int(params.get("leg_min_bars", 3) if params else 3)
        bounce_max = int(params.get("bounce_max_bars", 3) if params else 3)
        lookback = int(params.get("max_lookback", 25) if params else 25)
        sl_buf = float(params.get("sl_atr_buffer", 0.5) if params else 0.5)
        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
        )

        h2_sig, l2_sig, h2_sl, h2_tp, l2_sl, l2_tp = _detect_h2_l2(
            df,
            trend_col="trend_long",
            leg_min_bars=leg_min,
            bounce_max_bars=bounce_max,
            max_lookback=lookback,
            atr_col="atr14",
            sl_atr_buffer=sl_buf,
            primary_R=primary_R,
        )
        df["h2_signal"] = h2_sig
        df["l2_signal"] = l2_sig
        df["h2_sl"] = h2_sl
        df["h2_tp"] = h2_tp
        df["l2_sl"] = l2_sl
        df["l2_tp"] = l2_tp

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "h2_signal" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        confluence = signals_cfg.confluence

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # Score series — start from detected signals
        h2_score = df["h2_signal"].astype(float) * 2.0
        l2_score = df["l2_signal"].astype(float) * 2.0

        # ATR min filter
        atr_min = float(getattr(filters, "atr_min_pct", 0.004) or 0.004)
        if atr_min > 0:
            mask = df["atr_pct"] >= atr_min
            h2_score = h2_score.where(mask, 0.0)
            l2_score = l2_score.where(mask, 0.0)

        # Kaufman ER min
        er_min = float(getattr(filters, "kaufman_er_min", 0.0) or 0.0)
        if er_min > 0 and "kaufman_er" in df.columns:
            mask = df["kaufman_er"] >= er_min
            h2_score = h2_score.where(mask, 0.0)
            l2_score = l2_score.where(mask, 0.0)

        # 200-EMA bear regime
        bear_factor = float(getattr(filters, "bear_regime_size_factor", 1.0) or 1.0)
        if bear_factor < 1.0 and "ema200" in df.columns:
            below_200 = df["close"] < df["ema200"]
            h2_score = h2_score.where(~below_200, h2_score * bear_factor)

        min_score = float(confluence.min_score)

        out: list[Signal] = []
        for i in range(len(df)):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue

            # H2 long
            hs = float(h2_score.iat[i])
            if hs >= min_score and not np.isnan(row.get("h2_sl", np.nan)):
                sl_price = float(row["h2_sl"])
                tp_price = float(row["h2_tp"])
                if not np.isnan(sl_price) and not np.isnan(tp_price) and sl_price < close:
                    ts = pd.Timestamp(row["ts"]).to_pydatetime()
                    sig = self.emit_signal(
                        ts=ts,
                        venue=venue,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="long",
                        pattern_id="h2_long",
                        confluence_score=float(hs),
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=1.0,
                        metadata={
                            "atr14": atr,
                            "ema50": float(row.get("ema50") or 0.0),
                            "kaufman_er": float(row.get("kaufman_er") or 0.0),
                            "trend_long": bool(row.get("trend_long", False)),
                        },
                    )
                    out.append(sig)

            # L2 short
            ls = float(l2_score.iat[i])
            if ls >= min_score and not np.isnan(row.get("l2_sl", np.nan)):
                sl_price = float(row["l2_sl"])
                tp_price = float(row["l2_tp"])
                if not np.isnan(sl_price) and not np.isnan(tp_price) and sl_price > close:
                    ts = pd.Timestamp(row["ts"]).to_pydatetime()
                    sig = self.emit_signal(
                        ts=ts,
                        venue=venue,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="short",
                        pattern_id="l2_short",
                        confluence_score=float(ls),
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=1.0,
                        metadata={
                            "atr14": atr,
                            "ema50": float(row.get("ema50") or 0.0),
                            "kaufman_er": float(row.get("kaufman_er") or 0.0),
                            "trend_long": bool(row.get("trend_long", False)),
                        },
                    )
                    out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("brooks_h2_l2.signals.generated")
        return out
