"""Three White Soldiers / Three Black Crows stratejisi.

Bulkowski rank: 3/103  — %82 continuation rate (en yuksek 3-bar pattern)
Mirror: Three Black Crows (short taraf, %78 continuation rate, rank 7/103)

Pattern (mekanik):
  THREE WHITE SOLDIERS (long):
    1. 3 ardisik bullish bar
    2. Her bar bir oncekinin close'unu asar (HH kapanislar dizisi)
    3. Her bar govde >= %50 bar range'i (trend bar)
    4. Ust golge <= %20 bar range'i (minimal upper shadow)
    5. Volume artiyor (her bar onceki bar ortalamasindan yuksek)

  THREE BLACK CROWS (short mirror):
    1. 3 ardisik bearish bar
    2. Her bar bir oncekinin close'unu asan dusus (LL kapanislar)
    3. Her bar govde >= %50 bar range'i
    4. Alt golge <= %20 bar range'i (minimal lower shadow)
    5. Volume artiyor

Giris  : Pattern barinin (Bar 3) kapanisindan sonraki bar acilisinda
Stop   : Bar 1'in low'u (long) / Bar 1'in high'i (short)
Hedef  : 1.5R (overextension riski nedeniyle Bulkowski H-C2 onerisi)
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
    _rolling_sharpe,
)


# =====================================================================
# Pattern detection helpers
# =====================================================================

def _three_white_soldiers(
    df: pd.DataFrame,
    body_ratio_min: float = 0.50,
    upper_shadow_max: float = 0.20,
    volume_increasing: bool = True,
    vol_lookback: int = 10,
) -> pd.Series:
    """Three White Soldiers pattern — lookahead-free.

    Dondurulmus indeksler: t bari icin (t-2, t-1, t) uclisi test edilir.
    shift() ile gecmis bilgi kullanilir; hicbir gelecek bilgi yok.

    Returns boolean Series indexed on df.index.
    """
    o = df["open"]
    h = df["high"]
    l = df["low"]
    c = df["close"]
    vol = df["volume"]

    # Bar 2 ve 3 icin Bar N = gecerli, Bar N-1 = shift(1), Bar N-2 = shift(2)
    rng0 = (h - l).replace(0, np.nan)          # Bar t (bar 3)
    rng1 = (h.shift(1) - l.shift(1)).replace(0, np.nan)   # Bar t-1 (bar 2)
    rng2 = (h.shift(2) - l.shift(2)).replace(0, np.nan)   # Bar t-2 (bar 1)

    body0 = (c - o)                             # Pozitif ise bullish
    body1 = (c.shift(1) - o.shift(1))
    body2 = (c.shift(2) - o.shift(2))

    # Kural 1: 3 ardisik bullish bar
    bull0 = body0 > 0
    bull1 = body1 > 0
    bull2 = body2 > 0
    all_bullish = bull0 & bull1 & bull2

    # Kural 2: HH kapanislar — her bar oncekinin close'unu asar
    hh_closes = (c > c.shift(1)) & (c.shift(1) > c.shift(2))

    # Kural 3: Govde >= %50 range (trend bar)
    body_ok0 = body0.abs() >= body_ratio_min * rng0
    body_ok1 = body1.abs() >= body_ratio_min * rng1
    body_ok2 = body2.abs() >= body_ratio_min * rng2
    all_body_ok = body_ok0 & body_ok1 & body_ok2

    # Kural 4: Ust golge <= %20 range (minimal upper shadow)
    upper_shadow0 = (h - c).clip(lower=0)
    upper_shadow1 = (h.shift(1) - c.shift(1)).clip(lower=0)
    upper_shadow2 = (h.shift(2) - c.shift(2)).clip(lower=0)
    shadow_ok0 = upper_shadow0 <= upper_shadow_max * rng0
    shadow_ok1 = upper_shadow1 <= upper_shadow_max * rng1
    shadow_ok2 = upper_shadow2 <= upper_shadow_max * rng2
    all_shadow_ok = shadow_ok0 & shadow_ok1 & shadow_ok2

    # Kural 5: Volume artiyor (her bar onceki rolling ortalamadan yuksek)
    if volume_increasing:
        vol_avg = vol.shift(1).rolling(vol_lookback, min_periods=3).mean()
        vol_ok = (
            (vol > vol_avg)
            & (vol.shift(1) > vol.shift(2).rolling(vol_lookback, min_periods=3).mean())
        )
    else:
        vol_ok = pd.Series(True, index=df.index)

    pattern = all_bullish & hh_closes & all_body_ok & all_shadow_ok & vol_ok
    return pattern.fillna(False)


def _three_black_crows(
    df: pd.DataFrame,
    body_ratio_min: float = 0.50,
    lower_shadow_max: float = 0.20,
    volume_increasing: bool = True,
    vol_lookback: int = 10,
) -> pd.Series:
    """Three Black Crows pattern — mirror of Three White Soldiers (short).

    Lookahead-free.
    """
    o = df["open"]
    h = df["high"]
    l = df["low"]
    c = df["close"]
    vol = df["volume"]

    rng0 = (h - l).replace(0, np.nan)
    rng1 = (h.shift(1) - l.shift(1)).replace(0, np.nan)
    rng2 = (h.shift(2) - l.shift(2)).replace(0, np.nan)

    body0 = (o - c)          # Pozitif ise bearish (open > close)
    body1 = (o.shift(1) - c.shift(1))
    body2 = (o.shift(2) - c.shift(2))

    # Kural 1: 3 ardisik bearish bar
    bear0 = body0 > 0
    bear1 = body1 > 0
    bear2 = body2 > 0
    all_bearish = bear0 & bear1 & bear2

    # Kural 2: LL kapanislar — her bar oncekinden dusuk close
    ll_closes = (c < c.shift(1)) & (c.shift(1) < c.shift(2))

    # Kural 3: Govde >= %50 range
    body_ok0 = body0.abs() >= body_ratio_min * rng0
    body_ok1 = body1.abs() >= body_ratio_min * rng1
    body_ok2 = body2.abs() >= body_ratio_min * rng2
    all_body_ok = body_ok0 & body_ok1 & body_ok2

    # Kural 4: Alt golge <= %20 range (minimal lower shadow)
    lower_shadow0 = (c - l).clip(lower=0)
    lower_shadow1 = (c.shift(1) - l.shift(1)).clip(lower=0)
    lower_shadow2 = (c.shift(2) - l.shift(2)).clip(lower=0)
    shadow_ok0 = lower_shadow0 <= lower_shadow_max * rng0
    shadow_ok1 = lower_shadow1 <= lower_shadow_max * rng1
    shadow_ok2 = lower_shadow2 <= lower_shadow_max * rng2
    all_shadow_ok = shadow_ok0 & shadow_ok1 & shadow_ok2

    # Kural 5: Volume artiyor
    if volume_increasing:
        vol_avg = vol.shift(1).rolling(vol_lookback, min_periods=3).mean()
        vol_ok = (
            (vol > vol_avg)
            & (vol.shift(1) > vol.shift(2).rolling(vol_lookback, min_periods=3).mean())
        )
    else:
        vol_ok = pd.Series(True, index=df.index)

    pattern = all_bearish & ll_closes & all_body_ok & all_shadow_ok & vol_ok
    return pattern.fillna(False)


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "three_white_soldiers",
        "version": "1.0.0",
        "description": (
            "Three White Soldiers (long) + Three Black Crows (short). "
            "Bulkowski rank 3/103 — %82 continuation rate."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "three_white_soldiers",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_min": 0.50,
                        "upper_shadow_max": 0.20,
                        "volume_increasing": True,
                        "vol_lookback": 10,
                    },
                },
                {
                    "id": "three_black_crows",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_min": 0.50,
                        "lower_shadow_max": 0.20,
                        "volume_increasing": True,
                        "vol_lookback": 10,
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
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.15,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "pattern_extreme", "swing_lookback": 3},
            "take_profit": {"method": "r_multiple", "primary_R": 1.5},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class ThreeWhiteSoldiersStrategy(Strategy):
    """Three White Soldiers (long) + Three Black Crows (short).

    Bulkowski #3 pattern — %82 continuation rate.
    Stop: Bar 1 extreme (low for longs, high for shorts)
    Target: 1.5R (conservative due to overextension risk)
    """

    name = "three_white_soldiers"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # EMAs
        df["ema20"] = _ema(df["close"], 20)
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)

        # ATR
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Volume z-score (60 bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Pattern params
        tws_cfg = {}
        tbc_cfg = {}
        for p in self.manifest.signals.patterns:
            if p.id == "three_white_soldiers":
                tws_cfg = p.params
            elif p.id == "three_black_crows":
                tbc_cfg = p.params

        # Three White Soldiers flag
        df["tws_signal"] = _three_white_soldiers(
            df,
            body_ratio_min=float(tws_cfg.get("body_ratio_min", 0.50)),
            upper_shadow_max=float(tws_cfg.get("upper_shadow_max", 0.20)),
            volume_increasing=bool(tws_cfg.get("volume_increasing", True)),
            vol_lookback=int(tws_cfg.get("vol_lookback", 10)),
        )

        # Three Black Crows flag
        df["tbc_signal"] = _three_black_crows(
            df,
            body_ratio_min=float(tbc_cfg.get("body_ratio_min", 0.50)),
            lower_shadow_max=float(tbc_cfg.get("lower_shadow_max", 0.20)),
            volume_increasing=bool(tbc_cfg.get("volume_increasing", True)),
            vol_lookback=int(tbc_cfg.get("vol_lookback", 10)),
        )

        # Stop levels: Bar 1 extreme (2 bars ago)
        # For long (TWS): stop at low of bar 1 (shift(2))
        df["tws_stop"] = df["low"].shift(2)
        # For short (TBC): stop at high of bar 1 (shift(2))
        df["tbc_stop"] = df["high"].shift(2)

        # Kaufman ER
        er_period = int(
            getattr(self.manifest.signals.filters, "kaufman_er_period", 14) or 14
        )
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Rolling Sharpe
        df["rolling_sharpe"] = _rolling_sharpe(df["close"], period=60)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "tws_signal" not in df.columns:
            df = self.prepare_features(df)

        filters = self.manifest.signals.filters
        confluence = self.manifest.signals.confluence

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 1.5)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        atr_min = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)
        er_min = float(getattr(filters, "kaufman_er_min", 0.15) or 0.15)
        min_score = float(confluence.min_score)

        # Pattern weights
        tws_weight = 2.0
        tbc_weight = 2.0
        for p in self.manifest.signals.patterns:
            if not p.enabled:
                continue
            if p.id == "three_white_soldiers":
                tws_weight = p.weight
            elif p.id == "three_black_crows":
                tbc_weight = p.weight

        out: list[Signal] = []
        for i in range(len(df)):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue

            # ATR pct filter
            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr_min > 0 and atr_pct < atr_min:
                continue

            # Kaufman ER filter
            er = float(row.get("kaufman_er") or 0.0)
            if er_min > 0 and er < er_min:
                continue

            # --- Three White Soldiers (LONG) ---
            if bool(row.get("tws_signal", False)):
                score = tws_weight
                if score >= min_score:
                    sl_price = float(row.get("tws_stop") or (close - 3.0 * atr))
                    if np.isnan(sl_price) or sl_price <= 0 or sl_price >= close:
                        sl_price = close - 3.0 * atr
                    # Ensure at least 0.5 ATR below close
                    sl_price = min(sl_price, close - 0.5 * atr)
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
                        pattern_id="three_white_soldiers",
                        confluence_score=score,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        suggested_size_atr=1.0,
                        metadata={
                            "atr14": atr,
                            "kaufman_er": er,
                            "ema50": float(row.get("ema50") or 0.0),
                            "bar1_low_stop": float(row.get("tws_stop") or 0.0),
                        },
                    )
                    out.append(sig)

            # --- Three Black Crows (SHORT) ---
            if bool(row.get("tbc_signal", False)):
                score = tbc_weight
                if score >= min_score:
                    sl_price = float(row.get("tbc_stop") or (close + 3.0 * atr))
                    if np.isnan(sl_price) or sl_price <= 0 or sl_price <= close:
                        sl_price = close + 3.0 * atr
                    # Ensure at least 0.5 ATR above close
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
                        confluence_score=score,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        suggested_size_atr=1.0,
                        metadata={
                            "atr14": atr,
                            "kaufman_er": er,
                            "ema50": float(row.get("ema50") or 0.0),
                            "bar1_high_stop": float(row.get("tbc_stop") or 0.0),
                        },
                    )
                    out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("three_white_soldiers.signals.generated")
        return out
