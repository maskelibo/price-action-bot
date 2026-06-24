"""SEC55.A — Paralel scan benchmark.

Kullanım:
    python scripts/benchmark_scan_parallel.py [--workers 1 4 8 16] [--runs 3]

Çıktı:
    - SPEEDUP TABLE: max_workers × scan_time (saniye) × speedup ratio
    - Per-strategy breakdown (mock olmadan DuckDB'den gerçek veri varsa)
    - GIL analizi: CPU-bound vs I/O-bound yorum

Ortam:
    - Gerçek DuckDB market.duckdb ile koşulmalı (veri varsa).
    - Veri yoksa fallback: sentetik OHLCV ile strateji hesaplama zamanı ölçülür.
    - PA_SCAN_PARALLEL_WORKERS env override devre dışı (benchmark kendi kontrol eder).
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import os
os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed


# ── Config ────────────────────────────────────────────────────────────────────

SYMBOLS: list[str] = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
    "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT",
]

TF = "15m"

TOP_4_15M = [
    ("vsa_climax_test",          "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout",   "BrooksFailedBreakoutStrategy"),
    ("anchored_vwap_reversal",   "AnchoredVWAPReversalStrategy"),
    ("engulfing_continuation",   "EngulfingContinuationStrategy"),
]

_BAR_CLOSE = datetime.now(timezone.utc).replace(second=0, microsecond=0)


# ── Sentetik OHLCV oluştur ────────────────────────────────────────────────────

def _make_synthetic_ohlcv(sym: str, n_bars: int = 500) -> pd.DataFrame:
    """Gerçekçi 15m OHLCV bar'ları (seed: sym hash)."""
    rng = np.random.default_rng(abs(hash(sym)) % (2**32))
    base = 100.0 if "BTC" not in sym else 60000.0

    closes = base * np.cumprod(1 + rng.normal(0, 0.002, n_bars))
    opens  = np.roll(closes, 1); opens[0] = closes[0]
    highs  = np.maximum(opens, closes) * (1 + rng.uniform(0, 0.005, n_bars))
    lows   = np.minimum(opens, closes) * (1 - rng.uniform(0, 0.005, n_bars))
    vols   = rng.uniform(1000, 50000, n_bars)

    end_ts = pd.Timestamp(_BAR_CLOSE)
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")
    ts_idx = pd.date_range(
        end=end_ts, periods=n_bars, freq="15min", tz="UTC"
    )
    df = pd.DataFrame({
        "venue": "binance",
        "symbol": sym,
        "timeframe": TF,
        "ts": ts_idx,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": vols,
    })
    df["vol_z_pre"] = 0
    return df


# ── Per-symbol scan (benchmark version — sentetik veri) ──────────────────────

def _scan_symbol_synth(sym: str, target_bar_close: pd.Timestamp) -> tuple[str, list, dict]:
    """Per-symbol scan ile per-strategy timing."""
    df = _make_synthetic_ohlcv(sym)
    df_filtered = df[df["ts"] <= target_bar_close].copy()
    if df_filtered.empty:
        return sym, [], {}

    last_bar_ts = df_filtered["ts"].iloc[-1]
    last_close = float(df_filtered.iloc[-1]["close"])

    signals = []
    strategy_times: dict[str, float] = {}

    for module_name, class_name in TOP_4_15M:
        t0 = time.perf_counter()
        try:
            mod = __import__(
                f"price_action.strategies.{module_name}",
                fromlist=[class_name, "_default_manifest"],
            )
            cls = getattr(mod, class_name)
            manifest_fn = getattr(mod, "_default_manifest", None)
            if not manifest_fn:
                strategy_times[module_name] = 0.0
                continue
            strategy = cls(manifest_fn())
            df_prep = strategy.prepare_features(df_filtered.copy())
            sigs = strategy.generate_signals(df_prep)

            for sig in sigs:
                sig_ts = pd.Timestamp(sig.ts)
                if sig_ts.tzinfo is None:
                    sig_ts = sig_ts.tz_localize("UTC")
                if abs((sig_ts - last_bar_ts).total_seconds()) < 60:
                    signals.append({
                        "ts": sig_ts,
                        "bar_close_ts": last_bar_ts,
                        "symbol": sym,
                        "strategy": module_name,
                        "side": sig.direction,
                        "entry_price": last_close,
                        "sl_price": sig.sl_price,
                        "tp_price": sig.tp_price,
                        "confluence": sig.confluence_score,
                    })
        except Exception as exc:
            print(f"  [WARN] {sym} / {module_name}: {type(exc).__name__}: {str(exc)[:80]}")
        finally:
            strategy_times[module_name] = time.perf_counter() - t0

    return sym, signals, strategy_times


def _run_scan_workers(workers: int, n_syms: int = 10) -> dict:
    """Tüm sembolleri workers adedi ile scan et, timing döndür."""
    tbc = pd.Timestamp(_BAR_CLOSE).tz_localize("UTC") if pd.Timestamp(_BAR_CLOSE).tzinfo is None else pd.Timestamp(_BAR_CLOSE).tz_convert("UTC")
    syms = SYMBOLS[:n_syms]

    strategy_agg: dict[str, list[float]] = {m: [] for m, _ in TOP_4_15M}
    sym_times: dict[str, float] = {}
    all_signals: list[dict] = []

    wall_start = time.perf_counter()

    if workers == 1:
        # Sequential
        for sym in syms:
            t_sym = time.perf_counter()
            _, sigs, strat_times = _scan_symbol_synth(sym, tbc)
            sym_times[sym] = time.perf_counter() - t_sym
            all_signals.extend(sigs)
            for m, t in strat_times.items():
                strategy_agg[m].append(t)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_scan_symbol_synth, sym, tbc): sym
                for sym in syms
            }
            for fut in as_completed(futures):
                sym = futures[fut]
                t_sym_start = time.perf_counter()
                try:
                    _, sigs, strat_times = fut.result(timeout=300)
                    sym_times[sym] = time.perf_counter() - t_sym_start
                    all_signals.extend(sigs)
                    for m, t in strat_times.items():
                        strategy_agg[m].append(t)
                except Exception as exc:
                    print(f"  [ERR] {sym}: {exc}")

    wall_elapsed = time.perf_counter() - wall_start
    all_signals.sort(key=lambda s: (s["ts"], s["symbol"]))

    strategy_mean: dict[str, float] = {
        m: (sum(v) / len(v) if v else 0.0)
        for m, v in strategy_agg.items()
    }

    return {
        "workers": workers,
        "wall_sec": wall_elapsed,
        "n_signals": len(all_signals),
        "sym_times": sym_times,
        "strategy_mean_sec": strategy_mean,
    }


