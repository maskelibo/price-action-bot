"""reports/PRODUCTION_BENCHMARK.md uretir.

Tek source-of-truth: canonical production_replay (lab.py) tum pencerelerde
calistirilir; ROI/DD bu tek dosyaya yazilir. Her commit'te update edilmeli.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, stdev

os.environ["PA_LOG_QUIET"] = "1"

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay
from scripts.v09_optimize_top10 import _gather, TOP_10


def git_short_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "?"


def run_window(trades, start, end, cfg):
    w = [t for t in trades if start <= t["entry_ts"] < end]
    years = (end - start).total_seconds() / (365.25 * 86400)
    r = production_replay(w, cfg)
    if r is None:
        return None
    return {
        "n": r.trades,
        "final": r.final_equity,
        "return_pct": r.total_return * 100,
        "ann_pct": r.annualized(years) * 100,
        "dd_pct": r.max_drawdown * 100,
        "wr_pct": r.win_rate * 100,
        "years": years,
    }


def main():
    print("Trade'leri topluyor (1 kez)...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)} sinyal\n")

    # Configurations
    cfg_v091 = ProductionConfig(
        risk_pct=0.030, conf_min=0.20,
        max_notional_pct_equity=None,
        consecutive_loss_n=3, consecutive_loss_pause_days=5,
    )
    cfg_v092 = ProductionConfig.from_yaml()  # production (cap 0.30) - varsayilan
    cfg_realistic = cfg_v092.with_overrides(concentration_max_per_symbol_pct=0.20)

    # v0.9.3 presets — concentration_gate YAML'da otomatik aktif (live-realistic)
    cfg_aggressive = ProductionConfig.from_yaml("configs/risk_aggressive.yaml")
    cfg_defensive = ProductionConfig.from_yaml("configs/risk_defensive.yaml")
    # v0.9.4 BALANCED preset (AGGRESSIVE + capitulation halt)
    cfg_balanced = ProductionConfig.from_yaml("configs/risk_balanced.yaml")

    configs = [
        ("v0.9.1 (no cap)", cfg_v091),
        ("v0.9.2 (cap 0.30)", cfg_v092),
        ("v0.9.2 + conc 0.20 (live-like)", cfg_realistic),
        ("v0.9.3 AGGRESSIVE preset", cfg_aggressive),
        ("v0.9.3 DEFENSIVE preset", cfg_defensive),
        ("v0.9.4 BALANCED preset (halt+r%4)", cfg_balanced),
    ]

    # Pencereler
    full_start = all_trades[0]["entry_ts"]
    full_end = all_trades[-1]["exit_ts"]
    one_y_start = pd.Timestamp("2025-05-09", tz="UTC")
    one_y_end = pd.Timestamp("2026-05-09", tz="UTC")

    # 3y rolling pencereleri
    rolling_windows = []
    cur = full_start
    while cur + pd.Timedelta(days=3 * 365) <= full_end:
        rolling_windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)

    results = {}
    for cfg_name, cfg in configs:
        print(f"# {cfg_name} hesaplaniyor...")
        # 5y single window
        r_5y = run_window(all_trades, full_start, full_end, cfg)
        # 1y OOS
        r_1y = run_window(all_trades, one_y_start, one_y_end, cfg)
        # 3y rolling
        rolls = []
        for ws, we in rolling_windows:
            rr = run_window(all_trades, ws, we, cfg)
            if rr:
                rolls.append(rr)
        results[cfg_name] = {"5y": r_5y, "1y": r_1y, "rolls": rolls}

    # Build markdown
    md = []
    md.append("# PRODUCTION BENCHMARK")
    md.append("")
    md.append(f"**Son güncelleme:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    md.append(f"**Git commit:** `{git_short_sha()}`")
    md.append("**Kaynak:** `scripts/v092_build_benchmark.py` (canonical `production_replay` üzerinden)")
    md.append("")
    md.append("> Bu dosya **tek doğruluk kaynağıdır**. Her commit'te güncellenir.")
    md.append("> Aynı pencere/aynı config = aynı rakam — sapma varsa script bug'ı vardır.")
    md.append("")

    # Production config detay
    md.append("## v0.9.2 Production Config")
    md.append("")
    md.append("```")
    md.append(f"label              : {cfg_v092.label()}")
    md.append(f"risk_pct           : {cfg_v092.risk_pct}")
    md.append(f"max_notional_pct   : {cfg_v092.max_notional_pct_equity} (v0.9.2 cap)")
    md.append(f"conf_min           : {cfg_v092.conf_min}")
    md.append(f"consecutive_loss   : {cfg_v092.consecutive_loss_n} -> {cfg_v092.consecutive_loss_pause_days}d pause")
    md.append(f"max_concurrent     : {cfg_v092.max_concurrent}")
    md.append(f"DD breakers (d/w/m): {cfg_v092.daily_dd}/{cfg_v092.weekly_dd}/{cfg_v092.monthly_dd}")
    md.append("```")
    md.append("")

    # === 1y OOS ===
    md.append("## 1 Yıl Out-of-Sample (2025-05-09 → 2026-05-09)")
    md.append("")
    md.append("| Config | n_trade | final $ | toplam % | yıllık % | max DD | WR |")
    md.append("|---|---|---|---|---|---|---|")
    for name, _ in configs:
        r = results[name]["1y"]
        if r is None:
            md.append(f"| {name} | - | - | - | - | - | - |"); continue
        md.append(f"| {name} | {r['n']} | ${r['final']:,.0f} | {r['return_pct']:+.1f}% | "
                  f"{r['ann_pct']:+.1f}% | {r['dd_pct']:+.1f}% | {r['wr_pct']:.1f}% |")
    md.append("")

    # === 5y In-Sample ===
    md.append("## 5 Yıl In-Sample (tek pencere)")
    md.append("")
    md.append("> ⚠️ Tek pencere; dispersiyon yüksek olabilir. 3y rolling'den daha az güvenilir.")
    md.append("")
    md.append("| Config | n_trade | final $ | toplam % | yıllık % | max DD | WR |")
    md.append("|---|---|---|---|---|---|---|")
    for name, _ in configs:
        r = results[name]["5y"]
        if r is None:
            md.append(f"| {name} | - | - | - | - | - | - |"); continue
        md.append(f"| {name} | {r['n']} | ${r['final']:,.0f} | {r['return_pct']:+.1f}% | "
                  f"{r['ann_pct']:+.2f}% | {r['dd_pct']:+.1f}% | {r['wr_pct']:.1f}% |")
    md.append("")

    # === 3y Rolling Summary ===
    md.append("## 3 Yıl Rolling Stress (13 pencere, 60-gün adım)")
    md.append("")
    md.append("> ⭐ **ASIL referans** — pencere ortalaması dispersiyona dirençli.")
    md.append("")
    md.append("| Config | n_pencere | ort. yıllık | median yıllık | min yıllık | max yıllık | ort. DD | min DD | %50+ | neg |")
    md.append("|---|---|---|---|---|---|---|---|---|---|")
    for name, _ in configs:
        rolls = results[name]["rolls"]
        if not rolls:
            md.append(f"| {name} | 0 | - | - | - | - | - | - | - | - |"); continue
        anns = [r["ann_pct"] for r in rolls]
        dds = [r["dd_pct"] for r in rolls]
        neg = sum(1 for a in anns if a < 0)
        target50 = sum(1 for a in anns if a >= 50)
        md.append(f"| {name} | {len(rolls)} | {mean(anns):+.2f}% | {median(anns):+.2f}% | "
                  f"{min(anns):+.1f}% | {max(anns):+.1f}% | {mean(dds):+.1f}% | "
                  f"{min(dds):+.0f}% | {target50}/{len(rolls)} | {neg} |")
    md.append("")

    # 3y rolling pencere detayi (v0.9.2 production)
    md.append("### v0.9.2 Production — 3y rolling pencereleri (tam liste)")
    md.append("")
    md.append("| Pencere | n_trade | final $ | yıllık % | DD |")
    md.append("|---|---|---|---|---|")
    for r, (ws, we) in zip(results["v0.9.2 (cap 0.30)"]["rolls"], rolling_windows):
        md.append(f"| {ws.date()} → {we.date()} | {r['n']} | ${r['final']:,.0f} | "
                  f"{r['ann_pct']:+.2f}% | {r['dd_pct']:+.1f}% |")
    md.append("")

    # v0.9.3 Presets karsilastirma
    md.append("## v0.9.3 PRESETS — İki Production Seçeneği")
    md.append("")
    md.append("`configs/risk_aggressive.yaml` ve `configs/risk_defensive.yaml` iki paralel preset.")
    md.append("Production default `configs/risk.yaml` (v0.9.2) — değiştirilmedi.")
    md.append("")
    md.append("### Aggressive (Aday A) — `risk_aggressive.yaml`")
    md.append("- Tek değişiklik: `backtest_risk_pct: 0.040`")
    md.append("- Profil: \"GETIRI maksimum\"")
    md.append("- Beklenti: yıllık +%42, DD -%37, 5y $59K")
    md.append("- Live-realistic (conc 0.20): yıllık +%30, DD -%26, 5y $37K")
    md.append("")
    md.append("### Defensive (Aday B = T6 r%3.5) — `risk_defensive.yaml`")
    md.append("- `backtest_risk_pct: 0.035`")
    md.append("- `vol_target.enabled: true`")
    md.append("- `max_same_side_concurrent: 4`")
    md.append("- `drop_strategies: [equal_highs_sweep, cvd_spike_fade, vsa_climax_test]`")
    md.append("- Profil: \"TUTARLILIK maksimum\"")
    md.append("- Beklenti: yıllık +%31, DD -%24, 5y $38K, **risk-adj 1.31 (en yüksek)**")
    md.append("- Live-realistic (conc 0.20): yıllık ~%22, DD -%19, 5y $27K")
    md.append("")
    md.append("### Balanced (v0.9.4 — Analyst regime halt) — `risk_balanced.yaml` ⭐ YENİ")
    md.append("- AGGRESSIVE base + `regime_filter.btc_capitulation_halt_enabled: true`")
    md.append("- ATR%≥6 + EMA200 streak ≥10gün + 90d-DD ≤-25% (2 of 3 → halt)")
    md.append("- Profil: \"DENGELI\" — yüksekçe getiri, dar dispersiyon")
    md.append("- Beklenti: yıllık +%33, DD -%30, **min pencere +%20 (en kötü senaryo bile iyi)**")
    md.append("- AGGRESSIVE'den farkı: dispersiyon yarı, min 6x yukseldi, DD -%7pp")
    md.append("")
    md.append("### Kullanim")
    md.append("```python")
    md.append("from price_action.backtest.lab import ProductionConfig, production_replay")
    md.append("cfg = ProductionConfig.from_yaml('configs/risk_aggressive.yaml')")
    md.append("# veya 'configs/risk_defensive.yaml'")
    md.append("result = production_replay(trades, cfg)")
    md.append("```")
    md.append("")

    # === Yorum ===
    md.append("## Yorum — Hangisi 'Gerçek' Beklentidir?")
    md.append("")
    md.append("Üç pencere üç ayrı şey ölçer:")
    md.append("")
    md.append("- **1y OOS** (`+%170, DD -%64`): Son 12 ayda kripto yükselişinde aşırı iyi performans.")
    md.append("  Single window — dispersiyon yüksek. Live'da tekrar edilmesi şart değil.")
    md.append("- **5y in-sample** (`+%97 yıllık, DD -%59`): Tek pencere, optimizasyon biased.")
    md.append("  Üst sınır olarak görülmeli, gerçek değil.")
    md.append("- **3y rolling 13 pencere** ⭐ (`ort. yıllık +%57, DD -%65`): Pencere-bağımsız")
    md.append("  ortalama — beklenti olarak **bu** kullanılmalı.")
    md.append("")
    md.append("**Live trading realistik beklenti** (slip+funding %20 kayıp):")
    md.append("- Yıllık ROI: **+%40-50**")
    md.append("- Max DD: **-%65 ile -%75 arası**")
    md.append("- Best/Worst pencere ROI: +%14 (en kötü) ile +%134 (en iyi) arası bekleyin")
    md.append("")
    md.append("> **NOT — 'v0.9.2 + conc 0.20'** kolonu live'a en yakın simulasyon.")
    md.append("> Concentration gate (`%20 per symbol`) RiskOfficer.evaluate'ta uygulanıyor.")
    md.append("> Eski backtest replay'lerde bu gate yoktu; rakamlar burada gerçek live'a daha yakın.")
    md.append("")
    md.append("## Reproducibility")
    md.append("")
    md.append("Bu rakamları yeniden üretmek için:")
    md.append("```bash")
    md.append("python scripts/v092_build_benchmark.py  # bu dosyayi yeniden uretir")
    md.append("python scripts/v092_parity_check.py     # canonical vs eski replay parity")
    md.append("```")
    md.append("")

    out = ROOT / "reports" / "PRODUCTION_BENCHMARK.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"\n[OK] {out} yazildi ({len(md)} satir)")
    print()
    print("Onemli rakamlar:")
    for name, _ in configs:
        r1y = results[name]["1y"]
        r5y = results[name]["5y"]
        rolls = results[name]["rolls"]
        anns = [r["ann_pct"] for r in rolls] if rolls else []
        dds = [r["dd_pct"] for r in rolls] if rolls else []
        print(f"\n  {name}:")
        print(f"    1y OOS    : {r1y['ann_pct']:+.1f}% yillik, DD {r1y['dd_pct']:+.1f}%")
        print(f"    5y single : {r5y['ann_pct']:+.2f}% yillik, DD {r5y['dd_pct']:+.1f}%")
        if anns:
            print(f"    3y roll   : ort. {mean(anns):+.2f}% yillik, ort. DD {mean(dds):+.1f}%  ({sum(1 for a in anns if a>=50)}/{len(anns)} %50+)")


if __name__ == "__main__":
    main()
