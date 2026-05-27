"""rsi2 round 4 — ROI öncelikli iterasyon.

User: 'ROI çok düştü böyle' (v9.1 sadece +%4).
Hedef: aylık >= 6%, DD ≤ -30% (live'a daha yakın trade-off).

Strateji: agresif risk azaltma yerine SMART risk kontrolleri:
  - Monthly DD halt (büyük loser ayı dur, küçük zaman ayları normal)
  - Consecutive loss pause (loss streak break, küçük risk değişimi)
  - Volatility-aware position sizing (yüksek vol = küçük risk)
  - Daha gevşek concurrent cap (8 yerine 4)

Yeni varyantlar (10):
  v21 medium balance     risk=0.003 conc=6 daily=0.025
  v22 v7 + monthly halt  risk=0.005 conc=4 monthly=0.15
  v23 v15 + monthly halt risk=0.005 conc=4 monthly=0.15 tp=2.0
  v24 risk=0.004 conc=6  risk=0.004 conc=6 daily=0.025
  v25 risk=0.0035 conc=5 risk=0.0035 conc=5 daily=0.02 monthly=0.12
  v26 v7+loss_pause      risk=0.005 conc=4 consecutive_loss=3
  v27 best_short_only    risk=0.005 conc=4 short_only
  v28 v15+conc=6         risk=0.005 conc=6 tp=2.0 monthly=0.12
  v29 ultra_balanced     risk=0.003 conc=4 daily=0.025 tp=2.0
  v30 risk=0.004+v7      risk=0.004 conc=4 daily=0.03
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
from iterate_rsi2_v3 import _equity_with_monthly_halt, collect_trades
from iterate_rsi2_variants import _compute_metrics


def _equity_with_loss_pause(
    trades_df: pd.DataFrame, *,
    initial_capital: float = 10_000.0,
    risk_pct: float = 0.005,
    daily_dd_halt: float | None = None,
    monthly_dd_halt: float | None = None,
    max_concurrent: int = 999,
    consecutive_loss_pause: int | None = None,
    pause_days: int = 1,
) -> tuple[pd.Series, float, int]:
    """Equity sim + loss streak pause (örn 3 art arda kayıp → 1 gün dur)."""
    if trades_df.empty:
        return pd.Series(dtype=float), initial_capital, 0
    sorted_trades = trades_df.sort_values("entry_ts").reset_index(drop=True)
    equity = initial_capital
    eq_data = []
    n_taken = 0
    halted_days, halted_months = set(), set()
    day_start_eq, month_start_eq = {}, {}
    open_positions = []
    consecutive_losses = 0
    pause_until = None
    for _, t in sorted_trades.iterrows():
        entry_ts = pd.Timestamp(t["entry_ts"])
        exit_ts = pd.Timestamp(t["exit_ts"])
        day_key = entry_ts.date()
        month_key = (entry_ts.year, entry_ts.month)
        if pause_until and entry_ts < pause_until:
            continue
        if monthly_dd_halt and month_key not in month_start_eq:
            month_start_eq[month_key] = equity
        if daily_dd_halt and day_key not in day_start_eq:
            day_start_eq[day_key] = equity
        if day_key in halted_days or month_key in halted_months:
            continue
        open_positions = [p for p in open_positions if p["exit_ts"] > entry_ts]
        if len(open_positions) >= max_concurrent:
            continue
        risk_d = equity * risk_pct
        R = float(t["R"])
        pnl = risk_d * R
        equity += pnl
        n_taken += 1
        eq_data.append({"ts": exit_ts, "equity": equity})
        open_positions.append({"exit_ts": exit_ts})
        # Consecutive loss tracking
        if R < 0:
            consecutive_losses += 1
            if consecutive_loss_pause and consecutive_losses >= consecutive_loss_pause:
                pause_until = exit_ts + pd.Timedelta(days=pause_days)
                consecutive_losses = 0
        else:
            consecutive_losses = 0
        if daily_dd_halt:
            ddd = (equity - day_start_eq[day_key]) / day_start_eq[day_key]
            if ddd <= -daily_dd_halt:
                halted_days.add(day_key)
        if monthly_dd_halt:
            mdd = (equity - month_start_eq[month_key]) / month_start_eq[month_key]
            if mdd <= -monthly_dd_halt:
                halted_months.add(month_key)
    if not eq_data:
        return pd.Series(dtype=float), initial_capital, n_taken
    eq_df = pd.DataFrame(eq_data)
    eq_series = pd.Series(eq_df["equity"].values, index=pd.to_datetime(eq_df["ts"], utc=True))
    return eq_series, equity, n_taken


VARIANTS_R4 = [
    {"name": "v21_balance",       "trades": {},                  "equity": {"risk_pct": 0.003,  "daily_dd_halt": 0.025, "max_concurrent": 6}},
    {"name": "v22_v7+monthly",    "trades": {},                  "equity": {"risk_pct": 0.005,  "max_concurrent": 4, "monthly_dd_halt": 0.15}},
    {"name": "v23_v15+monthly",   "trades": {"tp_r": 2.0},       "equity": {"risk_pct": 0.005,  "max_concurrent": 4, "monthly_dd_halt": 0.15}},
    {"name": "v24_r0.004_c6",     "trades": {},                  "equity": {"risk_pct": 0.004,  "daily_dd_halt": 0.025, "max_concurrent": 6}},
    {"name": "v25_r0.0035_c5",    "trades": {},                  "equity": {"risk_pct": 0.0035, "daily_dd_halt": 0.02, "max_concurrent": 5, "monthly_dd_halt": 0.12}},
    {"name": "v26_v7+loss3",      "trades": {},                  "equity": {"risk_pct": 0.005,  "max_concurrent": 4, "consecutive_loss_pause": 3}},
    {"name": "v27_short+normal",  "trades": {"side_only": "short"}, "equity": {"risk_pct": 0.005, "max_concurrent": 4}},
    {"name": "v28_v15+c6+mon",    "trades": {"tp_r": 2.0},       "equity": {"risk_pct": 0.005,  "max_concurrent": 6, "monthly_dd_halt": 0.12}},
    {"name": "v29_balance+tp2",   "trades": {"tp_r": 2.0},       "equity": {"risk_pct": 0.003,  "daily_dd_halt": 0.025, "max_concurrent": 4}},
    {"name": "v30_r0.004+v7",     "trades": {},                  "equity": {"risk_pct": 0.004,  "daily_dd_halt": 0.03, "max_concurrent": 4}},
]


def main() -> int:
    print("=== rsi2 v4 — ROI öncelikli 10 varyant ===\n")
    print(f"{'Varyant':22} {'aylık':>8} {'neg':>7} {'DD':>8} {'yıllık':>9} {'n_tr':>6}  Sonuç")
    print("-" * 110)
    print(f"{'🟢 LIVE':22} {'+12.99%':>8} {'4/61':>7} {'-15.48%':>8} {'+329%':>9} {'4458':>6}  baseline")
    print(f"{'✅ v9.1 (önceki PROM)':22} {'+4.04%':>8} {'20/61':>7} {'-24.01%':>8} {'+57%':>9} {'25184':>6}  düşük ROI")
    print(f"{'🟡 v7 (yüksek ROI)':22} {'+10.44%':>8} {'24/61':>7} {'-58.42%':>8} {'+173%':>9} {'27394':>6}  DD kötü")
    print("-" * 110)

    out_dir = ROOT / "memory" / "researcher" / "realistic_backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for v in VARIANTS_R4:
        trades_df = collect_trades(**v["trades"])
        if trades_df.empty:
            print(f"{v['name']:22} NO_TRADES")
            continue
        eq_series, final_eq, n_taken = _equity_with_loss_pause(trades_df, **v["equity"])
        m = _compute_metrics(eq_series, 10_000.0)
        # Gevşek gate: aylık >=5%, DD >=-35%, neg <=22
        promote = (m["monthly_roi"] >= 5.0 and m["max_dd"] >= -35.0 and m["neg_count"] <= 22)
        strict = (m["monthly_roi"] >= 4.0 and m["max_dd"] >= -25.0 and m["neg_count"] <= 20)
        flag = "✅✅ STRICT" if strict else ("✅ LOOSE" if promote else (
            "🟡 marg" if m["monthly_roi"] > 3 else "❌"))
        print(f"{v['name']:22} "
              f"{m['monthly_roi']:>+7.2f}% "
              f"{m['neg_count']:>2}/{m['total_months']:<3} "
              f"{m['max_dd']:>+7.2f}% "
              f"{m['annualized']:>+8.2f}% "
              f"{n_taken:>6}  {flag}")
        results.append({
            "variant": v["name"], "trades": v["trades"], "equity": v["equity"],
            "n_taken": n_taken, **m, "strict_promote": strict, "loose_promote": promote,
        })

    out_path = out_dir / "rsi2-iterate-v4-comparison.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(), "variants": results,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nDetay: {out_path}")

    # En iyi 3 — risk-adjusted (return/abs(DD))
    viable = [r for r in results if r["monthly_roi"] > 0]
    if viable:
        ranked = sorted(viable, key=lambda r: r["monthly_roi"] / max(abs(r["max_dd"]), 1), reverse=True)
        print("\n🏆 EN İYİ 3 RISK-ADJUSTED:")
        for i, r in enumerate(ranked[:3], 1):
            ratio = r["monthly_roi"] / max(abs(r["max_dd"]), 1)
            print(f"  #{i} {r['variant']:22}: aylık +{r['monthly_roi']:.2f}% DD {r['max_dd']:.2f}% (ratio {ratio:.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
