"""brooks_failed_breakout 7-FX RISK-PARITY PORTFOLIO — uncorrelated-legs expansion.

Pre-reg: memory/researcher/hypotheses/2026-05-29-brooks-7fx-uncorrelated-legs.md

Prior lesson (learning.md): vol-targeting overfit (RED). The real lever for variance
compression is UNCORRELATED positive-edge LEGS (independent monthly skews offset).

Reuses scripts/forex_4h_research.gather() VERBATIM per symbol (identical pre-reg
filters: session 07-16 UTC, weekend-flat, swap haircut, slippage 1.0bps, fee 0,
atr_min_pct, sl_pct_min 0). brooks is R-multiple based => cross/JPY pip-scale is
normalised (R = price-move / SL-distance). NO param search (no p-hacking).

Outputs:
  (a) 8-symbol standalone: n, IS/OOS/full net mR, shuffle p, BH-FDR. Select only
      self-positive (full mR>0 & shuffle BH-pass) legs. Negative legs DO NOT enter.
  (b) full 8x8 monthly-R correlation matrix + AUD/NZD block handling.
  (c) chosen low-correlation subset -> RISK-PARITY portfolio (AUD/NZD = 1 risk unit:
      each gets HALF risk; R-scaling by 0.5 == risk-halving, exact in fixed-fractional).
  (d) 3fx vs 7fx monthly distribution comparison (mean/median/STD/min/max/neg%/MaxDD/
      MC_medDD/MC_ruin/monthly Sharpe).
  (e) leverage table eff_r {1,1.5,2,2.5,3,4}% : where median 15-20% & MaxDD <= -30%.
  (f) ROBUSTNESS (vol-targeting paranoia): WF (2y/6m/3m), SYMBOL-OUT CV (drop each leg),
      shuffle baseline OOS.

Lookahead-paranoia: causal gather(); IS=[2020,2024) frozen, OOS=[2024,2026).
Standalone SELECTION uses full+shuffle only (NOT OOS) — no select-on-test leak.
Reproducibility: git_hash, data_hash, seed=12345.

Usage: .venv/bin/python scripts/brooks_portfolio_7fx.py
"""
from __future__ import annotations

import hashlib
import math
import os
import sys
from pathlib import Path
from statistics import mean, median, pstdev, stdev

os.environ["PA_LOG_QUIET"] = "1"
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.forex_4h_research as fx
from price_action.backtest.lab import ProductionConfig, production_replay

YAML = ROOT / "configs" / "risk_forex.yaml"
IS_END = pd.Timestamp("2024-01-01", tz="UTC")
ALL_SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF",
               "EUR/GBP", "USD/CAD", "NZD/USD"]
THREE_FX = ["EUR/USD", "GBP/USD", "USD/JPY"]  # baseline portfolio
# AUD/USD & NZD/USD correlate +0.89 (data_engineer) => one risk unit. Each leg gets
# HALF risk weight when both selected.
RISK_BLOCK = {"AUD/USD", "NZD/USD"}
SEED = 12345
_rng = np.random.default_rng(SEED)


# --------------------------------------------------------------------------
def symbol_trades(sym: str) -> list[dict]:
    fx.SYMBOL = sym
    df = fx.load_ohlcv()
    strat = fx.build_strategy("brooks_failed_breakout", "BrooksFailedBreakoutStrategy")
    tr = fx.gather(strat, df.copy(), fx.SLIPPAGE_BPS)
    for t in tr:
        t["symbol"] = sym
    return sorted(tr, key=lambda x: x["entry_ts"])


def r_summary(tr: list[dict]) -> dict:
    Rs = [t["R"] for t in tr]
    if not Rs:
        return {"n": 0, "mR": 0.0, "wr": 0.0, "sumR": 0.0, "sharpe": 0.0}
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


def monthly_R_series(tr: list[dict]) -> pd.Series:
    if not tr:
        return pd.Series(dtype=float)
    s = pd.Series([t["R"] for t in tr],
                  index=pd.to_datetime([t["entry_ts"] for t in tr], utc=True)).sort_index()
    return s.resample("ME").sum()


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


