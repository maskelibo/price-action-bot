"""Naked POC (Point of Control) Mean Reversion stratejisi.

TPO Value Area'dan farklar (neden bu strateji TPO'dan farklı):
  - TPO (REJECTED): 30-bar kısa pencere, VAH/VAL sınırlarına (Value Area) dayalı,
    fiyat value area'dan çıkınca reversal. SORUN: Gürültüye çok duyarlı, kısa lookback
    sık false signal üretir, değer alanı her 30 barda güncellenir.

  - Naked POC (BU): 60-bar uzun pencere. Fiyatın HIÇ test etmediği eski POC seviyeleri
    aranır (untested constraint). "Naked" = son 30 günde POC bölgesi fiyat tarafından
    hiç ziyaret edilmemiş. Uzak, test edilmemiş POC'lar çok daha güçlü mıknatıs etkisi
    yaratır çünkü orada hala doldurulmamış eski emir blokları vardır.

Mekanizma (Volume Profile mıknatıs teorisi):
  - Hacim profili POC = piyasanın "adil değer" olarak belirlediği fiyat.
  - Fiyat uzaklaşırsa, piyasa yapıcılar oraya dönüş için likidite sağlar.
  - "Naked" (hiç test edilmemiş) POC'lar bu çekim kuvvetini kümülatif olarak biriktirir.
  - Sonuç: Fiyat POC'a döndüğünde hacim absorbsiyonu ve çekim etkisi çok daha güçlü.

Strateji kuralları:
  - 60-bar volume profile (50 bin) ile POC hesapla.
  - "Naked" kriteri: Son 30 barda fiyat hiç POC +/- poc_band_atr * ATR aralığına girmemiş.
  - Price drift kriteri: Son 5 barda fiyat POC yönünde hareket etmiş (momentum doğrulaması).
  - LONG: close < POC ve ATR mesafe ≥ 1 ATR + bullish reversal pattern → long, target POC.
  - SHORT: close > POC ve ATR mesafe ≥ 1 ATR + bearish reversal pattern → short, target POC.
  - SL: Structural swing low/high - 1.5 * ATR.
  - TP: Naked POC seviyesi.
  - Zaman stop: 20 bar içinde POC'a ulaşmazsa exit.
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
# Volume Profile: Long-lookback POC hesaplayıcısı
# =====================================================================

def _compute_long_poc(
    df: pd.DataFrame,
    lookback: int = 60,
    bins: int = 50,
) -> pd.Series:
    """Rolling long-lookback POC — her t için [t-lookback .. t-1].

    TPO'dan farkı: 60-bar (vs 30-bar) uzun pencere. Bu, daha az gürültülü
    ve daha "kurumsal" seviyeler üretir. VAH/VAL hesaplanmaz; sadece POC
    aranır çünkü bizim kriterimiz "en yüksek hacim seviyesi" tır.

    Args:
        df: OHLCV DataFrame.
        lookback: Kaç bar geriye bakılacak (varsayılan 60).
        bins: Fiyat aralığını kaç dilime böl (varsayılan 50).

    Returns:
        poc: pd.Series — her bar için Point of Control fiyatı.
    """
    n = len(df)
    poc_arr = np.full(n, np.nan)

    lows = df["low"].values
    highs = df["high"].values
    vols = df["volume"].values

    for t in range(lookback, n):
        start = t - lookback
        end = t  # exclusive: [start, end) = [t-lookback .. t-1] — lookahead-free
        w_low = lows[start:end]
        w_high = highs[start:end]
        w_vol = vols[start:end]

        price_min = np.nanmin(w_low)
        price_max = np.nanmax(w_high)

        if (
            np.isnan(price_min)
            or np.isnan(price_max)
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
            continue

        # POC: en yüksek hacimli bucket merkezi
        poc_idx = int(np.argmax(bucket_vol))
        poc_arr[t] = (edges[poc_idx] + edges[poc_idx + 1]) / 2.0

    return pd.Series(poc_arr, index=df.index, dtype=float)


# =====================================================================
# Naked POC kriteri: Son untested_lookback barda hiç ziyaret edilmemiş mi?
# =====================================================================

def _compute_naked_flag(
    df: pd.DataFrame,
    poc: pd.Series,
    untested_lookback: int = 30,
    poc_band_atr: float = 0.3,
    atr: pd.Series | None = None,
) -> pd.Series:
    """Her bar için POC'un "naked" (hiç test edilmemiş) olup olmadığını belirle.

    Untested kriteri: son `untested_lookback` barda fiyatın high veya low'u
    POC +/- poc_band_atr * ATR aralığına GİRMEMİŞ olmalı.

    Bu kriter TPO'dan tamamen farklıdır: TPO hiçbir untested constraint uygulamaz,
    her 30 barda yeni VAH/VAL hesaplar. Naked POC ise sadece eski,
    doldurulmamış seviyelere odaklanır — bunlar çok daha güçlü mıknatıslardır.

    Args:
        df: OHLCV DataFrame.
        poc: POC serileri (her bar için).
        untested_lookback: Son kaç barda test edilmemiş olmalı (varsayılan 30).
        poc_band_atr: POC etrafındaki tolerans bandı (ATR katı, varsayılan 0.3).
        atr: ATR serileri. None ise hesaplanır.

    Returns:
        naked: pd.Series[bool] — True ise Naked POC var.
    """
    n = len(df)
    naked_arr = np.zeros(n, dtype=bool)

    if atr is None:
        atr = _atr(df, 14)

    highs = df["high"].values
    lows = df["low"].values
    poc_vals = poc.values
    atr_vals = atr.values

    for t in range(n):
        poc_t = poc_vals[t]
        atr_t = atr_vals[t]

        if np.isnan(poc_t) or np.isnan(atr_t) or atr_t <= 0:
            continue

        band = poc_band_atr * atr_t
        poc_hi = poc_t + band
        poc_lo = poc_t - band

        # Son untested_lookback barı tara: t dahil DEĞİL (lookahead-free)
        # Ancak t'nin kendi barının da test etmemesini istiyoruz, bu yüzden
        # testi [t-untested_lookback .. t-1] aralığında yapıyoruz.
        start_test = max(0, t - untested_lookback)
        end_test = t  # exclusive

        if end_test <= start_test:
            continue

        test_highs = highs[start_test:end_test]
        test_lows = lows[start_test:end_test]

        # Herhangi bir bar POC bandına dokunmuş mu?
        touched = (test_highs >= poc_lo) & (test_lows <= poc_hi)
        if not touched.any():
            naked_arr[t] = True

    return pd.Series(naked_arr, index=df.index, dtype=bool)


# =====================================================================
# Price drift: Son n barda fiyat POC yönünde hareket ediyor mu?
# =====================================================================

def _compute_price_drift_toward_poc(
    df: pd.DataFrame,
    poc: pd.Series,
    drift_lookback: int = 5,
) -> pd.Series:
    """Son `drift_lookback` barda fiyat POC yönüne doğru hareket etti mi?

    POC altında (long senaryosu): son drift_lookback barda close artıyor mu?
      → close[t-1] > close[t-drift_lookback-1] (pozitif drift)
    POC üstünde (short senaryosu): son drift_lookback barda close azalıyor mu?
      → close[t-1] < close[t-drift_lookback-1] (negatif drift)

    Bu "momentum doğrulaması", POC'tan çok uzaklaşmış ve dönmeye başlamış
    fiyatları yakalar — tamamen durağan veya POC'tan uzaklaşmaya devam eden
    fiyatları filtreler.

    Returns:
        drift_toward: pd.Series[int]
          +1 = POC altında, yukarı drift (long setup hazır)
          -1 = POC üstünde, aşağı drift (short setup hazır)
           0 = drift yok / nötr
    """
    n = len(df)
    drift_arr = np.zeros(n, dtype=int)

    closes = df["close"].values
    poc_vals = poc.values

    for t in range(drift_lookback + 1, n):
        poc_t = poc_vals[t]
        close_t = closes[t]

        if np.isnan(poc_t):
            continue

        # drift_lookback bar önce ve şimdiki close
        past_close = closes[t - drift_lookback]
        curr_close = close_t

        if np.isnan(past_close):
            continue

        if close_t < poc_t:
            # Long senaryosu: close POC altında, son barlar yukarı mı gidiyor?
            if curr_close > past_close:
                drift_arr[t] = 1  # yukarı drift → POC'a yaklaşıyor
        elif close_t > poc_t:
            # Short senaryosu: close POC üstünde, son barlar aşağı mı gidiyor?
            if curr_close < past_close:
                drift_arr[t] = -1  # aşağı drift → POC'a yaklaşıyor

    return pd.Series(drift_arr, index=df.index, dtype=int)


# =====================================================================
# Reversal pattern tespiti (TPO'dan alındı + genişletildi)
# =====================================================================

def _bullish_reversal_pattern(df: pd.DataFrame, idx: int) -> bool:
    """t=idx bar'da bullish reversal var mı?

    Kriterler (herhangi biri yeterli):
      A. Bullish engulfing: close > prev_open AND open <= prev_close, bearish önceki bar.
      B. Hammer/Pin bar: alt fitil >= 2 * body, close > prev_close.
      C. Bullish harami: küçük bullish bar, önceki büyük bearish bar içinde.

    Lookahead-free: sadece t-1 ve t bar'ı kullanılır.
    """
    if idx < 1:
        return False

    o = float(df["open"].iat[idx])
    c = float(df["close"].iat[idx])
    h = float(df["high"].iat[idx])
    lo = float(df["low"].iat[idx])
    prev_o = float(df["open"].iat[idx - 1])
    prev_c = float(df["close"].iat[idx - 1])

    body = abs(c - o)
    prev_body = abs(prev_c - prev_o)
    rng = h - lo

    # A: Bullish engulfing — bearish önceki bar'ı tamamen sarıyor
    if c > o and prev_c < prev_o:  # bullish bar, bearish önceki
        if o <= prev_c and c >= prev_o:
            return True

    # B: Hammer — alt fitil >=2x body, bullish kapanış
    if rng > 0 and body > 0:
        lower_wick = min(o, c) - lo
        if lower_wick >= 2.0 * body and c > prev_c:
            return True

    # C: Bullish harami — küçük bullish bar önceki bearish'in içinde
    if (
        c > o
        and prev_c < prev_o
        and body < prev_body * 0.5
        and o > prev_c
        and c < prev_o
    ):
        return True

    return False


def _bearish_reversal_pattern(df: pd.DataFrame, idx: int) -> bool:
    """t=idx bar'da bearish reversal var mı?

    Kriterler (herhangi biri yeterli):
      A. Bearish engulfing.
      B. Shooting star: üst fitil >= 2 * body, bearish kapanış.
      C. Bearish harami.

    Lookahead-free: sadece t-1 ve t bar'ı kullanılır.
    """
    if idx < 1:
        return False

    o = float(df["open"].iat[idx])
    c = float(df["close"].iat[idx])
    h = float(df["high"].iat[idx])
    lo = float(df["low"].iat[idx])
    prev_o = float(df["open"].iat[idx - 1])
    prev_c = float(df["close"].iat[idx - 1])

    body = abs(c - o)
    prev_body = abs(prev_c - prev_o)
    rng = h - lo

    # A: Bearish engulfing — bullish önceki bar'ı tamamen sarıyor
    if c < o and prev_c > prev_o:  # bearish bar, bullish önceki
        if o >= prev_c and c <= prev_o:
            return True

    # B: Shooting star — üst fitil >= 2x body, bearish kapanış
    if rng > 0 and body > 0:
        upper_wick = h - max(o, c)
        if upper_wick >= 2.0 * body and c < prev_c:
            return True

    # C: Bearish harami — küçük bearish bar önceki bullish'in içinde
    if (
        c < o
        and prev_c > prev_o
        and body < prev_body * 0.5
        and o < prev_c
        and c > prev_o
    ):
        return True

    return False


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "naked_poc_mr",
        "version": "1.0.0",
        "description": (
            "Naked POC Mean Reversion: 60-bar volume profile, untested POC magnet, "
            "price drift toward POC + reversal pattern entry"
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "naked_poc_long",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "vp_lookback": 60,
                        "vp_bins": 50,
                        "untested_lookback": 30,
                        "poc_band_atr": 0.3,
                        "atr_distance_min": 1.0,
                        "drift_lookback": 5,
                    },
                },
                {
                    "id": "naked_poc_short",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "vp_lookback": 60,
                        "vp_bins": 50,
                        "untested_lookback": 30,
                        "poc_band_atr": 0.3,
                        "atr_distance_min": 1.0,
                        "drift_lookback": 5,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 3},
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
            "stop_loss": {
                "method": "structural_atr",
                "swing_lookback": 10,
                "atr_buffer": 1.5,
            },
            "take_profit": {"method": "poc_target"},
            "position_sizing": {
                "method": "fixed_fractional",
                "risk_per_trade": 0.01,
            },
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class NakedPOCMeanReversionStrategy(Strategy):
    """Naked POC Mean Reversion — 60-bar volume profile + untested constraint.

    TPO'dan temel farklar:
    1. Lookback 60-bar (vs 30-bar): daha stabil, kurumsal POC seviyeleri.
    2. Untested constraint: son 30 barda POC bölgesine hiç girilmemiş olmalı.
       TPO bu kriteri hiç uygulamaz.
    3. Price drift filtresi: fiyat POC yönünde hareket etmiş olmalı (momentum).
       TPO sadece VAH/VAL sınırlarını kontrol eder.
    4. Entry: POC'a 1 ATR mesafede + reversal (vs TPO'nun VAH/VAL sınırlarından 2 ATR).
    5. Target: Naked POC (vs TPO'nun POC veya VAH/VAL).

    Long:
      - close < poc (POC altında)
      - (poc - close) >= atr_distance_min * ATR
      - POC son 30 barda test edilmemiş (naked)
      - Son 5 barda fiyat yukarı drift (POC'a yaklaşıyor)
      - Bullish reversal pattern

    Short:
      - close > poc (POC üstünde)
      - (close - poc) >= atr_distance_min * ATR
      - POC son 30 barda test edilmemiş (naked)
      - Son 5 barda fiyat aşağı drift (POC'a yaklaşıyor)
      - Bearish reversal pattern

    SL: Structural swing low/high - 1.5 * ATR
    TP: Naked POC seviyesi
    """

    name = "naked_poc_mr"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # --- Temel göstergeler ---
        df["ema200"] = _ema(df["close"], 200)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # --- Parametre ayıklama ---
        vp_lookback = 60
        vp_bins = 50
        untested_lookback = 30
        poc_band_atr = 0.3
        drift_lookback = 5

        for p in self.manifest.signals.patterns:
            if p.id in ("naked_poc_long", "naked_poc_short"):
                vp_lookback = int(p.params.get("vp_lookback", 60))
                vp_bins = int(p.params.get("vp_bins", 50))
                untested_lookback = int(p.params.get("untested_lookback", 30))
                poc_band_atr = float(p.params.get("poc_band_atr", 0.3))
                drift_lookback = int(p.params.get("drift_lookback", 5))
                break

        # --- Long-lookback POC hesapla ---
        df["poc"] = _compute_long_poc(df, lookback=vp_lookback, bins=vp_bins)

        # --- Naked flag: son untested_lookback barda hiç test edilmemiş ---
        df["poc_naked"] = _compute_naked_flag(
            df,
            poc=df["poc"],
            untested_lookback=untested_lookback,
            poc_band_atr=poc_band_atr,
            atr=df["atr14"],
        )

        # --- Price drift toward POC ---
        df["poc_drift"] = _compute_price_drift_toward_poc(
            df,
            poc=df["poc"],
            drift_lookback=drift_lookback,
        )

        # --- Reversal pattern flags ---
        bull_flags = []
        bear_flags = []
        for i in range(len(df)):
            bull_flags.append(_bullish_reversal_pattern(df, i))
            bear_flags.append(_bearish_reversal_pattern(df, i))
        df["bull_reversal"] = bull_flags
        df["bear_reversal"] = bear_flags

        # --- Structural SL seviyeleri ---
        swing_lookback = int(
            self.manifest.risk.get("stop_loss", {}).get("swing_lookback", 10)
        )
        df["struct_sl_long"] = df["low"].shift(1).rolling(
            swing_lookback, min_periods=1
        ).min()
        df["struct_sl_short"] = df["high"].shift(1).rolling(
            swing_lookback, min_periods=1
        ).max()

        # --- Volume z-score ---
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0.0, np.nan)

        # --- Distance to POC (ATR birimleri) ---
        df["dist_to_poc_atr"] = (df["close"] - df["poc"]).abs() / df["atr14"].replace(
            0.0, np.nan
        )

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "poc" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters_cfg = signals_cfg.filters
        confluence = signals_cfg.confluence

        atr_buffer = float(
            self.manifest.risk.get("stop_loss", {}).get("atr_buffer", 1.5)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # --- Parametre ayıklama ---
        atr_dist_min = 1.0
        long_weight = 1.5
        short_weight = 1.5
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "naked_poc_long":
                atr_dist_min = float(p.params.get("atr_distance_min", 1.0))
                long_weight = p.weight
            elif p.id == "naked_poc_short":
                atr_dist_min = float(p.params.get("atr_distance_min", 1.0))
                short_weight = p.weight

        atr_min_pct = float(getattr(filters_cfg, "atr_min_pct", 0.003) or 0.003)
        min_score = float(confluence.min_score)

        out: list[Signal] = []
        n = len(df)

        for i in range(n):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)

            if atr <= 0 or np.isnan(atr):
                continue

            # ATR min filtresi (düşük volatilite dönemlerini elendir)
            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr_min_pct > 0 and atr_pct < atr_min_pct:
                continue

            poc = float(row.get("poc") or np.nan)
            if np.isnan(poc) or poc <= 0:
                continue

            # Naked kriteri: sadece naked POC'larla işlem yap
            poc_naked = bool(row.get("poc_naked", False))
            if not poc_naked:
                continue

            drift = int(row.get("poc_drift", 0))
            bull_rev = bool(row.get("bull_reversal", False))
            bear_rev = bool(row.get("bear_reversal", False))

            sl_long = float(row.get("struct_sl_long") or np.nan)
            sl_short = float(row.get("struct_sl_short") or np.nan)

            # ------ LONG: close < POC, yaklaşıyor, bullish reversal ------
            if close < poc and drift == 1 and bull_rev:
                dist_atr = (poc - close) / atr
                if dist_atr >= atr_dist_min:
                    score = long_weight
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

                        # TP: Naked POC (mean reversion hedefi)
                        tp_price = poc
                        if tp_price <= close:
                            continue

                        ts_val = pd.Timestamp(row["ts"]).to_pydatetime()
                        r_multiple = (tp_price - close) / risk if risk > 0 else 0.0

                        sig = self.emit_signal(
                            ts=ts_val,
                            venue=venue,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="long",
                            pattern_id="naked_poc_long",
                            confluence_score=float(score),
                            sl_price=float(sl_price),
                            tp_price=float(tp_price),
                            suggested_size_atr=1.0,
                            metadata={
                                "poc": poc,
                                "poc_naked": True,
                                "atr14": atr,
                                "dist_to_poc_atr": dist_atr,
                                "drift": drift,
                                "implied_r": r_multiple,
                            },
                        )
                        out.append(sig)

            # ------ SHORT: close > POC, aşağı yaklaşıyor, bearish reversal ------
            elif close > poc and drift == -1 and bear_rev:
                dist_atr = (close - poc) / atr
                if dist_atr >= atr_dist_min:
                    score = short_weight
                    if score >= min_score:
                        # SL: structural swing high + atr_buffer * ATR
                        if np.isnan(sl_short) or sl_short <= 0:
                            sl_price = close + 2.0 * atr
                        else:
                            sl_price = sl_short + atr_buffer * atr
                        sl_price = max(sl_price, close + 0.5 * atr)
                        risk = sl_price - close
                        if risk <= 0:
                            continue

                        # TP: Naked POC
                        tp_price = poc
                        if tp_price >= close:
                            continue

                        ts_val = pd.Timestamp(row["ts"]).to_pydatetime()
                        r_multiple = (close - tp_price) / risk if risk > 0 else 0.0

                        sig = self.emit_signal(
                            ts=ts_val,
                            venue=venue,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="short",
                            pattern_id="naked_poc_short",
                            confluence_score=float(score),
                            sl_price=float(sl_price),
                            tp_price=float(tp_price),
                            suggested_size_atr=1.0,
                            metadata={
                                "poc": poc,
                                "poc_naked": True,
                                "atr14": atr,
                                "dist_to_poc_atr": dist_atr,
                                "drift": drift,
                                "implied_r": r_multiple,
                            },
                        )
                        out.append(sig)

        self._log.bind(n=len(out), bars=n).info("naked_poc_mr.signals.generated")
        return out
