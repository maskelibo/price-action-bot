"""Brooks ii (Inside-Inside) Breakout stratejisi.

Kavram:
  Iki ardisik inside bar = volatility compression (sıkısma).
  Sıkısma sonrasi breakout guclü continuation sinyali uretir.

Mekanik pattern (Bar A-B-C-D modeli):
  Bar A: Konteyner bar (trend bar, buyuk range)
  Bar B: Inside bar of A  => B.high < A.high  AND  B.low > A.low
  Bar C: Inside bar of B  => C.high < B.high  AND  C.low > B.low
  Bar D: Breakout bar
          Long  => D.close > A.high
          Short => D.close < A.low

Giris ve risk (task spec):
  Entry : Bar D kapanisi (veya D sonraki bar acilisi)
  SL    : A range opposite end + 0.5 * ATR14
  TP    : 2R

Trend filtresi (opsiyonel, varsayilan aktif):
  50-EMA yonu -- long sinyali icin close > EMA50, short icin close < EMA50.

Brooks referanslari (brooks_deep_catalog.md):
  - ii (Inside-Inside) Konsolidasyon Breakout -- Bolum 3
  - Win rate trend yonunde ~%60-65; stop dar, R:R 3:1+
  - "ii setup gives tight stop = best mechanical R:R"
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
    _kaufman_efficiency_ratio,
    _always_in_flags,
    _rolling_sharpe,
)


# =====================================================================
# Pattern detectors
# =====================================================================

def _ii_pattern(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """ii (Inside-Inside) pattern tespiti.

    Bar A: df.iloc[i-2]  (konteyner)
    Bar B: df.iloc[i-1]  (inside of A)
    Bar C: df.iloc[i]    (inside of B -- sinyal bari)

    Dondurulenler (her biri lookahead-free):
      ii_long_setup  : Bar C kapanisi sonrasi A.high kirilirsa long
      ii_short_setup : Bar C kapanisi sonrasi A.low  kirilirsa short
      a_high / a_low : Container bar A'nin extreme'leri (SL/TP icin)

    Lookahead: Tum hesaplamalar shift(1) ve shift(2) ile gecmis bar bilgisini
               kullanir. Bar C (i) kapandiktan *sonra* sinyal olusur;
               entry bar i+1 acilisinda olur (veya D kapanisinda).
    """
    high = df["high"]
    low  = df["low"]

    # A = 2 bar once, B = 1 bar once, C = simdi
    a_high = high.shift(2)
    a_low  = low.shift(2)
    b_high = high.shift(1)
    b_low  = low.shift(1)
    c_high = high
    c_low  = low

    # B inside of A
    b_in_a = (b_high < a_high) & (b_low > a_low)

    # C inside of B
    c_in_b = (c_high < b_high) & (c_low > b_low)

    # ii tamamlandi
    ii_complete = b_in_a & c_in_b

    # Breakout: D bar'i (i+1) breakout yaparsa sinyal alinir.
    # D kapanisi icin: close.shift(-1) > a_high (lookahead olur).
    # Bunun yerine, bar C kapaninca hem long hem short setup hazir;
    # Bar D bizi A.high veya A.low disina cikarirsa entry tetiklenir.
    # generate_signals icerisinde D = current bar olarak islenir:
    # ii_complete.shift(1) => bir onceki barda ii tamamlandi, D bari biz oluyoruz.

    return ii_complete, a_high, a_low


def _ii_breakout_flags(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Bar D breakout tespit et.

    ii_complete.shift(1): bir onceki barda ii tamamlandi (A/B/C hazir).
    Bar D (current bar):
      long  => close > prev_a_high (A.high kırıldı)
      short => close < prev_a_low

    Dondurulenler:
      long_breakout  : D bari long breakout
      short_breakout : D bari short breakout
      a_high_prev    : Entry/SL hesaplamalari icin A.high
      a_low_prev     : Entry/SL hesaplamalari icin A.low
    """
    ii_complete, a_high, a_low = _ii_pattern(df)

    # ii_complete biz bar C idi. Simdi bar D bakiyoruz => shift(1)
    ii_setup     = ii_complete.shift(1).fillna(False)
    a_high_prev  = a_high.shift(1)   # A.high, ii tamamlandigi andan bir bar once => 3 bar once
    a_low_prev   = a_low.shift(1)

    close = df["close"]

    long_breakout  = ii_setup & (close > a_high_prev)
    short_breakout = ii_setup & (close < a_low_prev)

    return (
        long_breakout.fillna(False),
        short_breakout.fillna(False),
        a_high_prev.fillna(np.nan),
        a_low_prev.fillna(np.nan),
    )


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "ii_breakout",
        "version": "1.0.0",
        "description": "Brooks ii (Inside-Inside) Breakout -- volatility compression continuation",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "ii_long_breakout",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {},
                },
                {
                    "id": "ii_short_breakout",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {},
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
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.0,
                "always_in_required": False,
                "bear_regime_size_factor": 1.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {
                "method": "a_range_opposite",
                "sl_atr_buffer": 0.5,
            },
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 50,
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class IIBreakoutStrategy(Strategy):
    """Brooks ii (Inside-Inside) Breakout strateji implementasyonu.

    Pattern:
      A -> B (inside A) -> C (inside B) -> D (breakout of A range)

    Entry    : Bar D kapanisinda (breakout confirm edilmis)
    SL long  : A.low  - 0.5 * ATR14
    SL short : A.high + 0.5 * ATR14
    TP       : 2R
    """

    name = "ii_breakout"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # EMA
        df["ema50"]  = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)

        # ATR
        df["atr14"]    = _atr(df, 14)
        df["atr_pct"]  = df["atr14"] / df["close"]

        # Volume z-score (60 bar)
        vol   = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd  = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Kaufman ER
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=14)

        # Brooks always-in flags
        long_ai, short_ai = _always_in_flags(df, n_confirm=3)
        df["always_in_long"]  = long_ai
        df["always_in_short"] = short_ai

        # Rolling Sharpe
        df["rolling_sharpe"] = _rolling_sharpe(df["close"], period=60)

        # ii pattern + breakout flags
        long_bo, short_bo, a_high, a_low = _ii_breakout_flags(df)
        df["ii_long_breakout"]  = long_bo
        df["ii_short_breakout"] = short_bo
        df["ii_a_high"]         = a_high   # Container bar A'nin high'i
        df["ii_a_low"]          = a_low    # Container bar A'nin low'u

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "ii_long_breakout" not in df.columns:
            df = self.prepare_features(df)

        filters    = self.manifest.signals.filters
        risk_cfg   = self.manifest.risk
        primary_R  = float(risk_cfg.get("take_profit", {}).get("primary_R", 2.0))
        sl_atr_buf = float(risk_cfg.get("stop_loss", {}).get("sl_atr_buffer", 0.5))

        venue     = str(df["venue"].iloc[0])     if "venue"     in df.columns else "unknown"
        symbol    = str(df["symbol"].iloc[0])    if "symbol"    in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # ---- ATR min filter mask ----
        atr_min  = float(getattr(filters, "atr_min_pct", 0.003) or 0.003)
        atr_ok   = df["atr_pct"] >= atr_min if atr_min > 0 else pd.Series(True, index=df.index)

        # ---- Trend filter (50-EMA) ----
        trend_required = self.manifest.trend_filter.required
        up_trend   = df["close"] > df["ema50"]
        down_trend = df["close"] < df["ema50"]

        # ---- Build signal rows ----
        out: list[Signal] = []

        for i in range(len(df)):
            row   = df.iloc[i]
            close = float(row["close"])
            atr   = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue
            if not bool(atr_ok.iat[i]):
                continue

            a_high_val = float(row.get("ii_a_high") or np.nan)
            a_low_val  = float(row.get("ii_a_low")  or np.nan)
            if np.isnan(a_high_val) or np.isnan(a_low_val):
                continue

            # --- Long breakout ---
            if bool(row.get("ii_long_breakout", False)):
                if trend_required and not bool(up_trend.iat[i]):
                    pass  # trend filtresi reddetti
                else:
                    # SL = A.low - sl_atr_buf * ATR
                    sl_price = a_low_val - sl_atr_buf * atr
                    sl_price = min(sl_price, close - 0.5 * atr)  # en az 0.5 ATR altta
                    risk     = close - sl_price
                    if risk <= 0:
                        continue
                    tp_price = close + primary_R * risk

                    ts  = pd.Timestamp(row["ts"]).to_pydatetime()
                    sig = self.emit_signal(
                        ts=ts,
                        venue=venue,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="long",
                        pattern_id="ii_long_breakout",
                        confluence_score=1.0,
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=1.0,
                        metadata={
                            "atr14":    atr,
                            "a_high":   a_high_val,
                            "a_low":    a_low_val,
                            "ema50":    float(row.get("ema50") or 0.0),
                        },
                    )
                    out.append(sig)

            # --- Short breakout ---
            if bool(row.get("ii_short_breakout", False)):
                if trend_required and not bool(down_trend.iat[i]):
                    pass  # trend filtresi reddetti
                else:
                    # SL = A.high + sl_atr_buf * ATR
                    sl_price = a_high_val + sl_atr_buf * atr
                    sl_price = max(sl_price, close + 0.5 * atr)
                    risk     = sl_price - close
                    if risk <= 0:
                        continue
                    tp_price = close - primary_R * risk

                    ts  = pd.Timestamp(row["ts"]).to_pydatetime()
                    sig = self.emit_signal(
                        ts=ts,
                        venue=venue,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="short",
                        pattern_id="ii_short_breakout",
                        confluence_score=1.0,
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=1.0,
                        metadata={
                            "atr14":    atr,
                            "a_high":   a_high_val,
                            "a_low":    a_low_val,
                            "ema50":    float(row.get("ema50") or 0.0),
                        },
                    )
                    out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("ii_breakout.signals.generated")
        return out
