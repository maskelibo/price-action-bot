"""brooks_failed_breakout EUR/USD 4H — REAL compounded monthly profile + leverage/risk scaling.

Reuses scripts/forex_4h_research.gather() VERBATIM (same pre-reg filters, same
swap haircut, same slippage) so the brooks R-series is bit-identical to the
JSON in reports/lab/forex_4h_20260529.json (n_IS=230, n_OOS=113, net mR ~+0.43).

Then:
  (1) production_replay with the CONFIG risk_pct (read from risk_forex.yaml) to
      build the canonical COMPOUNDED equity curve WITH breakers.
  (2) monthly ROI metrics (mean/median/neg-month%/worst/MaxDD) IS / OOS / combined.
  (3) risk_pct {1,2,3%} x leverage-equiv {1,2,3,5x} scaling table:
        monthly mean ROI, continuous MaxDD, risk-of-ruin from empirical
        consecutive-loss runs + Kelly fraction.

NOTE ON MECHANICS (documented, not hand-waved): in production_replay the
per-trade equity delta is  equity * risk_pct * R. Nominal leverage only gates
whether margin (=notional/leverage) fits in cash; with max_notional_pct_equity
null and lev>=1, margin never binds for risk%<=3 on a single-position FX book.
=> The TRUE return/DD lever is risk_pct, NOT nominal leverage. We therefore map
"leverage L at base risk r" -> effective risk_pct = r * L, and verify via replay.

Usage: .venv/bin/python scripts/brooks_leverage_scaling.py
"""
from __future__ import annotations

import os
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

import scripts.forex_4h_research as fx  # reuse gather/build_strategy/load_ohlcv VERBATIM
from price_action.backtest.lab import ProductionConfig, production_replay

YAML = ROOT / "configs" / "risk_forex.yaml"
IS_END = pd.Timestamp("2024-01-01", tz="UTC")


# --------------------------------------------------------------------------
def brooks_trades() -> list[dict]:
    """Bit-identical to forex_4h_research brooks full-period gather."""
    df = fx.load_ohlcv()
    df_full = df.copy()
    strat = fx.build_strategy("brooks_failed_breakout", "BrooksFailedBreakoutStrategy")
    return fx.gather(strat, df_full, fx.SLIPPAGE_BPS)


def monthly_returns_from_curve(eq_curve: list[float], exit_ts: list) -> pd.Series:
    """Compounded equity -> calendar-month ROI%. exit_ts aligns to eq_curve[1:]."""
    # eq_curve[0] = initial; eq_curve[i] is equity AFTER trade i-1 (exit_ts[i-1]).
    eq = pd.Series(eq_curve[1:], index=pd.to_datetime([pd.Timestamp(t) for t in exit_ts], utc=True))
    eq = eq.sort_index()
    # month-end equity (last equity within each month), prepend initial
    me = eq.resample("ME").last().dropna()
    if me.empty:
        return pd.Series(dtype=float)
    prev = pd.Series([eq_curve[0]] + list(me.values[:-1]), index=me.index)
    return (me / prev - 1.0) * 100.0


def continuous_max_dd(eq_curve: list[float]) -> float:
    peak = eq_curve[0]
    mdd = 0.0
    for v in eq_curve:
        peak = max(peak, v)
        dd = (v - peak) / peak if peak > 0 else 0.0
        mdd = min(mdd, dd)
    return mdd * 100.0


def monthly_profile(eq_curve, exit_ts, label) -> dict:
    mr = monthly_returns_from_curve(eq_curve, exit_ts)
    if mr.empty:
        return {}
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


def max_consecutive_losses(Rs: list[float]) -> tuple[int, list[int]]:
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
    return (max(runs) if runs else 0), runs


def kelly_fraction(Rs: list[float]) -> float:
    """Kelly for R-multiple bets: f* = mean(R) / mean(R^2) (continuous approx,
    optimal-growth fraction of equity to risk per trade)."""
    a = np.array(Rs, dtype=float)
    m2 = float((a ** 2).mean())
    return float(a.mean() / m2) if m2 > 0 else 0.0


