"""2x2 matrix: {10sym, 14sym} x {trail1.5, trail3.0} on vsa_climax_test 15m.

Reuses the EXACT replay/cost/monthly machinery from
scripts/crypto_winner_let_run_vsa_exit.py (production_replay + widestop_vsa2 cfg,
risk 0.5%, sl_pct>=0.025, pyramid-OFF, honest fees/slippage).

10-sym trades  : /tmp/wlr_vsa_variants.pkl  (B_baseline=trail1.5, V1a_trail3.0)
4 new-sym trades: /tmp/expansion_4sym_2variants.pkl  (ZEC,NEAR,FIL,XLM; SUI excluded)

Date-align: ALL cells start 2021-05-16 (common start of the 10-sym universe), so
the 4 new symbols (which list earlier) are clipped to the SAME window -> the
ONLY differences across cells are (universe size) and (trail mult). 61 months.

Tail: block-bootstrap (moving block, len=3 months) on the continuous monthly-ROI
series -> p95/p99 worst-month + bootstrap MaxDD distribution. NO iid MC.
"""
from __future__ import annotations
import os, sys, pickle
from pathlib import Path

os.environ["PA_DUCKDB_READ_ONLY"] = "true"
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import importlib.util
spec = importlib.util.spec_from_file_location(
    "wlr", str(ROOT / "scripts" / "crypto_winner_let_run_vsa_exit.py"))
wlr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wlr)

ALIGN_START = pd.Timestamp("2021-05-16", tz="UTC")
END = pd.Timestamp("2026-07-01", tz="UTC")
SEED = 12345
BLOCK = 3  # months per bootstrap block


def clip(trades):
    return [t for t in trades
            if ALIGN_START <= t["entry_ts"] < END and wlr.sl_pct_of(t) >= 0.025]


def monthly_series(trades, cfg):
    pool = sorted(trades, key=lambda x: x["entry_ts"])
    res = wlr.production_replay(pool, cfg)
    if res is None:
        return None, None
    mr = wlr.monthly_from_replay(res, cfg)
    return res, mr


def block_bootstrap_tail(mr, n_iter=5000, block=BLOCK, seed=SEED):
    """Moving-block bootstrap on monthly-ROI series. Preserves serial structure.
    Returns p95/p99 worst single month, and bootstrap MaxDD p95/p99."""
    a = np.asarray(mr.values, dtype=float)
    n = len(a)
    if n < block + 1:
        return dict(p95_mo=np.nan, p99_mo=np.nan, dd_p95=np.nan, dd_p99=np.nan, neff=n)
    rng = np.random.default_rng(seed)
    nblocks = int(np.ceil(n / block))
    starts_pool = np.arange(0, n - block + 1)
    worst_month = np.empty(n_iter)
    boot_dd = np.empty(n_iter)
    for it in range(n_iter):
        starts = rng.choice(starts_pool, size=nblocks, replace=True)
        seq = np.concatenate([a[s:s + block] for s in starts])[:n]
        worst_month[it] = seq.min()
        # compound equity & MaxDD on resampled monthly path
        eq = np.cumprod(1.0 + seq / 100.0)
        peak = np.maximum.accumulate(eq)
        boot_dd[it] = ((eq - peak) / peak).min() * 100.0
    neff = n / block  # effective independent blocks
    return dict(p95_mo=float(np.percentile(worst_month, 5)),
                p99_mo=float(np.percentile(worst_month, 1)),
                dd_p95=float(np.percentile(boot_dd, 5)),
                dd_p99=float(np.percentile(boot_dd, 1)),
                neff=neff)


def cell_metrics(trades, cfg, label):
    trades = clip(trades)
    res, mr = monthly_series(trades, cfg)
    if res is None or mr is None or mr.empty:
        return None
    tail = block_bootstrap_tail(mr)
    Rs = np.array([t["R"] for t in trades], dtype=float)
    return dict(
        label=label,
        n_pos=res.trades,
        med=float(mr.median()),
        mean=float(mr.mean()),
        sharpe=float(mr.mean() / mr.std()) if mr.std() > 0 else 0.0,
        realized_dd=wlr.cont_dd(res.equity_curve),
        neg=int((mr < 0).sum()),
        nmo=len(mr),
        mean_R=float(Rs.mean()),
        wr=float(res.win_rate * 100),
        **tail,
    )


