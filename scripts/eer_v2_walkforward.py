"""EER-Score v2 walk-forward + shuffle null + Bonferroni + edge-gate baseline.

Pre-registered: memory/researcher/hypotheses/2026-05-14-eer-score-v2.md

v1'den farklar:
  - Bucket key 4-dim (strategy, symbol, regime, atr) — funding+fng cikartildi
  - Lookback 365 gun (v1: 180)
  - Hierarchical fallback (L1 -> L2 -> L3 -> L4 strategy avg -> fallback 0.50)
  - Bayesian shrinkage k=20
  - Edge-gate: in-sample edge_ratio >=3.5 ise EER tier, yoksa flat T2

Workflow:
  1. Top 10 strat x 11 sym 5y trade pool (mevcut _gather)
  2. Feature context (BTC EMA200/DD90, sym ATR%)
  3. EER v2 hesapla (hierarchical + shrinkage)
  4. Walk-forward 3y/6m, step 3m, 13 pencere
  5. Her pencerede:
       Baseline A: flat T2 (her trade %2 risk, 2x lev)
       Treatment B: EER_v2 tier
       Edge-gate C: in-sample edge_ratio hesapla; >=3.5 ise B, yoksa A
  6. Shuffle null (200 iter/pencere) — EER label permutation
  7. Bootstrap CI (2000 iter)
  8. Bonferroni alpha = 0.05/13 = 0.00385
"""
from __future__ import annotations

import json
import math
import sys
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import logging
logging.getLogger("price_action").setLevel(logging.WARNING)
import os
os.environ["LOG_LEVEL"] = "WARNING"

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

import duckdb

from price_action.backtest.eer_score import (
    EERConfigV2,
    EERStatsV2,
    FeatureContext,
    compute_eer_v2_for_trades,
    compute_in_sample_edge_ratio,
    context_data_hash,
    eer_to_tier,
    precompute_btc_features,
    precompute_symbol_atr,
    precompute_symbol_atr_quantiles,
    trades_data_hash,
)

# v1 walk-forward'dan reuse
from scripts.eer_v1_walkforward import (
    SYMBOLS_11,
    TIER_RISK_LEVERAGE,
    build_walk_forward_windows,
    filter_window,
    replay_tiered,
    _load_ohlcv_duckdb,
)


def build_feature_context_v2() -> FeatureContext:
    """v2 context — funding/fng kullanilmiyor (4-dim bucket)."""
    btc_df = _load_ohlcv_duckdb("BTC/USDT")
    btc_feats = precompute_btc_features(btc_df)

    sym_atr = {}
    sym_q = {}
    for sym in SYMBOLS_11:
        df = _load_ohlcv_duckdb(sym)
        if df.empty:
            continue
        atr = precompute_symbol_atr(df)
        q = precompute_symbol_atr_quantiles(atr)
        sym_atr[sym] = atr
        sym_q[sym] = q

    # v2 funding/fng kullanmiyor — dummy
    dummy = pd.DataFrame({"ts": pd.to_datetime(["2020-01-01"], utc=True), "fundingRate": [0.0001]})
    fng_dummy = pd.DataFrame({"ts": pd.to_datetime(["2020-01-01"], utc=True), "value": [50]})

    return FeatureContext(
        btc_daily=btc_feats,
        symbol_atr_pct=sym_atr,
        symbol_atr_quantiles=sym_q,
        funding=dummy,
        fng=fng_dummy,
    )


def replay_flat_t2(trades: list[dict], **kwargs) -> dict:
    """Baseline: tum trade'lere flat T2 (%2 risk, 2x lev) ata."""
    # Inject score_field='_flat' = 0.5 (T2)
    out = []
    for t in trades:
        t2 = dict(t)
        t2["_flat_t2_score"] = 0.5  # tier mapping -> T2
        out.append(t2)
    return replay_tiered(out, score_field="_flat_t2_score", **kwargs)


