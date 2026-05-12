"""4h ekleme — multi-target engine ile + 1d Top 5."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))


SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
           "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


def _gather_tf(module_name, class_name, tf):
    from price_action.backtest.engine import BacktestEngine
    from scripts.run_real_backtest import _load_symbol_ohlcv
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn: return []
        s = cls(manifest_fn())
    except Exception:
        return []
    out = []
    for sym in SYMBOLS:
        try:
            df = _load_symbol_ohlcv(sym, tf=tf)
            if df is None or df.empty: continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym; df["venue"] = "binance"; df["timeframe"] = tf
            def prov(*a, **k): return df.copy()
            e = BacktestEngine(risk_officer=None, store_load=None)
            r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(),
                     end=df["ts"].iloc[-1].to_pydatetime(), timeframe=tf,
                     initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010},
                     slippage_bps=5.0, ohlcv_provider=prov)
            for _, t in r.trades.iterrows():
                conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
                ts_e = pd.Timestamp(t["entry_ts"])
                if ts_e.tzinfo is None: ts_e = ts_e.tz_localize("UTC")
                ts_x = pd.Timestamp(t["exit_ts"])
                if ts_x.tzinfo is None: ts_x = ts_x.tz_localize("UTC")
                out.append({
                    "entry_ts": ts_e, "exit_ts": ts_x,
                    "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]), "symbol": sym, "side": str(t["side"]),
                    "conf": conf, "strategy": f"{module_name}_{tf}", "tf": tf,
                })
        except Exception:
            continue
    return out


from scripts.v08_autonomous_research import replay


def main():
    print("=" * 70)
    print("4h timeframe + multi-target engine testi")
    print("=" * 70)

    TOP5_1D = [
        ("engulfing_continuation", "EngulfingContinuationStrategy"),
        ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
        ("brooks_h2_l2", "BrooksH2L2Strategy"),
        ("wyckoff_phase_d", "WyckoffPhaseDStrategy"),
        ("obv_engulfing_confluence", "OBVEngulfingConfluenceStrategy"),
    ]

    # 1d trade'leri
    print("\n1d trade'leri topluyor...")
    trades_1d = []
    for m, c in TOP5_1D:
        trs = _gather_tf(m, c, "1d")
        trades_1d.extend(trs)
    trades_1d.sort(key=lambda x: x["entry_ts"])
    print(f"  {len(trades_1d)} sinyal")

    # 4h sadece engulfing (digerleri zaten coook sinyal verir)
    print("4h trade'leri topluyor...")
    trades_4h = _gather_tf("engulfing_continuation", "EngulfingContinuationStrategy", "4h")
    trades_4h.sort(key=lambda x: x["entry_ts"])
    print(f"  {len(trades_4h)} sinyal (sadece engulfing 4h)")

    # 4h engulfing solo
    print("\n# 4h engulfing solo (multi-target):")
    r = replay(trades_4h, risk_pct=0.015)
    if r:
        ann = ((r["final"]/10000)**(1/5)-1)*100
        print(f"  4h solo : final ${r['final']:,.0f} yIllIk {ann:+.2f}% DD {r['max_dd']*100:+.0f}% WR {r['wr']*100:.0f}%")

    # 1d + 4h birlesik
    combined = trades_1d + trades_4h
    combined.sort(key=lambda x: x["entry_ts"])

    print("\n# 1d + 4h birlesik (ayni cooldown):")
    for risk in [0.005, 0.010, 0.015]:
        r = replay(combined, risk_pct=risk)
        if r is None: continue
        ann = ((r["final"]/10000)**(1/5)-1)*100
        print(f"  risk %{risk*100:.1f}: final ${r['final']:,.0f} yIllIk {ann:+.2f}% DD {r['max_dd']*100:+.0f}% WR {r['wr']*100:.0f}% n={r['trades']}")


if __name__ == "__main__":
    main()
