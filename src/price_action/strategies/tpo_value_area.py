"""TPO Value Area (Volume Profile) Mean-Reversion stratejisi.

Steidlmayer Market Profile metodolojisinin kripto 1d uyarlamasi.

Strateji konsepti:
  - Rolling 30-bar Volume Profile (price-binned histogram) ile gunluk Value Area hesapla.
  - Value Area High (VAH): toplam hacmin %70'ini kapsayan ust sinir.
  - Point of Control (POC): en yuksek hacimli fiyat seviyesi.
  - Value Area Low (VAL): toplam hacmin %70'ini kapsayan alt sinir.
  - Fiyat VAL altina uzandiginda (> 2*ATR) ve bullish reversal pattern varsa LONG.
  - Fiyat VAH uzerinde uzandiginda (> 2*ATR) ve bearish reversal varsa SHORT.
  - TP: POC'a don (degisken R).
  - SL: Entry'nin yapısal low/high'inin 1*ATR otesi.

AVWAP'tan farki:
  AVWAP tek bir fiyat cizgisidir. TPO tam volume dagilimi seklini yakalar.
  Fiyat "kuyrukta" (dusuk hacimli nodda) olduğunda, strukturel olarak
  zayiftir — piyasa orada "kabul" gormemistir. Kripto'da VAH/VAL etrafinda
  heavy bid/ask absorpsiyonu gozlenmektedir (Harris, auction theory).

Neden basarisiz olabilir:
  Steidlmayer metodu equity index futures icin gelistirilmistir.
  Kripto guclu trend rejimleri uretir (Kaufman: mean-reversion trend'de katastrofik).
  AVWAP gibi bu da trend-dominant kripto ortaminda olumsuz koşullara maruz kalabilir.
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
    _fractal_swings,
)


# =====================================================================
# Volume Profile hesaplayicilari
# =====================================================================

def _volume_profile(
    df: pd.DataFrame,
    lookback: int = 30,
    bins: int = 50,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Rolling volume profile: VAH, POC, VAL hesapla.

    Her t bari icin [t-lookback .. t-1] araligini kullanir (lookahead-free).
    Value Area: toplam hacmin %70'ini icerir.

    Algoritma:
      1. Lookback penceresindeki low-high araligini `bins` esit dilime bol.
      2. Her bin icin toplam hacim = o bin araliginda kesen bar'larin hacimleri.
      3. En yuksek hacimli bin = POC.
      4. POC'tan disari dogru (yukari ve asagi) hacim kumulunu tut,
         toplam hacmin %70'ine ulasana kadar — VAH ust siniri, VAL alt siniri.

    Returns:
      vah: pd.Series — Value Area High
      poc: pd.Series — Point of Control
      val: pd.Series — Value Area Low
    """
    n = len(df)
    vah_arr = np.full(n, np.nan)
    poc_arr = np.full(n, np.nan)
    val_arr = np.full(n, np.nan)

    lows = df["low"].values
    highs = df["high"].values
    vols = df["volume"].values

    for t in range(lookback, n):
        start = t - lookback
        end = t  # exclusive — [start, end) = [t-lookback .. t-1]
        w_low = lows[start:end]
        w_high = highs[start:end]
        w_vol = vols[start:end]

        price_min = np.nanmin(w_low)
        price_max = np.nanmax(w_high)

        if (
            np.isnan(price_min) or np.isnan(price_max)
            or price_max <= price_min
        ):
            continue

        edges = np.linspace(price_min, price_max, bins + 1)
        bucket_vol = np.zeros(bins)

        for bi in range(bins):
            b_lo = edges[bi]
            b_hi = edges[bi + 1]
            # Bar bu bucket ile overlap ediyorsa hacmini ekle
            mask = (w_high >= b_lo) & (w_low <= b_hi)
            if mask.any():
                bucket_vol[bi] = np.nansum(w_vol[mask])

        total_vol = bucket_vol.sum()
        if total_vol == 0:
            poc_arr[t] = (price_min + price_max) / 2.0
            vah_arr[t] = price_max
            val_arr[t] = price_min
            continue

        # POC: max volume bucket merkezi
        poc_idx = int(np.argmax(bucket_vol))
        poc_arr[t] = (edges[poc_idx] + edges[poc_idx + 1]) / 2.0

        # Value Area: toplam hacmin %70'ini kapsayan aralik
        target_vol = total_vol * 0.70
        va_vol = bucket_vol[poc_idx]
        va_low_idx = poc_idx
        va_high_idx = poc_idx

        while va_vol < target_vol:
            # Bir sonraki adim: yukari mi asagi mi genis?
            can_go_up = va_high_idx + 1 < bins
            can_go_dn = va_low_idx - 1 >= 0

            if not can_go_up and not can_go_dn:
                break

            if can_go_up and can_go_dn:
                vol_up = bucket_vol[va_high_idx + 1]
                vol_dn = bucket_vol[va_low_idx - 1]
                if vol_up >= vol_dn:
                    va_high_idx += 1
                    va_vol += bucket_vol[va_high_idx]
                else:
                    va_low_idx -= 1
                    va_vol += bucket_vol[va_low_idx]
            elif can_go_up:
                va_high_idx += 1
                va_vol += bucket_vol[va_high_idx]
            else:
                va_low_idx -= 1
                va_vol += bucket_vol[va_low_idx]

        vah_arr[t] = edges[va_high_idx + 1]
        val_arr[t] = edges[va_low_idx]

    vah = pd.Series(vah_arr, index=df.index, dtype=float)
    poc = pd.Series(poc_arr, index=df.index, dtype=float)
    val = pd.Series(val_arr, index=df.index, dtype=float)
    return vah, poc, val


