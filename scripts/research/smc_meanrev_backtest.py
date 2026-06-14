#!/usr/bin/env python3
# ruff: noqa: E741,N803,N802,N806,E702,SIM102,B007,F841
"""
SMC MEAN-REVERSION backtest harness — standalone, lookahead-safe.

Structurally DIFFERENT from the SFP reversal family (smc_sfp_backtest.py).
Two range / mean-reversion concepts from the SMC course, codifiable on bar-OHLCV:

(a) RANGE-DEVIATION -> MID  ("box sweep + close-back-inside, fade to mid"):
    Detect a consolidation BOX over the prior N bars (rolling high/low) whose ATR is
    LOW relative to a longer baseline (range, not trend). When the current bar's WICK
    pierces the box boundary (liquidity sweep) but the bar CLOSES back INSIDE the box,
    enter toward the range MIDLINE (0.5) or the OPPOSITE boundary (1.0).
      long  : low[t]  < box_lo  AND  close[t] > box_lo   (swept the bottom, held)
      short : high[t] > box_hi  AND  close[t] < box_hi   (swept the top, held)
    SL: beyond the deviation wick (max of structural buffer, k*ATR -> honest floor).
    TP: range mid (0.5) or opposite boundary (1.0).

(b) CAMARILLA PIVOT FADE:
    Compute daily Camarilla levels from the PRIOR COMPLETED UTC day's OHLC.
      H3 = C + (H-L)*1.1/4 ;  L3 = C - (H-L)*1.1/4   (reversal band)
      H4 = C + (H-L)*1.1/2 ;  L4 = C - (H-L)*1.1/2   (breakout band)
      PP = (H+L+C)/3                                  (central pivot)
    Fade H3 (short) / L3 (long): a bar that touches H3/L3 but closes back toward the
    pivot. SL beyond H4/L4 (floored by k*ATR). TP = PP (central) or the level itself.

LOOKAHEAD DISCIPLINE (paranoid):
  - Decision on bar t uses only data <= t-1 for the BOX (box = rolling stats ending t-1).
    The trigger uses bar t's own OHLC (the bar that completes -> close known at t's close);
    entry fills at close[t]. NO df.shift(-1), NO center=True.
  - Camarilla levels for any bar in UTC-day D come ONLY from day D-1's completed OHLC.
  - First-touch exit scans (t+1 .. t+max_hold); same-bar SL+TP tie -> SL wins (conservative).

FEES: 55bps round-trip (also reports 0bps gross). Honest min-stop floored at k*ATR;
fee_R reported (median) so we can see fee death.

Robustness: shuffle baseline (p_gross = honest fee-independent direction edge),
walk-forward monthly OOS positive-month fraction, per-symbol breakdown.

CLI:
  python smc_meanrev_backtest.py --concept range --tf 15m --tp mid
  python smc_meanrev_backtest.py --concept cam   --tf 1h  --tp central
  python smc_meanrev_backtest.py --all           # full matrix -> report numbers
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

UNIVERSE = [
    "BTC", "ETH", "SOL", "BNB", "ADA", "AVAX", "LINK", "DOT",
    "DOGE", "XRP", "ZEC", "NEAR", "FIL", "XLM", "TRX",
]

FEE_RT_BPS = 55.0  # round-trip fees+slippage in basis points


# --------------------------------------------------------------------------- #
# Data loading (copied from smc_sfp_backtest.py — same DB schema/contract)
# --------------------------------------------------------------------------- #
def _git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return "nogit"


def load_ohlcv(symbol: str, tf: str) -> pd.DataFrame | None:
    """Load one symbol/timeframe as naive-UTC indexed OHLCV. Returns None if absent."""
    sym = f"{symbol}/USDT"
    if tf not in ("15m", "1h"):
        raise ValueError(f"unsupported tf {tf}")
    con = duckdb.connect(str(DB), read_only=True)
    try:
        vrows = con.execute(
            "SELECT venue, count(*) n FROM ohlcv WHERE symbol=? AND timeframe=? "
            "GROUP BY venue ORDER BY n DESC LIMIT 1",
            [sym, tf],
        ).fetchall()
        if not vrows:
            return None
        venue = vrows[0][0]
        df = con.execute(
            "SELECT (ts AT TIME ZONE 'UTC') AS ts, open, high, low, close, volume "
            "FROM ohlcv WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts",
            [venue, sym, tf],
        ).fetch_df()
    finally:
        con.close()
    if df.empty:
        return None
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df[["open", "high", "low", "close", "volume"]]


def _atr(df, period):
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(period, min_periods=1).mean().values


# --------------------------------------------------------------------------- #
# Params
# --------------------------------------------------------------------------- #
@dataclass
class Params:
    concept: str = "range"          # range | cam
    # --- range (a) ---
    box_lookback: int = 20          # N bars forming the box (ending t-1)
    atr_expansion_max: float = 1.2  # box_atr <= atr_expansion_max * baseline_atr (range filter)
    baseline_lookback: int = 60     # baseline ATR window for the range filter
    wick_min_atr: float = 0.10      # deviation wick must pierce >= this*ATR beyond boundary
    tp: str = "mid"                 # mid (0.5) | opposite (1.0)  [range]; central | level [cam]
    # --- camarilla (b) ---
    cam_touch_atr: float = 0.05     # bar must reach within this*ATR of H3/L3 (or pierce)
    # --- shared ---
    sl_floor_k: float = 0.50        # SL floor = max(structural, k*ATR)  <-- honest min stop
    sl_struct_atr: float = 0.10     # structural buffer beyond the wick/level (in ATR)
    max_hold: int = 32
    atr_period: int = 14


# --------------------------------------------------------------------------- #
# Concept (a): range-deviation -> mid
# --------------------------------------------------------------------------- #
def _candidates_range(df: pd.DataFrame, p: Params):
    """Causal box: for bar t the box = rolling [t-N .. t-1] high/low. Trigger uses bar t's
    own wick + close. Returns arrays of candidate entries (direction-independent levels)."""
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(df)
    atr = _atr(df, p.atr_period)

    # box over [t-N .. t-1]: shift(1) so bar t never sees its own value in the box
    box_hi = pd.Series(h).rolling(p.box_lookback).max().shift(1).values
    box_lo = pd.Series(l).rolling(p.box_lookback).min().shift(1).values
    # range filter: box height vs baseline ATR (compactness => consolidation, not trend)
    box_height = box_hi - box_lo
    base_atr = pd.Series(atr).shift(1).rolling(p.baseline_lookback).mean().shift(1).values
    # "low ATR-expansion": box height small relative to (baseline_lookback * baseline_atr).
    # We require the box to be a CONSOLIDATION: height <= atr_expansion_max * (N-bar typical move).
    # typical N-bar move proxy = base_atr * sqrt(N) (random-walk scaling).
    typ_move = base_atr * np.sqrt(p.box_lookback)

    e_idx, ent, tip, base_dir, atr_l, bhi, blo = [], [], [], [], [], [], []
    start = max(p.box_lookback + 1, p.baseline_lookback + 2, p.atr_period + 1)
    for t in range(start, n):
        bh, bl = box_hi[t], box_lo[t]
        if not (np.isfinite(bh) and np.isfinite(bl)) or bh <= bl:
            continue
        a = atr[t - 1] if atr[t - 1] > 0 else (c[t - 1] * 0.005)  # ATR known by t-1
        # range filter: only fade inside a genuine consolidation
        if np.isfinite(typ_move[t]) and box_height[t] > p.atr_expansion_max * typ_move[t]:
            continue
        # bullish deviation: swept box bottom, closed back inside
        pierce_lo = bl - l[t]
        if l[t] < bl and c[t] > bl and pierce_lo >= p.wick_min_atr * a:
            e_idx.append(t); ent.append(c[t]); tip.append(l[t]); base_dir.append(1)
            atr_l.append(a); bhi.append(bh); blo.append(bl)
        # bearish deviation: swept box top, closed back inside
        pierce_hi = h[t] - bh
        if h[t] > bh and c[t] < bh and pierce_hi >= p.wick_min_atr * a:
            e_idx.append(t); ent.append(c[t]); tip.append(h[t]); base_dir.append(-1)
            atr_l.append(a); bhi.append(bh); blo.append(bl)

    return dict(
        e_idx=np.array(e_idx, int), ent=np.array(ent, float), tip=np.array(tip, float),
        base_dir=np.array(base_dir, np.int8), atr=np.array(atr_l, float),
        box_hi=np.array(bhi, float), box_lo=np.array(blo, float),
    )


# --------------------------------------------------------------------------- #
# Concept (b): Camarilla pivot fade
# --------------------------------------------------------------------------- #
def _camarilla_levels(df: pd.DataFrame):
    """Per-bar Camarilla levels from the PRIOR COMPLETED UTC day. No same-day leakage."""
    idx = df.index
    day = idx.floor("D")
    daily = df.groupby(day).agg(H=("high", "max"), L=("low", "min"), C=("close", "last"))
    rng = daily["H"] - daily["L"]
    cam = pd.DataFrame(index=daily.index)
    cam["PP"] = (daily["H"] + daily["L"] + daily["C"]) / 3.0
    cam["H3"] = daily["C"] + rng * 1.1 / 4.0
    cam["L3"] = daily["C"] - rng * 1.1 / 4.0
    cam["H4"] = daily["C"] + rng * 1.1 / 2.0
    cam["L4"] = daily["C"] - rng * 1.1 / 2.0
    # shift by one day so a bar in day D uses day D-1's levels
    cam = cam.shift(1)
    # map each bar to its day's (already prior-day-derived) levels
    per_bar = cam.reindex(day).set_index(idx)
    return per_bar


def _candidates_cam(df: pd.DataFrame, p: Params):
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(df)
    atr = _atr(df, p.atr_period)
    cam = _camarilla_levels(df)
    PP = cam["PP"].values; H3 = cam["H3"].values; L3 = cam["L3"].values
    H4 = cam["H4"].values; L4 = cam["L4"].values

    e_idx, ent, tip, base_dir, atr_l, tp_lvl, sl_lvl = [], [], [], [], [], [], []
    start = p.atr_period + 1
    for t in range(start, n):
        if not np.isfinite(PP[t]):
            continue
        a = atr[t - 1] if atr[t - 1] > 0 else (c[t - 1] * 0.005)
        # fade L3 long: bar reaches L3 (touch/pierce) but closes back above L3 (toward PP)
        if (l[t] <= L3[t] + p.cam_touch_atr * a) and c[t] > L3[t]:
            e_idx.append(t); ent.append(c[t]); tip.append(l[t]); base_dir.append(1)
            atr_l.append(a); tp_lvl.append(PP[t]); sl_lvl.append(L4[t])
        # fade H3 short: bar reaches H3 but closes back below H3
        elif (h[t] >= H3[t] - p.cam_touch_atr * a) and c[t] < H3[t]:
            e_idx.append(t); ent.append(c[t]); tip.append(h[t]); base_dir.append(-1)
            atr_l.append(a); tp_lvl.append(PP[t]); sl_lvl.append(H4[t])

    return dict(
        e_idx=np.array(e_idx, int), ent=np.array(ent, float), tip=np.array(tip, float),
        base_dir=np.array(base_dir, np.int8), atr=np.array(atr_l, float),
        tp_lvl=np.array(tp_lvl, float), sl_lvl=np.array(sl_lvl, float),
    )


_CAND_CACHE: dict = {}


def _df_fp(df: pd.DataFrame):
    return (id(df), len(df), int(df.index[0].value), int(df.index[-1].value),
            float(df["close"].iloc[-1]))


def build_candidates(df: pd.DataFrame, p: Params):
    key = (_df_fp(df), p.concept, p.box_lookback, p.atr_expansion_max, p.baseline_lookback,
           round(p.wick_min_atr, 4), round(p.cam_touch_atr, 4), p.atr_period)
    if key in _CAND_CACHE:
        return _CAND_CACHE[key]
    cand = _candidates_range(df, p) if p.concept == "range" else _candidates_cam(df, p)
    if len(_CAND_CACHE) > 200:
        _CAND_CACHE.clear()
    _CAND_CACHE[key] = cand
    return cand


# --------------------------------------------------------------------------- #
# Backtest (vectorized first-touch exit)
# --------------------------------------------------------------------------- #
def backtest_symbol(df: pd.DataFrame, p: Params, randomize_dir: np.random.Generator | None = None):
    if df is None or len(df) < (p.baseline_lookback + p.atr_period + 60):
        return []
    h = df["high"].values; l = df["low"].values; c = df["close"].values
    n = len(df)

    cand = build_candidates(df, p)
    e_idx_a = cand["e_idx"]
    if e_idx_a.size == 0:
        return []
    ent_a = cand["ent"]; tip_a = cand["tip"]; atr_a = cand["atr"]

    if randomize_dir is not None:
        dir_a = np.where(randomize_dir.random(len(e_idx_a)) < 0.5, 1, -1).astype(np.int8)
    else:
        dir_a = cand["base_dir"]

    # ---- SL: beyond the deviation wick/level, FLOORED at k*ATR (honest min stop) ----
    # structural distance from entry to (wick + struct buffer)
    struct_sl = np.where(
        dir_a == 1,
        tip_a - p.sl_struct_atr * atr_a,          # long SL below the wick
        tip_a + p.sl_struct_atr * atr_a,          # short SL above the wick
    )
    struct_risk = np.where(dir_a == 1, ent_a - struct_sl, struct_sl - ent_a)
    floor_risk = p.sl_floor_k * atr_a              # honest ATR floor
    risk_a = np.maximum(struct_risk, floor_risk)
    sl_a = np.where(dir_a == 1, ent_a - risk_a, ent_a + risk_a)
    valid = risk_a > 0
    risk_safe = np.where(valid, risk_a, np.nan)

    # ---- TP ----
    if p.concept == "range":
        box_hi = cand["box_hi"]; box_lo = cand["box_lo"]
        mid = (box_hi + box_lo) / 2.0
        if p.tp == "mid":
            tp_a = mid
        else:  # opposite boundary
            tp_a = np.where(dir_a == 1, box_hi, box_lo)
        # if shuffled direction points the "wrong" way relative to the static box target,
        # the target may be on the wrong side of entry -> fall back to symmetric R-multiple
        wrong = np.where(dir_a == 1, tp_a <= ent_a, tp_a >= ent_a)
        tp_a = np.where(wrong, ent_a + dir_a * risk_a, tp_a)  # 1R fallback (rare)
    else:  # cam
        tp_lvl = cand["tp_lvl"]
        if p.tp == "central":
            tp_a = tp_lvl  # PP
        else:  # level: 1R-ish target = halfway, fall through to PP anyway
            tp_a = tp_lvl
        wrong = np.where(dir_a == 1, tp_a <= ent_a, tp_a >= ent_a)
        tp_a = np.where(wrong, ent_a + dir_a * risk_a, tp_a)

    # ---- vectorized first-touch exit over [e+1, e+max_hold] ----
    H = p.max_hold
    offs = e_idx_a[:, None] + 1 + np.arange(H)[None, :]
    in_range = offs < n
    offs_clip = np.clip(offs, 0, n - 1)
    hh = np.where(in_range, h[offs_clip], np.nan)
    ll = np.where(in_range, l[offs_clip], np.nan)
    cc = c[offs_clip]

    long = dir_a == 1
    sl_hit = np.where(long[:, None], ll <= sl_a[:, None], hh >= sl_a[:, None]) & in_range
    tp_hit = np.where(long[:, None], hh >= tp_a[:, None], ll <= tp_a[:, None]) & in_range

    def first_idx(mat):
        any_t = mat.any(axis=1)
        return np.where(any_t, mat.argmax(axis=1), H), any_t

    sl_first, _ = first_idx(sl_hit)
    tp_first, _ = first_idx(tp_hit)
    sl_step = np.where(sl_hit.any(axis=1), sl_first, H + 1)
    tp_step = np.where(tp_hit.any(axis=1), tp_first, H + 1)

    T = len(e_idx_a)
    has_sl = sl_step <= H
    has_tp = tp_step <= H
    timed = (~has_sl) & (~has_tp)
    sl_wins = has_sl & (sl_step <= tp_step)   # same-bar tie -> SL (conservative)
    tp_wins = has_tp & (~sl_wins)

    exit_step = np.where(sl_wins, sl_step, np.where(tp_wins, tp_step, 0))
    last_step = np.where(in_range.any(axis=1),
                         in_range.shape[1] - 1 - in_range[:, ::-1].argmax(axis=1), 0)
    exit_step = np.where(timed, last_step, exit_step)

    tp_R = np.abs(tp_a - ent_a) / risk_safe
    cc_at = cc[np.arange(T), exit_step]
    timed_R = np.where(dir_a == 1, (cc_at - ent_a), (ent_a - cc_at)) / risk_safe
    R_gross = np.where(sl_wins, -1.0, np.where(tp_wins, tp_R, timed_R))

    fee_frac = FEE_RT_BPS / 10000.0
    fee_R_a = fee_frac / (risk_safe / ent_a)       # round-trip fee expressed in R
    R_net = R_gross - fee_R_a
    exit_bar = np.clip(e_idx_a + 1 + exit_step, 0, n - 1)

    ts = df.index
    v = valid
    eb = exit_bar[v]; eidx = e_idx_a[v]; dv = dir_a[v]
    rg = R_gross[v]; rn = R_net[v]; fr = fee_R_a[v]
    entry_ts = ts[eidx]; exit_ts = ts[eb]
    return [
        {"entry_ts": entry_ts[k], "exit_ts": exit_ts[k], "dir": int(dv[k]),
         "R_gross": float(rg[k]), "R_net": float(rn[k]), "fee_R": float(fr[k])}
        for k in range(len(eidx))
    ]


# --------------------------------------------------------------------------- #
# Metrics (copied contract from smc_sfp_backtest.py)
# --------------------------------------------------------------------------- #
def calendar_day_sharpe(trades, r_key="R_net"):
    if not trades:
        return 0.0
    d = pd.DataFrame(trades)
    d["day"] = pd.to_datetime(d["exit_ts"]).dt.floor("D")
    daily = d.groupby("day")[r_key].sum()
    if len(daily) < 2 or daily.std(ddof=1) == 0:
        return 0.0
    return float(daily.mean() / daily.std(ddof=1))


def max_drawdown_R(trades, r_key="R_net"):
    if not trades:
        return 0.0
    eq = np.cumsum([t[r_key] for t in sorted(trades, key=lambda x: x["exit_ts"])])
    peak = np.maximum.accumulate(eq)
    return float((eq - peak).min())


def summarize(trades):
    if not trades:
        return dict(n=0, mean_R_0=0.0, mean_R_55=0.0, win=0.0, sharpe=0.0,
                    mdd=0.0, total_R=0.0, fee_R_med=0.0)
    rg = np.array([t["R_gross"] for t in trades])
    rn = np.array([t["R_net"] for t in trades])
    fr = np.array([t["fee_R"] for t in trades])
    return dict(
        n=len(trades), mean_R_0=float(rg.mean()), mean_R_55=float(rn.mean()),
        win=float((rn > 0).mean() * 100), sharpe=calendar_day_sharpe(trades),
        mdd=max_drawdown_R(trades), total_R=float(rn.sum()), fee_R_med=float(np.median(fr)),
    )


# --------------------------------------------------------------------------- #
# Robustness
# --------------------------------------------------------------------------- #
def shuffle_pvalue(uni: dict, p: Params, n_seeds=50):
    real = []
    for sym, df in uni.items():
        real += backtest_symbol(df, p)
    real_net = summarize(real)["mean_R_55"]
    real_gross = float(np.mean([t["R_gross"] for t in real])) if real else 0.0
    sn, sg = [], []
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        st = []
        for sym, df in uni.items():
            st += backtest_symbol(df, p, randomize_dir=rng)
        if st:
            sn.append(np.mean([t["R_net"] for t in st]))
            sg.append(np.mean([t["R_gross"] for t in st]))
    sn = np.array(sn); sg = np.array(sg)
    if len(sn) == 0:
        return dict(real_net=real_net, real_gross=real_gross, p_net=1.0, p_gross=1.0)
    return dict(
        real_net=real_net, real_gross=real_gross,
        p_net=float((sn >= real_net).mean()),
        p_gross=float((sg >= real_gross).mean()),
        shuf_gross_mean=float(sg.mean()), shuf_net_mean=float(sn.mean()),
    )


def walk_forward_months(uni: dict, p: Params):
    all_tr = []
    for sym, df in uni.items():
        all_tr += backtest_symbol(df, p)
    if not all_tr:
        return dict(months=0, pos=0, frac=0.0, monthly_meanR=0.0)
    d = pd.DataFrame(all_tr)
    d["month"] = pd.to_datetime(d["exit_ts"]).dt.to_period("M")
    by = d.groupby("month")["R_net"].sum()
    return dict(months=len(by), pos=int((by > 0).sum()), frac=float((by > 0).mean()),
                monthly_meanR=float(by.mean()))


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def load_universe(tf: str):
    out = {}
    for s in UNIVERSE:
        df = load_ohlcv(s, tf)
        if df is not None and len(df) > 500:
            out[s] = df
    return out


def run_one(tf: str, p: Params, n_seeds=50, do_robust=True):
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


def _print_line(tag, res):
    a = res["agg"]; sh = res.get("shuffle", {}); wf = res.get("walk_forward", {})
    print(f"[{tag}] n={a['n']} R0={a['mean_R_0']:.3f} R55={a['mean_R_55']:.3f} "
          f"win={a['win']:.1f}% sh={a['sharpe']:.3f} feeR={a['fee_R_med']:.3f} "
          f"p_gross={sh.get('p_gross','-')} p_net={sh.get('p_net','-')} "
          f"wf={wf.get('pos','-')}/{wf.get('months','-')} monMeanR={wf.get('monthly_meanR',0):.2f}",
          file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concept", choices=["range", "cam"], default="range")
    ap.add_argument("--tf", choices=["15m", "1h"], default="15m")
    ap.add_argument("--tp", default="mid")
    ap.add_argument("--box-lookback", type=int, default=20)
    ap.add_argument("--wick-min-atr", type=float, default=0.10)
    ap.add_argument("--atr-expansion-max", type=float, default=1.2)
    ap.add_argument("--cam-touch-atr", type=float, default=0.05)
    ap.add_argument("--sl-floor-k", type=float, default=0.50)
    ap.add_argument("--max-hold", type=int, default=32)
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-robust", action="store_true")
    args = ap.parse_args()

    if args.all:
        out = {"git": _git_hash(), "fee_rt_bps": FEE_RT_BPS, "matrix": []}
        configs = []
        # concept (a) range: tp mid & opposite, two box sizes
        for tf in ["15m", "1h"]:
            for tp in ["mid", "opposite"]:
                for box in [20, 40]:
                    configs.append(("range", tf, dict(tp=tp, box_lookback=box)))
            # concept (b) cam: central TP, two SL floors
            for floor in [0.5, 1.0]:
                configs.append(("cam", tf, dict(tp="central", sl_floor_k=floor)))
        for concept, tf, kw in configs:
            p = Params(concept=concept, max_hold=args.max_hold, **kw)
            res = run_one(tf, p, n_seeds=args.seeds, do_robust=not args.no_robust)
            out["matrix"].append(res)
            _print_line(f"{concept}/{tf}/{kw}", res)
        outp = ROOT / "data" / "_meanrev_matrix.json"
        outp.write_text(json.dumps(out, indent=2, default=str))
        print(f"WROTE {outp}", file=sys.stderr)
    else:
        p = Params(
            concept=args.concept, tp=args.tp, box_lookback=args.box_lookback,
            wick_min_atr=args.wick_min_atr, atr_expansion_max=args.atr_expansion_max,
            cam_touch_atr=args.cam_touch_atr, sl_floor_k=args.sl_floor_k,
            max_hold=args.max_hold,
        )
        res = run_one(args.tf, p, n_seeds=args.seeds, do_robust=not args.no_robust)
        print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
