"""peak_R-enriched _gather — v2.0.3 baseline reproduce için.

mfe_pct'tan peak_R hesaplar, MFE-aware pyramid bonus aktifleşir.
"""
from __future__ import annotations

import os
import sys
import pickle
import time
from pathlib import Path

os.environ['PA_LOG_QUIET'] = '1'

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger('price_action').setLevel(logging.ERROR)
import warnings
warnings.filterwarnings('ignore')

from price_action.backtest.engine import BacktestEngine
from price_action.signals.filters import volume_zscore
from scripts.run_real_backtest import _load_symbol_ohlcv


SYMBOLS_11 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
              "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
              "DOGE/USDT", "XRP/USDT", "MATIC/USDT"]


PRODUCTION_STRATEGIES = [
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
    ("obv_engulfing_confluence", "OBVEngulfingConfluenceStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("wyckoff_phase_d", "WyckoffPhaseDStrategy"),
    ("brooks_h2_l2", "BrooksH2L2Strategy"),
    ("pin_bar_round_numbers", "PinBarRoundNumbersStrategy"),
    ("equal_highs_sweep", "EqualHighsSweepStrategy"),
    ("cvd_spike_fade", "CVDSpikeFadeStrategy"),
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("fvg_fill_reversal", "FVGFillReversalStrategy"),
    ("microstructure_proxy", "MicrostructureProxyStrategy"),
    ("naked_poc_mr", "NakedPOCMeanReversionStrategy"),
]


def _gather_peakR(module_name: str, class_name: str) -> list:
    """v09_optimize_top10._gather'ın peak_R-enriched versiyonu."""
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name, None) or getattr(mod, class_name.replace("Strategy",""), None)
        if cls is None:
            # Heuristic: ilk *Strategy class'ı bul
            for name in dir(mod):
                if name.endswith("Strategy") and not name.startswith("_"):
                    cls = getattr(mod, name)
                    break
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn or not cls:
            return []
        s = cls(manifest_fn())
    except Exception as e:
        print(f"  {module_name}: SKIP ({e})")
        return []

    out = []
    for sym in SYMBOLS_11:
        try:
            df = _load_symbol_ohlcv(sym, tf="1d")
            if df is None or df.empty:
                continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym
            df["venue"] = "binance"
            df["timeframe"] = "1d"
            try:
                df["vol_z_pre"] = volume_zscore(df["volume"], period=20)
            except Exception:
                rolling = df["volume"].rolling(20)
                df["vol_z_pre"] = (df["volume"] - rolling.mean()) / rolling.std()
            def prov(*a, **k): return df.copy()
            e = BacktestEngine(risk_officer=None, store_load=None)
            r = e.run(
                s, [sym],
                start=df["ts"].iloc[0].to_pydatetime(),
                end=df["ts"].iloc[-1].to_pydatetime(),
                timeframe="1d",
                initial_capital=10_000.0,
                fees={"taker": 0.00075, "maker": -0.00010},
                slippage_bps=5.0,
                ohlcv_provider=prov,
            )
            ts_map = pd.to_datetime(df["ts"], utc=True)
            for _, t in r.trades.iterrows():
                # confluence -> conf [0,1]
                conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))

                # peak_R: mfe_pct'tan R'a dönüştür (MFE-aware pyramid için kritik!)
                entry_price = float(t["entry_price"])
                initial_sl = float(t["initial_sl"])
                mfe_pct = float(t.get("mfe_pct", 0))
                risk_pct = abs(initial_sl - entry_price) / entry_price if entry_price > 0 else 0.04
                # Engine MFE konvansiyonu (engine.py sat 445/526):
                #   Long:  mfe = max(mfe, (hi - entry)/entry)   → pozitif (favorable up)
                #   Short: mfe = min(mfe, (lo - entry)/entry)   → negatif (favorable down)
                # peak_R (favorable move R-multiple olarak) → side'a göre işareti çevir:
                side = str(t["side"]).lower()
                if side == "long":
                    peak_R = mfe_pct / risk_pct if risk_pct > 0 else 0
                else:  # short
                    peak_R = -mfe_pct / risk_pct if risk_pct > 0 else 0
                # Ensure peak_R >= final_R (peak en azından final kadar olmalı)
                final_R = float(t["realized_r_multiple"])
                peak_R = max(peak_R, final_R)

                ts_e = pd.Timestamp(t["entry_ts"])
                if ts_e.tzinfo is None: ts_e = ts_e.tz_localize("UTC")
                ts_x = pd.Timestamp(t["exit_ts"])
                if ts_x.tzinfo is None: ts_x = ts_x.tz_localize("UTC")
                mask = ts_map < ts_e
                vz = 0.0
                if mask.any():
                    idx = ts_map[mask].index[-1]
                    vz_val = df["vol_z_pre"].iloc[idx]
                    vz = float(vz_val) if not pd.isna(vz_val) else 0.0
                out.append({
                    "entry_ts": ts_e, "exit_ts": ts_x,
                    "entry_price": entry_price, "initial_sl": initial_sl,
                    "R": final_R,
                    "peak_R": peak_R,  # ← KRİTİK YENİ FIELD (MFE-aware pyramid için)
                    "symbol": sym, "side": str(t["side"]),
                    "conf": conf, "strategy": module_name, "vol_z": vz,
                })
        except Exception as ex:
            print(f"  {module_name}/{sym}: ERR {ex}")
            continue
    return out


def main():
    print("=" * 80)
    print("v2.0.3 BASELINE REPRODUCE — peak_R-enriched _gather")
    print("=" * 80)

    all_trades = []
    summary = []
    for module_name, class_name in PRODUCTION_STRATEGIES:
        t0 = time.time()
        trades = _gather_peakR(module_name, class_name)
        elapsed = time.time() - t0
        peak_R_dist = ""
        if trades:
            peakRs = [t["peak_R"] for t in trades]
            n_high_peak = sum(1 for p in peakRs if p >= 1.0)
            peak_R_dist = f"  peak_R>=1: {n_high_peak}/{len(trades)} ({n_high_peak*100/len(trades):.0f}%)"
        print(f"  {module_name}: {len(trades)} trades  ({elapsed:.1f}s){peak_R_dist}")
        summary.append((module_name, len(trades), elapsed))
        all_trades.extend(trades)

    out_path = ROOT / "data" / "v203_full_pool_peakR_2026-05-15.pkl"
    with open(out_path, "wb") as f:
        pickle.dump(all_trades, f)

    print()
    print(f"TOTAL: {len(all_trades)} trades")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
