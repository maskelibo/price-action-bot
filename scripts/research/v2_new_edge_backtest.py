#!/usr/bin/env python3
"""
v2_new_edge_backtest.py — Search for a GENUINELY NEW crypto edge (not chart patterns).

Chart patterns failed twice (Fabio orderflow, SMC). This script tests MECHANISM-BASED,
documented edges that are structurally different from per-symbol candle patterns:

  CANDIDATE 1: Cross-sectional (XS) momentum.
      Each rebalance, rank the 19-symbol universe by trailing N-day return.
      Long top-k / short bottom-k, hold M bars, rebalance every M bars.
      Documented crypto edge (Liu & Tsyvinski 2021 "Risks and Returns of Crypto";
      Hubrich 2017; Grobys & Sapkota 2019). Tradeable on bar-OHLCV.
      DECISIVE TEST: does the long-short spread have gross edge (shuffle p_gross<0.05)
      AND clear 55bps round-trip?

  CANDIDATE 2: Regime overlay diagnostic.
      Compute BTC regime (trend sign, vol tertile, breadth) on <=t-1 daily data.
      Report XS-momentum and a naive long-beta benchmark conditioned on regime, to
      see whether a regime gate would ADD risk-adjusted return or merely TRIM.
      (The champion VSA engine lives in protected files; we do NOT touch it. We
      characterise regime structure here and reason about the overlay from the
      existing champion_characterization.md, which already found the champion
      positive in ALL regimes.)

  CANDIDATE 3: Funding-rate carry — DATA-BLOCKED.
      data/market.duckdb has only (instruments, ohlcv). No funding table exists in
      any DB (market/market_ingest/forex). No persisted funding dataset. The prior
      funding hypothesis (memory/.../2026-05-08-funding-rate-mean-reversion.json) is
      marked NOT_EXECUTABLE for this exact reason. We report it blocked and do NOT
      fabricate any funding numbers.

LOOKAHEAD SAFETY (audited):
  - Ranking signal uses returns over [t-N .. t-1] (close[t-1]/close[t-1-N] - 1).
  - Positions formed at bar t are ENTERED at open[t] (the next bar's open after the
    signal bar t-1). PnL accrues open[t]->open[t+M] (next-open to next-open).
  - No shift(-1), no center=True, no same-bar peeking. Regime computed on shift(1).

FEES: 55 bps round-trip (conservative, matches deploy claim) AND 0 bps gross reported.
      Turnover-aware: fee charged only on the fraction of book that actually changes
      each rebalance (realistic — winners that stay top-k are not re-traded).

GATES (hard): shuffle p_gross<0.05, walk-forward positive months, MaxDD,
              calendar-day Sharpe (honest ann sqrt(365)), top-5% R-share concentration.

Usage:
  .venv/bin/python scripts/research/v2_new_edge_backtest.py
"""
from __future__ import annotations
import os, sys, json, hashlib, subprocess
from dataclasses import dataclass, asdict
from itertools import product
import numpy as np
import pandas as pd
import duckdb

DB = "data/market.duckdb"
VENUE = "binance"
TF = "1d"
UNIVERSE = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","ADA/USDT","AVAX/USDT",
            "LINK/USDT","DOT/USDT","DOGE/USDT","XRP/USDT","ZEC/USDT","NEAR/USDT",
            "FIL/USDT","XLM/USDT","TRX/USDT","UNI/USDT","ATOM/USDT","AAVE/USDT",
            "ALGO/USDT"]
FEE_BPS_RT = float(os.environ.get("PA_FEE_RT_BPS", "55.0"))  # round-trip, per side-change of notional (env-overridable)
SHUFFLE_SEEDS = 200
RNG_MASTER = 12345


def git_hash() -> str:
    try:
        return subprocess.check_output(["git","rev-parse","--short","HEAD"]).decode().strip()
    except Exception:
        return "nogit"


