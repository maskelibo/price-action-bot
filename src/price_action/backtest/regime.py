"""Regime filtreleri — backtest replay'inde overlay olarak uygulanir.

İki ana filter:
  1. BTC capitulation halt — ATR% + EMA200 streak + 90d DD (Analyst HYP)
  2. Per-symbol chop suppressor — ADX(14) + Bollinger Band Width percentile (Researcher B HYP-REGIME-001)

Her ikisi de "calendar dict" formatinda dondurulur:
  {(symbol|"BTC", date) -> action}  — action: "halt" / "skip" / "half" / None

production_replay buradan okur, trade entry_ts.date()'e bakar.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]


def _load_ohlcv(symbol: str, tf: str = "1d") -> pd.DataFrame:
    """run_real_backtest._load_symbol_ohlcv'in module-level wrapper'i.

    Late import — scripts/ ve src/ mixed ortam icin.
    """
    import sys
    sys.path.insert(0, str(ROOT))
    from scripts.run_real_backtest import _load_symbol_ohlcv
    df = _load_symbol_ohlcv(symbol, tf=tf)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts").reset_index(drop=True)


def compute_btc_capitulation_halt(
    atr_threshold: float = 6.0,
    ema200_streak_threshold: int = 10,
    dd_90d_threshold: float = -25.0,
    resume_atr_threshold: float = 4.0,
    resume_streak_days: int = 5,
) -> dict[date, bool]:
    """Analyst HYP — capitulation halt calendar.

    Returns: dict[date -> halt:bool]
    Sirasi: bos gun -> halt False. Var olan gun icin 3 kuralin ENaz 2'si saglanirsa halt True.
    Resume: ATR% <= 4 AND BTC > EMA50 son 5 gun -> halt False.

    Implementasyon — analyst'in scripts/v093_regime_analysis.py'sindeki ATR/EMA/DD formulu.
    """
    df = _load_ohlcv("BTC/USDT", tf="1d")

    # ATR(14) Wilder
    h_l = df["high"] - df["low"]
    h_c = (df["high"] - df["close"].shift()).abs()
    l_c = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([h_l, h_c, l_c], axis=1).max(axis=1)
    df["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["atr_pct"] = df["atr14"] / df["close"] * 100

    # EMA50, EMA200
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["below_ema200"] = (df["close"] < df["ema200"]).astype(int)

    # Below-EMA200 streak (consecutive days)
    streak = 0
    streaks = []
    for v in df["below_ema200"]:
        if v == 1:
            streak += 1
        else:
            streak = 0
        streaks.append(streak)
    df["below_ema200_streak"] = streaks

    # 90d max-DD
    rolling_max = df["close"].rolling(90, min_periods=1).max()
    df["dd_90d"] = (df["close"] / rolling_max - 1) * 100

    # Resume condition (5 consec days)
    df["above_ema50"] = (df["close"] > df["ema50"]).astype(int)
    df["resume_ok"] = (
        (df["atr_pct"] <= resume_atr_threshold)
        & (df["above_ema50"].rolling(resume_streak_days, min_periods=resume_streak_days).sum() == resume_streak_days)
    )

    # SEC16 LOOK-AHEAD FIX: T günü kararı T-1 verisine bakmalı (causal)
    # Önce: halt[T] = T günü atr_pct/streak/dd_90d -> trade entry T'de yapıldıysa T verisi kullanım = LOOK-AHEAD
    # Sonra: rules.shift(1) ile T günü kararı T-1 ATR/streak/DD'ye bakar (causal)
    rules = pd.DataFrame({
        "high_vol": df["atr_pct"] >= atr_threshold,
        "bear_streak": df["below_ema200_streak"] >= ema200_streak_threshold,
        "deep_dd": df["dd_90d"] <= dd_90d_threshold,
    })
    halt_candidate = (rules.sum(axis=1) >= 2).shift(1).fillna(False)
    resume_ok_lag = df["resume_ok"].shift(1).fillna(False)

    # Sticky halt: bir kez tetiklenince resume kuralina kadar acik (causal)
    halt = []
    in_halt = False
    for i in range(len(df)):
        if not in_halt and halt_candidate.iloc[i]:
            in_halt = True
        elif in_halt and resume_ok_lag.iloc[i]:
            in_halt = False
        halt.append(in_halt)

    return {df["ts"].iloc[i].date(): halt[i] for i in range(len(df))}


def compute_per_symbol_chop(
    symbol: str,
    adx_low: float = 18.0,
    adx_high: float = 22.0,
    bbw_pct_low: float = 30.0,
    bbw_pct_high: float = 40.0,
) -> dict[date, str]:
    """Researcher B HYP-REGIME-001 — per symbol chop/transition/trend classifier.

    Returns: dict[date -> mode] where mode:
      "chop"       -> skip (ADX < 18 + BBW pct < 30)
      "transition" -> half risk (ara)
      "trend"      -> full (ADX >= 22 + BBW pct >= 40)
    """
    df = _load_ohlcv(symbol, tf="1d")
    if df.empty:
        return {}

    # ADX(14) — Wilder
    high = df["high"]; low = df["low"]; close = df["close"]
    plus_dm = (high.diff()).where((high.diff() > low.diff().abs()) & (high.diff() > 0), 0.0).fillna(0)
    minus_dm = (low.diff().abs()).where((low.diff().abs() > high.diff()) & (low.diff() < 0), 0.0).fillna(0)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr14 = tr.ewm(alpha=1 / 14, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr14)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr14)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["adx14"] = dx.ewm(alpha=1 / 14, adjust=False).mean()

    # Bollinger Band Width (20, 2)
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    upper = sma20 + 2 * std20
    lower = sma20 - 2 * std20
    bbw = (upper - lower) / sma20 * 100
    # BBW percentile (252-day rolling)
    df["bbw_pct"] = bbw.rolling(252, min_periods=60).apply(
        lambda x: (x.iloc[-1] >= x).mean() * 100,
        raw=False,
    )

    out: dict[date, str] = {}
    for i in range(len(df)):
        adx = df["adx14"].iloc[i]
        bbw_p = df["bbw_pct"].iloc[i]
        if pd.isna(adx) or pd.isna(bbw_p):
            mode = "trend"  # default — yeterli veri yoksa tam risk
        elif adx < adx_low and bbw_p < bbw_pct_low:
            mode = "chop"
        elif adx >= adx_high and bbw_p >= bbw_pct_high:
            mode = "trend"
        else:
            mode = "transition"
        out[df["ts"].iloc[i].date()] = mode
    return out


def build_all_chop_calendars(symbols: list[str]) -> dict[str, dict[date, str]]:
    """Tum semboller icin chop calendar — bir kerede ana memory'e cache."""
    return {sym: compute_per_symbol_chop(sym) for sym in symbols}


