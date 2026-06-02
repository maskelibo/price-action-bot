#!/usr/bin/env python3
# ruff: noqa: E741,N803,N802,N806,E702,SIM102,B007,F841
# (research script: L/l/h/c/o are deliberate OHLC/fractal-length conventions; the
#  semicolon groupings keep the vectorized math compact and readable.)
"""
SMC / SFP backtest harness — REUSABLE, lookahead-safe.

Codified from a verified course (Stage-1 rules replication-confirmed on BTC/USDT 1h).

Detectors (all causal — decision on bar t uses only data <= t-1; NO df.shift(-1),
NO center=True rolling, NO future leakage):
  - swing       : +/-L fractal (confirmed L bars after the pivot)
  - msb         : close-based break of prior confirmed swing extreme (structure/direction)
  - order block : last opposite-color candle before the break-impulse, quality-filtered
  - fvg         : 3-candle imbalance with a min-gap (fee-aware) filter
  - sfp         : single-bar liquidity sweep + close back inside (the standout signal)

Strategy = SFP entry + optional confluence gate (SFP at/near OB or FVG zone in the
discount/premium half) + optional MSB-direction filter.

Backtest:
  - fees 55bps round-trip (also reports 0bps raw edge)
  - mean_R after fees, win%, trade count
  - calendar-day Sharpe (NO annualization inflation)
  - max drawdown on R-equity curve

Robustness:
  - shuffle baseline (random direction, N seeds -> empirical p that real >= shuffle)
  - walk-forward (monthly OOS positive-month count)
  - per-symbol breakdown

CLI examples:
  python smc_sfp_backtest.py --tf 1h --confluence on --entry A --tp-mode fixed --R 2
  python smc_sfp_backtest.py --all              # full result matrix -> report numbers
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path("/Users/peyman/price-action-bot")
DB = ROOT / "data" / "market.duckdb"
CACHE = ROOT / "data" / "_smc_cache"
CACHE.mkdir(parents=True, exist_ok=True)

UNIVERSE = [
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "ADA",
    "AVAX",
    "LINK",
    "DOT",
    "DOGE",
    "XRP",
    "ZEC",
    "NEAR",
    "FIL",
    "XLM",
    "TRX",
]

FEE_RT_BPS = 55.0  # round-trip fees+slippage in basis points


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
def _git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return "nogit"


def load_ohlcv(symbol: str, tf: str) -> pd.DataFrame | None:
    """Load one symbol/timeframe as naive-UTC indexed OHLCV.

    5m,15m,1h are loaded direct. 30m/45m are resampled from a base TF
    (45m needs a 5m or 15m base whose period divides 45m; we use 5m if
    available else 15m). Returns None if not available.
    """
    sym = f"{symbol}/USDT"
    if tf in ("5m", "15m", "1h"):
        base_tf, rule = tf, None
    elif tf == "30m":
        base_tf, rule = "5m", "30min"
    elif tf == "45m":
        base_tf, rule = "5m", "45min"
    else:
        raise ValueError(f"unsupported tf {tf}")

    con = duckdb.connect(str(DB), read_only=True)
    try:
        # pick venue with most rows for this symbol/base_tf
        vrows = con.execute(
            "SELECT venue, count(*) n FROM ohlcv WHERE symbol=? AND timeframe=? "
            "GROUP BY venue ORDER BY n DESC LIMIT 1",
            [sym, base_tf],
        ).fetchall()
        if not vrows:
            return None
        venue = vrows[0][0]
        df = con.execute(
            "SELECT (ts AT TIME ZONE 'UTC') AS ts, open, high, low, close, volume "
            "FROM ohlcv WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts",
            [venue, sym, base_tf],
        ).fetch_df()
    finally:
        con.close()

    if df.empty:
        return None
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="first")]

    if rule is not None:
        # right-closed-left bars: pandas default label='left' for ohlc; keep left
        agg = df.resample(rule, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        )
        agg = agg.dropna(subset=["open", "high", "low", "close"])
        df = agg
    return df[["open", "high", "low", "close", "volume"]]


# --------------------------------------------------------------------------- #
# Detectors (causal)
# --------------------------------------------------------------------------- #
def detect_swings(df: pd.DataFrame, L: int):
    """+/-L fractal swings. A swing high at i requires high[i] == max(high[i-L:i+L+1]).
    A pivot is only KNOWN (confirmed) at bar i+L. We return per-pivot-index arrays plus
    the confirmation index, so downstream logic never uses a swing before it is visible.
    """
    high = df["high"].values
    low = df["low"].values
    n = len(df)
    if n < 2 * L + 1:
        return np.zeros(n, bool), np.zeros(n, bool)
    # rolling max/min over the centered (2L+1) window; a pivot at i is the window extreme.
    # vectorized via sliding_window_view on the padded array.
    from numpy.lib.stride_tricks import sliding_window_view

    w = 2 * L + 1
    hw = sliding_window_view(high, w)  # shape (n-w+1, w), row j covers bars j..j+w-1, center j+L
    lw = sliding_window_view(low, w)
    cmax = hw.max(axis=1)
    cmin = lw.min(axis=1)
    center = np.arange(L, n - L)
    is_sh = np.zeros(n, dtype=bool)
    is_sl = np.zeros(n, dtype=bool)
    is_sh[center] = high[center] >= cmax
    is_sl[center] = low[center] <= cmin
    # confirmation index = pivot index + L (used downstream for causality)
    return is_sh, is_sl


def _prior_confirmed_swings(df, L):
    """For each bar t, precompute lists of (pivot_idx, level) for swing highs/lows
    that are CONFIRMED by bar t (i.e. pivot_idx + L <= t-1, visible for decision on t).
    Returns two object arrays: most-recent prior confirmed swing high/low pivot idx.
    """
    is_sh, is_sl = detect_swings(df, L)
    n = len(df)
    sh_idx = np.where(is_sh)[0]
    sl_idx = np.where(is_sl)[0]
    # confirmation times
    sh_conf = sh_idx + L
    sl_conf = sl_idx + L
    return is_sh, is_sl, sh_idx, sh_conf, sl_idx, sl_conf


def detect_fvg(df: pd.DataFrame, min_gap_frac: float):
    """3-candle FVG. Bull FVG forms at candle c3 (index i) when low[i] > high[i-2].
    Zone=[high[i-2], low[i]]. Bear mirror. Only known at bar i (c3). min_gap filter on
    relative gap size. Returns dict idx -> (kind, lo, hi)."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)
    out = {}
    for i in range(2, n):
        # bull
        if low[i] > high[i - 2]:
            gap = (low[i] - high[i - 2]) / close[i]
            if gap >= min_gap_frac:
                out[i] = ("bull", high[i - 2], low[i])
        elif high[i] < low[i - 2]:
            gap = (low[i - 2] - high[i]) / close[i]
            if gap >= min_gap_frac:
                out[i] = ("bear", high[i], low[i - 2])
    return out


