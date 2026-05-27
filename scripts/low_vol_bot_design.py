"""Gerçek düşük-vol bot tasarımı.

User: 'Düşük vol bot yapsana.'

Hipotez: Bollinger Band Squeeze + Breakout, sadece BTC ATR/price < %2
günlerinde aktif. Düşük vol → squeeze → breakout (high vol'a geçiş yakalama).

Önceki test (vol filter YOK): -%2.33 / -%80 (kötü)
Şimdi: vol filter + risk control ile 8 varyant.

Hızlı: bollinger_squeeze sayısı az (~10K), cache ile saniyeler içinde.
"""
from __future__ import annotations
import json, os, sys, warnings, time as time_mod
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
from price_action.strategies.bollinger_squeeze_breakout import BollingerSqueezeBreakoutStrategy


def _get_btc_vol_filter():
    """BTC daily ATR/price hesabı. <%2 = düşük vol."""
    df = _load_ohlcv("BTC/USDT", "1d")
    if df.empty:
        return None
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr14"] / c
    df = df[["ts", "atr_pct"]].set_index("ts")
    return df


def collect_signals(tp_r: float = 2.0) -> pd.DataFrame:
    """1 kez topla — tüm tp_r için yeniden hesaplamadan."""
    manifest = StrategyManifest(name="bollinger_squeeze_breakout", version="low-vol")
    strategy = BollingerSqueezeBreakoutStrategy(manifest)
    all_trades = []
    for sym in SYMBOLS:
        df = _load_ohlcv(sym, "15m")
        if df.empty:
            continue
        try:
            df_feats = strategy.prepare_features(df)
            signals = strategy.generate_signals(df_feats)
        except Exception:
            continue
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


def apply_vol_filter(trades: pd.DataFrame, btc_atr: pd.DataFrame, threshold: float | None) -> pd.DataFrame:
    """Sadece BTC vol < threshold olan günlerin trade'lerini tut."""
    if threshold is None or trades.empty:
        return trades.copy()
    out = []
    for _, t in trades.iterrows():
        day_ts = pd.Timestamp(t["entry_ts"]).floor("1D")
        if day_ts in btc_atr.index:
            atr_p = btc_atr.loc[day_ts, "atr_pct"]
        else:
            idx = btc_atr.index.searchsorted(day_ts)
            if idx == 0 or idx >= len(btc_atr):
                continue
            atr_p = btc_atr.iloc[idx - 1]["atr_pct"]
        if pd.notna(atr_p) and atr_p < threshold:
            out.append(t)
    return pd.DataFrame(out) if out else pd.DataFrame()


