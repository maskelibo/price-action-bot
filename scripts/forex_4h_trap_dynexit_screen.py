"""Screen of Brooks trap-family extensions (A1/A2/A3) + dynamic-exit re-tests (B1/B2).

Pre-registered (code-after-prereg), memory/researcher/hypotheses/:
  A1 brooks_failed_swing      2026-05-29-forex-brooks-trap-family-A1-failed-swing.md
  A2 double_top_bottom        2026-05-29-forex-brooks-trap-family-A2-double-top-bottom-failed.md
  A3 wyckoff_spring_upthrust  2026-05-29-forex-brooks-trap-family-A3-wyckoff-spring-upthrust.md
  B1 ema20_pullback_dynexit   2026-05-29-forex-ema20-pullback-dynamic-exit-B1.md
  B2 atr_squeeze_dynexit      2026-05-29-forex-atr-squeeze-breakout-fixed-gating-dynamic-exit-B2.md

Honest cost model IDENTICAL to scripts/forex_4h_research.py /
scripts/forex_4h_newfamilies_screen.py:
  fee=0, slip 1.0bps round-trip (split entry+exit), swap 0.3bps/night (Wed triple),
  session bar-OPEN 07-16 UTC, weekend no-entry, cooldown 6 bars (24h),
  next-bar OPEN entry, SL-first conservative intrabar.

Two exit engines:
  - simulate_fixed_tp(): original fixed-target/2R (for the A-family structure targets and
    for the F3/F5 "twin" comparison).
  - simulate_dynamic(): initial SL -> BE@+1R -> trail prior-bar swing +-0.5*ATR (runner).

IS=2020-2023, OOS=2024-2025 frozen. Verdict per pre-reg.

Usage: .venv/bin/python scripts/forex_4h_trap_dynexit_screen.py
"""
from __future__ import annotations

import hashlib
import math
import os
import sys
from pathlib import Path
from statistics import mean

os.environ["PA_LOG_QUIET"] = "1"
import warnings

warnings.filterwarnings("ignore")

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

DB = ROOT / "data" / "forex_market.duckdb"
SYMBOL = "EUR/USD"
TF = "4h"

SLIPPAGE_BPS = 1.0
SLIPPAGE_BPS_STRESS = 1.7
SWAP_BPS_PER_NIGHT = 0.3
SESSION_START_H = 7
SESSION_END_H = 16
SEED = 12345
rng = np.random.default_rng(SEED)

IS_START = pd.Timestamp("2020-01-01", tz="UTC")
IS_END = pd.Timestamp("2024-01-01", tz="UTC")
OOS_START = IS_END
OOS_END = pd.Timestamp("2026-01-01", tz="UTC")

COOLDOWN_BARS = 6
PIVOT_K = 3          # fractal window (confirmed at p+K)
MAX_R_CAP = 3.0      # cap structure targets at 3R


# --------------------------------------------------------------------------- data
def load_ohlcv() -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close FROM ohlcv WHERE symbol=? AND timeframe=? ORDER BY ts",
        [SYMBOL, TF],
    ).fetchdf()
    con.close()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    return df


