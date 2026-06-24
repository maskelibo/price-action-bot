"""Brooks Failed High — Dedicated Short-Only (S3-B).

PHOENIX-SCALP v2.1 / SEC47 / D5-sec49 (CEO master plan 2026-05-17).

Mirror short stratejisi `brooks_failed_breakout`'in DENGI degil
TAMAMLAYICISI: existing strategy `bull_trap_short` N-bar high'i BREAK eder
ve sonra fail eder. Bu strateji **prior swing high'a yaklasir AMA ASLA
break etmez** — kapanis swing high altinda kalir, "failed high" sinyali
verir.

Mekanik:
  1. Prior swing high (lookback N bar) tespit edilir.
  2. Bar yaklasir: high[t] swing_high'in approach_pct (varsayilan %0.3)
     icinde AMA close[t] < swing_high (break yok).
  3. Failure confirmation: close yakinligin **alt 10%**'unda (yani close
     bar high'in altinda buyuk fark var) — close < bar_open AND
     bar_close <= bar_high - 0.7*(bar_high - bar_low). Anlami: yuksek
     reddedildi, ust fitil olustu.
  4. Entry: failure bar acilisinda SHORT (.shift(1) ile next bar open).
  5. SL: swing high + sl_atr_factor * ATR.
  6. TP: prior swing low (dinamik) ya da 2R (sabit, hangisi daha yakin).

Mirror gerekce: brooks_failed_breakout long mean R +0.195 (kanitli edge);
mirror failed_high short bear top'larda yuksek olasi. "Yaklasim-fail"
mekanigi "break-fail" mekanigine kiyasla daha hizli sinyal verir
(BREAK + 1-3 bar bekleme yok).

Pre-reg gerekce dosyasi:
  reports/researcher/hypotheses/2026-05-17-bidirectional-shorts.md (HYP-S3-B)

Look-ahead audit checklist:
  - swing high: shift(1).rolling(period).max() -> sadece gecmis bar
  - approach + failure: bar t close anligi bilinir, t close itibariyle
    karar; entry sonraki bar open (engine .shift(1))
  - swing low (TP): shift(1).rolling(period).min() -> causal
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
)


# =====================================================================
# Yardimcilar
# =====================================================================

def _rolling_prior_swing_high(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Onceki N bar'in en yuksek high'i (lookahead-free).

    Bar t icin [t-period .. t-1] araligini kullanir.
    """
    return df["high"].shift(1).rolling(period, min_periods=period).max()


