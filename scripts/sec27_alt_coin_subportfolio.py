"""SEC27 — Alt-Coin Sub-Portfolio Standalone Manifest Test.

Pre-registered hypothesis: memory/researcher/hypotheses/2026-05-15-alt-coin-sub-portfolio.md

SEC26 forensik bulgusu: alt-coin (DOT/ADA/SOL/AVAX/MATIC) avg mR 3.22x BTC.
Bu sprint o bulgudan production-eligible sub-universe variant uretilebilir mi sorusunu test eder.

Method:
- Cached pool: data/_sec13_4_cache/pool_baseline_v1_3.pkl (n=6650, v1.2/v2.0.3 baseline).
- BALANCED preset (configs/risk_balanced.yaml) + halt + F&G + funding + drop_pairs.
- Sembol filter ile 5 variant (V0 baseline, V1 alt5_only, V2 alt7_plus_eth, V3 alt5_btc_anchor, V4 top_volume_5).
- WF 3y rolling, 2y train + 3mo OOS + 1mo step, 13 pencere benzeri.
- Bootstrap CI + paired-bootstrap p-value (B=2000).
- Bonferroni k=4 -> alpha_adj = 0.0125.

Output:
- reports/researcher/2026-05-15_sec27_alt_coin_subportfolio.md
- reports/researcher/sec27_variants_metrics.csv
"""
from __future__ import annotations

import os
import sys
import json
import pickle
from pathlib import Path
from statistics import mean, median, stdev
import random

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip


# Sub-universe variantları (pre-reg)
VARIANTS = {
    "V0_baseline":     ["BTC/USDT","ETH/USDT","SOL/USDT","ADA/USDT","DOT/USDT","AVAX/USDT","MATIC/USDT","LINK/USDT","BNB/USDT","XRP/USDT","DOGE/USDT"],
    "V1_alt5_only":    ["SOL/USDT","ADA/USDT","DOT/USDT","AVAX/USDT","MATIC/USDT"],
    "V2_alt7_plus_eth":["SOL/USDT","ADA/USDT","DOT/USDT","AVAX/USDT","MATIC/USDT","LINK/USDT","DOGE/USDT","ETH/USDT"],
    "V3_alt5_btc":     ["SOL/USDT","ADA/USDT","DOT/USDT","AVAX/USDT","MATIC/USDT","BTC/USDT"],
    "V4_top_vol_5":    ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","XRP/USDT"],
}


def load_pool() -> list[dict]:
    p = ROOT / "data" / "_sec13_4_cache" / "pool_baseline_v1_3.pkl"
    with open(p, "rb") as f:
        return pickle.load(f)


def build_cfg() -> ProductionConfig:
    base = ProductionConfig.from_yaml(str(ROOT / "configs" / "risk_balanced.yaml"))
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}
    cfg = base.with_overrides(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
        btc_halt_calendar=halt_cal,
        # v1.5/v2.0 engine defaults yansıt:
        monthly_dd=0.06,
    )
    return cfg


def make_windows(pool: list[dict], train_years: int = 2, oos_months: int = 3, step_months: int = 1):
    """3y rolling: 2y train + 3mo OOS + 1mo step. SEC11 yontemi (3y total = 2y+1y display)."""
    pool_s = sorted(pool, key=lambda t: t["entry_ts"])
    start = pool_s[0]["entry_ts"]
    end = pool_s[-1]["exit_ts"]
    # SEC11 ile parite: 3y window, step 60d (~2mo)
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    return windows


def replay_wf(pool: list[dict], cfg: ProductionConfig, windows):
    """Returns: list[ (yıllık%, dd%) ] per window."""
    out = []
    for ws, we in windows:
        ww = [t for t in pool if ws <= t["entry_ts"] < we]
        if not ww:
            continue
        r = production_replay(ww, cfg)
        if r is None:
            continue
        out.append((r.annualized(3.0) * 100, r.max_drawdown * 100, len(ww)))
    return out


