"""Synthetic OHLCV / trade üretici — test ve demolar için.

CI'da network gerektirmeden testleri yürütmek için kullanılır.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


def generate_ohlcv(
    n: int = 1000,
    *,
    start: datetime | None = None,
    seed: int = 42,
    drift: float = 0.0005,
    vol: float = 0.02,
    initial_price: float = 30_000.0,
) -> pd.DataFrame:
    """Basit GBM tabanlı sentetik 1d OHLCV."""
    rng = np.random.default_rng(seed)
    start = start or datetime(2022, 1, 1)
    rets = rng.normal(drift, vol, size=n)
    close = initial_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[initial_price], close[:-1]])
    intra_vol = np.abs(rng.normal(0, 0.005, size=n))
    high = np.maximum(open_, close) * (1 + intra_vol)
    low = np.minimum(open_, close) * (1 - intra_vol)
    volume = rng.lognormal(mean=10, sigma=0.5, size=n) * 1000
    idx = pd.date_range(start=start, periods=n, freq="1D")
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )


def generate_trades(n: int = 100, *, seed: int = 42) -> pd.DataFrame:
    """Sentetik trade tablosu — analytics testleri için."""
    rng = np.random.default_rng(seed)
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT"]
    patterns = ["bullish_pin_bar", "bearish_pin_bar", "bullish_engulfing", "inside_bar_breakout"]
    rows = []
    base = datetime(2024, 1, 1)
    eq = 10_000.0
    for i in range(n):
        side = rng.choice(["long", "short"])
        sym = rng.choice(symbols)
        r = rng.normal(0.3, 1.2)  # expectancy ~ 0.3R, std 1.2R
        pnl = r * 100.0  # 1R = 100 USDT
        eq += pnl
        entry_ts = base + timedelta(days=int(i))
        exit_ts = entry_ts + timedelta(days=int(rng.integers(1, 7)))
        rows.append(
            {
                "trade_id": f"T{i:05d}",
                "venue": "binance",
                "symbol": sym,
                "side": side,
                "entry_ts": entry_ts,
                "exit_ts": exit_ts,
                "entry_price": float(rng.uniform(10, 50_000)),
                "exit_price": float(rng.uniform(10, 50_000)),
                "quantity": float(rng.uniform(0.001, 1.0)),
                "realized_pnl_usdt": float(pnl),
                "realized_r_multiple": float(r),
                "fees_usdt": 0.5,
                "slippage_bps": float(abs(rng.normal(5, 3))),
                "strategy_id": "classic_pa",
                "pattern_id": str(rng.choice(patterns)),
                "confluence_score": float(rng.uniform(1.0, 3.0)),
                "initial_sl": 0.0,
                "initial_tp": 0.0,
                "mae_pct": float(abs(rng.normal(0.01, 0.005))),
                "mfe_pct": float(abs(rng.normal(0.015, 0.008))),
                "classification": None,
                "notes": None,
                "manifest_hash": "synthetic",
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic OHLCV / trades")
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--out", default="data/synthetic_btc_1d.parquet")
    parser.add_argument("--trades-out", default=None)
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df = generate_ohlcv(args.n)
    df.to_parquet(out)
    print(f"OHLCV → {out}  rows={len(df)}")

    if args.trades_out:
        tr = generate_trades(min(args.n, 250))
        Path(args.trades_out).parent.mkdir(parents=True, exist_ok=True)
        tr.to_parquet(args.trades_out)
        print(f"trades → {args.trades_out}  rows={len(tr)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
