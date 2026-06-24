"""VSA Buying Climax — Dedicated Short-Only (S3-A).

PHOENIX-SCALP v2.1 / SEC47 / D5-sec49 (CEO master plan 2026-05-17).

Bu strateji `vsa_climax_test`'in mirror short variant'idir AMA mekanik olarak
**farkli**: existing strateji BC sonrasi 3-15 bar bekler ve Up Thrust arar.
Bu strateji **immediate distribution test** mekanigi kullanir:

  1. Buying Climax bari (BC): yuksek hacim + buyuk UST golge + close lower
     half + 5-bar maximum high.
  2. Distribution test: BC sonraki bar(lar) **yeni high yapamaz** — close <
     BC high. Bu hizli "failure to follow through" sinyalidir.
  3. Confirmation pencere: 3-5 bar icinde lower-low yapilir AND RSI(14) < 70
     (overbought'tan cikmis).
  4. Entry: confirmation bar acilisinda SHORT (.shift(1) ile next bar open).
  5. SL: BC bar high + 0.5*ATR.
  6. TP: 1.5R primary / 2.5R extended.

Mirror gerekce: existing vsa_climax_test 15m'de mean R +0.586 (yildiz);
fakat o BC+UT mekanigi 3-15 bar bekleme ile yavas. Bear top'larda distribution
**hizli** olur — bu varyant o hizi yakalar.

Pre-reg gerekce dosyasi:
  reports/researcher/hypotheses/2026-05-17-bidirectional-shorts.md (HYP-S3-A)

Sablon: vsa_climax_test.py (BC detection paylasildi)

Look-ahead audit checklist:
  - rolling/shift(1) yalniz gecmis bilgi
  - confirmation bar i icin sadece [i-confirm_max] araliginda gecmis bar bilgisi
  - RSI shift'siz hesaplaniyor ama trigger barda kullanilir (ayni bar OK,
    feedback yok cunku entry sonraki bar open)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema
from price_action.strategies.vsa_climax_test import (
    _detect_buying_climax,
    _close_position,
    _spread,
    _vol_sma,
)


# =====================================================================
# RSI helper (look-ahead safe)
# =====================================================================

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI. Causal: sadece gecmis kapanis bilgisi."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return rsi.fillna(50.0)


# =====================================================================
# Distribution test detector (post-BC immediate failure)
# =====================================================================

def _detect_distribution_short(
    df: pd.DataFrame,
    bc_flag: pd.Series,
    rsi_series: pd.Series,
    confirm_min_bars: int = 3,
    confirm_max_bars: int = 5,
    rsi_max: float = 70.0,
) -> tuple[pd.Series, pd.Series]:
    """BC sonrasi distribution short tetikleyici.

    Her bar i icin:
      - Son [i-confirm_max .. i-confirm_min] araliginda en az 1 BC var mi?
      - O BC'den BU bara kadar yeni high yapilmadi mi? (max high BC high'in altinda)
      - close[i] < low[i-1] (lower low yapildi — first leg down)
      - RSI[i] < rsi_max
    -> Confirmation tetikleyici (short entry i+1 open).

    Returns
    -------
    (short_trigger, bc_high_at_trigger)
        short_trigger: pd.Series[bool]
        bc_high_at_trigger: BC bar high (SL hesabi icin)
    """
    n = len(df)
    trigger = pd.Series(False, index=df.index)
    bc_high_out = pd.Series(np.nan, index=df.index)

    high_arr = df["high"].to_numpy()
    low_arr = df["low"].to_numpy()
    close_arr = df["close"].to_numpy()
    bc_arr = bc_flag.to_numpy()
    rsi_arr = rsi_series.to_numpy()

    for i in range(confirm_min_bars, n):
        # Lower-low check (causal: i-1 known at i close)
        if i < 1:
            continue
        ll_ok = close_arr[i] < low_arr[i - 1]
        if not ll_ok:
            continue

        # RSI gate
        if np.isnan(rsi_arr[i]) or rsi_arr[i] >= rsi_max:
            continue

        # BC araligi: [i - confirm_max .. i - confirm_min]
        bc_window_start = max(0, i - confirm_max_bars)
        bc_window_end = i - confirm_min_bars + 1  # exclusive

        # En son (en yakin) BC index
        last_bc_idx = -1
        for j in range(bc_window_end - 1, bc_window_start - 1, -1):
            if j < 0:
                break
            if bc_arr[j]:
                last_bc_idx = j
                break
        if last_bc_idx < 0:
            continue

        bc_high = high_arr[last_bc_idx]

        # Distribution: BC sonrasi bar'lardan biri yeni high yapmis mi?
        # post_max = max(high[bc_idx+1 .. i-1])
        if last_bc_idx + 1 > i - 1:
            post_max = -np.inf
        else:
            post_max = float(np.max(high_arr[last_bc_idx + 1 : i]))

        if post_max >= bc_high:
            # BC high asildi -> distribution invalid (range hala live)
            continue

        # Tum kosullar gecti
        trigger.iloc[i] = True
        bc_high_out.iloc[i] = bc_high

    return trigger, bc_high_out


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "vsa_buying_climax",
        "version": "1.0.0",
        "description": (
            "VSA Buying Climax + Immediate Distribution Test — short-only mirror. "
            "S3-A dedicated bear strategy. BC + lower-low confirm + RSI<70 filter."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "vsa_bc_distribution_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "spread_atr_mult": 1.5,
                        "vol_sma_mult": 2.5,
                        "close_pos_max": 0.40,
                        "max_high_bars": 5,
                        "confirm_min_bars": 3,
                        "confirm_max_bars": 5,
                        "rsi_period": 14,
                        "rsi_max": 70.0,
                        "sl_atr_buffer": 0.5,
                        "primary_R": 1.5,
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
            "stop_loss": {"method": "bc_high_atr", "atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 1.5},
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
# Strategy implementation
# =====================================================================

class VSABuyingClimaxStrategy(Strategy):
    """VSA Buying Climax + Immediate Distribution Test (SHORT-ONLY).

    Mirror short stratejisi vsa_climax_test'in BC+UT bekleme yapisina
    KARSI hizli "no follow-through" mekanigi. Bear top'larda hizli alpha
    icin tasarlandi.
    """

    name = "vsa_buying_climax"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # vsa_internals (15m/5m manifest hub)
        _vsa_internals = getattr(self.manifest, "vsa_internals", {}) or {}
        _vol_sma_period = int(
            _vsa_internals.get("vol_sma_period", 20)
            if isinstance(_vsa_internals, dict) else 20
        )
        _atr_period = int(
            _vsa_internals.get("atr_period", 20)
            if isinstance(_vsa_internals, dict) else 20
        )

        # ATR + vol SMA + EMA
        df[f"atr{_atr_period}"] = _atr(df, _atr_period)
        df["atr20"] = df[f"atr{_atr_period}"]
        df["atr_pct"] = df["atr20"] / df["close"].replace(0, np.nan)
        df["vol_sma20"] = _vol_sma(df["volume"], _vol_sma_period)
        df["ema200"] = _ema(df["close"], 200)

        # Pattern parametreleri
        bc_params: dict[str, Any] = {}
        for p in self.manifest.signals.patterns:
            if p.id == "vsa_bc_distribution_short":
                bc_params = p.params
                break

        # RSI (manifest period)
        rsi_period = int(bc_params.get("rsi_period", 14))
        df["rsi"] = _rsi(df["close"], rsi_period)

        # Buying Climax detect (vsa_climax_test'den paylasildi)
        df["bc_flag"] = _detect_buying_climax(
            df,
            atr_col="atr20",
            vol_sma_col="vol_sma20",
            spread_atr_mult=float(bc_params.get("spread_atr_mult", 1.5)),
            vol_sma_mult=float(bc_params.get("vol_sma_mult", 2.5)),
            close_pos_max=float(bc_params.get("close_pos_max", 0.40)),
            max_high_bars=int(bc_params.get("max_high_bars", 5)),
        )

        # Distribution short trigger
        dist_trigger, bc_high_at_trig = _detect_distribution_short(
            df,
            bc_flag=df["bc_flag"],
            rsi_series=df["rsi"],
            confirm_min_bars=int(bc_params.get("confirm_min_bars", 3)),
            confirm_max_bars=int(bc_params.get("confirm_max_bars", 5)),
            rsi_max=float(bc_params.get("rsi_max", 70.0)),
        )
        df["dist_short_trigger"] = dist_trigger
        df["bc_high_at_trigger"] = bc_high_at_trig

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "dist_short_trigger" not in df.columns:
            df = self.prepare_features(df)

        filters = self.manifest.signals.filters
        bc_params: dict[str, Any] = {}
        for p in self.manifest.signals.patterns:
            if p.id == "vsa_bc_distribution_short":
                bc_params = p.params
                break

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get(
                "primary_R", bc_params.get("primary_R", 1.5)
            )
        )
        atr_buffer = float(
            self.manifest.risk.get("stop_loss", {}).get(
                "atr_buffer", bc_params.get("sl_atr_buffer", 0.5)
            )
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = (
            str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "5m"
        )

        atr_min = float(getattr(filters, "atr_min_pct", 0.003) or 0.003)

        out: list[Signal] = []

        for i in range(len(df)):
            row = df.iloc[i]
            if not bool(row.get("dist_short_trigger", False)):
                continue

            atr = float(row.get("atr20") or 0.0)
            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue
            if atr_min > 0 and atr_pct < atr_min:
                continue

            bc_high = float(row.get("bc_high_at_trigger") or 0.0)
            close = float(row["close"])
            open_ = float(row["open"])

            if np.isnan(bc_high) or bc_high <= 0:
                bc_high = close + 2.0 * atr

            # SHORT entry: bar open used as proxy (engine .shift(1) fills t+1 open)
            entry = open_
            sl_price = bc_high + atr_buffer * atr
            sl_price = max(sl_price, entry + 0.5 * atr)  # en az 0.5 ATR risk
            risk = sl_price - entry
            if risk <= 0:
                continue
            tp_price = entry - primary_R * risk

            ts = pd.Timestamp(row["ts"]).to_pydatetime()
            sig = self.emit_signal(
                ts=ts,
                venue=venue,
                symbol=symbol,
                timeframe=timeframe,
                direction="short",
                pattern_id="vsa_bc_distribution_short",
                confluence_score=2.0,
                sl_price=float(sl_price),
                tp_price=float(tp_price),
                suggested_size_atr=1.0,
                metadata={
                    "bc_high": float(bc_high),
                    "atr20": float(atr),
                    "rsi": float(row.get("rsi") or 0.0),
                    "entry_open": float(entry),
                    "risk_r": float(risk),
                },
            )
            out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info(
            "vsa_buying_climax.signals.generated"
        )
        return out
