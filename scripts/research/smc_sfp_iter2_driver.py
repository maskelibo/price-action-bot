#!/usr/bin/env python3
# ruff: noqa
"""ITER-2 driver: sweep selective-SFP-at-confluence configs on 15m & 1h, report the
HONEST shuffle p_gross plus net edge. Writes JSON to data/_smc_cache/iter2_results.json."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import smc_sfp_backtest as S

ROOT = Path("/Users/peyman/price-action-bot")
OUT = ROOT / "data" / "_smc_cache" / "iter2_results.json"


def run_cfg(uni, p, n_seeds=40):
    per_sym = {}
    all_tr = []
    for sym, df in uni.items():
        tr = S.backtest_symbol(df, p)
        per_sym[sym] = S.summarize(tr)
        all_tr += tr
    agg = S.summarize(all_tr)
    sh = S.shuffle_pvalue(uni, p, n_seeds=n_seeds)
    wf = S.walk_forward_months(uni, p)
    return dict(agg=agg, shuffle=sh, walk_forward=wf, per_symbol=per_sym)


def main():
    tfs = sys.argv[1].split(",") if len(sys.argv) > 1 else ["1h", "15m"]
    universes = {tf: S.load_universe(tf) for tf in tfs}
    for tf in tfs:
        print(f"[load] {tf}: {len(universes[tf])} symbols", file=sys.stderr)

    # Config grid: progressively-selective SFP at confluence, ATR-floored stops, exit variants.
    base = dict(L=3, sweep_lookback=48, min_gap=0.0010, atr_period=14, max_hold=48, entry="A")
    configs = []

    def add(name, **kw):
        configs.append((name, {**base, **kw}))

    # --- A) ATR-floor only, vary k and R (isolate the stop fix on raw SFP) ---
    for k in [1.5, 2.0, 3.0]:
        for R in [2, 3, 4]:
            add(f"floor_k{k}_R{R}", confluence=False, k_atr_floor=k, R=R, tp_mode="fixed")

    # --- B) selective SFP (pool/leg + displacement + MSB bias) + ATR-floor, fixed R ---
    for k in [2.0, 3.0]:
        for R in [2, 3, 4]:
            add(
                f"sel_k{k}_R{R}", confluence=False, k_atr_floor=k, R=R, tp_mode="fixed",
                require_pool=True, eqh_tol_atr=0.10, min_leg_atr=1.0,
                require_displacement=True, disp_body_frac=0.5, use_msb_filter=True,
            )

    # --- C) selective + strict inside-zone confluence (wick INSIDE fresh OB/FVG) ---
    for k in [2.0, 3.0]:
        for R in [2, 3]:
            add(
                f"selconf_k{k}_R{R}", confluence=True, confluence_inside=True, fresh_zone_only=True,
                k_atr_floor=k, R=R, tp_mode="fixed",
                require_pool=True, eqh_tol_atr=0.10, min_leg_atr=1.0,
                require_displacement=True, disp_body_frac=0.5, use_msb_filter=True,
            )

    # --- D) selective + structure-TP and trail exits (capture let-run) ---
    for k in [2.0, 3.0]:
        add(
            f"sel_structTP_k{k}", confluence=False, k_atr_floor=k, tp_mode="structure", R=3,
            require_pool=True, min_leg_atr=1.0, require_displacement=True, use_msb_filter=True,
        )
        add(
            f"sel_trail_k{k}", confluence=False, k_atr_floor=k, tp_mode="trail",
            partial_R=1.0, partial_frac=0.5, be_after_partial=True, trail_atr=2.0,
            require_pool=True, min_leg_atr=1.0, require_displacement=True, use_msb_filter=True,
        )

    # --- E) milder selectivity (pool OR significant-leg, no displacement) to keep n higher ---
    for k in [2.0, 3.0]:
        add(
            f"selmild_k{k}_R3", confluence=False, k_atr_floor=k, R=3, tp_mode="fixed",
            require_pool=True, min_leg_atr=0.0, use_msb_filter=True,
        )

    results = {"git": S._git_hash(), "fee_rt_bps": S.FEE_RT_BPS, "tfs": tfs, "runs": []}
    for tf in tfs:
        uni = universes[tf]
        for name, kw in configs:
            t0 = time.time()
            p = S.Params(**kw)
            r = run_cfg(uni, p, n_seeds=40)
            r["name"] = name
            r["tf"] = tf
            r["params"] = kw
            results["runs"].append(r)
            a = r["agg"]; sh = r["shuffle"]; wf = r["walk_forward"]
            print(
                f"[{tf}] {name:22s} n={a['n']:6d} R0={a['mean_R_0']:+.4f} "
                f"R55={a['mean_R_55']:+.4f} win={a['win']:.1f}% "
                f"p_gross={sh.get('p_gross',1):.3f} wf={wf.get('pos',0)}/{wf.get('months',0)} "
                f"({time.time()-t0:.0f}s)",
                file=sys.stderr,
            )
    OUT.write_text(json.dumps(results, indent=2, default=str))
    print(f"WROTE {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
