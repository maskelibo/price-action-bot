"""session_vwap_mean_reversion rescue — düşük-vol bot adayı.

User: 'Dar piyasalarda iş yapacak bir bot yapsana.'

Baseline: aylık +%277 / DD -%100 / n=568,593 (5y) — agresif sinyal, edge var.
Yapılacak: risk reduction + concurrent cap + loss pause + regime gate.

Bu rsi2 v63 yolculuğunun kısaltılmış hali (1-2 round).
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
from iterate_rsi2_variants import SYMBOLS, _load_ohlcv, _exit_with_be, _compute_metrics
from iterate_rsi2_v4 import _equity_with_loss_pause
from price_action.strategies.base import StrategyManifest
from price_action.strategies.session_vwap_mean_reversion import SessionVWAPMeanReversionStrategy


def _get_btc_low_vol_filter():
    """BTC günlük ATR/price < %2 → düşük vol regime."""
    df = _load_ohlcv("BTC/USDT", "1d")
    if df.empty:
        return None
    h = df["high"]
    l = df["low"]
    c = df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr14"] / c
    df["low_vol"] = df["atr_pct"] < 0.02  # %2 altı = düşük vol
    return df[["ts", "low_vol", "atr_pct"]].set_index("ts")


def collect_trades(*, tp_r: float = 1.5, regime_filter=None) -> pd.DataFrame:
    manifest = StrategyManifest(name="session_vwap_mean_reversion", version="iterate")
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
            # Regime filter — sadece low vol gün
            if regime_filter is not None:
                sig_day = pd.Timestamp(sig.ts).floor("1D")
                if sig_day in regime_filter.index:
                    if not regime_filter.loc[sig_day, "low_vol"]:
                        continue
                else:
                    nearest = regime_filter.index.searchsorted(sig_day)
                    if nearest == 0 or nearest >= len(regime_filter):
                        continue
                    if not regime_filter.iloc[nearest - 1]["low_vol"]:
                        continue
            R, exit_price, exit_offset = _exit_with_be(
                df_feats, i0, entry, sig.sl_price,
                tp_r=tp_r, direction=sig.direction,
            )
            all_trades.append({
                "entry_ts": sig.ts, "exit_ts": df_feats["ts"].iloc[i0 + exit_offset] if i0 + exit_offset < len(df_feats) else df_feats["ts"].iloc[-1],
                "R": float(R), "symbol": sym, "side": sig.direction,
            })
    return pd.DataFrame(all_trades)


VARIANTS = [
    {"name": "v1_baseline",                "trades": {"tp_r": 1.5}, "equity": {"risk_pct": 0.005, "max_concurrent": 999}, "regime": False},
    {"name": "v2_risk_red",                "trades": {"tp_r": 1.5}, "equity": {"risk_pct": 0.002, "max_concurrent": 999, "daily_dd_halt": 0.02}, "regime": False},
    {"name": "v3_concurrent4_pause3",      "trades": {"tp_r": 1.5}, "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3}, "regime": False},
    {"name": "v4_combo_risk_conc",         "trades": {"tp_r": 1.5}, "equity": {"risk_pct": 0.002, "max_concurrent": 4, "consecutive_loss_pause": 3, "daily_dd_halt": 0.02}, "regime": False},
    {"name": "v5_low_vol_only",            "trades": {"tp_r": 1.5}, "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3}, "regime": True},
    {"name": "v6_combo_low_vol",           "trades": {"tp_r": 1.5}, "equity": {"risk_pct": 0.002, "max_concurrent": 4, "consecutive_loss_pause": 3, "daily_dd_halt": 0.02}, "regime": True},
    {"name": "v7_tp2.0_low_vol",           "trades": {"tp_r": 2.0}, "equity": {"risk_pct": 0.002, "max_concurrent": 4, "consecutive_loss_pause": 3}, "regime": True},
    {"name": "v8_tp3.0_low_vol_conc6",     "trades": {"tp_r": 3.0}, "equity": {"risk_pct": 0.002, "max_concurrent": 6, "consecutive_loss_pause": 3}, "regime": True},
]


def main() -> int:
    print("=== session_vwap_mean_reversion RESCUE ===\n")
    print(f"{'Varyant':28} {'aylık':>9} {'neg':>7} {'DD':>8} {'yıllık':>10} {'n_tr':>7}  Sonuç")
    print("-" * 110)
    print(f"{'🟢 LIVE':28} {'+12.99%':>9} {'4/61':>7} {'-15.48%':>8} {'+329%':>10} {'4458':>7}  baseline")
    print(f"{'🏆 v63 (rsi2)':28} {'+20.08%':>9} {'11/61':>7} {'-16.95%':>8} {'+640%':>10} {'4610':>7}  high-vol rescue")
    print("-" * 110)
    btc_regime = _get_btc_low_vol_filter()
    print(f"BTC low-vol gün sayısı: {int(btc_regime['low_vol'].sum())} / {len(btc_regime)} ({btc_regime['low_vol'].mean()*100:.0f}%)")
    print("-" * 110)
    out_dir = ROOT / "memory" / "researcher" / "realistic_backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for v in VARIANTS:
        regime = btc_regime if v["regime"] else None
        trades_df = collect_trades(**v["trades"], regime_filter=regime)
        if trades_df.empty:
            print(f"{v['name']:28} NO_TRADES")
            continue
        eq, final_eq, n_taken = _equity_with_loss_pause(trades_df, **v["equity"])
        m = _compute_metrics(eq, 10_000.0)
        elite = (m["monthly_roi"] >= 10.0 and m["max_dd"] >= -20.0)
        strict = (m["monthly_roi"] >= 5.0 and m["max_dd"] >= -25.0)
        flag = "🏆 ELITE" if elite else ("✅ STRICT" if strict else ("🟡 marg" if m["monthly_roi"] > 0 else "❌"))
        print(f"{v['name']:28} "
              f"{m['monthly_roi']:>+8.2f}% "
              f"{m['neg_count']:>2}/{m['total_months']:<3} "
              f"{m['max_dd']:>+7.2f}% "
              f"{m['annualized']:>+9.2f}% "
              f"{n_taken:>7}  {flag}")
        results.append({"variant": v["name"], **v, "n_taken": n_taken, **m, "elite": elite, "strict": strict})

    out_path = out_dir / "session_vwap_iterate.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(), "variants": results,
    }, indent=2, default=str), encoding="utf-8")

    viable = [r for r in results if r["monthly_roi"] > 0]
    if viable:
        ranked = sorted(viable, key=lambda r: r["monthly_roi"] / max(abs(r["max_dd"]), 1), reverse=True)
        print(f"\n🏆 EN İYİ 3 RİSK-ADJUSTED:")
        for r in ranked[:3]:
            ratio = r["monthly_roi"] / max(abs(r["max_dd"]), 1)
            print(f"  {r['variant']:28}: aylık +{r['monthly_roi']:.2f}% DD {r['max_dd']:.2f}% (ratio {ratio:.3f})")
    print(f"\nDetay: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
