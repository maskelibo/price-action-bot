"""SEC28-yardımcı: Phoenix 4h şu an taraması — son 7 bar (28h) içinde sinyal var mı?

10 Phoenix sym × 10 strateji × 4h, son birkaç bar'da entry üreten setup'ları listele.
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

from price_action.backtest.engine import BacktestEngine
from scripts.run_real_backtest import _load_symbol_ohlcv
from scripts.sec27_phoenix_4h_pivot import SYMBOLS_10, PHOENIX_STRATEGIES

LOOKBACK_BARS = 7  # son 7 bar (28h)
TF = "4h"


def scan_one(module_name: str, class_name: str) -> list[dict]:
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name, None)
        if cls is None:
            return []
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn:
            return []
        s = cls(manifest_fn())
    except Exception as e:
        print(f"  [SKIP] {module_name}: {e}")
        return []

    hits = []
    for sym in SYMBOLS_10:
        try:
            df = _load_symbol_ohlcv(sym, tf=TF)
            if df is None or df.empty:
                continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym
            df["venue"] = "binance"
            df["timeframe"] = TF

            def prov(*a, **k):
                return df.copy()

            e = BacktestEngine(risk_officer=None, store_load=None)
            r = e.run(
                s, [sym],
                start=df["ts"].iloc[0].to_pydatetime(),
                end=df["ts"].iloc[-1].to_pydatetime(),
                timeframe=TF,
                initial_capital=10_000.0,
                fees={"taker": 0.00075, "maker": -0.00010},
                slippage_bps=5.0,
                ohlcv_provider=prov,
            )
            if r.trades.empty:
                continue
            # Son LOOKBACK_BARS bar içinde entry yapan trade'leri filtrele
            last_bar_ts = pd.Timestamp(df["ts"].iloc[-1])
            if last_bar_ts.tzinfo is None:
                last_bar_ts = last_bar_ts.tz_localize("UTC")
            cutoff = last_bar_ts - pd.Timedelta(hours=4 * LOOKBACK_BARS)
            for _, t in r.trades.iterrows():
                ts_e = pd.Timestamp(t["entry_ts"])
                if ts_e.tzinfo is None:
                    ts_e = ts_e.tz_localize("UTC")
                if ts_e >= cutoff:
                    hits.append({
                        "strategy": module_name,
                        "symbol": sym,
                        "side": str(t["side"]),
                        "entry_ts": ts_e,
                        "entry_price": float(t["entry_price"]),
                        "initial_sl": float(t["initial_sl"]),
                        "confluence": float(t["confluence_score"]),
                    })
        except Exception as ex:
            print(f"  [ERR] {module_name}/{sym}: {ex}")
            continue
    return hits


def main():
    print(f"SEC28-NOW: Phoenix 4h scan — son {LOOKBACK_BARS} bar ({LOOKBACK_BARS*4}h)")
    print(f"Sym pool: {len(SYMBOLS_10)} sym × Strateji: {len(PHOENIX_STRATEGIES)} = {len(SYMBOLS_10)*len(PHOENIX_STRATEGIES)} cell")
    print("=" * 80)

    all_hits = []
    for m, c in PHOENIX_STRATEGIES:
        hits = scan_one(m, c)
        if hits:
            print(f"\n[HIT] {m}: {len(hits)} sinyal")
            for h in hits:
                ts_str = h["entry_ts"].strftime("%Y-%m-%d %H:%M UTC")
                print(f"   {h['symbol']:12s} {h['side']:5s} entry={h['entry_price']:>10.4f} SL={h['initial_sl']:>10.4f} conf={h['confluence']:.2f} ts={ts_str}")
            all_hits.extend(hits)
        else:
            print(f"  {m}: -")

    print()
    print("=" * 80)
    if all_hits:
        print(f"TOPLAM {len(all_hits)} sinyal (son {LOOKBACK_BARS*4}h)")
        # Group by symbol
        from collections import Counter
        by_sym = Counter(h["symbol"] for h in all_hits)
        print(f"Sembol dağılımı: {dict(by_sym)}")
    else:
        print(f"Son {LOOKBACK_BARS*4}h içinde sinyal YOK")


if __name__ == "__main__":
    main()
