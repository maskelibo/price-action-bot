"""Vektörize mum kalıbı detektörleri.

KRITIK:
    - Tüm fonksiyonlar SADECE geçmiş ve mevcut bar bilgisini kullanır.
    - `df.shift(-1)` veya benzeri lookahead operasyonu yasaktır.
    - Aynı (open, high, low, close) → aynı çıktı (deterministik).

Beklenen DataFrame şeması:
    columns: open, high, low, close (volume opsiyonel)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.logging_config import logger

_REQUIRED_COLS: tuple[str, ...] = ("open", "high", "low", "close")


def _validate(df: pd.DataFrame) -> None:
    missing = [c for c in _REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"OHLC kolonları eksik: {missing}")


def _ranges(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Yardımcı: range, body, wicks. Vektörize. NaN-safe."""
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    rng = (h - l).astype(float)
    body = (c - o).astype(float)  # +bullish, -bearish
    body_abs = body.abs()
    upper_wick = h - np.maximum(o, c)
    lower_wick = np.minimum(o, c) - l
    return {
        "range": rng,
        "body": body,
        "body_abs": body_abs,
        "upper_wick": upper_wick.astype(float),
        "lower_wick": lower_wick.astype(float),
    }


def _safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    """0'a bölmeden kaçınan oran. den==0 ise NaN."""
    den = den.where(den != 0, np.nan)
    return num / den


# ---------------------------------------------------------------------------
# Pin bar
# ---------------------------------------------------------------------------
def bullish_pin_bar(
    df: pd.DataFrame,
    params: dict[str, Any] | None = None,
) -> pd.Series:
    """Bullish pin bar (uzun alt fitil, küçük gövde, ihmal edilebilir üst fitil).

    Params:
        body_to_range_max: gövde / range üst sınırı (default 0.33)
        lower_wick_to_range_min: alt fitil / range alt sınırı (default 0.6)
        upper_wick_to_range_max: üst fitil / range üst sınırı (default 0.15)
    """
    _validate(df)
    p = params or {}
    body_max = float(p.get("body_to_range_max", 0.33))
    lower_min = float(p.get("lower_wick_to_range_min", 0.6))
    upper_max = float(p.get("upper_wick_to_range_max", 0.15))

    parts = _ranges(df)
    rng = parts["range"]
    body_ratio = _safe_div(parts["body_abs"], rng)
    lower_ratio = _safe_div(parts["lower_wick"], rng)
    upper_ratio = _safe_div(parts["upper_wick"], rng)

    flag = (
        (rng > 0)
        & (body_ratio <= body_max)
        & (lower_ratio >= lower_min)
        & (upper_ratio <= upper_max)
    )
    return flag.fillna(False).astype(bool)


def bearish_pin_bar(
    df: pd.DataFrame,
    params: dict[str, Any] | None = None,
) -> pd.Series:
    """Bearish pin bar (uzun üst fitil, küçük gövde, ihmal edilebilir alt fitil)."""
    _validate(df)
    p = params or {}
    body_max = float(p.get("body_to_range_max", 0.33))
    upper_min = float(p.get("upper_wick_to_range_min", 0.6))
    lower_max = float(p.get("lower_wick_to_range_max", 0.15))

    parts = _ranges(df)
    rng = parts["range"]
    body_ratio = _safe_div(parts["body_abs"], rng)
    upper_ratio = _safe_div(parts["upper_wick"], rng)
    lower_ratio = _safe_div(parts["lower_wick"], rng)

    flag = (
        (rng > 0)
        & (body_ratio <= body_max)
        & (upper_ratio >= upper_min)
        & (lower_ratio <= lower_max)
    )
    return flag.fillna(False).astype(bool)


# ---------------------------------------------------------------------------
# Engulfing
# ---------------------------------------------------------------------------
def bullish_engulfing(
    df: pd.DataFrame,
    params: dict[str, Any] | None = None,
) -> pd.Series:
    """Bullish engulfing: önceki mum bearish, mevcut mum bullish ve gövdesi
    önceki mumun gövdesini sarar (open <= prev_close, close >= prev_open)."""
    _validate(df)
    p = params or {}
    prev_body_min = float(p.get("prev_body_min_range_pct", 0.0))

    o, c = df["open"], df["close"]
    prev_o = o.shift(1)
    prev_c = c.shift(1)
    rng = (df["high"] - df["low"]).astype(float)
    prev_rng = rng.shift(1)
    prev_body_abs = (prev_c - prev_o).abs()
    prev_body_ratio = _safe_div(prev_body_abs, prev_rng)

    prev_bearish = prev_c < prev_o
    cur_bullish = c > o
    engulf = (o <= prev_c) & (c >= prev_o)
    body_ok = prev_body_ratio >= prev_body_min
    flag = prev_bearish & cur_bullish & engulf & body_ok
    return flag.fillna(False).astype(bool)


