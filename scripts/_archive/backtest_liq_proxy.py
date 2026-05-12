"""Quick synthetic backtest — liquidation cascade fade (proxy version).

Uses available free data:
  - Bybit OI daily history (~200 bars, back to 2025-10-22)
  - Binance taker L/S ratio (30 bars daily — too few; use hourly for more)
  - OHLCV from CCXT (Binance, 1d, BTC/ETH)

Runs simplified backtest (not walk-forward — not enough data for WF).
Reports: N signals, win rate, profit factor, avg R.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pandas as pd
import requests
from datetime import datetime, timezone

from price_action.strategies.liquidation_fade import (
    LiquidationFadeStrategy,
    liquidation_extreme_signal,
)


# ---------------------------------------------------------------------------
# Fetch helpers (direct REST, no ingest store)
# ---------------------------------------------------------------------------

def fetch_bybit_oi(symbol: str = "BTCUSDT", limit: int = 200) -> pd.DataFrame:
    url = "https://api.bybit.com/v5/market/open-interest"
    try:
        r = requests.get(url, params={
            "category": "linear", "symbol": symbol,
            "intervalTime": "1d", "limit": str(limit)
        }, timeout=15)
        data = r.json()
        if data.get("retCode") != 0:
            return pd.DataFrame()
        rows = [
            {"ts": pd.Timestamp(int(x["timestamp"]), unit="ms", tz="UTC"),
             "open_interest": float(x["openInterest"])}
            for x in data["result"]["list"]
        ]
        df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
        df["oi_pct_change"] = df["open_interest"].pct_change()
        return df
    except Exception as e:
        print(f"OI fetch error: {e}")
        return pd.DataFrame()


def fetch_binance_taker(symbol: str = "BTCUSDT", period: str = "1d") -> pd.DataFrame:
    url = "https://fapi.binance.com/futures/data/takerlongshortRatio"
    try:
        r = requests.get(url, params={"symbol": symbol, "period": period, "limit": "30"}, timeout=15)
        data = r.json()
        rows = []
        for item in data:
            bv = float(item.get("buyVol", 0))
            sv = float(item.get("sellVol", 0))
            tot = bv + sv
            rows.append({
                "ts": pd.Timestamp(int(item["timestamp"]), unit="ms", tz="UTC"),
                "taker_sell_ratio": sv / tot if tot > 0 else 0.5,
            })
        return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    except Exception as e:
        print(f"Taker fetch error: {e}")
        return pd.DataFrame()


def fetch_binance_ohlcv(symbol: str = "BTCUSDT", limit: int = 200) -> pd.DataFrame:
    url = "https://fapi.binance.com/fapi/v1/klines"
    try:
        r = requests.get(url, params={
            "symbol": symbol, "interval": "1d", "limit": str(limit)
        }, timeout=15)
        data = r.json()
        rows = [{
            "ts": pd.Timestamp(int(x[0]), unit="ms", tz="UTC"),
            "open": float(x[1]), "high": float(x[2]),
            "low": float(x[3]), "close": float(x[4]),
            "volume": float(x[5]),
            "venue": "binance", "symbol": symbol, "timeframe": "1d",
        } for x in data]
        return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    except Exception as e:
        print(f"OHLCV fetch error: {e}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Simple backtest engine
# ---------------------------------------------------------------------------

def simple_backtest(signals: list, ohlcv: pd.DataFrame, primary_r: float = 2.0) -> dict:
    """Match signals to next-bar outcomes using high/low to determine SL/TP hit."""
    if not signals:
        return {"n_trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "avg_r": 0.0}

    results = []
    for sig in signals:
        sig_ts = pd.Timestamp(sig.ts)
        # Find index of signal bar in OHLCV
        mask = ohlcv["ts"] == sig_ts
        if not mask.any():
            continue
        idx = ohlcv[mask].index[0]
        if idx + 1 >= len(ohlcv):
            continue

        # Entry: next bar close (simplified — avoids lookahead)
        entry_bar = ohlcv.iloc[idx + 1]
        entry = float(entry_bar["close"])
        sl = sig.sl_price
        tp = sig.tp_price

        if sig.direction == "long":
            risk = entry - sl
            if risk <= 0:
                continue
            # Simulate over next 5 bars
            outcome = "timeout"
            for j in range(idx + 2, min(idx + 7, len(ohlcv))):
                bar = ohlcv.iloc[j]
                if bar["low"] <= sl:
                    outcome = "loss"
                    break
                if bar["high"] >= tp:
                    outcome = "win"
                    break
        else:
            risk = sl - entry
            if risk <= 0:
                continue
            outcome = "timeout"
            for j in range(idx + 2, min(idx + 7, len(ohlcv))):
                bar = ohlcv.iloc[j]
                if bar["high"] >= sl:
                    outcome = "loss"
                    break
                if bar["low"] <= tp:
                    outcome = "win"
                    break

        if outcome == "win":
            results.append(primary_r)
        elif outcome == "loss":
            results.append(-1.0)
        # timeout → skip (partial result)

    if not results:
        return {"n_trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "avg_r": 0.0}

    wins = [r for r in results if r > 0]
    losses = [r for r in results if r < 0]
    win_rate = len(wins) / len(results)
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else float("inf")
    avg_r = sum(results) / len(results)

    return {
        "n_trades": len(results),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_r": avg_r,
        "total_r": sum(results),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("LIQUIDATION CASCADE FADE - SYNTHETIC PROXY BACKTEST")
    print("Data: Bybit OI + Binance taker ratio (free, ~30-200d)")
    print("=" * 60)

    symbols = [("BTCUSDT", "BTC"), ("ETHUSDT", "ETH")]

    all_signals = []
    for binance_sym, label in symbols:
        print(f"\n--- {label} ---")

        oi_df = fetch_bybit_oi(binance_sym, limit=200)
        taker_df = fetch_binance_taker(binance_sym, period="1d")
        ohlcv_df = fetch_binance_ohlcv(binance_sym, limit=500)

        print(f"OI bars: {len(oi_df)} (oldest: {oi_df['ts'].min().date() if not oi_df.empty else 'N/A'})")
        print(f"Taker bars: {len(taker_df)} (oldest: {taker_df['ts'].min().date() if not taker_df.empty else 'N/A'})")
        print(f"OHLCV bars: {len(ohlcv_df)}")

        if taker_df.empty or oi_df.empty or ohlcv_df.empty:
            print("Insufficient data — skip")
            continue

        # Merge proxy onto OHLCV
        merged = pd.merge_asof(
            taker_df.sort_values("ts"),
            oi_df[["ts", "open_interest", "oi_pct_change"]].sort_values("ts"),
            on="ts", direction="nearest", tolerance=pd.Timedelta("2D")
        )
        # Merge OHLCV
        df = pd.merge_asof(
            ohlcv_df.sort_values("ts"),
            merged.sort_values("ts"),
            on="ts", direction="nearest", tolerance=pd.Timedelta("2D")
        )
        # Fill NaN proxy with 0 (no cascade info)
        df["oi_pct_change"] = df["oi_pct_change"].fillna(0.0)
        df["taker_sell_ratio"] = df["taker_sell_ratio"].fillna(0.5)

        # Cascade signal check
        long_cas, short_cas = liquidation_extreme_signal(df, rolling_window=20)
        n_long = long_cas.sum()
        n_short = short_cas.sum()
        print(f"Cascade signals — long: {n_long}, short: {n_short}")

        strat = LiquidationFadeStrategy()
        df_feat = strat.prepare_features(df)
        signals = strat.generate_signals(df_feat)
        print(f"Trading signals: {len(signals)}")
        all_signals.extend(signals)

        if signals:
            result = simple_backtest(signals, ohlcv_df)
            print(f"Backtest result:")
            for k, v in result.items():
                if isinstance(v, float):
                    print(f"  {k}: {v:.3f}")
                else:
                    print(f"  {k}: {v}")

    if not all_signals:
        print("\n" + "=" * 60)
        print("VERDICT: INSUFFICIENT SIGNALS FOR BACKTEST")
        print("Free taker data: only 30 days daily → too few bars for reliable stats")
        print("DEFER: CoinGlass $29/mo needed for 3yr liquidation history")
        print("=" * 60)
        return

    print("\n" + "=" * 60)
    print("COMBINED RESULT (BTC + ETH)")
    print("=" * 60)
    # Need OHLCV for all symbols combined — just report signal count
    print(f"Total signals across symbols: {len(all_signals)}")
    print("\nNOTE: 30-day daily data is statistically insufficient (need >= 200 bars).")
    print("VERDICT: DEFER — proxy signal fires too rarely in 30-day window.")
    print("Real liquidation data (CoinGlass) needed for proper validation.")


if __name__ == "__main__":
    main()
