"""Morning Star / Evening Star uc-bar reversal stratejisi.

Bulkowski istatistigi:
  Morning Star (Doji variant): %74 bullish reversal rate  — Rank 8-9 / 103
  Evening Star (Doji variant): %73 bearish reversal rate  — Rank 8   / 103

Mekanik kural:
  BAR 1 (Guc barı):
    - Morning : BEARISH, gövde >= %50 * range  (bar1_body_ratio >= 0.5)
    - Evening : BULLISH, gövde >= %50 * range
  BAR 2 (Yildiz barı):
    - Küçük gövde: body <= bar2_max_body_ratio * range  (default 0.35)
    - Doji veya spinning top kabul edilir
    - Açılış, Bar1 kapanısından <= gap_atr_factor*ATR ötede (gap down/flat MS, gap up/flat ES)
  BAR 3 (Onay barı):
    - Morning : BULLISH, kapanış Bar1 gövde ortasının ÜSTÜNDE (>= 50% penetrasyon)
    - Evening : BEARISH, kapanış Bar1 gövde ortasının ALTINDA
  Volume filtresi (opsiyonel, varsayılan aktif):
    - Bar2 volume <= vol_bar2_factor * Vol_MA  (zayıf kararsızlık barı)
    - Bar3 volume >= vol_bar3_factor * Vol_MA  (güçlü onay)

Giriş  : Bar3 kapanışında (Bar3 sona erdikten sonra)
Stop   : Bar2 low'u (Morning) / Bar2 high'ı (Evening)
Hedef  : 2R (primary_R * risk)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# Paylaşılan yardımcılar — classic_pa'dan import
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
    _fractal_swings,
    _kaufman_efficiency_ratio,
    _always_in_flags,
    _rolling_sharpe,
    _sr_levels,
)


# =====================================================================
# Morning Star / Evening Star örüntü tespiti (vektörel, lookahead-free)
# =====================================================================

def _morning_star_flags(
    df: pd.DataFrame,
    bar1_body_ratio_min: float = 0.50,
    bar2_max_body_ratio: float = 0.35,
    bar3_penetration_min: float = 0.50,
    gap_atr_factor: float = 1.0,
) -> pd.Series:
    """3-bar Morning Star tespiti.

    Dönen seri: Bar3 indeksinde True ise o pozisyonda Morning Star tamamlandı.
    Bar indeksi N => Bar3=N, Bar2=N-1, Bar1=N-2.
    Lookahead yok (shift kullanılıyor).
    """
    o = df["open"]
    c = df["close"]
    h = df["high"]
    l = df["low"]
    atr = df["atr14"].fillna(0.0)

    rng = (h - l).replace(0, np.nan)
    body_abs = (c - o).abs()

    # --- Bar1 (N-2) : Güçlü bearish ---
    b1_open = o.shift(2)
    b1_close = c.shift(2)
    b1_range = rng.shift(2)
    b1_body = body_abs.shift(2)
    b1_bearish = b1_close < b1_open
    b1_body_ratio = b1_body / b1_range.replace(0, np.nan)
    b1_strong = b1_bearish & (b1_body_ratio >= bar1_body_ratio_min)

    # Bar1 gövde orta noktası (midpoint of Bar1 body)
    b1_mid = (b1_open + b1_close) / 2  # body midpoint: (open + close)/2

    # --- Bar2 (N-1) : Küçük gövde (doji/spinning top) ---
    b2_open = o.shift(1)
    b2_close = c.shift(1)
    b2_low = l.shift(1)
    b2_range = rng.shift(1)
    b2_body = body_abs.shift(1)
    b2_body_ratio = b2_body / b2_range.replace(0, np.nan)
    b2_small = b2_body_ratio <= bar2_max_body_ratio

    # Gap down veya flat: Bar2 açılışı Bar1 kapanışından ATR * factor altında ya da eşit
    # Crypto'da tam gap nadir; açılışın Bar1 kapanışının ATR * gap_atr_factor içinde/altında olması yeterli
    atr2 = atr.shift(1)
    b2_gap_ok = b2_open <= b1_close + gap_atr_factor * atr2

    # --- Bar3 (N) : Güçlü bullish, yeterli penetrasyon ---
    b3_open = o
    b3_close = c
    b3_bullish = b3_close > b3_open

    # Kapanış, Bar1 gövde ortasının ÜSTÜNDE olmalı
    b3_penetration_ok = b3_close > b1_mid + bar3_penetration_min * (b1_open - b1_mid)

    # Basit penetrasyon: close > b1_mid (Bar1 gövde ortasını geçmek = %50+ penetrasyon)
    b3_above_mid = b3_close > b1_mid

    flag = b1_strong & b2_small & b2_gap_ok & b3_bullish & b3_above_mid
    return flag.fillna(False)


def _evening_star_flags(
    df: pd.DataFrame,
    bar1_body_ratio_min: float = 0.50,
    bar2_max_body_ratio: float = 0.35,
    bar3_penetration_min: float = 0.50,
    gap_atr_factor: float = 1.0,
) -> pd.Series:
    """3-bar Evening Star tespiti.

    Bar3 indeksinde True ise Evening Star tamamlandı.
    """
    o = df["open"]
    c = df["close"]
    h = df["high"]
    l = df["low"]
    atr = df["atr14"].fillna(0.0)

    rng = (h - l).replace(0, np.nan)
    body_abs = (c - o).abs()

    # --- Bar1 (N-2) : Güçlü bullish ---
    b1_open = o.shift(2)
    b1_close = c.shift(2)
    b1_range = rng.shift(2)
    b1_body = body_abs.shift(2)
    b1_bullish = b1_close > b1_open
    b1_body_ratio = b1_body / b1_range.replace(0, np.nan)
    b1_strong = b1_bullish & (b1_body_ratio >= bar1_body_ratio_min)

    # Bar1 gövde orta noktası
    b1_mid = (b1_open + b1_close) / 2

    # --- Bar2 (N-1) : Küçük gövde ---
    b2_open = o.shift(1)
    b2_close = c.shift(1)
    b2_high = h.shift(1)
    b2_range = rng.shift(1)
    b2_body = body_abs.shift(1)
    b2_body_ratio = b2_body / b2_range.replace(0, np.nan)
    b2_small = b2_body_ratio <= bar2_max_body_ratio

    # Gap up veya flat: Bar2 açılışı Bar1 kapanışına yakın/yukarıda
    atr2 = atr.shift(1)
    b2_gap_ok = b2_open >= b1_close - gap_atr_factor * atr2

    # --- Bar3 (N) : Güçlü bearish, yeterli penetrasyon ---
    b3_close = c
    b3_open = o
    b3_bearish = b3_close < b3_open

    # Kapanış, Bar1 gövde ortasının ALTINDA olmalı
    b3_below_mid = b3_close < b1_mid

    flag = b1_strong & b2_small & b2_gap_ok & b3_bearish & b3_below_mid
    return flag.fillna(False)


def _volume_confirmation(
    df: pd.DataFrame,
    vol_ma_window: int = 20,
    bar2_vol_factor: float = 0.85,
    bar3_vol_factor: float = 1.10,
) -> tuple[pd.Series, pd.Series]:
    """Volume filtresi.

    Dönen: (bar2_low_vol, bar3_high_vol) — her ikisi Boolean serileri.
    Bar2 için: vol_N-1 <= bar2_vol_factor * vol_ma
    Bar3 için: vol_N   >= bar3_vol_factor * vol_ma
    """
    vol = df["volume"]
    vol_ma = vol.rolling(vol_ma_window, min_periods=5).mean().shift(1)  # lookahead-free MA

    b2_vol = vol.shift(1)
    b3_vol = vol

    b2_low = b2_vol <= bar2_vol_factor * vol_ma
    b3_high = b3_vol >= bar3_vol_factor * vol_ma

    return b2_low.fillna(True), b3_high.fillna(False)


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "morning_evening_star",
        "version": "1.0.0",
        "description": (
            "Morning Star (long) & Evening Star (short) — Bulkowski %72-74 reversal rate"
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "morning_star",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "bar1_body_ratio_min": 0.50,
                        "bar2_max_body_ratio": 0.35,
                        "gap_atr_factor": 1.0,
                        "use_volume_filter": True,
                        "vol_ma_window": 20,
                        "bar2_vol_factor": 0.85,
                        "bar3_vol_factor": 1.10,
                    },
                },
                {
                    "id": "evening_star",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "bar1_body_ratio_min": 0.50,
                        "bar2_max_body_ratio": 0.35,
                        "gap_atr_factor": 1.0,
                        "use_volume_filter": True,
                        "vol_ma_window": 20,
                        "bar2_vol_factor": 0.85,
                        "bar3_vol_factor": 1.10,
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
                "require_proximity_to_sr_atr": 0.0,  # S/R proximity: isteğe bağlı bonus
            },
            "filters": {
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.15,   # chop filtresi (engulfing'den biraz yumuşak)
                "bear_regime_size_factor": 0.5,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.0,
                "bonus_if_at_sr": 0.5,
            },
        },
        "risk": {
            "stop_loss": {"method": "bar2_extreme", "swing_lookback": 5},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy sınıfı
# =====================================================================

class MorningEveningStarStrategy(Strategy):
    """Morning Star & Evening Star üç-bar reversal stratejisi.

    Morning Star (bullish reversal):
      Bar1: güçlü bearish (body >= 50% range)
      Bar2: küçük gövde doji/spinning top (body <= 35% range), gap down/flat
      Bar3: bullish, kapanış Bar1 body midpoint üstünde

    Evening Star (bearish reversal):
      Bar1: güçlü bullish (body >= 50% range)
      Bar2: küçük gövde, gap up/flat
      Bar3: bearish, kapanış Bar1 body midpoint altında

    Stop: Bar2 low (Morning) / Bar2 high (Evening)
    Target: 2R
    """

    name = "morning_evening_star"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # --- Teknik göstergeler ---
        df["ema20"] = _ema(df["close"], 20)
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Volume z-score
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Swing high/low
        n_fractal = self.manifest.signals.structure.swing.fractal_n
        sh, sl = _fractal_swings(df, n=n_fractal)
        df["swing_high"] = sh
        df["swing_low"] = sl

        # Kaufman ER
        filters_cfg = self.manifest.signals.filters
        er_period = int(getattr(filters_cfg, "kaufman_er_period", 14) or 14)
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Rolling Sharpe
        rs_period = int(getattr(filters_cfg, "rolling_sharpe_period", 60) or 60)
        df["rolling_sharpe"] = _rolling_sharpe(df["close"], period=rs_period)

        # Pattern parametrelerini manifest'ten çek
        ms_params: dict[str, Any] = {}
        es_params: dict[str, Any] = {}
        for p in self.manifest.signals.patterns:
            if p.id == "morning_star":
                ms_params = p.params
            elif p.id == "evening_star":
                es_params = p.params

        ms_body1 = float(ms_params.get("bar1_body_ratio_min", 0.50))
        ms_body2 = float(ms_params.get("bar2_max_body_ratio", 0.35))
        ms_gap   = float(ms_params.get("gap_atr_factor", 1.0))

        es_body1 = float(es_params.get("bar1_body_ratio_min", 0.50))
        es_body2 = float(es_params.get("bar2_max_body_ratio", 0.35))
        es_gap   = float(es_params.get("gap_atr_factor", 1.0))

        # Morning Star & Evening Star örüntü bayrakları
        df["morning_star"] = _morning_star_flags(
            df,
            bar1_body_ratio_min=ms_body1,
            bar2_max_body_ratio=ms_body2,
            gap_atr_factor=ms_gap,
        )
        df["evening_star"] = _evening_star_flags(
            df,
            bar1_body_ratio_min=es_body1,
            bar2_max_body_ratio=es_body2,
            gap_atr_factor=es_gap,
        )

        # Volume onayı (ortak parametre — morning/evening için aynı)
        vol_window = int(ms_params.get("vol_ma_window", 20))
        b2_vf = float(ms_params.get("bar2_vol_factor", 0.85))
        b3_vf = float(ms_params.get("bar3_vol_factor", 1.10))
        b2_low_vol, b3_high_vol = _volume_confirmation(
            df, vol_ma_window=vol_window, bar2_vol_factor=b2_vf, bar3_vol_factor=b3_vf
        )
        df["vol_b2_low"] = b2_low_vol
        df["vol_b3_high"] = b3_high_vol

        # Stop seviyeleri: Bar2 low (Morning stop) / Bar2 high (Evening stop)
        df["star_sl_long"]  = df["low"].shift(1)   # Bar2 low
        df["star_sl_short"] = df["high"].shift(1)  # Bar2 high

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "morning_star" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        confluence_cfg = signals_cfg.confluence
        sr_cfg = signals_cfg.structure.support_resistance

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # Volume filtresi aktif mi?
        ms_params: dict[str, Any] = {}
        es_params: dict[str, Any] = {}
        for p in signals_cfg.patterns:
            if p.id == "morning_star":
                ms_params = p.params
            elif p.id == "evening_star":
                es_params = p.params

        use_vol_ms = bool(ms_params.get("use_volume_filter", True))
        use_vol_es = bool(es_params.get("use_volume_filter", True))

        ms_weight = 2.0
        es_weight = 2.0
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "morning_star":
                ms_weight = p.weight
            elif p.id == "evening_star":
                es_weight = p.weight

        # --- Score serileri ---
        long_score  = pd.Series(0.0, index=df.index)
        short_score = pd.Series(0.0, index=df.index)

        morning = df["morning_star"].fillna(False)
        evening = df["evening_star"].fillna(False)

        # Volume onayı ile birleştir
        b2_low = df["vol_b2_low"].fillna(True)
        b3_high = df["vol_b3_high"].fillna(False)

        if use_vol_ms:
            ms_ok = morning & b2_low & b3_high
        else:
            ms_ok = morning

        if use_vol_es:
            es_ok = evening & b2_low & b3_high
        else:
            es_ok = evening

        long_score  = long_score.where(~ms_ok, ms_weight)
        short_score = short_score.where(~es_ok, es_weight)

        # --- Trend filtresi (isteğe bağlı) ---
        if self.manifest.trend_filter.required:
            up_ok   = df["close"] > df["ema50"]
            down_ok = df["close"] < df["ema50"]
            long_score  = long_score.where(up_ok, 0.0)
            short_score = short_score.where(down_ok, 0.0)

        # --- ATR minimum filtresi ---
        atr_min = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)
        if atr_min > 0 and "atr_pct" in df.columns:
            mask = df["atr_pct"] >= atr_min
            long_score  = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # --- Kaufman ER filtresi ---
        er_min = float(getattr(filters, "kaufman_er_min", 0.0) or 0.0)
        if er_min > 0 and "kaufman_er" in df.columns:
            mask = df["kaufman_er"] >= er_min
            long_score  = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # --- 200-EMA bear regime filtresi ---
        bear_factor = float(getattr(filters, "bear_regime_size_factor", 1.0) or 1.0)
        if bear_factor < 1.0 and "ema200" in df.columns:
            below_200 = df["close"] < df["ema200"]
            long_score = long_score.where(~below_200, long_score * bear_factor)

        # --- S/R proximity bonus ---
        cluster_tol = df["atr14"].fillna(0) * sr_cfg.cluster_atr_multiplier
        sr_records = _sr_levels(
            df,
            lookback_bars=sr_cfg.lookback_bars,
            cluster_tol=cluster_tol,
            min_touches=sr_cfg.min_touches,
        )
        sr_by_bar: dict[int, list[float]] = {}
        for i, lvl, _t in sr_records:
            sr_by_bar.setdefault(i, []).append(lvl)

        proximity_atr = signals_cfg.structure.require_proximity_to_sr_atr
        bonus = float(getattr(confluence_cfg, "bonus_if_at_sr", 0.0) or 0.0)
        min_score = float(confluence_cfg.min_score)

        out: list[Signal] = []

        for i in range(len(df)):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue

            # S/R proximity kontrolü
            levels = sr_by_bar.get(i, [])
            near_sr = False
            if levels and proximity_atr > 0:
                tol = proximity_atr * atr
                near_sr = any(abs(close - lvl) <= tol for lvl in levels)

            for direction, score_series, pattern_id_name in (
                ("long",  long_score,  "morning_star"),
                ("short", short_score, "evening_star"),
            ):
                base_score = float(score_series.iat[i])
                if base_score <= 0:
                    continue

                final_score = base_score + (bonus if near_sr else 0.0)
                if final_score < min_score:
                    continue

                # Stop-loss: Bar2 extremes
                if direction == "long":
                    sl_raw = float(row.get("star_sl_long") or 0.0)
                    if np.isnan(sl_raw) or sl_raw <= 0:
                        sl_raw = close - 2.0 * atr
                    sl_price = min(sl_raw, close - 0.3 * atr)  # en az 0.3 ATR aşağıda
                    risk = close - sl_price
                    if risk <= 0:
                        continue
                    tp_price = close + primary_R * risk
                else:
                    sl_raw = float(row.get("star_sl_short") or 0.0)
                    if np.isnan(sl_raw) or sl_raw <= 0:
                        sl_raw = close + 2.0 * atr
                    sl_price = max(sl_raw, close + 0.3 * atr)
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
                    direction=direction,
                    pattern_id=pattern_id_name,
                    confluence_score=float(final_score),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "near_sr": near_sr,
                        "atr14": atr,
                        "ema50": float(row.get("ema50") or 0.0),
                        "kaufman_er": float(row.get("kaufman_er") or 0.0),
                        "vol_b2_low": bool(row.get("vol_b2_low", False)),
                        "vol_b3_high": bool(row.get("vol_b3_high", False)),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("morning_evening_star.signals.generated")
        return out