def bearish_engulfing(
    df: pd.DataFrame,
    params: dict[str, Any] | None = None,
) -> pd.Series:
    """Bearish engulfing: önceki bullish, mevcut bearish, mevcut gövde önceki gövdeyi sarar."""
    _validate(df)
    p = params or {}
    prev_body_min = float(p.get("prev_body_min_range_pct", 0.0))

    o, c = df["open"], df["close"]
    prev_o = o.shift(1)
    prev_c = c.shift(1)
    rng = (df["high"] - df["low"]).astype(float)
    prev_rng = rng.shift(1)
    prev_body_abs = (prev_c - prev_o).abs()
    prev_body_ratio = _safe_div(prev_body_abs, prev_rng)

    prev_bullish = prev_c > prev_o
    cur_bearish = c < o
    engulf = (o >= prev_c) & (c <= prev_o)
    body_ok = prev_body_ratio >= prev_body_min
    flag = prev_bullish & cur_bearish & engulf & body_ok
    return flag.fillna(False).astype(bool)


# ---------------------------------------------------------------------------
# Inside bar
# ---------------------------------------------------------------------------
def inside_bar(df: pd.DataFrame) -> pd.Series:
    """Inside bar: mevcut high < prev high AND mevcut low > prev low."""
    _validate(df)
    h, l = df["high"], df["low"]
    prev_h = h.shift(1)
    prev_l = l.shift(1)
    flag = (h < prev_h) & (l > prev_l)
    return flag.fillna(False).astype(bool)


def inside_bar_breakout(df: pd.DataFrame) -> pd.Series:
    """Inside bar breakout: önceki mum bir inside bar ise ve şimdiki mum
    onun aralığının dışında kapandıysa yön ('long'|'short'), aksi 'none'.

    KRITIK: Karar mevcut barın kapanışında alınır ve önceki bar'ın
    inside-bar olduğu olgusu sadece o anki kapanışla biliniyor olur. Bu
    nedenle SADECE geçmişi (t ve t-1) kullanır; lookahead yoktur.
    """
    _validate(df)
    inside_prev = inside_bar(df).shift(1).fillna(False)
    h, l, c = df["high"], df["low"], df["close"]
    prev_h = h.shift(1)
    prev_l = l.shift(1)
    long_break = inside_prev & (c > prev_h)
    short_break = inside_prev & (c < prev_l)
    out = pd.Series(np.where(long_break, "long", np.where(short_break, "short", "none")),
                    index=df.index, dtype=object)
    return out


# ---------------------------------------------------------------------------
# Morning / Evening star (3-bar)
# ---------------------------------------------------------------------------
def morning_star(df: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.Series:
    """Morning star (3-bar dip dönüşü).

    1) t-2: belirgin bearish (gövde ≥ params.first_body_min_ratio * range)
    2) t-1: küçük gövde (gövde / range ≤ params.middle_body_max_ratio); aşağıda gap olabilir
    3) t  : bullish ve close, ilk barın gövdesinin orta noktasının üstünde
    """
    _validate(df)
    p = params or {}
    first_body_min = float(p.get("first_body_min_ratio", 0.5))
    middle_body_max = float(p.get("middle_body_max_ratio", 0.35))

    o, c = df["open"], df["close"]
    rng = (df["high"] - df["low"]).astype(float)
    body = (c - o).astype(float)
    body_abs = body.abs()
    body_ratio = _safe_div(body_abs, rng)

    o2, c2 = o.shift(2), c.shift(2)
    body2 = (c2 - o2)
    body2_ratio = _safe_div(body2.abs(), rng.shift(2))
    first_bearish = (body2 < 0) & (body2_ratio >= first_body_min)

    body1_ratio = body_ratio.shift(1)
    middle_small = body1_ratio <= middle_body_max

    cur_bullish = body > 0
    midpoint_first = (o2 + c2) / 2.0
    close_above_mid = c > midpoint_first

    flag = first_bearish & middle_small & cur_bullish & close_above_mid
    return flag.fillna(False).astype(bool)


def evening_star(df: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.Series:
    """Evening star — morning star'ın aynası."""
    _validate(df)
    p = params or {}
    first_body_min = float(p.get("first_body_min_ratio", 0.5))
    middle_body_max = float(p.get("middle_body_max_ratio", 0.35))

    o, c = df["open"], df["close"]
    rng = (df["high"] - df["low"]).astype(float)
    body = (c - o).astype(float)
    body_abs = body.abs()
    body_ratio = _safe_div(body_abs, rng)

    o2, c2 = o.shift(2), c.shift(2)
    body2 = (c2 - o2)
    body2_ratio = _safe_div(body2.abs(), rng.shift(2))
    first_bullish = (body2 > 0) & (body2_ratio >= first_body_min)

    body1_ratio = body_ratio.shift(1)
    middle_small = body1_ratio <= middle_body_max

    cur_bearish = body < 0
    midpoint_first = (o2 + c2) / 2.0
    close_below_mid = c < midpoint_first

    flag = first_bullish & middle_small & cur_bearish & close_below_mid
    return flag.fillna(False).astype(bool)


# ---------------------------------------------------------------------------
# Doji
# ---------------------------------------------------------------------------
def doji(df: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.Series:
    """Doji: gövde / range ≤ body_to_range_max ve range > 0.

    Params:
        body_to_range_max: default 0.05
    """
    _validate(df)
    p = params or {}
    body_max = float(p.get("body_to_range_max", 0.05))

    parts = _ranges(df)
    rng = parts["range"]
    body_ratio = _safe_div(parts["body_abs"], rng)
    flag = (rng > 0) & (body_ratio <= body_max)
    return flag.fillna(False).astype(bool)


# Pakette modül seviye log emniyet kemeri (sessiz fail engelleme)
_ = logger
