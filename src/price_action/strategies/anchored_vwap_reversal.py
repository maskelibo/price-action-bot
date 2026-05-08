"""Anchored VWAP + Volume Profile POC Reversal stratejisi.

Strateji konsepti:
  - AVWAP: belirli bir anchor bar'dan (HTF swing low/high) itibaren hesaplanan
    hacim-agirlikli ortalama fiyat.  Kurumsal algoritmalar bu noktayi referans
    alir — Harris (2003) "value traders" absorpsiyon hipotezi.
  - POC (Point of Control): son N barin volume profile'inda en yuksek hacimli
    fiyat bolgesi.  Bu seviye kurumsal "fair value" gorusunu yansitir.
  - Entry: fiyat AVWAP'a yukari donuste (long) veya asagi donuste (short)
    yaklasirken POC confluance'i varsa sinyal uretilir.
  - Karakter: mean-reversion — engulfing_continuation trend-following ile
    dekorelasyon saglar (Kaufman portfolio diversification ilkesi).

Kural ozeti:
  Long:
    - close > ema200  (uzun vadeli bias yukari)
    - avwap_long (swing-low anchor) mevcut
    - price crosses AVWAP from below (body rejection up)
    - POC yakinda: |close - poc| <= 1.5 * ATR14
    - RSI14 < 55 (overbought degil)
  Short: simetrik (swing-high anchor, price crosses AVWAP from above, RSI > 45)
  SL  : structural swing low/high - 1.0 * ATR (buffer)
  TP  : 2R

Manifest yoksa dahili default kullanilir.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# Paylasilmis yardimcilar (engulfing_continuation ile ortak kaynak)
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
    _fractal_swings,
)


# =====================================================================
# AVWAP + POC yardimcilari
# =====================================================================

def _anchored_vwap(df: pd.DataFrame, anchor_idx: int) -> pd.Series:
    """Anchor bar'dan itibaren kumulatif hacim-agirlikli ortalama fiyat.

    Formul (Wikipedia kaynaklı):
      AVWAP_t = Σ_{i=anchor}^{t} (typical_price_i * volume_i)
                / Σ_{i=anchor}^{t} volume_i
      typical_price = (high + low + close) / 3

    Lookahead-free: t aninda sadece [anchor..t] araligi kullanilir.
    Anchor_idx cari bar'dan once olmali (t-1 veya daha eski).
    Eger anchor_idx >= len(df) veya negatif ise NaN serisi doner.
    """
    n = len(df)
    if anchor_idx < 0 or anchor_idx >= n:
        return pd.Series(np.nan, index=df.index)

    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].clip(lower=0.0)

    cum_tpv = np.zeros(n)
    cum_vol = np.zeros(n)

    for i in range(anchor_idx, n):
        if i == anchor_idx:
            cum_tpv[i] = typical.iat[i] * vol.iat[i]
            cum_vol[i] = vol.iat[i]
        else:
            cum_tpv[i] = cum_tpv[i - 1] + typical.iat[i] * vol.iat[i]
            cum_vol[i] = cum_vol[i - 1] + vol.iat[i]

    with np.errstate(invalid="ignore", divide="ignore"):
        avwap_arr = np.where(cum_vol > 0, cum_tpv / cum_vol, np.nan)

    result = pd.Series(avwap_arr, index=df.index, dtype=float)
    # anchor oncesi NaN
    result.iloc[:anchor_idx] = np.nan
    return result


def _volume_profile_poc(df: pd.DataFrame, lookback: int = 60, n_buckets: int = 50) -> pd.Series:
    """Son `lookback` barin volume profile'indan Point of Control (POC) hesapla.

    Lookahead-free: t bari icin [t-lookback .. t-1] (shift ile) kullanilir.

    Algoritma:
      1. Son lookback bar'in low-high araligini 50 fiyat bucket'ina bol.
      2. Her bucket icin toplam volume hesapla (bar tamamen bucket icerisindeyse).
      3. En yuksek volume'lu bucket'in merkez fiyati POC'tur.

    Returns: pd.Series — her bar icin o anda hesaplanan POC degeri.
    """
    n = len(df)
    poc_vals = np.full(n, np.nan)

    lows = df["low"].values
    highs = df["high"].values
    vols = df["volume"].values

    for t in range(lookback, n):
        # Lookback penceresi: [t-lookback .. t-1] — lookahead yok
        start = t - lookback
        end = t  # pandas slice exclusive, so [start:end] = [t-lookback..t-1]
        w_low = lows[start:end]
        w_high = highs[start:end]
        w_vol = vols[start:end]

        price_min = np.nanmin(w_low)
        price_max = np.nanmax(w_high)
        if price_max <= price_min or np.isnan(price_min) or np.isnan(price_max):
            poc_vals[t] = np.nan
            continue

        edges = np.linspace(price_min, price_max, n_buckets + 1)
        bucket_vol = np.zeros(n_buckets)

        for bi in range(n_buckets):
            b_lo = edges[bi]
            b_hi = edges[bi + 1]
            # Bar bu bucket ile overlaps mi?
            # Overlap: bar_high >= b_lo AND bar_low <= b_hi
            mask = (w_high >= b_lo) & (w_low <= b_hi)
            bucket_vol[bi] = np.nansum(w_vol[mask])

        if bucket_vol.max() == 0:
            poc_vals[t] = (price_min + price_max) / 2.0
        else:
            best_bucket = int(np.argmax(bucket_vol))
            poc_vals[t] = (edges[best_bucket] + edges[best_bucket + 1]) / 2.0

    return pd.Series(poc_vals, index=df.index, dtype=float)


def _rolling_avwap_from_swing(
    df: pd.DataFrame,
    swing_col: str,
    lookback: int = 60,
) -> pd.Series:
    """Her t bari icin son lookback barda en son swing anchor'dan AVWAP.

    swing_col: 'swing_low' veya 'swing_high' — fractal swing serisi.
    Lookahead-free: t aninda [t-lookback..t-1] araliginda son swing noktasi
    anchor olarak alinir; eger yoksa NaN.
    """
    n = len(df)
    avwap_vals = np.full(n, np.nan)
    swing_arr = df[swing_col].values
    typical = ((df["high"] + df["low"] + df["close"]) / 3.0).values
    vol = df["volume"].clip(lower=0.0).values

    for t in range(lookback, n):
        # Son lookback barda en son swing bul (t dahil degil = t-1'e kadar)
        anchor_idx = -1
        # Geriye dogru ara — en yakin (en son) swing
        for i in range(t - 1, max(t - lookback - 1, -1), -1):
            if not np.isnan(swing_arr[i]) and swing_arr[i] > 0:
                anchor_idx = i
                break
        if anchor_idx < 0:
            continue
        # AVWAP'i anchor_idx'ten t'ye kadar hesapla (t dahil)
        cum_tpv = 0.0
        cum_vol = 0.0
        for i in range(anchor_idx, t + 1):
            v = vol[i]
            cum_vol += v
            cum_tpv += typical[i] * v
        if cum_vol > 0:
            avwap_vals[t] = cum_tpv / cum_vol

    return pd.Series(avwap_vals, index=df.index, dtype=float)


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI hesapla. Lookahead-free."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "anchored_vwap_reversal",
        "version": "1.0.0",
        "description": "Anchored VWAP + POC mean-reversion with 200-EMA bias",
        "trend_filter": {"type": "ema", "period": 200, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "avwap_long_reversal",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "poc_atr_tolerance": 1.5,
                        "rsi_long_max": 55.0,
                        "avwap_swing_lookback": 60,
                        "poc_lookback": 60,
                    },
                },
                {
                    "id": "avwap_short_reversal",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "poc_atr_tolerance": 1.5,
                        "rsi_short_min": 45.0,
                        "avwap_swing_lookback": 60,
                        "poc_lookback": 60,
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
            "stop_loss": {"method": "structural_atr", "swing_lookback": 10, "atr_buffer": 1.0},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class AnchoredVWAPReversalStrategy(Strategy):
    """Anchored VWAP + Volume Profile POC mean-reversion strategy.

    Long:
      - 200-EMA yukari (close > ema200)
      - Swing-low anchored AVWAP hesapli
      - Price AVWAP'i asagi dan yukari gecis (body rejection up)
      - POC yakinda: |close - poc| <= poc_atr_tolerance * ATR14
      - RSI14 < rsi_long_max (overbought degil)
    Short: simetrik
    SL  : structural swing low/high - atr_buffer * ATR14
    TP  : primary_R * risk (default 2R)
    """

    name = "anchored_vwap_reversal"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # --- Temel gostergeler ---
        df["ema200"] = _ema(df["close"], 200)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]
        df["rsi14"] = _rsi(df["close"], 14)

        # --- Fractal swing high/low ---
        fractal_n = self.manifest.signals.structure.swing.fractal_n
        sh, sl = _fractal_swings(df, n=fractal_n)
        df["swing_high"] = sh
        df["swing_low"] = sl

        # --- Parametre ayiklama ---
        avwap_lookback = 60
        poc_lookback = 60
        for p in self.manifest.signals.patterns:
            if p.id in ("avwap_long_reversal", "avwap_short_reversal"):
                avwap_lookback = int(p.params.get("avwap_swing_lookback", 60))
                poc_lookback = int(p.params.get("poc_lookback", 60))
                break

        # --- Rolling AVWAP: swing-low anchor (long), swing-high anchor (short) ---
        df["avwap_long"] = _rolling_avwap_from_swing(
            df, swing_col="swing_low", lookback=avwap_lookback
        )
        df["avwap_short"] = _rolling_avwap_from_swing(
            df, swing_col="swing_high", lookback=avwap_lookback
        )

        # --- Volume Profile POC (lookahead-free, lookback penceresi) ---
        df["poc"] = _volume_profile_poc(df, lookback=poc_lookback, n_buckets=50)

        # --- AVWAP crossover flags (body rejection) ---
        # Long: prev_close < avwap_long AND close >= avwap_long  (cross up)
        prev_close = df["close"].shift(1)
        df["avwap_long_cross_up"] = (
            (prev_close < df["avwap_long"]) &
            (df["close"] >= df["avwap_long"])
        ).fillna(False)

        # Short: prev_close > avwap_short AND close <= avwap_short  (cross down)
        df["avwap_short_cross_down"] = (
            (prev_close > df["avwap_short"]) &
            (df["close"] <= df["avwap_short"])
        ).fillna(False)

        # --- Structural SL seviyeleri ---
        df["struct_sl_long"] = df["low"].shift(1).rolling(10, min_periods=1).min()
        df["struct_sl_short"] = df["high"].shift(1).rolling(10, min_periods=1).max()

        # --- Volume z-score (filtre icin) ---
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0.0, np.nan)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "avwap_long" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters_cfg = signals_cfg.filters
        confluence = signals_cfg.confluence

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
        )
        atr_buffer = float(
            self.manifest.risk.get("stop_loss", {}).get("atr_buffer", 1.0)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # --- Parametre ayiklama ---
        poc_atr_tol = 1.5
        rsi_long_max = 55.0
        rsi_short_min = 45.0
        bull_weight = 1.5
        bear_weight = 1.5
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "avwap_long_reversal":
                poc_atr_tol = float(p.params.get("poc_atr_tolerance", 1.5))
                rsi_long_max = float(p.params.get("rsi_long_max", 55.0))
                bull_weight = p.weight
            elif p.id == "avwap_short_reversal":
                rsi_short_min = float(p.params.get("rsi_short_min", 45.0))
                bear_weight = p.weight

        atr_min = float(getattr(filters_cfg, "atr_min_pct", 0.003) or 0.003)
        min_score = float(confluence.min_score)

        out: list[Signal] = []
        n = len(df)

        for i in range(n):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue

            # ATR min filter
            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr_min > 0 and atr_pct < atr_min:
                continue

            poc = float(row.get("poc") or np.nan)
            rsi = float(row.get("rsi14") or 50.0)
            ema200 = float(row.get("ema200") or np.nan)
            avwap_long = float(row.get("avwap_long") or np.nan)
            avwap_short = float(row.get("avwap_short") or np.nan)
            cross_up = bool(row.get("avwap_long_cross_up", False))
            cross_down = bool(row.get("avwap_short_cross_down", False))
            sl_long = float(row.get("struct_sl_long") or np.nan)
            sl_short = float(row.get("struct_sl_short") or np.nan)

            # ------ LONG setup ------
            ema_up = (not np.isnan(ema200)) and (close > ema200)
            avwap_l_ok = (not np.isnan(avwap_long))
            poc_ok_long = (not np.isnan(poc)) and (abs(close - poc) <= poc_atr_tol * atr)
            rsi_ok_long = rsi < rsi_long_max

            if ema_up and avwap_l_ok and cross_up and poc_ok_long and rsi_ok_long:
                score = bull_weight
                if score >= min_score:
                    # SL: structural swing low - atr buffer
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

                    ts = pd.Timestamp(row["ts"]).to_pydatetime()
                    sig = self.emit_signal(
                        ts=ts,
                        venue=venue,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="long",
                        pattern_id="avwap_long_reversal",
                        confluence_score=float(score),
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=1.0,
                        metadata={
                            "avwap_long": avwap_long,
                            "poc": poc,
                            "rsi14": rsi,
                            "atr14": atr,
                            "ema200": ema200,
                            "poc_dist_atr": abs(close - poc) / atr if atr > 0 else np.nan,
                        },
                    )
                    out.append(sig)

            # ------ SHORT setup ------
            ema_down = (not np.isnan(ema200)) and (close < ema200)
            avwap_s_ok = (not np.isnan(avwap_short))
            poc_ok_short = (not np.isnan(poc)) and (abs(close - poc) <= poc_atr_tol * atr)
            rsi_ok_short = rsi > rsi_short_min

            if ema_down and avwap_s_ok and cross_down and poc_ok_short and rsi_ok_short:
                score = bear_weight
                if score >= min_score:
                    if np.isnan(sl_short) or sl_short <= 0:
                        sl_price = close + 2.0 * atr
                    else:
                        sl_price = sl_short + atr_buffer * atr
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
                        pattern_id="avwap_short_reversal",
                        confluence_score=float(score),
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=1.0,
                        metadata={
                            "avwap_short": avwap_short,
                            "poc": poc,
                            "rsi14": rsi,
                            "atr14": atr,
                            "ema200": ema200,
                            "poc_dist_atr": abs(close - poc) / atr if atr > 0 else np.nan,
                        },
                    )
                    out.append(sig)

        self._log.bind(n=len(out), bars=n).info("avwap_reversal.signals.generated")
        return out
