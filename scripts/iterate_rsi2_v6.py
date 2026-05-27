"""rsi2 round 6 — v36 (+18%/-23%) üzerinde fine-tuning.

User: 'v36 daha da gelişir mi? ROI artırılabilir, DD düşürülebilir mi?'

v36 spec: risk=0.005 conc=6 pause=3 tp=2.0 → +18.03% / -23.22% / +556%

Hipotezler:
  - tp_r 2.0 → 2.5 / 3.0: big winner yakalama (ROI ↑)
  - monthly halt ekle: DD yıkıcı ayları kes (DD ↓)
  - trail stop: peak'ten % geri (winner'ları koru)
  - pause 3 → 2: daha sık halt (DD ↓)
  - conc 6 → 8: daha fazla trade fırsatı (ROI ↑)

Yeni 12 varyant:
  v43 v36+monthly0.12      DD reducer
  v44 v36+tp2.5            ROI booster
  v45 v36+tp3.0            ROI extreme
  v46 v36+pause2           tighter halt
  v47 v36+monthly0.10      DD strict
  v48 v36+daily0.03        daily soft halt
  v49 v36+conc8            more trades
  v50 v36+tp2.5+monthly    combo
  v51 v36+trail8%          peak - %8 trail
  v52 v36+tp3.0+monthly    extreme ROI + DD cap
  v53 v36+conc8+monthly    more trades + DD cap
  v54 v36+pause2+monthly+tp2.5  triple combo
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
from iterate_rsi2_v3 import collect_trades as _collect_basic
from iterate_rsi2_v4 import _equity_with_loss_pause
from iterate_rsi2_variants import (
    SYMBOLS, _load_ohlcv, _exit_with_be, _compute_metrics
)
from price_action.strategies.base import StrategyManifest
from price_action.strategies.rsi2_extreme_fade import RSI2ExtremeFadeStrategy


def collect_trades_with_trail(*, tp_r: float = 1.5, trail_pct: float | None = None) -> pd.DataFrame:
    """tp_r + opsiyonel trail stop ile trade collect."""
    manifest = StrategyManifest(name="rsi2_extreme_fade", version="v6")
    strategy = RSI2ExtremeFadeStrategy(manifest)
    all_trades = []
    for sym in SYMBOLS:
        df = _load_ohlcv(sym, "15m")
        if df.empty: continue
        df_feats = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_feats)
        df_feats = df_feats.reset_index(drop=True)
        for sig in signals:
            sig_idx = df_feats.index[df_feats["ts"] == sig.ts]
            if len(sig_idx) == 0: continue
            i0 = sig_idx[0]
            if i0 >= len(df_feats) - 1: continue
            entry = float(df_feats["close"].iloc[i0])
            R, exit_price, exit_offset = _exit_with_be(
                df_feats, i0, entry, sig.sl_price,
                tp_r=tp_r, direction=sig.direction,
                be_protect=False, trail_pct=trail_pct,
            )
            all_trades.append({
                "entry_ts": sig.ts,
                "exit_ts": df_feats["ts"].iloc[i0 + exit_offset] if i0 + exit_offset < len(df_feats) else df_feats["ts"].iloc[-1],
                "entry_price": entry, "R": float(R),
                "symbol": sym, "side": sig.direction,
            })
    return pd.DataFrame(all_trades)


VARIANTS_R6 = [
    {"name": "v43_monthly0.12",      "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.12}},
    {"name": "v44_tp2.5",            "trades": {"tp_r": 2.5}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3}},
    {"name": "v45_tp3.0",            "trades": {"tp_r": 3.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3}},
    {"name": "v46_pause2",           "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 2}},
    {"name": "v47_monthly0.10",      "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.10}},
    {"name": "v48_daily0.03",        "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3, "daily_dd_halt": 0.03}},
    {"name": "v49_conc8",            "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 8, "consecutive_loss_pause": 3}},
    {"name": "v50_tp2.5+monthly",    "trades": {"tp_r": 2.5}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.12}},
    {"name": "v51_trail8",           "trades": {"tp_r": 2.0, "trail_pct": 0.08}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3}},
    {"name": "v52_tp3+monthly",      "trades": {"tp_r": 3.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.12}},
    {"name": "v53_conc8+monthly",    "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.005, "max_concurrent": 8, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.12}},
    {"name": "v54_triple",           "trades": {"tp_r": 2.5}, "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 2, "monthly_dd_halt": 0.12}},
]


def main() -> int:
    print("=== rsi2 v6 — v36 üzerine fine-tune (12 varyant) ===\n")
    print(f"{'Varyant':24} {'aylık':>8} {'neg':>7} {'DD':>8} {'yıllık':>9} {'n_tr':>6}  Sonuç")
    print("-" * 110)
    print(f"{'🟢 LIVE':24} {'+12.99%':>8} {'4/61':>7} {'-15.48%':>8} {'+329%':>9} {'4458':>6}  baseline")
    print(f"{'🥇 v36 (önceki best)':24} {'+18.03%':>8} {'8/61':>7} {'-23.22%':>8} {'+556%':>9} {'7994':>6}  ROI patladı")
    print(f"{'🏆 v37':24} {'+10.90%':>8} {'12/61':>7} {'-17.02%':>8} {'+227%':>9} {'5088':>6}  DD denge")
    print("-" * 110)

    out_dir = ROOT / "memory" / "researcher" / "realistic_backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for v in VARIANTS_R6:
        if "trail_pct" in v["trades"]:
            trades_df = collect_trades_with_trail(**v["trades"])
        else:
            trades_df = _collect_basic(**v["trades"])
        if trades_df.empty:
            print(f"{v['name']:24} NO_TRADES")
            continue
        eq_series, final_eq, n_taken = _equity_with_loss_pause(trades_df, **v["equity"])
        m = _compute_metrics(eq_series, 10_000.0)
        # Tier'lar:
        beats_live = (m["monthly_roi"] >= 13.0 and m["max_dd"] >= -20.0)  # live'ı yener
        elite = (m["monthly_roi"] >= 10.0 and m["max_dd"] >= -20.0)
        strict = (m["monthly_roi"] >= 5.0 and m["max_dd"] >= -25.0)
        flag = "👑 BEATS_LIVE" if beats_live else (
            "🏆 ELITE" if elite else ("✅ STRICT" if strict else (
                "🟡" if m["monthly_roi"] > 3 else "❌")))
        print(f"{v['name']:24} "
              f"{m['monthly_roi']:>+7.2f}% "
              f"{m['neg_count']:>2}/{m['total_months']:<3} "
              f"{m['max_dd']:>+7.2f}% "
              f"{m['annualized']:>+8.2f}% "
              f"{n_taken:>6}  {flag}")
        results.append({
            "variant": v["name"], "trades": v["trades"], "equity": v["equity"],
            "n_taken": n_taken, **m, "beats_live": beats_live, "elite": elite, "strict": strict,
        })

    out_path = out_dir / "rsi2-iterate-v6-comparison.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(), "variants": results,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nDetay: {out_path}")

    # En iyi 3
    beats = [r for r in results if r["beats_live"]]
    elites = [r for r in results if r["elite"] and not r["beats_live"]]
    if beats:
        print("\n👑👑 LIVE'I YENEN VARYANTLAR (ROI ≥13, DD ≥-20):")
        for r in sorted(beats, key=lambda r: r["monthly_roi"] / max(abs(r["max_dd"]), 1), reverse=True):
            ratio = r["monthly_roi"] / max(abs(r["max_dd"]), 1)
            print(f"  {r['variant']:24}: aylık +{r['monthly_roi']:.2f}% DD {r['max_dd']:.2f}% neg {r['neg_count']}/{r['total_months']} ratio {ratio:.3f}")
    if elites:
        print("\n🏆 ELITE (ROI ≥10, DD ≥-20):")
        for r in sorted(elites, key=lambda r: r["monthly_roi"], reverse=True)[:3]:
            print(f"  {r['variant']:24}: aylık +{r['monthly_roi']:.2f}% DD {r['max_dd']:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