VARIANTS = [
    {"name": "v1_no_filter",         "tp_r": 2.0, "vol_thr": None,   "equity": {"risk_pct": 0.005, "max_concurrent": 999}},
    {"name": "v2_vol<2.5%",          "tp_r": 2.0, "vol_thr": 0.025,  "equity": {"risk_pct": 0.005, "max_concurrent": 999}},
    {"name": "v3_vol<2.0%",          "tp_r": 2.0, "vol_thr": 0.020,  "equity": {"risk_pct": 0.005, "max_concurrent": 999}},
    {"name": "v4_vol<1.5%",          "tp_r": 2.0, "vol_thr": 0.015,  "equity": {"risk_pct": 0.005, "max_concurrent": 999}},
    {"name": "v5_vol<2.0+conc4",     "tp_r": 2.0, "vol_thr": 0.020,  "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3}},
    {"name": "v6_vol<2.5+conc4+tp3", "tp_r": 3.0, "vol_thr": 0.025,  "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3}},
    {"name": "v7_vol<2.0+safe",      "tp_r": 2.0, "vol_thr": 0.020,  "equity": {"risk_pct": 0.003, "max_concurrent": 4, "consecutive_loss_pause": 3, "daily_dd_halt": 0.02}},
    {"name": "v8_vol<1.8+combo",     "tp_r": 2.5, "vol_thr": 0.018,  "equity": {"risk_pct": 0.003, "max_concurrent": 4, "consecutive_loss_pause": 3, "monthly_dd_halt": 0.12}},
]


def main() -> int:
    t0 = time_mod.time()
    print("=== Düşük-Vol Bot Tasarımı (bollinger_squeeze_breakout) ===\n")

    btc_atr = _get_btc_vol_filter()
    print(f"BTC daily veri: {len(btc_atr)} gün")
    for thr in [0.025, 0.020, 0.015]:
        n = (btc_atr["atr_pct"] < thr).sum()
        print(f"  BTC ATR/price < {thr*100:.1f}%: {n} gün ({n/len(btc_atr)*100:.1f}%)")
    print()

    # tp_r için trade pool — 3 farklı: 2.0, 3.0, 2.5
    unique_tprs = sorted({v["tp_r"] for v in VARIANTS})
    pools = {}
    for tpr in unique_tprs:
        ts = time_mod.time()
        pool = collect_signals(tp_r=tpr)
        print(f"  tp_r={tpr}: {len(pool)} signal toplandı ({time_mod.time()-ts:.1f}s)")
        pools[tpr] = pool

    print()
    print(f"{'Varyant':28} {'aylık':>9} {'neg':>7} {'DD':>8} {'yıllık':>10} {'n_tr':>7}  Sonuç")
    print("-" * 115)
    print(f"{'🟢 LIVE (high-vol bot)':28} {'+12.99%':>9} {'4/61':>7} {'-15.48%':>8} {'+329%':>10} {'4458':>7}  baseline")
    print("-" * 115)

    out_dir = ROOT / "memory" / "researcher" / "realistic_backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for v in VARIANTS:
        base = pools[v["tp_r"]]
        if base.empty:
            print(f"{v['name']:28} NO_BASE_TRADES")
            continue
        filtered = apply_vol_filter(base, btc_atr, v["vol_thr"])
        if filtered.empty:
            print(f"{v['name']:28} FILTER_KILLED ({len(base)} → 0)")
            continue
        eq, final_eq, n_taken = _equity_with_loss_pause(filtered, **v["equity"])
        m = _compute_metrics(eq, 10_000.0)
        ideal = (m["monthly_roi"] >= 5.0 and m["max_dd"] >= -18.0)
        good = (m["monthly_roi"] >= 3.0 and m["max_dd"] >= -25.0)
        flag = "⚡ IDEAL" if ideal else ("✅ good" if good else (
            "🟡 marg" if m["monthly_roi"] > 0 else "❌"))
        print(f"{v['name']:28} "
              f"{m['monthly_roi']:>+8.2f}% "
              f"{m['neg_count']:>2}/{m['total_months']:<3} "
              f"{m['max_dd']:>+7.2f}% "
              f"{m['annualized']:>+9.2f}% "
              f"{n_taken:>7}  {flag}  (vol<{v['vol_thr']*100 if v['vol_thr'] else 'all'}, tp={v['tp_r']})")
        results.append({"variant": v["name"], **v, "n_filtered": len(filtered), "n_taken": n_taken, **m,
                       "ideal": ideal, "good": good})

    out_path = out_dir / "low_vol_bot_design.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "btc_low_vol_days": {
            "atr<2.5%": int((btc_atr["atr_pct"] < 0.025).sum()),
            "atr<2.0%": int((btc_atr["atr_pct"] < 0.020).sum()),
            "atr<1.5%": int((btc_atr["atr_pct"] < 0.015).sum()),
            "total_days": int(len(btc_atr)),
        },
        "variants": results,
    }, indent=2, default=str), encoding="utf-8")

    viable = [r for r in results if r["monthly_roi"] > 0]
    if viable:
        ranked = sorted(viable, key=lambda r: r["monthly_roi"] / max(abs(r["max_dd"]), 1), reverse=True)
        print(f"\n🏆 EN İYİ 3 RİSK-ADJUSTED:")
        for r in ranked[:3]:
            ratio = r["monthly_roi"] / max(abs(r["max_dd"]), 1)
            print(f"  {r['variant']:28}: aylık +{r['monthly_roi']:.2f}% DD {r['max_dd']:.2f}% (ratio {ratio:.3f})")
    print(f"\nDetay: {out_path}")
    print(f"Toplam süre: {time_mod.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