def compute_btc_atr_pct_calendar(period: int = 14) -> dict[date, float]:
    """v1.6 sec15.4 — BTC ATR% calendar (vol-conditional adaptive risk icin).

    Causal: trade entry_ts T'de bakar -> calendar[T] = T-1 close-of-day verisi
    ile hesaplanan rolling 14-bar ATR / close. Lookahead-bias yok.

    Implementation:
      - Wilder ATR(14) BTC/USDT 1d
      - ATR / close = ATR% (oran, %4 = 0.04)
      - Calendar[T] = ATR%[T-1]  (T gunu giren trade T-1 close-of-day verisini bilir)

    Returns: dict[date -> float ATR% (oran)]
    """
    df = _load_ohlcv("BTC/USDT", tf="1d")

    # Wilder ATR(period)
    h_l = df["high"] - df["low"]
    h_c = (df["high"] - df["close"].shift()).abs()
    l_c = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([h_l, h_c, l_c], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / period, adjust=False).mean()
    df["atr_pct"] = df["atr"] / df["close"]   # ORAN (0.04 = %4)

    # CAUSAL shift: T gunu giren trade T-1 close-of-day verisini bilir
    df["atr_pct_lag1"] = df["atr_pct"].shift(1)

    out: dict[date, float] = {}
    for i in range(len(df)):
        v = df["atr_pct_lag1"].iloc[i]
        if pd.notna(v):
            out[df["ts"].iloc[i].date()] = float(v)
    return out


__all__ = [
    "compute_btc_capitulation_halt",
    "compute_per_symbol_chop",
    "build_all_chop_calendars",
    "compute_btc_atr_pct_calendar",
]
