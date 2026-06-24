"""SEC49: 15m R4 TOP-4 Per-Calendar-Month P&L (61 ay).

15m R4 mc=20 production candidate'ı için sec46 paterninin 15m'ye port'u.
Pool: data/sec31_15m_pool.pkl (TOP-10 strateji × 10 sym × 5y).
TOP-4 filter: vsa_climax_test, brooks_failed_breakout,
              anchored_vwap_reversal, engulfing_continuation.
Config: configs/risk_phoenix_scalp_15m_pyramid_r3.yaml
Override: max_concurrent=20, same_symbol_side_cooldown_days=0 (R4 mc=20 senaryosu).

Output:
  - reports/lab/sec49_phoenix_scalp_15m_r4_per_month_results.md
  - reports/lab/sec49_per_month.csv
"""
from __future__ import annotations

import csv
import io
import os
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

CACHE = ROOT / "data" / "sec31_15m_pool.pkl"
REPORT = ROOT / "reports" / "lab" / "sec49_phoenix_scalp_15m_r4_per_month_results.md"
CSV_OUT = ROOT / "reports" / "lab" / "sec49_per_month.csv"
RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"

# TOP-4 (sec31g ablation BOMBA)
TOP4_STRATEGIES = {
    "vsa_climax_test",
    "brooks_failed_breakout",
    "anchored_vwap_reversal",
    "engulfing_continuation",
}

# 10 sym universe (RESUME + risk_phoenix_scalp_15m_pyramid_r3.yaml)
SYMBOLS_10 = {
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
    "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT",
}

# Gate thresholds (görev brief)
GATE_MEAN = 20.0       # mean monthly % minimum
GATE_CV = 0.70         # CV max
GATE_NEG_MAX = 6       # max negatif ay sayısı (61 ayda)


