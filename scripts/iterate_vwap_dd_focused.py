"""session_vwap v3 — DD düşürme FOKUSU.

Sadece 6 en umut verici varyant, tek tp_r=1.5 (cache 1 kez), saniyeler.

v3 önceki: aylık +%15.28 / DD -%21.87
Hedef: DD -%18 altına (live -%15.48'e yakın), ROI 10-14 bandında.

Önce trade pool'u disk'e cache et (file lock).
"""
from __future__ import annotations
import json, os, sys, warnings, time as time_mod, pickle
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
from iterate_rsi2_variants import SYMBOLS, _load_ohlcv, _exit_with_be, _compute_metrics
from iterate_rsi2_v4 import _equity_with_loss_pause
from price_action.strategies.base import StrategyManifest
from price_action.strategies.session_vwap_mean_reversion import SessionVWAPMeanReversionStrategy


CACHE_PATH = Path("/tmp/vwap_trade_pool_tp1.5.pkl")


def collect_or_load(tp_r: float = 1.5) -> pd.DataFrame:
    """Disk cache — 1 kez topla."""
    if CACHE_PATH.exists():
        try:
            print(f"  Cache LOAD: {CACHE_PATH}")
            return pickle.loads(CACHE_PATH.read_bytes())
        except Exception:
            pass

    print(f"  Trade pool toplanıyor (tp_r={tp_r}, 10 sembol)...")
    manifest = StrategyManifest(name="session_vwap_mean_reversion", version="dd-focused")
    strategy = SessionVWAPMeanReversionStrategy(manifest)
    all_trades = []
    for i, sym in enumerate(SYMBOLS):
        ts = time_mod.time()
        df = _load_ohlcv(sym, "15m")
        if df.empty: continue
        df_feats = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_feats)
        df_feats = df_feats.reset_index(drop=True)
        n_added = 0
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
            n_added += 1
        print(f"    [{i+1}/10] {sym}: {n_added} trade ({time_mod.time()-ts:.1f}s)")

    df_out = pd.DataFrame(all_trades)
    CACHE_PATH.write_bytes(pickle.dumps(df_out))
    print(f"  Cache SAVE: {len(df_out)} trade → {CACHE_PATH}")
    return df_out


# Sadece DD düşürücü 6 varyant (tek tp_r=1.5)
VARIANTS = [
    {"name": "v3_baseline",             "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3}},
    {"name": "v9_+monthly0.12",         "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.12}},
    {"name": "v11_pause2",              "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 2}},
    {"name": "v14_pause2+monthly0.12",  "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 2, "monthly_dd_halt": 0.12}},
    {"name": "v15_risk0.003",           "equity": {"risk_pct": 0.003, "max_concurrent": 4, "consecutive_loss_pause": 3}},
    {"name": "v17_triple_combo",        "equity": {"risk_pct": 0.003, "max_concurrent": 4, "consecutive_loss_pause": 2, "monthly_dd_halt": 0.12}},
    {"name": "v18_pause2+conc3",        "equity": {"risk_pct": 0.005, "max_concurrent": 3, "consecutive_loss_pause": 2}},
    {"name": "v19_safest",              "equity": {"risk_pct": 0.003, "max_concurrent": 3, "consecutive_loss_pause": 2, "monthly_dd_halt": 0.10, "daily_dd_halt": 0.02}},
]


def main() -> int:
    t0 = time_mod.time()
    print("=== session_vwap DD-FOCUSED (8 varyant) ===\n")
    pool = collect_or_load(tp_r=1.5)
    if pool.empty:
        print("HİÇ TRADE YOK"); return 1
    print()
    print(f"{'Varyant':26} {'aylık':>9} {'neg':>7} {'DD':>8} {'yıllık':>9} {'n_tr':>6}  Sonuç")
    print("-" * 105)
    print(f"{'🟢 LIVE':26} {'+12.99%':>9} {'4/61':>7} {'-15.48%':>8} {'+329%':>9} {'4458':>6}  baseline")
    print(f"{'★ v3 önceki':26} {'+15.28%':>9} {'7/61':>7} {'-21.87%':>8} {'+414%':>9} {'12758':>6}  pre")
    print("-" * 105)

    out_dir = ROOT / "memory" / "researcher" / "realistic_backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for v in VARIANTS:
        eq, final_eq, n_taken = _equity_with_loss_pause(pool, **v["equity"])
        m = _compute_metrics(eq, 10_000.0)
        beats_live = (m["monthly_roi"] >= 12.99 and m["max_dd"] >= -15.48)
        ideal = (m["monthly_roi"] >= 10.0 and m["max_dd"] >= -18.0)
        elite = (m["monthly_roi"] >= 10.0 and m["max_dd"] >= -20.0)
        flag = "👑 BEATS_LIVE" if beats_live else ("⚡ IDEAL" if ideal else (
            "🏆 ELITE" if elite else ("✅" if m["monthly_roi"] > 5 else "🟡")))
        print(f"{v['name']:26} "
              f"{m['monthly_roi']:>+8.2f}% "
              f"{m['neg_count']:>2}/{m['total_months']:<3} "
              f"{m['max_dd']:>+7.2f}% "
              f"{m['annualized']:>+8.2f}% "
              f"{n_taken:>6}  {flag}")
        results.append({"variant": v["name"], **v, "n_taken": n_taken, **m,
                       "beats_live": beats_live, "ideal": ideal, "elite": elite})

    out_path = out_dir / "session_vwap_dd_focused.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(), "variants": results,
    }, indent=2, default=str), encoding="utf-8")

    viable = [r for r in results if r["monthly_roi"] > 0]
    if viable:
        ranked = sorted(viable, key=lambda r: r["monthly_roi"] / max(abs(r["max_dd"]), 1), reverse=True)
        print(f"\n🏆 EN İYİ 3 RİSK-ADJUSTED:")
        for r in ranked[:3]:
            ratio = r["monthly_roi"] / max(abs(r["max_dd"]), 1)
            print(f"  {r['variant']:26}: aylık +{r['monthly_roi']:.2f}% DD {r['max_dd']:.2f}% ratio {ratio:.3f}")
    print(f"\nToplam süre: {time_mod.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