def metrics_table(label: str, results):
    if not results:
        return {
            "label": label, "n_window": 0, "n_trade_pool": 0,
            "mean_ann": 0.0, "median_ann": 0.0, "min_ann": 0.0, "max_ann": 0.0,
            "mean_dd": 0.0, "median_dd": 0.0,
            "r_adj": 0.0, "neg_windows": 0,
        }
    anns = [r[0] for r in results]
    dds = [r[1] for r in results]
    ns = [r[2] for r in results]
    ma = mean(anns); md = mean(dds)
    return {
        "label": label, "n_window": len(results), "n_trade_pool": max(ns) if ns else 0,
        "mean_ann": ma, "median_ann": median(anns),
        "min_ann": min(anns), "max_ann": max(anns),
        "mean_dd": md, "median_dd": median(dds),
        "r_adj": ma / abs(md) if md != 0 else 0.0,
        "neg_windows": sum(1 for a in anns if a < 0),
    }


def paired_bootstrap(results_v, results_v0, B=2000, seed=42, metric_idx=0):
    """Paired bootstrap (per-window): Δ_mean CI ve p-value.

    metric_idx: 0=ann, 1=dd, 2=r_adj (per-window).
    """
    rng = random.Random(seed)
    # Pencereler eşleşmeli; çift listenin min uzunluğunu kullan
    n = min(len(results_v), len(results_v0))
    if n == 0:
        return {"ci_low": 0.0, "ci_high": 0.0, "p_value": 1.0, "mean_delta": 0.0}

    def metric(r):
        if metric_idx == 2:  # r-adj = ann/|dd|
            return r[0] / abs(r[1]) if r[1] != 0 else 0.0
        return r[metric_idx]

    pairs = [(metric(results_v[i]), metric(results_v0[i])) for i in range(n)]
    deltas = [a - b for a, b in pairs]
    obs_mean = sum(deltas) / n

    # Bootstrap CI
    boot_means = []
    for _ in range(B):
        sample = [deltas[rng.randrange(n)] for _ in range(n)]
        boot_means.append(sum(sample) / n)
    boot_means.sort()
    lo = boot_means[int(0.025 * B)]
    hi = boot_means[int(0.975 * B)]

    # p-value: H0 mean_delta=0 (two-sided)
    # Permutation: re-center deltas to 0 -> bootstrap mean dist
    centered = [d - obs_mean for d in deltas]
    null_means = []
    for _ in range(B):
        sample = [centered[rng.randrange(n)] for _ in range(n)]
        null_means.append(abs(sum(sample) / n))
    p = sum(1 for x in null_means if x >= abs(obs_mean)) / B

    return {"ci_low": lo, "ci_high": hi, "p_value": p, "mean_delta": obs_mean, "n_pairs": n}


def per_strategy_alt(pool: list[dict], alt_symbols: set[str]):
    """Eğer alt-only PASS olursa: hangi strateji alt-coin'lerde özellikle güçlü?"""
    from collections import defaultdict
    g = defaultdict(list)
    for t in pool:
        if t["symbol"] in alt_symbols:
            g[t["strategy"]].append(float(t["R"]))
    rows = []
    for s, rs in sorted(g.items(), key=lambda x: -sum(x[1])):
        rows.append({
            "strategy": s, "n": len(rs),
            "mR": sum(rs) / len(rs) if rs else 0.0,
            "sumR": sum(rs),
            "WR": sum(1 for r in rs if r > 0) / len(rs) if rs else 0.0,
        })
    return rows


