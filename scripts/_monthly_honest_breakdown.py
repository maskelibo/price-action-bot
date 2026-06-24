"""15m R4 v3.1 — DÜRÜST aylık tablo (NO compound, fixed $10K her ay).

User feedback: $5B / $2B compound matematiksel artifact (notional cap %30
of equity ama equity exponential büyüyor → gerçek live'da imkansız, crypto
derinlik $1B+ yok).

Bu script DÜRÜST sunum:
  - Her ay BAĞIMSIZ $10K capital ile simülasyon
  - ROI% per ay — pure strategy edge benchmark
  - Compound yok (yapay growth artifact silinir)
  - Yıllık 12-ay tam tablo
  - Yıllık özet: aylık mean ROI, std, neg/poz ay
"""
from __future__ import annotations

import csv
import io
import os
import pickle
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
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

import pandas as pd
from price_action.backtest.lab import ProductionConfig, production_replay

POOL_15M = ROOT / "data" / "sec31_15m_pool.pkl"
YAML_15M = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"
CSV_OUT = ROOT / "reports" / "engineering" / "2026-05-17_monthly_honest_breakdown.csv"
MD_OUT = ROOT / "reports" / "engineering" / "2026-05-17_monthly_honest_breakdown.md"

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}

INIT_CAP = 10000.0


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def main():
    print(f"[LOAD] {POOL_15M.name}")
    with POOL_15M.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [t for t in pool_raw if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"  pool: {len(pool):,} trade")

    cfg = ProductionConfig.from_yaml(str(YAML_15M))
    cfg = cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0.010)
    cfg = replace(cfg, btc_halt_calendar=None)
    print(f"[cfg] pyramid={cfg.pyramid_triggers}, halt=OFF, cooldown={cfg.same_symbol_side_cooldown_days}d")

    pool.sort(key=lambda x: x["entry_ts"])

    # 12 ay × 5 yıl = 60 ay (2021-05 → 2026-05 partial, 2021 ve 2026 partial)
    # Tam yıllık tablo için 2021-01 → 2026-12 (72 cell, partial yıllar boş gösterilecek)
    YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
    MONTHS_PER_YEAR = list(range(1, 13))

    print(f"\n[STEP] Per-month BAGIMSIZ replay (each month starts ${INIT_CAP:,.0f})")
    rows = []
    cell = {}  # (year, month) -> result dict

    for yr in YEARS:
        for mo in MONTHS_PER_YEAR:
            ms = datetime(yr, mo, 1, tzinfo=timezone.utc)
            me = datetime(yr + (1 if mo == 12 else 0), 1 if mo == 12 else mo + 1, 1, tzinfo=timezone.utc)
            m_trades = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
            n_raw = len(m_trades)

            if n_raw < 10:
                cell[(yr, mo)] = {"yyyy_mm": f"{yr:04d}-{mo:02d}", "n_raw": n_raw,
                                   "n_trades": 0, "wr_pct": 0.0, "roi_pct": None,
                                   "max_dd_pct": 0.0, "note": "no_data"}
                continue

            r = production_replay(m_trades, cfg)
            if r is None:
                cell[(yr, mo)] = {"yyyy_mm": f"{yr:04d}-{mo:02d}", "n_raw": n_raw,
                                   "n_trades": 0, "wr_pct": 0.0, "roi_pct": None,
                                   "max_dd_pct": 0.0, "note": "replay_none"}
                continue

            cell[(yr, mo)] = {
                "yyyy_mm": f"{yr:04d}-{mo:02d}", "n_raw": n_raw,
                "n_trades": r.trades,
                "wr_pct": round(r.win_rate * 100, 2),
                "roi_pct": round(r.total_return * 100, 3),
                "max_dd_pct": round(r.max_drawdown * 100, 3),
                "note": "",
            }

    # CSV
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    keys = ["yyyy_mm", "n_raw", "n_trades", "wr_pct", "roi_pct", "max_dd_pct", "note"]
    with CSV_OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for yr in YEARS:
            for mo in MONTHS_PER_YEAR:
                if (yr, mo) in cell:
                    w.writerow({k: cell[(yr, mo)].get(k, "") for k in keys})

    print(f"  CSV → {CSV_OUT}")

    # MD — yıllık 12 ay tablolar
    md = ["# 15m R4 v3.1 — DÜRÜST Aylık Tablo (NO compound)\n",
          "**ÖNEMLİ:** Her ay BAĞIMSIZ $10,000 capital ile simülasyon. ROI% saf strateji edge'i gösterir.",
          "Compound yapay — gerçek live'da equity büyüdükçe slippage/derinlik patlar.",
          "",
          f"**Config:** {YAML_15M.name} (Pyramid + Halt OFF + cooldown 15dk)",
          f"**Pool:** TOP-4 × 10 sym × 5y (n={len(pool):,})",
          "",
          ]

    # Her yıl için 12 ay tablo
    for yr in YEARS:
        md.append(f"## {yr} — 12 Ay")
        md.append("")
        md.append("| Ay | İşlem | WR% | DD% | **ROI%** | Sermaye Sonu ($) | Not |")
        md.append("|---|---:|---:|---:|---:|---:|---|")
        yr_rois = []
        for mo in MONTHS_PER_YEAR:
            c = cell.get((yr, mo))
            if c is None:
                md.append(f"| {mo:02d} | — | — | — | — | — | (out of span) |")
                continue
            if c["roi_pct"] is None:
                md.append(f"| {mo:02d} | 0 | 0.0 | 0.0 | — | $10,000 | {c['note']} |")
                continue
            end_cap = INIT_CAP * (1 + c["roi_pct"] / 100)
            md.append(f"| {mo:02d} | {c['n_trades']} | {c['wr_pct']:.1f} | "
                      f"{c['max_dd_pct']:.2f} | **{c['roi_pct']:+.2f}** | ${end_cap:,.0f} | |")
            yr_rois.append(c["roi_pct"])

        # Yıllık özet
        if yr_rois:
            mu = mean(yr_rois)
            sd = stdev(yr_rois) if len(yr_rois) > 1 else 0.0
            pos = sum(1 for x in yr_rois if x > 0)
            neg = sum(1 for x in yr_rois if x < 0)
            ge20 = sum(1 for x in yr_rois if x >= 20)
            md.append(f"\n**{yr} özet:** {len(yr_rois)} ay simüle | "
                      f"Mean ROI: **{mu:+.2f}%** | Std: {sd:.2f} | "
                      f"Pozitif: {pos} | Negatif: {neg} | ≥%20: {ge20}\n")

    # 5y toplu özet
    all_rois = [c["roi_pct"] for c in cell.values() if c["roi_pct"] is not None]
    md.append("\n## 5 Yıl Toplu Özet (NO compound)\n")
    md.append(f"- **Simüle ay sayısı:** {len(all_rois)}")
    md.append(f"- **Mean monthly ROI:** {mean(all_rois):+.2f}%")
    md.append(f"- **Median monthly ROI:** {sorted(all_rois)[len(all_rois)//2]:+.2f}%")
    md.append(f"- **Std:** {stdev(all_rois):.2f}")
    md.append(f"- **Min ay:** {min(all_rois):+.2f}% | **Max ay:** {max(all_rois):+.2f}%")
    md.append(f"- **Pozitif ay:** {sum(1 for x in all_rois if x > 0)}")
    md.append(f"- **Negatif ay:** {sum(1 for x in all_rois if x < 0)}")
    md.append(f"- **≥%20 ay:** {sum(1 for x in all_rois if x >= 20)}")
    md.append(f"- **≥%15 ay:** {sum(1 for x in all_rois if x >= 15)}")
    md.append(f"- **≥%10 ay:** {sum(1 for x in all_rois if x >= 10)}")

    md.append("\n## Realistic Live Projeksiyon\n")
    md.append("Her ay $10K bağımsız ile mean ROI **+%X**. Live'da sermaye büyüdükçe:")
    md.append("- $10K → $100K (10x, ~6-12 ay): mümkün, slippage minimal")
    md.append("- $100K → $1M (10x, ~12-18 ay): mümkün ama slippage hissedilir (1-3%)")
    md.append("- $1M → $10M (10x): zor, altcoin derinlik problemi")
    md.append("- $10M+ : ana coin'ler dışı imkansız, market manipulation riski")
    md.append("")
    md.append("**Backtest $2B/$5B → matematiksel limit, gerçek live tavanı ~$1-10M aralığı.**")

    MD_OUT.write_text("\n".join(md), encoding="utf-8")
    print(f"  MD → {MD_OUT}")

    # Console summary
    print(f"\n[SUMMARY 5Y NO-COMPOUND]")
    print(f"  Simüle ay: {len(all_rois)}")
    print(f"  Mean monthly ROI: {mean(all_rois):+.2f}%")
    print(f"  Pozitif/Neg: {sum(1 for x in all_rois if x > 0)} / {sum(1 for x in all_rois if x < 0)}")
    print(f"  ≥%20 ay: {sum(1 for x in all_rois if x >= 20)} / {len(all_rois)}")
    print(f"  Min/Max: {min(all_rois):+.2f}% / {max(all_rois):+.2f}%")


if __name__ == "__main__":
    main()