def load_panel() -> pd.DataFrame:
    """Return wide close & open DataFrames aligned on a common daily date index."""
    con = duckdb.connect(DB, read_only=True)
    frames = {}
    for s in UNIVERSE:
        df = con.execute(
            "select ts, open, close from ohlcv "
            "where venue=? and symbol=? and timeframe=? order by ts",
            [VENUE, s, TF]).fetchdf()
        df["date"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("UTC").dt.normalize()
        df = df.drop_duplicates("date").set_index("date")
        frames[s] = df[["open","close"]]
    con.close()
    closes = pd.DataFrame({s: frames[s]["close"] for s in UNIVERSE})
    opens  = pd.DataFrame({s: frames[s]["open"]  for s in UNIVERSE})
    # common, fully-aligned window (every symbol present). Drop rows with ANY NaN
    # so XS ranking is fair across the same universe each day (no survivorship of
    # late-listed names getting a free rank).
    both = closes.dropna(how="any")
    opens = opens.reindex(both.index)
    return both.sort_index(), opens.sort_index()


def calendar_day_sharpe(daily_ret: pd.Series) -> float:
    r = daily_ret.dropna()
    if len(r) < 5 or r.std(ddof=1) == 0:
        return float("nan")
    return float(r.mean() / r.std(ddof=1) * np.sqrt(365))


def max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    dd = equity/peak - 1.0
    return float(dd.min())


def monthly_stats(daily_ret: pd.Series):
    """Compound daily returns into calendar months."""
    if len(daily_ret) == 0:
        return 0, 0, float("nan"), float("nan")
    eq = (1.0 + daily_ret.fillna(0.0))
    m = eq.groupby([daily_ret.index.year, daily_ret.index.month]).prod() - 1.0
    n = len(m)
    pos = int((m > 0).sum())
    return n, pos, float(m.mean()), float(m.median())


@dataclass
class XSResult:
    N: int; k: int; M: int
    n_rebal: int
    gross_mean_R: float       # per-rebalance long-short spread return, 0bps
    net_mean_R: float         # after 55bps turnover-aware fees
    gross_total: float        # compounded gross
    net_total: float          # compounded net
    sharpe_gross: float
    sharpe_net: float
    maxdd_net: float
    wf_pos_months: int
    wf_tot_months: int
    top5_Rshare: float        # share of total |gross spread| from top 5% rebalances
    p_gross: float            # shuffle: P(shuffle spread mean >= real), one-sided
    turnover_mean: float


def xs_momentum(closes: pd.DataFrame, opens: pd.DataFrame,
                N: int, k: int, M: int, rng: np.random.Generator) -> XSResult:
    """
    Lookahead-safe XS momentum long-short.
    Signal at decision day d (index i): rank by ret = close[i-1]/close[i-1-N] - 1.
    Enter at open[i], exit at open[i+M]. Rebalance stride = M.
    """
    idx = closes.index
    c = closes.values
    o = opens.values
    nrows, nsym = c.shape

    # decision rows: need i-1-N >= 0 and i+M < nrows
    dec_rows = list(range(N+1, nrows - M, M))
    spread_rets = []          # per-rebalance long-short return (gross)
    net_rets = []
    turnovers = []
    dates = []
    prev_long = set(); prev_short = set()

    for i in dec_rows:
        sig = c[i-1] / c[i-1-N] - 1.0      # trailing N-day return through t-1
        if np.any(~np.isfinite(sig)):
            continue
        order = np.argsort(sig)            # ascending
        shorts = set(order[:k].tolist())
        longs = set(order[-k:].tolist())
        if longs & shorts:
            continue

        # per-symbol open-to-open hold return over [i .. i+M]
        hold = o[i+M] / o[i] - 1.0
        if np.any(~np.isfinite(hold)):
            continue
        long_ret = np.mean([hold[j] for j in longs])
        short_ret = np.mean([hold[j] for j in shorts])
        gross = long_ret - short_ret       # dollar-neutral long-short spread

        # turnover-aware fees: fraction of the 2k legs that changed vs previous book
        changed = len(longs ^ prev_long) + len(shorts ^ prev_short)
        total_legs = 2*k * 2  # entries+exits at full turnover would be 4k legs
        # turnover fraction in [0,1]: legs changed / max legs
        turn = changed / (2*k) if k > 0 else 0.0   # 0=no change,2=full flip both sides
        turn = min(turn, 2.0)
        # fee in return units: each fully-traded leg pays fee_bps/2 (one side).
        # round-trip already embedded by trading both entry now and exit later;
        # model: charge full round-trip on the changed fraction of the book.
        fee = (FEE_BPS_RT/1e4) * (turn/2.0)
        net = gross - fee

        spread_rets.append(gross)
        net_rets.append(net)
        turnovers.append(turn)
        dates.append(idx[i])
        prev_long, prev_short = longs, shorts

    if len(spread_rets) < 10:
        return XSResult(N,k,M,len(spread_rets),*([float('nan')]*9),0,0,float('nan'),float('nan'),float('nan'))

    sr = np.array(spread_rets); nr = np.array(net_rets)
    s_dates = pd.DatetimeIndex(dates)

    # per-rebalance returns -> convert to a daily-equivalent series for honest Sharpe
    # (each rebalance spans M days; spread the compounded return over M calendar days)
    daily_g = pd.Series(0.0, index=closes.index)
    daily_n = pd.Series(0.0, index=closes.index)
    for d, g, n in zip(dates, sr, nr):
        di = idx.get_loc(d)
        span = idx[di:di+M]
        if len(span) == 0:
            continue
        # geometric per-day allocation of the period return
        per_g = (1.0+g)**(1.0/M) - 1.0
        per_n = (1.0+n)**(1.0/M) - 1.0
        daily_g.loc[span] = per_g
        daily_n.loc[span] = per_n

    eq_g = np.cumprod(1.0+sr); eq_n = np.cumprod(1.0+nr)
    sh_g = calendar_day_sharpe(daily_g[daily_g != 0.0])
    sh_n = calendar_day_sharpe(daily_n[daily_n != 0.0])
    mdd_n = max_drawdown(eq_n)

    wf_tot, wf_pos, _, _ = monthly_stats(daily_n[daily_n != 0.0])

    # top-5% R-share (concentration): fraction of total gross PnL from top 5% rebalances
    absg = np.abs(sr)
    if sr.sum() != 0:
        k5 = max(1, int(np.ceil(0.05*len(sr))))
        top5 = np.sort(sr)[-k5:].sum()
        top5_share = float(top5 / sr.sum()) if sr.sum() > 0 else float('nan')
    else:
        top5_share = float('nan')

    # shuffle baseline: break the rank->forward-return link by permuting which symbols
    # are long/short each rebalance (random k-long / k-short, dollar neutral), keeping
    # the same forward-return matrix. Null = "random selection has no spread edge".
    real_mean = sr.mean()
    ge = 0
    # rebuild forward hold matrix for shuffle
    hold_mat = []
    for i in dec_rows:
        if i+M >= nrows: continue
        h = o[i+M]/o[i] - 1.0
        if np.all(np.isfinite(h)):
            hold_mat.append(h)
    hold_mat = np.array(hold_mat[:len(sr)])
    for _ in range(SHUFFLE_SEEDS):
        sh_spread = []
        for row in hold_mat:
            perm = rng.permutation(nsym)
            L = perm[:k]; S = perm[k:2*k]
            sh_spread.append(row[L].mean() - row[S].mean())
        if np.mean(sh_spread) >= real_mean:
            ge += 1
    p_gross = (ge+1)/(SHUFFLE_SEEDS+1)

    return XSResult(N,k,M,len(sr),
                    float(sr.mean()), float(nr.mean()),
                    float(eq_g[-1]-1), float(eq_n[-1]-1),
                    sh_g, sh_n, mdd_n, wf_pos, wf_tot,
                    top5_share, p_gross, float(np.mean(turnovers)))


def regime_diagnostic(closes: pd.DataFrame):
    """Characterise BTC regime on <=t-1 data and report XS-mom & long-beta by regime."""
    btc = closes["BTC/USDT"]
    ret = btc.pct_change()
    # trend: sign of 30d return through t-1 (shift(1) to avoid lookahead)
    trend30 = btc.pct_change(30).shift(1)
    # vol: 30d realized vol through t-1, tertile-bucketed
    vol30 = ret.rolling(30).std().shift(1)
    # breadth: fraction of universe above its own 30d-ago close, through t-1
    breadth = (closes > closes.shift(30)).mean(axis=1).shift(1)

    df = pd.DataFrame({"ret": ret, "trend30": trend30, "vol30": vol30, "breadth": breadth}).dropna()
    out = {}
    # BTC next-day return conditioned on regime (long-beta benchmark, lookahead-safe)
    df["btc_fwd"] = btc.pct_change().reindex(df.index)
    df["trend_sign"] = np.where(df["trend30"] > 0, "up", "down")
    vt = df["vol30"].quantile([1/3, 2/3])
    df["vol_bucket"] = np.where(df["vol30"] <= vt.iloc[0], "lo",
                       np.where(df["vol30"] <= vt.iloc[1], "mid", "hi"))
    by_trend = df.groupby("trend_sign")["btc_fwd"].agg(["mean","count"])
    by_vol = df.groupby("vol_bucket")["btc_fwd"].agg(["mean","count"])
    out["btc_fwd_by_trend"] = by_trend.to_dict("index")
    out["btc_fwd_by_vol"] = by_vol.to_dict("index")
    return out


def main():
    print(f"# v2 NEW EDGE backtest  git={git_hash()}  TF={TF}  syms={len(UNIVERSE)}")
    closes, opens = load_panel()
    dh = hashlib.md5(pd.util.hash_pandas_object(closes).values.tobytes()).hexdigest()[:10]
    print(f"# aligned daily rows={len(closes)}  {closes.index[0].date()}->{closes.index[-1].date()}  data_hash={dh}")

    # ---------- CANDIDATE 1: XS momentum sweep ----------
    Ns = [7, 14, 30]
    ks = [2, 3, 4]
    Ms = [3, 7, 14]
    results = []
    for N, k, M in product(Ns, ks, Ms):
        rng = np.random.default_rng(RNG_MASTER + N*1000 + k*100 + M)
        r = xs_momentum(closes, opens, N, k, M, rng)
        results.append(r)
        print(f"  XS N={N:2d} k={k} M={M:2d} | n={r.n_rebal:4d} "
              f"gR={r.gross_mean_R:+.4f} nR={r.net_mean_R:+.4f} "
              f"shN={r.sharpe_net:+.2f} DD={r.maxdd_net:+.1%} "
              f"WF={r.wf_pos_months}/{r.wf_tot_months} top5={r.top5_Rshare:.2f} "
              f"p_g={r.p_gross:.3f} turn={r.turnover_mean:.2f}")

    n_configs = len(results)
    # Multiple-testing: Benjamini-Hochberg on p_gross across all configs
    pvals = sorted([(r.p_gross, i) for i, r in enumerate(results)])
    bh = {}
    for rank, (p, i) in enumerate(pvals, start=1):
        bh[i] = min(1.0, p * n_configs / rank)  # BH-adjusted
    print(f"\n# Multiple-testing: {n_configs} configs tested. BH-FDR adjustment applied.")

    # ---------- CANDIDATE 2: regime diagnostic ----------
    reg = regime_diagnostic(closes)

    payload = {
        "git": git_hash(), "data_hash": dh, "tf": TF, "universe_n": len(UNIVERSE),
        "rows": len(closes), "date_start": str(closes.index[0].date()),
        "date_end": str(closes.index[-1].date()),
        "fee_bps_rt": FEE_BPS_RT, "shuffle_seeds": SHUFFLE_SEEDS,
        "xs_results": [
            {**asdict(r), "bh_adj_p": bh[i]} for i, r in enumerate(results)
        ],
        "regime_diagnostic": reg,
        "candidate3_funding": "DATA_BLOCKED: no funding table in any DB; not fabricated.",
    }
    out_json = "data/_v2_new_edge_results.json"
    with open(out_json, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\n# wrote {out_json}")


if __name__ == "__main__":
    main()