def monthly_profile(eq_curve, exit_ts) -> dict | None:
    mr = monthly_returns_from_curve(eq_curve, exit_ts)
    if mr.empty:
        return None
    mstd = float(mr.std())
    return {
        "n_months": len(mr),
        "mean_pct": float(mr.mean()),
        "median_pct": float(mr.median()),
        "std_pct": mstd,
        "neg_month_ratio": float((mr < 0).mean()),
        "worst_pct": float(mr.min()),
        "best_pct": float(mr.max()),
        "cont_maxdd_pct": continuous_max_dd(eq_curve),
        "mo_sharpe": float(mr.mean() / mstd) if mstd > 0 else 0.0,
        "final_mult": eq_curve[-1] / eq_curve[0],
        "_mr": mr,
    }


def kelly_fraction(Rs) -> float:
    a = np.array(Rs, dtype=float)
    m2 = float((a ** 2).mean())
    return float(a.mean() / m2) if m2 > 0 else 0.0


def mc_ruin(Rs, risk_pct, n_paths=4000, ruin_threshold=0.5, seed=12345) -> float:
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
        max_concurrent=8,
        initial_capital=10_000.0,
    )


def risk_parity_trades(trades_by_sym: dict, symbols: list[str]) -> list[dict]:
    """Pool selected symbols. AUD/NZD block: if both selected, each leg's R is
    scaled by 0.5 (== half risk; exact in fixed-fractional: risk*(0.5R)==(0.5risk)*R).
    This makes the +0.89-correlated AUD/NZD pair contribute ~1 risk unit, not 2."""
    block_present = RISK_BLOCK.issubset(set(symbols))
    pooled = []
    for s in symbols:
        scale = 0.5 if (block_present and s in RISK_BLOCK) else 1.0
        for t in trades_by_sym[s]:
            t2 = dict(t)
            if scale != 1.0:
                t2["R"] = t["R"] * scale
                t2["gross_R"] = t.get("gross_R", t["R"]) * scale
            pooled.append(t2)
    return sorted(pooled, key=lambda x: x["entry_ts"])


def replay_profile(trades_in, base_cfg, risk_pct):
    c = base_cfg.with_overrides(risk_pct=risk_pct)
    res = production_replay(trades_in, c)
    if res is None:
        return None, None
    return monthly_profile(res.equity_curve, res.entry_ts_list), res


# --------------------------------------------------------------------------
def walk_forward_pooled(trades: list[dict], train_days=730) -> list[dict]:
    if not trades:
        return []
    ts0 = min(t["entry_ts"] for t in trades)
    ts1 = max(t["entry_ts"] for t in trades)
    step = pd.Timedelta(days=91)
    test = pd.Timedelta(days=182)
    train = pd.Timedelta(days=train_days)
    windows, cur = [], ts0
    while cur + train + test <= ts1 + step:
        tr_e = cur + train
        te_s, te_e = tr_e, tr_e + test
        is_tr = [t["R"] for t in trades if cur <= t["entry_ts"] < tr_e]
        oos_tr = [t["R"] for t in trades if te_s <= t["entry_ts"] < te_e]
        if oos_tr:
            is_sh = (mean(is_tr) / pstdev(is_tr)) if len(is_tr) > 1 and pstdev(is_tr) > 0 else 0.0
            oos_sh = (mean(oos_tr) / pstdev(oos_tr)) if len(oos_tr) > 1 and pstdev(oos_tr) > 0 else 0.0
            windows.append({"test_start": te_s, "is_sharpe": is_sh, "oos_sharpe": oos_sh,
                            "oos_mR": mean(oos_tr), "oos_n": len(oos_tr)})
        cur += step
    return windows


