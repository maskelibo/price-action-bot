#!/usr/bin/env python3
# ruff: noqa: E741,N803,N802,N806,E702,SIM102,B007,F841
"""
v4 HIGHER-TIMEFRAME (4h/1d) continuation / trend edge hunt — DIVERSIFIER search.

GOAL: find a SECOND, uncorrelated positive edge on 4h/1d (where lower turnover
survives the 55bps fee bite) that can STACK with the live VSA-WIDESTOP champion
(vsa_climax_test 15m) to lift portfolio Sharpe. A candidate is valuable ONLY if:
  (a) real gross edge: shuffle p_gross < 0.05 (direction beats its own null), AND
  (b) low-correlation diversifier: |rho_daily| < 0.30 vs the champion's daily-R series.

THREE candidate families (all lookahead-safe; decision uses bars <= t-1, ENTRY ON
THE NEXT BAR'S OPEN; no shift(-1)/center):

  A) BOS+displacement continuation: after a close-based Break-of-Structure with a
     quality (displacement) order block / FVG, enter WITH-TREND on the FIRST pullback
     into the originating OB/FVG zone. SL beyond zone far edge (ATR-floored), TP fixed R.
     -> reuses audited detect_ob_msb / detect_fvg / _atr from smc_sfp_backtest.py.

  B) Donchian breakout with-trend: close > N-bar prior high (long) / < N-bar prior low
     (short), filtered by trend (EMA-fast vs EMA-slow). Entry next open, SL = k*ATR,
     TP = R*risk. Lower turnover version of the 15m breakout that shuffle-FAILED.

  C) EMA200 + pullback momentum: trend = close vs EMA200; in an uptrend, buy the first
     pullback that tags EMA-fast then closes back up (mirror for downtrend). Entry next
     open, SL = k*ATR, TP = R*risk.

CAUSALITY CONTRACT (Feynman: do not fool yourself):
  - Every signal is decided on bar t using ONLY data with index <= t (and swing pivots
    that are confirmed <= t-1 inside the audited detectors).
  - The trade ENTERS at open[t+1] (next bar open), never at close[t]. If t+1 is the last
    bar, the candidate is dropped.
  - Exit walk starts at t+2 (the bar AFTER entry) for SL/TP/timeout, conservative SL-first.

SHUFFLE NULL: randomize trade DIRECTION (keep entry timing + level geometry). p_gross is
the fee-independent directional-edge test. p_net adds the 55bps drag.

CORRELATION vs CHAMPION: build the champion's per-trade R via the real engine
(crypto_winner_let_run_vsa_exit.gather, widestop sl_pct>=0.025 subset, BASELINE exit),
aggregate to a CALENDAR-DAY summed-R series; aggregate each candidate's net R to the same
calendar-day grid; Pearson rho on the overlapping days. <0.30 abs => diversifier.

DATA: data/market.duckdb. 4h = 10 symbols (BTC ETH SOL BNB ADA AVAX LINK DOT DOGE XRP,
~2023-05..2026-05). 1d = all 15 (adds ZEC NEAR FIL XLM TRX, ~2021-05..2026-06).

Does NOT modify any other agent's file. Reuses smc_sfp_backtest detectors/metrics.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import warnings

import duckdb
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from smc_sfp_backtest import (  # noqa: E402
    DB,
    FEE_RT_BPS,
    UNIVERSE,
    _atr,
    _git_hash,
    detect_fvg,
    detect_ob_msb,
)

CHAMP_CACHE = Path("/tmp/v4_champion_daily_R.json")


# --------------------------------------------------------------------------- #
# Data loading: direct 4h and 1d (the 15m loader does not serve these TFs)
# --------------------------------------------------------------------------- #
def load_ohlcv_htf(symbol: str, tf: str) -> pd.DataFrame | None:
    assert tf in ("4h", "1d")
    sym = f"{symbol}/USDT"
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


def load_universe(tf: str) -> dict:
    out = {}
    for s in UNIVERSE:
        df = load_ohlcv_htf(s, tf)
        if df is not None and len(df) > 250:
            out[s] = df
    return out


# --------------------------------------------------------------------------- #
# Common exit walker — entry on NEXT OPEN (e+1), exit walk from e+2. Vectorized.
# Signal arrays: sig_bar (decision bar t), dir (+1/-1), risk_dist (price units).
# --------------------------------------------------------------------------- #
def _walk_exits(df, sig_bar, base_dir, risk_dist, R, max_hold, randomize_dir=None):
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(df)

    sig_bar = np.asarray(sig_bar, dtype=int)
    # entry is next bar's open
    e_idx = sig_bar + 1
    ok = (e_idx < n - 1) & (risk_dist > 0)
    sig_bar = sig_bar[ok]
    e_idx = e_idx[ok]
    risk_dist = np.asarray(risk_dist, dtype=float)[ok]
    base_dir = np.asarray(base_dir, dtype=np.int8)[ok]
    if e_idx.size == 0:
        return []

    if randomize_dir is not None:
        d = np.where(randomize_dir.random(e_idx.size) < 0.5, 1, -1).astype(np.int8)
    else:
        d = base_dir

    ent = o[e_idx]  # NEXT OPEN
    sl = ent - d * risk_dist
    tp = ent + d * R * risk_dist
    fee_frac = FEE_RT_BPS / 10000.0
    fee_R = fee_frac / (risk_dist / ent)

    H = max_hold
    # exit walk begins at the bar AFTER entry (e+1 .. e+H)
    offs = e_idx[:, None] + 1 + np.arange(H)[None, :]
    in_range = offs < n
    offs_c = np.clip(offs, 0, n - 1)
    hh = np.where(in_range, h[offs_c], np.nan)
    ll = np.where(in_range, l[offs_c], np.nan)
    cc = c[offs_c]

    long = d == 1
    sl_hit = np.where(long[:, None], ll <= sl[:, None], hh >= sl[:, None]) & in_range
    tp_hit = np.where(long[:, None], hh >= tp[:, None], ll <= tp[:, None]) & in_range

    def first_idx(mat):
        any_t = mat.any(axis=1)
        return np.where(any_t, mat.argmax(axis=1), H)

    sl_first = first_idx(sl_hit)
    tp_first = first_idx(tp_hit)
    sl_step = np.where(sl_hit.any(axis=1), sl_first, H + 1)
    tp_step = np.where(tp_hit.any(axis=1), tp_first, H + 1)

    T = e_idx.size
    tp_R = R
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
    timed_R = np.where(d == 1, (cc_at - ent), (ent - cc_at)) / risk_dist
    R_gross = np.where(sl_wins, -1.0, np.where(tp_wins, tp_R, timed_R))
    R_net = R_gross - fee_R
    exit_bar = np.clip(e_idx + 1 + exit_step, 0, n - 1)

    ts = df.index
    return [
        {"entry_ts": ts[e_idx[k]], "exit_ts": ts[exit_bar[k]], "dir": int(d[k]),
         "R_gross": float(R_gross[k]), "R_net": float(R_net[k]), "fee_R": float(fee_R[k])}
        for k in range(T)
    ]


# --------------------------------------------------------------------------- #
# Candidate A: BOS+displacement continuation (pullback to OB/FVG, with-trend)
# --------------------------------------------------------------------------- #
@dataclass
class ParamsA:
    family: str = "A_bos_cont"
    L: int = 3
    min_gap: float = 0.0010
    atr_period: int = 14
    zone: str = "ob"           # ob | fvg
    k_atr_floor: float = 1.0   # stop floor in ATR
    sl_buffer_atr: float = 0.10
    R: float = 2.0
    max_hold: int = 24
    pullback_window: int = 24


def _signals_A(df, p: ParamsA):
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(df)
    atr = _atr(df, p.atr_period)
    msb_dir, obs = detect_ob_msb(df, p.L, p.min_gap)
    fvg = detect_fvg(df, p.min_gap)

    zones = []  # (break_bar, dir, zlo, zhi)
    if p.zone == "ob":
        for b, (kind, lo, hi) in obs.items():
            zones.append((b, 1 if kind == "bull" else -1, lo, hi))
    else:
        for b in np.where(msb_dir != 0)[0]:
            d = int(msb_dir[b]); want = "bull" if d == 1 else "bear"
            w0 = max(0, b - 5); best = None
            for j in range(w0, b + 1):
                if j in fvg and fvg[j][0] == want:
                    best = fvg[j]
            if best is not None:
                zones.append((b, d, best[1], best[2]))

    sig_bar, dirs, risk = [], [], []
    for (b, d, zlo, zhi) in zones:
        end = min(n, b + 1 + p.pullback_window)
        hit = -1
        for j in range(b + 1, end):
            if l[j] <= zhi and h[j] >= zlo:   # first pullback into the zone band, KNOWN at close[j]
                hit = j
                break
        if hit < 0 or hit + 1 >= n:
            continue
        a = atr[hit] if atr[hit] > 0 else c[hit] * 0.005
        ent_ref = c[hit]  # entry will be next open; size risk off the structural zone
        if d == 1:
            sl_dist = (ent_ref - (zlo - p.sl_buffer_atr * a))
        else:
            sl_dist = ((zhi + p.sl_buffer_atr * a) - ent_ref)
        sl_dist = max(sl_dist, p.k_atr_floor * a)
        if sl_dist <= 0:
            continue
        sig_bar.append(hit); dirs.append(d); risk.append(sl_dist)
    return np.array(sig_bar, int), np.array(dirs, np.int8), np.array(risk, float)


# --------------------------------------------------------------------------- #
# Candidate B: Donchian breakout with-trend
# --------------------------------------------------------------------------- #
@dataclass
class ParamsB:
    family: str = "B_donchian"
    N: int = 20            # donchian lookback
    ema_fast: int = 20
    ema_slow: int = 50
    atr_period: int = 14
    k_atr: float = 1.5
    R: float = 2.0
    max_hold: int = 24


def _signals_B(df, p: ParamsB):
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(df)
    atr = _atr(df, p.atr_period)
    ef = pd.Series(c).ewm(span=p.ema_fast, adjust=False).mean().values
    es = pd.Series(c).ewm(span=p.ema_slow, adjust=False).mean().values
    # prior-N high/low EXCLUDING current bar -> known at close[t]
    sh = pd.Series(h).shift(1).rolling(p.N).max().values
    sl_ = pd.Series(l).shift(1).rolling(p.N).min().values

    sig_bar, dirs, risk = [], [], []
    for t in range(p.N + p.ema_slow, n - 1):
        a = atr[t]
        if not (a > 0):
            continue
        up = ef[t] > es[t]
        dn = ef[t] < es[t]
        if up and c[t] > sh[t]:
            sig_bar.append(t); dirs.append(1); risk.append(p.k_atr * a)
        elif dn and c[t] < sl_[t]:
            sig_bar.append(t); dirs.append(-1); risk.append(p.k_atr * a)
    return np.array(sig_bar, int), np.array(dirs, np.int8), np.array(risk, float)


# --------------------------------------------------------------------------- #
# Candidate C: EMA200 trend + pullback to EMA-fast
# --------------------------------------------------------------------------- #
@dataclass
class ParamsC:
    family: str = "C_ema200_pull"
    ema_trend: int = 200
    ema_pull: int = 20
    atr_period: int = 14
    k_atr: float = 1.5
    R: float = 2.0
    max_hold: int = 24


def _signals_C(df, p: ParamsC):
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(df)
    atr = _atr(df, p.atr_period)
    et = pd.Series(c).ewm(span=p.ema_trend, adjust=False).mean().values
    ep = pd.Series(c).ewm(span=p.ema_pull, adjust=False).mean().values

    sig_bar, dirs, risk = [], [], []
    for t in range(p.ema_trend + 2, n - 1):
        a = atr[t]
        if not (a > 0):
            continue
        up = c[t] > et[t]
        dn = c[t] < et[t]
        # uptrend pullback: prior bar tagged below EMA-fast, this bar closes back above it
        if up and l[t - 1] <= ep[t - 1] and c[t] > ep[t] and c[t] > c[t - 1]:
            sig_bar.append(t); dirs.append(1); risk.append(p.k_atr * a)
        elif dn and h[t - 1] >= ep[t - 1] and c[t] < ep[t] and c[t] < c[t - 1]:
            sig_bar.append(t); dirs.append(-1); risk.append(p.k_atr * a)
    return np.array(sig_bar, int), np.array(dirs, np.int8), np.array(risk, float)


SIGNAL_FN = {"A_bos_cont": _signals_A, "B_donchian": _signals_B, "C_ema200_pull": _signals_C}


def backtest_symbol(df, p, randomize_dir=None):
    minlen = {"A_bos_cont": getattr(p, "atr_period", 14) + 60,
              "B_donchian": p.N + p.ema_slow + 5 if hasattr(p, "N") else 80,
              "C_ema200_pull": getattr(p, "ema_trend", 200) + 5}[p.family]
    if df is None or len(df) < minlen:
        return []
    sig_bar, dirs, risk = SIGNAL_FN[p.family](df, p)
    if sig_bar.size == 0:
        return []
    return _walk_exits(df, sig_bar, dirs, risk, p.R, p.max_hold, randomize_dir=randomize_dir)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def calendar_day_R(trades, key="R_net"):
    if not trades:
        return pd.Series(dtype=float)
    d = pd.DataFrame(trades)
    d["day"] = pd.to_datetime(d["exit_ts"], utc=True).dt.floor("D")
    return d.groupby("day")[key].sum()


def calendar_day_sharpe(trades, key="R_net"):
    daily = calendar_day_R(trades, key)
    if len(daily) < 2 or daily.std(ddof=1) == 0:
        return 0.0
    return float(daily.mean() / daily.std(ddof=1))


def max_drawdown_R(trades, key="R_net"):
    if not trades:
        return 0.0
    eq = np.cumsum([t[key] for t in sorted(trades, key=lambda x: x["exit_ts"])])
    peak = np.maximum.accumulate(eq)
    return float((eq - peak).min())


def top5_R_share(trades):
    if not trades:
        return 0.0
    rn = np.array([t["R_net"] for t in trades])
    wins = rn[rn > 0]
    if wins.size == 0:
        return 0.0
    k = max(1, int(np.ceil(0.05 * len(rn))))
    top = np.sort(rn)[::-1][:k]
    return float(top[top > 0].sum() / wins.sum())


def summarize(trades):
    if not trades:
        return dict(n=0, mean_R_0=0.0, mean_R_55=0.0, win=0.0, sharpe=0.0,
                    mdd=0.0, total_R_55=0.0, top5=0.0, fee_R_med=0.0)
    rg = np.array([t["R_gross"] for t in trades])
    rn = np.array([t["R_net"] for t in trades])
    fr = np.array([t["fee_R"] for t in trades])
    return dict(
        n=len(trades), mean_R_0=float(rg.mean()), mean_R_55=float(rn.mean()),
        win=float((rn > 0).mean() * 100), sharpe=calendar_day_sharpe(trades),
        mdd=max_drawdown_R(trades), total_R_55=float(rn.sum()),
        top5=top5_R_share(trades), fee_R_med=float(np.median(fr)),
    )


def shuffle_pvalue(uni, p, n_seeds=50):
    real = []
    for sym, df in uni.items():
        real += backtest_symbol(df, p)
    if not real:
        return dict(real_net=0.0, real_gross=0.0, p_net=1.0, p_gross=1.0,
                    shuf_gross_mean=0.0, shuf_net_mean=0.0, n=0)
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
        real_net=real_net, real_gross=real_gross, n=len(real),
        p_net=float((sn >= real_net).mean()), p_gross=float((sg >= real_gross).mean()),
        shuf_gross_mean=float(sg.mean()), shuf_net_mean=float(sn.mean()),
    )


def walk_forward_months(uni, p):
    tr = []
    for sym, df in uni.items():
        tr += backtest_symbol(df, p)
    if not tr:
        return dict(months=0, pos=0, frac=0.0, monthly_meanR=0.0)
    d = pd.DataFrame(tr)
    d["month"] = pd.to_datetime(d["exit_ts"], utc=True).dt.to_period("M")
    by = d.groupby("month")["R_net"].sum()
    bg = d.groupby("month")["R_gross"].sum()
    return dict(months=int(len(by)), pos=int((by > 0).sum()), frac=float((by > 0).mean()),
                monthly_meanR=float(by.mean()), pos_gross=int((bg > 0).sum()))


# --------------------------------------------------------------------------- #
# CHAMPION daily-R series (real engine; widestop sl_pct>=0.025 subset, BASELINE exit)
# --------------------------------------------------------------------------- #
def champion_daily_R():
    if CHAMP_CACHE.exists():
        s = pd.read_json(CHAMP_CACHE, typ="series")
        s.index = pd.to_datetime(s.index, utc=True)
        return s
    sys.path.insert(0, str(ROOT / "scripts"))
    import crypto_winner_let_run_vsa_exit as wlr  # noqa: E402
    from crypto_winner_let_run_vsa_exit import gather  # noqa: E402
    # honest 55bps: taker 27.5 bps/leg x2 = 55bps round-trip, 0 slippage
    wlr.FEES = {"taker": 0.00275, "maker": -0.00010}
    wlr.SLIPPAGE_BPS = 0.0
    # BASELINE exit (the validated +7.58%/mo edge) — exact engine knobs from
    # _champ_55bps_exit_compare.py EXITS["BASELINE"].
    base_exit = dict(
        runner_trail_mult=1.5, trail_activate_stage=2,
        tp1_R=1.0, tp2_R=1.5, tp1_close_pct=0.30, tp2_close_pct=0.30,
        runner_force_exit_method="time", runner_force_exit_bars=30,
        force_exit_from_entry=False,
    )
    SL_PCT_MIN = 0.025
    rows = []
    for sym in UNIVERSE:
        full = f"{sym}/USDT"  # gather() expects the full venue symbol string
        try:
            tr = gather(full, base_exit, tf="15m")
        except Exception as ex:
            print(f"[champ] {sym} gather failed: {ex}", file=sys.stderr)
            continue
        for t in tr:
            ep, sp = t["entry_price"], t["initial_sl"]
            slp = abs(sp - ep) / ep if ep > 0 else 0.04
            if slp >= SL_PCT_MIN:
                rows.append({"exit_ts": t["exit_ts"], "R": t["R"]})
        print(f"[champ] {sym}: {len(tr)} trades", file=sys.stderr)
    if not rows:
        raise RuntimeError("champion gather produced no trades")
    d = pd.DataFrame(rows)
    d["day"] = pd.to_datetime(d["exit_ts"], utc=True).dt.floor("D")
    s = d.groupby("day")["R"].sum()
    s.index = s.index.astype(str)
    s.to_json(CHAMP_CACHE)
    s.index = pd.to_datetime(s.index, utc=True)
    print(f"[champ] cached {len(s)} days, total R={s.sum():.1f}", file=sys.stderr)
    return s


def corr_to_champion(cand_trades, champ_daily):
    if not cand_trades or champ_daily is None or len(champ_daily) == 0:
        return dict(rho=float("nan"), overlap_days=0)
    cand_daily = calendar_day_R(cand_trades, "R_net")
    j = pd.concat([champ_daily.rename("champ"), cand_daily.rename("cand")], axis=1)
    # reindex to union of days; missing day = 0 R (no trade that day = flat)
    j = j.reindex(pd.date_range(min(j.index.min(), cand_daily.index.min()),
                                max(j.index.max(), cand_daily.index.max()),
                                freq="D", tz="UTC")).fillna(0.0)
    # restrict to the candidate's active window (first..last trade day) so we measure
    # co-movement over the period the candidate is actually live, not a long flat tail
    lo, hi = cand_daily.index.min(), cand_daily.index.max()
    j = j.loc[lo:hi]
    overlap = int(((j["champ"] != 0) & (j["cand"] != 0)).sum())
    if len(j) < 5 or j["cand"].std() == 0 or j["champ"].std() == 0:
        return dict(rho=float("nan"), overlap_days=overlap, active_days=int(len(j)))
    rho = float(np.corrcoef(j["champ"], j["cand"])[0, 1])
    return dict(rho=rho, overlap_days=overlap, active_days=int(len(j)))


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def run_one(tf, p, uni, champ_daily, n_seeds=50):
    per_sym, all_tr = {}, []
    for sym, df in uni.items():
        tr = backtest_symbol(df, p)
        per_sym[sym] = summarize(tr)
        all_tr += tr
    res = dict(tf=tf, family=p.family, params=asdict(p), agg=summarize(all_tr),
               n_symbols=len(uni))
    res["shuffle"] = shuffle_pvalue(uni, p, n_seeds=n_seeds)
    res["walk_forward"] = walk_forward_months(uni, p)
    res["corr"] = corr_to_champion(all_tr, champ_daily)
    return res


def verdict_line(res):
    a = res["agg"]; sh = res["shuffle"]; wf = res["walk_forward"]; cr = res["corr"]
    pg = sh["p_gross"]; rho = cr["rho"]
    edge_ok = (pg < 0.05) and (a["mean_R_55"] > 0)
    div_ok = (rho == rho) and (abs(rho) < 0.30)
    if edge_ok and div_ok:
        v = "DIVERSIFIER"
    elif edge_ok and not div_ok:
        v = "EDGE-but-CORRELATED"
    elif (pg < 0.05) and a["mean_R_55"] <= 0:
        v = "GROSS-edge-fee-killed"
    else:
        v = "REJECT(no-edge)"
    return v, edge_ok, div_ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--tfs", default="1d,4h")
    ap.add_argument("--quick", action="store_true", help="one param per family")
    ap.add_argument("--champ-only", action="store_true")
    args = ap.parse_args()

    champ_daily = champion_daily_R()
    if args.champ_only:
        print(f"champion daily-R: {len(champ_daily)} days, total R={champ_daily.sum():.1f}, "
              f"mean/day={champ_daily.mean():.3f}")
        return

    # Param grids (kept SMALL to limit multiple-testing; HTF = coarse by design)
    if args.quick:
        gridA = [ParamsA(zone="ob", k_atr_floor=1.0, R=2.0)]
        gridB = [ParamsB(N=20, k_atr=1.5, R=2.0)]
        gridC = [ParamsC(k_atr=1.5, R=2.0)]
    else:
        gridA = [ParamsA(zone=z, k_atr_floor=k, R=R)
                 for z in ("ob", "fvg") for k in (1.0, 1.5) for R in (2.0, 3.0)]
        gridB = [ParamsB(N=N, ema_slow=es, k_atr=1.5, R=R)
                 for N in (20, 55) for es in (50, 100) for R in (2.0, 3.0)]
        gridC = [ParamsC(ema_pull=ep, k_atr=1.5, R=R)
                 for ep in (20, 50) for R in (2.0, 3.0)]

    out = {"git": _git_hash(), "fee_rt_bps": FEE_RT_BPS,
           "champ_total_R": float(champ_daily.sum()), "champ_days": int(len(champ_daily)),
           "results": []}
    n_trials = 0
    for tf in args.tfs.split(","):
        uni = load_universe(tf)
        print(f"\n==== TF {tf}: {len(uni)} symbols ====", file=sys.stderr)
        for grid in (gridA, gridB, gridC):
            for p in grid:
                res = run_one(tf, p, uni, champ_daily, n_seeds=args.seeds)
                out["results"].append(res)
                n_trials += 1
                a = res["agg"]; sh = res["shuffle"]; wf = res["walk_forward"]; cr = res["corr"]
                v, _, _ = verdict_line(res)
                pp = {k: v2 for k, v2 in res["params"].items()
                      if k not in ("family", "atr_period", "min_gap", "L", "max_hold",
                                   "sl_buffer_atr", "pullback_window", "ema_fast", "ema_trend")}
                print(f"tf={tf} {p.family} {pp} | n={a['n']} R0={a['mean_R_0']:+.3f} "
                      f"R55={a['mean_R_55']:+.3f} win={a['win']:.0f}% Sh={a['sharpe']:+.3f} "
                      f"mdd={a['mdd']:.0f}R top5={a['top5']:.2f} | p_g={sh['p_gross']:.3f} "
                      f"p_n={sh['p_net']:.3f} wf={wf['pos']}/{wf['months']} "
                      f"rho={cr['rho']:+.3f} | {v}", file=sys.stderr)

    # Benjamini-Hochberg note on n_trials (gross p-values)
    out["n_trials"] = n_trials
    outp = ROOT / "data" / "_smc_cache" / "v4_htf_continuation.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWROTE {outp}  ({n_trials} trials)", file=sys.stderr)


if __name__ == "__main__":
    main()