def detect_ob_msb(df: pd.DataFrame, L: int, min_gap_frac: float):
    """Walk forward; track most recent confirmed swing high/low. On a close-based break
    of the prior confirmed swing extreme, mark an MSB and build the order block = last
    opposite-color candle before the impulse leg. Quality filter: impulse leaves an FVG
    AND impulse range >= 2x OB-candle range.

    Returns:
      msb_dir : np.array length n, +1 bull break confirmed AT bar i, -1 bear, 0 none
      obs     : dict break_idx -> ('bull'/'bear', ob_lo, ob_hi)
    All causal: the break is detected at bar i using close[i] vs a swing confirmed <= i-1.
    """
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(df)
    is_sh, is_sl = detect_swings(df, L)

    msb_dir = np.zeros(n, dtype=np.int8)
    obs = {}

    last_sh_level = np.nan
    last_sh_pivot = -1
    last_sl_level = np.nan
    last_sl_pivot = -1

    for i in range(n):
        # 1) decide using swings confirmed by i-1: a pivot at p is confirmed when p+L <= i-1
        #    -> p <= i-1-L. Update the "available" swings up to that pivot.
        avail_p = i - 1 - L
        if avail_p >= 0:
            if is_sh[avail_p]:
                last_sh_level = h[avail_p]
                last_sh_pivot = avail_p
            if is_sl[avail_p]:
                last_sl_level = l[avail_p]
                last_sl_pivot = avail_p

        # 2) close-based break test on bar i
        if not np.isnan(last_sh_level) and c[i] > last_sh_level:
            msb_dir[i] = 1
            ob = _build_ob(o, c, h, l, last_sh_pivot, i, "bull")
            if ob is not None and _ob_quality(df, ob, i, L, min_gap_frac, "bull"):
                obs[i] = ("bull", ob[0], ob[1])
            # reset so we don't re-fire same level
            last_sh_level = np.nan
        elif not np.isnan(last_sl_level) and c[i] < last_sl_level:
            msb_dir[i] = -1
            ob = _build_ob(o, c, h, l, last_sl_pivot, i, "bear")
            if ob is not None and _ob_quality(df, ob, i, L, min_gap_frac, "bear"):
                obs[i] = ("bear", ob[0], ob[1])
            last_sl_level = np.nan

    return msb_dir, obs


