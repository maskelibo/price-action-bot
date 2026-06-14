"""19-sembol x 4-strateji taze 15m havuz üretimi (2026-06-10).

sec31_phoenix_scalp_15m_rolling._gather_peakR_single pipeline'ı birebir:
  - engine fees taker 7.5bps / maker -1bp, slippage 5bps
  - apply_tf_manifest 15m manifestleri otomatik yükler (vsa2 amplify dahil)
  - her sembol kendi listing tarihinden (survivorship yok)
Hücre bazlı checkpoint: data/pool_19sym_20260610/{strat}__{sym}.pkl
Merge: data/pool_19sym_20260610.pkl

Kullanım:
  ./.venv/bin/python scripts/research/build_pool_19sym.py [--workers 6]
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys
import time
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings

warnings.filterwarnings("ignore")
import logging

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
logging.getLogger("price_action").setLevel(logging.ERROR)

SYMBOLS_19 = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "DOT/USDT",
    "DOGE/USDT",
    "XRP/USDT",
    "ZEC/USDT",
    "NEAR/USDT",
    "FIL/USDT",
    "XLM/USDT",
    "TRX/USDT",
    "UNI/USDT",
    "ATOM/USDT",
    "AAVE/USDT",
    "ALGO/USDT",
]
STRATS = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
]
# Kalan 6 Phoenix stratejisi (sec31 listesi) — --extra6 ile üretilir
STRATS_EXTRA6 = [
    ("obv_engulfing_confluence", "OBVEngulfingConfluenceStrategy"),
    ("brooks_h2_l2", "BrooksH2L2Strategy"),
    ("pin_bar_round_numbers", "PinBarRoundNumbersStrategy"),
    ("equal_highs_sweep", "EqualHighsSweepStrategy"),
    ("cvd_spike_fade", "CVDSpikeFadeStrategy"),
    ("fvg_fill_reversal", "FVGFillReversalStrategy"),
]
TF = "15m"
CELL_DIR = ROOT / "data" / "pool_19sym_20260610"
OUT = ROOT / "data" / "pool_19sym_20260610.pkl"
OUT_EXTRA6 = ROOT / "data" / "pool_19sym_extra6_20260610.pkl"


def gather_cell(args):
    """(module, cls, sym, tf) -> trade list. sec31 _gather_peakR_single birebir.

    NOT: tf task-tuple ile taşınır — multiprocessing spawn worker'ları modülü
    taze import ettiği için module-level TF global'i worker'da sıfırlanır.
    """
    module_name, class_name, sym, tf = args
    import duckdb
    import pandas as pd

    from price_action.backtest.engine import BacktestEngine
    from price_action.signals.filters import volume_zscore

    # "4h@15m" formati: 15m verisinden 4h'a resample (native 4h verisi
    # 10 sym / 3 yilla sinirli; 15m tum 19 sembolde listing'den itibaren tam).
    resample_rule = None
    if "@" in tf:
        tf, src_tf = tf.split("@", 1)
        resample_rule = {"4h": "4h", "1h": "1h", "30m": "30min"}.get(tf)
        if resample_rule is None:
            return ("ERR_TF", "resample hedefi taninmiyor: " + tf)
    else:
        src_tf = tf

    try:
        mod = __import__(
            f"price_action.strategies.{module_name}",
            fromlist=[class_name, "_default_manifest"],
        )
        cls = getattr(mod, class_name)
        s = cls(mod._default_manifest())
    except Exception as e:
        return ("ERR_IMPORT", str(e))

    try:
        con = duckdb.connect(str(ROOT / "data" / "market.duckdb"), read_only=True)
        df = con.execute(
            "SELECT ts, open, high, low, close, volume FROM ohlcv "
            "WHERE venue='binance' AND symbol=? AND timeframe=? ORDER BY ts",
            [sym, src_tf],
        ).fetchdf()
        con.close()
        if df.empty:
            return ("ERR_DATA", "empty")
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        if resample_rule is not None:
            # UTC sınırlarına hizalı OHLCV resample (bar-close konvansiyonu korunur)
            df = (
                df.set_index("ts")
                .resample(resample_rule, label="left", closed="left")
                .agg(
                    {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
                )
                .dropna(subset=["open", "close"])
                .reset_index()
            )
            if df.empty:
                return ("ERR_DATA", "resample bos")
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

        # PA_EXIT_VARIANT (2026-06-11): exit-geometri sweep'i. Widestop için TP
        # geometrisi hiç optimize edilmedi (2026-05-17 dar-stop ayarı). Env var
        # spawn worker'lara miras kalır (TF global'inin aksine güvenli).
        _exit_kwargs = {}
        _ev = os.environ.get("PA_EXIT_VARIANT", "")
        if _ev:
            import json as _json

            _exit_kwargs = _json.loads(_ev)
        e = BacktestEngine(risk_officer=None, store_load=None, **_exit_kwargs)
        r = e.run(
            s,
            [sym],
            start=df["ts"].iloc[0].to_pydatetime(),
            end=df["ts"].iloc[-1].to_pydatetime(),
            timeframe=tf,
            initial_capital=10_000.0,
            fees={"taker": 0.00075, "maker": -0.00010},
            slippage_bps=5.0,
            ohlcv_provider=prov,
        )
    except Exception as ex:
        return ("ERR_RUN", str(ex))

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
            peak_R = (mfe_pct if side == "long" else -mfe_pct) / risk_pct if risk_pct > 0 else 0
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
            out.append(
                {
                    "entry_ts": ts_e,
                    "exit_ts": ts_x,
                    "entry_price": entry_price,
                    "initial_sl": initial_sl,
                    "R": final_R,
                    "peak_R": peak_R,
                    "symbol": sym,
                    "side": str(t["side"]),
                    "conf": conf,
                    "strategy": module_name,
                    "vol_z": vz,
                }
            )
        except Exception:
            continue
    return ("OK", out)


def run_cell(args):
    module_name, class_name, sym, tf, cell_dir = args
    cell = Path(cell_dir) / ("%s__%s.pkl" % (module_name, sym.replace("/", "")))
    if cell.exists():
        return (module_name, sym, "cached", -1, 0.0)
    t0 = time.time()
    status, payload = gather_cell((module_name, class_name, sym, tf))
    if status != "OK":
        return (module_name, sym, status + ":" + str(payload)[:60], 0, time.time() - t0)
    with cell.open("wb") as f:
        pickle.dump(payload, f)
    return (module_name, sym, "ok", len(payload), time.time() - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument(
        "--extra6", action="store_true", help="kalan 6 Phoenix stratejisini üret (ayrı çıktı pkl)"
    )
    ap.add_argument("--timeframe", default="15m", help="OHLCV timeframe (örn. 4h)")
    args = ap.parse_args()

    strats = STRATS_EXTRA6 if args.extra6 else STRATS
    out = OUT_EXTRA6 if args.extra6 else OUT
    tf = args.timeframe
    cell_dir = CELL_DIR
    if tf != "15m":
        tf_tag = tf.replace("@", "_")
        cell_dir = CELL_DIR.parent / (CELL_DIR.name + "_" + tf_tag)
        out = out.parent / out.name.replace(".pkl", "_%s.pkl" % tf_tag)
    _exit_tag = os.environ.get("PA_EXIT_TAG", "")
    if _exit_tag:
        cell_dir = cell_dir.parent / (cell_dir.name + "_" + _exit_tag)
        out = out.parent / out.name.replace(".pkl", "_%s.pkl" % _exit_tag)
    cell_dir.mkdir(parents=True, exist_ok=True)

    tasks = [(m, c, sym, tf, str(cell_dir)) for m, c in strats for sym in SYMBOLS_19]
    print("[build] %d hücre, %d worker" % (len(tasks), args.workers), flush=True)

    if args.workers > 1:
        import multiprocessing as mp

        with mp.get_context("spawn").Pool(args.workers) as pool:
            for m, sym, st, n, dt in pool.imap_unordered(run_cell, tasks):
                print("  %-26s %-10s %-8s n=%-6d %.0fs" % (m, sym, st, n, dt), flush=True)
    else:
        for t in tasks:
            m, sym, st, n, dt = run_cell(t)
            print("  %-26s %-10s %-8s n=%-6d %.0fs" % (m, sym, st, n, dt), flush=True)

    merged = []
    missing = []
    for m, c in strats:
        for sym in SYMBOLS_19:
            cell = cell_dir / ("%s__%s.pkl" % (m, sym.replace("/", "")))
            if not cell.exists():
                missing.append((m, sym))
                continue
            with cell.open("rb") as f:
                merged.extend(pickle.load(f))
    if missing:
        print("[uyari] eksik hücreler: %s" % missing, flush=True)
    with out.open("wb") as f:
        pickle.dump(merged, f)
    print("[saved] %s — %d trade" % (out, len(merged)), flush=True)


if __name__ == "__main__":
    main()