def _rolling_prior_swing_low(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Onceki N bar'in en dusuk low'u (lookahead-free)."""
    return df["low"].shift(1).rolling(period, min_periods=period).min()


def _detect_failed_high_short(
    df: pd.DataFrame,
    swing_high_series: pd.Series,
    atr_series: pd.Series,
    approach_pct: float = 0.003,
    failure_close_pct: float = 0.30,
    require_red_bar: bool = True,
) -> tuple[pd.Series, pd.Series]:
    """Failed-high short tetikleyici.

    Bar t icin kosullar:
      - swing_high[t] mevcut (warmup gecti)
      - high[t] >= swing_high[t] * (1 - approach_pct)  -> approach yapildi
      - high[t] <  swing_high[t]                       -> AMA break YOK
        (close[t] da swing_high altinda otomatik)
      - close[t] <= low[t] + failure_close_pct * (high[t] - low[t])
        (close bar range'inin alt portion'unda — rejection wick)
      - require_red_bar: close[t] < open[t]

    Returns
    -------
    (trigger, swing_high_at_trigger)
    """
    n = len(df)
    trigger = pd.Series(False, index=df.index)
    sh_out = pd.Series(np.nan, index=df.index)

    high_arr = df["high"].to_numpy()
    low_arr = df["low"].to_numpy()
    open_arr = df["open"].to_numpy()
    close_arr = df["close"].to_numpy()
    sh_arr = swing_high_series.to_numpy()

    for i in range(n):
        sh = sh_arr[i]
        if np.isnan(sh) or sh <= 0:
            continue

        hi = high_arr[i]
        lo = low_arr[i]
        op = open_arr[i]
        cl = close_arr[i]
        rng = hi - lo
        if rng <= 0:
            continue

        # Approach: high yeterince yakin AMA break yok
        approach_min = sh * (1.0 - approach_pct)
        if not (approach_min <= hi < sh):
            continue

        # Close bar alt portion'unda
        close_thr = lo + failure_close_pct * rng
        if cl > close_thr:
            continue

        # Red bar zorunlu?
        if require_red_bar and cl >= op:
            continue

        trigger.iloc[i] = True
        sh_out.iloc[i] = sh

    return trigger, sh_out


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "brooks_failed_high",
        "version": "1.0.0",
        "description": (
            "Brooks Failed High — short-only mirror. Swing high'a yaklasim "
            "+ break yok + rejection wick + red bar. S3-B dedicated bear."
        ),
        "trend_filter": {"type": "none", "period": 0, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "failed_high_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_period": 20,
                        "approach_pct": 0.003,
                        "failure_close_pct": 0.30,
                        "require_red_bar": True,
                        "sl_atr_factor": 0.5,
                        "tp_method": "r_multiple",  # "r_multiple" or "swing_low"
                        "primary_R": 2.0,
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
                "kaufman_er_period": 14,
                "kaufman_er_max_trend": 0.90,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {
                "method": "swing_high_plus_atr",
                "atr_factor": 0.5,
            },
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
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

class BrooksFailedHighStrategy(Strategy):
    """Brooks Failed High — short-only failed-approach reversal."""

    name = "brooks_failed_high"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # Pattern parametreleri
        lookback = 20
        approach_pct = 0.003
        failure_close_pct = 0.30
        require_red_bar = True
        for p in self.manifest.signals.patterns:
            if p.id == "failed_high_short":
                lookback = int(p.params.get("lookback_period", 20))
                approach_pct = float(p.params.get("approach_pct", 0.003))
                failure_close_pct = float(p.params.get("failure_close_pct", 0.30))
                require_red_bar = bool(p.params.get("require_red_bar", True))
                break

        # ATR + EMA + ER
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)
        df["ema20"] = _ema(df["close"], 20)
        df["ema50"] = _ema(df["close"], 50)

        er_period = int(
            getattr(self.manifest.signals.filters, "kaufman_er_period", 14) or 14
        )
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Volume z-score (60-bar baseline)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Swing high + low
        df[f"prior_high_{lookback}"] = _rolling_prior_swing_high(df, period=lookback)
        df[f"prior_low_{lookback}"] = _rolling_prior_swing_low(df, period=lookback)

        # Failed-high detect
        trigger, sh_at_trig = _detect_failed_high_short(
            df,
            swing_high_series=df[f"prior_high_{lookback}"],
            atr_series=df["atr14"],
            approach_pct=approach_pct,
            failure_close_pct=failure_close_pct,
            require_red_bar=require_red_bar,
        )
        df["failed_high_trigger"] = trigger
        df["swing_high_at_trigger"] = sh_at_trig

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "failed_high_trigger" not in df.columns:
            df = self.prepare_features(df)

        filters = self.manifest.signals.filters
        confluence = self.manifest.signals.confluence

        # Pattern parametreleri
        lookback = 20
        sl_atr_factor = 0.5
        primary_R = 2.0
        tp_method = "r_multiple"
        for p in self.manifest.signals.patterns:
            if p.id == "failed_high_short":
                lookback = int(p.params.get("lookback_period", 20))
                sl_atr_factor = float(p.params.get("sl_atr_factor", 0.5))
                primary_R = float(p.params.get("primary_R", 2.0))
                tp_method = str(p.params.get("tp_method", "r_multiple"))
                break

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", primary_R)
        )

        atr_min = float(getattr(filters, "atr_min_pct", 0.003) or 0.003)
        vol_min = float(getattr(filters, "volume_zscore_min", 0.0) or 0.0)
        er_max = float(getattr(filters, "kaufman_er_max_trend", 1.0) or 1.0)
        min_score = float(confluence.min_score)

        short_weight = 2.0
        for p in self.manifest.signals.patterns:
            if p.enabled and p.id == "failed_high_short":
                short_weight = p.weight
                break

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = (
            str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "5m"
        )

        prior_low_col = f"prior_low_{lookback}"
        out: list[Signal] = []

        for i in range(len(df)):
            row = df.iloc[i]
            if not bool(row.get("failed_high_trigger", False)):
                continue

            atr = float(row.get("atr14") or 0.0)
            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue
            if atr_min > 0 and atr_pct < atr_min:
                continue

            vol_z = float(row.get("vol_z") or 0.0)
            if vol_min > 0 and (np.isnan(vol_z) or vol_z < vol_min):
                continue

            er = float(row.get("kaufman_er") or 0.0)
            if er_max < 1.0 and er > er_max:
                continue

            score = short_weight
            if score < min_score:
                continue

            sh = float(row.get("swing_high_at_trigger") or np.nan)
            if np.isnan(sh):
                continue

            close = float(row["close"])
            open_ = float(row["open"])
            entry = open_  # next-bar open proxy (engine .shift(1))

            sl_price = sh + sl_atr_factor * atr
            sl_price = max(sl_price, entry + 0.5 * atr)
            risk = sl_price - entry
            if risk <= 0:
                continue

            # TP hesabi
            if tp_method == "swing_low":
                sl_tp = float(row.get(prior_low_col) or np.nan)
                if not np.isnan(sl_tp) and sl_tp < entry:
                    # En yakin hangisi: swing_low ya da 2R seviye
                    tp_r = entry - primary_R * risk
                    tp_price = max(sl_tp, tp_r)  # SHORT icin max = en yakin
                else:
                    tp_price = entry - primary_R * risk
            else:
                tp_price = entry - primary_R * risk

            if tp_price >= entry:
                continue

            ts = pd.Timestamp(row["ts"]).to_pydatetime()
            sig = self.emit_signal(
                ts=ts,
                venue=venue,
                symbol=symbol,
                timeframe=timeframe,
                direction="short",
                pattern_id="failed_high_short",
                confluence_score=float(score),
                sl_price=float(sl_price),
                tp_price=float(tp_price),
                suggested_size_atr=1.0,
                metadata={
                    "atr14": atr,
                    "swing_high": float(sh),
                    "kaufman_er": er,
                    "tp_method": tp_method,
                    "entry_open": float(entry),
                    "risk_r": float(risk),
                },
            )
            out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info(
            "brooks_failed_high.signals.generated"
        )
        return out