def _build_ob(o, c, h, l, pivot_idx, break_idx, direction):
    """OB = last opposite-color candle before the impulse leg [pivot..break]."""
    if pivot_idx < 0 or break_idx <= pivot_idx:
        return None
    if direction == "bull":
        # impulse is up -> OB = last red (close<open) candle before break, scanning back
        for j in range(break_idx - 1, pivot_idx - 1, -1):
            if c[j] < o[j]:
                return (l[j], h[j])
    else:
        for j in range(break_idx - 1, pivot_idx - 1, -1):
            if c[j] > o[j]:
                return (l[j], h[j])
    return None


def _ob_quality(df, ob, break_idx, L, min_gap_frac, direction):
    """impulse leaves an FVG (within the impulse window) AND impulse range >= 2x OB range."""
    h = df["high"].values
    l = df["low"].values
    ob_range = ob[1] - ob[0]
    if ob_range <= 0:
        return False
    # impulse window: a small window around the break
    w0 = max(0, break_idx - 5)
    impulse_range = h[w0 : break_idx + 1].max() - l[w0 : break_idx + 1].min()
    if impulse_range < 2.0 * ob_range:
        return False
    # FVG present in impulse window?
    for i in range(w0 + 2, break_idx + 1):
        if direction == "bull" and l[i] > h[i - 2]:
            if (l[i] - h[i - 2]) / df["close"].values[i] >= min_gap_frac:
                return True
        if direction == "bear" and h[i] < l[i - 2]:
            if (l[i - 2] - h[i]) / df["close"].values[i] >= min_gap_frac:
                return True
    return False