def main():
    cfg = wlr.build_cfg()
    print("cfg: risk_pct=%.4f sl_pct_min=%.4f init_cap=%s pyramid=%s"
          % (cfg.risk_pct, cfg.sl_pct_min, cfg.initial_capital,
             getattr(cfg, "pyramid_enabled", "n/a")))

    V10 = pickle.load(open("/tmp/wlr_vsa_variants.pkl", "rb"))
    E4 = pickle.load(open("/tmp/expansion_4sym_2variants.pkl", "rb"))

    syms10 = wlr.SYMS
    new4 = ["ZEC/USDT", "NEAR/USDT", "FIL/USDT", "XLM/USDT"]

    base10 = {s: V10["B_baseline"][s] for s in syms10}     # trail 1.5
    t30_10 = {s: V10["V1a_trail3.0"][s] for s in syms10}   # trail 3.0
    new_15 = E4["trail1.5"]
    new_30 = E4["trail3.0"]

    def flat(d):
        return [t for s in d for t in d[s]]

    cells = {
        ("10", "1.5"): flat(base10),
        ("10", "3.0"): flat(t30_10),
        ("14", "1.5"): flat(base10) + flat({s: new_15[s] for s in new4}),
        ("14", "3.0"): flat(t30_10) + flat({s: new_30[s] for s in new4}),
    }

    M = {}
    for key, tr in cells.items():
        M[key] = cell_metrics(tr, cfg, f"{key[0]}sym/trail{key[1]}")

    # ---- (a) 2x2 matrix ----
    print("\n" + "=" * 120)
    print("(a) 2x2 MATRIX  — date-aligned 2021-05-16+, continuous-curve, honest cost, block-bootstrap tail")
    print("=" * 120)
    hdr = (f"{'cell':<18}| {'med%':>6} {'mean%':>6} {'Sharpe':>6} {'realDD%':>7} "
           f"{'neg':>4} {'meanR':>6} {'wr%':>5} {'n_pos':>6} | "
           f"{'bsP95mo':>7} {'bsP99mo':>7} {'bsDDp95':>7} {'bsDDp99':>7} {'Neff':>5}")
    print(hdr); print("-" * len(hdr))
    order = [("10", "1.5"), ("10", "3.0"), ("14", "1.5"), ("14", "3.0")]
    names = {("10","1.5"):"10sym x t1.5 BASE", ("10","3.0"):"10sym x t3.0 WLR",
             ("14","1.5"):"14sym x t1.5 SYMEXP", ("14","3.0"):"14sym x t3.0 COMBINED"}
    for k in order:
        m = M[k]
        print(f"{names[k]:<18}| {m['med']:>+6.2f} {m['mean']:>+6.2f} {m['sharpe']:>+6.2f} "
              f"{m['realized_dd']:>+7.1f} {m['neg']:>3}/{m['nmo']:<2} {m['mean_R']:>+6.3f} "
              f"{m['wr']:>4.0f}% {m['n_pos']:>6} | {m['p95_mo']:>+7.2f} {m['p99_mo']:>+7.2f} "
              f"{m['dd_p95']:>+7.1f} {m['dd_p99']:>+7.1f} {m['neff']:>5.1f}")

    # ---- (b) additivity decomposition (median ROI) ----
    b = M[("10","1.5")]["med"]
    d_sym = M[("14","1.5")]["med"] - b      # symbol expansion alone
    d_trail = M[("10","3.0")]["med"] - b    # winner-let-run alone
    combined = M[("14","3.0")]["med"] - b   # combined uplift
    additive = d_sym + d_trail
    interaction = combined - additive
    print("\n" + "=" * 120)
    print("(b) ADDITIVITY — median monthly ROI decomposition (baseline = 10sym x trail1.5)")
    print("=" * 120)
    print(f"  baseline median             : {b:+.2f}%")
    print(f"  Δ symbol-exp alone (14/1.5) : {d_sym:+.2f}pp")
    print(f"  Δ winner-let-run alone (3.0): {d_trail:+.2f}pp")
    print(f"  combined uplift (14/3.0)    : {combined:+.2f}pp")
    print(f"  additive prediction         : {additive:+.2f}pp")
    print(f"  INTERACTION (combined-add)  : {interaction:+.2f}pp")
    ratio = combined / additive if additive != 0 else float("nan")
    print(f"  capture ratio (comb/add)    : {ratio:.2f}x")
    verdict = ("SYNERGY (>110% of additive)" if ratio > 1.10 else
               "ADDITIVE (90-110%)" if ratio >= 0.90 else
               "PARTIAL/INTERFERE (<90%)")
    print(f"  VERDICT: {verdict}")

    # also decompose Sharpe and tail
    print("\n  --- Sharpe decomposition ---")
    bs = M[("10","1.5")]["sharpe"]
    print(f"  base Sharpe {bs:+.2f} | +symexp {M[('14','1.5')]['sharpe']-bs:+.2f} "
          f"| +trail {M[('10','3.0')]['sharpe']-bs:+.2f} "
          f"| combined {M[('14','3.0')]['sharpe']-bs:+.2f}")
    print("\n  --- block-bootstrap tail (worst-month p99) decomposition ---")
    bt = M[("10","1.5")]["p99_mo"]
    print(f"  base p99mo {bt:+.2f} | +symexp {M[('14','1.5')]['p99_mo']-bt:+.2f}pp "
          f"| +trail {M[('10','3.0')]['p99_mo']-bt:+.2f}pp "
          f"| combined {M[('14','3.0')]['p99_mo']-bt:+.2f}pp")
    btd = M[("10","1.5")]["dd_p99"]
    print(f"  base bsDDp99 {btd:+.1f} | +symexp {M[('14','1.5')]['dd_p99']-btd:+.1f}pp "
          f"| +trail {M[('10','3.0')]['dd_p99']-btd:+.1f}pp "
          f"| combined {M[('14','3.0')]['dd_p99']-btd:+.1f}pp")

    pickle.dump(M, open("/tmp/combined_2x2_metrics.pkl", "wb"))


if __name__ == "__main__":
    main()
