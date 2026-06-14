"""v6 — FUNDING-RATE crypto edge: deployable diversifier to stack on VSA-WIDESTOP champion?

CRYPTO-ONLY path to consistent ~15%/mo at low DD (forex dropped). Brutally honest.

Two mechanisms, SAME hard gates:
  M1  Funding MEAN-REVERSION  — fade EXTREME funding (crowded longs short / squeeze long).
                                Contrarian -> likely low-corr to champion.
  M2  Cross-sectional CARRY (DOLLAR-NEUTRAL) — long lowest-funding / short highest-funding.
                                Feynman: prove neutral spread > equal-weight-long-all (long-beta) BENCHMARK.

Gates (decisive):
  - Lookahead-safe join: 1d bar at ts=T uses prior-day 16:00 UTC settlement = f.ts = o.ts - 8h.
    Decision on <= t-1 settled funding; entry NEXT open.
  - Realistic fees: 55 bps round-trip per perp leg; carry fee/turnover-adjusted.
  - Shuffle p_gross < 0.05.
  - Walk-forward positive months; calendar-day Sharpe (honest, ann sqrt(365)); MaxDD; top-5% R-share.
  - rho_daily to live champion vsa_climax_test (widestop) < 0.30 to be a diversifier.

If both fail shuffle OR collapse to long-beta -> say so cleanly. No p-hacking.

Repro: .venv/bin/python scripts/research/v6_funding_edge.py
"""
from __future__ import annotations
import io, os, sys, math, pickle, subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ["PA_LOG_QUIET"] = "1"
os.environ["PA_DUCKDB_READ_ONLY"] = "true"
import warnings; warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import duckdb

ROOT = Path(__file__).resolve().parents[2]
SEED = 12345
np.random.seed(SEED)
GIT = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                     capture_output=True, text=True).stdout.strip()

FUND_DB = str(ROOT / "data" / "funding.duckdb")
MKT_DB = str(ROOT / "data" / "market.duckdb")
CHAMP_PKL = str(ROOT / "data" / "sec53_15m_pool_v11.pkl")

SYMS = ["BNB", "SOL", "TRX", "ATOM", "DOT", "AVAX", "ZEC", "NEAR", "BTC", "ADA",
        "ETH", "XLM", "ALGO", "FIL", "DOGE", "XRP", "AAVE", "UNI", "LINK"]
FEE_RT = float(os.environ.get("PA_FEE_RT_BPS", "55.0")) / 10000.0  # round-trip, price fraction (env-overridable)
N_SHUF = 5000


# ---------------------------------------------------------------------------
def stats(series):
    """Monthly-pct series -> dist stats (mirror portfolio_leverage_15pct.stats)."""
    a = np.array(series, dtype=float)
    if len(a) == 0:
        return dict(n=0, mean=0, med=0, sd=0, sharpe_m=0, sharpe_ann=0, neg=0, maxdd=0, ann=0, mn=0, pos=0)
    mean = a.mean(); med = float(np.median(a)); sd = a.std(ddof=1) if len(a) > 1 else 0.0
    sharpe_m = mean / sd if sd > 0 else 0.0
    eq = np.cumprod(1 + a / 100.0); peak = np.maximum.accumulate(eq)
    dd = (eq / peak - 1.0).min() * 100.0
    ann = (eq[-1] ** (12.0 / len(a)) - 1.0) * 100.0 if eq[-1] > 0 else -100.0
    neg = int((a < 0).sum())
    return dict(n=len(a), mean=mean, med=med, sd=sd, sharpe_m=sharpe_m,
                sharpe_ann=sharpe_m * math.sqrt(12), neg=neg, pos=len(a) - neg,
                maxdd=dd, ann=ann, mn=float(a.min()))


def cal_sharpe(daily_ret):
    """Honest calendar-day Sharpe, ann sqrt(365), on a daily return (fraction) series."""
    a = np.array(daily_ret, dtype=float)
    if len(a) < 2 or a.std(ddof=1) == 0:
        return 0.0
    return float(a.mean() / a.std(ddof=1) * math.sqrt(365))