def detect_sfp(df: pd.DataFrame, L: int, sweep_lookback: int):
    """SFP: bar i wicks beyond the most recent prior CONFIRMED fractal swing
    low/high within sweep_lookback bars, but CLOSES back inside.

    Bullish SFP: low[i] < swept_swing_low AND close[i] > swept_swing_low.
    Bearish SFP: high[i] > swept_swing_high AND close[i] < swept_swing_high.

    Causal: the swept swing must be confirmed by i-1 (pivot p with p+L <= i-1) and
    within [i-sweep_lookback, i-1]. Returns list of dicts.
    """
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(df)
    is_sh, is_sl = detect_swings(df, L)
    sh_idx = np.where(is_sh)[0]
    sl_idx = np.where(is_sl)[0]

    # Vectorized: for each bar i, find most-recent confirmed swing low/high within lookback.
    # "confirmed by i-1" => pivot p satisfies p + L <= i-1, i.e. p <= i-1-L.
    # We build, for every confirmation-time, the level that becomes available, then
    # forward-fill the most recent available level and pivot index.
    idx_all = np.arange(n)
    # swing low: available from bar (p+L+1) onward (decision bar i has cutoff i-1-L >= p)
    avail_sl_level = np.full(n, np.nan)
    avail_sl_pivot = np.full(n, -1)
    for p in sl_idx:
        a = p + L + 1
        if a < n:
            avail_sl_level[a] = l[p]
            avail_sl_pivot[a] = p
    avail_sh_level = np.full(n, np.nan)
    avail_sh_pivot = np.full(n, -1)
    for p in sh_idx:
        a = p + L + 1
        if a < n:
            avail_sh_level[a] = h[p]
            avail_sh_pivot[a] = p
    # forward-fill most-recent available level + its pivot
    sl_lvl = pd.Series(avail_sl_level).ffill().values
    sl_piv = pd.Series(np.where(avail_sl_pivot < 0, np.nan, avail_sl_pivot)).ffill().values
    sh_lvl = pd.Series(avail_sh_level).ffill().values
    sh_piv = pd.Series(np.where(avail_sh_pivot < 0, np.nan, avail_sh_pivot)).ffill().values

    signals = []
    for i in range(L + 1, n):
        lb_start = i - sweep_lookback
        # bullish sweep of swing low
        if not np.isnan(sl_lvl[i]) and sl_piv[i] >= lb_start:
            swept = sl_lvl[i]
            if l[i] < swept and c[i] > swept:
                signals.append(
                    {
                        "idx": i,
                        "dir": 1,
                        "swept_level": float(swept),
                        "swept_pivot": int(sl_piv[i]),
                        "wick_tip": float(l[i]),
                    }
                )
        # bearish sweep of swing high
        if not np.isnan(sh_lvl[i]) and sh_piv[i] >= lb_start:
            swept = sh_lvl[i]
            if h[i] > swept and c[i] < swept:
                signals.append(
                    {
                        "idx": i,
                        "dir": -1,
                        "swept_level": float(swept),
                        "swept_pivot": int(sh_piv[i]),
                        "wick_tip": float(h[i]),
                    }
                )
    return signals


# --------------------------------------------------------------------------- #
# Strategy / backtest
# --------------------------------------------------------------------------- #
@dataclass
class Params:
    L: int = 3
    sweep_lookback: int = 48
    min_gap: float = 0.0010  # 0.10%
    confluence: bool = True  # require SFP near OB/FVG in discount/premium half
    confluence_dist_atr: float = 0.5
    use_msb_filter: bool = False
    entry: str = "A"  # A=SFP close, B=next confirmation bar close
    sl_buffer_atr: float = 0.10
    tp_mode: str = "fixed"  # fixed | structure
    R: float = 2.0
    max_hold: int = 48
    atr_period: int = 14


def _atr(df, period):
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = pd.Series(tr).rolling(period, min_periods=1).mean().values
    return atr


_DETECT_CACHE: dict = {}


def _df_fp(df: pd.DataFrame):
    """Stable fingerprint for a dataframe (id() alone is unsafe — ids get reused
    after GC, which silently returned stale cached arrays sized for a different df)."""
    return (
        id(df),
        len(df),
        int(df.index[0].value),
        int(df.index[-1].value),
        float(df["close"].iloc[-1]),
    )


def _detect_all(df: pd.DataFrame, p: Params):
    """Deterministic detection (SFP, OB/MSB, FVG) — cached so shuffle reuses it."""
    key = (_df_fp(df), p.L, p.sweep_lookback, round(p.min_gap, 8), p.confluence, p.use_msb_filter)
    if key in _DETECT_CACHE:
        return _DETECT_CACHE[key]
    n = len(df)
    sfp = detect_sfp(df, p.L, p.sweep_lookback)
    msb_dir, obs = (
        detect_ob_msb(df, p.L, p.min_gap)
        if (p.confluence or p.use_msb_filter)
        else (np.zeros(n, np.int8), {})
    )
    fvg = detect_fvg(df, p.min_gap) if p.confluence else {}
    res = (sfp, msb_dir, obs, fvg)
    if len(_DETECT_CACHE) > 200:
        _DETECT_CACHE.clear()
    _DETECT_CACHE[key] = res
    return res


_CAND_CACHE: dict = {}


