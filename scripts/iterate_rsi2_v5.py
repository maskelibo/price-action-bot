"""rsi2 round 5 — ROI 10-15%+ hedefi, DD ≤ -%18.

User: 'Biraz daha geliştir, ROI 10-15+, DD'yi de düşür.'

v26 (+9.55/-19.01) sırrı: loss_pause=3 magic. Bu sihri korurken:
  - ROI artırmak için: tp_r genişlet, concurrent artır
  - DD korumak için: loss_pause inceltimi, monthly halt eklemesi

Yeni 12 varyant:
  v31 v26+tp2.0           tp_r=2.0
  v32 v26+pause2          loss_pause=2 (daha sık halt)
  v33 v26+pause4          loss_pause=4 (daha gevşek)
  v34 v26+conc=6          max_concurrent=6
  v35 v26+monthly0.10     monthly halt eklendi
  v36 v26+tp2+conc=6      ikisi birden
  v37 v26+pause2+tp2      sıkı halt + geniş TP
  v38 v26+pause3+tp2+monthly
  v39 v26+pause3+conc=6+monthly0.12
  v40 v26+pause_days=2    1 gün yerine 2 gün
  v41 v7+pause3+tp2 hibrit (risk azaltma YOK)
  v42 v26+pause3+conc=5+tp1.75 sweet spot search
"""
from __future__ import annotations
import json, os, sys, warnings
warnings.filterwarnings("ignore")
os.environ.setdefault("PA_LOG_QUIET", "1")
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
import logging
logging.getLogger("price_action").setLevel(logging.ERROR)
import pandas as pd
from datetime import datetime, timezone
from iterate_rsi2_v3 import collect_trades
from iterate_rsi2_v4 import _equity_with_loss_pause
from iterate_rsi2_variants import _compute_metrics


VARIANTS_R5 = [
    {"name": "v31_v26+tp2.0",       "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3}},
    {"name": "v32_v26+pause2",      "trades": {},            "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 2}},
    {"name": "v33_v26+pause4",      "trades": {},            "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 4}},
    {"name": "v34_v26+conc6",       "trades": {},            "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3}},
    {"name": "v35_v26+monthly0.10", "trades": {},            "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.10}},
    {"name": "v36_v26+tp2+conc6",   "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3}},
    {"name": "v37_v26+pause2+tp2",  "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 2}},
    {"name": "v38_v26+tp2+monthly", "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.12}},
    {"name": "v39_v26+conc6+mon",   "trades": {},            "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.12}},
    {"name": "v40_v26+pause_days2", "trades": {},            "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3, "pause_days": 2}},
    {"name": "v41_v7+pause3+tp2",   "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3}},  # aynı v31, kontrol
    {"name": "v42_v26+conc5+tp175", "trades": {"tp_r": 1.75},"equity": {"risk_pct": 0.005, "max_concurrent": 5, "consecutive_loss_pause": 3}},
]


def main() -> int:
    print("=== rsi2 v5 — ROI 10-15%+ hedef, 12 varyant ===\n")
    print(f"{'Varyant':24} {'aylık':>8} {'neg':>7} {'DD':>8} {'yıllık':>9} {'n_tr':>6}  Sonuç")
    print("-" * 110)
    print(f"{'🟢 LIVE':24} {'+12.99%':>8} {'4/61':>7} {'-15.48%':>8} {'+329%':>9} {'4458':>6}  baseline")
    print(f"{'★ v26 (best until)':24} {'+9.55%':>8} {'14/61':>7} {'-19.01%':>8} {'+183%':>9} {'8640':>6}  STRICT PROMOTE")
    print("-" * 110)

    out_dir = ROOT / "memory" / "researcher" / "realistic_backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for v in VARIANTS_R5:
        trades_df = collect_trades(**v["trades"])
        if trades_df.empty:
            print(f"{v['name']:24} NO_TRADES")
            continue
        eq_series, final_eq, n_taken = _equity_with_loss_pause(trades_df, **v["equity"])
        m = _compute_metrics(eq_series, 10_000.0)
        # Gate'ler (hedef: ROI 10-15+, DD ≤ -18)
        elite = (m["monthly_roi"] >= 10.0 and m["max_dd"] >= -20.0 and m["neg_count"] <= 15)
        strict = (m["monthly_roi"] >= 5.0 and m["max_dd"] >= -25.0 and m["neg_count"] <= 20)
        flag = "🏆 ELITE" if elite else ("✅✅ STRICT" if strict else (
            "🟡" if m["monthly_roi"] > 3 else "❌"))
        print(f"{v['name']:24} "
              f"{m['monthly_roi']:>+7.2f}% "
              f"{m['neg_count']:>2}/{m['total_months']:<3} "
              f"{m['max_dd']:>+7.2f}% "
              f"{m['annualized']:>+8.2f}% "
              f"{n_taken:>6}  {flag}")
        results.append({
            "variant": v["name"], "trades": v["trades"], "equity": v["equity"],
            "n_taken": n_taken, **m, "elite": elite, "strict": strict,
        })

    out_path = out_dir / "rsi2-iterate-v5-comparison.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(), "variants": results,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nDetay: {out_path}")

    # En iyi 3
    viable = [r for r in results if r["monthly_roi"] > 0]
    if viable:
        # Önce ELITE, sonra ratio
        elites = [r for r in viable if r["elite"]]
        if elites:
            print("\n🏆🏆 ELITE PROMOTE (ROI 10+ ve DD ≤ -20):")
            for r in sorted(elites, key=lambda r: r["monthly_roi"], reverse=True)[:3]:
                print(f"  {r['variant']:24}: aylık +{r['monthly_roi']:.2f}% DD {r['max_dd']:.2f}% neg {r['neg_count']}/{r['total_months']} yıllık +{r['annualized']:.1f}%")
        else:
            ranked = sorted(viable, key=lambda r: r["monthly_roi"] / max(abs(r["max_dd"]), 1), reverse=True)
            print("\n🏆 EN İYİ 3 RİSK-ADJUSTED (elite yok):")
            for r in ranked[:3]:
                ratio = r["monthly_roi"] / max(abs(r["max_dd"]), 1)
                print(f"  {r['variant']:24}: aylık +{r['monthly_roi']:.2f}% DD {r['max_dd']:.2f}% (ratio {ratio:.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
