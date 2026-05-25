"""SEC32: Phoenix-Scalp v1.0 — 5m Rolling Walk-Forward (Phase 4b).

SEC31 ile aynı pattern, TF=5m, risk YAML=`risk_phoenix_scalp_5m.yaml`.

GATE P4b (master plan §6 ile aynı, sadece WR esnek):
  Ana hedef: yıllık >= +%200, DD en cok -%32, r-adj >= 6.26, WR >= %55
  Alt-gate:  yıllık >= +%50,  DD en cok -%25, r-adj >= 2.0, korelasyon < 0.30

Compute budget (master plan §2.3 + §9):
  - 5y × 10 sym × 5m = 5.26M bar, ~1.5-2M trade pool
  - Tek pencere (2y train) ~ 25-45 dakika single-thread
  - 13 pencere ~ 5-10 saat single-thread
  - Multiprocessing 10-worker hedef: ~1-2 saat
  - NUMBA JIT ZORUNLU (engine + strategies hot path)

Dependencies:
  - data_engineer: 10 sym × 5m × 5y ingest (Phase 1)
                   mevcut: 5m TF data store'da YOK — ingest gerekli (~5.26M bar)
  - signal_chief : 10 strat × 5m lookahead audit PASS
  - risk_officer : configs/risk_phoenix_scalp_5m.yaml hazır
                   FALLBACK: yoksa Phoenix 1d YAML + TODO

Run modes (SEC31 ile aynı):
  - DRY_RUN=1: 1 sym × 1 ay subset
  - varsayılan: full 13-pencere 3y

Output: reports/lab/sec32_phoenix_scalp_5m_results.md
"""
from __future__ import annotations

import io
import os
import sys
import time
from multiprocessing import Pool, cpu_count
from pathlib import Path
from statistics import mean, median

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

from price_action.backtest.lab import ProductionConfig, production_replay
# SEC31'deki yardımcıları yeniden kullan (DRY)
from scripts.sec31_phoenix_scalp_15m_rolling import (
    SYMBOLS_10,
    PHOENIX_STRATEGIES,
    TRAIN_DAYS,
    OOS_DAYS,
    STEP_DAYS,
    TARGET_WINDOWS,
    GATE_PRIMARY,
    GATE_FALLBACK,
    _gather_peakR_single,
    build_windows,
)


TF = "5m"
TF_BAR_MINUTES = 5
DRY_RUN = bool(int(os.environ.get("DRY_RUN", "0")))
PARALLEL = bool(int(os.environ.get("PARALLEL", "0")))
REPORT_OUT = ROOT / "reports" / "lab" / "sec32_phoenix_scalp_5m_results.md"

SCALP_RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_5m.yaml"
FALLBACK_RISK_YAML = ROOT / "configs" / "risk_phoenix_v204.yaml"


def collect_all_trades(symbols: list[str], parallel: bool = True) -> list[dict]:
    """SEC31 pattern, TF=5m fanout."""
    tasks = [(m, c, sym, TF) for m, c in PHOENIX_STRATEGIES for sym in symbols]
    all_trades: list[dict] = []
    t0 = time.time()
    if parallel and len(tasks) > 1:
        n_workers = min(cpu_count() or 4, 10, len(tasks))
        print(f"  [pool] {n_workers}-worker fanout, {len(tasks)} task (TF=5m, compute-heavy)")
        with Pool(processes=n_workers) as pool:
            results = pool.map(_gather_peakR_single, tasks)
        for r in results:
            all_trades.extend(r)
    else:
        for task in tasks:
            print(f"  [serial] {task[0]}/{task[2]}")
            all_trades.extend(_gather_peakR_single(task))
    elapsed = time.time() - t0
    print(f"  [collect] {len(all_trades)} trade, {elapsed:.1f}s ({elapsed/60:.1f} min)")
    return all_trades