def shuffle_p(daily_pnl):
    """Sign-flip shuffle null on a daily PnL series. p = P(null mean >= observed)."""
    a = np.array(daily_pnl, dtype=float)
    if len(a) == 0:
        return 1.0
    obs = a.mean(); absA = np.abs(a)
    rng = np.random.default_rng(SEED); cnt = 0
    for _ in range(N_SHUF):
        if (absA * rng.choice([-1.0, 1.0], size=len(a))).mean() >= obs:
            cnt += 1
    return (cnt + 1) / (N_SHUF + 1)


def top5_share(pnl):
    """Share of total POSITIVE pnl held by the top-5% of positive observations."""
    a = np.array(pnl, dtype=float); w = a[a > 0]
    if len(w) == 0:
        return float("nan")
    k = max(1, int(math.ceil(0.05 * len(w))))
    return float(np.sort(w)[-k:].sum() / w.sum())


def daily_to_monthly_pct(daily_ret_by_date):
    """date->daily fractional return -> month->compounded pct. Equity-reset monthly."""
    s = pd.Series(daily_ret_by_date).sort_index()
    s.index = pd.to_datetime(s.index)
    out = {}
    for ym, grp in s.groupby(s.index.to_period("M")):
        out[str(ym)] = (np.prod(1.0 + grp.values) - 1.0) * 100.0
    return out


# ---------------------------------------------------------------------------
# DATA
# ---------------------------------------------------------------------------
def load_funding():
    c = duckdb.connect(FUND_DB, read_only=True)
    df = c.execute("SELECT symbol, ts, funding_rate FROM funding_rates ORDER BY symbol, ts").fetchdf()
    c.close()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def load_ohlcv_1d():
    c = duckdb.connect(MKT_DB, read_only=True)
    fulls = [f"{s}/USDT:USDT" for s in SYMS]
    df = c.execute(
        "SELECT symbol, ts, open, high, low, close FROM ohlcv "
        "WHERE timeframe='1d' AND venue='binance' AND symbol IN ("
        + ",".join(["?"] * len(fulls)) + ") ORDER BY symbol, ts", fulls).fetchdf()
    c.close()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["sym"] = df["symbol"].str.replace("/USDT:USDT", "", regex=False)
    return df


def build_panel():
    """Lookahead-safe daily panel per symbol with prior-day 16:00 UTC funding attached.

    For a 1d bar opening at ts=T (00:00 UTC), the join uses the funding settlement at
    f.ts = T - 8h = prior day 16:00 UTC, which is fully observed before the bar opens.
    We attach NEXT bar's open/high/low/close as the tradeable execution (entry next open).
    """
    fund = load_funding()
    ohlc = load_ohlcv_1d()
    panels = {}
    for s in SYMS:
        o = ohlc[ohlc["sym"] == s].sort_values("ts").reset_index(drop=True).copy()
        f = fund[fund["symbol"] == s].sort_values("ts").reset_index(drop=True).copy()
        if len(o) < 30 or len(f) < 30:
            continue
        # normalize bar ts to 00:00 UTC date key
        o["date"] = o["ts"].dt.floor("D")
        # the settlement we are allowed to use to decide a trade at bar date D's open
        # = funding at D - 8h (prior day 16:00 UTC). Map each funding ts to the bar
        # date it informs: bar_date = (f.ts + 8h).floor('D')
        f["bar_date"] = (f["ts"] + pd.Timedelta(hours=8)).dt.floor("D")
        # there can be multiple settlements per day; the 16:00 one maps to next 00:00 bar.
        # keep the funding settlement whose hour==16 UTC (the one exactly t-8h from 00:00 open)
        f16 = f[f["ts"].dt.hour == 16].copy()
        fmap = f16.groupby("bar_date")["funding_rate"].last()
        o = o.set_index("date")
        o["funding"] = fmap.reindex(o.index)
        o = o.reset_index()
        o = o.dropna(subset=["funding"]).reset_index(drop=True)
        if len(o) < 60:
            continue
        # next-open execution columns (entry at next bar open after decision bar)
        o["next_open"] = o["open"].shift(-1)
        o["next_high"] = o["high"].shift(-1)
        o["next_low"] = o["low"].shift(-1)
        o["next_close"] = o["close"].shift(-1)
        o["next_date"] = o["date"].shift(-1)
        panels[s] = o
    return panels, fund