def risk_of_ruin(risk_pct: float, win_p: float, payoff_R: float, max_run: int,
                 n_trades: int, ruin_threshold: float = 0.5) -> dict:
    """Two estimates of ruin / catastrophic-DD risk:
    (A) empirical worst loss-run: equity multiple after `max_run` consecutive
        full-R losses (each loss ~ -1R => -risk_pct of equity).
        mult = (1 - risk_pct)^max_run. ruin if < ruin_threshold.
    (B) Monte-Carlo on i.i.d. resample of actual R series at this risk_pct:
        fraction of 2000 paths whose equity ever drops below ruin_threshold."""
    worst_run_mult = (1.0 - risk_pct) ** max_run
    return {
        "worst_run_dd_pct": (worst_run_mult - 1.0) * 100.0,
        "worst_run_breaches_ruin": worst_run_mult < ruin_threshold,
    }


def mc_ruin(Rs: list[float], risk_pct: float, n_paths: int = 4000,
            ruin_threshold: float = 0.5, seed: int = 12345) -> float:
    """Fraction of bootstrap paths (resample actual R, same length) whose
    compounded equity ever falls below ruin_threshold * initial.
    Per-trade compounding: eq *= (1 + risk_pct * R)."""
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


def mc_maxdd(Rs: list[float], risk_pct: float, n_paths: int = 4000,
             seed: int = 777) -> float:
    """Median continuous MaxDD over bootstrap paths at given risk_pct (robust DD)."""
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
def main() -> None:
    raw = yaml.safe_load(YAML.read_text())
    cfg_risk = float(raw["position_sizing"].get("backtest_risk_pct",
                                                 raw["position_sizing"]["risk_per_trade"]))
    cfg_lev = float(raw["leverage"]["max_leverage_per_symbol"])
    print("=" * 80)
    print("brooks_failed_breakout EUR/USD 4H — COMPOUNDED MONTHLY + LEVERAGE SCALING")
    print("=" * 80)
    print(f"config risk_forex.yaml: risk_per_trade={cfg_risk*100:.2f}%  "
          f"max_leverage={cfg_lev:.0f}x  max_notional_pct_equity="
          f"{raw['position_sizing'].get('max_notional_pct_equity')}")

    tr = brooks_trades()
    tr = sorted(tr, key=lambda t: t["entry_ts"])
    Rs_all = [t["R"] for t in tr]
    is_tr = [t for t in tr if t["entry_ts"] < IS_END]
    oos_tr = [t for t in tr if t["entry_ts"] >= IS_END]
    print(f"\nbrooks trades: full n={len(tr)}  IS n={len(is_tr)}  OOS n={len(oos_tr)}")
    print(f"net mean R: full={mean(Rs_all):+.3f}  IS={mean([t['R'] for t in is_tr]):+.3f}  "
          f"OOS={mean([t['R'] for t in oos_tr]):+.3f}  sumR full={sum(Rs_all):+.1f}")
    wr = sum(1 for r in Rs_all if r > 0) / len(Rs_all)
    print(f"win rate full={wr*100:.1f}%  trade-R Sharpe={mean(Rs_all)/pstdev(Rs_all):.3f}")

    # ---- (1) canonical compounded replay at config risk_pct, WITH breakers ----
    # Use forex YAML breaker values, single-strategy (no portfolio interaction).
    base_cfg = ProductionConfig(
        risk_pct=cfg_risk,
        leverage=cfg_lev,
        max_notional_pct_equity=None,        # forex: cap null
        conf_min=0.0,                        # do not re-filter brooks conf
        daily_dd=raw["drawdown_breakers"]["daily_loss_pct"],
        weekly_dd=raw["drawdown_breakers"]["weekly_loss_pct"],
        monthly_dd=raw["drawdown_breakers"]["monthly_loss_pct"],
        consecutive_loss_n=None,             # forex: disabled (999)
        same_symbol_side_cooldown_days=1.0,
        max_concurrent=6,
        initial_capital=10_000.0,
    )

    def replay_profile(trades, risk_pct, lev=cfg_lev, label=""):
        c = base_cfg.with_overrides(risk_pct=risk_pct, leverage=lev)
        res = production_replay(trades, c)
        if res is None:
            return None
        return monthly_profile(res.equity_curve, res.entry_ts_list, label), res

    print("\n" + "-" * 80)
    print("(1)+(2) REAL COMPOUNDED MONTHLY PROFILE @ config risk=%.1f%% (WITH breakers)"
          % (cfg_risk * 100))
    print("-" * 80)
    for scope, trades in (("IS(2020-23)", is_tr), ("OOS(2024-25)", oos_tr), ("COMBINED", tr)):
        prof, res = replay_profile(trades, cfg_risk, label=scope)
        if not prof:
            print(f"  {scope}: no replay")
            continue
        print(f"\n  {scope}: replay trades={res.trades}  final=${res.final_equity:,.0f} "
              f"({(res.final_equity/10000-1)*100:+.1f}%)  cont_MaxDD={res.max_drawdown*100:+.1f}%")
        print(f"    months={prof['n_months']}  mean={prof['mean_pct']:+.2f}%  "
              f"median={prof['median_pct']:+.2f}%  neg-month={prof['neg_month_ratio']*100:.0f}%")
        print(f"    worst-month={prof['worst_pct']:+.2f}%  best-month={prof['best_pct']:+.2f}%  "
              f"std={prof['std_pct']:.2f}%")
        # histogram (deciles)
        mr = prof["_mr"]
        bins = [-100, -10, -5, -2, 0, 2, 5, 10, 100]
        hist = pd.cut(mr, bins=bins).value_counts().sort_index()
        print("    monthly ROI histogram (count):")
        for iv, cnt in hist.items():
            bar = "#" * int(cnt)
            print(f"      ({iv.left:>4.0f},{iv.right:>4.0f}]%: {cnt:>2}  {bar}")

    # ---- (3) leverage x risk scaling table ----
    print("\n" + "=" * 80)
    print("(3) LEVERAGE x RISK SCALING TABLE  (COMBINED brooks series, replay-verified)")
    print("=" * 80)
    print("NOTE: equity delta = equity*risk_pct*R. Nominal leverage only gates margin")
    print("      (never binds here) => effective risk = base_risk * leverage_equiv.\n")

    k = kelly_fraction(Rs_all)
    max_run, runs = max_consecutive_losses(Rs_all)
    print(f"Kelly fraction f* (full-Kelly per-trade risk) = {k*100:.1f}%   "
          f"=> half-Kelly={k*50:.1f}%")
    print(f"Worst empirical consecutive-loss run = {max_run} trades  "
          f"(loss runs: {sorted(runs, reverse=True)[:6]}...)\n")

    base_risks = [0.01, 0.02, 0.03]
    levs = [1, 2, 3, 5]
    hdr = (f"{'base_r':>7} {'lev':>4} {'eff_r%':>7} {'mean_mo%':>9} {'median%':>8} "
           f"{'neg%':>5} {'worst_mo%':>10} {'contMaxDD%':>11} {'MC_medDD%':>10} "
           f"{'worstRunDD%':>12} {'MC_ruin%':>9} {'>Kelly?':>8}")
    print(hdr)
    print("-" * len(hdr))
    rows = []
    for br in base_risks:
        for L in levs:
            eff = br * L
            prof, res = replay_profile(tr, eff, lev=cfg_lev, label=f"r{eff}")
            if not prof:
                continue
            mc_dd = mc_maxdd(Rs_all, eff)
            ror = risk_of_ruin(eff, wr, 0, max_run, len(Rs_all))
            mcr = mc_ruin(Rs_all, eff)
            over_kelly = "YES" if eff > k else "no"
            rows.append((br, L, eff, prof, res, mc_dd, ror, mcr, over_kelly))
            print(f"{br*100:>6.0f}% {L:>3}x {eff*100:>6.0f}% "
                  f"{prof['mean_pct']:>+8.2f}% {prof['median_pct']:>+7.2f}% "
                  f"{prof['neg_month_ratio']*100:>4.0f}% {prof['worst_pct']:>+9.2f}% "
                  f"{prof['cont_maxdd_pct']:>+10.1f}% {mc_dd:>+9.1f}% "
                  f"{ror['worst_run_dd_pct']:>+11.1f}% {mcr*100:>8.1f}% {over_kelly:>8}")

    # ---- target %10/mo feasibility ----
    print("\n" + "=" * 80)
    print("(c) %10/MONTH FEASIBILITY — single-strategy brooks")
    print("=" * 80)
    for br, L, eff, prof, res, mc_dd, ror, mcr, ok in rows:
        if prof["mean_pct"] >= 9.0:
            print(f"  eff_risk={eff*100:.0f}% -> mean {prof['mean_pct']:+.2f}%/mo  "
                  f"contMaxDD={prof['cont_maxdd_pct']:+.1f}%  MC_medDD={mc_dd:+.1f}%  "
                  f"MC_ruin={mcr*100:.1f}%  worstRunDD={ror['worst_run_dd_pct']:+.1f}%  "
                  f">Kelly={ok}")


if __name__ == "__main__":
    main()