def load_risk_config(w_log) -> tuple[ProductionConfig, bool]:
    if SCALP_RISK_YAML.exists():
        cfg = ProductionConfig.from_yaml(str(SCALP_RISK_YAML))
        w_log(f"**Risk YAML:** `{SCALP_RISK_YAML.name}` (scalper 5m, risk_officer Phase 3)")
        return cfg, False
    cfg = ProductionConfig.from_yaml(str(FALLBACK_RISK_YAML))
    w_log("")
    w_log("> **WARNING — FALLBACK YAML:** `risk_phoenix_scalp_5m.yaml` bulunamadı.")
    w_log(f"> Phoenix 1d YAML kullanıldı — sonuçlar **kalibre değil**.")
    w_log("> TODO: risk_officer Phase 3 tamamlayıp re-run gerekli.")
    w_log("")
    return cfg, True


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w(f"# SEC32: Phoenix-Scalp v1.0 — 5m Rolling Walk-Forward")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w(f"**Timeframe:** {TF}")
    w(f"**Mode:** {'DRY_RUN (1 sym × 1 ay)' if DRY_RUN else 'FULL (10 sym × 3y rolling 13 pencere)'}")
    w(f"**Master plan:** reports/ceo/2026-05-16_phoenix_scalp_v1_master_plan.md §4.6 + §6")
    w("")
    w(f"## Champion Baseline (Phoenix v2.0.4 1d)")
    w("")
    w(f"- Yıllık +%200.3 / DD -%32 / r-adj 6.26 / WR %69.7 (13/13 pozitif)")
    w("")
    w(f"## Phase 4b Gate Threshold")
    w("")
    w(f"- **Primary:** annual ≥ +{GATE_PRIMARY['annual_pct']}%, DD ≥ -{GATE_PRIMARY['dd_pct']}%, r-adj ≥ {GATE_PRIMARY['r_adj']}, WR ≥ 55%")
    w(f"- **Fallback:** annual ≥ +{GATE_FALLBACK['annual_pct']}%, DD ≥ -{GATE_FALLBACK['dd_pct']}%, r-adj ≥ {GATE_FALLBACK['r_adj']}, corr < 0.30")
    w("")
    w("> **KILL kriterleri (master plan §7):** Post-fee+slip annual < 0 -> 5m KILL; ")
    w("> daily breaker > 5x/yıl simde -> preset gevşet.")
    w("")

    risk_cfg, fallback_used = load_risk_config(w)

    symbols = SYMBOLS_10[:1] if DRY_RUN else SYMBOLS_10
    w(f"**Universe:** {len(symbols)} sym × {len(PHOENIX_STRATEGIES)} strateji")
    w("")

    # Trade collection
    w("## Trade Toplama (compute-heavy: 5m × 5y × 10 sym × 10 strat)")
    w("")
    t0 = time.time()
    use_parallel = PARALLEL and not DRY_RUN
    all_trades = collect_all_trades(symbols, parallel=use_parallel)
    collect_elapsed = time.time() - t0

    w(f"- Toplanan trade: **{len(all_trades)}**")
    w(f"- Süre: {collect_elapsed:.1f}s ({collect_elapsed/60:.1f} min)")

    if all_trades:
        all_trades.sort(key=lambda x: x["entry_ts"])
        Rs = [t["R"] for t in all_trades]
        wr = sum(1 for r in Rs if r > 0) / len(Rs) * 100
        w(f"- Pool R stats: mean R {sum(Rs)/len(Rs):+.3f}, sumR {sum(Rs):+.1f}, WR {wr:.1f}%")
        n_peak1 = sum(1 for t in all_trades if t["peak_R"] >= 1.0)
        w(f"- peak_R≥1 count: {n_peak1} ({n_peak1*100/len(all_trades):.0f}%)")
        w(f"- Range: {all_trades[0]['entry_ts']} → {all_trades[-1]['exit_ts']}")
    w("")

    if len(all_trades) < 100:
        w(f"**STOP:** Pool < 100 trade — data_engineer 5y × 5m ingest tamamlamadı veya harness debug gerek.")
        REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
        print(f"\nRapor: {REPORT_OUT}")
        return

    # Walk-forward
    if DRY_RUN:
        windows = [(all_trades[0]["entry_ts"], all_trades[-1]["exit_ts"])]
        w(f"**DRY_RUN windows:** 1")
    else:
        windows = build_windows(all_trades)
        w(f"## Walk-Forward Windows ({len(windows)} pencere)")
        w("")
        if len(windows) < TARGET_WINDOWS:
            w(f"> **WARNING:** {len(windows)}/{TARGET_WINDOWS} pencere — span yetersiz, 5y ingest gerekli.")
        w("")

    scenarios = [
        ("PHOENIX 5m default (mc=20)", risk_cfg.with_overrides(max_concurrent=20)),
        ("PHOENIX 5m mc=24 + cooldown=0", risk_cfg.with_overrides(
            max_concurrent=24, same_symbol_side_cooldown_days=0)),
    ]

    period_years = TRAIN_DAYS / 365.0 if not DRY_RUN else max(0.1,
        (all_trades[-1]["exit_ts"] - all_trades[0]["entry_ts"]).days / 365.0)

    w("## Sonuçlar (Rolling, default scenario detayı)")
    w("")
    w(f"| Pencere | Start | End | Trades | Mean R | Annual % | DD % | r-adj | WR % | Breaker | Fee/Slip $ |")
    w(f"|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")

    default_cfg = scenarios[0][1]
    for i, (ws, we) in enumerate(windows, start=1):
        ww_trades = [t for t in all_trades if ws <= t["entry_ts"] < we]
        if not ww_trades:
            w(f"| W{i} | {ws.date()} | {we.date()} | 0 | - | - | - | - | - | - | - |")
            continue
        r = production_replay(ww_trades, default_cfg)
        if r is None:
            w(f"| W{i} | {ws.date()} | {we.date()} | {len(ww_trades)} | - | (replay None) | - | - | - | - | - |")
            continue
        ann = r.annualized(period_years) * 100
        dd = r.max_drawdown * 100
        ra = ann / abs(dd) if dd != 0 else 0
        Rs = [t["R"] for t in ww_trades]
        mR = sum(Rs) / len(Rs) if Rs else 0
        wr = sum(1 for r0 in Rs if r0 > 0) / len(Rs) * 100 if Rs else 0
        breaker_n = getattr(r, "n_breaker_triggers", "n/a")
        fee_slip = getattr(r, "total_fee_slip_usdt", "n/a")
        w(f"| W{i} | {ws.date()} | {we.date()} | {len(ww_trades)} | {mR:+.3f} | "
          f"{ann:+.1f}% | {dd:+.1f}% | {ra:.3f} | {wr:.1f}% | {breaker_n} | {fee_slip} |")

    # Senaryo özeti
    w("")
    w("## Senaryo Özeti")
    w("")
    w(f"| Senaryo | Mean Yıllık | Median | Min | Max | Mean DD | r-adj | Negatif |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|")

    rated = []
    for name, cfg in scenarios:
        anns, dds = [], []
        for ws, we in windows:
            ww_trades = [t for t in all_trades if ws <= t["entry_ts"] < we]
            r = production_replay(ww_trades, cfg)
            if r is None:
                continue
            anns.append(r.annualized(period_years) * 100)
            dds.append(r.max_drawdown * 100)
        if not anns:
            w(f"| {name} | - | - | - | - | - | - | - |")
            continue
        ma, md = mean(anns), mean(dds)
        ra = ma / abs(md) if md != 0 else 0
        neg = sum(1 for a in anns if a < 0)
        rated.append((name, ma, median(anns), md, ra, min(anns), max(anns), neg, len(anns)))
        w(f"| {name} | {ma:+.1f}% | {median(anns):+.1f}% | {min(anns):+.1f}% | {max(anns):+.1f}% | "
          f"{md:+.1f}% | {ra:.3f} | {neg}/{len(anns)} |")

    # Gate karar
    w("")
    w("## Gate Karar (P4b)")
    w("")
    if not rated:
        w("**STOP:** Hiçbir senaryo replay üretmedi.")
    else:
        best = max(rated, key=lambda x: x[4])
        primary_pass = (best[1] >= GATE_PRIMARY["annual_pct"] and
                        abs(best[3]) <= GATE_PRIMARY["dd_pct"] and
                        best[4] >= GATE_PRIMARY["r_adj"])
        fallback_pass = (best[1] >= GATE_FALLBACK["annual_pct"] and
                         abs(best[3]) <= GATE_FALLBACK["dd_pct"] and
                         best[4] >= GATE_FALLBACK["r_adj"])
        w(f"**Best senaryo:** {best[0]}")
        w(f"- Yıllık {best[1]:+.1f}% / DD {best[3]:+.1f}% / r-adj {best[4]:.3f}")
        w("")
        if primary_pass:
            w("**GATE P4b PRIMARY PASS** -> P4c (1m) sprint başlasın.")
        elif fallback_pass:
            w("**GATE P4b FALLBACK PASS** -> P5 (portfolio layer).")
        else:
            w("**GATE P4b FAIL** -> 5m archive, 1m muhtemelen daha kötü (KILL adayı).")

    if fallback_used:
        w("")
        w("> **NOT:** Fallback YAML kullanıldı — sonuçlar gösterge, scalper kalibrasyonu sonrası yeniden çalıştırılmalı.")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