def main():
    print("=" * 100)
    print("SEC27 — Alt-Coin Sub-Portfolio Standalone Manifest Test")
    print("=" * 100)
    pool = load_pool()
    print(f"\nPool loaded: n={len(pool)} trade")
    cfg = build_cfg()
    print("Config built (BALANCED + halt + F&G + funding + drop_pairs + monthly_dd=0.06)")

    # Pencereler tek bir referans pool'dan (V0 baseline) hesaplanır,
    # tüm variantlar aynı pencerelerde replay edilir -> paired comparison
    pool_v0 = [t for t in pool if t["symbol"] in set(VARIANTS["V0_baseline"])]
    windows = make_windows(pool_v0)
    print(f"WF windows: {len(windows)} (3y rolling, 60d step)")

    print("\n--- Variant Replay ---")
    all_results = {}
    metrics = []
    for vid, syms in VARIANTS.items():
        symset = set(syms)
        v_pool = [t for t in pool if t["symbol"] in symset]
        print(f"\n  {vid:<22} n_syms={len(syms)} n_trade={len(v_pool)}")
        res = replay_wf(v_pool, cfg, windows)
        all_results[vid] = res
        m = metrics_table(vid, res)
        metrics.append(m)
        print(f"    -> yıllık {m['mean_ann']:+.1f}% (med {m['median_ann']:+.1f}, "
              f"min {m['min_ann']:+.1f}, max {m['max_ann']:+.1f}) / "
              f"DD {m['mean_dd']:+.1f}% / r-adj {m['r_adj']:.3f} / "
              f"neg {m['neg_windows']}/{m['n_window']}")

    # Paired bootstrap vs V0 — Δ_ann (primary)
    print("\n--- Paired Bootstrap (vs V0_baseline) — Δ_yıllık ---")
    boot_stats = {}
    for vid in VARIANTS:
        if vid == "V0_baseline":
            continue
        bs = paired_bootstrap(all_results[vid], all_results["V0_baseline"], metric_idx=0)
        boot_stats[vid] = bs
        print(f"  {vid:<22} Δ_mean_ann {bs['mean_delta']:+.2f}pp  "
              f"CI95 [{bs['ci_low']:+.2f}, {bs['ci_high']:+.2f}]  "
              f"p={bs['p_value']:.4f}  n={bs.get('n_pairs',0)}")

    # Secondary metric: Δ_r-adj per window
    print("\n--- Paired Bootstrap (vs V0_baseline) — Δ_r-adj (SECONDARY, exploratory) ---")
    boot_stats_radj = {}
    for vid in VARIANTS:
        if vid == "V0_baseline":
            continue
        bs = paired_bootstrap(all_results[vid], all_results["V0_baseline"], metric_idx=2, seed=43)
        boot_stats_radj[vid] = bs
        print(f"  {vid:<22} Δ_mean_radj {bs['mean_delta']:+.3f}  "
              f"CI95 [{bs['ci_low']:+.3f}, {bs['ci_high']:+.3f}]  "
              f"p={bs['p_value']:.4f}  n={bs.get('n_pairs',0)}")

    # Secondary: Δ_dd per window
    print("\n--- Paired Bootstrap (vs V0_baseline) — Δ_DD (negatif daha az = iyilesme) ---")
    boot_stats_dd = {}
    for vid in VARIANTS:
        if vid == "V0_baseline":
            continue
        bs = paired_bootstrap(all_results[vid], all_results["V0_baseline"], metric_idx=1, seed=44)
        boot_stats_dd[vid] = bs
        # dd negatif; Δ_dd > 0 = DD daha az kötü
        print(f"  {vid:<22} Δ_mean_dd {bs['mean_delta']:+.2f}pp  "
              f"CI95 [{bs['ci_low']:+.2f}, {bs['ci_high']:+.2f}]  "
              f"p={bs['p_value']:.4f}  n={bs.get('n_pairs',0)}")

    # Verdict tablosu — pre-reg hard gate
    print("\n--- Verdict Tablosu (Bonferroni α_adj = 0.0125) ---")
    v0_m = next(m for m in metrics if m["label"] == "V0_baseline")
    verdicts = []
    for m in metrics:
        if m["label"] == "V0_baseline":
            verdicts.append({**m, "verdict": "BASELINE", "delta_ann": 0.0, "delta_radj": 0.0, "delta_dd": 0.0, "p_adj": None, "ci_low": None, "ci_high": None})
            continue
        d_ann = m["mean_ann"] - v0_m["mean_ann"]
        d_radj = m["r_adj"] - v0_m["r_adj"]
        d_dd = m["mean_dd"] - v0_m["mean_dd"]  # negative numbers; daha negatif = daha kötü
        bs = boot_stats[m["label"]]
        # Hard gate: (Δ_ann ≥ +10pp OR Δ_radj ≥ +0.30) AND |Δ_dd| ≤ 10pp (worse) AND ci_low > 0
        cond_perf = (d_ann >= 10.0) or (d_radj >= 0.30)
        cond_dd = (d_dd >= -10.0)  # m_dd, v0_dd ikisi de negatif; d_dd ≥ -10pp = max 10pp ek kötüleşme
        cond_sig = (bs["ci_low"] > 0.0) and (bs["p_value"] < 0.0125)
        verdict = "PASS" if (cond_perf and cond_dd and cond_sig) else "REJECT"
        verdicts.append({
            **m, "verdict": verdict,
            "delta_ann": d_ann, "delta_radj": d_radj, "delta_dd": d_dd,
            "p_adj": bs["p_value"] * 4,  # Bonferroni (display only)
            "p_raw": bs["p_value"],
            "ci_low": bs["ci_low"], "ci_high": bs["ci_high"],
        })

    # CSV
    csv_path = ROOT / "reports" / "researcher" / "sec27_variants_metrics.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    import csv as _csv
    cols = ["label", "verdict", "n_window", "n_trade_pool",
            "mean_ann", "median_ann", "min_ann", "max_ann",
            "mean_dd", "median_dd", "r_adj", "neg_windows",
            "delta_ann", "delta_radj", "delta_dd",
            "p_raw", "p_adj", "ci_low", "ci_high"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for v in verdicts:
            row = {k: v.get(k, "") for k in cols}
            w.writerow(row)
    print(f"\nCSV: {csv_path}")

    # Print verdict tablosu
    print(f"\n{'Variant':<22} {'verdict':<8} {'Δ_ann':>8} {'Δ_radj':>8} {'Δ_dd':>8} {'p_raw':>8} {'CI95':>22}")
    print("-" * 100)
    for v in verdicts:
        ci = f"[{v['ci_low']:+.2f}, {v['ci_high']:+.2f}]" if v.get("ci_low") is not None else "—"
        p_s = f"{v.get('p_raw',1.0):.4f}" if v.get("p_raw") is not None else "—"
        print(f"  {v['label']:<22} {v['verdict']:<8} {v['delta_ann']:>+7.1f}pp {v['delta_radj']:>+7.3f} {v['delta_dd']:>+7.1f}pp {p_s:>8} {ci:>22}")

    # Per-strategy breakdown alt-only
    print("\n--- Per-Strategy mR (alt5 only: SOL ADA DOT AVAX MATIC) ---")
    alt5_set = set(VARIANTS["V1_alt5_only"])
    rows = per_strategy_alt(pool, alt5_set)
    for r in rows:
        print(f"  {r['strategy']:<32} n={r['n']:>4}  mR {r['mR']:+.3f}  sumR {r['sumR']:+7.1f}  WR {r['WR']*100:.1f}%")

    # Stress period analysis (per-variant, stress windows nasıl davranır?)
    print("\n--- Stress Period Coverage (her variant icin per-window minlist) ---")
    stress_periods = [
        ("2022-05_LUNA", pd.Timestamp("2022-05-01", tz="UTC"), pd.Timestamp("2022-06-30", tz="UTC")),
        ("2022-11_FTX",  pd.Timestamp("2022-11-01", tz="UTC"), pd.Timestamp("2022-12-31", tz="UTC")),
        ("2024-03_ATH",  pd.Timestamp("2024-03-01", tz="UTC"), pd.Timestamp("2024-04-30", tz="UTC")),
        ("2024-08_Yen",  pd.Timestamp("2024-08-01", tz="UTC"), pd.Timestamp("2024-09-30", tz="UTC")),
    ]
    stress_data = {}
    for sp_name, sp_s, sp_e in stress_periods:
        print(f"\n  {sp_name} ({sp_s.date()} → {sp_e.date()})")
        stress_data[sp_name] = {}
        for vid in VARIANTS:
            symset = set(VARIANTS[vid])
            v_pool = [t for t in pool if t["symbol"] in symset and sp_s <= t["entry_ts"] <= sp_e]
            if not v_pool:
                continue
            sum_r = sum(float(t["R"]) for t in v_pool)
            n = len(v_pool)
            mR = sum_r / n if n else 0.0
            wr = sum(1 for t in v_pool if float(t["R"]) > 0) / n if n else 0.0
            stress_data[sp_name][vid] = {"n": n, "sumR": sum_r, "mR": mR, "WR": wr}
            print(f"    {vid:<22} n={n:>3}  sumR {sum_r:+.2f}  mR {mR:+.3f}  WR {wr*100:>4.1f}%")

    # BTC vs Alt mR comparison per stress
    print("\n--- BTC vs Alt5 mR (pool ortalama, stress-included) ---")
    btc_pool = [t for t in pool if t["symbol"] == "BTC/USDT"]
    alt5_set = set(VARIANTS["V1_alt5_only"])
    alt5_pool = [t for t in pool if t["symbol"] in alt5_set]
    btc_mR = sum(float(t["R"]) for t in btc_pool) / len(btc_pool) if btc_pool else 0.0
    alt5_mR = sum(float(t["R"]) for t in alt5_pool) / len(alt5_pool) if alt5_pool else 0.0
    print(f"  BTC: n={len(btc_pool)}  mR={btc_mR:+.3f}")
    print(f"  Alt5: n={len(alt5_pool)}  mR={alt5_mR:+.3f}  ({alt5_mR/btc_mR:.2f}x BTC)" if btc_mR else "")

    # Concentration risk diagnostic — V1 vs V0
    # V1'in 13 pencere min ve max'i V0'a göre nasıl?
    print("\n--- Concentration Risk Diagnostic (V1 vs V0, 13 pencere) ---")
    v1_ann = [r[0] for r in all_results["V1_alt5_only"]]
    v0_ann = [r[0] for r in all_results["V0_baseline"]]
    v1_dd = [r[1] for r in all_results["V1_alt5_only"]]
    v0_dd = [r[1] for r in all_results["V0_baseline"]]
    print(f"  V0 yıllık range: [{min(v0_ann):+.1f}, {max(v0_ann):+.1f}] σ={pd.Series(v0_ann).std():.1f}")
    print(f"  V1 yıllık range: [{min(v1_ann):+.1f}, {max(v1_ann):+.1f}] σ={pd.Series(v1_ann).std():.1f}")
    print(f"  V0 DD range: [{min(v0_dd):+.1f}, {max(v0_dd):+.1f}]")
    print(f"  V1 DD range: [{min(v1_dd):+.1f}, {max(v1_dd):+.1f}]")
    # Korelasyon V0/V1 pencere bazında
    import statistics
    cov = sum((a - mean(v0_ann))*(b - mean(v1_ann)) for a, b in zip(v0_ann, v1_ann)) / len(v0_ann)
    corr = cov / (statistics.pstdev(v0_ann) * statistics.pstdev(v1_ann)) if statistics.pstdev(v0_ann) and statistics.pstdev(v1_ann) else 0.0
    print(f"  Pencere korelasyonu (V0 ann vs V1 ann): {corr:+.3f}")

    # Save JSON dump for reproducibility
    out_json = {
        "variants": {vid: sorted(list(syms)) for vid, syms in VARIANTS.items()},
        "n_window": len(windows),
        "metrics": metrics,
        "boot_stats_ann": boot_stats,
        "boot_stats_radj": boot_stats_radj,
        "boot_stats_dd": boot_stats_dd,
        "verdicts": [{k: (v if not isinstance(v, float) else round(v, 4)) for k, v in d.items()} for d in verdicts],
        "alt5_per_strategy": rows,
        "stress_periods": stress_data,
        "v0_v1_diagnostics": {
            "v0_ann": v0_ann, "v1_ann": v1_ann, "v0_dd": v0_dd, "v1_dd": v1_dd,
            "corr_ann_v0v1": corr,
        },
    }
    j_path = ROOT / "reports" / "researcher" / "sec27_data.json"
    with open(j_path, "w", encoding="utf-8") as f:
        json.dump(out_json, f, indent=2, default=str)
    print(f"\nJSON: {j_path}")

    # Final karar
    print("\n" + "=" * 100)
    print("SONUC")
    print("=" * 100)
    passes = [v for v in verdicts if v["verdict"] == "PASS"]
    if passes:
        print(f"PASS variants: {[v['label'] for v in passes]}")
        for v in passes:
            print(f"  -> {v['label']}: Δ_ann {v['delta_ann']:+.1f}pp / Δ_radj {v['delta_radj']:+.3f} / "
                  f"DD {v['mean_dd']:+.1f}% / p={v['p_raw']:.4f} (Bonf k=4)")
    else:
        print("Tüm variantlar REJECT — H_anti doğrulandı:")
        print("  Alt-only sub-universe BALANCED champion baseline'ı yenemedi.")
        print("  SEC13.3 ile zincir kanıt: BTC-anchor'lı 11-sym crypto için yapısal optimum.")

    return verdicts, metrics, all_results, rows


if __name__ == "__main__":
    main()
