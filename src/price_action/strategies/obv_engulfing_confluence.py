"""OBV Divergence + Engulfing Confluence stratejisi.

Konsept (knowledge/books/volume_price_divergence.md — BULL-5 / BEAR-5):
  Bullish setup  : Son lookback barda price Lower-Low FAKAT OBV Higher-Low
                   => gizli birikim. Bu lookback icinde bullish engulfing firer
                   => yuksek kaliteli LONG.
  Bearish setup  : Son lookback barda price Higher-High FAKAT OBV Lower-High
                   => gizli dagitim. Bu lookback icinde bearish engulfing firer
                   => yuksek kaliteli SHORT.

Mekanik kurallar (HYP-01 pre-registration esas alinarak):
  1. OBV hesaplama (Granville 1963).
  2. Lookback (default 20) icinde price ve OBV lineer regression slope kontrolu:
       Bullish div  : price slope < 0 (LL) AND obv slope > 0 (HL)
       Bearish div  : price slope > 0 (HH) AND obv slope < 0 (LH)
  3. Ayni lookback icinde bullish/bearish strict engulfing bar var mi?
  4. Engulfing + OBV div konfluensi => sinyal.
  5. Entry : engulfing bar kapanisi (veya sonraki bar acilisi — backtest engine
             bir sonraki bar acilisinda girer).
  6. SL    : engulfing bar'in structural swingu (10-bar lookback).
  7. TP    : 2R.

Sadece filtre olarak da kullanilabilir (filter_with_obv_divergence fonksiyonu):
  Var olan Signal listesini OBV divergence kosuluyla eler.

Lookahead garantisi:
  - OBV hesaplamasi tamamen geri bakan (shift/rolling).
  - Slope hesabi: lookback bar penceresi [t-lookback .. t-1] — shift(1) ile.
  - Engulfing flag: sadece t-1 bar bilgisi (shift(1)).
  - Divergence flag: t aninda [t-lookback..t-1] araligi kullanilir.

Yazim notu: ASCII karakterler kullanildi (Türkçe karakter yok) — encoding
salimligi.
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
    _sr_levels,
)
from price_action.strategies.engulfing_continuation import (
    _strict_engulfing,
    _swing_sl,
)


# =====================================================================
# OBV hesaplama
# =====================================================================

def _compute_obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume (Granville 1963).

    OBV[t] = OBV[t-1] + vol[t]  if close[t] > close[t-1]
    OBV[t] = OBV[t-1] - vol[t]  if close[t] < close[t-1]
    OBV[t] = OBV[t-1]            if close[t] == close[t-1]

    Lookahead-free: her t icin sadece t anindaki close ve volume kullanilir
    (kumulatif sum — geri donuk).
    """
    close = df["close"].to_numpy(dtype=float)
    volume = df["volume"].to_numpy(dtype=float)
    obv = np.zeros(len(close), dtype=float)
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            obv[i] = obv[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            obv[i] = obv[i - 1] - volume[i]
        else:
            obv[i] = obv[i - 1]
    return pd.Series(obv, index=df.index, name="obv")


def _linreg_slope(series: pd.Series, window: int) -> pd.Series:
    """Rolling linear regression slope over `window` bars.

    Lookahead-free: t anindaki slope [t-window..t-1]'i kullanir (shift(1) sonrasi).
    Deger: pozitif = yukselis, negatif = dusus.
    """
    arr = series.to_numpy(dtype=float)
    n = len(arr)
    slopes = np.full(n, np.nan)
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()
    if x_var == 0:
        return pd.Series(slopes, index=series.index)
    for i in range(window, n):
        y = arr[i - window : i]  # [i-window .. i-1] — lookahead yok
        if np.any(np.isnan(y)):
            continue
        y_mean = y.mean()
        slopes[i] = ((x - x_mean) * (y - y_mean)).sum() / x_var
    return pd.Series(slopes, index=series.index)


# =====================================================================
# Divergence detection (vectorized, lookahead-free)
# =====================================================================

def _obv_divergence_flags(
    df: pd.DataFrame,
    lookback: int = 20,
    price_slope_threshold: float = 0.0,
    obv_slope_threshold: float = 0.0,
) -> tuple[pd.Series, pd.Series]:
    """Bullish ve bearish OBV divergence flaglerini hesapla.

    Bullish  div: price slope < price_slope_threshold (LL yapiyor)
                  AND obv slope > obv_slope_threshold  (HL yapiyor)
    Bearish  div: price slope > -price_slope_threshold (HH yapiyor)
                  AND obv slope < -obv_slope_threshold  (LH yapiyor)

    slope degerleri [t-lookback..t-1] uzerinden hesaplanir (shift uygulanmis).
    Min lookback/2 bar veri olmadan NaN => False.

    Returns
    -------
    (bull_div, bear_div) — her ikisi pd.Series[bool], index=df.index
    """
    obv = df["obv"] if "obv" in df.columns else _compute_obv(df)

    # Slope'lar shift(1) edilmis serileri kullanir — ancak _linreg_slope zaten
    # [i-window..i-1] alir, yani t aninda [t-lookback..t-1] => lookahead yok.
    price_slope = _linreg_slope(df["close"], lookback)
    obv_slope = _linreg_slope(obv, lookback)

    bull_div = (price_slope < price_slope_threshold) & (obv_slope > obv_slope_threshold)
    bear_div = (price_slope > -price_slope_threshold) & (obv_slope < -obv_slope_threshold)

    # NaN'lari False'a donustur
    bull_div = bull_div.fillna(False)
    bear_div = bear_div.fillna(False)

    return bull_div.astype(bool), bear_div.astype(bool)


# =====================================================================
# Filter function (standalone, Signal listesine uygulama)
# =====================================================================

def filter_with_obv_divergence(
    signals: list[Signal],
    df: pd.DataFrame,
    *,
    lookback: int = 20,
) -> tuple[list[Signal], int]:
    """Var olan Signal listesini OBV divergence kosuluyla filtrele.

    Bir engulfing sinyalinin ts'ine karsilik gelen bar'da OBV divergence yoksa
    sinyal elenir.

    Parameters
    ----------
    signals:
        Herhangi bir strateji tarafindan uretilmis Signal listesi.
    df:
        OBV hesaplamak icin kullanilacak OHLCV DataFrame (ts kolonu olmali).
    lookback:
        OBV slope hesabi icin pencere boyutu (bar).

    Returns
    -------
    (filtered, n_rejected)
    """
    if not signals:
        return [], 0

    df = df.copy().sort_values("ts").reset_index(drop=True)
    if "obv" not in df.columns:
        df["obv"] = _compute_obv(df)

    bull_div, bear_div = _obv_divergence_flags(df, lookback=lookback)

    # ts -> index map
    ts_to_idx: dict[pd.Timestamp, int] = {
        pd.Timestamp(t): i for i, t in enumerate(df["ts"])
    }

    passed: list[Signal] = []
    n_rejected = 0

    for sig in signals:
        sig_ts = pd.Timestamp(sig.ts)
        idx = ts_to_idx.get(sig_ts)
        if idx is None:
            # Zaman uyusmazligi — konservatif: gecir
            passed.append(sig)
            continue

        if sig.direction == "long" and not bool(bull_div.iat[idx]):
            n_rejected += 1
            continue
        if sig.direction == "short" and not bool(bear_div.iat[idx]):
            n_rejected += 1
            continue

        passed.append(sig)

    logger.bind(
        total=len(signals),
        passed=len(passed),
        rejected=n_rejected,
        lookback=lookback,
    ).info("obv_div_filter.applied")

    return passed, n_rejected


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw: dict[str, Any] = {
        "name": "obv_engulfing_confluence",
        "version": "1.0.0",
        "description": (
            "OBV Divergence + Engulfing Confluence: "
            "price LL + OBV HL (bullish div) ya da price HH + OBV LH (bearish div) "
            "lokasyonunda strict engulfing bar => high-quality entry."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_obv_div_engulfing",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_min": 0.55,
                        "obv_lookback": 20,
                        "engulfing_lookback": 20,
                        "obv_slope_threshold": 0.0,
                    },
                },
                {
                    "id": "bearish_obv_div_engulfing",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_min": 0.55,
                        "obv_lookback": 20,
                        "engulfing_lookback": 20,
                        "obv_slope_threshold": 0.0,
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
                "atr_min_pct": 0.004,
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.5,
            },
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class OBVEngulfingConfluenceStrategy(Strategy):
    """OBV Divergence + Engulfing Confluence.

    Bullish setup:
      - Son obv_lookback barda price slope < 0 (LL) ve OBV slope > 0 (HL)
        => bullish OBV divergence mevcut
      - Ayni pencere icinde strict bullish engulfing bar var
      - Entry: engulfing bar kapanisi (sonraki barda)
      - SL   : engulfing structural (10-bar swing low)
      - TP   : 2R

    Bearish setup: simetrik tersine.
    """

    name = "obv_engulfing_confluence"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # Temel indikatörler
        df["ema20"] = _ema(df["close"], 20)
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)

        # Volume z-score (60 bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # OBV
        df["obv"] = _compute_obv(df)

        # Konfigurasyon
        obv_lookback = 20
        body_ratio_min = 0.55
        obv_slope_thr = 0.0
        for p in self.manifest.signals.patterns:
            if p.id in ("bullish_obv_div_engulfing", "bearish_obv_div_engulfing"):
                obv_lookback = int(p.params.get("obv_lookback", 20))
                body_ratio_min = float(p.params.get("body_ratio_min", 0.55))
                obv_slope_thr = float(p.params.get("obv_slope_threshold", 0.0))
                break

        # OBV divergence flag'leri
        bull_div, bear_div = _obv_divergence_flags(
            df, lookback=obv_lookback,
            price_slope_threshold=obv_slope_thr,
            obv_slope_threshold=obv_slope_thr,
        )
        df["obv_bull_div"] = bull_div
        df["obv_bear_div"] = bear_div

        # Engulfing flag'leri (sadece t-1 kullaniyor — lookahead-free)
        df["strict_bull_engulf"] = _strict_engulfing(df, body_ratio_min=body_ratio_min, bullish=True)
        df["strict_bear_engulf"] = _strict_engulfing(df, body_ratio_min=body_ratio_min, bullish=False)

        # Structural SL
        df["struct_sl_long"] = _swing_sl(df, "long", lookback=10)
        df["struct_sl_short"] = _swing_sl(df, "short", lookback=10)

        # Swing
        n_frac = self.manifest.signals.structure.swing.fractal_n
        sh, sl_frac = _fractal_swings(df, n=n_frac)
        df["swing_high"] = sh
        df["swing_low"] = sl_frac

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "obv" not in df.columns:
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

        # Pattern agirliklar
        bull_weight = 2.0
        bear_weight = 2.0
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "bullish_obv_div_engulfing":
                bull_weight = p.weight
            elif p.id == "bearish_obv_div_engulfing":
                bear_weight = p.weight

        # Temel koşul serileri
        bull_div = df["obv_bull_div"].fillna(False)
        bear_div = df["obv_bear_div"].fillna(False)
        bull_engulf = df["strict_bull_engulf"].fillna(False)
        bear_engulf = df["strict_bear_engulf"].fillna(False)

        # Confluence: OBV div AND engulfing (ayni bar'da)
        long_cond = bull_div & bull_engulf
        short_cond = bear_div & bear_engulf

        long_score = pd.Series(0.0, index=df.index)
        short_score = pd.Series(0.0, index=df.index)
        long_score = long_score.where(~long_cond, bull_weight)
        short_score = short_score.where(~short_cond, bear_weight)

        # 50-EMA trend filter (optional)
        if self.manifest.trend_filter.required:
            up_ok = df["close"] > df["ema50"]
            down_ok = df["close"] < df["ema50"]
            long_score = long_score.where(up_ok, 0.0)
            short_score = short_score.where(down_ok, 0.0)

        # ATR min filter
        atr_min = float(getattr(filters, "atr_min_pct", 0.004) or 0.004)
        if atr_min > 0:
            mask = df["atr_pct"].fillna(0) >= atr_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # S/R seviyeleri (lookahead-free)
        cluster_tol = df["atr14"].fillna(0) * sr_cfg.cluster_atr_multiplier
        sr_records = _sr_levels(
            df,
            lookback_bars=sr_cfg.lookback_bars,
            cluster_tol=cluster_tol,
            min_touches=sr_cfg.min_touches,
        )
        sr_by_bar: dict[int, list[float]] = {}
        for i_sr, lvl, _t in sr_records:
            sr_by_bar.setdefault(i_sr, []).append(lvl)

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

            # S/R proximity
            levels = sr_by_bar.get(i, [])
            near_sr = False
            if levels and proximity_atr > 0:
                tol = proximity_atr * atr
                near_sr = any(abs(close - lvl) <= tol for lvl in levels)

            for direction, score_series, pid in (
                ("long", long_score, "bullish_obv_div_engulfing"),
                ("short", short_score, "bearish_obv_div_engulfing"),
            ):
                base_score = float(score_series.iat[i])
                if base_score <= 0:
                    continue
                final_score = base_score + (bonus if near_sr else 0.0)
                if final_score < min_score:
                    continue

                # Structural SL
                if direction == "long":
                    sl_price = float(row.get("struct_sl_long") or (close - 2.0 * atr))
                    if np.isnan(sl_price) or sl_price <= 0:
                        sl_price = close - 2.0 * atr
                    sl_price = min(sl_price, close - 0.5 * atr)
                    risk = close - sl_price
                    if risk <= 0:
                        continue
                    tp_price = close + primary_R * risk
                else:
                    sl_price = float(row.get("struct_sl_short") or (close + 2.0 * atr))
                    if np.isnan(sl_price) or sl_price <= 0:
                        sl_price = close + 2.0 * atr
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
                    direction=direction,
                    pattern_id=pid,
                    confluence_score=float(final_score),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "obv_bull_div": bool(row.get("obv_bull_div", False)),
                        "obv_bear_div": bool(row.get("obv_bear_div", False)),
                        "atr14": atr,
                        "near_sr": near_sr,
                        "ema50": float(row.get("ema50") or 0.0),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("obv_engulfing_conf.signals.generated")
        return out
