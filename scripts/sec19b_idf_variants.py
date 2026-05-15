"""Sec19b: IDF varyant testleri.

IDF standalone mR=+0.088 (HARD gate FAIL, 0.10 esiginde marjinal kil payi).
Shuffle p=0.080 (null'dan zar zor anlamli, 0.05 esik altinda).
WF +IDF marjinal POSITIVE (+0.3pp / +0.008 r-adj).

Bu sprintte:
  V1: base (no trend filter) — yapildi
  V2: trend filter ON (LONG > EMA50, SHORT < EMA50)
  V3: body ratio 0.50 (daha sec ici rejection)

En iyi varyantin shuffle, symbol-out, ensemble katkisini olc.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from price_action.strategies.inside_day_failure import InsideDayFailureStrategy, _default_manifest
from price_action.strategies.base import StrategyManifest


def _v2_manifest():
    raw = {
        "name": "inside_day_failure",
        "version": "1.0.0-v2",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {"id": "idf_long", "enabled": True, "weight": 2.0,
                 "params": {"id_range_atr_max": 1.5, "sl_atr_mult": 0.25, "body_ratio_min": 0.30,
                            "tp_r_multiple": 2.0, "cooldown_bars": 5, "require_trend": True}},
                {"id": "idf_short", "enabled": True, "weight": 2.0,
                 "params": {"id_range_atr_max": 1.5, "sl_atr_mult": 0.25, "body_ratio_min": 0.30,
                            "tp_r_multiple": 2.0, "cooldown_bars": 5, "require_trend": True}},
            ],
            "filters": {"atr_min_pct": 0.005, "volume_zscore_min": 0.0},
            "confluence": {"method": "weighted_sum", "min_score": 1.5, "bonus_if_at_sr": 0.0},
        },
        "risk": {"take_profit": {"primary_R": 2.0}},
    }
    return StrategyManifest.model_validate(raw)


def _v3_manifest():
    raw = {
        "name": "inside_day_failure",
        "version": "1.0.0-v3",
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {"id": "idf_long", "enabled": True, "weight": 2.0,
                 "params": {"id_range_atr_max": 1.5, "sl_atr_mult": 0.25, "body_ratio_min": 0.50,
                            "tp_r_multiple": 2.0, "cooldown_bars": 5, "require_trend": False}},
                {"id": "idf_short", "enabled": True, "weight": 2.0,
                 "params": {"id_range_atr_max": 1.5, "sl_atr_mult": 0.25, "body_ratio_min": 0.50,
                            "tp_r_multiple": 2.0, "cooldown_bars": 5, "require_trend": False}},
            ],
            "filters": {"atr_min_pct": 0.005, "volume_zscore_min": 0.0},
            "confluence": {"method": "weighted_sum", "min_score": 1.5, "bonus_if_at_sr": 0.0},
        },
        "risk": {"take_profit": {"primary_R": 2.0}},
    }
    return StrategyManifest.model_validate(raw)


def _v4_manifest():
    """V4: trend + tight body."""
    raw = {
        "name": "inside_day_failure",
        "version": "1.0.0-v4",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {"id": "idf_long", "enabled": True, "weight": 2.0,
                 "params": {"id_range_atr_max": 1.5, "sl_atr_mult": 0.25, "body_ratio_min": 0.50,
                            "tp_r_multiple": 2.0, "cooldown_bars": 5, "require_trend": True}},
                {"id": "idf_short", "enabled": True, "weight": 2.0,
                 "params": {"id_range_atr_max": 1.5, "sl_atr_mult": 0.25, "body_ratio_min": 0.50,
                            "tp_r_multiple": 2.0, "cooldown_bars": 5, "require_trend": True}},
            ],
            "filters": {"atr_min_pct": 0.005, "volume_zscore_min": 0.0},
            "confluence": {"method": "weighted_sum", "min_score": 1.5, "bonus_if_at_sr": 0.0},
        },
        "risk": {"take_profit": {"primary_R": 2.0}},
    }
    return StrategyManifest.model_validate(raw)


def _gather_custom(manifest_fn, name="inside_day_failure", cls=InsideDayFailureStrategy):
    """Gather trades with a custom manifest variant."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.signals.filters import volume_zscore
    from scripts.run_real_backtest import _load_symbol_ohlcv
    from scripts.v09_optimize_top10 import SYMBOLS_11

    s = cls(manifest_fn())
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
            r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(),
                     end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d",
                     initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010},
                     slippage_bps=5.0, ohlcv_provider=prov)
            for _, t in r.trades.iterrows():
                ts_e = pd.Timestamp(t["entry_ts"])
                if ts_e.tzinfo is None: ts_e = ts_e.tz_localize("UTC")
                ts_x = pd.Timestamp(t["exit_ts"])
                if ts_x.tzinfo is None: ts_x = ts_x.tz_localize("UTC")
                out.append({
                    "entry_ts": ts_e, "exit_ts": ts_x,
                    "entry_price": float(t["entry_price"]),
                    "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]),
                    "symbol": sym, "side": str(t["side"]),
                    "conf": max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5)),
                    "strategy": name, "vol_z": 0.0,
                })
        except Exception as exc:
            print(f"  err {sym}: {exc}")
            continue
    return out