def _build_candidates(df: pd.DataFrame, p: Params):
    """Deterministic, direction-independent candidate selection (gate + levels).
    Cached so shuffle reuses it. Returns dict of arrays + zone arrays for structure-TP."""
    key = (
        _df_fp(df),
        p.L,
        p.sweep_lookback,
        round(p.min_gap, 8),
        p.confluence,
        p.use_msb_filter,
        p.entry,
        round(p.confluence_dist_atr, 4),
    )
    if key in _CAND_CACHE:
        return _CAND_CACHE[key]

    c = df["close"].values
    atr = _atr(df, p.atr_period)
    n = len(df)
    sfp, msb_dir, obs, fvg = _detect_all(df, p)

    zones = []
    for idx, (kind, lo, hi) in obs.items():
        zones.append((kind, lo, hi, idx))
    for idx, (kind, lo, hi) in fvg.items():
        zones.append((kind, lo, hi, idx))
    zones.sort(key=lambda z: z[3])
    z_kind = np.array([1 if z[0] == "bull" else -1 for z in zones], dtype=np.int8)
    z_lo = np.array([z[1] for z in zones], dtype=float)
    z_hi = np.array([z[2] for z in zones], dtype=float)
    z_mid = (z_lo + z_hi) / 2.0
    z_f = np.array([z[3] for z in zones], dtype=int)

    struct = np.zeros(n, dtype=np.int8)
    cur = 0
    for i in range(n):
        if msb_dir[i] != 0:
            cur = msb_dir[i]
        struct[i] = cur

    e_idx_l, ent_l, tip_l, base_dir_l, atr_l = [], [], [], [], []
    for s in sfp:
        i = s["idx"]
        direction = s["dir"]
        if p.entry == "A":
            e_idx = i
            entry_price = c[i]
        else:
            if i + 1 >= n:
                continue
            e_idx = i + 1
            entry_price = c[i + 1]
        a = atr[i] if atr[i] > 0 else (c[i] * 0.005)

        if p.confluence and z_kind.size:
            want = 1 if direction == 1 else -1
            tip = s["wick_tip"]
            m = (z_f <= i) & (z_kind == want)
            if not m.any():
                continue
            zlo = z_lo[m]
            zhi = z_hi[m]
            inside = (zlo <= tip) & (tip <= zhi)
            d = np.where(inside, 0.0, np.minimum(np.abs(tip - zlo), np.abs(tip - zhi)))
            if not (d <= p.confluence_dist_atr * a).any():
                continue
        elif p.confluence and not z_kind.size:
            continue

        if p.use_msb_filter and struct[i] != direction:
            continue

        e_idx_l.append(e_idx)
        ent_l.append(entry_price)
        tip_l.append(s["wick_tip"])
        base_dir_l.append(direction)
        atr_l.append(a)

    cand = dict(
        e_idx=np.array(e_idx_l, dtype=int),
        ent=np.array(ent_l, dtype=float),
        tip=np.array(tip_l, dtype=float),
        base_dir=np.array(base_dir_l, dtype=np.int8),
        atr=np.array(atr_l, dtype=float),
        z_kind=z_kind,
        z_mid=z_mid,
        z_f=z_f,
    )
    if len(_CAND_CACHE) > 200:
        _CAND_CACHE.clear()
    _CAND_CACHE[key] = cand
    return cand


