"""SEC47: Regime-Conditional Daily DD — 5m TOP-2 Per-Year Replay.

SEC-S1 engineering sprint sonucu doğrulama.
- Pool: data/sec44_5m_top2_pool.pkl (cached)
- YAML: configs/risk_phoenix_scalp_5m.yaml (daily_loss_pct_regime_aware: true)
- Karşılaştırma: sec44 baseline (regime_aware: false / static 0.03) vs sec47 (regime_aware: true)

Hedef:
  Y1 ROI: 8.9% → 50-100% hedef (bear year, volatil = gevşek threshold)
  CV: 105% → 70-80% hedef (yıllık istikrar artışı)

Output: reports/lab/sec47_regime_dd_5m_per_year_results.md
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

import pandas as pd
from price_action.backtest.lab import ProductionConfig, production_replay

CACHE = ROOT / "data" / "sec44_5m_top2_pool.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_5m.yaml"
REPORT = ROOT / "reports" / "lab" / "sec47_regime_dd_5m_per_year_results.md"


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def replay_per_year(pool: list[dict], cfg: ProductionConfig) -> list[tuple]:
    pool_s = sorted(pool, key=lambda x: x["entry_ts"])
    pool_start = to_utc(pool_s[0]["entry_ts"])
    pool_end = to_utc(pool_s[-1]["entry_ts"])

    results = []
    for y_offset in range(5):
        y_start = pool_start + pd.Timedelta(days=365 * y_offset)
        y_end = y_start + pd.Timedelta(days=365)
        if y_end > pool_end:
            y_end = pool_end + pd.Timedelta(days=1)
        y_trades = [t for t in pool_s if y_start <= to_utc(t["entry_ts"]) < y_end]
        if not y_trades:
            results.append((y_offset + 1, y_start.date(), y_end.date(), 0, 0.0, 0.0, 0.0, 0.0, 0.0))
            continue
        r = production_replay(y_trades, cfg)
        if r is None:
            results.append((y_offset + 1, y_start.date(), y_end.date(), len(y_trades), 0.0, 0.0, 0.0, 0.0, 0.0))
            continue
        ann = r.annualized(1.0) * 100
        dd = r.max_drawdown * 100
        ra = ann / abs(dd) if dd != 0 else 0.0
        Rs = [t["R"] for t in y_trades]
        mR = sum(Rs) / len(Rs)
        wr = sum(1 for x in Rs if x > 0) / len(Rs) * 100
        results.append((y_offset + 1, y_start.date(), y_end.date(), len(y_trades), mR, ann, dd, ra, wr))
    return results


def print_table(label: str, results: list[tuple]) -> None:
    print(f"\n--- {label} ---")
    print(f"| Yil | Start | End | n | mR | Annual% | DD% | r-adj | WR% |")
    print(f"|---|---|---|---:|---:|---:|---:|---:|---:|")
    for r in results:
        if r[3] == 0:
            print(f"| Y{r[0]} | {r[1]} | {r[2]} | 0 | - | - | - | - | - |")
            continue
        print(f"| Y{r[0]} | {r[1]} | {r[2]} | {r[3]:,} | {r[4]:+.3f} | {r[5]:+.1f}% | {r[6]:+.1f}% | {r[7]:.3f} | {r[8]:.1f}% |")


def summary_stats(results: list[tuple]) -> dict:
    valid = [r for r in results if r[3] > 0]
    if not valid:
        return {}
    anns = [r[5] for r in valid]
    dds = [r[6] for r in valid]
    ras = [r[7] for r in valid]
    mu = sum(anns) / len(anns)
    std = (sum((a - mu) ** 2 for a in anns) / max(len(anns) - 1, 1)) ** 0.5
    cv = std / abs(mu) if mu != 0 else 0
    return {
        "n": len(valid),
        "mean": mu,
        "median": sorted(anns)[len(anns) // 2],
        "min": min(anns),
        "max": max(anns),
        "std": std,
        "cv": cv * 100,
        "dd_mean": sum(dds) / len(dds),
        "ra_mean": sum(ras) / len(ras),
    }


def main():
    if not CACHE.exists():
        print(f"ERROR: Pool cache eksik: {CACHE}")
        print("Once sec44 calistirin: python scripts/sec44_phoenix_scalp_5m_per_year.py")
        return

    print(f"[LOAD] {CACHE} ({CACHE.stat().st_size / 1e6:.1f} MB)", flush=True)
    with CACHE.open("rb") as fh:
        pool = pickle.load(fh)
    print(f"[POOL] {len(pool):,} trade, mR {sum(t['R'] for t in pool) / len(pool):+.3f}", flush=True)

    # === Baseline (regime_aware: false) ===
    print("\n[BUILD] Baseline config (regime_aware: false)...", flush=True)
    cfg_base = ProductionConfig.from_yaml(str(YAML))
    # Baseline: force regime_aware=False for comparison
    cfg_base = cfg_base.with_overrides(
        daily_dd_regime_aware=False,
        btc_atr_percentile_calendar=None,
    )
    print(f"  daily_dd={cfg_base.daily_dd}, regime_aware={cfg_base.daily_dd_regime_aware}")
    print("[REPLAY] Baseline per-year...", flush=True)
    results_base = replay_per_year(pool, cfg_base)
    print_table("BASELINE (regime_aware=False, static 0.03)", results_base)
    stats_base = summary_stats(results_base)
    if stats_base:
        print(f"  Mean: {stats_base['mean']:+.1f}% | Min: {stats_base['min']:+.1f}% | Max: {stats_base['max']:+.1f}%")
        print(f"  Std:  {stats_base['std']:.1f}pp | CV: {stats_base['cv']:.1f}%")
        print(f"  DD mean: {stats_base['dd_mean']:+.1f}% | r-adj mean: {stats_base['ra_mean']:.3f}")

    # === Regime-aware (regime_aware: true) ===
    print("\n[BUILD] Regime-aware config (regime_aware: true)...", flush=True)
    cfg_regime = ProductionConfig.from_yaml(str(YAML))
    print(f"  daily_dd={cfg_regime.daily_dd}, regime_aware={cfg_regime.daily_dd_regime_aware}")
    print(f"  volatile_multiplier={cfg_regime.daily_dd_volatile_multiplier}")
    print(f"  percentile_low={cfg_regime.regime_percentile_low}, high={cfg_regime.regime_percentile_high}")
    calendar_loaded = cfg_regime.btc_atr_percentile_calendar is not None
    print(f"  btc_atr_percentile_calendar={'loaded' if calendar_loaded else 'MISSING'}")
    if not calendar_loaded:
        print("  WARNING: Calendar yüklenemedi — test ortamı, conservative fallback aktif")
    print("[REPLAY] Regime-aware per-year...", flush=True)
    results_regime = replay_per_year(pool, cfg_regime)
    print_table("REGIME-AWARE (dynamic threshold, volatile=0.06)", results_regime)
    stats_regime = summary_stats(results_regime)
    if stats_regime:
        print(f"  Mean: {stats_regime['mean']:+.1f}% | Min: {stats_regime['min']:+.1f}% | Max: {stats_regime['max']:+.1f}%")
        print(f"  Std:  {stats_regime['std']:.1f}pp | CV: {stats_regime['cv']:.1f}%")
        print(f"  DD mean: {stats_regime['dd_mean']:+.1f}% | r-adj mean: {stats_regime['ra_mean']:.3f}")

    # === Delta ===
    print("\n--- DELTA (Regime-aware vs Baseline) ---")
    print(f"| Yil | Baseline% | Regime% | Delta pp |")
    print(f"|---|---:|---:|---:|")
    for i in range(len(results_base)):
        rb = results_base[i]
        rr = results_regime[i]
        if rb[3] == 0 or rr[3] == 0:
            continue
        delta = rr[5] - rb[5]
        sign = "+" if delta >= 0 else ""
        print(f"| Y{rb[0]} | {rb[5]:+.1f}% | {rr[5]:+.1f}% | {sign}{delta:.1f}pp |")
    if stats_base and stats_regime:
        delta_mean = stats_regime['mean'] - stats_base['mean']
        delta_cv = stats_regime['cv'] - stats_base['cv']
        delta_ra = stats_regime['ra_mean'] - stats_base['ra_mean']
        print(f"\nMean delta: {'+' if delta_mean >= 0 else ''}{delta_mean:.1f}pp")
        print(f"CV delta:   {'+' if delta_cv >= 0 else ''}{delta_cv:.1f}pp (negatif = daha istikrarlı)")
        print(f"r-adj delta:{'+' if delta_ra >= 0 else ''}{delta_ra:.3f}")

    # === Markdown rapor yaz ===
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    out = []
    out.append(f"# SEC47: Regime-Conditional Daily DD — 5m TOP-2 Per-Year Replay\n")
    out.append(f"**Generated:** {datetime.now().isoformat()}\n")
    out.append(f"**YAML:** `{YAML.name}` (daily_loss_pct_regime_aware: true)\n")
    out.append(f"**Pool:** {len(pool):,} trade\n\n")
    out.append(f"## Baseline (static daily_dd=0.03)\n\n")
    out.append(f"| Yil | Start | End | n | mR | Annual% | DD% | r-adj | WR% |\n")
    out.append(f"|---|---|---|---:|---:|---:|---:|---:|---:|\n")
    for r in results_base:
        if r[3] == 0:
            out.append(f"| Y{r[0]} | {r[1]} | {r[2]} | 0 | - | - | - | - | - |\n")
        else:
            out.append(f"| Y{r[0]} | {r[1]} | {r[2]} | {r[3]:,} | {r[4]:+.3f} | {r[5]:+.1f}% | {r[6]:+.1f}% | {r[7]:.3f} | {r[8]:.1f}% |\n")
    if stats_base:
        out.append(f"\n- Mean: **{stats_base['mean']:+.1f}%** | Std: {stats_base['std']:.1f}pp | CV: **{stats_base['cv']:.1f}%**\n")
    out.append(f"\n## Regime-Aware (dynamic threshold, volatile=0.06)\n\n")
    out.append(f"| Yil | Start | End | n | mR | Annual% | DD% | r-adj | WR% |\n")
    out.append(f"|---|---|---|---:|---:|---:|---:|---:|---:|\n")
    for r in results_regime:
        if r[3] == 0:
            out.append(f"| Y{r[0]} | {r[1]} | {r[2]} | 0 | - | - | - | - | - |\n")
        else:
            out.append(f"| Y{r[0]} | {r[1]} | {r[2]} | {r[3]:,} | {r[4]:+.3f} | {r[5]:+.1f}% | {r[6]:+.1f}% | {r[7]:.3f} | {r[8]:.1f}% |\n")
    if stats_regime:
        out.append(f"\n- Mean: **{stats_regime['mean']:+.1f}%** | Std: {stats_regime['std']:.1f}pp | CV: **{stats_regime['cv']:.1f}%**\n")
    if stats_base and stats_regime:
        delta_mean = stats_regime['mean'] - stats_base['mean']
        delta_cv = stats_regime['cv'] - stats_base['cv']
        delta_ra = stats_regime['ra_mean'] - stats_base['ra_mean']
        out.append(f"\n## Delta (Regime-aware vs Baseline)\n\n")
        out.append(f"- Mean ROI delta: **{'+' if delta_mean >= 0 else ''}{delta_mean:.1f}pp**\n")
        out.append(f"- CV delta: **{'+' if delta_cv >= 0 else ''}{delta_cv:.1f}pp** (negatif = daha istikrarli)\n")
        out.append(f"- r-adj delta: **{'+' if delta_ra >= 0 else ''}{delta_ra:.3f}**\n")
        out.append(f"\n## Degerlendirme\n\n")
        out.append(f"- Y1 bear ROI hedefi: +50-100%\n")
        out.append(f"- CV hedefi: <%80\n")
        out.append(f"- Sonuc: {'HEDEF ULASILDI' if stats_regime['min'] > 30 and stats_regime['cv'] < 80 else 'HEDEF ATLANDI'}\n")
    REPORT.write_text("".join(out), encoding="utf-8")
    print(f"\n[DONE] {REPORT}")


if __name__ == "__main__":
    main()