def main():
    print("=" * 90)
    print("Sec19b -- IDF varyant testleri")
    print("=" * 90)

    REPORT_OUT = ROOT / "reports" / "researcher" / "sec19b_idf_variants.md"
    out_lines = []
    def w(line=""):
        print(line)
        out_lines.append(line)

    w("# Sec19b - IDF (Inside Day Failure) varyant testleri")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w("")

    variants = [
        ("V1 (base)", _default_manifest),
        ("V2 (trend ON)", _v2_manifest),
        ("V3 (body>=0.50)", _v3_manifest),
        ("V4 (trend ON + body>=0.50)", _v4_manifest),
    ]

    summaries = []
    rng = np.random.default_rng(42)
    w("| Varyant | n | mR | sumR | WR | Long/Short | Shuffle 90 | p-value | Edge gate |")
    w("|---|---:|---:|---:|---:|---|---:|---:|---|")
    for vname, mfn in variants:
        print(f"\n-> {vname}")
        trades = _gather_custom(mfn)
        if not trades:
            w(f"| {vname} | 0 | - | - | - | - | - | - | n/a |")
            continue
        Rs = np.array([t["R"] for t in trades])
        n_long = sum(1 for t in trades if t["side"] == "long")
        n_short = sum(1 for t in trades if t["side"] == "short")
        mR = Rs.mean()
        wr = (Rs > 0).mean()
        # Shuffle
        sh_means = [np.mean(np.abs(Rs) * rng.choice([-1, 1], size=len(Rs))) for _ in range(50)]
        sh_90 = float(np.percentile(sh_means, 90))
        p = float((np.array(sh_means) >= mR).mean())
        passes = mR > 0.10 and len(trades) > 50 and wr > 0.35 and p < 0.10
        verdict = "PASS" if passes else "FAIL"
        summaries.append((vname, trades, mR, wr, p))
        w(f"| {vname} | {len(trades)} | {mR:+.3f} | {Rs.sum():+.1f} | {wr*100:.1f}% | {n_long}/{n_short} | {sh_90:+.3f} | {p:.3f} | **{verdict}** |")

    # Save best variant for WF
    if summaries:
        best = max(summaries, key=lambda x: x[2])  # by mR
        print(f"\nBest variant: {best[0]} (mR={best[2]:+.3f}, p={best[4]:.3f})")
        w("")
        w(f"## Best Variant: {best[0]}")
        w(f"")
        w(f"- mR: {best[2]:+.3f}")
        w(f"- WR: {best[3]*100:.1f}%")
        w(f"- shuffle p: {best[4]:.3f}")
        w(f"- n trades: {len(best[1])}")

        # Dump for WF
        import pickle
        pkl_path = ROOT / "reports" / "researcher" / "sec19b_best_idf.pkl"
        with open(pkl_path, "wb") as f:
            pickle.dump({"variant": best[0], "trades": best[1], "mR": best[2], "p": best[4]}, f)
        w(f"")
        w(f"Dumped to: `{pkl_path.name}`")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nReport: {REPORT_OUT}")


if __name__ == "__main__":
    main()
