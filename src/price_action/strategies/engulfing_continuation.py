"""Engulfing Continuation stratejisi.

Strateji: 20-EMA'ya pullback sonrasi bullish/bearish engulfing bar,
           50-EMA + Brooks 'always-in' trend filtresi ile konfirme edilmis.

Kural ozeti:
  - Trend filtresi : 50-EMA yonu + 3-bar always-in konfirmasyonu
  - Pullback       : Son 5-10 barda fiyat 20-EMA'ya dokunmus/bounced
  - Engulfing      : Strict — Body(N) body(N-1)'i tamamen sarar, zit renk,
                     body_ratio >= 0.6 (total range uzerine)
  - Giris          : Bar N+1 acilis (bar N kapanis sonrasi karar)
  - Stop           : Structural swing low (long) / swing high (short)
  - Hedef          : 2R birincil; 14-EMA trailing runner 1R sonrasi
  - Confluence     : S/R proximity bonusu, atr_min_pct 0.005

Manifest yoksa dahili default kullanilir.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# Shared helpers — aynı fonksiyonlari yeniden yazmaktan kacin
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
# Strateji ozgune ek yardimcilar
# =====================================================================

def _pullback_to_ema_flag(
    df: pd.DataFrame,
    ema_col: str = "ema20",
    window: int = 10,
    touch_atr_factor: float = 0.5,
) -> pd.Series:
    """Son `window` barda fiyat 20-EMA'ya yeterince yakin geldi mi?

    Dokunma kriteri: bar'in low <= ema + touch_atr_factor*atr  VE
                     bar'in high >= ema - touch_atr_factor*atr
    (yani EMA, bar'in 'atr*factor' bandi icinde kalmis olmali)

    Lookahead-free: t bari icin sadece [t-window..t-1] bari kullanilir.
    """
    close = df["close"]
    ema_val = df[ema_col]
    atr_val = df["atr14"].fillna(0.0)
    tolerance = atr_val * touch_atr_factor

    # Bar bazli dokunma: low <= ema + tol AND high >= ema - tol
    bar_low = df["low"]
    bar_high = df["high"]
    touched = (bar_low <= ema_val + tolerance) & (bar_high >= ema_val - tolerance)

    # Son `window` bar icinde herhangi bir dokunma var mi? (t dahil degil — shift)
    # shift(1) ile t-1'e tasiyoruz, rolling(window) ile [t-window..t-1]'e bakiyoruz
    pulled_back = touched.shift(1).rolling(window, min_periods=1).max().fillna(0).astype(bool)
    return pulled_back


def _strict_engulfing(
    df: pd.DataFrame,
    body_ratio_min: float = 0.6,
    bullish: bool = True,
) -> pd.Series:
    """Strict engulfing: body(N) tamamen body(N-1)'i sarar + body_ratio >= 0.6.

    body_ratio = body_abs / total_range — sadece engulfing bar icin.
    Lookahead-free: sadece shift(1) (t-1 bar bilgisi) kullanilir.
    """
    o = df["open"]
    c = df["close"]
    prev_o = o.shift(1)
    prev_c = c.shift(1)
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    body_abs = (c - o).abs()
    body_ratio = body_abs / rng

    if bullish:
        color_ok = (c > o) & (prev_c < prev_o)           # N bullish, N-1 bearish
        # N body tamamen N-1 body'yi sarar (strict: >=)
        engulf = (o <= prev_c) & (c >= prev_o)
    else:
        color_ok = (c < o) & (prev_c > prev_o)           # N bearish, N-1 bullish
        engulf = (o >= prev_c) & (c <= prev_o)

    strict = color_ok & engulf & (body_ratio >= body_ratio_min)
    return strict.fillna(False)


def _swing_sl(
    df: pd.DataFrame,
    direction: str,
    lookback: int = 10,
) -> pd.Series:
    """Structural stop: son `lookback` barin swing low (long) veya swing high (short).

    Lookahead-free: t bari icin [t-lookback..t-1] araligina bakilir.
    """
    if direction == "long":
        sl = df["low"].shift(1).rolling(lookback, min_periods=1).min()
    else:
        sl = df["high"].shift(1).rolling(lookback, min_periods=1).max()
    return sl


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "engulfing_continuation",
        "version": "1.0.0",
        "description": "Engulfing bar after 20-EMA pullback in established trend",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "body_ratio_min": 0.6,
                        "pullback_window": 10,
                        "pullback_touch_atr": 0.5,
                    },
                },
                {
                    "id": "bearish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "body_ratio_min": 0.6,
                        "pullback_window": 10,
                        "pullback_touch_atr": 0.5,
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
                "require_proximity_to_sr_atr": 0.5,
            },
            "filters": {
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.20,
                "always_in_required": False,
                "bear_regime_size_factor": 0.5,
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

class EngulfingContinuationStrategy(Strategy):
    """Engulfing bar after 20-EMA pullback in established trend.

    Trend filtresi  : 50-EMA + Brooks always-in 3-bar
    Pullback        : Son 10 barda fiyat 20-EMA'ya dokundu (ATR tol)
    Engulfing       : Strict (body >= 0.6 * range, tam sarim, zit renk)
    Giris           : N+1 bar acilis
    Stop            : Structural swing low/high (son 10 bar)
    Hedef           : 2R
    """

    name = "engulfing_continuation"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # EMAs
        df["ema20"] = _ema(df["close"], 20)
        df["ema14"] = _ema(df["close"], 14)  # runner trailing stop
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)

        # ATR
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Volume z-score (60 bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Swing high/low (fractal)
        n = self.manifest.signals.structure.swing.fractal_n
        sh, sl = _fractal_swings(df, n=n)
        df["swing_high"] = sh
        df["swing_low"] = sl

        # Pullback to 20-EMA flag (rolling 10-bar window)
        filters_cfg = self.manifest.signals.filters
        pb_window = 10
        pb_touch = 0.5
        # Try to get params from first pattern
        for p in self.manifest.signals.patterns:
            if p.id in ("bullish_engulfing_cont", "bearish_engulfing_cont"):
                pb_window = int(p.params.get("pullback_window", 10))
                pb_touch = float(p.params.get("pullback_touch_atr", 0.5))
                break
        df["pullback_to_20ema"] = _pullback_to_ema_flag(
            df, ema_col="ema20", window=pb_window, touch_atr_factor=pb_touch
        )

        # Strict engulfing flags
        body_ratio_min = 0.6
        for p in self.manifest.signals.patterns:
            if p.id in ("bullish_engulfing_cont", "bearish_engulfing_cont"):
                body_ratio_min = float(p.params.get("body_ratio_min", 0.6))
                break
        df["strict_bull_engulf"] = _strict_engulfing(df, body_ratio_min=body_ratio_min, bullish=True)
        df["strict_bear_engulf"] = _strict_engulfing(df, body_ratio_min=body_ratio_min, bullish=False)

        # Structural SL levels
        df["struct_sl_long"] = _swing_sl(df, "long", lookback=10)
        df["struct_sl_short"] = _swing_sl(df, "short", lookback=10)

        # Kaufman ER
        er_period = int(getattr(filters_cfg, "kaufman_er_period", 14) or 14)
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Brooks always-in flags
        ai_n = int(getattr(filters_cfg, "always_in_n_confirm", 3) or 3)
        long_ai, short_ai = _always_in_flags(df, n_confirm=ai_n)
        df["always_in_long"] = long_ai
        df["always_in_short"] = short_ai

        # Rolling Sharpe
        rs_period = int(getattr(filters_cfg, "rolling_sharpe_period", 60) or 60)
        df["rolling_sharpe"] = _rolling_sharpe(df["close"], period=rs_period)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "ema20" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        confluence = signals_cfg.confluence
        sr_cfg = signals_cfg.structure.support_resistance

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # --- Score series ---
        long_score = pd.Series(0.0, index=df.index)
        short_score = pd.Series(0.0, index=df.index)

        # Pattern weights
        bull_weight = 1.5
        bear_weight = 1.5
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "bullish_engulfing_cont":
                bull_weight = p.weight
            elif p.id == "bearish_engulfing_cont":
                bear_weight = p.weight

        # Pullback + engulfing condition
        pullback = df["pullback_to_20ema"].fillna(False)
        bull_engulf = df["strict_bull_engulf"].fillna(False)
        bear_engulf = df["strict_bear_engulf"].fillna(False)

        long_score = long_score.where(~(pullback & bull_engulf), bull_weight)
        short_score = short_score.where(~(pullback & bear_engulf), bear_weight)

        # --- Trend filter (50-EMA direction) ---
        if self.manifest.trend_filter.required:
            up_ok = df["close"] > df["ema50"]
            down_ok = df["close"] < df["ema50"]
            long_score = long_score.where(up_ok, 0.0)
            short_score = short_score.where(down_ok, 0.0)

        # --- ATR min filter ---
        atr_min = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)
        if atr_min > 0:
            mask = df["atr_pct"] >= atr_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # --- Volume z-score filter ---
        vol_min = float(getattr(filters, "volume_zscore_min", 0.0) or 0.0)
        if vol_min > 0:
            mask = df["vol_z"].fillna(-np.inf) >= vol_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # --- Kaufman ER min ---
        er_min = float(getattr(filters, "kaufman_er_min", 0.0) or 0.0)
        if er_min > 0 and "kaufman_er" in df.columns:
            mask = df["kaufman_er"] >= er_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # --- Brooks always-in (optional) ---
        if bool(getattr(filters, "always_in_required", False)):
            long_score = long_score.where(df["always_in_long"], 0.0)
            short_score = short_score.where(df["always_in_short"], 0.0)

        # --- Rolling Sharpe size factor ---
        rs_min = float(getattr(filters, "rolling_sharpe_min", -1e9))
        rs_size_factor = float(getattr(filters, "rolling_sharpe_size_factor", 1.0) or 1.0)
        if rs_min > -1e8 and "rolling_sharpe" in df.columns:
            poor_regime = df["rolling_sharpe"] < rs_min
            long_score = long_score.where(~poor_regime, long_score * rs_size_factor)
            short_score = short_score.where(~poor_regime, short_score * rs_size_factor)

        # --- 200-EMA bear regime size factor ---
        bear_factor = float(getattr(filters, "bear_regime_size_factor", 1.0) or 1.0)
        if bear_factor < 1.0 and "ema200" in df.columns:
            below_200 = df["close"] < df["ema200"]
            long_score = long_score.where(~below_200, long_score * bear_factor)

        # --- S/R levels (lookahead-free) ---
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
        bonus = float(getattr(confluence, "bonus_if_at_sr", 0.0) or 0.0)
        min_score = float(confluence.min_score)

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

            for direction, score_series, pattern_id_name in (
                ("long", long_score, "bullish_engulfing_cont"),
                ("short", short_score, "bearish_engulfing_cont"),
            ):
                base_score = float(score_series.iat[i])
                if base_score <= 0:
                    continue
                final_score = base_score + (bonus if near_sr else 0.0)
                if proximity_atr > 0 and not near_sr:
                    final_score = max(0.0, final_score - 0.25)
                if final_score < min_score:
                    continue

                # Structural SL
                if direction == "long":
                    sl_price = float(row.get("struct_sl_long") or (close - 2.0 * atr))
                    if np.isnan(sl_price) or sl_price <= 0:
                        sl_price = close - 2.0 * atr
                    # Ensure SL is below close
                    sl_price = min(sl_price, close - 0.5 * atr)
                    risk = close - sl_price
                    tp_price = close + primary_R * risk
                else:
                    sl_price = float(row.get("struct_sl_short") or (close + 2.0 * atr))
                    if np.isnan(sl_price) or sl_price <= 0:
                        sl_price = close + 2.0 * atr
                    sl_price = max(sl_price, close + 0.5 * atr)
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
                        "near_sr": near_sr,
                        "atr14": atr,
                        "ema20": float(row.get("ema20") or 0.0),
                        "ema50": float(row.get("ema50") or 0.0),
                        "pullback_to_20ema": bool(row.get("pullback_to_20ema", False)),
                        "kaufman_er": float(row.get("kaufman_er") or 0.0),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("engulfing_cont.signals.generated")
        return out