import pandas as pd
from price_action.backtest.lab import ProductionConfig, production_replay


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        # pandas Timestamp
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def main():
    # ========================================================================
    # 1) Load pool + filter TOP-4 + 10 sym
    # ========================================================================
    if not CACHE.exists():
        print(f"ERROR: pool cache missing: {CACHE}")
        return
    print(f"[LOAD] {CACHE} ({CACHE.stat().st_size/1e6:.1f} MB)", flush=True)
    with CACHE.open("rb") as fh:
        pool_raw = pickle.load(fh)
    print(f"[POOL raw] {len(pool_raw):,} trade (TOP-10 × 10 sym × 5y)", flush=True)

    # TOP-4 + 10-sym filter
    pool = [
        t for t in pool_raw
        if t.get("strategy") in TOP4_STRATEGIES
        and t.get("symbol") in SYMBOLS_10
    ]
    if not pool:
        print("ERROR: TOP-4 filter sonrası pool boş")
        return

    Rs_full = [t["R"] for t in pool]
    print(f"[POOL TOP-4] {len(pool):,} trade  |  mean R {sum(Rs_full)/len(Rs_full):+.3f}  |  sumR {sum(Rs_full):+.1f}", flush=True)

    # Strategy + symbol breakdown
    from collections import Counter
    s_cnt = Counter(t["strategy"] for t in pool)
    sym_cnt = Counter(t["symbol"] for t in pool)
    print(f"[STRATEGIES] {dict(s_cnt)}", flush=True)
    print(f"[SYMBOLS] {len(sym_cnt)} sym, range {min(sym_cnt.values())}-{max(sym_cnt.values())}", flush=True)

    # ========================================================================
    # 2) Risk config (with R4 mc=20 + cooldown=0 override)
    # ========================================================================
    cfg = ProductionConfig.from_yaml(str(RISK_YAML))
    cfg = cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    print(f"[YAML] {RISK_YAML.name}  |  override: max_concurrent=20, cooldown=0 (R4)", flush=True)

    pool.sort(key=lambda x: x["entry_ts"])
    start_dt = to_utc(pool[0]["entry_ts"])
    end_dt = to_utc(pool[-1]["entry_ts"])
    print(f"[RANGE] {start_dt.date()} -> {end_dt.date()}", flush=True)

    # ========================================================================
    # 3) Calendar-month bucket
    # ========================================================================
    months = []
    cur_year, cur_month = start_dt.year, start_dt.month
    while True:
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

    print(f"\n[MONTHS] {len(months)} ay analiz edilecek", flush=True)
    print(f"\n| Ay | n trade | mean R | Monthly % | DD % | r-adj | WR % |")
    print(f"|---|---:|---:|---:|---:|---:|---:|")

    results = []
    for yr, mo, ms, me in months:
        m_trades = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_trades) < 10:
            print(f"| {yr}-{mo:02d} | {len(m_trades)} | - | (n<10 skip) | - | - | - |")
            continue
        r = production_replay(m_trades, cfg)
        if r is None:
            print(f"| {yr}-{mo:02d} | {len(m_trades)} | - | (replay None) | - | - | - |")
            continue
        # Monthly raw return (compound): total_return = final/initial - 1
        ret_pct = r.total_return * 100
        dd_pct = r.max_drawdown * 100
        ra = ret_pct / abs(dd_pct) if dd_pct != 0 else 0
        Rs = [t["R"] for t in m_trades]
        mR = sum(Rs) / len(Rs)
        wr = sum(1 for x in Rs if x > 0) / len(Rs) * 100
        results.append((yr, mo, len(m_trades), mR, ret_pct, dd_pct, ra, wr))
        print(f"| {yr}-{mo:02d} | {len(m_trades):,} | {mR:+.3f} | {ret_pct:+.2f}% | {dd_pct:+.2f}% | {ra:.2f} | {wr:.1f}% |")

    if not results:
        print("[FATAL] hiç ay sonuç vermedi")
        return

    # ========================================================================
    # 4) CSV (raw verify için)
    # ========================================================================
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    with CSV_OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["year", "month", "n_trade", "mean_R", "monthly_pct", "dd_pct", "r_adj", "wr_pct"])
        for r in results:
            w.writerow([r[0], r[1], r[2], f"{r[3]:.6f}", f"{r[4]:.6f}", f"{r[5]:.6f}", f"{r[6]:.6f}", f"{r[7]:.6f}"])
    print(f"\n[CSV] {CSV_OUT}", flush=True)

    # ========================================================================
    # 5) Summary metrics (KRİTİK — net sayı, hallucinasyon yok)
    # ========================================================================
    rets = [r[4] for r in results]
    dds = [r[5] for r in results]
    ras = [r[6] for r in results]
    n = len(rets)

    mean_ret = sum(rets) / n
    sorted_rets = sorted(rets)
    if n % 2 == 1:
        median_ret = sorted_rets[n // 2]
    else:
        median_ret = (sorted_rets[n // 2 - 1] + sorted_rets[n // 2]) / 2

    pos = sum(1 for x in rets if x > 0)
    neg = sum(1 for x in rets if x < 0)
    zero = sum(1 for x in rets if x == 0)

    min_r = min(rets)
    max_r = max(rets)
    min_idx = rets.index(min_r)
    max_idx = rets.index(max_r)
    min_ym = f"{results[min_idx][0]}-{results[min_idx][1]:02d}"
    max_ym = f"{results[max_idx][0]}-{results[max_idx][1]:02d}"

    if n > 1:
        std = (sum((x - mean_ret) ** 2 for x in rets) / (n - 1)) ** 0.5
    else:
        std = 0.0
    cv = std / abs(mean_ret) if mean_ret != 0 else float("inf")

    ge20 = sum(1 for x in rets if x >= 20.0)
    ge15 = sum(1 for x in rets if x >= 15.0)

    print(f"\n--- ÖZET ({n} ay) ---")
    print(f"Aylık mean   : {mean_ret:+.2f}%")
    print(f"Aylık median : {median_ret:+.2f}%")
    print(f"Aylık min    : {min_r:+.2f}%  ({min_ym})")
    print(f"Aylık max    : {max_r:+.2f}%  ({max_ym})")
    print(f"Std          : {std:.2f}pp")
    print(f"CV           : {cv*100:.0f}%  (std/|mean|)")
    print(f"Pozitif ay   : {pos}/{n} ({pos/n*100:.0f}%)")
    print(f"Negatif ay   : {neg}/{n} ({neg/n*100:.0f}%)")
    print(f"Sıfır ay     : {zero}/{n}")
    print(f"Aylar >= +20%: {ge20}/{n}  (user STRICT gate)")
    print(f"Aylar >= +15%: {ge15}/{n}  (user LOOSE gate)")

    # ========================================================================
    # 6) Gate verdict
    # ========================================================================
    if mean_ret >= GATE_MEAN and cv <= GATE_CV and neg <= GATE_NEG_MAX:
        verdict = "PASS"
    elif mean_ret >= 15.0:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    print(f"\n=== GATE VERDICT: {verdict} ===")
    print(f"  Gate: mean>={GATE_MEAN}% (got {mean_ret:+.2f})  |  CV<={GATE_CV*100:.0f}% (got {cv*100:.0f}%)  |  neg<={GATE_NEG_MAX} (got {neg})")

    # ========================================================================
    # 7) Markdown rapor
    # ========================================================================
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    out = []
    out.append(f"# SEC49: Phoenix-Scalp 15m R4 TOP-4 — Per-Month P&L (61 ay)\n\n")
    out.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n\n")
    out.append(f"**YAML:** `{RISK_YAML.name}` + R4 override (max_concurrent=20, cooldown=0)\n\n")
    out.append(f"**Pool:** {len(pool):,} trade (TOP-4 × 10 sym × 5y, filtered from {len(pool_raw):,})\n\n")
    out.append(f"**TOP-4 strategies:** {sorted(TOP4_STRATEGIES)}\n\n")
    out.append(f"**Range:** {start_dt.date()} -> {end_dt.date()}\n\n")
    out.append(f"**Champion baseline (RESUME.md):** yıllık +%234 / DD -%30 / r-adj 7.83 (34/34 pozitif walk-forward)\n\n")
    out.append(f"## Pool Composition\n\n")
    out.append(f"| Strategy | n trade |\n|---|---:|\n")
    for s, c in s_cnt.most_common():
        out.append(f"| {s} | {c:,} |\n")
    out.append(f"\n| Symbol | n trade |\n|---|---:|\n")
    for s, c in sym_cnt.most_common():
        out.append(f"| {s} | {c:,} |\n")
    out.append(f"\n## {n} Aylık Breakdown\n\n")
    out.append(f"| Ay | n trade | mean R | Monthly % | DD % | r-adj | WR % |\n")
    out.append(f"|---|---:|---:|---:|---:|---:|---:|\n")
    for r in results:
        out.append(f"| {r[0]}-{r[1]:02d} | {r[2]:,} | {r[3]:+.3f} | {r[4]:+.2f}% | {r[5]:+.2f}% | {r[6]:.2f} | {r[7]:.1f}% |\n")
    out.append(f"\n## Özet Metrikleri\n\n")
    out.append(f"| Metrik | Değer |\n|---|---:|\n")
    out.append(f"| Mean monthly return | **{mean_ret:+.2f}%** |\n")
    out.append(f"| Median monthly return | {median_ret:+.2f}% |\n")
    out.append(f"| Std (pp) | {std:.2f} |\n")
    out.append(f"| CV (std/\\|mean\\|) | **{cv*100:.0f}%** |\n")
    out.append(f"| Min ay | {min_r:+.2f}% ({min_ym}) |\n")
    out.append(f"| Max ay | {max_r:+.2f}% ({max_ym}) |\n")
    out.append(f"| Pozitif ay | {pos}/{n} ({pos/n*100:.0f}%) |\n")
    out.append(f"| Negatif ay | {neg}/{n} ({neg/n*100:.0f}%) |\n")
    out.append(f"| Aylar ≥ +20% | **{ge20}/{n}** (STRICT user gate) |\n")
    out.append(f"| Aylar ≥ +15% | {ge15}/{n} (LOOSE user gate) |\n")
    out.append(f"\n## Gate Verdict\n\n")
    out.append(f"**{verdict}**\n\n")
    out.append(f"- Threshold: mean ≥ {GATE_MEAN}% AND CV ≤ {GATE_CV*100:.0f}% AND neg ≤ {GATE_NEG_MAX}/61\n")
    out.append(f"- Got: mean {mean_ret:+.2f}% | CV {cv*100:.0f}% | neg {neg}/{n}\n")

    REPORT.write_text("".join(out), encoding="utf-8")
    print(f"\n[DONE] {REPORT}")
    print(f"[DONE] {CSV_OUT}")


if __name__ == "__main__":
    main()
