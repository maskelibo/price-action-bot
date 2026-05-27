"""rsi2-extreme-fade v2 iterasyon — daha akıllı varyantlar.

Faz 14.23 round 2: İlk round bulgular:
  - v2 risk_reduction = ŞAMPİYON (DD %33, aylık +%5.91)
  - v4 BE-protect = FELAKET (mean-rev'e uyuşmaz)
  - v3/v6 confluence filter = NO_TRADES (rsi2 confluence sabit 2.0)
  - v5 regime = DD hala kötü

Yeni varyantlar:
  v2.1: risk_pct 0.001 (daha agresif azaltma)
  v7  : max_concurrent = 4 (cluster losses break)
  v8  : ATR-bazlı vol filter (atr/price > 0.005 → yüksek vol trade)
  v9  : combo v2 + concurrent=4 (risk + cap)
  v10 : combo v2 + ATR filter
  v11 : v2 + sadece BTC ve ETH (sembol subset)
"""
from __future__ import annotations

import json
import os
import sys
import warnings

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


def collect_with_filters(
    *,
    symbol_subset: list[str] | None = None,
    atr_pct_min: float | None = None,  # 0.005 = ATR/price >= %0.5
    be_protect: bool = False,
    tp_r: float = 1.5,
) -> pd.DataFrame:
    """Filter ile signal collect."""
    manifest = StrategyManifest(name="rsi2_extreme_fade", version="iterate-v2")
    strategy = RSI2ExtremeFadeStrategy(manifest)
    syms = symbol_subset or SYMBOLS
    all_trades = []
    for sym in syms:
        df = _load_ohlcv(sym, "15m")
        if df.empty:
            continue
        df_feats = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_feats)
        df_feats = df_feats.reset_index(drop=True)
        for sig in signals:
            sig_idx = df_feats.index[df_feats["ts"] == sig.ts]
            if len(sig_idx) == 0:
                continue
            i0 = sig_idx[0]
            if i0 >= len(df_feats) - 1:
                continue
            entry = float(df_feats["close"].iloc[i0])
            # ATR filter (high volatility only)
            if atr_pct_min is not None:
                atr = sig.metadata.get("atr14", 0)
                if entry <= 0 or atr / entry < atr_pct_min:
                    continue
            R, exit_price, exit_offset = _exit_with_be(
                df_feats, i0, entry, sig.sl_price,
                tp_r=tp_r, direction=sig.direction,
                be_protect=be_protect, trail_pct=None,
            )
            all_trades.append({
                "entry_ts": sig.ts,
                "exit_ts": df_feats["ts"].iloc[i0 + exit_offset] if i0 + exit_offset < len(df_feats) else df_feats["ts"].iloc[-1],
                "entry_price": entry,
                "exit_price": exit_price,
                "R": float(R),
                "symbol": sym,
                "side": sig.direction,
            })
    return pd.DataFrame(all_trades)


VARIANTS_R2 = [
    {
        "name": "v2.1_risk0.001",
        "label": "risk_pct 0.001 + daily DD halt 1.5%",
        "args": {},
        "equity": {"risk_pct": 0.001, "daily_dd_halt": 0.015, "max_concurrent": 999},
    },
    {
        "name": "v7_concurrent4",
        "label": "max_concurrent=4 only (no risk change)",
        "args": {},
        "equity": {"risk_pct": 0.005, "daily_dd_halt": None, "max_concurrent": 4},
    },
    {
        "name": "v8_atr_filter",
        "label": "ATR/price >= 0.5% (yüksek vol)",
        "args": {"atr_pct_min": 0.005},
        "equity": {"risk_pct": 0.005, "daily_dd_halt": None, "max_concurrent": 999},
    },
    {
        "name": "v9_combo_v2_v7",
        "label": "risk 0.002 + concurrent=4",
        "args": {},
        "equity": {"risk_pct": 0.002, "daily_dd_halt": 0.02, "max_concurrent": 4},
    },
    {
        "name": "v10_combo_v2_v8",
        "label": "risk 0.002 + ATR filter",
        "args": {"atr_pct_min": 0.005},
        "equity": {"risk_pct": 0.002, "daily_dd_halt": 0.02, "max_concurrent": 999},
    },
    {
        "name": "v11_btc_eth_only",
        "label": "Sadece BTC + ETH (mature)",
        "args": {"symbol_subset": ["BTC/USDT", "ETH/USDT"]},
        "equity": {"risk_pct": 0.002, "daily_dd_halt": 0.02, "max_concurrent": 999},
    },
    {
        "name": "v12_ultra_combo",
        "label": "risk 0.0015 + ATR + concurrent=4 + BTC/ETH/SOL",
        "args": {"atr_pct_min": 0.004, "symbol_subset": ["BTC/USDT", "ETH/USDT", "SOL/USDT"]},
        "equity": {"risk_pct": 0.0015, "daily_dd_halt": 0.02, "max_concurrent": 4},
    },
]


def main() -> int:
    print("=== rsi2 v2 — 7 yeni varyant ===")
    print()
    print(f"{'Varyant':22} {'aylık':>8} {'neg':>7} {'DD':>8} {'yıllık':>9} {'n_tr':>6}  Sonuç")
    print("-" * 110)
    print(f"{'🟢 LIVE bot':22} {'+12.99%':>8} {'4/61':>7} {'-15.48%':>8} {'+329%':>9} {'4458':>6}  baseline")
    print(f"{'🟡 v2 (round 1)':22} {'+5.91%':>8} {'20/61':>7} {'-33.66%':>8} {'+88%':>9} {'33777':>6}  marginal")
    print("-" * 110)

    out_dir = ROOT / "memory" / "researcher" / "realistic_backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for v in VARIANTS_R2:
        trades_df = collect_with_filters(**v["args"])
        if trades_df.empty:
            print(f"{v['name']:22} NO_TRADES — filter çok katı")
            continue
        eq_series, final_eq, n_taken = _equity_sim_with_dd_halt(trades_df, **v["equity"])
        m = _compute_metrics(eq_series, 10_000.0)
        promote = (m["monthly_roi"] >= 4.0 and m["max_dd"] >= -25.0 and m["neg_count"] <= 20)
        flag = "✅ PROMOTE" if promote else (
            "🟡 marginal" if m["monthly_roi"] > 2 and m["max_dd"] > -50 else "❌"
        )
        print(f"{v['name']:22} "
              f"{m['monthly_roi']:>+7.2f}% "
              f"{m['neg_count']:>2}/{m['total_months']:<3} "
              f"{m['max_dd']:>+7.2f}% "
              f"{m['annualized']:>+8.2f}% "
              f"{n_taken:>6}  {flag}  ({v['label']})")
        results.append({
            "variant": v["name"], "label": v["label"],
            "args": v["args"], "equity": v["equity"],
            "n_taken": n_taken,
            **m, "promote": promote, "final_equity": final_eq,
        })

    out_path = out_dir / "rsi2-iterate-v2-comparison.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "variants": results,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nDetay: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
