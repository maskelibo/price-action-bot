"""Grimes ABC two-leg pullback havuz üretimi — 19 sembol, 15m + 4h@15m.

build_pool_19sym.gather_cell altyapısını birebir kullanır (engine fees taker
7.5bps / maker -1bp, slippage 5bps, native 30/30/40 exit). Tek strateji.

Çıktı:
  data/pool_grimes_abc_15m.pkl   (tf=15m)
  data/pool_grimes_abc_4h.pkl    (tf=4h@15m → 15m'den 4h resample)

Kullanım:
  ./.venv/bin/python scripts/research/build_pool_grimes_abc.py --tf 15m --workers 6
  ./.venv/bin/python scripts/research/build_pool_grimes_abc.py --tf 4h@15m --workers 6
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
sys.path.insert(0, str(ROOT / "scripts" / "research"))
logging.getLogger("price_action").setLevel(logging.ERROR)

from build_pool_19sym import SYMBOLS_19, gather_cell

MODULE = "grimes_abc_pullback"
CLASS = "GrimesABCPullbackStrategy"


def run_cell(args):
    sym, tf, cell_dir = args
    cell = Path(cell_dir) / ("%s__%s.pkl" % (MODULE, sym.replace("/", "")))
    if cell.exists():
        return (sym, "cached", -1, 0.0)
    t0 = time.time()
    status, payload = gather_cell((MODULE, CLASS, sym, tf))
    if status != "OK":
        return (sym, status + ":" + str(payload)[:60], 0, time.time() - t0)
    with cell.open("wb") as f:
        pickle.dump(payload, f)
    return (sym, "ok", len(payload), time.time() - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--tf", default="15m", help="15m veya 4h@15m")
    args = ap.parse_args()

    tf = args.tf
    tf_tag = "15m" if tf == "15m" else tf.split("@")[0]  # 4h
    cell_dir = ROOT / "data" / ("pool_grimes_abc_%s_cells" % tf_tag)
    out = ROOT / "data" / ("pool_grimes_abc_%s.pkl" % tf_tag)
    cell_dir.mkdir(parents=True, exist_ok=True)

    tasks = [(sym, tf, str(cell_dir)) for sym in SYMBOLS_19]
    print("[build] grimes_abc tf=%s — %d hücre, %d worker" % (tf, len(tasks), args.workers), flush=True)

    if args.workers > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(args.workers) as pool:
            for sym, st, n, dt in pool.imap_unordered(run_cell, tasks):
                print("  %-10s %-12s n=%-6d %.0fs" % (sym, st, n, dt), flush=True)
    else:
        for t in tasks:
            sym, st, n, dt = run_cell(t)
            print("  %-10s %-12s n=%-6d %.0fs" % (sym, st, n, dt), flush=True)

    merged, missing = [], []
    for sym in SYMBOLS_19:
        cell = cell_dir / ("%s__%s.pkl" % (MODULE, sym.replace("/", "")))
        if not cell.exists():
            missing.append(sym)
            continue
        with cell.open("rb") as f:
            merged.extend(pickle.load(f))
    if missing:
        print("[uyari] eksik: %s" % missing, flush=True)
    with out.open("wb") as f:
        pickle.dump(merged, f)
    print("[saved] %s — %d trade" % (out, len(merged)), flush=True)


if __name__ == "__main__":
    main()
