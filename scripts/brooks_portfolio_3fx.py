"""brooks_failed_breakout 3-FX PORTFOLIO (EUR/USD, GBP/USD, USD/JPY 4H).

Reuses scripts/forex_4h_research.gather() VERBATIM per symbol (same pre-reg
filters: session 07-16 UTC, weekend-flat, swap haircut, slippage 1.0bps, fee 0,
atr_min_pct, sl_pct_min 0). brooks is R-multiple based => JPY pip scale is
naturally normalised (R = price-move / SL-distance, both in same price units);
swap haircut uses sl_pct (dimensionless) => JPY-safe. No code change needed for
JPY beyond loading the right symbol.

Outputs:
  (a) per-symbol standalone: n, IS/OOS net mR, shuffle p (BH-FDR over 3 symbols)
  (b) monthly-R correlation matrix (diversification value)
  (c) portfolio compounded monthly profile (full-budget vs split-budget)
  (d) portfolio leverage/risk scaling table + single-symbol comparison at
      matched MaxDD (the "free lunch" measurement)
  (e) %10/mo feasibility verdict

Lookahead-paranoia: all signals from causal gather(); IS=[2020,2024) frozen,
OOS=[2024,2026). MC ruin/DD use bootstrap on realised R only. NO param search
(no p-hacking) — single fixed brooks manifest per symbol.

Usage: .venv/bin/python scripts/brooks_portfolio_3fx.py
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path
from statistics import mean, median, pstdev

os.environ["PA_LOG_QUIET"] = "1"
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.forex_4h_research as fx  # reuse gather/build_strategy/load_ohlcv
from price_action.backtest.lab import ProductionConfig, production_replay

YAML = ROOT / "configs" / "risk_forex.yaml"
IS_END = pd.Timestamp("2024-01-01", tz="UTC")
SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY"]
SEED = 12345
_rng = np.random.default_rng(SEED)


# --------------------------------------------------------------------------
def symbol_trades(sym: str) -> list[dict]:
    """brooks full-period trades for `sym`, bit-identical to forex_4h_research.

    fx.gather/load_ohlcv read module-global fx.SYMBOL; set it so the same
    machinery (filters/swap/slippage) runs for the requested symbol."""
    fx.SYMBOL = sym
    df = fx.load_ohlcv()
    strat = fx.build_strategy("brooks_failed_breakout", "BrooksFailedBreakoutStrategy")
    tr = fx.gather(strat, df.copy(), fx.SLIPPAGE_BPS)
    for t in tr:
        t["symbol"] = sym  # ensure tag
    return sorted(tr, key=lambda x: x["entry_ts"])


def r_summary(tr: list[dict]) -> dict:
    Rs = [t["R"] for t in tr]
    if not Rs:
        return {"n": 0, "mR": 0.0, "wr": 0.0, "sumR": 0.0}
    return {
        "n": len(Rs),
        "mR": mean(Rs),
        "wr": sum(1 for r in Rs if r > 0) / len(Rs) * 100,
        "sumR": sum(Rs),
        "sharpe": mean(Rs) / pstdev(Rs) if len(Rs) > 1 and pstdev(Rs) > 0 else 0.0,
    }


def shuffle_p(tr: list[dict], n_iter: int = 5000) -> float:
    Rs = np.array([t["R"] for t in tr], dtype=float)
    if len(Rs) == 0:
        return 1.0
    obs = float(Rs.mean())
    abs_R = np.abs(Rs)
    cnt = 0
    for _ in range(n_iter):
        signs = _rng.choice([-1.0, 1.0], size=len(Rs))
        if (abs_R * signs).mean() >= obs:
            cnt += 1
    return (cnt + 1) / (n_iter + 1)


# --------------------------------------------------------------------------
# Monthly-R series (equal-weight per-trade R aggregated by calendar month).
# This is the DIVERSIFICATION signal: are symbols' monthly edges correlated?
def monthly_R_series(tr: list[dict]) -> pd.Series:
    if not tr:
        return pd.Series(dtype=float)
    s = pd.Series(
        [t["R"] for t in tr],
        index=pd.to_datetime([t["entry_ts"] for t in tr], utc=True),
    ).sort_index()
    return s.resample("ME").sum()  # monthly sum of R


# --------------------------------------------------------------------------
def continuous_max_dd(eq_curve) -> float:
    peak = eq_curve[0]
    mdd = 0.0
    for v in eq_curve:
        peak = max(peak, v)
        dd = (v - peak) / peak if peak > 0 else 0.0
        mdd = min(mdd, dd)
    return mdd * 100.0


def monthly_returns_from_curve(eq_curve, exit_ts) -> pd.Series:
    eq = pd.Series(eq_curve[1:], index=pd.to_datetime([pd.Timestamp(t) for t in exit_ts], utc=True))
    eq = eq.sort_index()
    me = eq.resample("ME").last().dropna()
    if me.empty:
        return pd.Series(dtype=float)
    prev = pd.Series([eq_curve[0]] + list(me.values[:-1]), index=me.index)
    return (me / prev - 1.0) * 100.0


def monthly_profile(eq_curve, exit_ts, label) -> dict | None:
    mr = monthly_returns_from_curve(eq_curve, exit_ts)
    if mr.empty:
        return None
    return {
        "label": label,
        "n_months": len(mr),
        "mean_pct": float(mr.mean()),
        "median_pct": float(mr.median()),
        "neg_month_ratio": float((mr < 0).mean()),
        "worst_pct": float(mr.min()),
        "best_pct": float(mr.max()),
        "std_pct": float(mr.std()),
        "cont_maxdd_pct": continuous_max_dd(eq_curve),
        "final_mult": eq_curve[-1] / eq_curve[0],
        "_mr": mr,
    }


def max_consecutive_losses(Rs) -> int:
    runs, cur = [], 0
    for r in Rs:
        if r <= 0:
            cur += 1
        else:
            if cur:
                runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    return max(runs) if runs else 0


def kelly_fraction(Rs) -> float:
    a = np.array(Rs, dtype=float)
    m2 = float((a ** 2).mean())
    return float(a.mean() / m2) if m2 > 0 else 0.0


def mc_ruin(Rs, risk_pct, n_paths=4000, ruin_threshold=0.5, seed=12345) -> float:
    """Bootstrap resample of the realised per-trade R series; per-trade compound
    eq *= (1 + risk_pct*R); fraction of paths ever below ruin_threshold."""
    rng = np.random.default_rng(seed)
    a = np.array(Rs, dtype=float)
    n = len(a)
    ruined = 0
    for _ in range(n_paths):
        sample = a[rng.integers(0, n, size=n)]
        mult = np.cumprod(1.0 + risk_pct * sample)
        if mult.min() < ruin_threshold:
            ruined += 1
    return ruined / n_paths


def mc_maxdd(Rs, risk_pct, n_paths=4000, seed=777) -> float:
    rng = np.random.default_rng(seed)
    a = np.array(Rs, dtype=float)
    n = len(a)
    dds = []
    for _ in range(n_paths):
        sample = a[rng.integers(0, n, size=n)]
        eq = np.concatenate([[1.0], np.cumprod(1.0 + risk_pct * sample)])
        peak = np.maximum.accumulate(eq)
        dds.append(((eq - peak) / peak).min())
    return float(np.median(dds)) * 100.0


# --------------------------------------------------------------------------
def build_cfg(raw) -> ProductionConfig:
    return ProductionConfig(
        risk_pct=0.01,
        leverage=float(raw["leverage"]["max_leverage_per_symbol"]),
        max_notional_pct_equity=None,
        conf_min=0.0,
        daily_dd=raw["drawdown_breakers"]["daily_loss_pct"],
        weekly_dd=raw["drawdown_breakers"]["weekly_loss_pct"],
        monthly_dd=raw["drawdown_breakers"]["monthly_loss_pct"],
        consecutive_loss_n=None,
        same_symbol_side_cooldown_days=1.0,
        max_concurrent=6,
        initial_capital=10_000.0,
    )


def main() -> None:
    raw = yaml.safe_load(YAML.read_text())
    git = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    base_cfg = build_cfg(raw)

    print("=" * 92)
    print("brooks_failed_breakout 3-FX PORTFOLIO — EUR/USD + GBP/USD + USD/JPY 4H")
    print("=" * 92)
    print(f"git={git}  seed={SEED}  cost: fee=0 slip={fx.SLIPPAGE_BPS}bps swap={fx.SWAP_BPS_PER_NIGHT}bps/n(Wed3x)")
    print(f"IS=[2020,2024)  OOS=[2024,2026)  session 07-16UTC weekend-flat  cooldown 1d  max_concurrent=6")

    # ---------------- (a) per-symbol standalone ----------------
    trades = {s: symbol_trades(s) for s in SYMBOLS}
    print("\n" + "-" * 92)
    print("(a) PER-SYMBOL STANDALONE (brooks, R-multiple; JPY pip-scale normalised by R)")
    print("-" * 92)
    print(f"{'symbol':<9} {'n_full':>6} {'n_IS':>5} {'n_OOS':>6} {'IS_mR':>8} {'OOS_mR':>8} "
          f"{'full_mR':>8} {'wr%':>6} {'tShrp':>6} {'shuf_p':>7}")
    pvals = {}
    for s in SYMBOLS:
        tr = trades[s]
        is_tr = [t for t in tr if t["entry_ts"] < IS_END]
        oos_tr = [t for t in tr if t["entry_ts"] >= IS_END]
        si, so, sf = r_summary(is_tr), r_summary(oos_tr), r_summary(tr)
        p = shuffle_p(tr)
        pvals[s] = p
        print(f"{s:<9} {sf['n']:>6} {si['n']:>5} {so['n']:>6} {si['mR']:>+8.3f} {so['mR']:>+8.3f} "
              f"{sf['mR']:>+8.3f} {sf['wr']:>5.1f}% {sf['sharpe']:>+6.3f} {p:>7.4f}")

    # BH-FDR over the 3 symbols
    order = sorted(pvals.items(), key=lambda x: x[1])
    m = len(order)
    print("\n  BH-FDR (alpha=0.05) over 3 symbols:")
    for i, (s, p) in enumerate(order, 1):
        thr = i / m * 0.05
        print(f"    rank{i} {s:<9} p={p:.4f} thr={thr:.4f} -> {'PASS' if p <= thr else 'fail'}")

    # ---------------- (b) monthly-R correlation matrix ----------------
    mser = {s: monthly_R_series(trades[s]) for s in SYMBOLS}
    mdf = pd.DataFrame(mser).sort_index()
    # align on union of months, fill 0 (a month with no trade on a symbol = 0 R contribution)
    mdf_filled = mdf.fillna(0.0)
    corr = mdf_filled.corr()
    # also correlation on overlapping (both-traded) months only
    corr_overlap = mdf.corr()  # pandas pairwise drops NaN
    print("\n" + "-" * 92)
    print("(b) MONTHLY-R CORRELATION MATRIX (sum-of-R per calendar month)")
    print("-" * 92)
    print("  [fill-0: months with no trades count as 0 R]")
    print(corr.round(3).to_string())
    print("\n  [overlap-only: pairwise on months both symbols traded]")
    print(corr_overlap.round(3).to_string())
    off = [corr.iloc[i, j] for i in range(3) for j in range(3) if i < j]
    print(f"\n  mean pairwise corr (fill-0) = {np.mean(off):.3f}  "
          f"=> diversification ratio approx 1/sqrt(1+2*rho*... ) ; low rho = more free lunch")

    # naive variance-reduction estimate: portfolio monthly-R std vs avg single std
    port_month_R = mdf_filled.sum(axis=1)
    avg_single_std = np.mean([mdf_filled[s].std() for s in SYMBOLS])
    sum_single_std = sum(mdf_filled[s].std() for s in SYMBOLS)
    print(f"  portfolio monthly-R std (equal-sum) = {port_month_R.std():.2f}  "
          f"vs sum-of-single-stds = {sum_single_std:.2f}  "
          f"(if rho=1 they'd be equal; ratio={port_month_R.std()/sum_single_std:.3f})")

    # ---------------- (c) portfolio compounded monthly profile ----------------
    all_tr = sorted([t for s in SYMBOLS for t in trades[s]], key=lambda x: x["entry_ts"])
    all_R = [t["R"] for t in all_tr]
    is_all = [t for t in all_tr if t["entry_ts"] < IS_END]
    oos_all = [t for t in all_tr if t["entry_ts"] >= IS_END]

    print("\n" + "=" * 92)
    print("(c) PORTFOLIO COMPOUNDED MONTHLY PROFILE")
    print("=" * 92)
    print(f"pooled trades: full n={len(all_tr)}  IS n={len(is_all)}  OOS n={len(oos_all)}  "
          f"full net mR={mean(all_R):+.3f}")

    # Two budget conventions:
    #  FULL  : each symbol's trade entered at base risk_pct => concurrent overlap
    #          multiplies exposure (realistic shared-book; more risk + diversified).
    #  SPLIT : per-trade risk = base/3 so 3 simultaneous positions ~ 1 budget unit
    #          (fixed total risk vs single-symbol-at-base).
    def replay(trades_in, risk_pct, label):
        c = base_cfg.with_overrides(risk_pct=risk_pct)
        res = production_replay(trades_in, c)
        if res is None:
            return None, None
        return monthly_profile(res.equity_curve, res.entry_ts_list, label), res

    for mode, rp in (("FULL@1%", 0.01), ("SPLIT@0.333%", 0.01 / 3)):
        print(f"\n  --- portfolio mode={mode} (per-trade risk={rp*100:.3f}%) ---")
        for scope, tin in (("IS", is_all), ("OOS", oos_all), ("COMBINED", all_tr)):
            prof, res = replay(tin, rp, f"{mode}-{scope}")
            if not prof:
                print(f"    {scope}: no replay"); continue
            print(f"    {scope:<9} months={prof['n_months']:>2} mean={prof['mean_pct']:>+6.2f}% "
                  f"median={prof['median_pct']:>+6.2f}% neg={prof['neg_month_ratio']*100:>3.0f}% "
                  f"worst={prof['worst_pct']:>+7.2f}% contMaxDD={prof['cont_maxdd_pct']:>+6.1f}% "
                  f"final={res.final_equity/10000:.2f}x")

    # ---------------- (d) portfolio leverage scaling table ----------------
    print("\n" + "=" * 92)
    print("(d) PORTFOLIO LEVERAGE/RISK SCALING (COMBINED pooled, FULL-budget per-trade risk)")
    print("=" * 92)
    k_port = kelly_fraction(all_R)
    max_run_port = max_consecutive_losses(all_R)
    print(f"pooled Kelly f*={k_port*100:.1f}% (half-Kelly={k_port*50:.1f}%)  "
          f"worst consec-loss run={max_run_port}")
    print(f"NOTE: 'eff_r' = per-trade risk_pct. Portfolio overlaps => realised MaxDD is the")
    print(f"      honest axis. Compare to single-symbol at SAME realised MaxDD.\n")

    eff_risks = [0.01, 0.02, 0.03, 0.04, 0.06]
    hdr = (f"{'eff_r%':>7} {'mean_mo%':>9} {'median%':>8} {'neg%':>5} {'worst%':>8} "
           f"{'contMaxDD%':>11} {'MC_medDD%':>10} {'MC_ruin%':>9} {'final_x':>8} {'>halfKelly':>11}")
    print(hdr)
    print("-" * len(hdr))
    port_rows = {}
    for er in eff_risks:
        prof, res = replay(all_tr, er, f"port_r{er}")
        if not prof:
            continue
        mcdd = mc_maxdd(all_R, er)
        mcr = mc_ruin(all_R, er)
        port_rows[er] = (prof, res, mcdd, mcr)
        flag = "YES" if er > k_port * 0.5 else "no"
        print(f"{er*100:>6.0f}% {prof['mean_pct']:>+8.2f}% {prof['median_pct']:>+7.2f}% "
              f"{prof['neg_month_ratio']*100:>4.0f}% {prof['worst_pct']:>+7.2f}% "
              f"{prof['cont_maxdd_pct']:>+10.1f}% {mcdd:>+9.1f}% {mcr*100:>8.1f}% "
              f"{res.final_equity/10000:>7.2f}x {flag:>11}")

    # ---------------- single-symbol EUR/USD comparison at matched MC_medDD ----------------
    print("\n  SINGLE-SYMBOL (EUR/USD) reference for the SAME eff_r (free-lunch delta):")
    eur = trades["EUR/USD"]
    eur_R = [t["R"] for t in eur]
    print(f"  {'eff_r%':>7} {'PORT_med%':>10} {'PORT_MCdd%':>11} | {'EUR_med%':>9} {'EUR_MCdd%':>10} | "
          f"{'med_delta':>10} {'dd_delta':>9}")
    for er in eff_risks:
        if er not in port_rows:
            continue
        pprof, _, pmcdd, _ = port_rows[er]
        eprof, eres = replay(eur, er, f"eur_r{er}")  # NOTE: replay uses all_tr cfg; rebuild for eur
        # replay() closes over base_cfg; trades_in=eur is fine
        emcdd = mc_maxdd(eur_R, er)
        if not eprof:
            continue
        print(f"  {er*100:>6.0f}% {pprof['median_pct']:>+9.2f}% {pmcdd:>+10.1f}% | "
              f"{eprof['median_pct']:>+8.2f}% {emcdd:>+9.1f}% | "
              f"{pprof['median_pct']-eprof['median_pct']:>+9.2f}% {pmcdd-emcdd:>+8.1f}%")

    # ---------------- matched-DD comparison: find port eff_r and eur eff_r at same MC_medDD ----------------
    print("\n  MATCHED-DD FREE LUNCH (interpolate eff_r so MC_medDD approx -25% for both):")
    def med_and_dd_at(Rs_series, trades_in, target_dd=-25.0):
        # scan fine eff_r to hit target MC_medDD
        best = None
        for er in np.arange(0.005, 0.121, 0.005):
            dd = mc_maxdd(Rs_series, float(er))
            if dd <= target_dd:
                prof, res = replay(trades_in, float(er), "match")
                if prof:
                    return float(er), prof["median_pct"], prof["mean_pct"], dd
        return None
    for tgt in (-20.0, -25.0, -35.0):
        pr = med_and_dd_at(all_R, all_tr, tgt)
        er_ = med_and_dd_at(eur_R, eur, tgt)
        if pr and er_:
            print(f"   target MC_medDD~{tgt:.0f}%: PORT eff_r={pr[0]*100:.1f}% median={pr[1]:+.2f}% mean={pr[2]:+.2f}% (dd{pr[3]:.0f}%)"
                  f"  |  EUR eff_r={er_[0]*100:.1f}% median={er_[1]:+.2f}% mean={er_[2]:+.2f}% (dd{er_[3]:.0f}%)"
                  f"  |  median free-lunch={pr[1]-er_[1]:+.2f}pp")

    # ---------------- (e) %10/mo feasibility ----------------
    print("\n" + "=" * 92)
    print("(e) %10/MONTH FEASIBILITY — 3-FX brooks portfolio (FULL-budget)")
    print("=" * 92)
    found = False
    for er in eff_risks:
        if er not in port_rows:
            continue
        prof, res, mcdd, mcr = port_rows[er]
        tag = []
        if prof["median_pct"] >= 9.0:
            tag.append("MEDIAN>=9%")
            found = True
        if prof["mean_pct"] >= 9.0:
            tag.append("MEAN>=9%")
        safe = (er <= k_port * 0.5) and (mcr < 0.05)
        if tag:
            print(f"  eff_r={er*100:.0f}% median={prof['median_pct']:+.2f}% mean={prof['mean_pct']:+.2f}% "
                  f"contMaxDD={prof['cont_maxdd_pct']:+.1f}% MC_medDD={mcdd:+.1f}% MC_ruin={mcr*100:.1f}% "
                  f"-> {' '.join(tag)} | safe(half-Kelly&ruin<5%)={'YES' if safe else 'NO'}")
    if not found:
        print("  NO eff_r in {1..6%} reaches median +10%/mo. Mean-based 10% requires risk")
        print("  above half-Kelly (see table). Reporting closest below.")


if __name__ == "__main__":
    main()
