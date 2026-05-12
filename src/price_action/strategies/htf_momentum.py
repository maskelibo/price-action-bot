"""HTF Momentum Multi-TF Confluence stratejisi.

Pre-registered: memory/researcher/hypotheses/2026-05-12-htf-momentum-mtf-confluence.md

Iddia: 1W trend + 1D pullback + 1D engulfing trigger uc-TF cascade
       confluence; tek-TF Top 10'a yıllık +%8-15 katkı, korelasyon <0.30.

Backtest sınırlamasi: Mevcut BacktestEngine 1D OHLCV feed bekliyor; bu
strateji 1D bar uzerinde calisir, 1W trend filtresi 1D bar'lardan resample
edilerek hesaplanır (looking-back 7-bar grup, last weekly close).

Kural ozeti (1D bar uzerinde):
  - 1W trend (resample 5/7 bar): close > 20w-EMA AND 8w-ROC > +%5
    (long); ters yon short. Resample causal — sadece kapanmis 1w bar.
  - 1D pullback: son 10 barda 20-EMA'ya dokunmus
  - 1D engulfing trigger: strict engulfing + body_ratio >= 0.55
  - 1D bar range > 0.7 * ATR(14) — momentum sarti
  - Volume_z(20) >= -0.5 (asgari katilim)
  - SL: structural swing low (long) / high (short) - 0.3*ATR
  - TP: 2R primary, partial 1R + 2R + chandelier trail
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
    _kaufman_efficiency_ratio,
    _sr_levels,
)


# =====================================================================
# Helper'lar — multi-TF resample (causal)
# =====================================================================

def _weekly_ema_and_roc(
    df: pd.DataFrame,
    weeks_lookback: int = 8,
    ema_weeks: int = 20,
) -> pd.DataFrame:
    """1D bar'lardan haftalik EMA ve ROC turet — causal.

    Her 1D bar i icin:
      - "weekly_close_lastN": son N=1 hafta'lik bar'in son kapanisi
      - "weekly_ema_20": son 20 hafta'lik bar EMA
      - "weekly_roc_8w": (weekly_close[t] - weekly_close[t-8]) / weekly_close[t-8]

    Causal kural: 1D bar i'de "su anki hafta" kapanmamis ise SON KAPANMIS
    hafta'nin verisi kullanilir. Ornek: cuma bar i=4 (haftaici), o anki
    haftanin close'u henuz yok → onceki hafta close'u kullan.

    Pandas resample('W-SUN').last() ile haftalik close serisi olusturulur;
    sonra .reindex(daily_df.ts).ffill().shift(1) — bu son shift "su an
    kapanmamis hafta" sorunu icin (pazar 23:59 bar'i bile, "bu hafta"
    kapanmamis kabul et).
    """
    if df.empty:
        df["weekly_ema_20"] = np.nan
        df["weekly_roc_8w"] = np.nan
        return df

    # Index on ts for resampling
    tmp = df.set_index("ts")[["close"]].copy()
    weekly = tmp.resample("W-SUN").last().dropna()
    weekly["w_ema_20"] = weekly["close"].ewm(span=ema_weeks, adjust=False).mean()
    weekly["w_roc"] = weekly["close"].pct_change(weeks_lookback)

    # Reindex back to daily — forward-fill, then shift(1) to enforce causality
    # (latest known WEEKLY value is the previous completed week)
    weekly_reidx = weekly[["w_ema_20", "w_roc", "close"]].reindex(tmp.index, method="ffill").shift(1)

    df = df.copy()
    df["weekly_ema_20"] = weekly_reidx["w_ema_20"].values
    df["weekly_roc_8w"] = weekly_reidx["w_roc"].values
    df["weekly_close"] = weekly_reidx["close"].values
    return df


def _strict_engulfing(df: pd.DataFrame, body_ratio_min: float = 0.55, bullish: bool = True) -> pd.Series:
    """Engulfing bar — body(N) tamamen body(N-1)'i sarar + body_ratio sart."""
    o = df["open"]
    c = df["close"]
    prev_o = o.shift(1)
    prev_c = c.shift(1)
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    body_abs = (c - o).abs()
    body_ratio = body_abs / rng
    if bullish:
        color_ok = (c > o) & (prev_c < prev_o)
        engulf = (o <= prev_c) & (c >= prev_o)
    else:
        color_ok = (c < o) & (prev_c > prev_o)
        engulf = (o >= prev_c) & (c <= prev_o)
    return (color_ok & engulf & (body_ratio >= body_ratio_min)).fillna(False)


