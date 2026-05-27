"""session_vwap v2 — OPTIMIZED. Trade'leri 1 kez topla, 12 equity sim hızlı koş.

Eski versiyon her varyant için TÜM 568K signal'i tekrar üretiyordu — 1 saat++.
Bu versiyon: collect_trades 1 kez, sonra 12 farklı equity simulation → ~3-5 dk.

Trade collection değişmiyor (sadece tp_r etkiliyor), o yüzden tp_r=1.5 ve tp_r=1.0/2.0
için ayrı 3 trade pool topla, kalan equity varyantları bu pool'ları kullansın.
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
import time as time_mod
from datetime import datetime, timezone
from iterate_rsi2_variants import SYMBOLS, _load_ohlcv, _exit_with_be, _compute_metrics
from iterate_rsi2_v4 import _equity_with_loss_pause
from price_action.strategies.base import StrategyManifest
from price_action.strategies.session_vwap_mean_reversion import SessionVWAPMeanReversionStrategy


def collect_trades_once(tp_r: float) -> pd.DataFrame:
    """Tek bir tp_r için trade pool topla (her sembol)."""
    manifest = StrategyManifest(name="session_vwap_mean_reversion", version="v2-fast")
    strategy = SessionVWAPMeanReversionStrategy(manifest)
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
            )
            all_trades.append({
                "entry_ts": sig.ts,
                "exit_ts": df_feats["ts"].iloc[i0 + exit_offset] if i0 + exit_offset < len(df_feats) else df_feats["ts"].iloc[-1],
                "R": float(R), "symbol": sym, "side": sig.direction,
            })
    return pd.DataFrame(all_trades)


# Equity varyantları — her birinde tp_r ve equity params
VARIANTS = [
    {"name": "v9_v3+monthly0.12",  "tp_r": 1.5, "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.12}},
    {"name": "v10_v3+monthly0.10", "tp_r": 1.5, "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.10}},
    {"name": "v11_v3+pause2",      "tp_r": 1.5, "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 2}},
    {"name": "v12_v3+conc3",       "tp_r": 1.5, "equity": {"risk_pct": 0.005, "max_concurrent": 3, "consecutive_loss_pause": 3}},
    {"name": "v13_v3+daily0.025",  "tp_r": 1.5, "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3, "daily_dd_halt": 0.025}},
    {"name": "v14_v3+pause2+mon",  "tp_r": 1.5, "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 2, "monthly_dd_halt": 0.12}},
    {"name": "v15_v3+risk0.003",   "tp_r": 1.5, "equity": {"risk_pct": 0.003, "max_concurrent": 4, "consecutive_loss_pause": 3}},
    {"name": "v16_v3+r0.003+mon",  "tp_r": 1.5, "equity": {"risk_pct": 0.003, "max_concurrent": 4, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.12}},
    {"name": "v17_triple_combo",   "tp_r": 1.5, "equity": {"risk_pct": 0.003, "max_concurrent": 4, "consecutive_loss_pause": 2, "monthly_dd_halt": 0.12}},
    {"name": "v18_v3+tp1.0",       "tp_r": 1.0, "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3}},
    {"name": "v19_v3+tp2.0+mon",   "tp_r": 2.0, "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.12}},
    {"name": "v20_conc3+pause2",   "tp_r": 1.5, "equity": {"risk_pct": 0.005, "max_concurrent": 3, "consecutive_loss_pause": 2}},
]


def main() -> int:
    t0 = time_mod.time()
    print("=== session_vwap v2 FAST — DD düşürme (12 varyant) ===\n")

    # Trade pool cache — tp_r başına 1 kez
    unique_tprs = sorted({v["tp_r"] for v in VARIANTS})
    pools = {}
    print(f"Trade pool toplanıyor ({len(unique_tprs)} tp_r değeri)...")
    for tpr in unique_tprs:
        ts = time_mod.time()
        pool = collect_trades_once(tpr)
        print(f"  tp_r={tpr}: {len(pool)} trade ({time_mod.time()-ts:.1f}s)")
        pools[tpr] = pool

    print()
    print(f"{'Varyant':24} {'aylık':>9} {'neg':>7} {'DD':>8} {'yıllık':>9} {'n_tr':>6}  Sonuç")
    print("-" * 110)
    print(f"{'🟢 LIVE':24} {'+12.99%':>9} {'4/61':>7} {'-15.48%':>8} {'+329%':>9} {'4458':>6}  baseline")
    print(f"{'★ v3 önceki ELITE':24} {'+15.28%':>9} {'7/61':>7} {'-21.87%':>8} {'+414%':>9} {'12758':>6}  pre")
    print(f"{'★ v4 SAFE':24} {'+5.77%':>9} {'7/61':>7} {'-9.36%':>8} {'+95%':>9} {'12758':>6}  pre")
    print("-" * 110)

    out_dir = ROOT / "memory" / "researcher" / "realistic_backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for v in VARIANTS:
        trades_df = pools[v["tp_r"]]
        if trades_df.empty:
            print(f"{v['name']:24} NO_TRADES")
            continue
        eq, final_eq, n_taken = _equity_with_loss_pause(trades_df, **v["equity"])
        m = _compute_metrics(eq, 10_000.0)
        ideal = (m["monthly_roi"] >= 10.0 and m["max_dd"] >= -18.0 and m["neg_count"] <= 10)
        beats_live = (m["monthly_roi"] >= 12.99 and m["max_dd"] >= -15.48)
        elite = (m["monthly_roi"] >= 10.0 and m["max_dd"] >= -20.0)
        flag = "👑 BEATS_LIVE" if beats_live else ("⚡ IDEAL" if ideal else (
            "🏆 ELITE" if elite else ("✅ marg" if m["monthly_roi"] > 5 else "❌")))
        print(f"{v['name']:24} "
              f"{m['monthly_roi']:>+8.2f}% "
              f"{m['neg_count']:>2}/{m['total_months']:<3} "
              f"{m['max_dd']:>+7.2f}% "
              f"{m['annualized']:>+8.2f}% "
              f"{n_taken:>6}  {flag}")
        results.append({"variant": v["name"], **v, "n_taken": n_taken, **m,
                       "ideal": ideal, "elite": elite, "beats_live": beats_live})

    out_path = out_dir / "session_vwap_v2_dd_reduce.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(), "variants": results,
    }, indent=2, default=str), encoding="utf-8")

    viable = [r for r in results if r["monthly_roi"] > 0]
    if viable:
        ranked = sorted(viable, key=lambda r: r["monthly_roi"] / max(abs(r["max_dd"]), 1), reverse=True)
        print(f"\n🏆 EN İYİ 3 RİSK-ADJUSTED:")
        for r in ranked[:3]:
            ratio = r["monthly_roi"] / max(abs(r["max_dd"]), 1)
            print(f"  {r['variant']:24}: aylık +{r['monthly_roi']:.2f}% DD {r['max_dd']:.2f}% (ratio {ratio:.3f})")
    print(f"\nToplam süre: {time_mod.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