def _classify_zone(
    close: float, vah: float, val: float
) -> str:
    """Fiyat VAH/VAL'e gore konumunu siniflandir.

    Returns:
      'above_vah' : close > VAH (deger alaninin uzerinde)
      'in_value'  : VAL <= close <= VAH (deger alani icinde)
      'below_val' : close < VAL (deger alaninin altinda)
      'unknown'   : VAH/VAL NaN
    """
    if np.isnan(vah) or np.isnan(val):
        return "unknown"
    if close > vah:
        return "above_vah"
    if close < val:
        return "below_val"
    return "in_value"


def _bullish_reversal(df: pd.DataFrame, idx: int) -> bool:
    """t=idx bar'da bullish reversal paterni var mi?

    Kriter (iki alternatiften biri yeterli):
      A. Bullish engulfing: close > prev_open AND open < prev_close (body engulfs)
         + close > open (bullish candle)
      B. Pin bar (hammer): alt fitil >= 2 * body, close > prev_close

    Lookahead-free: sadece t-1 ve t bar'ini kullanir.
    """
    if idx < 1:
        return False
    o = float(df["open"].iat[idx])
    c = float(df["close"].iat[idx])
    h = float(df["high"].iat[idx])
    lo = float(df["low"].iat[idx])
    prev_o = float(df["open"].iat[idx - 1])
    prev_c = float(df["close"].iat[idx - 1])

    # A: Bullish engulfing
    if c > o:  # bullish candle
        if o <= prev_c and c >= prev_o and prev_c < prev_o:  # engulfs bearish prev
            return True

    # B: Hammer / pin bar (alt fitil domine)
    body = abs(c - o)
    lower_wick = min(o, c) - lo
    rng = h - lo
    if rng > 0 and body > 0 and lower_wick >= 2.0 * body and c > prev_c:
        return True

    return False