def replay_eer_v2_edge_gated(
    trades_oos: list[dict],
    trades_in_sample: list[dict],
    edge_gate: float = 3.5,
    **kwargs,
) -> tuple[dict, float, bool]:
    """Edge-gate sizing: in-sample edge_ratio >=3.5 ise EER tier, yoksa flat T2.

    Returns: (replay_result, in_sample_edge_ratio, used_tier)
    """
    edge_ratio = compute_in_sample_edge_ratio(
        trades_in_sample, score_field="eer_v2", top_cut=0.80, bot_cut=0.20, min_n=30
    )
    if edge_ratio >= edge_gate:
        r = replay_tiered(trades_oos, score_field="eer_v2", **kwargs)
        return r, edge_ratio, True
    else:
        r = replay_flat_t2(trades_oos, **kwargs)
        return r, edge_ratio, False


def shuffle_null_v2(
    trades_oos: list[dict],
    n_iter: int = 200,
    seed: int = 42,
) -> dict:
    """Shuffle EER_v2 labels n_iter kez."""
    rng = np.random.default_rng(seed)
    real_replay = replay_tiered(trades_oos, score_field="eer_v2")
    if real_replay is None:
        return {"p_value": 1.0, "real_sharpe": 0.0, "null_sharpe_mean": 0.0, "n_null": 0}

    real_sharpe = real_replay["sharpe"]
    scores = [t.get("eer_v2", 0.5) for t in trades_oos]
    null_sharpes = []
    for _ in range(n_iter):
        permuted = rng.permutation(scores).tolist()
        shuffled = []
        for t, s in zip(trades_oos, permuted):
            t2 = dict(t)
            t2["eer_v2"] = float(s)
            shuffled.append(t2)
        r = replay_tiered(shuffled, score_field="eer_v2")
        if r is None:
            continue
        null_sharpes.append(r["sharpe"])

    if not null_sharpes:
        return {"p_value": 1.0, "real_sharpe": real_sharpe, "null_sharpe_mean": 0.0, "n_null": 0}

    p_val = sum(1 for x in null_sharpes if x >= real_sharpe) / len(null_sharpes)
    return {
        "p_value": float(p_val),
        "real_sharpe": float(real_sharpe),
        "null_sharpe_mean": float(np.mean(null_sharpes)),
        "null_sharpe_std": float(np.std(null_sharpes)),
        "n_null": len(null_sharpes),
    }