def data_hash(df: pd.DataFrame) -> str:
    h = hashlib.sha256()
    h.update(df[["open", "high", "low", "close"]].to_numpy().tobytes())
    h.update(str(df["ts"].iloc[0]).encode())
    h.update(str(df["ts"].iloc[-1]).encode())
    return h.hexdigest()[:16]


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - c.shift(1)).abs(),
        (df["low"] - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(14, min_periods=14).mean()
    df["ema20"] = c.ewm(span=20, adjust=False).mean()
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    df["ema200"] = c.ewm(span=200, adjust=False).mean()
    df["don20_hi"] = df["high"].shift(1).rolling(20, min_periods=20).max()
    df["don20_lo"] = df["low"].shift(1).rolling(20, min_periods=20).min()
    df["atr_med50"] = df["atr14"].rolling(50, min_periods=50).median()
    df["hour"] = df["ts"].dt.hour
    df["dow"] = df["ts"].dt.dayofweek
    return df


# --------------------------------------------------------------------------- filters
def in_session(ts: pd.Timestamp) -> bool:
    return SESSION_START_H <= ts.hour <= SESSION_END_H


def is_weekend_block(ts: pd.Timestamp) -> bool:
    wd = ts.dayofweek
    if wd == 4 and ts.hour >= 16:
        return True
    return wd in (5, 6)


def nights_held(entry_ts: pd.Timestamp, exit_ts: pd.Timestamp) -> int:
    if exit_ts <= entry_ts:
        return 0
    d0 = entry_ts.normalize()
    d1 = exit_ts.normalize()
    nights = int((d1 - d0).days)
    if nights <= 0:
        return 0
    triple = 0
    cur = d0 + pd.Timedelta(days=1)
    while cur <= d1:
        if cur.dayofweek == 2:
            triple += 1
        cur += pd.Timedelta(days=1)
    return nights + 2 * triple


# --------------------------------------------------------------------------- fractal pivots
def confirmed_pivots(df: pd.DataFrame, k: int = PIVOT_K):
    """Return arrays pivot_hi_idx, pivot_lo_idx: for each bar index i, the index of the most
    recent pivot high/low CONFIRMED by bar i (i.e. pivot at p with p+k <= i). Causal."""
    h = df["high"].values
    l = df["low"].values
    n = len(df)
    is_ph = np.zeros(n, dtype=bool)
    is_pl = np.zeros(n, dtype=bool)
    for p in range(k, n - k):
        win_h = h[p - k:p + k + 1]
        win_l = l[p - k:p + k + 1]
        if h[p] == win_h.max() and (win_h == h[p]).sum() == 1:
            is_ph[p] = True
        if l[p] == win_l.min() and (win_l == l[p]).sum() == 1:
            is_pl[p] = True
    return is_ph, is_pl


# --------------------------------------------------------------------------- signal detectors
# Each returns list of dicts: {sig_idx, side, sl, tp, dyn(bool)}.
# sig_idx = decision bar t; entry at t+1 OPEN. dyn=True -> use dynamic exit (tp ignored).

def sig_A1_failed_swing(df: pd.DataFrame) -> list[dict]:
    """Failed break of a confirmed fractal swing point (bull/bear trap). Structure target."""
    h, l, c, o = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    atr = df["atr14"].values
    is_ph, is_pl = confirmed_pivots(df)
    n = len(df)
    # rolling last-confirmed pivot levels (confirmed at p+K)
    out = []
    # precompute, for each bar, the most recent confirmed pivot-high level and paired pivot-low
    last_ph_level = np.full(n, np.nan)
    last_ph_pairlo = np.full(n, np.nan)
    last_pl_level = np.full(n, np.nan)
    last_pl_pairhi = np.full(n, np.nan)
    cur_ph = np.nan; cur_ph_pairlo = np.nan
    cur_pl = np.nan; cur_pl_pairhi = np.nan
    recent_lo = np.nan; recent_hi = np.nan
    for i in range(n):
        # a pivot at p is confirmed at p+K
        p = i - PIVOT_K
        if p >= 0:
            if is_ph[p]:
                cur_ph = h[p]
                cur_ph_pairlo = recent_lo  # last confirmed swing low before this high
            if is_pl[p]:
                cur_pl = l[p]
                cur_pl_pairhi = recent_hi
            if is_ph[p]:
                recent_hi = h[p]
            if is_pl[p]:
                recent_lo = l[p]
        last_ph_level[i] = cur_ph
        last_ph_pairlo[i] = cur_ph_pairlo
        last_pl_level[i] = cur_pl
        last_pl_pairhi[i] = cur_pl_pairhi

    # detect breakout then failure
    # bull BO: high[b] > swing_hi & close[b] > swing_hi ; failure within b+1..b+3 close < swing_hi
    for b in range(PIVOT_K + 1, n):
        if np.isnan(atr[b]):
            continue
        # --- bull trap (short) ---
        swing_hi = last_ph_level[b]
        range_lo = last_ph_pairlo[b]
        if not np.isnan(swing_hi) and h[b] > swing_hi and c[b] > swing_hi:
            for f in range(b + 1, min(b + 4, n)):
                if c[f] < swing_hi:
                    if np.isnan(atr[f]):
                        break
                    entry_ref = c[f]
                    sl = h[b] + 0.25 * atr[f]
                    risk = sl - entry_ref
                    if risk <= 0:
                        break
                    tp = range_lo if not np.isnan(range_lo) else entry_ref - 2 * risk
                    if tp >= entry_ref:
                        break
                    # cap at 3R, reward/risk>=1
                    if (entry_ref - tp) > MAX_R_CAP * risk:
                        tp = entry_ref - MAX_R_CAP * risk
                    if (entry_ref - tp) < risk:
                        break
                    out.append({"sig_idx": f, "side": "short", "sl": sl, "tp": tp})
                    break
        # --- bear trap (long) ---
        swing_lo = last_pl_level[b]
        range_hi = last_pl_pairhi[b]
        if not np.isnan(swing_lo) and l[b] < swing_lo and c[b] < swing_lo:
            for f in range(b + 1, min(b + 4, n)):
                if c[f] > swing_lo:
                    if np.isnan(atr[f]):
                        break
                    entry_ref = c[f]
                    sl = l[b] - 0.25 * atr[f]
                    risk = entry_ref - sl
                    if risk <= 0:
                        break
                    tp = range_hi if not np.isnan(range_hi) else entry_ref + 2 * risk
                    if tp <= entry_ref:
                        break
                    if (tp - entry_ref) > MAX_R_CAP * risk:
                        tp = entry_ref + MAX_R_CAP * risk
                    if (tp - entry_ref) < risk:
                        break
                    out.append({"sig_idx": f, "side": "long", "sl": sl, "tp": tp})
                    break
    return out


def sig_A2_double_top_bottom(df: pd.DataFrame) -> list[dict]:
    """Double top/bottom: two pivot highs within 0.5ATR, 3-15 bars apart, neckline break."""
    h, l, c, o = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    atr = df["atr14"].values
    is_ph, is_pl = confirmed_pivots(df)
    n = len(df)
    ph_idx = [p for p in range(n) if is_ph[p]]
    pl_idx = [p for p in range(n) if is_pl[p]]
    out = []

    # double top -> short. iterate confirmed pivot-high pairs
    for j in range(1, len(ph_idx)):
        p2 = ph_idx[j]; p1 = ph_idx[j - 1]
        sep = p2 - p1
        if sep < 3 or sep > 15:
            continue
        if np.isnan(atr[p2]):
            continue
        if abs(h[p2] - h[p1]) > 0.5 * atr[p2]:
            continue
        neckline = l[p1 + 1:p2].min() if p2 > p1 + 1 else min(l[p1], l[p2])
        top = max(h[p1], h[p2])
        # trigger: first bar t after p2 confirmation (p2+K) with close<neckline & close<open
        start = p2 + PIVOT_K
        for t in range(start, min(start + 15, n)):
            if np.isnan(atr[t]):
                break
            if c[t] < neckline and c[t] < o[t]:
                entry_ref = c[t]
                sl = top + 0.25 * atr[t]
                risk = sl - entry_ref
                if risk <= 0:
                    break
                height = top - neckline
                tp = neckline - height
                if tp >= entry_ref:
                    break
                if (entry_ref - tp) > MAX_R_CAP * risk:
                    tp = entry_ref - MAX_R_CAP * risk
                if (entry_ref - tp) < risk:
                    break
                out.append({"sig_idx": t, "side": "short", "sl": sl, "tp": tp})
                break

    # double bottom -> long
    for j in range(1, len(pl_idx)):
        p2 = pl_idx[j]; p1 = pl_idx[j - 1]
        sep = p2 - p1
        if sep < 3 or sep > 15:
            continue
        if np.isnan(atr[p2]):
            continue
        if abs(l[p2] - l[p1]) > 0.5 * atr[p2]:
            continue
        neckline = h[p1 + 1:p2].max() if p2 > p1 + 1 else max(h[p1], h[p2])
        bottom = min(l[p1], l[p2])
        start = p2 + PIVOT_K
        for t in range(start, min(start + 15, n)):
            if np.isnan(atr[t]):
                break
            if c[t] > neckline and c[t] > o[t]:
                entry_ref = c[t]
                sl = bottom - 0.25 * atr[t]
                risk = entry_ref - sl
                if risk <= 0:
                    break
                height = neckline - bottom
                tp = neckline + height
                if tp <= entry_ref:
                    break
                if (tp - entry_ref) > MAX_R_CAP * risk:
                    tp = entry_ref + MAX_R_CAP * risk
                if (tp - entry_ref) < risk:
                    break
                out.append({"sig_idx": t, "side": "long", "sl": sl, "tp": tp})
                break
    return out


def sig_A3_wyckoff(df: pd.DataFrame) -> list[dict]:
    """Spring (false break below range low + reclaim -> long); upthrust mirror -> short."""
    h, l, c, o = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    atr = df["atr14"].values
    n = len(df)
    rng_hi = pd.Series(h).shift(1).rolling(20, min_periods=20).max().values
    rng_lo = pd.Series(l).shift(1).rolling(20, min_periods=20).min().values
    out = []
    for t in range(21, n):
        if np.isnan(atr[t]) or np.isnan(rng_hi[t]):
            continue
        tightness = rng_hi[t] - rng_lo[t]
        if tightness > 4.0 * atr[t] or tightness <= 0:
            continue
        # spring -> long
        if l[t] < rng_lo[t] and c[t] > rng_lo[t] and c[t] > o[t]:
            entry_ref = c[t]
            sl = l[t] - 0.25 * atr[t]
            risk = entry_ref - sl
            tp = rng_hi[t]
            if risk > 0 and tp > entry_ref:
                if (tp - entry_ref) > MAX_R_CAP * risk:
                    tp = entry_ref + MAX_R_CAP * risk
                if (tp - entry_ref) >= risk:
                    out.append({"sig_idx": t, "side": "long", "sl": sl, "tp": tp})
        # upthrust -> short
        elif h[t] > rng_hi[t] and c[t] < rng_hi[t] and c[t] < o[t]:
            entry_ref = c[t]
            sl = h[t] + 0.25 * atr[t]
            risk = sl - entry_ref
            tp = rng_lo[t]
            if risk > 0 and tp < entry_ref:
                if (entry_ref - tp) > MAX_R_CAP * risk:
                    tp = entry_ref - MAX_R_CAP * risk
                if (entry_ref - tp) >= risk:
                    out.append({"sig_idx": t, "side": "short", "sl": sl, "tp": tp})
    return out


def sig_B1_ema20_pullback(df: pd.DataFrame) -> list[dict]:
    """IDENTICAL entry to F3 (sig_f3_ema20_pullback). Exit handled dynamically (dyn=True)."""
    out = []
    h, l, c, o = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    e20, e50, e200, atr = df["ema20"].values, df["ema50"].values, df["ema200"].values, df["atr14"].values
    for t in range(3, len(df)):
        if np.isnan(e200[t]) or np.isnan(atr[t]):
            continue
        band = 0.25 * atr[t]
        if e50[t] > e200[t]:
            touched = l[t] <= e20[t] + band and l[t] >= e20[t] - 3 * band
            pulled = c[t - 1] < c[t - 3]
            resume = c[t] > e20[t] and c[t] > o[t]
            if touched and pulled and resume:
                sw_lo = min(l[t - 2], l[t - 1], l[t])
                sl = sw_lo - 0.5 * atr[t]
                entry_ref = c[t]
                risk = entry_ref - sl
                if risk <= 0:
                    continue
                out.append({"sig_idx": t, "side": "long", "sl": sl, "tp": entry_ref + 2 * risk, "dyn": True})
        elif e50[t] < e200[t]:
            touched = h[t] >= e20[t] - band and h[t] <= e20[t] + 3 * band
            pulled = c[t - 1] > c[t - 3]
            resume = c[t] < e20[t] and c[t] < o[t]
            if touched and pulled and resume:
                sw_hi = max(h[t - 2], h[t - 1], h[t])
                sl = sw_hi + 0.5 * atr[t]
                entry_ref = c[t]
                risk = sl - entry_ref
                if risk <= 0:
                    continue
                out.append({"sig_idx": t, "side": "short", "sl": sl, "tp": entry_ref - 2 * risk, "dyn": True})
    return out


def sig_B2_atr_squeeze(df: pd.DataFrame) -> list[dict]:
    """Corrected gate: coil at t-1,t-2,t-3 (squeeze); breakout bar t expands. Dynamic exit."""
    out = []
    c = df["close"].values
    dhi, dlo = df["don20_hi"].values, df["don20_lo"].values
    atr, amed = df["atr14"].values, df["atr_med50"].values
    n = len(df)
    for t in range(4, n):
        if np.isnan(dhi[t]) or np.isnan(amed[t]) or amed[t] <= 0:
            continue
        # coil at t-1..t-3
        coil = True
        for k in (1, 2, 3):
            if np.isnan(amed[t - k]) or amed[t - k] <= 0 or atr[t - k] > 0.7 * amed[t - k]:
                coil = False
                break
        if not coil:
            continue
        if c[t] > dhi[t]:
            entry_ref = c[t]
            sl = dlo[t]
            risk = entry_ref - sl
            if risk <= 0:
                continue
            out.append({"sig_idx": t, "side": "long", "sl": sl, "tp": entry_ref + 2 * risk, "dyn": True})
        elif c[t] < dlo[t]:
            entry_ref = c[t]
            sl = dhi[t]
            risk = sl - entry_ref
            if risk <= 0:
                continue
            out.append({"sig_idx": t, "side": "short", "sl": sl, "tp": entry_ref - 2 * risk, "dyn": True})
    return out


# --------------------------------------------------------------------------- simulators
def _entry_setup(df, s, slippage_bps):
    """Common: compute entry fill, risk_dist, tp_dist off signal-bar close ref, re-anchored
    on real next-bar OPEN. Returns (ei, side, entry_fill, risk_dist, tp_dist, half_slip) or None."""
    o = df["open"].values
    c = df["close"].values
    ts = df["ts"]
    n = len(df)
    t = s["sig_idx"]
    ei = t + 1
    if ei >= n:
        return None
    ets = ts.iloc[ei]
    if not in_session(ets) or is_weekend_block(ets):
        return None
    side = s["side"]
    half_slip = (slippage_bps / 2.0) / 1e4
    entry_px = o[ei]
    entry_fill = entry_px * (1 + half_slip) if side == "long" else entry_px * (1 - half_slip)
    sig_ref = c[t]
    if side == "long":
        risk_dist = sig_ref - s["sl"]
        tp_dist = s["tp"] - sig_ref
    else:
        risk_dist = s["sl"] - sig_ref
        tp_dist = sig_ref - s["tp"]
    if risk_dist <= 0 or tp_dist <= 0:
        return None
    return ei, side, entry_fill, risk_dist, tp_dist, half_slip, ets


def simulate_fixed_tp(df, signals, slippage_bps) -> list[dict]:
    """Fixed SL/TP (structure target). next-bar OPEN, SL-first, cooldown, swap haircut."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    ts = df["ts"]
    n = len(df)
    out = []
    last_exit_idx = -10 ** 9
    for s in signals:
        setup = _entry_setup(df, s, slippage_bps)
        if setup is None:
            continue
        ei, side, entry_fill, risk_dist, tp_dist, half_slip, ets = setup
        if ei - last_exit_idx < COOLDOWN_BARS:
            continue
        if side == "long":
            sl_px = entry_fill - risk_dist
            tp_px = entry_fill + tp_dist
        else:
            sl_px = entry_fill + risk_dist
            tp_px = entry_fill - tp_dist
        exit_idx = exit_px = None
        for j in range(ei, n):
            if j > ei and is_weekend_block(ts.iloc[j]):
                exit_idx, exit_px = j, df["open"].values[j]
                break
            if side == "long":
                hit_sl, hit_tp = l[j] <= sl_px, h[j] >= tp_px
            else:
                hit_sl, hit_tp = h[j] >= sl_px, l[j] <= tp_px
            if hit_sl:
                exit_idx, exit_px = j, sl_px
                break
            if hit_tp:
                exit_idx, exit_px = j, tp_px
                break
        if exit_idx is None:
            exit_idx, exit_px = n - 1, c[n - 1]
        out.append(_finalize(side, entry_fill, exit_px, risk_dist, half_slip, ets, ts.iloc[exit_idx]))
        last_exit_idx = exit_idx
    return out


def simulate_dynamic(df, signals, slippage_bps) -> list[dict]:
    """Dynamic exit: initial SL -> BE@+1R -> trail prior-bar swing +-0.5*ATR (runner, no TP).
    Lookahead-free: BE/trail decisions use only completed bars; intrabar SL-first; the BE
    trigger is checked on bars AFTER the bar that first reached +1R (no same-bar peek)."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["atr14"].values
    ts = df["ts"]
    n = len(df)
    out = []
    last_exit_idx = -10 ** 9
    for s in signals:
        setup = _entry_setup(df, s, slippage_bps)
        if setup is None:
            continue
        ei, side, entry_fill, risk_dist, tp_dist, half_slip, ets = setup
        if ei - last_exit_idx < COOLDOWN_BARS:
            continue
        if side == "long":
            sl_px = entry_fill - risk_dist
        else:
            sl_px = entry_fill + risk_dist
        be_done = False
        exit_idx = exit_px = None
        for j in range(ei, n):
            if j > ei and is_weekend_block(ts.iloc[j]):
                exit_idx, exit_px = j, df["open"].values[j]
                break
            # 1) intrabar SL check FIRST (conservative)
            if side == "long":
                if l[j] <= sl_px:
                    exit_idx, exit_px = j, sl_px
                    break
            else:
                if h[j] >= sl_px:
                    exit_idx, exit_px = j, sl_px
                    break
            # 2) BE@+1R: if this bar's extreme reached +1R, move SL to entry (from NEXT bar)
            if not be_done:
                if side == "long" and h[j] >= entry_fill + risk_dist:
                    sl_px = max(sl_px, entry_fill)
                    be_done = True
                elif side == "short" and l[j] <= entry_fill - risk_dist:
                    sl_px = min(sl_px, entry_fill)
                    be_done = True
            # 3) trail under/over prior completed bar by 0.5*ATR (only after BE armed)
            if be_done and not np.isnan(atr[j]):
                if side == "long":
                    cand = l[j] - 0.5 * atr[j]
                    if cand > sl_px:
                        sl_px = cand
                else:
                    cand = h[j] + 0.5 * atr[j]
                    if cand < sl_px:
                        sl_px = cand
        if exit_idx is None:
            exit_idx, exit_px = n - 1, c[n - 1]
        out.append(_finalize(side, entry_fill, exit_px, risk_dist, half_slip, ets, ts.iloc[exit_idx]))
        last_exit_idx = exit_idx
    return out


def _finalize(side, entry_fill, exit_px, risk_dist, half_slip, ets, ets_x) -> dict:
    if side == "long":
        exit_fill = exit_px * (1 - half_slip)
        gross_R = (exit_fill - entry_fill) / risk_dist
    else:
        exit_fill = exit_px * (1 + half_slip)
        gross_R = (entry_fill - exit_fill) / risk_dist
    nh = nights_held(ets, ets_x)
    sl_bps = (risk_dist / entry_fill) * 1e4 if entry_fill > 0 else 0.0
    swap_R = (nh * SWAP_BPS_PER_NIGHT) / sl_bps if sl_bps > 0 else 0.0
    return {"entry_ts": ets, "exit_ts": ets_x, "side": side,
            "R": gross_R - swap_R, "gross_R": gross_R, "swap_R": swap_R, "nights": nh}


# --------------------------------------------------------------------------- stats
def r_stats(trades) -> dict:
    if not trades:
        return {"n": 0, "mR": 0.0, "gross_mR": 0.0, "sumR": 0.0, "wr": 0.0, "pf": 0.0}
    Rs = [t["R"] for t in trades]
    g = [t["gross_R"] for t in trades]
    wins = [r for r in Rs if r > 0]
    losses = [r for r in Rs if r < 0]
    gl = abs(sum(losses))
    return {"n": len(Rs), "mR": mean(Rs), "gross_mR": mean(g), "sumR": sum(Rs),
            "wr": len(wins) / len(Rs) * 100, "pf": (sum(wins) / gl) if gl > 0 else float("inf")}


def shuffle_pvalue(trades, n_iter: int = 5000):
    Rs = np.array([t["R"] for t in trades], dtype=float)
    if len(Rs) == 0:
        return 0.0, 1.0
    obs = float(Rs.mean())
    abs_R = np.abs(Rs)
    cnt = 0
    for _ in range(n_iter):
        signs = rng.choice([-1.0, 1.0], size=len(Rs))
        if (abs_R * signs).mean() >= obs:
            cnt += 1
    return obs, (cnt + 1) / (n_iter + 1)


def monthly_R_series(trades, idx) -> pd.Series:
    s = pd.Series(0.0, index=idx)
    for t in trades:
        key = pd.Timestamp(t["entry_ts"]).to_period("M").to_timestamp().tz_localize("UTC")
        if key in s.index:
            s[key] += t["R"]
    return s


# --------------------------------------------------------------------------- brooks (correlation ref)
def brooks_trades(df_full) -> list[dict]:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.brooks_failed_breakout import _default_manifest, BrooksFailedBreakoutStrategy
    m = _default_manifest()
    m.signals.filters.atr_min_pct = 0.0008
    strat = BrooksFailedBreakoutStrategy(m)

    def prov(*a, **k):
        d = df_full.copy()
        d["symbol"] = SYMBOL; d["venue"] = "forex"; d["timeframe"] = TF; d["volume"] = 0.0
        return d

    e = BacktestEngine(risk_officer=None, store_load=None)
    r = e.run(strat, [SYMBOL], start=df_full["ts"].iloc[0].to_pydatetime(),
              end=df_full["ts"].iloc[-1].to_pydatetime(), timeframe=TF,
              initial_capital=10_000.0, fees={"taker": 0.0, "maker": 0.0},
              slippage_bps=SLIPPAGE_BPS, ohlcv_provider=prov)
    out = []
    if r.trades is None or r.trades.empty:
        return out
    for _, t in r.trades.iterrows():
        ts_e = pd.Timestamp(t["entry_ts"])
        ts_e = ts_e.tz_localize("UTC") if ts_e.tzinfo is None else ts_e.tz_convert("UTC")
        if not in_session(ts_e) or is_weekend_block(ts_e):
            continue
        out.append({"entry_ts": ts_e, "R": float(t["realized_r_multiple"])})
    return out


# --------------------------------------------------------------------------- regimes
def regime_label(df) -> pd.Series:
    ema = df["close"].ewm(span=200, adjust=False).mean()
    slope = ema.diff(50)
    atrp = ((df["high"] - df["low"]).rolling(14).mean() / df["close"])
    out = pd.Series("range", index=df.index)
    out[slope > atrp * 2] = "trend_up"
    out[slope < -atrp * 2] = "trend_down"
    return out


# --------------------------------------------------------------------------- main
# (family, detector, exit_engine, has_twin)  exit_engine: "fixed" or "dynamic"
FAMILIES = [
    ("A1_failed_swing", sig_A1_failed_swing, "fixed", True),
    ("A2_double_top_bot", sig_A2_double_top_bottom, "fixed", True),
    ("A3_wyckoff", sig_A3_wyckoff, "fixed", True),
    ("B1_ema20pull_dyn", sig_B1_ema20_pullback, "dynamic", True),
    ("B2_squeeze_dyn", sig_B2_atr_squeeze, "dynamic", True),
]


def run_family(df, fn, engine, slippage):
    sigs = fn(df)
    if engine == "fixed":
        return simulate_fixed_tp(df, sigs, slippage), sigs
    return simulate_dynamic(df, sigs, slippage), sigs


def split(trades):
    is_tr = [t for t in trades if IS_START <= t["entry_ts"] < IS_END]
    oos_tr = [t for t in trades if OOS_START <= t["entry_ts"] < OOS_END]
    return is_tr, oos_tr


def main() -> None:
    df = add_indicators(load_ohlcv())
    dhash = data_hash(df)
    git_hash = os.popen("git -C %s rev-parse --short HEAD" % ROOT).read().strip()
    print("=" * 92)
    print("BROOKS TRAP-FAMILY (A1/A2/A3) + DYNAMIC-EXIT RE-TESTS (B1/B2) — EUR/USD 4H honest cost")
    print("=" * 92)
    print(f"git={git_hash}  data_hash={dhash}  seed={SEED}  n_bars={len(df)}")
    print(f"cost: fee=0 slip={SLIPPAGE_BPS}bps swap={SWAP_BPS_PER_NIGHT}bps/night(Wed3x) "
          f"session{SESSION_START_H}-{SESSION_END_H}UTC weekend-flat cooldown{COOLDOWN_BARS}bars pivotK={PIVOT_K}")
    print(f"IS=[{IS_START.date()},{IS_END.date()})  OOS=[{OOS_START.date()},{OOS_END.date()})\n")

    midx = pd.period_range(IS_START, OOS_END, freq="M").to_timestamp().tz_localize("UTC")
    all_full = {}
    rows = {}
    print(f"{'family':<20} {'scope':<4} {'n':>4} {'net_mR':>8} {'gross_mR':>9} {'win%':>6} {'PF':>6} {'sumR':>8}")
    print("-" * 92)
    for name, fn, engine, _ in FAMILIES:
        full, _sigs = run_family(df, fn, engine, SLIPPAGE_BPS)
        all_full[name] = full
        is_tr, oos_tr = split(full)
        st_is, st_oos = r_stats(is_tr), r_stats(oos_tr)
        rows[name] = {"is": st_is, "oos": st_oos}
        for scope, st in (("IS", st_is), ("OOS", st_oos)):
            pf = st["pf"]; pfs = f"{pf:.2f}" if math.isfinite(pf) else "inf"
            print(f"{name:<20} {scope:<4} {st['n']:>4} {st['mR']:>+8.3f} {st['gross_mR']:>+9.3f} "
                  f"{st['wr']:>5.1f}% {pfs:>6} {st['sumR']:>+8.1f}")
    print("-" * 92)

    # TWIN comparison: B1/B2 dynamic vs their fixed-2R twin; A* structure-target vs 2R twin
    print("\nEXIT-THESIS CORROBORATION (this engine vs fixed-2R twin on SAME entries, full net mR):")
    twin_2r = {}
    for name, fn, engine, _ in FAMILIES:
        sigs = fn(df)
        # fixed-2R twin: override tp to 2R from sig ref
        twin_sigs = []
        for s in sigs:
            twin_sigs.append({**s, "tp": None})  # placeholder; recompute below in sim by 2R
        # build explicit 2R targets
        c = df["close"].values
        sig2r = []
        for s in sigs:
            t = s["sig_idx"]
            ref = c[t]
            if s["side"] == "long":
                risk = ref - s["sl"]
                tp = ref + 2 * risk
            else:
                risk = s["sl"] - ref
                tp = ref - 2 * risk
            if risk <= 0:
                continue
            sig2r.append({**s, "tp": tp})
        twin = simulate_fixed_tp(df, sig2r, SLIPPAGE_BPS)
        twin_2r[name] = twin
        st_main = r_stats(all_full[name])
        st_twin = r_stats(twin)
        beat = "BEATS 2R" if st_main["mR"] > st_twin["mR"] else "<= 2R (thesis falsified)"
        print(f"  {name:<20} this_mR={st_main['mR']:+.3f} (n{st_main['n']})  "
              f"2R_twin_mR={st_twin['mR']:+.3f} (n{st_twin['n']})  -> {beat}")

    print("\nSANITY (net mR <= gross mR):")
    for name in all_full:
        st = rows[name]["is"]
        ok = st["mR"] <= st["gross_mR"] + 1e-9
        print(f"  {name:<20} net {st['mR']:+.3f} <= gross {st['gross_mR']:+.3f} -> {'OK' if ok else 'BROKEN'}")

    print("\nSHUFFLE NULL (5000 iters, full period):")
    shuf = {}
    for name in all_full:
        obs, p = shuffle_pvalue(all_full[name])
        shuf[name] = p
        print(f"  {name:<20} obs_mR={obs:+.3f} p={p:.4f} n={len(all_full[name])}")
    pvals = sorted(shuf.items(), key=lambda x: x[1])
    m = len(pvals)
    print("\nBH-FDR (alpha=0.05) over 5 families:")
    bh = {}
    for i, (k, p) in enumerate(pvals, 1):
        thr = i / m * 0.05
        bh[k] = p <= thr
        print(f"  rank {i}: {k:<20} p={p:.4f} thr={thr:.4f} {'PASS' if bh[k] else 'fail'}")

    print("\nSLIPPAGE STRESS (1.0->1.7bps, full net mR):")
    for name, fn, engine, _ in FAMILIES:
        stress, _ = run_family(df, fn, engine, SLIPPAGE_BPS_STRESS)
        base = r_stats(all_full[name]); st = r_stats(stress)
        print(f"  {name:<20} base_mR={base['mR']:+.3f} stress_mR={st['mR']:+.3f} n={st['n']}")

    print("\nREGIME SPLIT (full-period net mR by regime at entry):")
    reg = regime_label(df)
    ts_to_reg = dict(zip(df["ts"], reg))
    for name in all_full:
        by = {}
        for t in all_full[name]:
            rgl = ts_to_reg.get(t["entry_ts"], "range")
            by.setdefault(rgl, []).append(t["R"])
        pos = 0; line = []
        for rgl in ("range", "trend_up", "trend_down"):
            rs = by.get(rgl, [])
            if rs:
                mr = mean(rs); pos += 1 if mr > 0 else 0
                line.append(f"{rgl}={mr:+.3f}(n{len(rs)})")
            else:
                line.append(f"{rgl}=na")
        print(f"  {name:<20} {'  '.join(line)}  pos_regimes={pos}")

    # correlation vs brooks
    print("\nCORRELATION vs brooks_failed_breakout (monthly R P&L, full period):")
    bk = brooks_trades(df)
    bk_m = monthly_R_series(bk, midx)
    print(f"  (brooks n={len(bk)} trades, monthly sumR={bk_m.sum():+.1f})")
    corr_out = {}
    for name in all_full:
        fam_m = monthly_R_series(all_full[name], midx)
        active = (fam_m != 0) | (bk_m != 0)
        if active.sum() < 4 or fam_m[active].std() == 0 or bk_m[active].std() == 0:
            corr = float("nan")
        else:
            corr = float(np.corrcoef(fam_m[active], bk_m[active])[0, 1])
        fam_months = {pd.Timestamp(t["entry_ts"]).to_period("M") for t in all_full[name]}
        bk_months = {pd.Timestamp(t["entry_ts"]).to_period("M") for t in bk}
        ov = len(fam_months & bk_months) / max(1, len(fam_months | bk_months))
        corr_out[name] = corr
        print(f"  {name:<20} monthly_R_corr={corr:+.3f}  month_overlap={ov*100:.0f}%")

    # verdicts
    print("\n" + "=" * 92)
    print("VERDICT (pre-reg: n_IS<30&mR>0 ITERATE-underpowered; IS mR<=0 KILL; 0<mR<0.10 ITERATE;")
    print("         mR>=0.10 & OOS>0 & p<0.05 & BH GO else ITERATE)")
    print("=" * 92)
    verdicts = {}
    for name in all_full:
        is_mR = rows[name]["is"]["mR"]; oos_mR = rows[name]["oos"]["mR"]
        n_is = rows[name]["is"]["n"]; p = shuf[name]; bhp = bh[name]
        if n_is < 30 and is_mR > 0:
            v = f"ITERATE (underpowered n_IS={n_is}<30)"
        elif is_mR <= 0:
            v = "KILL (IS net mR<=0)"
        elif is_mR < 0.10:
            v = "ITERATE (IS mR>0 but <+0.10)"
        elif p >= 0.05 or not bhp:
            v = "ITERATE (mR>=0.10 but shuffle/BH fail)"
        elif oos_mR <= 0:
            v = "ITERATE (IS edge but OOS<=0)"
        else:
            v = "GO (IS>=0.10, OOS>0, p<0.05, BH pass)"
        verdicts[name] = v
        print(f"  {name:<20} IS_mR={is_mR:+.3f} OOS_mR={oos_mR:+.3f} n_IS={n_is} p={p:.3f} "
              f"BH={'Y' if bhp else 'N'} corr_brooks={corr_out.get(name, float('nan')):+.3f} -> {v}")


if __name__ == "__main__":
    main()
