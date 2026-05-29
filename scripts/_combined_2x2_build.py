"""Build the 4 expansion-symbol trades through the REAL engine for BOTH exit
variants (trail 1.5 baseline + trail 3.0 winner-let-run), so the 2x2 matrix
(10sym/14sym x trail1.5/trail3.0) can be assembled.

10-symbol variants are already cached in /tmp/wlr_vsa_variants.pkl (built by
scripts/crypto_winner_let_run_vsa_exit.py — SAME engine, SAME exit_cfg, SAME
fees/slippage/sl_pct). We re-use the IDENTICAL gather()/BASELINE from that
harness, only swapping the DB to market_expansion_15m.duckdb for the 4 new syms.

SUI EXCLUDED (dilutive). Each symbol from its own listing -> no lookahead.
Read-only DB, no daemon touch.
"""
from __future__ import annotations
import os, sys, pickle
from pathlib import Path

os.environ["PA_DUCKDB_READ_ONLY"] = "true"
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

# import the EXACT gather + configs from the winner-let-run harness
import importlib.util
spec = importlib.util.spec_from_file_location(
    "wlr", str(ROOT / "scripts" / "crypto_winner_let_run_vsa_exit.py"))
wlr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wlr)

import duckdb, pandas as pd
from price_action.signals.filters import volume_zscore
from price_action.strategies.vsa_climax_test import VSAClimaxTestStrategy, _default_manifest
from price_action.backtest.engine import BacktestEngine

EXP_DB = ROOT / "data" / "market_expansion_15m.duckdb"
NEW_SYMS = ["ZEC/USDT", "NEAR/USDT", "FIL/USDT", "XLM/USDT"]  # SUI excluded

TRAIL15 = dict(wlr.BASELINE)                          # trail 1.5 (current exit)
TRAIL30 = {**wlr.BASELINE, "runner_trail_mult": 3.0}  # winner-let-run


def load_exp(sym, tf="15m", venue="binance"):
    con = duckdb.connect(str(EXP_DB), read_only=True)
    df = con.execute(
        "SELECT ts,open,high,low,close,volume FROM ohlcv "
        "WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts",
        [venue, sym, tf]).fetchdf()
    con.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    df["symbol"], df["venue"], df["timeframe"] = sym, venue, tf
    return df


def gather_exp(sym, exit_cfg, tf="15m"):
    """Identical body to wlr.gather() but reads the expansion DB."""
    s = VSAClimaxTestStrategy(_default_manifest())
    df = load_exp(sym, tf)
    if df is None or df.empty:
        return []
    try:
        df["vol_z_pre"] = volume_zscore(df["volume"], period=20)
    except Exception:
        roll = df["volume"].rolling(20)
        df["vol_z_pre"] = (df["volume"] - roll.mean()) / roll.std()

    def prov(*a, **k):
        return df.copy()

    e = BacktestEngine(risk_officer=None, store_load=None, **exit_cfg)
    r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(),
              end=df["ts"].iloc[-1].to_pydatetime(), timeframe=tf,
              initial_capital=10_000.0, fees=wlr.FEES, slippage_bps=wlr.SLIPPAGE_BPS,
              ohlcv_provider=prov)
    out = []
    if r.trades is None or r.trades.empty:
        return out
    for _, t in r.trades.iterrows():
        try:
            conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
            ep, sp = float(t["entry_price"]), float(t["initial_sl"])
            mfe_pct = float(t.get("mfe_pct", 0))
            rp = abs(sp - ep) / ep if ep > 0 else 0.04
            side = str(t["side"]).lower()
            pk = (mfe_pct / rp if side == "long" else -mfe_pct / rp) if rp > 0 else 0
            final_R = float(t["realized_r_multiple"])
            pk = max(pk, final_R)
            te = pd.Timestamp(t["entry_ts"]); te = te.tz_localize("UTC") if te.tzinfo is None else te
            tx = pd.Timestamp(t["exit_ts"]); tx = tx.tz_localize("UTC") if tx.tzinfo is None else tx
            out.append({"entry_ts": te, "exit_ts": tx, "entry_price": ep, "initial_sl": sp,
                        "R": final_R, "peak_R": pk, "symbol": sym, "side": str(t["side"]),
                        "conf": conf, "strategy": "vsa_climax_test", "vol_z": 0.0,
                        "hold_h": (tx - te) / pd.Timedelta(hours=1)})
        except Exception:
            continue
    return out


def main():
    # determinism gate on one new symbol
    import numpy as np
    g1 = gather_exp("ZEC/USDT", TRAIL15)
    g2 = gather_exp("ZEC/USDT", TRAIL15)
    r1 = np.array([t["R"] for t in g1]); r2 = np.array([t["R"] for t in g2])
    det = (len(r1) == len(r2)) and np.allclose(r1, r2, atol=1e-9)
    print(f"GATE determinism ZEC trail1.5: {'PASS' if det else 'FAIL'} (n={len(g1)})")
    assert det

    out = {"trail1.5": {}, "trail3.0": {}}
    out["trail1.5"]["ZEC/USDT"] = g1
    for sym in NEW_SYMS:
        for tag, cfg in (("trail1.5", TRAIL15), ("trail3.0", TRAIL30)):
            if sym in out[tag]:
                continue
            tr = gather_exp(sym, cfg)
            out[tag][sym] = tr
            rng = (f"{min(t['entry_ts'] for t in tr).date()} -> {max(t['entry_ts'] for t in tr).date()}"
                   if tr else "EMPTY")
            print(f"  {sym:10s} {tag:9s} n={len(tr):>6} {rng}")
    pickle.dump(out, open("/tmp/expansion_4sym_2variants.pkl", "wb"))
    print("[OUT] /tmp/expansion_4sym_2variants.pkl")


if __name__ == "__main__":
    main()
