"""Volume Expansion stratejisi.

Hipotez:
  - Gunluk hacim, son 60-bar (uzun pencere) medyaninin >=1.5x'i
  - Bar yonu (bullish/bearish) yonunde devam eder (trend continuation)
  - "Smart money" kurumsal absorbsiyon barlari yaratir, momentum izleyici
    olarak takip edersek edge yakalanir.

Lookahead-bias-free:
  - Volume z-score icin shift(1) ile [t-60..t-1] kullanilir.
  - Median benchmark t bar'in HACMI olmadan hesaplanir (causal).

Cooldown:
  - Ayni sembol + ayni yon icin 5 gun cooldown (over-trade onleme).

Trend filtresi:
  - 200-EMA: long sadece close>EMA200, short sadece close<EMA200.

Entry: bar N+1 acilis (sec11e parite icin manifest.execution.decision_after_close).
SL   : structural swing low/high (10-bar) + atr_buffer * ATR
TP   : 2R primary (engine multi-target ile 1R partial + runner trail)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema


def _swing_sl(df: pd.DataFrame, direction: str, lookback: int = 10) -> pd.Series:
    """Structural stop: lookahead-free swing low/high."""
    if direction == "long":
        return df["low"].shift(1).rolling(lookback, min_periods=1).min()
    return df["high"].shift(1).rolling(lookback, min_periods=1).max()


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "volume_expansion",
        "version": "1.0.0",
        "description": (
            "Volume Expansion Continuation: daily volume >= 1.5x 60-bar median, "
            "trend-aligned bullish/bearish bar -> direction continuation"
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "vol_exp_bull",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "vol_lookback": 60,
                        "vol_multiplier": 1.5,
                        "body_min_range_pct": 0.50,  # genis body ister (kucuk doji elenir)
                        "min_close_above_ema50": True,
                    },
                },
                {
                    "id": "vol_exp_bear",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "vol_lookback": 60,
                        "vol_multiplier": 1.5,
                        "body_min_range_pct": 0.50,
                        "min_close_below_ema50": True,
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
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {
                "method": "structural_atr",
                "swing_lookback": 10,
                "atr_buffer": 0.5,
            },
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {
                "method": "fixed_fractional",
                "risk_per_trade": 0.01,
            },
        },
    }
    return StrategyManifest.model_validate(raw)


class VolumeExpansionStrategy(Strategy):
    """Volume Expansion Continuation — uzun pencere hacim normalizasyonu.

    Long:
      - close > EMA50 ve close > EMA200 (trend up)
      - volume[t] >= vol_multiplier * median(volume[t-vol_lookback:t])
      - bullish bar (close > open)
      - body / total_range >= body_min_range_pct (ciddi body)

    Short:
      - close < EMA50 ve close < EMA200
      - volume[t] >= vol_multiplier * median(volume[t-vol_lookback:t])
      - bearish bar (close < open)
      - body / total_range >= body_min_range_pct

    Lookahead-free: median t bar'in hacmi DAHIL olmadan hesaplanir
    (shift(1) ile [t-vol_lookback..t-1]).

    SL: structural swing (10-bar) +/- atr_buffer * ATR
    TP: primary_R * risk (engine'de multi-target overlay var)
    """

    name = "volume_expansion"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # Indicators
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # --- Param extract ---
        vol_lookback = 60
        vol_multiplier = 1.5
        body_min = 0.50
        for p in self.manifest.signals.patterns:
            if p.id in ("vol_exp_bull", "vol_exp_bear"):
                vol_lookback = int(p.params.get("vol_lookback", 60))
                vol_multiplier = float(p.params.get("vol_multiplier", 1.5))
                body_min = float(p.params.get("body_min_range_pct", 0.50))
                break

        # --- LOOKAHEAD-FREE volume median (shift(1) ile t bar haric) ---
        vol_shifted = df["volume"].shift(1)
        df["vol_median_60"] = vol_shifted.rolling(
            vol_lookback, min_periods=20
        ).median()
        df["vol_ratio"] = df["volume"] / df["vol_median_60"].replace(0.0, np.nan)
        df["vol_expansion"] = df["vol_ratio"] >= vol_multiplier

        # --- Body filter ---
        body_abs = (df["close"] - df["open"]).abs()
        rng = (df["high"] - df["low"]).replace(0.0, np.nan)
        df["body_ratio"] = body_abs / rng
        df["body_ok"] = df["body_ratio"] >= body_min

        # --- Direction flags ---
        df["bull_bar"] = df["close"] > df["open"]
        df["bear_bar"] = df["close"] < df["open"]

        # --- Structural SL ---
        swing_lookback = int(
            self.manifest.risk.get("stop_loss", {}).get("swing_lookback", 10)
        )
        df["struct_sl_long"] = _swing_sl(df, "long", lookback=swing_lookback)
        df["struct_sl_short"] = _swing_sl(df, "short", lookback=swing_lookback)

        # --- Volume z-score (genel filter) ---
        vmean = vol_shifted.rolling(60, min_periods=10).mean()
        vstd = vol_shifted.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (df["volume"] - vmean) / vstd.replace(0.0, np.nan)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "vol_expansion" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters_cfg = signals_cfg.filters
        confluence = signals_cfg.confluence

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
        )
        atr_buffer = float(
            self.manifest.risk.get("stop_loss", {}).get("atr_buffer", 0.5)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        bull_weight = 1.5
        bear_weight = 1.5
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "vol_exp_bull":
                bull_weight = p.weight
            elif p.id == "vol_exp_bear":
                bear_weight = p.weight

        atr_min = float(getattr(filters_cfg, "atr_min_pct", 0.005) or 0.005)
        min_score = float(confluence.min_score)

        out: list[Signal] = []
        n = len(df)

        for i in range(n):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue
            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr_min > 0 and atr_pct < atr_min:
                continue

            if not bool(row.get("vol_expansion", False)):
                continue
            if not bool(row.get("body_ok", False)):
                continue

            ema50 = float(row.get("ema50") or 0.0)
            ema200 = float(row.get("ema200") or 0.0)
            if ema50 <= 0 or ema200 <= 0:
                continue

            ts_val = pd.Timestamp(row["ts"]).to_pydatetime()
            sl_long = float(row.get("struct_sl_long") or np.nan)
            sl_short = float(row.get("struct_sl_short") or np.nan)

            # ---- LONG ----
            if bool(row.get("bull_bar", False)):
                if close <= ema200 or close <= ema50:
                    pass  # trend filter elendi
                else:
                    score = bull_weight
                    if score >= min_score:
                        if np.isnan(sl_long) or sl_long <= 0:
                            sl_price = close - 2.0 * atr
                        else:
                            sl_price = sl_long - atr_buffer * atr
                        sl_price = min(sl_price, close - 0.5 * atr)
                        if sl_price <= 0:
                            continue
                        risk = close - sl_price
                        if risk <= 0:
                            continue
                        tp_price = close + primary_R * risk
                        sig = self.emit_signal(
                            ts=ts_val,
                            venue=venue,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="long",
                            pattern_id="vol_exp_bull",
                            confluence_score=float(score),
                            sl_price=float(sl_price),
                            tp_price=float(tp_price),
                            suggested_size_atr=1.0,
                            metadata={
                                "vol_ratio": float(row.get("vol_ratio") or 0.0),
                                "body_ratio": float(row.get("body_ratio") or 0.0),
                                "atr14": atr,
                                "ema50": ema50,
                                "ema200": ema200,
                                "vol_z": float(row.get("vol_z") or 0.0),
                            },
                        )
                        out.append(sig)
                continue  # bullish bar ise short denemiyoruz

            # ---- SHORT ----
            if bool(row.get("bear_bar", False)):
                if close >= ema200 or close >= ema50:
                    continue
                score = bear_weight
                if score < min_score:
                    continue
                if np.isnan(sl_short) or sl_short <= 0:
                    sl_price = close + 2.0 * atr
                else:
                    sl_price = sl_short + atr_buffer * atr
                sl_price = max(sl_price, close + 0.5 * atr)
                risk = sl_price - close
                if risk <= 0:
                    continue
                tp_price = close - primary_R * risk
                if tp_price <= 0:
                    continue
                sig = self.emit_signal(
                    ts=ts_val,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="short",
                    pattern_id="vol_exp_bear",
                    confluence_score=float(score),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "vol_ratio": float(row.get("vol_ratio") or 0.0),
                        "body_ratio": float(row.get("body_ratio") or 0.0),
                        "atr14": atr,
                        "ema50": ema50,
                        "ema200": ema200,
                        "vol_z": float(row.get("vol_z") or 0.0),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=n).info("volume_expansion.signals.generated")
        return out
