"""CVD Spike Fade stratejisi — OBV z-score proxy ile.

Konsept (HYP-02, volume_price_divergence.md §3.1 / §5):
  Kripto perpetual'da Cumulative Volume Delta (CVD) = buy_volume - sell_volume.
  Aşırı pozitif/negatif spike → retail FOMO/panic → ortalamaya dönüş fırsatı.

Veri kısıtı:
  Gerçek CVD tick-level data ücretli API gerektirir. Bu implementasyon
  OBV (On-Balance Volume) z-score'unu CVD spike proxy olarak kullanır.
  OBV formülü (Granville, 1963):
    OBV[t] = OBV[t-1] + Vol[t]  if Close[t] > Close[t-1]
    OBV[t] = OBV[t-1] - Vol[t]  if Close[t] < Close[t-1]
    OBV[t] = OBV[t-1]           if Close[t] = Close[t-1]

  OBV z-score = (OBV[t] - mean_OBV_30) / std_OBV_30
  Bu değer CVD z-score'un doğrusal yaklaşımı olarak kabul edilir; gerçek
  buy/sell ayrımı yerine net kapanış yönüne dayalı hacim akışı gösterir.

Pattern (mekanik, tamamen lookahead-free):
  SHORT sinyali:
    1. OBV z-score (30-bar rolling) > +2.5σ  → extreme bullish spike
    2. Confirmation bar: bearish engulfing (N-1 bullish, N bearish, body_ratio ≥ 0.5)
    3. Entry: confirmation bar kapanışında sinyal üretilir; backtest motoru N+1 açılışta girer
    4. SL: 1 ATR yukarı
    5. TP: 1.5R aşağı

  LONG sinyali:
    1. OBV z-score < -2.5σ  → extreme bearish spike
    2. Confirmation bar: bullish engulfing
    3. Entry / SL / TP: simetrik

Konfigürasyon (manifest parametreleri):
  obv_lookback   : OBV z-score rolling pencere (default: 30)
  zscore_thresh  : Eşik değeri (default: 2.5)
  atr_sl_mult    : SL = entry ± atr_sl_mult * ATR (default: 1.0)
  tp_r_multiple  : TP = entry ± tp_r_multiple * risk (default: 1.5)
  body_ratio_min : Confirmation engulfing body oranı (default: 0.5)
  atr_period     : ATR periyodu (default: 14)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema


# =====================================================================
# OBV hesaplama
# =====================================================================

def _obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume (Granville, 1963) — tamamen lookahead-free.

    CVD proxy: gerçek taker buy/sell yerine kapanış yönüne göre hacim biriktirme.
    """
    close = df["close"].to_numpy()
    volume = df["volume"].to_numpy()
    n = len(close)
    obv = np.zeros(n, dtype=float)
    for i in range(1, n):
        if close[i] > close[i - 1]:
            obv[i] = obv[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            obv[i] = obv[i - 1] - volume[i]
        else:
            obv[i] = obv[i - 1]
    return pd.Series(obv, index=df.index, name="obv")


def _obv_zscore(obv: pd.Series, lookback: int = 30) -> pd.Series:
    """Rolling z-score of OBV over `lookback` bars.

    z[t] = (OBV[t] - mean(OBV[t-lookback..t])) / std(OBV[t-lookback..t])

    NOT: rolling() pandas'ta son `lookback` barı (t dahil) kullanır.
    Burada OBV'nin z-score'u alınırken t anındaki OBV değeri de kullanılır;
    bu lookahead değildir çünkü t anındaki OBV zaten t kapanışından sonra
    hesaplanmış olur ve sinyal t kapanışında (t+1 açılışı öncesinde) üretilir.
    """
    mean = obv.rolling(lookback, min_periods=max(2, lookback // 2)).mean()
    std = obv.rolling(lookback, min_periods=max(2, lookback // 2)).std(ddof=0)
    z = (obv - mean) / std.replace(0, np.nan)
    return z.fillna(0.0)


# =====================================================================
# Confirmation bar: engulfing
# =====================================================================

def _bearish_engulfing(df: pd.DataFrame, body_ratio_min: float = 0.5) -> pd.Series:
    """Bearish reversal confirmation bar.

    Koşullar:
      - N-1 bar: bullish (close > open)
      - N bar: bearish (close < open)
      - N bar body tamamen N-1 bar body'sini sarar (strict)
      - N bar body / total_range >= body_ratio_min

    Lookahead-free: yalnızca shift(1) (t-1 bilgisi) kullanılır.
    """
    o = df["open"]
    c = df["close"]
    prev_o = o.shift(1)
    prev_c = c.shift(1)
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    body_abs = (o - c).abs()  # bearish: o > c
    body_ratio = body_abs / rng

    prev_bullish = prev_c > prev_o          # N-1 bullish
    curr_bearish = c < o                    # N bearish
    engulfs = (o >= prev_c) & (c <= prev_o)  # strict wrap
    ratio_ok = body_ratio >= body_ratio_min

    result = prev_bullish & curr_bearish & engulfs & ratio_ok
    return result.fillna(False)


def _bullish_engulfing(df: pd.DataFrame, body_ratio_min: float = 0.5) -> pd.Series:
    """Bullish reversal confirmation bar — simetrik."""
    o = df["open"]
    c = df["close"]
    prev_o = o.shift(1)
    prev_c = c.shift(1)
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    body_abs = (c - o).abs()
    body_ratio = body_abs / rng

    prev_bearish = prev_c < prev_o
    curr_bullish = c > o
    engulfs = (o <= prev_c) & (c >= prev_o)
    ratio_ok = body_ratio >= body_ratio_min

    result = prev_bearish & curr_bullish & engulfs & ratio_ok
    return result.fillna(False)


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "cvd_spike_fade",
        "version": "1.0.0",
        "description": (
            "OBV z-score spike fade: extreme OBV z-score (>2.5σ) + "
            "reversal confirmation bar → mean-reversion trade."
        ),
        "trend_filter": {"type": "none", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "obv_spike_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "obv_lookback": 30,
                        "zscore_thresh": 2.5,
                        "body_ratio_min": 0.5,
                    },
                },
                {
                    "id": "obv_spike_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "obv_lookback": 30,
                        "zscore_thresh": 2.5,
                        "body_ratio_min": 0.5,
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
            "stop_loss": {"method": "atr", "atr_mult": 1.0},
            "take_profit": {"method": "r_multiple", "tp_r": 1.5},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 60,
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10_000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy
# =====================================================================

class CVDSpikeFadeStrategy(Strategy):
    """OBV-proxy CVD Spike Fade — mean-reversion at extreme volume delta spikes.

    OBV z-score > +threshold → short (fade bullish spike)
    OBV z-score < -threshold → long  (fade bearish spike)
    Confirmation bar: reversal engulfing (lookahead-free).

    Veri notu:
      Gerçek CVD için tick-level buy/sell ayrımı gerekir (ücretli API).
      Bu implementasyon OBV'yi CVD proxy olarak kullanır; akademik
      literatüre göre OBV tek başına zayıf edge'e sahip olup burada
      reversal bar confirmation ile filtrelenmektedir.
    """

    name = "cvd_spike_fade"

    # ----- params -----
    @property
    def _cfg(self) -> dict[str, Any]:
        """İlk pattern'dan ortak parametreler."""
        for p in self.manifest.signals.patterns:
            return p.params
        return {}

    @property
    def _obv_lookback(self) -> int:
        return int(self._cfg.get("obv_lookback", 30))

    @property
    def _zscore_thresh(self) -> float:
        return float(self._cfg.get("zscore_thresh", 2.5))

    @property
    def _body_ratio_min(self) -> float:
        return float(self._cfg.get("body_ratio_min", 0.5))

    @property
    def _atr_sl_mult(self) -> float:
        return float(self.manifest.risk.get("stop_loss", {}).get("atr_mult", 1.0))

    @property
    def _tp_r(self) -> float:
        return float(self.manifest.risk.get("take_profit", {}).get("tp_r", 1.5))

    @property
    def _atr_period(self) -> int:
        return 14

    @property
    def _atr_min_pct(self) -> float:
        return float(getattr(self.manifest.signals.filters, "atr_min_pct", 0.003) or 0.003)

    # ----- prepare_features -----

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # ATR
        df["atr14"] = _atr(df, self._atr_period)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)

        # OBV + z-score (CVD proxy)
        df["obv"] = _obv(df)
        df["obv_zscore"] = _obv_zscore(df["obv"], lookback=self._obv_lookback)

        # Confirmation bars
        df["bear_confirm"] = _bearish_engulfing(df, body_ratio_min=self._body_ratio_min)
        df["bull_confirm"] = _bullish_engulfing(df, body_ratio_min=self._body_ratio_min)

        # Spike flags (current bar's z-score, no shift needed —
        # spike is evaluated at end of bar, signal fires same close)
        # OBV spike at t-1 (so that confirmation bar at t can use it)
        df["obv_z_lag1"] = df["obv_zscore"].shift(1)

        # EMA50 (opsiyonel trend context — metadata olarak kaydedilir)
        df["ema50"] = _ema(df["close"], 50)

        return df

    # ----- generate_signals -----

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "obv_zscore" not in df.columns:
            df = self.prepare_features(df)

        # Gerekli kolonlar yoksa çık
        required = ["obv_zscore", "obv_z_lag1", "bear_confirm", "bull_confirm", "atr14"]
        for col in required:
            if col not in df.columns:
                self._log.warning(f"cvd_spike_fade.missing_column.{col}")
                return []

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        thresh = self._zscore_thresh
        atr_sl = self._atr_sl_mult
        tp_r = self._tp_r
        atr_min_pct = self._atr_min_pct

        out: list[Signal] = []

        for i in range(1, len(df) - 1):  # -1: giriş için N+1 bar gerekir
            row = df.iloc[i]
            atr = float(row.get("atr14") or 0.0)
            close = float(row["close"])
            if atr <= 0 or np.isnan(atr):
                continue
            if atr / close < atr_min_pct:
                continue

            # OBV z-score lag-1 = confirmation bar önceki barın z-score'u
            # Spike pattern: spike bar (i-1) + confirmation bar (i)
            # NOT: obv_z_lag1[i] = obv_zscore[i-1]
            z_prev = float(row.get("obv_z_lag1") or 0.0)
            if np.isnan(z_prev):
                continue

            # --- SHORT: extreme bullish OBV spike + bearish engulfing confirmation ---
            if z_prev >= thresh and bool(row.get("bear_confirm", False)):
                sl_price = close + atr_sl * atr
                risk = sl_price - close
                if risk <= 0:
                    continue
                tp_price = close - tp_r * risk

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="short",
                    pattern_id="obv_spike_short",
                    confluence_score=float(abs(z_prev) / thresh) * 2.0,
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=atr_sl,
                    metadata={
                        "obv_zscore_prev": z_prev,
                        "obv_zscore_curr": float(row.get("obv_zscore") or 0.0),
                        "atr14": atr,
                        "ema50": float(row.get("ema50") or 0.0),
                        "bar_idx": i,
                        "proxy_type": "obv_zscore",
                    },
                )
                out.append(sig)

            # --- LONG: extreme bearish OBV spike + bullish engulfing confirmation ---
            elif z_prev <= -thresh and bool(row.get("bull_confirm", False)):
                sl_price = close - atr_sl * atr
                risk = close - sl_price
                if risk <= 0:
                    continue
                tp_price = close + tp_r * risk

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="long",
                    pattern_id="obv_spike_long",
                    confluence_score=float(abs(z_prev) / thresh) * 2.0,
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=atr_sl,
                    metadata={
                        "obv_zscore_prev": z_prev,
                        "obv_zscore_curr": float(row.get("obv_zscore") or 0.0),
                        "atr14": atr,
                        "ema50": float(row.get("ema50") or 0.0),
                        "bar_idx": i,
                        "proxy_type": "obv_zscore",
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("cvd_spike_fade.signals.generated")
        return out


# =====================================================================
# Convenience factory
# =====================================================================

def build_strategy(overrides: dict[str, Any] | None = None) -> CVDSpikeFadeStrategy:
    """Default manifest ile CVDSpikeFadeStrategy oluştur.

    `overrides`: manifest dict'ine üst seviyede merge edilecek dict.
    """
    manifest = _default_manifest()
    if overrides:
        raw = manifest.model_dump()
        raw.update(overrides)
        manifest = StrategyManifest.model_validate(raw)
    return CVDSpikeFadeStrategy(manifest)


__all__ = [
    "CVDSpikeFadeStrategy",
    "build_strategy",
    "_default_manifest",
    "_obv",
    "_obv_zscore",
    "_bearish_engulfing",
    "_bullish_engulfing",
]
