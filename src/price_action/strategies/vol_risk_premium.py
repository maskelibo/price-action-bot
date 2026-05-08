"""Volatility Risk Premium Fade stratejisi.

Konsept (Sinclair VRP + Harris Microstructure + Chan GARCH):
  - Kripto icin VIX proxy: 14-bar gerçekleşmiş volatilite (log-return std × sqrt(N))
  - RV 95. yüzdeliğe (son 90 bar) ulaştığında piyasa "korku premium" ödüyor
  - Bir sonraki bar inside-bar veya doji ise: vol kontraksiyon konfirmasyonu
  - Sinyal: spike yönünün TERSİ (fade), çünkü vol ortalamaya döner, price devam edebilir
  - Neden price-based mean-rev'den farklı: Volatilite dağılımı GARCH ile mean-reverting;
    fiyat dağılımı trending dönemlerde shift eder. Farklı mekanizma.

Kural özeti:
  SPIKE BAR   : ATR%[t-1] > 2x rolling-30-bar ATR% median
  DIRECTION   : bullish_spike (close>open, body>0.6*range) → SHORT fade
                bearish_spike (open>close, body>0.6*range) → LONG fade
  CONFIRM     : t barında inside-bar (high<t-1.high, low>t-1.low) OR
                doji (body < 0.1 × range)
  ENTRY       : t+1 bar açılışı
  SL          : spike extreme + 1 ATR buffer
                (spike_high + atr for SHORT, spike_low - atr for LONG)
  TP          : 1.5R (volatilite fade hızlı ama sınırlı)

Lookahead-free: tüm hesaplamalar shift(1) veya rolling([..:t-1]) ile.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr


# =====================================================================
# Yardımcı fonksiyonlar
# =====================================================================

def _realized_vol(close: pd.Series, lookback: int = 14) -> pd.Series:
    """Rolling gerçekleşmiş volatilite: log-return std × sqrt(lookback).

    Formül: RV_t = std(log(P_t / P_{t-1}), window=lookback) × sqrt(lookback)
    Lookahead-free: t anında [t-lookback..t-1] kullanılır (shift(1)+rolling).

    Returns: Annualized olmayan, period-ölçeğinde RV (0-1 arası tipik değer).
    """
    log_ret = np.log(close / close.shift(1))
    # shift(1) → t anında t-1'e kadar olan logret kullanılır
    rv = log_ret.shift(1).rolling(lookback, min_periods=max(2, lookback // 2)).std() * np.sqrt(lookback)
    return rv.fillna(0.0)


def _rv_percentile(rv: pd.Series, window: int = 90) -> pd.Series:
    """Rolling percentile rank: RV'nin son `window` bardaki sırası (0-1).

    t anında RV[t] değerinin [t-window..t-1] içindeki yüzdelik sırası.
    Lookahead-free: percent_rank shift(1)+rolling ile hesaplanır.
    """
    def _prank(x: np.ndarray) -> float:
        """x[-1] değerinin x dizisindeki percentile rank'i."""
        if len(x) < 2:
            return 0.5
        val = x[-1]
        return float(np.sum(x[:-1] < val) / max(1, len(x) - 1))

    # RV'yi shift(1) yaparak t anında t-1 değerini kullanıyoruz
    rv_shifted = rv.shift(1)
    result = rv_shifted.rolling(window + 1, min_periods=max(5, window // 4)).apply(
        _prank, raw=True
    )
    return result.fillna(0.5)


def _vol_contraction_signal(df: pd.DataFrame) -> pd.Series:
    """Inside-bar VEYA doji tespiti — bir önceki bar spike ise konfirmasyon.

    Inside-bar: current high < prev high AND current low > prev low
    Doji       : |close - open| < 0.10 × (high - low)

    Lookahead-free: her iki koşul da yalnızca t (current) ve t-1 (shift) kullanır.
    Sinyal t anında True ise, entry t+1 açılışında yapılır.
    """
    prev_high = df["high"].shift(1)
    prev_low = df["low"].shift(1)

    # Inside-bar
    inside = (df["high"] < prev_high) & (df["low"] > prev_low)

    # Doji: body / range < 0.10
    body = (df["close"] - df["open"]).abs()
    rng = (df["high"] - df["low"]).replace(0.0, np.nan)
    doji = (body / rng) < 0.10

    contraction = inside | doji
    return contraction.fillna(False)


def _atr_pct(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR / close — normalize edilmiş ATR yüzdesi."""
    atr = _atr(df, period)
    return atr / df["close"].replace(0.0, np.nan)


def _atr_median(atr_pct: pd.Series, window: int = 30) -> pd.Series:
    """Son `window` barin ATR% medyanı.

    Lookahead-free: shift(1) + rolling ile t anında [t-window..t-1] medyanı.
    """
    return atr_pct.shift(1).rolling(window, min_periods=max(5, window // 3)).median()


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "vol_risk_premium",
        "version": "1.0.0",
        "description": "Volatility Risk Premium Fade: sell vol when it spikes (Sinclair + Harris + Chan)",
        "trend_filter": {"type": "none", "period": 1, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "vol_fade_short",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "rv_lookback": 14,
                        "rv_pct_window": 90,
                        "spike_atr_mult": 2.0,
                        "spike_body_ratio": 0.6,
                        "atr_median_window": 30,
                        "rv_pct_threshold": 0.95,
                    },
                },
                {
                    "id": "vol_fade_long",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "rv_lookback": 14,
                        "rv_pct_window": 90,
                        "spike_atr_mult": 2.0,
                        "spike_body_ratio": 0.6,
                        "atr_median_window": 30,
                        "rv_pct_threshold": 0.95,
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
            "stop_loss": {
                "method": "structural_atr",
                "atr_buffer": 1.0,
            },
            "take_profit": {
                "method": "r_multiple",
                "primary_R": 1.5,
            },
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

class VolRiskPremiumStrategy(Strategy):
    """Volatility Risk Premium Fade stratejisi.

    Mantık:
      1. SPIKE_BAR tespit: t-1 barında ATR%[t-1] > spike_atr_mult × ATR%_median30[t-1]
         VE RV_pct_rank[t-1] > rv_pct_threshold (95. yüzdelik)
      2. Spike yönü: bullish_spike (close>open, body_ratio >= 0.6) → fade = SHORT
                     bearish_spike (open>close, body_ratio >= 0.6) → fade = LONG
      3. CONTRACTION: t barında inside-bar OR doji
      4. Entry: t+1 bar açılışında (sinyal t'de üretilir, execution t+1'de)
      5. SL   : spike extreme ± 1 ATR buffer
      6. TP   : 1.5R
    """

    name = "vol_risk_premium"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # --- Parametre okuma ---
        rv_lookback = 14
        rv_pct_window = 90
        spike_atr_mult = 2.0
        spike_body_ratio = 0.6
        atr_median_window = 30
        rv_pct_threshold = 0.95
        for p in self.manifest.signals.patterns:
            if p.id in ("vol_fade_short", "vol_fade_long"):
                rv_lookback = int(p.params.get("rv_lookback", 14))
                rv_pct_window = int(p.params.get("rv_pct_window", 90))
                spike_atr_mult = float(p.params.get("spike_atr_mult", 2.0))
                spike_body_ratio = float(p.params.get("spike_body_ratio", 0.6))
                atr_median_window = int(p.params.get("atr_median_window", 30))
                rv_pct_threshold = float(p.params.get("rv_pct_threshold", 0.95))
                break

        # --- ATR ---
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = _atr_pct(df, 14)
        df["atr_pct_median_30"] = _atr_median(df["atr_pct"], window=atr_median_window)

        # --- Realized vol & percentile rank ---
        df["realized_vol_14"] = _realized_vol(df["close"], lookback=rv_lookback)
        df["rv_pct_rank"] = _rv_percentile(df["realized_vol_14"], window=rv_pct_window)

        # --- Spike ratio: ATR%[t] / ATR%_median30[t] ---
        # Lookahead-free: atr_pct ve atr_pct_median_30 her ikisi de shift ile hesaplı
        df["spike_ratio"] = df["atr_pct"] / df["atr_pct_median_30"].replace(0.0, np.nan)

        # --- Spike bar detection (t-1 bilgisini t anında kullanmak için shift) ---
        # spike_bar_flag[t] = True → t-1 barı spike barıydı
        prev_atr_pct = df["atr_pct"].shift(1)
        prev_median = df["atr_pct_median_30"].shift(1)
        prev_rv_pct = df["rv_pct_rank"].shift(1)

        prev_spike_by_atr = prev_atr_pct > (spike_atr_mult * prev_median)
        prev_spike_by_rv = prev_rv_pct >= rv_pct_threshold

        # Spike barının yönü: t-1 barı
        prev_o = df["open"].shift(1)
        prev_c = df["close"].shift(1)
        prev_h = df["high"].shift(1)
        prev_l = df["low"].shift(1)
        prev_body = (prev_c - prev_o).abs()
        prev_range = (prev_h - prev_l).replace(0.0, np.nan)
        prev_body_ratio = prev_body / prev_range

        # Bullish spike: close > open (yeşil bar), büyük body
        prev_bullish_spike = (prev_c > prev_o) & (prev_body_ratio >= spike_body_ratio)
        # Bearish spike: open > close (kırmızı bar), büyük body
        prev_bearish_spike = (prev_o > prev_c) & (prev_body_ratio >= spike_body_ratio)

        # Spike bar flag (hem ATR hem RV koşulu)
        spike_ok = prev_spike_by_atr & prev_spike_by_rv

        df["spike_bar_prev"] = spike_ok.fillna(False)
        df["prev_bullish_spike"] = (spike_ok & prev_bullish_spike).fillna(False)
        df["prev_bearish_spike"] = (spike_ok & prev_bearish_spike).fillna(False)

        # Spike high/low (t-1 barın extremes — SL için)
        df["spike_high"] = df["high"].shift(1)   # SHORT için SL: spike_high + atr_buffer
        df["spike_low"] = df["low"].shift(1)     # LONG için SL:  spike_low  - atr_buffer

        # --- Contraction signal (t barı için) ---
        df["contraction_flag"] = _vol_contraction_signal(df)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "contraction_flag" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        confluence = signals_cfg.confluence

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 1.5)
        )
        atr_buffer = float(
            self.manifest.risk.get("stop_loss", {}).get("atr_buffer", 1.0)
        )
        min_score = float(confluence.min_score)
        atr_min = float(getattr(signals_cfg.filters, "atr_min_pct", 0.003) or 0.003)

        # Pattern weight
        weight = 1.5
        for p in signals_cfg.patterns:
            if p.id in ("vol_fade_short", "vol_fade_long") and p.enabled:
                weight = p.weight
                break

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

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

            contraction = bool(row.get("contraction_flag", False))
            if not contraction:
                continue

            prev_bull_spike = bool(row.get("prev_bullish_spike", False))
            prev_bear_spike = bool(row.get("prev_bearish_spike", False))

            spike_high = float(row.get("spike_high") or np.nan)
            spike_low = float(row.get("spike_low") or np.nan)

            rv14 = float(row.get("realized_vol_14") or 0.0)
            rv_pct = float(row.get("rv_pct_rank") or 0.0)
            spike_ratio = float(row.get("spike_ratio") or 0.0)

            ts = pd.Timestamp(row["ts"]).to_pydatetime()

            # ------ SHORT signal: bullish spike → fade (short) ------
            if prev_bull_spike and weight >= min_score:
                if np.isnan(spike_high) or spike_high <= 0:
                    sl_price = close + 2.0 * atr
                else:
                    sl_price = spike_high + atr_buffer * atr
                sl_price = max(sl_price, close + 0.5 * atr)
                risk = sl_price - close
                if risk <= 0:
                    continue
                tp_price = close - primary_R * risk

                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="short",
                    pattern_id="vol_fade_short",
                    confluence_score=float(weight),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "realized_vol_14": rv14,
                        "rv_pct_rank": rv_pct,
                        "spike_ratio": spike_ratio,
                        "spike_high": spike_high,
                        "atr14": atr,
                        "fade_type": "bullish_spike_short",
                    },
                )
                out.append(sig)

            # ------ LONG signal: bearish spike → fade (long) ------
            if prev_bear_spike and weight >= min_score:
                if np.isnan(spike_low) or spike_low <= 0:
                    sl_price = close - 2.0 * atr
                else:
                    sl_price = spike_low - atr_buffer * atr
                sl_price = min(sl_price, close - 0.5 * atr)
                if sl_price <= 0:
                    continue
                risk = close - sl_price
                if risk <= 0:
                    continue
                tp_price = close + primary_R * risk

                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="long",
                    pattern_id="vol_fade_long",
                    confluence_score=float(weight),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "realized_vol_14": rv14,
                        "rv_pct_rank": rv_pct,
                        "spike_ratio": spike_ratio,
                        "spike_low": spike_low,
                        "atr14": atr,
                        "fade_type": "bearish_spike_long",
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=n).info("vol_risk_premium.signals.generated")
        return out