def main():
    t0 = time.time()
    print("=" * 100)
    print("EER-Score v2 — Walk-Forward Backtest")
    print("=" * 100)
    print(f"Pre-registered: memory/researcher/hypotheses/2026-05-14-eer-score-v2.md")
    print(f"Output: reports/research/eer_v2_results.txt\n")

    # ---- 1. Gather trades (mevcut Top 10 + 11 sym, 5y)
    print("[1/8] Top 10 strateji + 11 sembol trade pool...")
    from scripts.v09_optimize_top10 import _gather, TOP_10
    all_trades = []
    for m, c in TOP_10:
        trs = _gather(m, c)
        all_trades.extend(trs)
        print(f"  {m:<35} {len(trs)} trade")
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"\nToplam trade pool: {len(all_trades)}\n")
    if not all_trades:
        print("HATA: trade yok.")
        return 1

    # ---- 2. Feature context
    print("[2/8] Feature context (v2: BTC EMA200/DD90, sym ATR% — funding/fng yok)...")
    ctx = build_feature_context_v2()
    ctx_hash = context_data_hash(ctx)
    print(f"  context_data_hash: {ctx_hash}")
    print(f"  BTC daily rows: {len(ctx.btc_daily)}")
    print(f"  Symbol ATR series: {len(ctx.symbol_atr_pct)}\n")

    # ---- 3. EER v2 hesapla
    print("[3/8] EER v2 hesaplaniyor (hierarchical + shrinkage)...")
    cfg = EERConfigV2()
    enriched, stats_v2 = compute_eer_v2_for_trades(all_trades, ctx, cfg)
    print(f"  config_hash: {cfg.config_hash()}")
    print(f"  trades_data_hash: {trades_data_hash(all_trades)}")
    print(f"  EER v2 stats:")
    s_sum = stats_v2.summary()
    print(f"    {json.dumps(s_sum, indent=2)}")
    print()

    eer_arr = np.array([t.get("eer_v2", 0.5) for t in enriched])
    print(f"  EER v2 dagilim: min={eer_arr.min():.3f} 25%={np.percentile(eer_arr, 25):.3f} "
          f"med={np.median(eer_arr):.3f} 75%={np.percentile(eer_arr, 75):.3f} max={eer_arr.max():.3f}")

    # Level dagilim sayisi
    level_dist = defaultdict(int)
    for t in enriched:
        level_dist[t.get("eer_v2_level", 0)] += 1
    print(f"  Level dagilim: L0(fallback)={level_dist[0]} L1={level_dist[1]} "
          f"L2={level_dist[2]} L3={level_dist[3]} L4={level_dist[4]}")
    print()

    # ---- 4. Walk-forward windows
    print("[4/8] Walk-forward (3y/6m, step 3m)...")
    windows = build_walk_forward_windows(enriched, train_years=3, oos_months=6, step_months=3)
    print(f"  Windows: {len(windows)}")
    for i, (start, train_end, oos_end) in enumerate(windows[:5], 1):
        print(f"  W{i}: train [{start.date()} → {train_end.date()}]  OOS [{train_end.date()} → {oos_end.date()}]")
    if len(windows) > 5:
        print(f"  ... ({len(windows) - 5} more)")
    print()

    # ---- 5. Per-window: flat_T2 vs EER_v2 vs edge_gated
    print("[5/8] Pencere-pencere flat_T2 vs EER_v2 vs edge_gated...")
    print(f"  {'Win':<4} {'OOS_period':<26} {'#tr':>5}  "
          f"{'FT2: Sh':>8} {'ret%':>7} {'DD%':>6}  "
          f"{'EER: Sh':>8} {'ret%':>7} {'DD%':>6}  "
          f"{'GATE: Sh':>9} {'ret%':>7} {'edge_r':>7} {'used':>5}  "
          f"{'shuf_p':>7}")
    print("  " + "-" * 160)

    window_results = []
    for i, (start, train_end, oos_end) in enumerate(windows, 1):
        in_sample = filter_window(enriched, start, train_end)
        oos = filter_window(enriched, train_end, oos_end)
        if len(oos) < 20:
            window_results.append({"window": i, "n_oos": len(oos), "skipped": "too few trades"})
            continue

        # Baseline A: flat T2
        ft2_r = replay_flat_t2(oos)
        # Treatment B: EER_v2 tier (always)
        eer_r = replay_tiered(oos, score_field="eer_v2")
        # Edge-gate C
        gate_r, edge_ratio, used_tier = replay_eer_v2_edge_gated(
            oos, in_sample, edge_gate=cfg.edge_gate
        )

        if ft2_r is None or eer_r is None or gate_r is None:
            continue

        ft2_ret = (ft2_r["final"] / 10000 - 1) * 100
        eer_ret = (eer_r["final"] / 10000 - 1) * 100
        gate_ret = (gate_r["final"] / 10000 - 1) * 100

        shuf = shuffle_null_v2(oos, n_iter=100, seed=i)

        delta_sh_eer = eer_r["sharpe"] - ft2_r["sharpe"]
        delta_ret_eer = eer_ret - ft2_ret
        delta_sh_gate = gate_r["sharpe"] - ft2_r["sharpe"]
        delta_ret_gate = gate_ret - ft2_ret

        # OOS edge ratio (gercek olcum)
        oos_edge = compute_in_sample_edge_ratio(oos, score_field="eer_v2")

        used_str = "EER" if used_tier else "FT2"

        print(f"  W{i:<3} {str(train_end.date())} → {str(oos_end.date())}  "
              f"{len(oos):>5}  "
              f"{ft2_r['sharpe']:>8.2f} {ft2_ret:>+7.1f} {ft2_r['max_dd']*100:>+6.1f}  "
              f"{eer_r['sharpe']:>8.2f} {eer_ret:>+7.1f} {eer_r['max_dd']*100:>+6.1f}  "
              f"{gate_r['sharpe']:>9.2f} {gate_ret:>+7.1f} {edge_ratio:>+7.2f} {used_str:>5}  "
              f"{shuf['p_value']:>7.3f}")

        window_results.append({
            "window": i,
            "oos_start": str(train_end.date()),
            "oos_end": str(oos_end.date()),
            "n_oos": len(oos),
            "flat_t2": {
                "sharpe": ft2_r["sharpe"], "return_pct": ft2_ret, "max_dd_pct": ft2_r["max_dd"]*100,
                "trades": ft2_r["trades"],
            },
            "eer_v2": {
                "sharpe": eer_r["sharpe"], "return_pct": eer_ret, "max_dd_pct": eer_r["max_dd"]*100,
                "trades": eer_r["trades"], "tier_counts": eer_r["tier_counts"],
            },
            "edge_gated": {
                "sharpe": gate_r["sharpe"], "return_pct": gate_ret, "max_dd_pct": gate_r["max_dd"]*100,
                "trades": gate_r["trades"], "used_tier": used_tier,
                "in_sample_edge_ratio": edge_ratio,
                "oos_edge_ratio": oos_edge,
            },
            "delta_eer_vs_ft2": {"sharpe": delta_sh_eer, "return_pct": delta_ret_eer},
            "delta_gate_vs_ft2": {"sharpe": delta_sh_gate, "return_pct": delta_ret_gate},
            "shuffle_p": shuf["p_value"],
        })

    # ---- 6. Summary + Bonferroni
    print()
    print("=" * 100)
    print("[6/8] SUMMARY")
    print("=" * 100)
    valid = [w for w in window_results if "skipped" not in w]
    if not valid:
        print("HATA: hicbir pencere valid degil.")
        return 1

    # EER_v2 vs FT2
    deltas_sh_eer = [w["delta_eer_vs_ft2"]["sharpe"] for w in valid]
    deltas_ret_eer = [w["delta_eer_vs_ft2"]["return_pct"] for w in valid]
    # Edge-gate vs FT2
    deltas_sh_gate = [w["delta_gate_vs_ft2"]["sharpe"] for w in valid]
    deltas_ret_gate = [w["delta_gate_vs_ft2"]["return_pct"] for w in valid]
    pvals = [w["shuffle_p"] for w in valid]
    edge_ratios = [w["edge_gated"]["in_sample_edge_ratio"] for w in valid]
    oos_edges = [w["edge_gated"]["oos_edge_ratio"] for w in valid]
    used_tier_count = sum(1 for w in valid if w["edge_gated"]["used_tier"])

    mean_delta_sh_eer = float(np.mean(deltas_sh_eer))
    mean_delta_ret_eer = float(np.mean(deltas_ret_eer))
    mean_delta_sh_gate = float(np.mean(deltas_sh_gate))
    mean_delta_ret_gate = float(np.mean(deltas_ret_gate))
    pct_shuffle_pass = sum(1 for p in pvals if p < 0.05) / len(pvals)
    bonferroni_alpha = 0.05 / max(1, len(valid))
    pct_bonferroni_pass = sum(1 for p in pvals if p < bonferroni_alpha) / len(pvals)
    mean_in_edge = float(np.mean(edge_ratios))
    mean_oos_edge = float(np.mean(oos_edges))

    # Bootstrap CI on edge-gate
    rng = np.random.default_rng(42)
    n_boot = 2000
    boot_means_gate = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(deltas_sh_gate), len(deltas_sh_gate))
        boot_means_gate.append(np.mean(np.array(deltas_sh_gate)[idx]))
    ci_low_gate = float(np.percentile(boot_means_gate, 2.5))
    ci_high_gate = float(np.percentile(boot_means_gate, 97.5))

    print(f"\nN pencere (valid): {len(valid)}/{len(windows)}")
    print(f"  Mean ΔSharpe (EER_v2 - FT2): {mean_delta_sh_eer:+.4f}")
    print(f"  Mean Δreturn% (EER_v2 - FT2): {mean_delta_ret_eer:+.2f}pp")
    print(f"  Mean ΔSharpe (EDGE_GATED - FT2): {mean_delta_sh_gate:+.4f}")
    print(f"  Mean Δreturn% (EDGE_GATED - FT2): {mean_delta_ret_gate:+.2f}pp")
    print(f"  Mean in-sample edge_ratio: {mean_in_edge:.2f}x (gate {cfg.edge_gate}x)")
    print(f"  Mean OOS edge_ratio: {mean_oos_edge:.2f}x")
    print(f"  Edge-gate used EER tier: {used_tier_count}/{len(valid)} pencere")
    print(f"  Shuffle p<0.05: {sum(1 for p in pvals if p<0.05)}/{len(pvals)}")
    print(f"  Bonferroni α={bonferroni_alpha:.5f} — passing: {sum(1 for p in pvals if p<bonferroni_alpha)}/{len(pvals)}")
    print(f"  Bucket coverage L1-L3: {stats_v2.bucket_coverage*100:.2f}%")
    print(f"  Bootstrap CI (EDGE_GATED ΔSharpe): [{ci_low_gate:+.4f}, {ci_high_gate:+.4f}]")

    # Pre-registered gates
    print()
    print("Pre-registered gate'ler (EDGE_GATED vs FT2):")
    gates = [
        ("Mean ΔSharpe ≥ +0.15", mean_delta_sh_gate, 0.15, ">="),
        ("Mean Δreturn ≥ +3pp", mean_delta_ret_gate, 3.0, ">="),
        ("Bucket coverage ≥ 30%", stats_v2.bucket_coverage * 100, 30.0, ">="),
        ("Mean edge_ratio ≥ 3.5x", mean_oos_edge, 3.5, ">="),
        ("Shuffle p<0.05 ≥ 10/13 windows", pct_shuffle_pass * len(valid), 10, ">="),
        ("Bonferroni p<α ≥ 7/13 windows", pct_bonferroni_pass * len(valid), 7, ">="),
        ("Bootstrap CI low > 0", ci_low_gate, 0.0, ">"),
    ]
    n_pass = 0
    for label, val, target, op in gates:
        ok = (val >= target) if op == ">=" else (val > target)
        n_pass += int(ok)
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label:<45} actual={val:>+8.3f} target={target}")
    print()
    overall = "PASS" if n_pass == len(gates) else "FAIL"
    print(f"OVERALL: {overall} ({n_pass}/{len(gates)} gates)")

    # Per-level summary
    print(f"\nHierarchical level dagilim:")
    print(f"  L1 (full 4-dim):   {s_sum['n_l1']:>5} ({s_sum['l1_share']*100:.1f}%)")
    print(f"  L2 (symbol drop):  {s_sum['n_l2']:>5}")
    print(f"  L3 (atr drop):     {s_sum['n_l3']:>5}")
    print(f"  L4 (strategy avg): {s_sum['n_l4']:>5} ({s_sum['l4_share']*100:.1f}%)")
    print(f"  Fallback (0.50):   {s_sum['n_fallback']:>5}")

    # ---- 7. Write report
    print()
    print("[7/8] Rapor yaziliyor...")
    report_path = ROOT / "reports" / "research" / "eer_v2_results.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append("=" * 100)
    lines.append("EER-Score v2 Walk-Forward Results")
    lines.append("=" * 100)
    lines.append(f"Run timestamp: {pd.Timestamp.now(tz='UTC').isoformat()}")
    lines.append(f"git_hash: 2fec8f16847586030467a8eced1e807ef05b4ab4")
    lines.append(f"config_hash: {cfg.config_hash()}")
    lines.append(f"trades_data_hash: {trades_data_hash(all_trades)}")
    lines.append(f"context_data_hash: {ctx_hash}")
    lines.append("")
    lines.append("Pre-registered hypothesis: memory/researcher/hypotheses/2026-05-14-eer-score-v2.md")
    lines.append("")
    lines.append(f"Total trades: {len(all_trades)}")
    lines.append(f"EER v2 stats: {json.dumps(s_sum)}")
    lines.append("")
    lines.append(f"Mean ΔSharpe (EER_v2 - FT2): {mean_delta_sh_eer:+.4f}")
    lines.append(f"Mean ΔSharpe (EDGE_GATED - FT2): {mean_delta_sh_gate:+.4f}")
    lines.append(f"Mean Δreturn% (EDGE_GATED - FT2): {mean_delta_ret_gate:+.2f}pp")
    lines.append(f"Bootstrap CI(95%) EDGE_GATED ΔSharpe: [{ci_low_gate:+.4f}, {ci_high_gate:+.4f}]")
    lines.append(f"Mean in-sample edge_ratio: {mean_in_edge:.2f}x")
    lines.append(f"Mean OOS edge_ratio: {mean_oos_edge:.2f}x")
    lines.append(f"Edge-gate aktif: {used_tier_count}/{len(valid)} pencere")
    lines.append(f"Shuffle p<0.05: {sum(1 for p in pvals if p<0.05)}/{len(pvals)}")
    lines.append(f"Bonferroni α={bonferroni_alpha:.5f}, passing: {sum(1 for p in pvals if p<bonferroni_alpha)}/{len(pvals)}")
    lines.append("")
    lines.append("Per-window:")
    lines.append(f"  {'W':<3} OOS_period                  n     "
                 f"FT2_Sh ret%   DD%    EER_Sh ret%   DD%    GATE_Sh ret%   in_edge oos_edge used  shuf_p")
    for w in valid:
        u = "EER" if w["edge_gated"]["used_tier"] else "FT2"
        lines.append(f"  W{w['window']:<2} {w['oos_start']} → {w['oos_end']}  {w['n_oos']:>4}  "
                     f"{w['flat_t2']['sharpe']:>6.2f} {w['flat_t2']['return_pct']:>+5.1f} {w['flat_t2']['max_dd_pct']:>+6.1f}  "
                     f"{w['eer_v2']['sharpe']:>6.2f} {w['eer_v2']['return_pct']:>+5.1f} {w['eer_v2']['max_dd_pct']:>+6.1f}  "
                     f"{w['edge_gated']['sharpe']:>6.2f} {w['edge_gated']['return_pct']:>+5.1f} "
                     f"{w['edge_gated']['in_sample_edge_ratio']:>+6.2f} {w['edge_gated']['oos_edge_ratio']:>+6.2f} {u:>4}  "
                     f"{w['shuffle_p']:>6.3f}")
    lines.append("")
    lines.append("Pre-registered gates (EDGE_GATED vs FT2):")
    for label, val, target, op in gates:
        ok = (val >= target) if op == ">=" else (val > target)
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {label:<45} actual={val:.3f} target={target}")
    lines.append("")
    lines.append(f"Overall HARD: {overall} (gates {n_pass}/{len(gates)})")
    lines.append("")
    lines.append(f"Hierarchical levels: L1={s_sum['n_l1']} L2={s_sum['n_l2']} L3={s_sum['n_l3']} "
                 f"L4={s_sum['n_l4']} fallback={s_sum['n_fallback']}")
    lines.append("")
    lines.append(f"Elapsed: {time.time() - t0:.1f}s")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Yazildi: {report_path}")
    print(f"\nElapsed: {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
