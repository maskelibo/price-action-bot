"""Yeni Strateji Sınıfı Survey — TOP_10 disindaki implementli stratejilerin hizli edge olcumu.

Aday yeni sınıflar:
  - funding_mean_reversion   (carry harvest)
  - vol_risk_premium         (VRP overlay)
  - liquidation_fade         (liquidation cascade fade)
  - naked_poc_mr             (POC mean reversion)
  - btc_eth_pairs            (pair trading)
  - smc_orderblock           (SMC OB core)
  - failed_bo_bos_reclaim    (failed breakout + BOS)
  - ob_mitigation_strict     (SMC mitigation)

Her biri: 11 sym × 5y backtest, n_trade + win_rate + mean_R + cumulative_R + DD.
Pozitif edge gosterenler ensemble adayidir (Sec sonrasi gerekirse BALANCED'e eklenir).

Output: reports/research/new_strategy_class_survey.md
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import warnings
warnings.filterwarnings("ignore")

from statistics import mean, median
from scripts.v09_optimize_top10 import _gather, SYMBOLS_11

REPORT_OUT = ROOT / "reports" / "research" / "new_strategy_class_survey.md"

# (module_name, class_name, label)
CANDIDATES = [
    ("funding_mean_reversion", "FundingMeanReversionStrategy", "funding carry"),
    ("vol_risk_premium", "VolRiskPremiumStrategy", "VRP overlay"),
    ("liquidation_fade", "LiquidationFadeStrategy", "liquidation fade"),
    ("naked_poc_mr", "NakedPOCMeanReversionStrategy", "naked POC MR"),
    ("btc_eth_pairs", "BTCETHPairsStrategy", "BTC/ETH pairs"),
    ("smc_orderblock", "SMCOrderBlockStrategy", "SMC OB"),
    ("failed_bo_bos_reclaim", "FailedBreakoutBOSReclaimStrategy", "failed BO+BOS"),
    ("ob_mitigation_strict", "OBMitigationStrictStrategy", "OB mitigation"),
    ("htf_momentum", "HTFMomentumStrategy", "HTF momentum"),
    ("halving_cycle", "HalvingCycleStrategy", "halving cycle"),
    ("onchain_signals", "OnchainSignalsStrategy", "on-chain"),
    ("ii_breakout", "IIBreakoutStrategy", "II breakout"),
    ("naked_poc_mr", "NakedPOCMrStrategy", "naked POC MR (alt cls)"),
]


def find_strategy_class(module_name: str, candidates: list[str]) -> str | None:
    """Modulde implementli olan ilk class adini dondur."""
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=["*"])
    except Exception as e:
        return None
    for c in candidates:
        if hasattr(mod, c):
            return c
    # Strategy / class adi tahmini: dosyaadi'ndan CamelCase
    parts = [p.capitalize() for p in module_name.split("_")]
    guess = "".join(parts) + "Strategy"
    if hasattr(mod, guess):
        return guess
    # Tum class'larin icinde Strategy ile bitenleri bul
    for name in dir(mod):
        if name.endswith("Strategy") and not name.startswith("_"):
            return name
    return None


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w("# Yeni Strateji Sınıfı Survey")
    w("")
    w(f"**Generated:** 2026-05-13 (post v1.0.4)")
    w(f"**Pool:** 11 sym × 5y (2021-05 → 2026-05)")
    w(f"**Yontem:** Standalone backtest, no filter/ensemble")
    w("")
    w("## Sonuclar")
    w("")
    w("| Strateji | label | n_trade | WR | mean_R | sum_R | min_R | max_R | edge |")
    w("|---|---|---:|---:|---:|---:|---:|---:|---|")

    print("Survey baslatiliyor...")
    print(f"{'strategy':<35} {'label':<22} {'n':>6} {'wr':>6} {'mR':>7} {'sumR':>8} {'edge':<6}")
    print("-" * 98)

    summary = []

    for module_name, default_class, label in CANDIDATES:
        # Sinif adi cozumu
        cls_name = find_strategy_class(module_name, [default_class])
        if cls_name is None:
            print(f"{module_name:<35} {label:<22} {'???':>6} (sinif bulunamadi)")
            w(f"| {module_name} | {label} | - | - | - | - | - | - | sinif yok |")
            continue

        try:
            trades = _gather(module_name, cls_name)
        except Exception as e:
            print(f"{module_name:<35} {label:<22} HATA: {str(e)[:40]}")
            w(f"| {module_name} | {label} | - | - | - | - | - | - | HATA: {str(e)[:60]} |")
            continue

        n = len(trades)
        if n == 0:
            print(f"{module_name:<35} {label:<22} {n:>6} (sinyal yok)")
            w(f"| {module_name} | {label} | 0 | - | - | - | - | - | sinyal yok |")
            continue

        Rs = [float(t.get("R", 0.0)) for t in trades]
        wr = sum(1 for r in Rs if r > 0) / n * 100
        mR = sum(Rs) / n
        sumR = sum(Rs)
        mnR = min(Rs)
        mxR = max(Rs)
        edge = ""
        if mR > 0.10 and n >= 30:
            edge = "POZITIF"
        elif mR > 0.0:
            edge = "marjinal"
        else:
            edge = "negatif"

        summary.append({
            "module": module_name,
            "label": label,
            "n": n, "wr": wr, "mR": mR, "sumR": sumR,
            "mnR": mnR, "mxR": mxR, "edge": edge,
        })
        print(f"{module_name:<35} {label:<22} {n:>6} {wr:>5.1f}% {mR:>+7.3f} {sumR:>+8.1f} {edge:<6}")
        w(f"| {module_name} | {label} | {n} | {wr:.1f}% | {mR:+.3f} | {sumR:+.1f} | {mnR:+.2f} | {mxR:+.2f} | {edge} |")

    # Sıralama: mean_R desc
    w("")
    w("## En Iyi 5 Aday (mean_R)")
    w("")
    w("| Sıra | Strateji | label | n | WR | mean_R | edge |")
    w("|---:|---|---|---:|---:|---:|---|")
    summary.sort(key=lambda x: -x["mR"])
    for i, r in enumerate(summary[:5], 1):
        w(f"| {i} | {r['module']} | {r['label']} | {r['n']} | {r['wr']:.1f}% | {r['mR']:+.3f} | {r['edge']} |")

    # Karar
    w("")
    w("## Karar")
    w("")
    pos_count = sum(1 for r in summary if r["edge"] == "POZITIF")
    marj_count = sum(1 for r in summary if r["edge"] == "marjinal")
    w(f"- POZITIF (mR>+0.10, n>=30): {pos_count}")
    w(f"- Marjinal (mR>0): {marj_count}")
    w(f"- Negatif: {len(summary) - pos_count - marj_count}")
    w("")
    if pos_count > 0:
        w(f"**ENSEMBLE ADAY:** Top {pos_count} POZITIF strateji BALANCED+F&G ensemble'a eklenebilir.")
        w("Sıradaki adim: BALANCED+pozitif strateji 13-pencere walk-forward retest.")
    else:
        w("**Yok:** Hicbir aday POZITIF gate (mR>+0.10, n>=30) gecmedi.")
        w("Yeni strateji sınıfı yolu archive — mevcut TOP_10 + BALANCED yapısı en iyisi.")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