def _pullback_to_ema_flag(
    df: pd.DataFrame,
    ema_col: str = "ema20",
    window: int = 10,
    touch_atr_factor: float = 0.5,
) -> pd.Series:
    """Son `window` barda fiyat ema'ya dokundu mu?"""
    ema_val = df[ema_col]
    atr_val = df["atr14"].fillna(0.0)
    tolerance = atr_val * touch_atr_factor
    touched = (df["low"] <= ema_val + tolerance) & (df["high"] >= ema_val - tolerance)
    return touched.shift(1).rolling(window, min_periods=1).max().fillna(0).astype(bool)


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "htf_momentum",
        "version": "0.1.0",
        "description": "HTF Momentum Cascade: 1W trend + 1D pullback + engulfing trigger",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "htf_momentum_long",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "weekly_roc_min": 0.05,
                        "body_ratio_min": 0.55,
                        "pullback_window": 10,
                        "range_atr_factor": 0.7,
                    },
                },
                {
                    "id": "htf_momentum_short",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "weekly_roc_min": 0.05,  # absolute, will be negated for short
                        "body_ratio_min": 0.55,
                        "pullback_window": 10,
                        "range_atr_factor": 0.7,
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
                "require_proximity_to_sr_atr": 0.0,  # SR proximity opsiyonel
            },
            "filters": {
                "atr_min_pct": 0.005,
                "volume_zscore_min": -0.5,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.15,
                "always_in_required": False,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.3,
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

class HTFMomentumStrategy(Strategy):
    """1W trend + 1D pullback + 1D engulfing trigger.

    Pre-registered: 2026-05-12-htf-momentum-mtf-confluence.md
    """
    name = "htf_momentum"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # Daily EMAs
        df["ema20"] = _ema(df["close"], 20)
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)

        # ATR
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Volume z (60-bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Weekly EMA + ROC (causal resample)
        df = _weekly_ema_and_roc(df, weeks_lookback=8, ema_weeks=20)

        # Swing high/low
        n = self.manifest.signals.structure.swing.fractal_n
        sh, sl = _fractal_swings(df, n=n)
        df["swing_high"] = sh
        df["swing_low"] = sl

        # Pullback flag
        df["pullback_to_20ema"] = _pullback_to_ema_flag(df, "ema20", 10, 0.5)

        # Engulfing flags
        body_ratio_min = 0.55
        for p in self.manifest.signals.patterns:
            if p.id in ("htf_momentum_long", "htf_momentum_short"):
                body_ratio_min = float(p.params.get("body_ratio_min", 0.55))
                break
        df["bull_engulf"] = _strict_engulfing(df, body_ratio_min, bullish=True)
        df["bear_engulf"] = _strict_engulfing(df, body_ratio_min, bullish=False)

        # Structural SL
        df["struct_sl_long"] = df["low"].shift(1).rolling(10, min_periods=1).min()
        df["struct_sl_short"] = df["high"].shift(1).rolling(10, min_periods=1).max()

        # Kaufman ER
        er_period = int(getattr(self.manifest.signals.filters, "kaufman_er_period", 14) or 14)
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Range / ATR ratio
        df["range_atr_ratio"] = (df["high"] - df["low"]) / df["atr14"]

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "weekly_ema_20" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        confluence = signals_cfg.confluence
        sr_cfg = signals_cfg.structure.support_resistance

        primary_R = float(self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0))
        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # Pattern params
        weekly_roc_min = 0.05
        range_atr_factor = 0.7
        pullback_window = 10
        for p in signals_cfg.patterns:
            if p.id == "htf_momentum_long" and p.enabled:
                weekly_roc_min = float(p.params.get("weekly_roc_min", 0.05))
                range_atr_factor = float(p.params.get("range_atr_factor", 0.7))
                pullback_window = int(p.params.get("pullback_window", 10))
                break

        # Long & short score series
        long_score = pd.Series(0.0, index=df.index)
        short_score = pd.Series(0.0, index=df.index)

        # 1W trend filter
        w_close = df["weekly_close"]
        w_ema = df["weekly_ema_20"]
        w_roc = df["weekly_roc_8w"]
        bull_weekly = (w_close > w_ema) & (w_roc > weekly_roc_min)
        bear_weekly = (w_close < w_ema) & (w_roc < -weekly_roc_min)

        # 1D bias (close > ema50)
        bull_daily = df["close"] > df["ema50"]
        bear_daily = df["close"] < df["ema50"]

        # Range & momentum
        range_ok = df["range_atr_ratio"] >= range_atr_factor

        # Pullback
        pullback = df["pullback_to_20ema"].fillna(False)

        # Engulfing trigger
        bull_engulf = df["bull_engulf"].fillna(False)
        bear_engulf = df["bear_engulf"].fillna(False)

        # Long signal
        long_cond = bull_weekly & bull_daily & range_ok & pullback & bull_engulf
        long_score = long_score.where(~long_cond, 1.5)

        # Short signal
        short_cond = bear_weekly & bear_daily & range_ok & pullback & bear_engulf
        short_score = short_score.where(~short_cond, 1.5)

        # ATR filter
        atr_min = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)
        if atr_min > 0:
            mask = df["atr_pct"] >= atr_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # Volume z filter
        vol_min = float(getattr(filters, "volume_zscore_min", -0.5) or -0.5)
        mask_v = df["vol_z"].fillna(-99) >= vol_min
        long_score = long_score.where(mask_v, 0.0)
        short_score = short_score.where(mask_v, 0.0)

        # Kaufman ER
        er_min = float(getattr(filters, "kaufman_er_min", 0.15) or 0.15)
        if er_min > 0 and "kaufman_er" in df.columns:
            mask_er = df["kaufman_er"] >= er_min
            long_score = long_score.where(mask_er, 0.0)
            short_score = short_score.where(mask_er, 0.0)

        # S/R proximity bonus (optional)
        proximity_atr = signals_cfg.structure.require_proximity_to_sr_atr
        bonus = float(getattr(confluence, "bonus_if_at_sr", 0.0) or 0.0)
        min_score = float(confluence.min_score)

        sr_by_bar = {}
        if proximity_atr > 0:
            cluster_tol = df["atr14"].fillna(0) * sr_cfg.cluster_atr_multiplier
            sr_records = _sr_levels(
                df,
                lookback_bars=sr_cfg.lookback_bars,
                cluster_tol=cluster_tol,
                min_touches=sr_cfg.min_touches,
            )
            for i, lvl, _t in sr_records:
                sr_by_bar.setdefault(i, []).append(lvl)

        out: list[Signal] = []
        for i in range(len(df)):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue

            near_sr = False
            if proximity_atr > 0:
                levels = sr_by_bar.get(i, [])
                if levels:
                    tol = proximity_atr * atr
                    near_sr = any(abs(close - lvl) <= tol for lvl in levels)

            for direction, score_series, pattern_id_name in (
                ("long", long_score, "htf_momentum_long"),
                ("short", short_score, "htf_momentum_short"),
            ):
                base_score = float(score_series.iat[i])
                if base_score <= 0:
                    continue
                final_score = base_score + (bonus if near_sr else 0.0)
                if final_score < min_score:
                    continue

                if direction == "long":
                    sl_price = float(row.get("struct_sl_long") or (close - 2.0 * atr))
                    if np.isnan(sl_price) or sl_price <= 0:
                        sl_price = close - 2.0 * atr
                    sl_price = min(sl_price, close - 0.5 * atr) - 0.3 * atr
                    risk = close - sl_price
                    tp_price = close + primary_R * risk
                else:
                    sl_price = float(row.get("struct_sl_short") or (close + 2.0 * atr))
                    if np.isnan(sl_price) or sl_price <= 0:
                        sl_price = close + 2.0 * atr
                    sl_price = max(sl_price, close + 0.5 * atr) + 0.3 * atr
                    risk = sl_price - close
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
                        "weekly_roc_8w": float(row.get("weekly_roc_8w") or 0.0),
                        "weekly_ema_20": float(row.get("weekly_ema_20") or 0.0),
                        "near_sr": near_sr,
                        "atr14": atr,
                        "pullback_to_20ema": bool(row.get("pullback_to_20ema", False)),
                        "kaufman_er": float(row.get("kaufman_er") or 0.0),
                        "range_atr_ratio": float(row.get("range_atr_ratio") or 0.0),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("htf_momentum.signals.generated")
        return out
