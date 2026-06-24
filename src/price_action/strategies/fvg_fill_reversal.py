"""Fair Value Gap (FVG) Fill + Reversal stratejisi.

Konsept:
  - 3-bar imbalance:
      Bullish FVG = bar[t-2].high < bar[t].low  (gap, fiyat asagiyi atladi)
      Bearish FVG = bar[t-2].low  > bar[t].high (gap, fiyat yukariyi atladi)
  - Bullish FVG taban araligi: [bar[t-2].high, bar[t].low]
    Bearish FVG taban araligi: [bar[t].high,   bar[t-2].low]
  - Tetik (mean reversion / fill): Sonraki barlardan birinin low'u FVG icine
    girip close'u FVG icinde veya tersine kapanir.

Bu stratejide "FILL + REVERSAL" varyantini implement ediyoruz:
  Bullish FVG (boslugu doldur, sonra alttan yukari donus):
     - Bar t'de FVG olusur (bull, ust=bar[t].low, alt=bar[t-2].high)
     - Sonraki `fill_window` barda fiyat FVG icine girip
       close > FVG_alt (bullish reclaim) yapar -> LONG sinyali

  Bearish FVG (mirror): SHORT sinyali

Kurallar:
  - Trend filtresi: opsiyonel (default OFF — FVG kendi basina mean-reversion edge)
  - Entry: tetik bar kapanisi sonrasi t+1 acilis
  - SL: bullish icin FVG_alt - 0.5*ATR; bearish icin FVG_ust + 0.5*ATR
  - TP: 2.0R
  - Cooldown: ayni FVG'den tekrar tetiklenmemek icin 5 bar

Lookahead-free: tum hesaplamalar shift(2) ile gecmis bar bilgisi.
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
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "fvg_fill_reversal",
        "version": "1.0.0",
        "description": (
            "Fair Value Gap (3-bar imbalance) fill + reclaim reversal. "
            "Long on bullish FVG fill+reclaim, short on bearish."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "fvg_bull_reclaim_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "fill_window": 10,
                        "min_gap_atr": 0.20,
                        "sl_atr_mult": 0.5,
                        "tp_r_multiple": 2.0,
                        "cooldown_bars": 5,
                    },
                },
                {
                    "id": "fvg_bear_reclaim_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "fill_window": 10,
                        "min_gap_atr": 0.20,
                        "sl_atr_mult": 0.5,
                        "tp_r_multiple": 2.0,
                        "cooldown_bars": 5,
                    },
                },
            ],
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
            "take_profit": {"primary_R": 2.0},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class FVGFillReversalStrategy(Strategy):
    """Fair Value Gap fill + reclaim reversal."""

    name = "fvg_fill_reversal"

    def _get_param(self, pattern_id: str, key: str, default: Any) -> Any:
        for p in self.manifest.signals.patterns:
            if p.id == pattern_id:
                return p.params.get(key, default)
        return default

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        df["ema50"] = _ema(df["close"], 50)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # 3-bar FVG detection (lookahead-free, shift(2))
        h_prev2 = df["high"].shift(2)
        l_prev2 = df["low"].shift(2)
        # Bullish FVG: bar[t-2].high < bar[t].low; gap range = [h_prev2, low]
        bull_fvg_mask = (h_prev2 < df["low"])
        # Bearish FVG: bar[t-2].low > bar[t].high; gap range = [high, l_prev2]
        bear_fvg_mask = (l_prev2 > df["high"])

        df["fvg_bull_top"] = np.where(bull_fvg_mask, df["low"], np.nan)
        df["fvg_bull_bot"] = np.where(bull_fvg_mask, h_prev2, np.nan)
        df["fvg_bear_top"] = np.where(bear_fvg_mask, l_prev2, np.nan)
        df["fvg_bear_bot"] = np.where(bear_fvg_mask, df["high"], np.nan)

        # Volume z (60-bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "fvg_bull_top" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        fill_window = int(self._get_param("fvg_bull_reclaim_long", "fill_window", 10))
        min_gap_atr = float(self._get_param("fvg_bull_reclaim_long", "min_gap_atr", 0.20))
        sl_atr_mult = float(self._get_param("fvg_bull_reclaim_long", "sl_atr_mult", 0.5))
        tp_r = float(self._get_param("fvg_bull_reclaim_long", "tp_r_multiple", 2.0))
        cooldown = int(self._get_param("fvg_bull_reclaim_long", "cooldown_bars", 5))

        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "fvg_bull_reclaim_long"), 2.0)
        short_w = next((p.weight for p in signals_cfg.patterns if p.id == "fvg_bear_reclaim_short"), 2.0)

        atr_min_pct = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        opens   = df["open"].to_numpy(dtype=float)
        highs   = df["high"].to_numpy(dtype=float)
        lows    = df["low"].to_numpy(dtype=float)
        closes  = df["close"].to_numpy(dtype=float)
        atrs    = df["atr14"].to_numpy(dtype=float)
        atr_pct = df["atr_pct"].to_numpy(dtype=float)
        bull_top = df["fvg_bull_top"].to_numpy(dtype=float)
        bull_bot = df["fvg_bull_bot"].to_numpy(dtype=float)
        bear_top = df["fvg_bear_top"].to_numpy(dtype=float)
        bear_bot = df["fvg_bear_bot"].to_numpy(dtype=float)
        ts_arr   = df["ts"].to_numpy()
        n = len(df)

        out: list[Signal] = []
        last_long_ts = -99
        last_short_ts = -99

        # Active FVG'leri takip et: yakin zamanli olanlar
        # Performance icin: her bar t'de son `fill_window` barlik FVG aktif
        for t in range(2, n):
            atr_t = atrs[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and not np.isnan(atr_pct[t]) and atr_pct[t] < atr_min_pct:
                continue

            # ----- LONG: bullish FVG fill+reclaim -----
            if t > last_long_ts + cooldown:
                # Son `fill_window` barda olusan bullish FVG'leri ara
                for fvg_idx in range(max(2, t - fill_window), t):
                    fvg_top = bull_top[fvg_idx]
                    fvg_bot = bull_bot[fvg_idx]
                    if np.isnan(fvg_top) or np.isnan(fvg_bot):
                        continue
                    gap_size = fvg_top - fvg_bot
                    if gap_size <= 0:
                        continue
                    # Min gap size icin ATR (gap olustugundaki ATR)
                    fvg_atr = atrs[fvg_idx]
                    if np.isnan(fvg_atr) or fvg_atr <= 0:
                        continue
                    if gap_size < min_gap_atr * fvg_atr:
                        continue
                    # Fill: bar t low fvg icine girdi mi?
                    if lows[t] > fvg_top:
                        continue  # daha doldurmadi
                    # Reclaim: close > fvg_bot (alt sinirin uzerine geri kapatti)
                    if closes[t] <= fvg_bot:
                        continue
                    # Sinyal
                    sl_price = fvg_bot - sl_atr_mult * atr_t
                    entry_ref = closes[t]
                    risk = entry_ref - sl_price
                    if risk <= 0:
                        continue
                    tp_price = entry_ref + tp_r * risk
                    score = long_w
                    if score < min_score:
                        continue
                    sig = self.emit_signal(
                        ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                        venue=venue, symbol=symbol, timeframe=timeframe,
                        direction="long",
                        pattern_id="fvg_bull_reclaim_long",
                        confluence_score=float(score),
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=1.0,
                        metadata={
                            "fvg_top": float(fvg_top),
                            "fvg_bot": float(fvg_bot),
                            "fvg_idx": int(fvg_idx),
                            "bars_since_fvg": int(t - fvg_idx),
                            "gap_atr": float(gap_size / fvg_atr),
                        },
                    )
                    out.append(sig)
                    last_long_ts = t
                    break

            # ----- SHORT: bearish FVG fill+reclaim -----
            if t > last_short_ts + cooldown:
                for fvg_idx in range(max(2, t - fill_window), t):
                    fvg_top = bear_top[fvg_idx]
                    fvg_bot = bear_bot[fvg_idx]
                    if np.isnan(fvg_top) or np.isnan(fvg_bot):
                        continue
                    gap_size = fvg_top - fvg_bot
                    if gap_size <= 0:
                        continue
                    fvg_atr = atrs[fvg_idx]
                    if np.isnan(fvg_atr) or fvg_atr <= 0:
                        continue
                    if gap_size < min_gap_atr * fvg_atr:
                        continue
                    # Fill: bar t high fvg icine girdi mi?
                    if highs[t] < fvg_bot:
                        continue
                    # Reclaim: close < fvg_top (ust sinirin altina geri kapatti)
                    if closes[t] >= fvg_top:
                        continue
                    sl_price = fvg_top + sl_atr_mult * atr_t
                    entry_ref = closes[t]
                    risk = sl_price - entry_ref
                    if risk <= 0:
                        continue
                    tp_price = entry_ref - tp_r * risk
                    score = short_w
                    if score < min_score:
                        continue
                    sig = self.emit_signal(
                        ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                        venue=venue, symbol=symbol, timeframe=timeframe,
                        direction="short",
                        pattern_id="fvg_bear_reclaim_short",
                        confluence_score=float(score),
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=1.0,
                        metadata={
                            "fvg_top": float(fvg_top),
                            "fvg_bot": float(fvg_bot),
                            "fvg_idx": int(fvg_idx),
                            "bars_since_fvg": int(t - fvg_idx),
                            "gap_atr": float(gap_size / fvg_atr),
                        },
                    )
                    out.append(sig)
                    last_short_ts = t
                    break

        self._log.bind(n=len(out), bars=len(df)).info("fvg_fill_reversal.signals.generated")
        return out