def backtest_symbol(df: pd.DataFrame, p: Params, randomize_dir: np.random.Generator | None = None):
    """Returns list of trade dicts with R (gross & net). randomize_dir: if given, the
    trade DIRECTION is randomized (shuffle baseline) keeping entry timing/levels intact."""
    if df is None or len(df) < (p.L * 2 + p.atr_period + 50):
        return []
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(df)

    cand = _build_candidates(df, p)
    e_idx_a = cand["e_idx"]
    if e_idx_a.size == 0:
        return []
    ent_a = cand["ent"]
    tip_a = cand["tip"]
    atr_a = cand["atr"]
    z_kind = cand["z_kind"]
    z_mid = cand["z_mid"]
    z_f = cand["z_f"]

    if randomize_dir is not None:
        dir_a = np.where(randomize_dir.random(len(e_idx_a)) < 0.5, 1, -1).astype(np.int8)
    else:
        dir_a = cand["base_dir"]

    # ---- 2) SL / risk / TP (vectorized) ----
    sl_a = np.where(dir_a == 1, tip_a - p.sl_buffer_atr * atr_a, tip_a + p.sl_buffer_atr * atr_a)
    risk_a = np.where(dir_a == 1, ent_a - sl_a, sl_a - ent_a)
    valid = risk_a > 0
    risk_safe = np.where(valid, risk_a, np.nan)  # avoid div-by-zero warnings

    if p.tp_mode == "fixed":
        tp_a = ent_a + dir_a * p.R * risk_a
    else:
        tp_a = ent_a + dir_a * p.R * risk_a  # default fallback
        for k in range(len(e_idx_a)):
            i = e_idx_a[k]
            want_opp = -1 if dir_a[k] == 1 else 1
            m = (z_f <= i) & (z_kind == want_opp)
            if not m.any():
                continue
            mids = z_mid[m]
            if dir_a[k] == 1:
                cc_ = mids[mids > ent_a[k]]
                if cc_.size:
                    tp_a[k] = cc_.min()
            else:
                cc_ = mids[mids < ent_a[k]]
                if cc_.size:
                    tp_a[k] = cc_.max()

    # ---- 3) vectorized first-touch exit over [e+1, e+max_hold] ----
    H = p.max_hold
    # offsets matrix: for each trade, the bar indices to scan
    offs = e_idx_a[:, None] + 1 + np.arange(H)[None, :]  # (T, H)
    in_range = offs < n
    offs_clip = np.clip(offs, 0, n - 1)
    hh = h[offs_clip]
    ll = l[offs_clip]
    cc = c[offs_clip]
    hh = np.where(in_range, hh, np.nan)
    ll = np.where(in_range, ll, np.nan)

    long = dir_a == 1
    # touch booleans per step
    sl_hit = np.where(long[:, None], ll <= sl_a[:, None], hh >= sl_a[:, None])
    tp_hit = np.where(long[:, None], hh >= tp_a[:, None], ll <= tp_a[:, None])
    sl_hit = sl_hit & in_range
    tp_hit = tp_hit & in_range

    def first_true_idx(mat):
        any_t = mat.any(axis=1)
        idx = np.where(any_t, mat.argmax(axis=1), H)  # H = none
        return idx, any_t

    sl_first, _ = first_true_idx(sl_hit)
    tp_first, _ = first_true_idx(tp_hit)
    # SL priority on same bar (conservative): if both touch on same step, SL wins
    sl_step = np.where(sl_hit.any(axis=1), sl_first, H + 1)
    tp_step = np.where(tp_hit.any(axis=1), tp_first, H + 1)

    T = len(e_idx_a)
    tp_R = np.abs(tp_a - ent_a) / risk_safe
    has_sl = sl_step <= H
    has_tp = tp_step <= H
    timed = (~has_sl) & (~has_tp)
    sl_wins = has_sl & (sl_step <= tp_step)  # SL first or tie
    tp_wins = has_tp & (~sl_wins)

    # exit step per trade
    exit_step = np.where(sl_wins, sl_step, np.where(tp_wins, tp_step, 0))
    # for timed exits: last in-range step
    last_step = np.where(
        in_range.any(axis=1), in_range.shape[1] - 1 - in_range[:, ::-1].argmax(axis=1), 0
    )
    exit_step = np.where(timed, last_step, exit_step)

    # close at timed-exit step (per trade)
    cc_at = cc[np.arange(T), exit_step]
    timed_R = np.where(dir_a == 1, (cc_at - ent_a), (ent_a - cc_at)) / risk_safe
    R_gross = np.where(sl_wins, -1.0, np.where(tp_wins, tp_R, timed_R))

    fee_frac = FEE_RT_BPS / 10000.0
    fee_R_a = fee_frac / (risk_safe / ent_a)
    R_net = R_gross - fee_R_a
    exit_bar = np.clip(e_idx_a + 1 + exit_step, 0, n - 1)

    ts_index = df.index
    v = valid
    eb = exit_bar[v]
    eidx = e_idx_a[v]
    dv = dir_a[v]
    rg = R_gross[v]
    rn = R_net[v]
    fr = fee_R_a[v]
    entry_ts = ts_index[eidx]
    exit_ts = ts_index[eb]
    trades = [
        {
            "entry_ts": entry_ts[k],
            "exit_ts": exit_ts[k],
            "dir": int(dv[k]),
            "R_gross": float(rg[k]),
            "R_net": float(rn[k]),
            "fee_R": float(fr[k]),
        }
        for k in range(len(eidx))
    ]
    return trades


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def calendar_day_sharpe(trades: list, r_key="R_net") -> float:
    """Sharpe of daily summed R, NO annualization. mean/std of per-calendar-day R."""
    if not trades:
        return 0.0
    df = pd.DataFrame(trades)
    df["day"] = pd.to_datetime(df["exit_ts"]).dt.floor("D")
    daily = df.groupby("day")[r_key].sum()
    if daily.std(ddof=1) == 0 or len(daily) < 2:
        return 0.0
    return float(daily.mean() / daily.std(ddof=1))


