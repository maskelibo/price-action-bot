#!/usr/bin/env python3
# ruff: noqa: E741,N803,N802,N806,E702,SIM102,B007,F841
"""
SMC TREND-CONTINUATION backtest driver (separate from SFP file).

Mechanism (structurally DIFFERENT from reversal — institutional continuation prior):
  After a close-based Break of Structure (BOS) in a direction, WITH displacement
  (the OB/MSB detector already requires impulse_range >= 2x OB-range AND an FVG in
  the impulse window -> a displacement gate), wait for the FIRST pullback into the
  zone that the impulse ORIGINATED from (the Order Block, or the impulse FVG), and
  enter IN THE TREND DIRECTION (continuation), NOT a fade.

Two concepts:
  - OB-continuation  : zone = the order block of the break impulse
  - FVG-continuation : zone = the FVG left inside the break impulse window
  - FTR              : "first-time-back" = same family; we treat first revisit of the
                       OB zone as FTR (alias of OB-continuation with require-first-touch)

REUSES the lookahead-audited detectors from smc_sfp_backtest.py
(detect_swings, detect_ob_msb, detect_fvg, _atr) — does NOT modify that file.

Causality: BOS at bar b is confirmed at b (close-based, swing confirmed by b-1-L).
The zone is known at b. We then scan bars > b for the FIRST bar whose range enters
the zone band; entry is on that pullback bar's close (with-trend). SL beyond the
zone far edge, floored at k*ATR. TP = fixed R. No future leakage.

Shuffle baseline: randomize the trade DIRECTION (keep entry timing + levels) -> the
fee-independent p_gross is the decisive directional-edge test.

DATA: 4h added (direct), plus 15m/1h from the SFP loader.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

# reuse audited detectors + metrics + git hash
sys.path.insert(0, str(Path(__file__).resolve().parent))
from smc_sfp_backtest import (  # noqa: E402
    DB,
    FEE_RT_BPS,
    UNIVERSE,
    _atr,
    _git_hash,
    calendar_day_sharpe,
    detect_fvg,
    detect_ob_msb,
    max_drawdown_R,
)
from smc_sfp_backtest import load_ohlcv as _load_ohlcv_base  # noqa: E402


# --------------------------------------------------------------------------- #
# Data loading — extend to 4h (direct) while keeping SFP loader for 5m/15m/1h
# --------------------------------------------------------------------------- #
def load_ohlcv(symbol: str, tf: str) -> pd.DataFrame | None:
    if tf in ("5m", "15m", "1h", "30m", "45m"):
        return _load_ohlcv_base(symbol, tf)
    if tf != "4h":
        raise ValueError(f"unsupported tf {tf}")
    sym = f"{symbol}/USDT"
    con = duckdb.connect(str(DB), read_only=True)
    try:
        vrows = con.execute(
            "SELECT venue, count(*) n FROM ohlcv WHERE symbol=? AND timeframe='4h' "
            "GROUP BY venue ORDER BY n DESC LIMIT 1",
            [sym],
        ).fetchall()
        if not vrows:
            return None
        venue = vrows[0][0]
        df = con.execute(
            "SELECT (ts AT TIME ZONE 'UTC') AS ts, open, high, low, close, volume "
            "FROM ohlcv WHERE venue=? AND symbol=? AND timeframe='4h' ORDER BY ts",
            [venue, sym],
        ).fetch_df()
    finally:
        con.close()
    if df.empty:
        return None
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df[["open", "high", "low", "close", "volume"]]


# --------------------------------------------------------------------------- #
# Params
# --------------------------------------------------------------------------- #
@dataclass
class Params:
    L: int = 3
    min_gap: float = 0.0010
    atr_period: int = 14
    zone: str = "ob"  # ob | fvg  (which zone the pullback must enter)
    require_first_touch: bool = True  # FTR/FTB: only the FIRST revisit qualifies
    k_atr_floor: float = 1.5  # stop floor in ATR; also the structural-stop floor
    sl_buffer_atr: float = 0.10  # extra buffer beyond zone far edge
    R: float = 2.0  # fixed TP in R
    max_hold: int = 48
    pullback_window: int = 48  # max bars after BOS to wait for the pullback
    min_disp_atr: float = 0.0  # extra displacement floor on impulse range (ATR); 0=off (OB detector already gates)


# --------------------------------------------------------------------------- #
# Candidate construction (deterministic, direction-independent for shuffle)
# --------------------------------------------------------------------------- #
_CAND_CACHE: dict = {}


def _df_fp(df: pd.DataFrame):
    return (id(df), len(df), int(df.index[0].value), int(df.index[-1].value),
            float(df["close"].iloc[-1]))


def _build_candidates(df: pd.DataFrame, p: Params):
    key = (_df_fp(df), p.L, round(p.min_gap, 8), p.zone, p.require_first_touch,
           round(p.k_atr_floor, 4), round(p.sl_buffer_atr, 4), p.pullback_window,
           round(p.min_disp_atr, 4), p.atr_period)
    if key in _CAND_CACHE:
        return _CAND_CACHE[key]

    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(df)
    atr = _atr(df, p.atr_period)

    msb_dir, obs = detect_ob_msb(df, p.L, p.min_gap)
    fvg = detect_fvg(df, p.min_gap)  # dict idx -> (kind, lo, hi)

    # Build the list of continuation zones keyed by the BOS break bar.
    # For OB: the order block of that break (obs[break_idx]).
    # For FVG: the LAST FVG inside the impulse window [break-5, break] matching dir.
    # Each zone: (break_idx, dir(+1/-1), lo, hi).
    zones = []
    if p.zone == "ob":
        for b, (kind, lo, hi) in obs.items():
            d = 1 if kind == "bull" else -1
            zones.append((b, d, lo, hi))
    else:  # fvg
        # index FVGs by bar for quick window scan
        for b in np.where(msb_dir != 0)[0]:
            d = int(msb_dir[b])
            want = "bull" if d == 1 else "bear"
            w0 = max(0, b - 5)
            best = None
            for j in range(w0, b + 1):
                if j in fvg and fvg[j][0] == want:
                    best = fvg[j]  # take the latest matching FVG in the impulse window
            if best is not None:
                zones.append((b, d, best[1], best[2]))

    e_idx_l, ent_l, dir_l, sl_dist_l = [], [], [], []
    for (b, d, zlo, zhi) in zones:
        a_b = atr[b] if atr[b] > 0 else (c[b] * 0.005)
        # optional extra displacement floor on the impulse range
        if p.min_disp_atr > 0:
            w0 = max(0, b - 5)
            imp = h[w0:b + 1].max() - l[w0:b + 1].min()
            if imp < p.min_disp_atr * a_b:
                continue
        # scan FORWARD for the first pullback bar that ENTERS the zone band [zlo,zhi]
        end = min(n, b + 1 + p.pullback_window)
        hit = -1
        for j in range(b + 1, end):
            # range overlap with zone band
            if l[j] <= zhi and h[j] >= zlo:
                hit = j
                break
        if hit < 0:
            continue
        e = hit
        if e + 1 >= n:
            continue
        entry_price = c[e]
        a = atr[e] if atr[e] > 0 else (c[e] * 0.005)
        # SL beyond the zone FAR edge (continuation): for longs, below zlo; shorts above zhi
        if d == 1:
            struct_sl = zlo - p.sl_buffer_atr * a
            sl_dist = entry_price - struct_sl
        else:
            struct_sl = zhi + p.sl_buffer_atr * a
            sl_dist = struct_sl - entry_price
        sl_dist = max(sl_dist, p.k_atr_floor * a)
        if sl_dist <= 0:
            continue
        e_idx_l.append(e)
        ent_l.append(entry_price)
        dir_l.append(d)
        sl_dist_l.append(sl_dist)

    cand = dict(
        e_idx=np.array(e_idx_l, dtype=int),
        ent=np.array(ent_l, dtype=float),
        base_dir=np.array(dir_l, dtype=np.int8),
        sl_dist=np.array(sl_dist_l, dtype=float),
    )
    if len(_CAND_CACHE) > 200:
        _CAND_CACHE.clear()
    _CAND_CACHE[key] = cand
    return cand


def backtest_symbol(df, p: Params, randomize_dir=None):
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
    sl_dist_a = cand["sl_dist"]
    if randomize_dir is not None:
        dir_a = np.where(randomize_dir.random(len(e_idx_a)) < 0.5, 1, -1).astype(np.int8)
    else:
        dir_a = cand["base_dir"]

    sl_a = ent_a - dir_a * sl_dist_a
    risk_a = sl_dist_a.copy()
    valid = risk_a > 0
    risk_safe = np.where(valid, risk_a, np.nan)
    fee_frac = FEE_RT_BPS / 10000.0
    fee_R_a = fee_frac / (risk_safe / ent_a)
    tp_a = ent_a + dir_a * p.R * risk_a

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

    def first_true_idx(mat):
        any_t = mat.any(axis=1)
        return np.where(any_t, mat.argmax(axis=1), H), any_t

    sl_first, _ = first_true_idx(sl_hit)
    tp_first, _ = first_true_idx(tp_hit)
    sl_step = np.where(sl_hit.any(axis=1), sl_first, H + 1)
    tp_step = np.where(tp_hit.any(axis=1), tp_first, H + 1)

    T = len(e_idx_a)
    tp_R = np.abs(tp_a - ent_a) / risk_safe
    has_sl = sl_step <= H
    has_tp = tp_step <= H
    timed = (~has_sl) & (~has_tp)
    sl_wins = has_sl & (sl_step <= tp_step)  # SL-first/tie conservative
    tp_wins = has_tp & (~sl_wins)

    exit_step = np.where(sl_wins, sl_step, np.where(tp_wins, tp_step, 0))
    last_step = np.where(in_range.any(axis=1),
                         in_range.shape[1] - 1 - in_range[:, ::-1].argmax(axis=1), 0)
    exit_step = np.where(timed, last_step, exit_step)
    cc_at = cc[np.arange(T), exit_step]
    timed_R = np.where(dir_a == 1, (cc_at - ent_a), (ent_a - cc_at)) / risk_safe
    R_gross = np.where(sl_wins, -1.0, np.where(tp_wins, tp_R, timed_R))
    R_net = R_gross - fee_R_a
    exit_bar = np.clip(e_idx_a + 1 + exit_step, 0, n - 1)

    ts = df.index
    v = valid
    trades = [
        {"entry_ts": ts[e_idx_a[v][k]], "exit_ts": ts[exit_bar[v][k]],
         "dir": int(dir_a[v][k]), "R_gross": float(R_gross[v][k]),
         "R_net": float(R_net[v][k]), "fee_R": float(fee_R_a[v][k])}
        for k in range(int(v.sum()))
    ]
    return trades


# --------------------------------------------------------------------------- #
# Metrics / robustness (reuse SFP helpers where possible)
# --------------------------------------------------------------------------- #
def summarize(trades):
    if not trades:
        return dict(n=0, mean_R_0=0.0, mean_R_55=0.0, win=0.0, sharpe=0.0, mdd=0.0,
                    total_R=0.0, fee_R_med=0.0)
    rg = np.array([t["R_gross"] for t in trades])
    rn = np.array([t["R_net"] for t in trades])
    fr = np.array([t["fee_R"] for t in trades])
    return dict(
        n=len(trades), mean_R_0=float(rg.mean()), mean_R_55=float(rn.mean()),
        win=float((rn > 0).mean() * 100), sharpe=calendar_day_sharpe(trades),
        mdd=max_drawdown_R(trades), total_R=float(rn.sum()), fee_R_med=float(np.median(fr)),
    )


def shuffle_pvalue(uni, p: Params, n_seeds=50):
    real = []
    for sym, df in uni.items():
        real += backtest_symbol(df, p)
    if not real:
        return dict(real_net=0.0, real_gross=0.0, p_net=1.0, p_gross=1.0,
                    shuf_gross_mean=0.0, shuf_net_mean=0.0)
    real_net = float(np.mean([t["R_net"] for t in real]))
    real_gross = float(np.mean([t["R_gross"] for t in real]))
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
    return dict(
        real_net=real_net, real_gross=real_gross,
        p_net=float((sn >= real_net).mean()), p_gross=float((sg >= real_gross).mean()),
        shuf_gross_mean=float(sg.mean()), shuf_net_mean=float(sn.mean()),
    )


def walk_forward_months(uni, p: Params):
    all_tr = []
    for sym, df in uni.items():
        all_tr += backtest_symbol(df, p)
    if not all_tr:
        return dict(months=0, pos=0, frac=0.0, monthly_meanR=0.0)
    d = pd.DataFrame(all_tr)
    d["month"] = pd.to_datetime(d["exit_ts"]).dt.to_period("M")
    by = d.groupby("month")["R_net"].sum()
    bg = d.assign(m=d["month"]).groupby("m")["R_gross"].sum()
    return dict(months=len(by), pos=int((by > 0).sum()), frac=float((by > 0).mean()),
                monthly_meanR=float(by.mean()), pos_gross=int((bg > 0).sum()))


def load_universe(tf):
    out = {}
    for s in UNIVERSE:
        df = load_ohlcv(s, tf)
        if df is not None and len(df) > 300:
            out[s] = df
    return out


def run_one(tf, p: Params, n_seeds=50, do_robust=True):
    uni = load_universe(tf)
    per_sym, all_tr = {}, []
    for sym, df in uni.items():
        tr = backtest_symbol(df, p)
        per_sym[sym] = summarize(tr)
        all_tr += tr
    res = dict(tf=tf, params=asdict(p), agg=summarize(all_tr),
               per_symbol=per_sym, n_symbols=len(uni))
    if do_robust:
        res["shuffle"] = shuffle_pvalue(uni, p, n_seeds=n_seeds)
        res["walk_forward"] = walk_forward_months(uni, p)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h")
    ap.add_argument("--zone", choices=["ob", "fvg"], default="ob")
    ap.add_argument("--k-atr", type=float, default=1.5)
    ap.add_argument("--R", type=float, default=2.0)
    ap.add_argument("--no-first-touch", action="store_true")
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--matrix", action="store_true")
    ap.add_argument("--no-robust", action="store_true")
    args = ap.parse_args()

    if args.matrix:
        out = {"git": _git_hash(), "fee_rt_bps": FEE_RT_BPS, "matrix": []}
        for tf in ["15m", "1h", "4h"]:
            for zone in ["ob", "fvg"]:
                for k in [1.5, 2.5]:
                    for R in [2.0, 3.0]:
                        p = Params(zone=zone, k_atr_floor=k, R=R)
                        res = run_one(tf, p, n_seeds=args.seeds, do_robust=not args.no_robust)
                        out["matrix"].append(res)
                        a = res["agg"]; sh = res.get("shuffle", {}); wf = res.get("walk_forward", {})
                        print(f"tf={tf} zone={zone} k={k} R={R} | n={a['n']} "
                              f"R0={a['mean_R_0']:.3f} R55={a['mean_R_55']:.3f} win={a['win']:.1f}% "
                              f"feeR={a['fee_R_med']:.3f} p_gross={sh.get('p_gross','-')} "
                              f"p_net={sh.get('p_net','-')} wf={wf.get('pos','-')}/{wf.get('months','-')}",
                              file=sys.stderr)
        outp = Path("/Users/peyman/price-action-bot/data/_smc_cache/continuation_matrix.json")
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(out, indent=2, default=str))
        print(f"WROTE {outp}", file=sys.stderr)
    else:
        p = Params(zone=args.zone, k_atr_floor=args.k_atr, R=args.R,
                   require_first_touch=not args.no_first_touch)
        res = run_one(args.tf, p, n_seeds=args.seeds, do_robust=not args.no_robust)
        print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
