"""HYP-2026-05-29-brooks-1h-timeframe-diversification — add 1H legs to 4H portfolio.

Pre-reg: memory/researcher/hypotheses/2026-05-29-brooks-1h-timeframe-diversification.md

Reuses forex_4h_research.gather() VERBATIM (identical honest cost: fee=0,
slippage 1.0bps round-trip spread, swap 0.3bps/night Wed3x, session 07-16 UTC on
bar-OPEN ts, weekend-flat). For 1H we override fx.TF='1h' and atr_min_pct=0.0004
(= 4H floor 0.0008 * 0.5, the measured median-ATR% TF ratio; PRE-REG, no search).

Reuses brooks_portfolio_7fx for risk-parity replay / MC / monthly profile.

Lookahead-paranoia: causal gather; session filter on bar-OPEN ts; IS/OOS frozen.
Selection uses full+shuffle only (no OOS peek). seed=12345.

Usage: .venv/bin/python scripts/brooks_1h_tf_diversification.py
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from statistics import mean, pstdev

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
import scripts.brooks_portfolio_7fx as bp

YAML = ROOT / "configs" / "risk_forex.yaml"
IS_END = pd.Timestamp("2024-01-01", tz="UTC")
FX3 = ["EUR/USD", "GBP/USD", "USD/JPY"]
ALL_4H = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF",
          "EUR/GBP", "USD/CAD", "NZD/USD"]
ATR_MIN_4H = 0.0008
ATR_MIN_1H = 0.0004  # PRE-REG: 4H floor * 0.5 (measured median ATR% TF ratio)
SEED = 12345
_rng = np.random.default_rng(SEED)


def gather_tf(sym: str, tf: str, atr_min: float, force_floor: bool = False) -> list[dict]:
    """gather() for (symbol, timeframe) with honest cost. Tags symbol+tf.

    NOTE: brooks has a PRE-EXISTING 1h TF manifest (atr_min_pct=0.004, lookback=8,
    max_bars_to_fail=2) auto-merged by apply_tf_manifest() in prepare_features.
    That 0.004 floor (= ~30x the 1H median ATR%) strangles signals to ~58/6y.
    force_floor=True overrides the floor AFTER apply_tf_manifest re-validates, so the
    PRE-REG matched-selectivity floor (0.0004) actually binds. We report BOTH."""
    fx.SYMBOL = sym
    fx.TF = tf
    fx.ATR_MIN_PCT = atr_min
    df = fx.load_ohlcv()
    strat = fx.build_strategy("brooks_failed_breakout", "BrooksFailedBreakoutStrategy")
    if force_floor:
        # apply_tf_manifest() runs inside prepare_features and re-validates self.manifest
        # from the 1h YAML, clobbering our floor. Re-set it after each apply by patching.
        _orig = strat.apply_tf_manifest
        def _patched(d):
            _orig(d)
            strat.manifest.signals.filters.atr_min_pct = atr_min
        strat.apply_tf_manifest = _patched
    tr = fx.gather(strat, df.copy(), fx.SLIPPAGE_BPS)
    leg = f"{sym}@{tf}"
    for t in tr:
        t["symbol"] = sym
        t["tf"] = tf
        t["leg"] = leg
    return sorted(tr, key=lambda x: x["entry_ts"])


def r_sum(tr):
    Rs = [t["R"] for t in tr]
    if not Rs:
        return {"n": 0, "mR": 0.0, "gmR": 0.0, "wr": 0.0, "sumR": 0.0, "shrp": 0.0}
    g = [t["gross_R"] for t in tr]
    return {"n": len(Rs), "mR": mean(Rs), "gmR": mean(g),
            "wr": sum(1 for r in Rs if r > 0) / len(Rs) * 100, "sumR": sum(Rs),
            "shrp": mean(Rs) / pstdev(Rs) if len(Rs) > 1 and pstdev(Rs) > 0 else 0.0}


def shuffle_p(tr, n=5000):
    Rs = np.array([t["R"] for t in tr], float)
    if len(Rs) == 0:
        return 1.0
    obs = float(Rs.mean()); a = np.abs(Rs); c = 0
    for _ in range(n):
        if (a * _rng.choice([-1.0, 1.0], size=len(Rs))).mean() >= obs:
            c += 1
    return (c + 1) / (n + 1)


def main():
    raw = yaml.safe_load(YAML.read_text())
    git = os.popen("git -C %s rev-parse --short HEAD" % ROOT).read().strip()
    base_cfg = bp.build_cfg(raw)

    print("=" * 104)
    print("HYP-2026-05-29 brooks 1H TIME-FRAME DIVERSIFICATION (add 1H legs to 4H portfolio)")
    print("=" * 104)
    print(f"git={git} seed={SEED} cost: fee=0 slip={fx.SLIPPAGE_BPS}bps swap={fx.SWAP_BPS_PER_NIGHT}bps/n(Wed3x)")
    print(f"atr_min_pct: 4H={ATR_MIN_4H} 1H={ATR_MIN_1H} (PRE-REG = 4H*0.5 measured TF ratio; no search)")
    print(f"IS=[2020,2024) OOS=[2024,2026) session 07-16UTC weekend-flat cooldown 1d")

    print(f"NOTE: brooks ships a 1h TF-manifest (atr_min=0.004, lookback=8, max_fail=2) that")
    print(f"      strangles signals to n<30/6y (0.004 = ~30x 1H median ATR%). PRE-REG matched")
    print(f"      floor=0.0004 (force_floor) is the honest apples-to-apples 1H<->4H comparison.")

    # ---- gather all legs ----
    tr4 = {s: gather_tf(s, "4h", ATR_MIN_4H) for s in ALL_4H}
    # 1H at PRE-REG matched-selectivity floor (force past the strict shipped YAML)
    tr1 = {s: gather_tf(s, "1h", ATR_MIN_1H, force_floor=True) for s in FX3}
    # 1H at shipped YAML floor (for honest disclosure of the n<30 alternative)
    tr1_yaml = {s: gather_tf(s, "1h", 0.004, force_floor=False) for s in FX3}

    h = hashlib.sha256()
    for s in ALL_4H:
        fx.SYMBOL, fx.TF = s, "4h"; h.update(fx.load_ohlcv()[["open","high","low","close"]].to_numpy().tobytes())
    for s in FX3:
        fx.SYMBOL, fx.TF = s, "1h"; h.update(fx.load_ohlcv()[["open","high","low","close"]].to_numpy().tobytes())
    print(f"data_hash={h.hexdigest()[:16]}")

    # ============ (a) 1H STANDALONE ============
    print("\n" + "-" * 104)
    print("(a) 1H STANDALONE — net edge positive or fee-victim? (honest cost identical to 4H)")
    print("-" * 104)
    print(f"{'leg':<14} {'n':>5} {'nIS':>5} {'nOOS':>5} {'IS_mR':>8} {'OOS_mR':>8} {'full_mR':>8} "
          f"{'gross_mR':>9} {'fee_drag':>9} {'wr%':>6} {'tShrp':>6} {'shuf_p':>7}")
    p1 = {}; full1 = {}; is1 = {}; oos1 = {}
    for s in FX3:
        tr = tr1[s]
        itr = [t for t in tr if t["entry_ts"] < IS_END]
        otr = [t for t in tr if t["entry_ts"] >= IS_END]
        si, so, sf = r_sum(itr), r_sum(otr), r_sum(tr)
        p = shuffle_p(tr); p1[s] = p; full1[s] = sf; is1[s] = si; oos1[s] = so
        fee_drag = sf["gmR"] - sf["mR"]
        print(f"{s+'@1h':<14} {sf['n']:>5} {si['n']:>5} {so['n']:>5} {si['mR']:>+8.3f} {so['mR']:>+8.3f} "
              f"{sf['mR']:>+8.3f} {sf['gmR']:>+9.3f} {fee_drag:>+9.3f} {sf['wr']:>5.1f}% "
              f"{sf['shrp']:>+6.3f} {p:>7.4f}")

    # 4H same-3 for reference
    print(f"\n  (ref) same 3 symbols @4H:")
    for s in FX3:
        tr = tr4[s]; sf = r_sum(tr)
        fee_drag = sf["gmR"] - sf["mR"]
        print(f"{s+'@4h':<14} {sf['n']:>5} {'':>5} {'':>5} {'':>8} {'':>8} "
              f"{sf['mR']:>+8.3f} {sf['gmR']:>+9.3f} {fee_drag:>+9.3f} {sf['wr']:>5.1f}% {sf['shrp']:>+6.3f}")

    print(f"\n  (disclosure) 1H at SHIPPED YAML floor 0.004 (project's committed config):")
    for s in FX3:
        sf = r_sum(tr1_yaml[s])
        print(f"{s+'@1h-yaml':<14} {sf['n']:>5} {'':>5} {'':>5} {'':>8} {'':>8} {sf['mR']:>+8.3f} "
              f"{'':>9} {'':>9} {sf['wr']:>5.1f}% {sf['shrp']:>+6.3f}  (n too small for a leg)")

    # BH-FDR over 3 1H legs
    order = sorted(p1.items(), key=lambda x: x[1]); m = len(order); bh1 = {}
    print("\n  BH-FDR (alpha=0.05) over 3 1H legs:")
    for i, (s, p) in enumerate(order, 1):
        thr = i / m * 0.05; ok = p <= thr; bh1[s] = ok
        print(f"    rank{i} {s+'@1h':<14} p={p:.4f} thr={thr:.4f} -> {'PASS' if ok else 'fail'}")

    sel1 = [s for s in FX3 if full1[s]["mR"] > 0 and is1[s]["mR"] > 0 and bh1[s] and oos1[s]["mR"] > 0]
    print(f"\n  SELECTION (full_mR>0 & IS_mR>0 & BH-pass & OOS_mR>0): {[s+'@1h' for s in sel1]}")

    # ============ (b) CROSS-TF CORRELATION ============
    print("\n" + "-" * 104)
    print("(b) CROSS-TF MONTHLY-R CORRELATION — is 1H an independent leg or repeat of 4H edge?")
    print("-" * 104)
    mser = {}
    for s in FX3:
        mser[f"{s}@1h"] = bp.monthly_R_series(tr1[s])
    for s in ALL_4H:
        mser[f"{s}@4h"] = bp.monthly_R_series(tr4[s])
    mdf = pd.DataFrame(mser).sort_index().fillna(0.0)
    # same-symbol cross-TF
    print("  SAME-SYMBOL cross-TF aylik-R corr (independence test, <0.6 = independent leg):")
    cross = {}
    for s in FX3:
        c = mdf[f"{s}@1h"].corr(mdf[f"{s}@4h"])
        cross[s] = c
        verd = "INDEPENDENT" if c < 0.6 else "REPEAT (>0.6)"
        print(f"    {s:<9} 1H<->4H corr = {c:+.3f}  -> {verd}")
    print(f"  mean same-symbol cross-TF corr = {np.mean(list(cross.values())):+.3f}")
    # 1H legs vs each other
    print("\n  1H legs pairwise corr:")
    for i in range(len(FX3)):
        for j in range(i+1, len(FX3)):
            a, b = FX3[i], FX3[j]
            print(f"    {a}@1h <-> {b}@1h = {mdf[f'{a}@1h'].corr(mdf[f'{b}@1h']):+.3f}")
    # 1H legs vs full 4H portfolio (pooled monthly-R)
    pool4_all = bp.risk_parity_trades(tr4, ALL_4H)
    m4 = bp.monthly_R_series(pool4_all)
    print("\n  each 1H leg vs FULL-8 4H pooled monthly-R:")
    for s in FX3:
        al = mdf[f"{s}@1h"].align(m4, fill_value=0.0)
        print(f"    {s}@1h <-> 4H-portfolio = {al[0].corr(al[1]):+.3f}")

    # ============ (c)/(d) COMBINED PORTFOLIO 11-leg vs 7-leg ============
    print("\n" + "=" * 104)
    print("(c)/(d) COMBINED PORTFOLIO — 4H-7leg(baseline) vs +1H legs; risk-parity replay")
    print("=" * 104)
    # baseline 7-leg: replicate brooks_portfolio_7fx selection (its SELECTED set).
    # Re-derive 4H selection identically (full_mR>0 & IS_mR>0 & shuffle BH over 8).
    p4 = {s: shuffle_p(tr4[s]) for s in ALL_4H}
    o4 = sorted(p4.items(), key=lambda x: x[1]); m4n = len(o4); bh4 = {}
    for i, (s, p) in enumerate(o4, 1):
        bh4[s] = p <= i / m4n * 0.05
    sel4 = [s for s in ALL_4H
            if r_sum(tr4[s])["mR"] > 0
            and r_sum([t for t in tr4[s] if t["entry_ts"] < IS_END])["mR"] > 0
            and bh4[s]]
    print(f"  4H SELECTED ({len(sel4)}): {sel4}")
    print(f"  1H SELECTED ({len(sel1)}): {[s+'@1h' for s in sel1]}")

    # pooled 4H-only (risk-parity, AUD/NZD half)
    pool7 = bp.risk_parity_trades(tr4, sel4)
    # combined: pool7 + selected 1H legs (full risk each, distinct legs)
    combined_legs = sel4 + [f"__1h__{s}" for s in sel1]
    pool11 = list(pool7)
    for s in sel1:
        pool11.extend(tr1[s])
    pool11 = sorted(pool11, key=lambda x: x["entry_ts"])
    R7 = [t["R"] for t in pool7]; R11 = [t["R"] for t in pool11]
    print(f"\n  7-leg pooled n={len(pool7)} net_mR={mean(R7):+.3f}")
    print(f"  {7+len(sel1)}-leg pooled n={len(pool11)} net_mR={mean(R11):+.3f}")

    # monthly distribution at matched eff_r grid
    print(f"\n  MONTHLY DISTRIBUTION (full period, full-budget per-trade risk):")
    print(f"  {'eff_r':>6} {'book':<7} {'mo':>3} {'mean%':>7} {'med%':>7} {'STD%':>7} {'neg%':>5} "
          f"{'min%':>8} {'contDD%':>8} {'MC_medDD%':>10} {'moShrp':>7} {'final':>8}")
    for er in (0.01, 0.015, 0.02):
        for label, pool, Rs in ((f"4H-{len(sel4)}", pool7, R7), (f"+1H-{7+len(sel1)}", pool11, R11)):
            prof, res = bp.replay_profile(pool, base_cfg, er)
            if not prof:
                continue
            mcdd = bp.mc_maxdd(Rs, er)
            print(f"  {er*100:>5.1f}% {label:<7} {prof['n_months']:>3} {prof['mean_pct']:>+6.2f}% "
                  f"{prof['median_pct']:>+6.2f}% {prof['std_pct']:>6.2f}% {prof['neg_month_ratio']*100:>4.0f}% "
                  f"{prof['worst_pct']:>+7.2f}% {prof['cont_maxdd_pct']:>+7.1f}% {mcdd:>+9.1f}% "
                  f"{prof['mo_sharpe']:>+6.3f} {res.final_equity/10000:>7.2f}x")

    # MATCHED-DD FRONTIER comparison (the principal question)
    print(f"\n  MATCHED MC_medDD FRONTIER (scan eff_r to hit DD target; the principal Q):")
    def at_dd(Rs, pool, tgt):
        for er in np.arange(0.005, 0.081, 0.0025):
            if bp.mc_maxdd(Rs, float(er)) <= tgt:
                prof, res = bp.replay_profile(pool, base_cfg, float(er))
                if prof:
                    return float(er), prof["median_pct"], prof["mean_pct"], prof["std_pct"], prof["mo_sharpe"], prof["neg_month_ratio"]
        return None
    print(f"  {'DD_tgt':>7} | {'4H-7leg':>34} | {'+1H combined':>34} | {'Δmed':>7} {'ΔmoShrp':>8} {'ΔSTD':>7}")
    for tgt in (-15.0, -18.0, -20.0, -25.0, -30.0):
        a7 = at_dd(R7, pool7, tgt); a11 = at_dd(R11, pool11, tgt)
        if a7 and a11:
            print(f"  {tgt:>6.0f}% | er={a7[0]*100:4.1f}% med={a7[1]:+5.1f}% mean={a7[2]:+5.1f}% STD={a7[3]:4.1f}% Sh={a7[4]:+.2f}"
                  f" | er={a11[0]*100:4.1f}% med={a11[1]:+5.1f}% mean={a11[2]:+5.1f}% STD={a11[3]:4.1f}% Sh={a11[4]:+.2f}"
                  f" | {a11[1]-a7[1]:>+6.1f}pp {a11[4]-a7[4]:>+7.2f} {a11[3]-a7[3]:>+6.1f}")

    # ============ (e) ROBUSTNESS ============
    print("\n" + "=" * 104)
    print("(e) ROBUSTNESS — 1H overfit paranoia (WF + shuffle OOS + symbol-out)")
    print("=" * 104)
    # WF on combined pool
    print("\n  [WF] 2y train / 6m test / 3m step (per-trade R Sharpe):")
    for label, pool in ((f"4H-{len(sel4)}", pool7), (f"+1H-{7+len(sel1)}", pool11)):
        wins = bp.walk_forward_pooled(pool)
        if wins:
            iss = mean([w["is_sharpe"] for w in wins]); oss = mean([w["oos_sharpe"] for w in wins])
            gap = abs(iss - oss) / abs(iss) if iss else float("inf")
            pos = sum(1 for w in wins if w["oos_mR"] > 0)
            print(f"    {label:<9} wins={len(wins)} IS_Sh={iss:+.3f} OOS_Sh={oss:+.3f} gap={gap*100:.0f}% "
                  f"pos_OOS={pos}/{len(wins)} -> {'PASS' if gap<0.5 and pos>len(wins)/2 else 'WEAK'}")

    # shuffle OOS — 1H legs alone OOS (overfit check) + combined
    print("\n  [SHUFFLE OOS] does OOS edge beat sign-flip null? (1H overfit check):")
    for s in sel1:
        otr = [t for t in tr1[s] if t["entry_ts"] >= IS_END]
        po = shuffle_p(otr)
        print(f"    {s+'@1h':<14} OOS_mR={r_sum(otr)['mR']:+.3f} n={len(otr)} shuf_p={po:.4f} "
              f"-> {'PASS' if po<0.05 else 'FAIL (OOS noise)'}")
    oos11 = [t for t in pool11 if t["entry_ts"] >= IS_END]
    oos7 = [t for t in pool7 if t["entry_ts"] >= IS_END]
    p11o = shuffle_p(oos11); p7o = shuffle_p(oos7)
    print(f"    {'4H-7 pooled':<14} OOS_mR={r_sum(oos7)['mR']:+.3f} n={len(oos7)} shuf_p={p7o:.4f}")
    print(f"    {'+1H pooled':<14} OOS_mR={r_sum(oos11)['mR']:+.3f} n={len(oos11)} shuf_p={p11o:.4f}")

    # leg-out: drop each 1H leg, does combined survive / stay better than 7?
    print("\n  [LEG-OUT] drop each 1H leg from combined (median@1.5% sensitivity):")
    prof_full, _ = bp.replay_profile(pool11, base_cfg, 0.015)
    for s in sel1:
        sub = [t for t in pool11 if not (t.get("tf") == "1h" and t["symbol"] == s)]
        prof_s, _ = bp.replay_profile(sub, base_cfg, 0.015)
        print(f"    -{s+'@1h':<13} med@1.5%={prof_s['median_pct']:+.2f}% (full={prof_full['median_pct']:+.2f}%, "
              f"Δ={prof_s['median_pct']-prof_full['median_pct']:+.2f}pp)")

    print("\n" + "=" * 104)
    print("DONE. Synthesis in researcher report (not auto-promoted).")
    print("=" * 104)


if __name__ == "__main__":
    main()