def max_drawdown_R(trades: list, r_key="R_net") -> float:
    if not trades:
        return 0.0
    eq = np.cumsum([t[r_key] for t in sorted(trades, key=lambda x: x["exit_ts"])])
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    return float(dd.min())


def summarize(trades: list) -> dict:
    if not trades:
        return dict(n=0, mean_R_0=0.0, mean_R_55=0.0, win=0.0, sharpe=0.0, mdd=0.0, total_R=0.0)
    rg = np.array([t["R_gross"] for t in trades])
    rn = np.array([t["R_net"] for t in trades])
    return dict(
        n=len(trades),
        mean_R_0=float(rg.mean()),
        mean_R_55=float(rn.mean()),
        win=float((rn > 0).mean() * 100),
        sharpe=calendar_day_sharpe(trades),
        mdd=max_drawdown_R(trades),
        total_R=float(rn.sum()),
    )


# --------------------------------------------------------------------------- #
# Robustness
# --------------------------------------------------------------------------- #
def shuffle_pvalue(per_symbol_df: dict, p: Params, n_seeds=50) -> dict:
    """Empirical p that real mean_R_net >= shuffled (random-direction) mean_R_net."""
    real_trades = []
    for sym, df in per_symbol_df.items():
        real_trades += backtest_symbol(df, p)
    real_net = summarize(real_trades)["mean_R_55"]
    real_gross = float(np.mean([t["R_gross"] for t in real_trades])) if real_trades else 0.0
    shuf_net, shuf_gross = [], []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        st = []
        for sym, df in per_symbol_df.items():
            st += backtest_symbol(df, p, randomize_dir=rng)
        if st:
            shuf_net.append(np.mean([t["R_net"] for t in st]))
            shuf_gross.append(np.mean([t["R_gross"] for t in st]))
    sn = np.array(shuf_net)
    sg = np.array(shuf_gross)
    if len(sn) == 0:
        return dict(real_net=real_net, p_net=1.0, p_gross=1.0)
    # p_gross is the HONEST directional-edge test (fee-independent); p_net is fee-confounded
    return dict(
        real_net=real_net,
        real_gross=real_gross,
        p_net=float((sn >= real_net).mean()),
        p_gross=float((sg >= real_gross).mean()),
        shuf_net_mean=float(sn.mean()),
        shuf_gross_mean=float(sg.mean()),
    )