def _bearish_reversal(df: pd.DataFrame, idx: int) -> bool:
    """t=idx bar'da bearish reversal paterni var mi?

    Kriter (iki alternatiften biri yeterli):
      A. Bearish engulfing
      B. Shooting star / pin bar (ust fitil domine)

    Lookahead-free: sadece t-1 ve t kullanilir.
    """
    if idx < 1:
        return False
    o = float(df["open"].iat[idx])
    c = float(df["close"].iat[idx])
    h = float(df["high"].iat[idx])
    lo = float(df["low"].iat[idx])
    prev_o = float(df["open"].iat[idx - 1])
    prev_c = float(df["close"].iat[idx - 1])

    # A: Bearish engulfing
    if c < o:  # bearish candle
        if o >= prev_c and c <= prev_o and prev_c > prev_o:  # engulfs bullish prev
            return True

    # B: Shooting star
    body = abs(c - o)
    upper_wick = h - max(o, c)
    rng = h - lo
    if rng > 0 and body > 0 and upper_wick >= 2.0 * body and c < prev_c:
        return True

    return False


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "tpo_value_area",
        "version": "1.0.0",
        "description": "TPO/Market Profile Value Area mean-reversion, Steidlmayer adapted to crypto 1d",
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "tpo_long_reversal",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "vp_lookback": 30,
                        "vp_bins": 50,
                        "atr_extension_min": 2.0,
                        "va_pct": 0.70,
                    },
                },
                {
                    "id": "tpo_short_reversal",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "vp_lookback": 30,
                        "vp_bins": 50,
                        "atr_extension_min": 2.0,
                        "va_pct": 0.70,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 60,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 60,
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
            "take_profit": {"method": "poc_target"},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class TPOValueAreaStrategy(Strategy):
    """TPO Market Profile Value Area mean-reversion strategy.

    Long:
      - close < VAL (deger alaninin altinda)
      - close, VAL'den en az atr_extension_min * ATR asagida
      - Bullish reversal candle (engulfing veya hammer)
    Short:
      - close > VAH (deger alaninin uzerinde)
      - close, VAH'den en az atr_extension_min * ATR yukarda
      - Bearish reversal candle (engulfing veya shooting star)
    SL  : structural swing low/high - 1*ATR (long icin); + 1*ATR (short icin)
    TP  : POC (degisken R — uzak POC = buyuk R)
    """

    name = "tpo_value_area"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # --- Temel gostergeler ---
        df["ema200"] = _ema(df["close"], 200)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # --- Parametre ayiklama ---
        vp_lookback = 30
        vp_bins = 50
        for p in self.manifest.signals.patterns:
            if p.id in ("tpo_long_reversal", "tpo_short_reversal"):
                vp_lookback = int(p.params.get("vp_lookback", 30))
                vp_bins = int(p.params.get("vp_bins", 50))
                break

        # --- Volume Profile: VAH / POC / VAL ---
        df["vah"], df["poc"], df["val"] = _volume_profile(
            df, lookback=vp_lookback, bins=vp_bins
        )

        # --- Zone classification (vektorize degil — generate_signals'de kullanilir) ---
        # Sadece kolon olarak ekle (str serisi yavaş — generate_signals'da inline kullanilir)

        # --- Reversal pattern flags (vectorized) ---
        bull_flags = []
        bear_flags = []
        for i in range(len(df)):
            bull_flags.append(_bullish_reversal(df, i))
            bear_flags.append(_bearish_reversal(df, i))
        df["bull_reversal"] = bull_flags
        df["bear_reversal"] = bear_flags

        # --- Structural SL seviyeleri ---
        df["struct_sl_long"] = df["low"].shift(1).rolling(10, min_periods=1).min()
        df["struct_sl_short"] = df["high"].shift(1).rolling(10, min_periods=1).max()

        # --- Volume z-score ---
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0.0, np.nan)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "vah" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters_cfg = signals_cfg.filters
        confluence = signals_cfg.confluence

        atr_buffer = float(
            self.manifest.risk.get("stop_loss", {}).get("atr_buffer", 1.0)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # --- Parametre ayiklama ---
        atr_ext_min = 2.0
        bull_weight = 1.5
        bear_weight = 1.5
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "tpo_long_reversal":
                atr_ext_min = float(p.params.get("atr_extension_min", 2.0))
                bull_weight = p.weight
            elif p.id == "tpo_short_reversal":
                atr_ext_min = float(p.params.get("atr_extension_min", 2.0))
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

            vah = float(row.get("vah") or np.nan)
            poc = float(row.get("poc") or np.nan)
            val = float(row.get("val") or np.nan)

            if np.isnan(vah) or np.isnan(poc) or np.isnan(val):
                continue
            if val >= vah:
                continue

            bull_rev = bool(row.get("bull_reversal", False))
            bear_rev = bool(row.get("bear_reversal", False))
            sl_long = float(row.get("struct_sl_long") or np.nan)
            sl_short = float(row.get("struct_sl_short") or np.nan)

            zone = _classify_zone(close, vah, val)

            # ------ LONG: below VAL ------
            if zone == "below_val" and bull_rev:
                dist = val - close  # pozitif: val uzerinde mi?
                # close VAL'in en az atr_ext_min * ATR altinda olmali
                if (val - close) >= atr_ext_min * atr:
                    score = bull_weight
                    if score >= min_score:
                        # SL: structural swing low - atr_buffer * ATR
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
                        # TP: POC (mean-reversion hedefi)
                        tp_price = poc
                        # POC entry'nin uzerinde olmali
                        if tp_price <= close:
                            # Eger POC close altindaysa (nadir ama mumkun) VAH kullan
                            tp_price = vah

                        if tp_price <= close:
                            continue

                        ts = pd.Timestamp(row["ts"]).to_pydatetime()
                        r_multiple = (tp_price - close) / risk if risk > 0 else 0.0
                        sig = self.emit_signal(
                            ts=ts,
                            venue=venue,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="long",
                            pattern_id="tpo_long_reversal",
                            confluence_score=float(score),
                            sl_price=float(sl_price),
                            tp_price=float(tp_price),
                            suggested_size_atr=1.0,
                            metadata={
                                "vah": vah,
                                "poc": poc,
                                "val": val,
                                "atr14": atr,
                                "zone": zone,
                                "dist_to_val_atr": (val - close) / atr,
                                "implied_r": r_multiple,
                            },
                        )
                        out.append(sig)

            # ------ SHORT: above VAH ------
            elif zone == "above_vah" and bear_rev:
                if (close - vah) >= atr_ext_min * atr:
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
                        # TP: POC
                        tp_price = poc
                        if tp_price >= close:
                            tp_price = val

                        if tp_price >= close:
                            continue

                        ts = pd.Timestamp(row["ts"]).to_pydatetime()
                        r_multiple = (close - tp_price) / risk if risk > 0 else 0.0
                        sig = self.emit_signal(
                            ts=ts,
                            venue=venue,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="short",
                            pattern_id="tpo_short_reversal",
                            confluence_score=float(score),
                            sl_price=float(sl_price),
                            tp_price=float(tp_price),
                            suggested_size_atr=1.0,
                            metadata={
                                "vah": vah,
                                "poc": poc,
                                "val": val,
                                "atr14": atr,
                                "zone": zone,
                                "dist_to_vah_atr": (close - vah) / atr,
                                "implied_r": r_multiple,
                            },
                        )
                        out.append(sig)

        self._log.bind(n=len(out), bars=n).info("tpo_value_area.signals.generated")
        return out
