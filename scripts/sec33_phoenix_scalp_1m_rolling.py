"""SEC33: Phoenix-Scalp v1.0 — 1m Rolling Walk-Forward (Phase 4c).

EXTREME COMPUTE WARNING: 5y × 10 sym × 1m × 10 strat ≈ 5-10M trade pool,
single-thread replay 72-168 saat (1 hafta+). NUMBA + multiprocessing ZORUNLU.

Master plan §2.3 + §9: 1m KILL kriteri compute > 168h.

GATE P4c (master plan §6):
  Ana hedef: yıllık >= +%200, DD en cok -%32, r-adj >= 6.26, WR >= %50
  Alt-gate:  yıllık >= +%50,  DD en cok -%25, r-adj >= 2.0, corr < 0.30

KILL kriterleri (özel 1m §7):
  - Maker fill rate < %50 sim'de -> taker fee × hız ROI imkansız -> KILL
  - Compute > 168h -> KILL ya da 3y'ye düşür + tekrar değerlendir
  - Post-fee+slip annual return < 0 -> KILL

Dependencies:
  - data_engineer: 10 sym × 1m × 5y ingest (~26.3M bar, 1m kapasite 95% gerek)
                   mevcut: 1m TF data store'da YOK
                   KILL: 1m bar coverage < %95 -> 1m TF iptal
  - signal_chief : 10 strat × 1m audit PASS
  - risk_officer : configs/risk_phoenix_scalp_1m.yaml hazır
                   risk_per_trade %0.5 (fee erosion), maker-only mode (post-only)
  - execution_chief: 1m maker fill rate sim >= %50 GEREKLI

Output: reports/lab/sec33_phoenix_scalp_1m_results.md
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


TF = "1m"
TF_BAR_MINUTES = 1
DRY_RUN = bool(int(os.environ.get("DRY_RUN", "0")))
PARALLEL = bool(int(os.environ.get("PARALLEL", "0")))
REPORT_OUT = ROOT / "reports" / "lab" / "sec33_phoenix_scalp_1m_results.md"

SCALP_RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_1m.yaml"
FALLBACK_RISK_YAML = ROOT / "configs" / "risk_phoenix_v204.yaml"

# Compute kill threshold (master plan §7.5)
COMPUTE_KILL_HOURS = 168  # 1 hafta


def collect_all_trades(symbols: list[str], parallel: bool = True) -> tuple[list[dict], float]:
    """SEC31 pattern, TF=1m extreme fanout."""
    tasks = [(m, c, sym, TF) for m, c in PHOENIX_STRATEGIES for sym in symbols]
    all_trades: list[dict] = []
    t0 = time.time()
    if parallel and len(tasks) > 1:
        n_workers = min(cpu_count() or 4, 10, len(tasks))
        print(f"  [pool] {n_workers}-worker EXTREME fanout, {len(tasks)} task (TF=1m)")
        print(f"  WARNING: estimated 72-168h single-thread, multiprocessing critical")
        with Pool(processes=n_workers) as pool:
            results = pool.map(_gather_peakR_single, tasks)
        for r in results:
            all_trades.extend(r)
    else:
        for task in tasks:
            print(f"  [serial] {task[0]}/{task[2]}")
            all_trades.extend(_gather_peakR_single(task))
    elapsed = time.time() - t0
    print(f"  [collect] {len(all_trades)} trade, {elapsed:.1f}s ({elapsed/3600:.2f}h)")
    return all_trades, elapsed


def load_risk_config(w_log) -> tuple[ProductionConfig, bool]:
    if SCALP_RISK_YAML.exists():
        cfg = ProductionConfig.from_yaml(str(SCALP_RISK_YAML))
        w_log(f"**Risk YAML:** `{SCALP_RISK_YAML.name}` (scalper 1m, risk_per_trade %0.5, maker-only)")
        return cfg, False
    cfg = ProductionConfig.from_yaml(str(FALLBACK_RISK_YAML))
    w_log("")
    w_log("> **WARNING — FALLBACK YAML:** `risk_phoenix_scalp_1m.yaml` bulunamadı.")
    w_log(f"> Phoenix 1d YAML (`{FALLBACK_RISK_YAML.name}`) kullanıldı.")
    w_log(f"> 1m için bu **CRITICAL FAIL**: risk_per_trade %4 → fee/yıl >%4000 (ROI sıfırlanır).")
    w_log("> TODO: risk_officer Phase 3 tamamlayıp re-run zorunlu.")
    w_log("")
    return cfg, True


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w(f"# SEC33: Phoenix-Scalp v1.0 — 1m Rolling Walk-Forward")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w(f"**Timeframe:** {TF} (EXTREME compute — 5-10M trade pool tahmini)")
    w(f"**Mode:** {'DRY_RUN (1 sym × 1 ay)' if DRY_RUN else 'FULL'}")
    w(f"**Master plan:** reports/ceo/2026-05-16_phoenix_scalp_v1_master_plan.md §4.6 + §6 + §7")
    w("")
    w(f"## CEO Honest Forecast (master plan §2.5)")
    w("")
    w(f"- 1m ana hedef olasılığı: **5-15%**")
    w(f"- 1m alt-gate olasılığı: **10-25%**")
    w(f"- Beklenen ROI: -%50 ile +%40 / DD -%40 ile -%85")
    w(f"- KILL beklentisi: yüksek (fee+slip+market impact fizik sınırı)")
    w("")
    w(f"## KILL Kriterleri (master plan §7 + 1m özel)")
    w("")
    w(f"1. Post-fee+slip annual < 0 -> 1m KILL")
    w(f"2. Maker fill rate < %50 -> 1m KILL (taker imkansız)")
    w(f"3. Compute > {COMPUTE_KILL_HOURS}h -> 1m KILL veya 3y'ye düşür")
    w(f"4. Side-cond DD breaker > 8x/yıl -> preset rejected")
    w("")

    risk_cfg, fallback_used = load_risk_config(w)

    symbols = SYMBOLS_10[:1] if DRY_RUN else SYMBOLS_10
    w(f"**Universe:** {len(symbols)} sym × {len(PHOENIX_STRATEGIES)} strateji")
    w("")

    # Trade collection (EXTREME)
    w("## Trade Toplama (EXTREME compute)")
    w("")
    t0 = time.time()
    use_parallel = PARALLEL and not DRY_RUN
    all_trades, collect_elapsed = collect_all_trades(symbols, parallel=use_parallel)

    w(f"- Toplanan trade: **{len(all_trades)}**")
    w(f"- Süre: {collect_elapsed:.1f}s ({collect_elapsed/3600:.2f}h)")

    if collect_elapsed > COMPUTE_KILL_HOURS * 3600:
        w(f"**COMPUTE KILL TETİKLENDİ:** {collect_elapsed/3600:.1f}h > {COMPUTE_KILL_HOURS}h limit")
        w(f"Karar: 3y'ye düşür ya da 1m KILL (master plan §7.5)")
        REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
        print(f"\nRapor: {REPORT_OUT}")
        return

    if all_trades:
        all_trades.sort(key=lambda x: x["entry_ts"])
        Rs = [t["R"] for t in all_trades]
        wr = sum(1 for r in Rs if r > 0) / len(Rs) * 100
        w(f"- Pool R stats: mean R {sum(Rs)/len(Rs):+.3f}, sumR {sum(Rs):+.1f}, WR {wr:.1f}%")
        n_peak1 = sum(1 for t in all_trades if t["peak_R"] >= 1.0)
        w(f"- peak_R≥1: {n_peak1} ({n_peak1*100/len(all_trades):.0f}%)")
        w(f"- Range: {all_trades[0]['entry_ts']} → {all_trades[-1]['exit_ts']}")
    w("")

    if len(all_trades) < 1000:
        w(f"**STOP:** Pool < 1000 trade — data_engineer 5y × 1m ingest tamamlamadı veya audit blacklist çoğunluğu kapsadı.")
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
            w(f"> **WARNING:** {len(windows)}/{TARGET_WINDOWS} pencere — 5y ingest gerekli.")
        w("")

    scenarios = [
        ("PHOENIX 1m default (mc=24, maker-only)",
         risk_cfg.with_overrides(max_concurrent=24)),
    ]

    period_years = TRAIN_DAYS / 365.0 if not DRY_RUN else max(0.1,
        (all_trades[-1]["exit_ts"] - all_trades[0]["entry_ts"]).days / 365.0)

    w("## Sonuçlar (Rolling, default scenario)")
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
    w("## Gate Karar (P4c)")
    w("")
    if not rated:
        w("**STOP:** Hiçbir senaryo replay üretmedi.")
    else:
        best = max(rated, key=lambda x: x[4])
        # KILL check: annual < 0
        if best[1] < 0:
            w(f"**KILL TETİKLENDİ (§7.1):** annual {best[1]:+.1f}% < 0 -> post-fee+slip negatif.")
            w("1m strategy archive, paper trading'e gönderilmez.")
        else:
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
                w("**GATE P4c PRIMARY PASS** -> beklenmedik başarı! Principal manual review.")
            elif fallback_pass:
                w("**GATE P4c FALLBACK PASS** -> P5 (portfolio layer), corr analizi zorunlu.")
            else:
                w("**GATE P4c FAIL** -> 1m KILL (master plan §7), archive.")

    if fallback_used:
        w("")
        w("> **CRITICAL NOT:** Fallback YAML 1m için kalibre değil — sonuçlar **GÜVENİLMEZ**.")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