def walk_forward_months(per_symbol_df: dict, p: Params) -> dict:
    """Monthly OOS positive-month count (pooled across symbols by exit month)."""
    all_tr = []
    for sym, df in per_symbol_df.items():
        all_tr += backtest_symbol(df, p)
    if not all_tr:
        return dict(months=0, pos=0, frac=0.0)
    d = pd.DataFrame(all_tr)
    d["month"] = pd.to_datetime(d["exit_ts"]).dt.to_period("M")
    by = d.groupby("month")["R_net"].sum()
    return dict(
        months=len(by),
        pos=int((by > 0).sum()),
        frac=float((by > 0).mean()),
        monthly_meanR=float(d.groupby("month")["R_net"].sum().mean()),
    )


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def available_symbols(tf: str) -> list:
    syms = []
    for s in UNIVERSE:
        df = load_ohlcv(s, tf)
        if df is not None and len(df) > 500:
            syms.append(s)
    return syms


def load_universe(tf: str) -> dict:
    out = {}
    for s in UNIVERSE:
        df = load_ohlcv(s, tf)
        if df is not None and len(df) > 500:
            out[s] = df
    return out


def run_one(tf: str, p: Params, n_seeds=50, do_robust=True) -> dict:
    uni = load_universe(tf)
    per_sym = {}
    all_tr = []
    for sym, df in uni.items():
        tr = backtest_symbol(df, p)
        per_sym[sym] = summarize(tr)
        all_tr += tr
    agg = summarize(all_tr)
    res = dict(tf=tf, params=asdict(p), agg=agg, per_symbol=per_sym, n_symbols=len(uni))
    if do_robust:
        res["shuffle"] = shuffle_pvalue(uni, p, n_seeds=n_seeds)
        res["walk_forward"] = walk_forward_months(uni, p)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--confluence", choices=["on", "off"], default="on")
    ap.add_argument("--msb-filter", action="store_true")
    ap.add_argument("--entry", choices=["A", "B"], default="A")
    ap.add_argument("--tp-mode", choices=["fixed", "structure"], default="fixed")
    ap.add_argument("--R", type=float, default=2.0)
    ap.add_argument("--L", type=int, default=3)
    ap.add_argument("--sweep-lookback", type=int, default=48)
    ap.add_argument("--min-gap", type=float, default=0.0010)
    ap.add_argument("--max-hold", type=int, default=48)
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--all", action="store_true", help="run full TF x config matrix")
    ap.add_argument("--no-robust", action="store_true")
    args = ap.parse_args()

    if args.all:
        out = {"git": _git_hash(), "fee_rt_bps": FEE_RT_BPS, "matrix": []}
        for tf in ["5m", "15m", "30m", "45m", "1h"]:
            for conf in [False, True]:
                p = Params(
                    L=args.L,
                    sweep_lookback=args.sweep_lookback,
                    min_gap=args.min_gap,
                    confluence=conf,
                    entry=args.entry,
                    tp_mode=args.tp_mode,
                    R=args.R,
                    max_hold=args.max_hold,
                )
                print(f"[run] tf={tf} confluence={conf} ...", file=sys.stderr)
                res = run_one(tf, p, n_seeds=args.seeds, do_robust=not args.no_robust)
                out["matrix"].append(res)
                a = res["agg"]
                sh = res.get("shuffle", {})
                wf = res.get("walk_forward", {})
                print(
                    f"   n={a['n']} R0={a['mean_R_0']:.3f} R55={a['mean_R_55']:.3f} "
                    f"win={a['win']:.1f}% sharpe={a['sharpe']:.3f} "
                    f"p_gross={sh.get('p_gross','-')} p_net={sh.get('p_net','-')} "
                    f"wf={wf.get('pos','-')}/{wf.get('months','-')}",
                    file=sys.stderr,
                )
        outp = CACHE / "matrix_results.json"
        outp.write_text(json.dumps(out, indent=2, default=str))
        print(f"WROTE {outp}", file=sys.stderr)
    else:
        p = Params(
            L=args.L,
            sweep_lookback=args.sweep_lookback,
            min_gap=args.min_gap,
            confluence=(args.confluence == "on"),
            use_msb_filter=args.msb_filter,
            entry=args.entry,
            tp_mode=args.tp_mode,
            R=args.R,
            max_hold=args.max_hold,
        )
        res = run_one(args.tf, p, n_seeds=args.seeds, do_robust=not args.no_robust)
        print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