# ---------------------------------------------------------------------------
# M1 — FUNDING MEAN-REVERSION (fade extreme funding)
# ---------------------------------------------------------------------------
def m1_signals(panels, q_hi, lookback, hold, atr_stop_mult=2.0):
    """Per symbol: rolling quantile of trailing funding. If today's settled funding
    (the t-1, lookahead-safe value) > trailing q_hi -> crowded longs -> SHORT next open.
    < trailing (1-q_hi) -> crowded shorts / squeeze -> LONG next open.
    Exit: after `hold` bars OR funding normalizes back inside [25,75] band of trailing.
    R measured vs an ATR(14)-based stop (price-move / stop-distance); 55bps fee charged.
    Returns list of trade dicts with realized R and exit date."""
    trades = []
    for s, o in panels.items():
        df = o.copy()
        df["atr"] = (df["high"] - df["low"]).rolling(14).mean()
        # trailing distribution of funding (uses only past values incl. current settled)
        fr = df["funding"]
        hi = fr.rolling(lookback, min_periods=max(20, lookback // 3)).quantile(q_hi)
        lo = fr.rolling(lookback, min_periods=max(20, lookback // 3)).quantile(1 - q_hi)
        med_hi = fr.rolling(lookback, min_periods=20).quantile(0.75)
        med_lo = fr.rolling(lookback, min_periods=20).quantile(0.25)
        n = len(df)
        i = 0
        last_exit_idx = -1
        while i < n - 1:
            if i <= last_exit_idx or pd.isna(hi.iloc[i]) or pd.isna(df["atr"].iloc[i]):
                i += 1; continue
            side = None
            if fr.iloc[i] > hi.iloc[i]:
                side = "short"
            elif fr.iloc[i] < lo.iloc[i]:
                side = "long"
            if side is None:
                i += 1; continue
            entry = df["next_open"].iloc[i]
            if pd.isna(entry) or entry <= 0:
                i += 1; continue
            stop_dist = atr_stop_mult * df["atr"].iloc[i]
            if not (stop_dist > 0):
                i += 1; continue
            # walk forward bars; entry executes at bar i+1 open, so j starts at i+1
            exit_idx = min(i + hold, n - 1)
            for j in range(i + 1, min(i + 1 + hold, n)):
                # funding normalized? exit at this bar's open (decision known at j-? )
                # we exit on hold or on normalization observed at bar j-1 funding -> exit j open
                if j - 1 >= 0 and not pd.isna(med_hi.iloc[j - 1]):
                    norm = (med_lo.iloc[j - 1] <= fr.iloc[j - 1] <= med_hi.iloc[j - 1])
                    if norm and j > i + 1:
                        exit_idx = j; break
                exit_idx = j
            ex_price = df["open"].iloc[exit_idx] if exit_idx > i else df["next_close"].iloc[i]
            if pd.isna(ex_price) or ex_price <= 0:
                i += 1; continue
            if side == "short":
                gross = (entry - ex_price) / stop_dist
            else:
                gross = (ex_price - entry) / stop_dist
            fee_R = (FEE_RT * entry) / stop_dist  # round-trip fee in R units
            R = gross - fee_R
            ex_date = df["date"].iloc[exit_idx]
            trades.append(dict(sym=s, side=side, entry_idx=i, exit_idx=exit_idx,
                               R=float(R), gross=float(gross), fee_R=float(fee_R),
                               exit_date=pd.Timestamp(ex_date), entry_date=pd.Timestamp(df["next_date"].iloc[i])
                               if not pd.isna(df["next_date"].iloc[i]) else pd.Timestamp(df["date"].iloc[i])))
            last_exit_idx = exit_idx
            i = exit_idx + 1
    return trades


def m1_daily_R(trades):
    """Aggregate realized R per calendar day (attributed at exit) -> date->R."""
    d = {}
    for t in trades:
        k = t["exit_date"].normalize()
        d[k] = d.get(k, 0.0) + t["R"]
    return d


# ---------------------------------------------------------------------------
# M2 — CROSS-SECTIONAL CARRY (dollar-neutral) + long-beta Feynman benchmark
# ---------------------------------------------------------------------------
def m2_panel_matrix(panels, exclude=("BNB",), winsor=("SOL",)):
    """Build aligned daily matrices: funding (decision, t-1 safe) and next-day return.
    next-day return = (next_close/next_open - 1) executed at next open (lookahead-safe)."""
    syms = [s for s in panels if s not in exclude]
    # collect per-symbol series indexed by decision-bar date
    fr_cols, ret_cols = {}, {}
    for s in syms:
        df = panels[s].copy()
        df = df.set_index("date")
        fr = df["funding"].copy()
        # realized next-day return of holding from next_open to next_close (the executable bar)
        ret = (df["next_close"] / df["next_open"] - 1.0)
        if s in winsor:
            pass  # winsorization applied at cross-section rank time (rank is robust); keep raw ret
        fr_cols[s] = fr; ret_cols[s] = ret
    FR = pd.DataFrame(fr_cols); RET = pd.DataFrame(ret_cols)
    common = FR.dropna(how="all").index.intersection(RET.dropna(how="all").index)
    FR = FR.loc[common]; RET = RET.loc[common]
    return FR.sort_index(), RET.sort_index(), syms


def m2_carry(FR, RET, k_frac=0.3, fee_rt=FEE_RT):
    """Each day rank symbols by t-1 settled funding. SHORT top (highest funding),
    LONG bottom (lowest). Dollar-neutral, equal weight within each leg. Hold 1 bar
    (next open->next close). Fee charged on legs that turn over (approx: full RT each
    rebalance day on the names that change side). Returns:
       neutral_daily : date->net fractional return (dollar-neutral spread)
       bench_daily   : date->equal-weight LONG-ALL benchmark (the long-beta check)
       turnover stats
    Carry collected: the realized funding paid/received over the hold is the funding at
    settlement during the hold; here next-day return ALREADY excludes funding, so we ADD
    the carry leg: short pays-receives -funding*notional, long receives funding.
    To be conservative we model carry = +funding for shorts on positive funding (they
    receive), -funding for longs (they pay). This is the actual cashflow that motivates
    the trade. 8h settlement x up-to-3 per day; we apply 1 settlement (t-1) per day held.
    """
    dates = FR.index
    neutral, bench = {}, {}
    prev_long, prev_short = set(), set()
    turnovers = []
    for d in dates:
        fr_row = FR.loc[d].dropna()
        ret_row = RET.loc[d].dropna()
        common = fr_row.index.intersection(ret_row.index)
        if len(common) < 6:
            continue
        fr_row = fr_row[common]; ret_row = ret_row[common]
        k = max(1, int(round(k_frac * len(common))))
        ranked = fr_row.sort_values()
        longs = list(ranked.index[:k])      # lowest funding -> long
        shorts = list(ranked.index[-k:])    # highest funding -> short
        # price PnL (dollar-neutral): +mean(long ret) - mean(short ret)
        long_ret = ret_row[longs].mean()
        short_ret = ret_row[shorts].mean()
        price_pnl = 0.5 * long_ret - 0.5 * short_ret   # half capital each leg, dollar-neutral
        # carry leg (the actual motivation): shorts RECEIVE funding (paid by longs in market);
        # our shorts on HIGH positive funding receive +funding; our longs on LOW/neg funding
        # pay funding (i.e. receive -funding). One t-1 settlement per held day.
        carry = 0.5 * (fr_row[shorts].mean()) - 0.5 * (fr_row[longs].mean())
        # fee: names entering/leaving a leg pay one side. Capital = 100%, split equally
        # across the 2k held names (k long + k short), so each name carries 1/(2k) of
        # capital. A churned name pays one side = 0.5*round-trip on its 1/(2k) slice.
        cur_long, cur_short = set(longs), set(shorts)
        churn = len(cur_long ^ prev_long) + len(cur_short ^ prev_short)
        fee = (churn / (2 * k)) * 0.5 * fee_rt if k else 0.0
        turnovers.append(churn / (2 * k) if k else 0)
        neutral[d] = float(price_pnl + carry - fee)
        prev_long, prev_short = cur_long, cur_short
        # benchmark: equal-weight LONG ALL names (the long-beta in costume)
        bench[d] = float(ret_row.mean())
    return neutral, bench, float(np.mean(turnovers)) if turnovers else 0.0


# ---------------------------------------------------------------------------
# CHAMPION daily PnL (for rho gate) — vsa_climax_test widestop, R per exit-day.
# ---------------------------------------------------------------------------
def champion_daily_R():
    with open(CHAMP_PKL, "rb") as f:
        pool = pickle.load(f)
    df = pd.DataFrame(pool)
    v = df[df["strategy"] == "vsa_climax_test"].copy()
    ep = v["entry_price"].astype(float); sp = v["initial_sl"].astype(float)
    v["slp"] = (ep - sp).abs() / ep.replace(0, np.nan)
    ws = v[v["slp"] >= 0.025].copy()
    ws["exit_ts"] = pd.to_datetime(ws["exit_ts"], utc=True)
    ws["d"] = ws["exit_ts"].dt.floor("D")
    daily = ws.groupby("d")["R"].sum()
    return {pd.Timestamp(k).normalize(): float(v) for k, v in daily.items()}


def rho_daily(a_daily, b_daily):
    """Pearson rho of two date->value daily series on the common dates (0-fill the
    union so non-trading days count as flat for BOTH — the honest portfolio view)."""
    idx = sorted(set(a_daily) | set(b_daily))
    a = np.array([a_daily.get(d, 0.0) for d in idx])
    b = np.array([b_daily.get(d, 0.0) for d in idx])
    # restrict to span where champion is active (avoid spurious 0-0 correlation tails)
    cdates = sorted(b_daily)
    if not cdates:
        return float("nan"), 0
    lo, hi = cdates[0], cdates[-1]
    mask = np.array([(lo <= d <= hi) for d in idx])
    a, b = a[mask], b[mask]
    if len(a) < 10 or a.std() == 0 or b.std() == 0:
        return float("nan"), len(a)
    return float(np.corrcoef(a, b)[0, 1]), len(a)


# ---------------------------------------------------------------------------
def r_series_to_daily_ret(daily_R, risk_pct=0.005):
    """Convert date->R to date->fractional return at risk_pct per R (for monthly/Sharpe)."""
    return {d: r * risk_pct for d, r in daily_R.items()}


def main():
    print(f"git={GIT} seed={SEED}  fee_rt=55bps  join: f.ts = o.ts - 8h (prior-day 16:00 UTC)")
    print("=" * 90)
    panels, fund = build_panel()
    print(f"panel: {len(panels)} symbols with lookahead-safe funding-attached 1d bars")

    champ_d = champion_daily_R()
    cd = sorted(champ_d)
    print(f"champion(vsa_climax widestop) daily-R series: {len(champ_d)} active days "
          f"{cd[0].date()}..{cd[-1].date()}  sumR={sum(champ_d.values()):+.0f}")

    # =========================================================================
    # M1 — FUNDING MEAN-REVERSION (threshold sweep + multiple-testing correction)
    # =========================================================================
    print("\n" + "=" * 90)
    print("[M1] FUNDING MEAN-REVERSION (fade extreme funding)")
    print("=" * 90)
    grid = []
    for q_hi in (0.80, 0.85, 0.90, 0.95):
        for lookback in (60, 90, 180):
            for hold in (2, 3, 5):
                grid.append((q_hi, lookback, hold))
    print(f"sweep {len(grid)} configs (q_hi x lookback x hold)")
    print(f"  {'q_hi':>5} {'lb':>4} {'hold':>4} {'n':>5} {'meanR':>7} {'sumR':>8} "
          f"{'win%':>6} {'Sh_cal':>7} {'p_shuf':>7} {'mo_mean':>8} {'mo_pos':>7} {'maxDD':>7}")
    m1_results = []
    for (q_hi, lookback, hold) in grid:
        trades = m1_signals(panels, q_hi, lookback, hold)
        if len(trades) < 30:
            continue
        dR = m1_daily_R(trades)
        dret = r_series_to_daily_ret(dR)
        # build a contiguous daily series across active span for Sharpe/shuffle
        days = sorted(dR)
        pnl = [dR[d] for d in days]
        sh = cal_sharpe([dret[d] for d in days])
        p = shuffle_p(pnl)
        mo = daily_to_monthly_pct(dret)
        ms = stats(list(mo.values()))
        Rsum = sum(pnl); Rmean = np.mean([t["R"] for t in trades]); win = np.mean([t["R"] > 0 for t in trades])
        m1_results.append(dict(q_hi=q_hi, lb=lookback, hold=hold, n=len(trades), meanR=Rmean,
                               sumR=Rsum, win=win, sh=sh, p=p, mo=mo, ms=ms, dR=dR, trades=trades))
        print(f"  {q_hi:>5.2f} {lookback:>4} {hold:>4} {len(trades):>5} {Rmean:>+7.3f} "
              f"{Rsum:>+8.1f} {win*100:>5.1f}% {sh:>+7.2f} {p:>7.4f} {ms['mean']:>+8.2f} "
              f"{ms['pos']}/{ms['n']:<3} {ms['maxdd']:>7.1f}")

    # multiple-testing correction (Benjamini-Hochberg across the sweep)
    if m1_results:
        ps = sorted([(r["p"], r) for r in m1_results], key=lambda x: x[0])
        m = len(ps); bh_pass = []
        for rank, (p, r) in enumerate(ps, 1):
            thr = 0.05 * rank / m
            r["bh_thr"] = thr; r["bh_pass"] = p <= thr
            if p <= thr:
                bh_pass.append(r)
        best = max(m1_results, key=lambda r: r["sh"])
        print(f"\n  BH(FDR=0.05) across {m} configs: {len(bh_pass)} survive correction")
        print(f"  best-by-Sharpe: q_hi={best['q_hi']} lb={best['lb']} hold={best['hold']} "
              f"-> meanR {best['meanR']:+.3f} Sh {best['sh']:+.2f} p={best['p']:.4f} "
              f"BH_pass={best.get('bh_pass')} mo_mean {best['ms']['mean']:+.2f}% "
              f"pos {best['ms']['pos']}/{best['ms']['n']}")
        # rho to champion for the best config
        r1, n1 = rho_daily(best["dR"], champ_d)
        print(f"  rho_daily(M1_best, champion) = {r1:+.3f}  (n={n1} common days)")
        # walk-forward: per-year monthly mean
        by_year = {}
        for ym, v in best["mo"].items():
            by_year.setdefault(ym[:4], []).append(v)
        wf = {y: float(np.mean(vs)) for y, vs in sorted(by_year.items())}
        print(f"  walk-forward (per-year mean %/mo): " + "  ".join(f"{y}:{v:+.2f}" for y, v in wf.items()))
        print(f"  top-5% R-share: {top5_share([t['R'] for t in best['trades']]):.3f}")
        m1_best = best; m1_rho = r1
    else:
        m1_best = None; m1_rho = float("nan")
        print("  M1: no config produced >=30 trades.")

    # =========================================================================
    # M2 — CROSS-SECTIONAL CARRY (dollar-neutral) + Feynman long-beta check
    # =========================================================================
    print("\n" + "=" * 90)
    print("[M2] CROSS-SECTIONAL CARRY (dollar-neutral) — exclude BNB, SOL kept (rank-robust)")
    print("=" * 90)
    FR, RET, syms = m2_panel_matrix(panels, exclude=("BNB",))
    print(f"matrix: {len(syms)} symbols, {len(FR)} aligned days "
          f"{FR.index[0].date()}..{FR.index[-1].date()}")
    print(f"  {'k_frac':>6} {'days':>5} {'mean_bps':>9} {'Sh_cal':>7} {'p_shuf':>7} "
          f"{'mo_mean':>8} {'mo_pos':>7} {'maxDD':>7} {'turn':>6}")
    m2_results = []
    for k_frac in (0.2, 0.3, 0.4, 0.5):
        neutral, bench, turn = m2_carry(FR, RET, k_frac=k_frac)
        days = sorted(neutral)
        pnl = [neutral[d] for d in days]
        sh = cal_sharpe(pnl)
        p = shuffle_p(pnl)
        mo = daily_to_monthly_pct({d: neutral[d] for d in days})
        ms = stats(list(mo.values()))
        m2_results.append(dict(k_frac=k_frac, neutral=neutral, bench=bench, turn=turn,
                               sh=sh, p=p, mo=mo, ms=ms, mean_bps=np.mean(pnl) * 10000))
        print(f"  {k_frac:>6.2f} {len(days):>5} {np.mean(pnl)*10000:>+9.3f} {sh:>+7.2f} "
              f"{p:>7.4f} {ms['mean']:>+8.2f} {ms['pos']}/{ms['n']:<3} "
              f"{ms['maxdd']:>7.1f} {turn:>6.2f}")

    # Feynman: neutral spread vs equal-weight-long-all benchmark
    print("\n  FEYNMAN long-beta check — neutral SPREAD vs equal-weight-LONG-ALL benchmark:")
    best2 = max(m2_results, key=lambda r: r["sh"])
    bench_days = sorted(best2["bench"])
    bench_pnl = [best2["bench"][d] for d in bench_days]
    bench_sh = cal_sharpe(bench_pnl)
    neut_days = sorted(best2["neutral"])
    neut_pnl = [best2["neutral"][d] for d in neut_days]
    # correlation of neutral spread to the long-all benchmark
    common_d = sorted(set(neut_days) & set(bench_days))
    na = np.array([best2["neutral"][d] for d in common_d])
    ba = np.array([best2["bench"][d] for d in common_d])
    rho_nb = float(np.corrcoef(na, ba)[0, 1]) if len(common_d) > 10 and na.std() > 0 else float("nan")
    print(f"    neutral spread (k={best2['k_frac']}): mean {np.mean(neut_pnl)*10000:+.3f} bps/day, "
          f"Sh_cal {best2['sh']:+.2f}, p_shuf {best2['p']:.4f}")
    print(f"    long-all benchmark:                    mean {np.mean(bench_pnl)*10000:+.3f} bps/day, "
          f"Sh_cal {bench_sh:+.2f}")
    print(f"    rho(neutral, long-all) = {rho_nb:+.3f}  "
          f"-> {'ALPHA (decoupled from beta)' if abs(rho_nb) < 0.5 else 'LONG-BETA IN COSTUME (reject if neutral~=bench)'}")
    print(f"    edge-beyond-beta: neutral Sh {best2['sh']:+.2f} vs bench Sh {bench_sh:+.2f}  "
          f"-> {'neutral wins' if best2['sh'] > bench_sh else 'NEUTRAL DOES NOT BEAT BETA'}")
    r2, n2 = rho_daily(best2["neutral"], champ_d)
    print(f"    rho_daily(M2_best_neutral, champion) = {r2:+.3f}  (n={n2} common days)")
    by_year2 = {}
    for ym, v in best2["mo"].items():
        by_year2.setdefault(ym[:4], []).append(v)
    wf2 = {y: float(np.mean(vs)) for y, vs in sorted(by_year2.items())}
    print(f"    walk-forward (per-year mean %/mo): " + "  ".join(f"{y}:{v:+.2f}" for y, v in wf2.items()))

    # =========================================================================
    # PORTFOLIO TEST (only if a mechanism passes shuffle AND is low-corr AND real)
    # =========================================================================
    print("\n" + "=" * 90)
    print("[PORTFOLIO] champion-alone vs champion+funding (crypto-only)")
    print("=" * 90)

    champ_mo = daily_to_monthly_pct(r_series_to_daily_ret(champ_d))
    sc = stats(list(champ_mo.values()))
    print(f"  champion monthly: n={sc['n']} mean {sc['mean']:+.2f}% sd {sc['sd']:.2f} "
          f"Sh_ann {sc['sharpe_ann']:+.2f} maxDD {sc['maxdd']:.1f}% pos {sc['pos']}/{sc['n']}")

    def portfolio_eval(name, mech_mo, mech_dR, mech_rho, mech_pass):
        if mech_mo is None:
            print(f"  {name}: no edge -> skip portfolio."); return
        common = sorted(set(champ_mo) & set(mech_mo))
        if len(common) < 6:
            print(f"  {name}: <6 overlapping months -> skip."); return
        cx = np.array([champ_mo[m] for m in common])
        mx = np.array([mech_mo[m] for m in common])
        rho_m = float(np.corrcoef(cx, mx)[0, 1]) if cx.std() > 0 and mx.std() > 0 else float("nan")
        sc_o = stats(list(cx)); sm_o = stats(list(mx))
        print(f"\n  --- {name} ---")
        print(f"  overlap {len(common)} mo. rho_monthly {rho_m:+.3f}  rho_daily {mech_rho:+.3f}")
        print(f"  champ(ovlp) mean {sc_o['mean']:+.2f}% sd {sc_o['sd']:.2f} Sh {sc_o['sharpe_ann']:+.2f}")
        print(f"  {name}(ovlp) mean {sm_o['mean']:+.2f}% sd {sm_o['sd']:.2f} Sh {sm_o['sharpe_ann']:+.2f}")
        if not mech_pass:
            print(f"  -> {name} FAILED gates (shuffle/beta/corr); not a deployable diversifier. No lever calc.")
            return
        # vol-match mech to champ vol, sweep blend for max Sharpe
        k = sc_o["sd"] / sm_o["sd"] if sm_o["sd"] > 0 else 0.0
        mx_s = mx * k
        vbest = None
        for w in np.arange(0.0, 1.01, 0.05):
            port = w * cx + (1 - w) * mx_s; sp = stats(list(port))
            if vbest is None or sp["sharpe_ann"] > vbest[1]["sharpe_ann"]:
                vbest = (w, sp, port)
        w_ch, pstat, port_base = vbest
        print(f"  vol-matched MAX-Sharpe blend: w_champ={w_ch:.2f} -> mean {pstat['mean']:+.2f}% "
              f"sd {pstat['sd']:.2f} Sh {pstat['sharpe_ann']:+.2f} maxDD {pstat['maxdd']:.1f}% "
              f"pos {pstat['pos']}/{pstat['n']}")
        # lever to 15%/mo
        m = pstat["mean"]
        if m > 0:
            L = min(10.0, 15.0 / m); lev = port_base * L; ls = stats(list(lev))
            print(f"  LEVER to 15%/mo: L={L:.2f}x -> mean {ls['mean']:+.2f}% median {ls['med']:+.2f}% "
                  f"sd {ls['sd']:.2f} maxDD {ls['maxdd']:.1f}% min {ls['mn']:+.2f}% "
                  f"pos {ls['pos']}/{ls['n']} ({(ls['pos']/ls['n']*100):.0f}%)")
        # champion alone to 15%
        Lc = min(10.0, 15.0 / sc_o["mean"]) if sc_o["mean"] > 0 else 0
        levc = cx * Lc; lcs = stats(list(levc))
        print(f"  champ-ALONE to 15%/mo: L={Lc:.2f}x -> maxDD {lcs['maxdd']:.1f}% min {lcs['mn']:+.2f}% "
              f"pos {lcs['pos']}/{lcs['n']} ({(lcs['pos']/lcs['n']*100):.0f}%)")

    # gate verdicts
    m1_pass = bool(m1_best and m1_best["p"] < 0.05 and m1_best.get("bh_pass")
                   and abs(m1_rho) < 0.30 and m1_best["sh"] > 0.5)
    m2_pass = bool(best2["p"] < 0.05 and best2["sh"] > bench_sh and abs(rho_nb) < 0.5
                   and abs(r2) < 0.30 and best2["sh"] > 0.5)

    portfolio_eval("M1_meanrev", m1_best["mo"] if m1_best else None,
                   m1_best["dR"] if m1_best else None, m1_rho, m1_pass)
    portfolio_eval("M2_carry_neutral", best2["mo"], best2["neutral"], r2, m2_pass)

    print("\n" + "=" * 90)
    print("[VERDICT GATES]")
    print(f"  M1 mean-rev: shuffle_p={m1_best['p']:.4f} BH_pass={m1_best.get('bh_pass') if m1_best else None} "
          f"Sh_cal={m1_best['sh']:+.2f} rho_daily={m1_rho:+.3f} -> PASS={m1_pass}" if m1_best else "  M1: no edge")
    print(f"  M2 carry:    shuffle_p={best2['p']:.4f} neutral_Sh={best2['sh']:+.2f} bench_Sh={bench_sh:+.2f} "
          f"rho(neut,bench)={rho_nb:+.3f} rho_daily={r2:+.3f} -> PASS={m2_pass}")
    return dict(m1_best=m1_best, m1_rho=m1_rho, m1_pass=m1_pass,
                m2_best=best2, rho_nb=rho_nb, bench_sh=bench_sh, r2=r2, m2_pass=m2_pass,
                champ_stats=sc)


if __name__ == "__main__":
    main()
