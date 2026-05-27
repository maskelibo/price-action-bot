"""rsi2 round 3 — v9'u inceltme + alternatif denemeler.

v9 sınırı KIL PAYI kaçırdı (DD -26.41 vs -25, neg 22 vs 20).
Hedef: PROMOTE eşiği (aylık ≥4%, DD ≥-25%, neg ≤20).

Yeni varyantlar:
  v9.1: v9 + daily_dd 0.015 (sıkılaştır)
  v9.2: v9 + concurrent=3 (daha sıkı cap)
  v9.3: v9 + monthly_dd 0.10 (aylık halt)
  v15:  v7 (concurrent=4) + tp_r=2.0 (daha geniş TP)
  v16:  v7 + tp_r=1.0 (daha hızlı TP)
  v17:  long-only (short bias kaldır)
  v18:  short-only (long bias kaldır)
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
from iterate_rsi2_variants import (
    SYMBOLS, _load_ohlcv, _exit_with_be, _equity_sim_with_dd_halt, _compute_metrics
)
from price_action.strategies.base import StrategyManifest
from price_action.strategies.rsi2_extreme_fade import RSI2ExtremeFadeStrategy


def _equity_with_monthly_halt(
    trades_df: pd.DataFrame, *,
    initial_capital: float = 10_000.0,
    risk_pct: float = 0.005,
    daily_dd_halt: float | None = None,
    monthly_dd_halt: float | None = None,
    max_concurrent: int = 999,
) -> tuple[pd.Series, float, int]:
    """Equity sim + daily + monthly halt."""
    if trades_df.empty:
        return pd.Series(dtype=float), initial_capital, 0
    sorted_trades = trades_df.sort_values("entry_ts").reset_index(drop=True)
    equity = initial_capital
    eq_data = []
    n_taken = 0
    halted_days, halted_months = set(), set()
    day_start_eq, month_start_eq = {}, {}
    open_positions = []
    for _, t in sorted_trades.iterrows():
        entry_ts = pd.Timestamp(t["entry_ts"])
        exit_ts = pd.Timestamp(t["exit_ts"])
        day_key = entry_ts.date()
        month_key = (entry_ts.year, entry_ts.month)
        # Halt checks
        if monthly_dd_halt and month_key not in month_start_eq:
            month_start_eq[month_key] = equity
        if daily_dd_halt and day_key not in day_start_eq:
            day_start_eq[day_key] = equity
        if day_key in halted_days or month_key in halted_months:
            continue
        # Concurrent cap
        open_positions = [p for p in open_positions if p["exit_ts"] > entry_ts]
        if len(open_positions) >= max_concurrent:
            continue
        # Trade
        risk_d = equity * risk_pct
        pnl = risk_d * float(t["R"])
        equity += pnl
        n_taken += 1
        eq_data.append({"ts": exit_ts, "equity": equity})
        open_positions.append({"exit_ts": exit_ts})
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


def collect_trades(*, side_only: str | None = None, tp_r: float = 1.5) -> pd.DataFrame:
    manifest = StrategyManifest(name="rsi2_extreme_fade", version="v3")
    strategy = RSI2ExtremeFadeStrategy(manifest)
    all_trades = []
    for sym in SYMBOLS:
        df = _load_ohlcv(sym, "15m")
        if df.empty: continue
        df_feats = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_feats)
        df_feats = df_feats.reset_index(drop=True)
        for sig in signals:
            if side_only and sig.direction != side_only:
                continue
            sig_idx = df_feats.index[df_feats["ts"] == sig.ts]
            if len(sig_idx) == 0: continue
            i0 = sig_idx[0]
            if i0 >= len(df_feats) - 1: continue
            entry = float(df_feats["close"].iloc[i0])
            R, exit_price, exit_offset = _exit_with_be(
                df_feats, i0, entry, sig.sl_price,
                tp_r=tp_r, direction=sig.direction, be_protect=False,
            )
            all_trades.append({
                "entry_ts": sig.ts,
                "exit_ts": df_feats["ts"].iloc[i0 + exit_offset] if i0 + exit_offset < len(df_feats) else df_feats["ts"].iloc[-1],
                "entry_price": entry, "R": float(R),
                "symbol": sym, "side": sig.direction,
            })
    return pd.DataFrame(all_trades)


VARIANTS_R3 = [
    {"name": "v9.1_daily0.015",   "trades": {}, "equity": {"risk_pct": 0.002, "daily_dd_halt": 0.015, "max_concurrent": 4}},
    {"name": "v9.2_concurrent3",  "trades": {}, "equity": {"risk_pct": 0.002, "daily_dd_halt": 0.02, "max_concurrent": 3}},
    {"name": "v9.3_monthly0.10",  "trades": {}, "equity": {"risk_pct": 0.002, "daily_dd_halt": 0.02, "max_concurrent": 4, "monthly_dd_halt": 0.10}},
    {"name": "v15_v7_tp2.0",      "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.005, "daily_dd_halt": None, "max_concurrent": 4}},
    {"name": "v16_v7_tp1.0",      "trades": {"tp_r": 1.0}, "equity": {"risk_pct": 0.005, "daily_dd_halt": None, "max_concurrent": 4}},
    {"name": "v17_long_only",     "trades": {"side_only": "long"}, "equity": {"risk_pct": 0.002, "daily_dd_halt": 0.02, "max_concurrent": 4}},
    {"name": "v18_short_only",    "trades": {"side_only": "short"}, "equity": {"risk_pct": 0.002, "daily_dd_halt": 0.02, "max_concurrent": 4}},
    {"name": "v19_v9_tp1.0",      "trades": {"tp_r": 1.0}, "equity": {"risk_pct": 0.002, "daily_dd_halt": 0.02, "max_concurrent": 4}},
    {"name": "v20_v9_tp2.0",      "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.002, "daily_dd_halt": 0.02, "max_concurrent": 4}},
]


def main() -> int:
    print("=== rsi2 v3 — 9 yeni varyant ===\n")
    print(f"{'Varyant':22} {'aylık':>8} {'neg':>7} {'DD':>8} {'yıllık':>9} {'n_tr':>6}  Sonuç")
    print("-" * 110)
    print(f"{'🟢 LIVE':22} {'+12.99%':>8} {'4/61':>7} {'-15.48%':>8} {'+329%':>9} {'4458':>6}  baseline")
    print(f"{'🟡 v9 (round 2)':22} {'+4.08%':>8} {'22/61':>7} {'-26.41%':>8} {'+57%':>9} {'26527':>6}  sınırda")
    print("-" * 110)
    out_dir = ROOT / "memory" / "researcher" / "realistic_backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for v in VARIANTS_R3:
        trades_df = collect_trades(**v["trades"])
        if trades_df.empty:
            print(f"{v['name']:22} NO_TRADES")
            continue
        eq_series, final_eq, n_taken = _equity_with_monthly_halt(trades_df, **v["equity"])
        m = _compute_metrics(eq_series, 10_000.0)
        promote = (m["monthly_roi"] >= 4.0 and m["max_dd"] >= -25.0 and m["neg_count"] <= 20)
        flag = "✅✅ PROMOTE" if promote else (
            "🟡 marginal" if m["monthly_roi"] > 2 and m["max_dd"] > -50 else "❌"
        )
        print(f"{v['name']:22} "
              f"{m['monthly_roi']:>+7.2f}% "
              f"{m['neg_count']:>2}/{m['total_months']:<3} "
              f"{m['max_dd']:>+7.2f}% "
              f"{m['annualized']:>+8.2f}% "
              f"{n_taken:>6}  {flag}")
        results.append({
            "variant": v["name"], "trades": v["trades"], "equity": v["equity"],
            "n_taken": n_taken, **m, "promote": promote,
        })
    out_path = out_dir / "rsi2-iterate-v3-comparison.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(), "variants": results,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nDetay: {out_path}")
    # Champion bul
    promoted = [r for r in results if r.get("promote")]
    if promoted:
        best = max(promoted, key=lambda r: r["monthly_roi"])
        print(f"\n🏆 EN İYİ PROMOTE: {best['variant']}")
        print(f"  Aylık: +{best['monthly_roi']:.2f}%, DD: {best['max_dd']:.2f}%, "
              f"Neg: {best['neg_count']}/{best['total_months']}, Yıllık: +{best['annualized']:.2f}%")
    else:
        # Yine PROMOTE yok — en iyi marginal
        viable = [r for r in results if r["monthly_roi"] > 0]
        if viable:
            best = max(viable, key=lambda r: r["monthly_roi"] / max(abs(r["max_dd"]), 1))
            print(f"\n🟡 EN İYİ RİSK-ADJUSTED: {best['variant']}")
            print(f"  Aylık: +{best['monthly_roi']:.2f}%, DD: {best['max_dd']:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