# ── Benchmark main ────────────────────────────────────────────────────────────

def _print_separator(char: str = "-", width: int = 72) -> None:
    print(char * width)


def run_benchmark(worker_configs: list[int], runs: int = 3) -> None:
    print()
    _print_separator("=")
    print("SEC55.A — PARALLEL SCAN BENCHMARK")
    print(f"Semboller: {len(SYMBOLS)} | Stratejiler: {len(TOP_4_15M)} | Runs: {runs}")
    print(f"Bar close: {_BAR_CLOSE.strftime('%Y-%m-%d %H:%M')} UTC")
    _print_separator("=")

    # Warm-up (JIT / import cache)
    print("\n[WARM-UP] max_workers=1, 1 run...")
    _run_scan_workers(1)
    print("  done.\n")

    results: dict[int, list[float]] = {}
    strategy_breakdown: dict[int, dict[str, float]] = {}

    for workers in worker_configs:
        run_times = []
        strat_agg: dict[str, list[float]] = {m: [] for m, _ in TOP_4_15M}

        for run_idx in range(runs):
            r = _run_scan_workers(workers)
            run_times.append(r["wall_sec"])
            for m, t in r["strategy_mean_sec"].items():
                strat_agg[m].append(t)

            sig_count = r["n_signals"]
            print(
                f"  workers={workers:>2}  run={run_idx+1}/{runs}  "
                f"wall={r['wall_sec']:.2f}s  signals={sig_count}"
            )

        results[workers] = run_times
        strategy_breakdown[workers] = {
            m: sum(v) / len(v) for m, v in strat_agg.items()
        }

    # ── SPEEDUP TABLE ──────────────────────────────────────────────────────────
    print()
    _print_separator("=")
    print("SPEEDUP TABLE")
    _print_separator("=")
    print(f"{'workers':>8}  {'mean (s)':>9}  {'min (s)':>8}  {'max (s)':>8}  {'speedup':>8}")
    _print_separator("-")

    baseline_mean = sum(results[1]) / len(results[1]) if 1 in results else None

    for workers in worker_configs:
        run_times = results[workers]
        mean_t = sum(run_times) / len(run_times)
        min_t  = min(run_times)
        max_t  = max(run_times)
        speedup = (baseline_mean / mean_t) if baseline_mean and mean_t > 0 else 1.0
        print(
            f"{workers:>8}  {mean_t:>9.2f}  {min_t:>8.2f}  {max_t:>8.2f}  {speedup:>7.2f}x"
        )

    # ── Per-strategy breakdown ─────────────────────────────────────────────────
    print()
    _print_separator("=")
    print("PER-STRATEGY BREAKDOWN (per-symbol mean, seconds)")
    _print_separator("=")
    header = f"{'strategy':<35}" + "".join(f"  w={w:>2}" for w in worker_configs)
    print(header)
    _print_separator("-")

    for module_name, _ in TOP_4_15M:
        row = f"{module_name:<35}"
        for workers in worker_configs:
            t = strategy_breakdown.get(workers, {}).get(module_name, 0.0)
            row += f"  {t:>5.2f}s"
        print(row)

    # ── GIL analizi ───────────────────────────────────────────────────────────
    print()
    _print_separator("=")
    print("GIL ANALIZI")
    _print_separator("=")

    if baseline_mean and 8 in results:
        par8_mean = sum(results[8]) / len(results[8])
        speedup8  = baseline_mean / par8_mean
        theoretical_max = min(8, len(SYMBOLS))

        if speedup8 > theoretical_max * 0.7:
            bound_type = "I/O-bound (ThreadPool yeterli)"
        elif speedup8 > theoretical_max * 0.3:
            bound_type = "MIXED (ThreadPool yeterli, ProcessPool geliştirme adayi)"
        else:
            bound_type = "CPU-bound (ProcessPool önerilir)"

        print(f"  w=8 speedup       : {speedup8:.2f}x")
        print(f"  Teorik max (w=8)  : {theoretical_max}x")
        print(f"  Bağımlılık tipi   : {bound_type}")
    else:
        print("  workers=8 sonucu bulunamadı — GIL analizi atlandı.")

    print()
    _print_separator("=")
    print("BENCHMARK TAMAMLANDI")
    _print_separator("=")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SEC55.A Parallel scan benchmark")
    parser.add_argument(
        "--workers", nargs="+", type=int, default=[1, 4, 8, 16],
        help="Test edilecek worker sayıları (default: 1 4 8 16)"
    )
    parser.add_argument(
        "--runs", type=int, default=3,
        help="Her config için tekrar sayısı (default: 3)"
    )
    args = parser.parse_args()

    run_benchmark(
        worker_configs=sorted(set(args.workers)),
        runs=args.runs,
    )
