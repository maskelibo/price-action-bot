"""Three Black Crows short-only strategy.

Bulkowski istatistigi: %78 bearish continuation/reversal rate (Rank 7/103).
H-C10 hipotezi: Three Black Crows + Volume Escalation.

Kural ozeti (SHORT ONLY):
  - Bagim  : 200-EMA ustu (top distribution — bear regime baslangici)
  - Bar 1  : Bearish bar; body >= 50% range; alt golge <= %20 range;
             volume >= 10-bar avg
  - Bar 2  : Bearish bar; body >= 50% range; alt golge <= %20 range;
             close < Bar1 close (LL); open yakin Bar1 close (body'nin %50 ici);
             volume >= Bar1 volume
  - Bar 3  : Bearish bar; body >= 50% range; alt golge <= %20 range;
             close < Bar2 close (LL); open yakin Bar2 close;
             volume >= Bar2 volume
  - Volume eskalasyonu: zorunlu (Bar1 < Bar2 < Bar3)
  - Giris  : Bar 3 kapanis sonrasi (next bar acilis)
  - Stop   : Bar 1'in high'i (3-bar pattern en yuksegi)
  - Hedef  : 2R (SL mesafesinin 2 kati kadar asagi)
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
# Pattern detector
# =====================================================================

def _three_black_crows(
    df: pd.DataFrame,
    *,
    body_ratio_min: float = 0.50,
    lower_shadow_max: float = 0.20,
    open_proximity_pct: float = 0.50,
    volume_escalation: bool = True,
    vol_avg_window: int = 10,
) -> pd.Series:
    """Three Black Crows dedektoru (lookahead-free).

    t barinda sinyal = True eger [t-2, t-1, t] uclisi kurali karsiliyor.

    Parametreler:
      body_ratio_min    : body / range >= bu deger (default 0.5)
      lower_shadow_max  : lower_shadow / range <= bu deger (default 0.2)
      open_proximity_pct: Bar N'in acilisi, Bar N-1'in kapanisinin
                          body_pct * onceki_body kadar uzakta olmali (0.5 = body'nin %50'si)
      volume_escalation : Her bar oncekinden yuksek volume olmali
      vol_avg_window    : Volume baseline penceresi
    """
    o = df["open"]
    h = df["high"]
    l = df["low"]
    c = df["close"]
    v = df["volume"]

    rng = (h - l).replace(0, np.nan)
    body_abs = (c - o).abs()
    body_ratio = body_abs / rng

    # Lower shadow (bearish: close < open => lower shadow = close - low)
    lower_shadow = (c - l).clip(lower=0.0)  # for bearish bars
    lower_shadow_ratio = lower_shadow / rng

    # Bearish color
    is_bearish = c < o

    # Bar-level: qualifies as a "good" crow bar
    good_bar = (
        is_bearish
        & (body_ratio >= body_ratio_min)
        & (lower_shadow_ratio <= lower_shadow_max)
    )

    # Volume baseline
    vol_avg = v.shift(1).rolling(vol_avg_window, min_periods=3).mean()

    # Bar 3 = t, Bar 2 = t-1, Bar 1 = t-2
    gb3 = good_bar
    gb2 = good_bar.shift(1).fillna(False)
    gb1 = good_bar.shift(2).fillna(False)

    o3, c3 = o, c
    o2, c2 = o.shift(1), c.shift(1)
    o1, c1 = o.shift(2), c.shift(2)
    v3, v2, v1 = v, v.shift(1), v.shift(2)

    # LL series: each bar closes lower than previous
    ll_ok = (c3 < c2) & (c2 < c1)

    # Open proximity: Bar N opens near Bar N-1's close (loose check).
    # Classic definition: open within upper half of previous bar's body.
    # For a bearish bar: open should not be too far above prev close.
    # We allow open up to open_proximity_pct * prev_body above prev close.
    body2 = (c2 - o2).abs()
    body1 = (c1 - o1).abs()
    prox3 = open_proximity_pct * body2
    prox2 = open_proximity_pct * body1

    # Bar 3 open near Bar 2 close (should not open FAR above c2)
    # Allow open >= c2 - prox3 (slightly below) AND open <= c2 + prox3 (slightly above)
    open3_ok = o3 <= (c2 + prox3)   # gap-up open too high = NOT a crow
    # Bar 2 open near Bar 1 close
    open2_ok = o2 <= (c1 + prox2)

    # Volume escalation: net escalation over the 3-bar pattern.
    # Requirement: v3 > v1 (bar3 volume exceeds bar1 volume) — net selling pressure grew.
    # Strict bar-to-bar (v1<v2<v3) is too tight for noisy crypto daily volume.
    # Also require v3 >= vol_avg (bar3 must be an elevated-volume day).
    if volume_escalation:
        vol_ok = (v3 > v1) & (v3 >= vol_avg.fillna(0))
    else:
        vol_ok = pd.Series(True, index=df.index)

    signal = gb1 & gb2 & gb3 & ll_ok & open2_ok & open3_ok & vol_ok
    return signal.fillna(False)


def _pattern_stop(df: pd.DataFrame) -> pd.Series:
    """Stop = Bar1 high (= t-2 bar high)."""
    return df["high"].shift(2)


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "three_black_crows",
        "version": "1.0.0",
        "description": (
            "Three Black Crows short-only. Bulkowski %78 bearish rate. "
            "200-EMA above (top distribution), volume escalation required."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "three_black_crows",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_min": 0.50,
                        "lower_shadow_max": 0.30,
                        "open_proximity_pct": 1.00,
                        "volume_escalation": True,
                        "vol_avg_window": 10,
                    },
                }
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
            "stop_loss": {"method": "pattern_high", "bar_lookback": 2},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class ThreeBlackCrowsStrategy(Strategy):
    """Three Black Crows — SHORT ONLY.

    Giris    : Pattern tamamlandiktan sonraki bar acilisi (bar3 kapanis + 1)
    Stop     : Bar1 high (pattern'in en yuksek noktasi)
    Hedef    : 2R
    Bagim    : 200-EMA ustu (distribution peak)
    Volume   : Escalation zorunlu (her bar bir oncekinden fazla)
    """

    name = "three_black_crows"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # EMAs
        df["ema200"] = _ema(df["close"], 200)
        df["ema50"] = _ema(df["close"], 50)

        # ATR
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Volume z-score (60 bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=5).mean()
        vstd = vol.rolling(60, min_periods=5).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Pattern parameters from manifest
        patterns = self.manifest.signals.patterns
        params: dict[str, Any] = {}
        for p in patterns:
            if p.id == "three_black_crows":
                params = p.params
                break

        body_ratio_min = float(params.get("body_ratio_min", 0.50))
        lower_shadow_max = float(params.get("lower_shadow_max", 0.20))
        open_proximity_pct = float(params.get("open_proximity_pct", 0.50))
        volume_escalation = bool(params.get("volume_escalation", True))
        vol_avg_window = int(params.get("vol_avg_window", 10))

        # Three Black Crows pattern flag
        df["tbc_signal"] = _three_black_crows(
            df,
            body_ratio_min=body_ratio_min,
            lower_shadow_max=lower_shadow_max,
            open_proximity_pct=open_proximity_pct,
            volume_escalation=volume_escalation,
            vol_avg_window=vol_avg_window,
        )

        # Pattern stop: Bar1 high (t-2)
        df["tbc_stop"] = _pattern_stop(df)

        # Bar1 (t-2) above 200-EMA: the distribution TOP context.
        # We check bar1 position, not bar3, because by bar3 the price may already
        # be below 200-EMA after three consecutive down days. The logic is:
        # the pattern STARTED (bar1) when price was above the 200-EMA.
        df["bar1_above_ema200"] = df["close"].shift(2) > df["ema200"].shift(2)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "tbc_signal" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
        )
        min_score = float(signals_cfg.confluence.min_score)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # Pattern weight
        pattern_weight = 2.0
        for p in signals_cfg.patterns:
            if p.id == "three_black_crows" and p.enabled:
                pattern_weight = p.weight
                break

        # ATR min filter
        atr_min = float(getattr(filters, "atr_min_pct", 0.003) or 0.003)

        out: list[Signal] = []

        for i in range(len(df)):
            row = df.iloc[i]

            # Pattern must fire
            if not bool(row.get("tbc_signal", False)):
                continue

            # ATR filter
            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue
            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr_min > 0 and atr_pct < atr_min:
                continue

            close = float(row["close"])

            # 200-EMA filter: Bar1 (t-2) must be above 200-EMA.
            # The pattern represents distribution at the TOP — the sell-off started
            # when price was above the 200-EMA. By bar3 close it may already be
            # slightly below, but the context (top distribution) is still valid.
            if self.manifest.trend_filter.required:
                bar1_above = bool(row.get("bar1_above_ema200", False))
                if not bar1_above:
                    continue

            # Score
            score = pattern_weight
            if score < min_score:
                continue

            # SL = Bar1 high (t-2 bar high)
            sl_price = float(row.get("tbc_stop") or (close + 2.0 * atr))
            if np.isnan(sl_price) or sl_price <= 0:
                sl_price = close + 2.0 * atr
            # Ensure SL is above close (short trade)
            sl_price = max(sl_price, close + 0.5 * atr)

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
                pattern_id="three_black_crows",
                confluence_score=float(score),
                sl_price=float(sl_price),
                tp_price=float(tp_price),
                suggested_size_atr=1.0,
                metadata={
                    "atr14": atr,
                    "ema200": float(row.get("ema200") or 0.0),
                    "vol_z": float(row.get("vol_z") or 0.0),
                    "close": close,
                },
            )
            out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("three_black_crows.signals.generated")
        return out
