"""SEC48: Regime-Conditional Daily DD — 5m TOP-2 Per-Month Replay.

sec46 baseline vs regime_aware: true karşılaştırması.
Pool: data/sec44_5m_top2_pool.pkl (cached)
Output: reports/lab/sec48_regime_dd_5m_per_month_results.md
"""
from __future__ import annotations

import io
import os
import pickle
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

from price_action.backtest.lab import ProductionConfig, production_replay

CACHE = ROOT / "data" / "sec44_5m_top2_pool.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_5m.yaml"
REPORT = ROOT / "reports" / "lab" / "sec48_regime_dd_5m_per_month_results.md"


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def get_months(pool: list[dict]):
    pool_s = sorted(pool, key=lambda x: x["entry_ts"])
    start_dt = to_utc(pool_s[0]["entry_ts"])
    end_dt = to_utc(pool_s[-1]["entry_ts"])
    months = []
    cur_year, cur_month = start_dt.year, start_dt.month
    while True:
        from datetime import datetime
        m_start = datetime(cur_year, cur_month, 1, tzinfo=timezone.utc)
        if cur_month == 12:
            m_end = datetime(cur_year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            m_end = datetime(cur_year, cur_month + 1, 1, tzinfo=timezone.utc)
        if m_start > end_dt:
            break
        months.append((cur_year, cur_month, m_start, m_end))
        cur_month += 1
        if cur_month > 12:
            cur_month = 1
            cur_year += 1
    return months, pool_s


def replay_monthly(pool_s: list[dict], months: list, cfg: ProductionConfig) -> list[tuple]:
    results = []
    for yr, mo, ms, me in months:
        m_trades = [t for t in pool_s if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_trades) < 10:
            continue
        r = production_replay(m_trades, cfg)
        if r is None:
            continue
        ret_pct = r.total_return * 100
        dd_pct = r.max_drawdown * 100
        ra = ret_pct / abs(dd_pct) if dd_pct != 0 else 0
        Rs = [t["R"] for t in m_trades]
        mR = sum(Rs) / len(Rs)
        wr = sum(1 for x in Rs if x > 0) / len(Rs) * 100
        results.append((yr, mo, len(m_trades), mR, ret_pct, dd_pct, ra, wr))
    return results


def print_summary(label: str, results: list[tuple]) -> dict:
    if not results:
        return {}
    rets = [r[4] for r in results]
    dds = [r[5] for r in results]
    ras = [r[6] for r in results]
    pos = sum(1 for r in rets if r > 0)
    mu = sum(rets) / len(rets)
    std = (sum((x - mu) ** 2 for x in rets) / max(len(rets) - 1, 1)) ** 0.5
    cv = std / abs(mu) if mu != 0 else 0
    print(f"\n--- {label} ---")
    print(f"Aylik mean: {mu:+.2f}%  |  median: {sorted(rets)[len(rets)//2]:+.2f}%")
    print(f"Aylik min : {min(rets):+.2f}%  |  max: {max(rets):+.2f}%")
    print(f"Pozitif ay: {pos}/{len(results)} ({pos/len(results)*100:.0f}%)")
    print(f"Std: {std:.2f}pp  |  CV: {cv*100:.0f}%")
    return {
        "mean": mu, "min": min(rets), "max": max(rets),
        "std": std, "cv": cv * 100, "pos": pos, "n": len(results),
        "dd_mean": sum(dds) / len(dds), "ra_mean": sum(ras) / len(ras),
    }


def main():
    if not CACHE.exists():
        print(f"ERROR: Pool cache eksik: {CACHE}")
        return

    print(f"[LOAD] {CACHE} ({CACHE.stat().st_size / 1e6:.1f} MB)", flush=True)
    with CACHE.open("rb") as fh:
        pool = pickle.load(fh)
    print(f"[POOL] {len(pool):,} trade", flush=True)

    months, pool_s = get_months(pool)
    print(f"[MONTHS] {len(months)} ay", flush=True)

    # Baseline
    print("\n[BUILD] Baseline (regime_aware: false)...", flush=True)
    cfg_base = ProductionConfig.from_yaml(str(YAML))
    cfg_base = cfg_base.with_overrides(daily_dd_regime_aware=False, btc_atr_percentile_calendar=None)
    print("[REPLAY] Baseline aylık...", flush=True)
    results_base = replay_monthly(pool_s, months, cfg_base)
    stats_base = print_summary("BASELINE (static 0.03)", results_base)

    # Regime-aware
    print("\n[BUILD] Regime-aware (regime_aware: true)...", flush=True)
    cfg_regime = ProductionConfig.from_yaml(str(YAML))
    cal_loaded = cfg_regime.btc_atr_percentile_calendar is not None
    print(f"  calendar={'loaded' if cal_loaded else 'MISSING'}", flush=True)
    print("[REPLAY] Regime-aware aylık...", flush=True)
    results_regime = replay_monthly(pool_s, months, cfg_regime)
    stats_regime = print_summary("REGIME-AWARE (dynamic 0.03→0.06)", results_regime)

    # Delta
    if stats_base and stats_regime:
        d_mean = stats_regime["mean"] - stats_base["mean"]
        d_cv = stats_regime["cv"] - stats_base["cv"]
        d_ra = stats_regime["ra_mean"] - stats_base["ra_mean"]
        print(f"\n--- DELTA (Regime-aware vs Baseline) ---")
        print(f"Aylik mean delta : {'+' if d_mean >= 0 else ''}{d_mean:.2f}pp")
        print(f"CV delta         : {'+' if d_cv >= 0 else ''}{d_cv:.1f}pp (negatif = daha istikrarli)")
        print(f"r-adj delta      : {'+' if d_ra >= 0 else ''}{d_ra:.3f}")

    # Markdown
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    out = []
    out.append(f"# SEC48: Regime-Conditional Daily DD — 5m TOP-2 Per-Month\n")
    out.append(f"**Generated:** {datetime.now().isoformat()}\n")
    out.append(f"**YAML:** `{YAML.name}` (regime_aware: true)\n")
    out.append(f"**Pool:** {len(pool):,} trade\n\n")

    # Side-by-side table (ay bazında delta)
    out.append(f"## Ay Bazında Karşılaştırma (ilk 24 ay)\n\n")
    out.append(f"| Ay | Baseline% | Regime% | Delta pp |\n")
    out.append(f"|---|---:|---:|---:|\n")
    base_map = {(r[0], r[1]): r[4] for r in results_base}
    regime_map = {(r[0], r[1]): r[4] for r in results_regime}
    all_keys = sorted(set(base_map.keys()) | set(regime_map.keys()))
    for k in all_keys[:24]:
        b = base_map.get(k)
        rr = regime_map.get(k)
        if b is None or rr is None:
            continue
        d = rr - b
        out.append(f"| {k[0]}-{k[1]:02d} | {b:+.1f}% | {rr:+.1f}% | {'+' if d>=0 else ''}{d:.1f}pp |\n")

    if stats_base and stats_regime:
        out.append(f"\n## Özet\n\n")
        out.append(f"| Metrik | Baseline | Regime-Aware | Delta |\n")
        out.append(f"|---|---:|---:|---:|\n")
        out.append(f"| Aylik mean | {stats_base['mean']:+.2f}% | {stats_regime['mean']:+.2f}% | {stats_regime['mean']-stats_base['mean']:+.2f}pp |\n")
        out.append(f"| Aylik min  | {stats_base['min']:+.2f}% | {stats_regime['min']:+.2f}% | {stats_regime['min']-stats_base['min']:+.2f}pp |\n")
        out.append(f"| CV         | {stats_base['cv']:.1f}% | {stats_regime['cv']:.1f}% | {stats_regime['cv']-stats_base['cv']:+.1f}pp |\n")
        out.append(f"| DD mean    | {stats_base['dd_mean']:+.2f}% | {stats_regime['dd_mean']:+.2f}% | {stats_regime['dd_mean']-stats_base['dd_mean']:+.2f}pp |\n")
        out.append(f"| r-adj mean | {stats_base['ra_mean']:.3f} | {stats_regime['ra_mean']:.3f} | {stats_regime['ra_mean']-stats_base['ra_mean']:+.3f} |\n")

    REPORT.write_text("".join(out), encoding="utf-8")
    print(f"\n[DONE] {REPORT}")


if __name__ == "__main__":
    main()