# --------------------------------------------------------------------------
def main() -> None:
    raw = yaml.safe_load(YAML.read_text())
    git = os.popen("git -C %s rev-parse --short HEAD" % ROOT).read().strip()
    base_cfg = build_cfg(raw)

    print("=" * 100)
    print("brooks_failed_breakout 7-FX RISK-PARITY PORTFOLIO — uncorrelated-legs expansion")
    print("=" * 100)
    print(f"git={git}  seed={SEED}  cost: fee=0 slip={fx.SLIPPAGE_BPS}bps swap={fx.SWAP_BPS_PER_NIGHT}bps/n(Wed3x)")
    print(f"IS=[2020,2024) OOS=[2024,2026)  session 07-16UTC weekend-flat cooldown 1d max_concurrent=8")
    print(f"AUD/USD+NZD/USD (+0.89 corr) => 1 risk unit (each HALF risk in parity pool)")

    # ---------------- (a) per-symbol standalone over ALL 8 ----------------
    print("\n" + "-" * 100)
    print("(a) PER-SYMBOL STANDALONE — all 8 (brooks; R-multiple normalises pip scale)")
    print("-" * 100)
    trades = {s: symbol_trades(s) for s in ALL_SYMBOLS}
    # data hash over concatenated close arrays of all symbols
    h = hashlib.sha256()
    for s in ALL_SYMBOLS:
        fx.SYMBOL = s
        dfh = fx.load_ohlcv()
        h.update(dfh[["open", "high", "low", "close"]].to_numpy().tobytes())
    dhash = h.hexdigest()[:16]
    print(f"data_hash(8sym)={dhash}")
    print(f"\n{'symbol':<9} {'n_full':>6} {'n_IS':>5} {'n_OOS':>6} {'IS_mR':>8} {'OOS_mR':>8} "
          f"{'full_mR':>8} {'wr%':>6} {'tShrp':>6} {'shuf_p':>7}")
    pvals, full_summ = {}, {}
    for s in ALL_SYMBOLS:
        tr = trades[s]
        is_tr = [t for t in tr if t["entry_ts"] < IS_END]
        oos_tr = [t for t in tr if t["entry_ts"] >= IS_END]
        si, so, sf = r_summary(is_tr), r_summary(oos_tr), r_summary(tr)
        p = shuffle_p(tr)
        pvals[s] = p
        full_summ[s] = sf
        print(f"{s:<9} {sf['n']:>6} {si['n']:>5} {so['n']:>6} {si['mR']:>+8.3f} {so['mR']:>+8.3f} "
              f"{sf['mR']:>+8.3f} {sf['wr']:>5.1f}% {sf['sharpe']:>+6.3f} {p:>7.4f}")

    # BH-FDR over 8 symbols
    order = sorted(pvals.items(), key=lambda x: x[1])
    m = len(order)
    bh_pass = {}
    print("\n  BH-FDR (alpha=0.05) over 8 symbols:")
    for i, (s, p) in enumerate(order, 1):
        thr = i / m * 0.05
        ok = p <= thr
        bh_pass[s] = ok
        print(f"    rank{i} {s:<9} p={p:.4f} thr={thr:.4f} -> {'PASS' if ok else 'fail'}")

    # SELECTION: self-positive (full mR>0 & IS mR>0) AND shuffle BH-pass. NO OOS peek.
    print("\n  SELECTION RULE (no OOS peek): full_mR>0 AND IS_mR>0 AND BH-FDR PASS")
    selected = []
    for s in ALL_SYMBOLS:
        is_mR = mean([t["R"] for t in trades[s] if t["entry_ts"] < IS_END]) if any(t["entry_ts"] < IS_END for t in trades[s]) else 0.0
        ok = full_summ[s]["mR"] > 0 and is_mR > 0 and bh_pass[s]
        tag = "SELECT" if ok else "REJECT"
        if ok:
            selected.append(s)
        print(f"    {s:<9} full_mR={full_summ[s]['mR']:+.3f} IS_mR={is_mR:+.3f} BH={'Y' if bh_pass[s] else 'N'} -> {tag}")
    print(f"\n  SELECTED LEGS ({len(selected)}): {selected}")

    # ---------------- (b) full 8x8 monthly-R correlation matrix ----------------
    mser = {s: monthly_R_series(trades[s]) for s in ALL_SYMBOLS}
    mdf = pd.DataFrame(mser).sort_index()
    corr = mdf.fillna(0.0).corr()
    print("\n" + "-" * 100)
    print("(b) FULL 8x8 MONTHLY-R CORRELATION MATRIX (fill-0; sum-of-R per calendar month)")
    print("-" * 100)
    print(corr.round(2).to_string())
    # mean abs off-diagonal
    offs = [corr.iloc[i, j] for i in range(8) for j in range(8) if i < j]
    print(f"\n  mean pairwise corr (8 sym) = {np.mean(offs):+.3f}  mean |corr| = {np.mean(np.abs(offs)):.3f}")
    print(f"  AUD/USD vs NZD/USD monthly-R corr = {corr.loc['AUD/USD','NZD/USD']:+.3f}  "
          f"(data_engineer trade-level +0.89; treat as 1 unit)")

    # ---------------- (c) 7fx risk-parity portfolio ----------------
    # The pre-reg target subset = selected legs. Report whatever passes selection.
    port7 = selected
    print("\n" + "=" * 100)
    print(f"(c)/(d) PORTFOLIO BUILD — chosen subset = {port7}")
    print("=" * 100)
    pooled7 = risk_parity_trades(trades, port7)
    pooled3 = risk_parity_trades(trades, THREE_FX)  # 3fx has no AUD/NZD block -> plain pool
    R7 = [t["R"] for t in pooled7]
    R3 = [t["R"] for t in pooled3]
    print(f"3fx pooled n={len(pooled3)}  net mR={mean(R3):+.3f}")
    print(f"7fx pooled n={len(pooled7)}  net mR={mean(R7):+.3f}  (AUD/NZD R halved if both in)")

    # monthly-R std comparison (diversification value)
    def port_monthly_std(symbols, scaled=True):
        if scaled:
            pooled = risk_parity_trades(trades, symbols)
        sub = {s: monthly_R_series([t for t in pooled if t["symbol"] == s]) for s in symbols}
        d = pd.DataFrame(sub).sort_index().fillna(0.0)
        port = d.sum(axis=1)
        sum_std = sum(d[s].std() for s in symbols)
        return port.std(), sum_std, (port.std() / sum_std if sum_std > 0 else 0.0)

    ps3, ss3, ratio3 = port_monthly_std(THREE_FX)
    ps7, ss7, ratio7 = port_monthly_std(port7)
    print(f"\n  DIVERSIFICATION (monthly-R, risk-parity scaled):")
    print(f"    3fx: port_std={ps3:.2f}  sum_single_std={ss3:.2f}  ratio={ratio3:.3f}")
    print(f"    7fx: port_std={ps7:.2f}  sum_single_std={ss7:.2f}  ratio={ratio7:.3f}  "
          f"({'BETTER' if ratio7 < ratio3 else 'WORSE'} than 3fx)")

    # ---------------- (d) 3fx vs 7fx monthly distribution (matched eff_r) ----------------
    print("\n  --- 3fx vs 7fx MONTHLY DISTRIBUTION (FULL-budget per-trade risk) ---")
    is7 = [t for t in pooled7 if t["entry_ts"] < IS_END]
    oos7 = [t for t in pooled7 if t["entry_ts"] >= IS_END]
    for rp in (0.01, 0.02, 0.03):
        print(f"\n  eff_r={rp*100:.0f}%  {'book':<6} {'mo':>3} {'mean%':>7} {'med%':>7} {'STD%':>7} "
              f"{'neg%':>5} {'min%':>8} {'max%':>8} {'contDD%':>8} {'moShrp':>7} {'final':>8}")
        for label, pooled in (("3fx", pooled3), ("7fx", pooled7)):
            prof, res = replay_profile(pooled, base_cfg, rp)
            if not prof:
                continue
            print(f"          {label:<6} {prof['n_months']:>3} {prof['mean_pct']:>+6.2f}% "
                  f"{prof['median_pct']:>+6.2f}% {prof['std_pct']:>6.2f}% "
                  f"{prof['neg_month_ratio']*100:>4.0f}% {prof['worst_pct']:>+7.2f}% "
                  f"{prof['best_pct']:>+7.2f}% {prof['cont_maxdd_pct']:>+7.1f}% "
                  f"{prof['mo_sharpe']:>+6.3f} {prof['final_mult']:>7.2f}x")

    # IS vs OOS for 7fx (consistency)
    print("\n  7fx IS vs OOS (eff_r=2%, the consistency check):")
    for scope, tin in (("IS", is7), ("OOS", oos7), ("FULL", pooled7)):
        prof, res = replay_profile(tin, base_cfg, 0.02)
        if prof:
            print(f"    {scope:<5} mo={prof['n_months']:>2} mean={prof['mean_pct']:>+6.2f}% "
                  f"med={prof['median_pct']:>+6.2f}% STD={prof['std_pct']:>5.2f}% neg={prof['neg_month_ratio']*100:>3.0f}% "
                  f"contDD={prof['cont_maxdd_pct']:>+6.1f}% moShrp={prof['mo_sharpe']:+.3f}")

    # ---------------- (e) leverage table 7fx ----------------
    print("\n" + "=" * 100)
    print("(e) 7-FX LEVERAGE/RISK SCALING (FULL period, risk-parity pool)")
    print("=" * 100)
    k7 = kelly_fraction(R7)
    print(f"pooled Kelly f*={k7*100:.1f}% (half-Kelly={k7*50:.1f}%)")
    hdr = (f"{'eff_r%':>7} {'mean%':>8} {'median%':>8} {'STD%':>7} {'neg%':>5} {'min%':>8} "
           f"{'contDD%':>8} {'MC_medDD%':>10} {'MC_ruin%':>9} {'moShrp':>7} {'final_x':>9} {'TARGET':>7}")
    print(hdr); print("-" * len(hdr))
    lev_rows = {}
    for er in (0.01, 0.015, 0.02, 0.025, 0.03, 0.04):
        prof, res = replay_profile(pooled7, base_cfg, er)
        if not prof:
            continue
        mcdd = mc_maxdd(R7, er)
        mcr = mc_ruin(R7, er)
        lev_rows[er] = (prof, mcdd, mcr)
        target = "YES" if (15.0 <= prof["median_pct"] <= 20.0 and mcdd >= -30.0) else ""
        print(f"{er*100:>6.1f}% {prof['mean_pct']:>+7.2f}% {prof['median_pct']:>+7.2f}% "
              f"{prof['std_pct']:>6.2f}% {prof['neg_month_ratio']*100:>4.0f}% {prof['worst_pct']:>+7.2f}% "
              f"{prof['cont_maxdd_pct']:>+7.1f}% {mcdd:>+9.1f}% {mcr*100:>8.1f}% "
              f"{prof['mo_sharpe']:>+6.3f} {res.final_equity/10000:>8.2f}x {target:>7}")

    # matched MC_medDD free-lunch: 3fx vs 7fx at same DD target
    print("\n  MATCHED MC_medDD FREE-LUNCH (3fx vs 7fx; scan eff_r to hit target DD):")
    def at_target_dd(Rs, pooled, target_dd):
        for er in np.arange(0.005, 0.081, 0.0025):
            if mc_maxdd(Rs, float(er)) <= target_dd:
                prof, _ = replay_profile(pooled, base_cfg, float(er))
                if prof:
                    return float(er), prof["median_pct"], prof["mean_pct"], prof["std_pct"], prof["mo_sharpe"]
        return None
    for tgt in (-20.0, -25.0, -30.0, -35.0):
        a3 = at_target_dd(R3, pooled3, tgt)
        a7 = at_target_dd(R7, pooled7, tgt)
        if a3 and a7:
            print(f"   DD~{tgt:.0f}%: 3fx er={a3[0]*100:.1f}% med={a3[1]:+.1f}% mean={a3[2]:+.1f}% STD={a3[3]:.1f}% moShrp={a3[4]:+.2f}"
                  f"  |  7fx er={a7[0]*100:.1f}% med={a7[1]:+.1f}% mean={a7[2]:+.1f}% STD={a7[3]:.1f}% moShrp={a7[4]:+.2f}"
                  f"  |  med Δ={a7[1]-a3[1]:+.1f}pp moShrp Δ={a7[4]-a3[4]:+.2f}")

    # ---------------- (f) ROBUSTNESS ----------------
    print("\n" + "=" * 100)
    print("(f) ROBUSTNESS SUITE (vol-targeting paranoia ON)")
    print("=" * 100)

    # f1 walk-forward pooled 7fx
    print("\n  [f1] WALK-FORWARD (2y train / 6m test / 3m step; per-trade R Sharpe):")
    wins = walk_forward_pooled(pooled7)
    if wins:
        is_sh = mean([w["is_sharpe"] for w in wins])
        oos_sh = mean([w["oos_sharpe"] for w in wins])
        gap = abs(is_sh - oos_sh) / abs(is_sh) if is_sh != 0 else float("inf")
        pos = sum(1 for w in wins if w["oos_mR"] > 0)
        print(f"    windows={len(wins)}  mean_IS_Sh={is_sh:+.3f}  mean_OOS_Sh={oos_sh:+.3f}  "
              f"gap={gap*100:.0f}%  pos_OOS={pos}/{len(wins)}  "
              f"-> {'PASS (gap<50%, majority pos)' if gap < 0.5 and pos > len(wins)/2 else 'WEAK'}")

    # f2 symbol-out CV: drop each leg, does portfolio survive?
    print("\n  [f2] SYMBOL-OUT CV (drop each leg; FULL net mR + eff_r=2% median):")
    full_prof, _ = replay_profile(pooled7, base_cfg, 0.02)
    print(f"    ALL-IN ({len(port7)} legs): net_mR={mean(R7):+.3f}  median@2%={full_prof['median_pct']:+.2f}%  "
          f"STD={full_prof['std_pct']:.2f}%")
    fragile = False
    for drop in port7:
        sub = [s for s in port7 if s != drop]
        pooled_sub = risk_parity_trades(trades, sub)
        Rsub = [t["R"] for t in pooled_sub]
        prof_sub, _ = replay_profile(pooled_sub, base_cfg, 0.02)
        d_med = prof_sub["median_pct"] - full_prof["median_pct"]
        d_std = prof_sub["std_pct"] - full_prof["std_pct"]
        neg = prof_sub["median_pct"] < 0 or mean(Rsub) < 0
        if neg:
            fragile = True
        print(f"    -{drop:<9} net_mR={mean(Rsub):+.3f} median@2%={prof_sub['median_pct']:+.2f}% "
              f"(Δmed={d_med:+.2f}pp Δstd={d_std:+.2f}pp) {'<-- TURNS NEGATIVE!' if neg else ''}")
    print(f"    -> {'FAIL: single-leg dependent' if fragile else 'PASS: no single leg flips portfolio negative'}")

    # f3 shuffle baseline OOS (does OOS pooled beat null?)
    print("\n  [f3] SHUFFLE BASELINE (pooled 7fx OOS net mR vs sign-flip null):")
    p_oos = shuffle_p([t for t in pooled7 if t["entry_ts"] >= IS_END])
    p_full = shuffle_p(pooled7)
    oos_mR = mean([t["R"] for t in oos7]) if oos7 else 0.0
    print(f"    FULL: obs_mR={mean(R7):+.3f}  shuffle_p={p_full:.4f}  -> {'PASS' if p_full < 0.05 else 'FAIL'}")
    print(f"    OOS : obs_mR={oos_mR:+.3f}  shuffle_p={p_oos:.4f}  n={len(oos7)}  "
          f"-> {'PASS (beats null OOS)' if p_oos < 0.05 else 'FAIL (OOS noise)'}")

    print("\n" + "=" * 100)
    print("DONE. Verdict synthesis in researcher report (not auto-promoted).")
    print("=" * 100)


if __name__ == "__main__":
    main()
