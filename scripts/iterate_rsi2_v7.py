"""rsi2 round 7 — SON — v45/v46/v50 hibritleri.

User: 'Hangisi en iyi bilemedim, son section yapalım.'

Önceki BEATS_LIVE'lar:
  v45 tp_r=3.0           +19.29% / -19.28%  (yüksek ROI, makul DD)
  v46 pause=2            +15.99% / -16.35%  (en güvenli DD)
  v50 tp2.5+monthly      +19.45% / -19.75%  (en yüksek aylık)

Hipotez: v45'in (tp=3.0) ROI gücü + v46'nın (pause=2) DD koruması
hibrit edilirse ULTIMATE varyant çıkar mı?

10 hibrit varyant:
  v55 v45+pause=2          tp=3.0 + pause=2 (ULTIMATE candidate)
  v56 v45+monthly0.10      tp=3.0 + monthly cap
  v57 v45+conc=5           tp=3.0 + fewer concurrent
  v58 v50+pause=2          tp=2.5 + monthly + pause=2 (TRIPLE)
  v59 v45+risk0.004        tp=3.0 + risk azalt
  v60 v45+pause=2+monthly  ULTIMATE TRIPLE
  v61 v46+tp=2.5           pause=2 + tp=2.5
  v62 v46+monthly          pause=2 + monthly cap
  v63 v45+conc=8+pause=2   high concurrent + tight pause (yarış)
  v64 v45+pause=2+conc=5+monthly  ULTRA SAFE
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


VARIANTS_R7 = [
    {"name": "v55_v45+pause2",        "trades": {"tp_r": 3.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 2}},
    {"name": "v56_v45+monthly0.10",   "trades": {"tp_r": 3.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.10}},
    {"name": "v57_v45+conc5",         "trades": {"tp_r": 3.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 5, "consecutive_loss_pause": 3}},
    {"name": "v58_v50+pause2",        "trades": {"tp_r": 2.5}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 2, "monthly_dd_halt": 0.12}},
    {"name": "v59_v45+risk0.004",     "trades": {"tp_r": 3.0}, "equity": {"risk_pct": 0.004, "max_concurrent": 6, "consecutive_loss_pause": 3}},
    {"name": "v60_v45+pause2+monthly","trades": {"tp_r": 3.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 2, "monthly_dd_halt": 0.10}},
    {"name": "v61_v46+tp2.5",         "trades": {"tp_r": 2.5}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 2}},
    {"name": "v62_v46+monthly",       "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 2, "monthly_dd_halt": 0.12}},
    {"name": "v63_v45+conc8+pause2",  "trades": {"tp_r": 3.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 8, "consecutive_loss_pause": 2}},
    {"name": "v64_ultra_safe",        "trades": {"tp_r": 3.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 5, "consecutive_loss_pause": 2, "monthly_dd_halt": 0.10}},
]


def main() -> int:
    print("=== rsi2 v7 SON — v45/v46/v50 hibrit (10 varyant) ===\n")
    print(f"{'Varyant':28} {'aylık':>8} {'neg':>7} {'DD':>8} {'yıllık':>9} {'n_tr':>6}  Sonuç")
    print("-" * 115)
    print(f"{'🟢 LIVE':28} {'+12.99%':>8} {'4/61':>7} {'-15.48%':>8} {'+329%':>9} {'4458':>6}  baseline")
    print(f"{'👑 v45 (tp=3.0)':28} {'+19.29%':>8} {'11/61':>7} {'-19.28%':>8} {'+587%':>9} {'6603':>6}  ratio 1.000")
    print(f"{'👑 v46 (pause=2)':28} {'+15.99%':>8} {'7/61':>7} {'-16.35%':>8} {'+437%':>9} {'5406':>6}  EN GÜVENLİ")
    print(f"{'👑 v50 (tp=2.5+monthly)':28} {'+19.45%':>8} {'9/61':>7} {'-19.75%':>8} {'+611%':>9} {'7059':>6}  EN YÜKSEK ROI")
    print("-" * 115)

    out_dir = ROOT / "memory" / "researcher" / "realistic_backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for v in VARIANTS_R7:
        trades_df = collect_trades(**v["trades"])
        if trades_df.empty:
            print(f"{v['name']:28} NO_TRADES")
            continue
        eq_series, final_eq, n_taken = _equity_with_loss_pause(trades_df, **v["equity"])
        m = _compute_metrics(eq_series, 10_000.0)
        # Tier'lar
        beats_live = (m["monthly_roi"] >= 13.0 and m["max_dd"] >= -20.0)
        super_elite = (m["monthly_roi"] >= 16.0 and m["max_dd"] >= -18.0)
        flag = "⚡ SUPER" if super_elite else (
            "👑 BEATS_LIVE" if beats_live else (
                "🏆 ELITE" if m["monthly_roi"] >= 10 and m["max_dd"] >= -20 else (
                    "✅" if m["monthly_roi"] > 5 else "🟡")))
        print(f"{v['name']:28} "
              f"{m['monthly_roi']:>+7.2f}% "
              f"{m['neg_count']:>2}/{m['total_months']:<3} "
              f"{m['max_dd']:>+7.2f}% "
              f"{m['annualized']:>+8.2f}% "
              f"{n_taken:>6}  {flag}")
        results.append({
            "variant": v["name"], "trades": v["trades"], "equity": v["equity"],
            "n_taken": n_taken, **m, "beats_live": beats_live, "super_elite": super_elite,
        })

    out_path = out_dir / "rsi2-iterate-v7-comparison.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(), "variants": results,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nDetay: {out_path}")

    # En iyi 3
    supers = [r for r in results if r["super_elite"]]
    beats = [r for r in results if r["beats_live"]]
    if supers:
        print("\n⚡⚡ SUPER ELITE (ROI ≥16 + DD ≥-18):")
        for r in sorted(supers, key=lambda r: r["monthly_roi"] / max(abs(r["max_dd"]), 1), reverse=True):
            ratio = r["monthly_roi"] / max(abs(r["max_dd"]), 1)
            print(f"  {r['variant']:28}: aylık +{r['monthly_roi']:.2f}% DD {r['max_dd']:.2f}% neg {r['neg_count']}/{r['total_months']} yıllık +{r['annualized']:.0f}% ratio {ratio:.3f}")
    elif beats:
        print("\n👑 BEATS_LIVE (yine, ama SUPER yok):")
        for r in sorted(beats, key=lambda r: r["monthly_roi"] / max(abs(r["max_dd"]), 1), reverse=True)[:3]:
            ratio = r["monthly_roi"] / max(abs(r["max_dd"]), 1)
            print(f"  {r['variant']:28}: +{r['monthly_roi']:.2f}% / {r['max_dd']:.2f}% (ratio {ratio:.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
