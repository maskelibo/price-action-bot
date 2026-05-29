"""Build vsa_climax_test (vsa2 amplify) pool for the 5 expansion symbols.

Reproduces sec53_15m_pool_v11_vsa2_top4.pkl pipeline exactly:
  - df["timeframe"]="15m" -> apply_tf_manifest auto-loads 15m manifest
    (vol_sma_mult 2.0 = vsa2 amplify), so no manual mult override.
  - same BacktestEngine fees/slippage as scripts/sec31_phoenix_scalp_15m_rolling.py
  - each symbol from its OWN listing date (full available span) -> no
    survivorship/listing bias.

Reads expansion DB read-only. Does NOT touch live daemons.

Usage:
  .venv/bin/python scripts/_expansion_vsa_pool_build.py            # 5 new syms
  PA_VERIFY_BTC=1 .venv/bin/python scripts/_expansion_vsa_pool_build.py  # reproduce BTC from main DB to validate pipeline
"""
from __future__ import annotations

import os
import pickle
import sys
import time
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

import duckdb
import pandas as pd

from price_action.backtest.engine import BacktestEngine
from price_action.signals.filters import volume_zscore
from price_action.strategies.vsa_climax_test import (
    VSAClimaxTestStrategy,
    _default_manifest,
)

EXPANSION_DB = ROOT / "data" / "market_expansion_15m.duckdb"
MAIN_DB = ROOT / "data" / "market.duckdb"
SYMS_10 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
           "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"]
NEW_SYMS = ["ZEC/USDT", "SUI/USDT", "NEAR/USDT", "FIL/USDT", "XLM/USDT"]
OUT = ROOT / "data" / "_expansion_vsa_pool.pkl"
OUT_15 = ROOT / "data" / "_vsa_pool_15sym_fresh.pkl"


def load_ohlcv(db_path: Path, symbol: str, tf: str = "15m", venue: str = "binance") -> pd.DataFrame:
    con = duckdb.connect(str(db_path), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM ohlcv "
        "WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts",
        [venue, symbol, tf],
    ).fetchdf()
    con.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["symbol"] = symbol
    df["timeframe"] = tf
    df["venue"] = venue
    return df


def gather_vsa(db_path: Path, sym: str, tf: str = "15m") -> list[dict]:
    """Replicate sec31_phoenix_scalp_15m_rolling._gather_peakR_single for vsa only."""
    s = VSAClimaxTestStrategy(_default_manifest())
    df = load_ohlcv(db_path, sym, tf=tf)
    if df is None or df.empty:
        return []
    df = df.sort_values("ts").reset_index(drop=True)
    df["symbol"] = sym
    df["venue"] = "binance"
    df["timeframe"] = tf
    try:
        df["vol_z_pre"] = volume_zscore(df["volume"], period=20)
    except Exception:
        rolling = df["volume"].rolling(20)
        df["vol_z_pre"] = (df["volume"] - rolling.mean()) / rolling.std()

    def prov(*a, **k):
        return df.copy()

    e = BacktestEngine(risk_officer=None, store_load=None)
    r = e.run(
        s, [sym],
        start=df["ts"].iloc[0].to_pydatetime(),
        end=df["ts"].iloc[-1].to_pydatetime(),
        timeframe=tf,
        initial_capital=10_000.0,
        fees={"taker": 0.00075, "maker": -0.00010},
        slippage_bps=5.0,
        ohlcv_provider=prov,
    )

    out = []
    ts_map = pd.to_datetime(df["ts"], utc=True)
    for _, t in r.trades.iterrows():
        try:
            conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
            entry_price = float(t["entry_price"])
            initial_sl = float(t["initial_sl"])
            mfe_pct = float(t.get("mfe_pct", 0))
            risk_pct = abs(initial_sl - entry_price) / entry_price if entry_price > 0 else 0.04
            side = str(t["side"]).lower()
            if side == "long":
                peak_R = mfe_pct / risk_pct if risk_pct > 0 else 0
            else:
                peak_R = -mfe_pct / risk_pct if risk_pct > 0 else 0
            final_R = float(t["realized_r_multiple"])
            peak_R = max(peak_R, final_R)

            ts_e = pd.Timestamp(t["entry_ts"])
            if ts_e.tzinfo is None:
                ts_e = ts_e.tz_localize("UTC")
            ts_x = pd.Timestamp(t["exit_ts"])
            if ts_x.tzinfo is None:
                ts_x = ts_x.tz_localize("UTC")

            mask = ts_map < ts_e
            vz = 0.0
            if mask.any():
                idx = ts_map[mask].index[-1]
                vz_val = df["vol_z_pre"].iloc[idx]
                vz = float(vz_val) if not pd.isna(vz_val) else 0.0

            out.append({
                "entry_ts": ts_e,
                "exit_ts": ts_x,
                "entry_price": entry_price,
                "initial_sl": initial_sl,
                "R": final_R,
                "peak_R": peak_R,
                "symbol": sym,
                "side": str(t["side"]),
                "conf": conf,
                "strategy": "vsa_climax_test",
                "vol_z": vz,
            })
        except Exception:
            continue
    return out


def main():
    if os.environ.get("PA_VERIFY_BTC"):
        t0 = time.time()
        btc = gather_vsa(MAIN_DB, "BTC/USDT")
        print(f"[VERIFY] BTC fresh build from market.duckdb: {len(btc)} trades "
              f"(cached vsa2_top4 BTC = 7952) in {time.time()-t0:.0f}s")
        return

    # Build ALL 15 fresh (10 from main DB + 5 from expansion DB) so the
    # 10-vs-15 comparison is bit-identical code path / same end date.
    pool_10 = []
    print("=== 10 main symbols (market.duckdb) ===")
    for sym in SYMS_10:
        t0 = time.time()
        tr = gather_vsa(MAIN_DB, sym)
        pool_10.extend(tr)
        rng = (f"{min(t['entry_ts'] for t in tr).date()} -> {max(t['entry_ts'] for t in tr).date()}"
               if tr else "EMPTY")
        print(f"  {sym:10s} {len(tr):>6d}  {rng}  ({time.time()-t0:.0f}s)")

    pool_new = []
    print("=== 5 expansion symbols (market_expansion_15m.duckdb) ===")
    for sym in NEW_SYMS:
        t0 = time.time()
        tr = gather_vsa(EXPANSION_DB, sym)
        pool_new.extend(tr)
        rng = (f"{min(t['entry_ts'] for t in tr).date()} -> {max(t['entry_ts'] for t in tr).date()}"
               if tr else "EMPTY")
        print(f"  {sym:10s} {len(tr):>6d}  {rng}  ({time.time()-t0:.0f}s)")

    with OUT.open("wb") as fh:
        pickle.dump(pool_new, fh)
    with OUT_15.open("wb") as fh:
        pickle.dump(pool_10 + pool_new, fh)
    print(f"[OUT] {OUT} — {len(pool_new)} new-symbol vsa trades")
    print(f"[OUT] {OUT_15} — {len(pool_10)+len(pool_new)} total (10+5) vsa trades")


if __name__ == "__main__":
    main()
