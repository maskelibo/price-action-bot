"""Sec13.2 yardimcilari: 4h cache'den trade gather + naked_poc gather.

Mevcut `scripts.v09_optimize_top10._gather` 1d odakli ve DuckDB'den okur.
4h trade gather icin data/mtf_4h_cache.pkl'den OHLCV oku.
"""
from __future__ import annotations

import os
import pickle
import sys
from pathlib import Path

os.environ.setdefault("PA_LOG_QUIET", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
import numpy as np

SYMBOLS_11 = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    "DOGE/USDT", "XRP/USDT", "MATIC/USDT",
]


def _load_4h_cache() -> dict:
    """data/mtf_4h_cache.pkl -> dict[symbol -> DataFrame]."""
    p = ROOT / "data" / "mtf_4h_cache.pkl"
    with open(p, "rb") as f:
        return pickle.load(f)


def gather_4h(module_name: str, class_name: str) -> list[dict]:
    """4h cache'den belirli stratejiyi calistir, trade list ret."""
    from price_action.backtest.engine import BacktestEngine
    try:
        mod = __import__(
            f"price_action.strategies.{module_name}",
            fromlist=[class_name, "_default_manifest"],
        )
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn:
            return []
        s = cls(manifest_fn())
    except Exception as e:
        print(f"[gather_4h] import fail {module_name}: {e}")
        return []

    cache = _load_4h_cache()
    out: list[dict] = []
    for sym in SYMBOLS_11:
        if sym not in cache:
            continue
        try:
            df = cache[sym].copy()
            if df is None or df.empty:
                continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym
            df["venue"] = "binance"
            df["timeframe"] = "4h"

            def prov(*a, **k):
                return df.copy()

            e = BacktestEngine(risk_officer=None, store_load=None)
            r = e.run(
                s, [sym],
                start=df["ts"].iloc[0].to_pydatetime(),
                end=df["ts"].iloc[-1].to_pydatetime(),
                timeframe="4h",
                initial_capital=10_000.0,
                fees={"taker": 0.00075, "maker": -0.00010},
                slippage_bps=5.0,
                ohlcv_provider=prov,
            )
            for _, t in r.trades.iterrows():
                conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
                ts_e = pd.Timestamp(t["entry_ts"])
                if ts_e.tzinfo is None:
                    ts_e = ts_e.tz_localize("UTC")
                ts_x = pd.Timestamp(t["exit_ts"])
                if ts_x.tzinfo is None:
                    ts_x = ts_x.tz_localize("UTC")
                out.append({
                    "entry_ts": ts_e,
                    "exit_ts": ts_x,
                    "entry_price": float(t["entry_price"]),
                    "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]),
                    "symbol": sym,
                    "side": str(t["side"]),
                    "conf": conf,
                    "strategy": module_name,
                    "vol_z": 0.0,
                })
        except Exception as ex:
            print(f"[gather_4h] {sym} fail: {ex}")
            continue
    return out


def summary(trades: list[dict], name: str) -> dict:
    if not trades:
        return {"name": name, "n": 0, "mR": 0.0, "sumR": 0.0, "WR": 0.0,
                "n_long": 0, "n_short": 0}
    Rs = np.array([t["R"] for t in trades], dtype=float)
    return {
        "name": name,
        "n": len(trades),
        "mR": float(Rs.mean()),
        "sumR": float(Rs.sum()),
        "WR": float((Rs > 0).mean()),
        "n_long": sum(1 for t in trades if t["side"] == "long"),
        "n_short": sum(1 for t in trades if t["side"] == "short"),
    }
