"""SEC-S5 Yol G - Standalone backtest of bb_band_continuation (15m x 10 sym x 5y).

Hypothesis: HYP-2026-05-17-bb-continuation-15m (pre-registered 15:10:56Z).

Pipeline:
  1. Collect trades using BacktestEngine (sec_s5 pattern)
  2. Per-strategy stats: n trade, mean R, WR%, sumR
  3. Per-symbol stats (10 sym leave-one-out)
  4. Regime split: 2022 (bear), 2024 (bull), 2025-2026 (range)
  5. Shuffle null (n=200) p-value
  6. Pre-registered gate evaluation (n>=500, mR>=+0.15, WR>=55%, p<0.10)
  7. Karar agaci: v1 fail (n<500) -> v2 fallback

Output:
  - data/sec_s5_yol_g_bb_cont_pool.pkl  (cached trade pool)
  - reports/researcher/2026-05-17_yol_g_bb_continuation_standalone.md
"""
from __future__ import annotations
import io, os, pickle, sys, time
from pathlib import Path

if __name__ == "__main__":
    try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception: pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from price_action.backtest.engine import BacktestEngine
from price_action.signals.filters import volume_zscore
from price_action.strategies.bb_band_continuation import (
    BBBandContinuationStrategy, _default_manifest, _v2_manifest,
)
from scripts.run_real_backtest import _load_symbol_ohlcv

SYMBOLS_10 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
              "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
              "DOGE/USDT", "XRP/USDT"]

TF = "15m"
CACHE_V1 = ROOT / "data" / "sec_s5_yol_g_bb_cont_v1_pool.pkl"
CACHE_V2 = ROOT / "data" / "sec_s5_yol_g_bb_cont_v2_pool.pkl"
REPORT_OUT = ROOT / "reports" / "researcher" / "2026-05-17_yol_g_bb_continuation_standalone.md"


# Pre-registered gate (from HYP-2026-05-17-bb-continuation-15m §7)
GATE = {
    "min_n_trades": 500,
    "min_mean_R": 0.15,
    "min_WR": 0.55,
    "max_pvalue": 0.10,
    "min_pos_regimes": 2,
    "max_symout_sapma_pct": 50.0,
}


def _gather_trades(manifest, variant: str, sym: str, tf: str = TF) -> list[dict]:
    """Collect trades for a given manifest variant on one symbol."""
    try:
        s = BBBandContinuationStrategy(manifest)
    except Exception as e:
        print(f"  [SKIP] {variant}/{sym}: init {e}")
        return []

    try:
        df = _load_symbol_ohlcv(sym, tf=tf)
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
    except Exception as ex:
        print(f"  [ERR] {variant}/{sym}: run {ex}")
        return []

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
                "strategy": "bb_band_continuation",
                "vol_z": vz,
            })
        except Exception:
            continue
    return out


def shuffle_null_pvalue(trades: list[dict], n_iter: int = 200, seed: int = 7) -> tuple[float, float]:
    """Shuffle null: random sign-flip R; compare observed mean R vs null distribution.

    Returns (p_value, observed_mean_R). One-sided: P(null_mean >= obs).
    """
    rng = np.random.default_rng(seed)
    Rs = np.array([t["R"] for t in trades], dtype=float)
    obs_mean = float(np.mean(Rs))
    n = len(Rs)
    if n == 0:
        return 1.0, 0.0
    null_means = []
    for _ in range(n_iter):
        flips = rng.choice([-1, 1], size=n)
        null_means.append(float(np.mean(Rs * flips)))
    null_arr = np.array(null_means)
    p = float((null_arr >= obs_mean).mean())
    return p, obs_mean


def regime_split(trades: list[dict]) -> dict[str, dict]:
    buckets = {"bear_2022": [], "bull_2023_2024": [], "range_2025_2026": []}
    for t in trades:
        ts = t["entry_ts"]
        if ts.year == 2022:
            buckets["bear_2022"].append(t)
        elif ts.year in (2023, 2024):
            buckets["bull_2023_2024"].append(t)
        elif ts.year >= 2025:
            buckets["range_2025_2026"].append(t)
    out = {}
    for k, v in buckets.items():
        if not v:
            out[k] = {"n": 0, "mR": 0.0, "wr": 0.0}
        else:
            Rs = [t["R"] for t in v]
            out[k] = {
                "n": len(v),
                "mR": sum(Rs) / len(Rs),
                "wr": sum(1 for r in Rs if r > 0) / len(Rs),
            }
    return out


def symbol_out_stats(trades: list[dict], syms: list[str]) -> dict[str, dict]:
    out = {}
    for excl in syms:
        sub = [t for t in trades if t["symbol"] != excl]
        if not sub:
            continue
        Rs = [t["R"] for t in sub]
        out[excl] = {
            "n": len(sub),
            "mR": sum(Rs) / len(Rs),
            "wr": sum(1 for r in Rs if r > 0) / len(Rs),
        }
    return out


def symbol_concentration(trades: list[dict]) -> dict[str, float]:
    """Per-symbol trade share (curve-fit detect)."""
    n = len(trades)
    if n == 0:
        return {}
    by_sym: dict[str, int] = {}
    for t in trades:
        sym = t["symbol"]
        by_sym[sym] = by_sym.get(sym, 0) + 1
    return {k: v / n for k, v in sorted(by_sym.items(), key=lambda x: -x[1])}


def evaluate(variant: str, trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {
            "variant": variant, "n": 0, "mR": 0.0, "wr": 0.0,
            "sumR": 0.0, "p_value": 1.0, "regime": {}, "symout": {},
            "concentration": {}, "verdict": "RED (n=0)", "fails": ["n=0"],
        }
    Rs = [t["R"] for t in trades]
    mR = sum(Rs) / n
    wr = sum(1 for r in Rs if r > 0) / n
    sumR = sum(Rs)
    p, _ = shuffle_null_pvalue(trades, n_iter=200)
    regime = regime_split(trades)
    symout = symbol_out_stats(trades, SYMBOLS_10)
    conc = symbol_concentration(trades)

    fails = []
    if n < GATE["min_n_trades"]:
        fails.append(f"n<{GATE['min_n_trades']}")
    if mR < GATE["min_mean_R"]:
        fails.append(f"mR<{GATE['min_mean_R']:.2f}")
    if wr < GATE["min_WR"]:
        fails.append(f"WR<{GATE['min_WR']:.0%}")
    if p >= GATE["max_pvalue"]:
        fails.append(f"p>={GATE['max_pvalue']:.2f}")

    pos_regimes = sum(1 for v in regime.values() if v["mR"] > 0 and v["n"] > 0)
    if pos_regimes < GATE["min_pos_regimes"]:
        fails.append(f"only {pos_regimes}/3 regime pos")

    if symout:
        worst_mr = min(s["mR"] for s in symout.values())
        sapma_pct = abs(worst_mr - mR) / max(abs(mR), 1e-9) * 100
        if sapma_pct > GATE["max_symout_sapma_pct"]:
            fails.append(f"symout sapma {sapma_pct:.0f}%>50%")

    # Concentration check (curve-fit guard)
    top_share = max(conc.values()) if conc else 0
    if top_share > 0.4:
        fails.append(f"top_sym_share {top_share:.0%}>40%")

    verdict = "PASS" if not fails else f"RED ({'; '.join(fails)})"

    return {
        "variant": variant, "n": n, "mR": mR, "wr": wr, "sumR": sumR,
        "p_value": p, "regime": regime, "symout": symout,
        "concentration": conc, "verdict": verdict, "fails": fails,
    }


def collect_for_variant(manifest, variant_name: str, cache_path: Path) -> list[dict]:
    """Collect or load cached trades for a variant."""
    if cache_path.exists():
        print(f"[cache hit] {cache_path.name}")
        with cache_path.open("rb") as f:
            return pickle.load(f)
    print(f"\n[collect] {variant_name}")
    all_trades: list[dict] = []
    for sym in SYMBOLS_10:
        t1 = time.time()
        tr = _gather_trades(manifest, variant_name, sym)
        print(f"  {sym}: {len(tr)} trades ({time.time()-t1:.1f}s)")
        all_trades.extend(tr)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("wb") as f:
        pickle.dump(all_trades, f)
    print(f"[cache] {cache_path.name}")
    return all_trades


def main():
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = ""):
        print(line)
        out_lines.append(line)

    w("# SEC-S5 Yol G - bb_band_continuation Standalone")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w(f"**Pre-registration:** HYP-2026-05-17-bb-continuation-15m (15:10:56Z)")
    w(f"**Timeframe:** {TF}")
    w(f"**Universe:** {len(SYMBOLS_10)} sym x 5y")
    w("")
    w("## Pre-Registered Gate (HEPSI zorunlu)")
    w(f"- n trades >= {GATE['min_n_trades']}")
    w(f"- mean R >= +{GATE['min_mean_R']:.2f}")
    w(f"- WR >= {GATE['min_WR']:.0%}")
    w(f"- shuffle p-value < {GATE['max_pvalue']:.2f}")
    w(f"- >= {GATE['min_pos_regimes']}/3 regime positive")
    w(f"- symbol-out worst sapma <= {GATE['max_symout_sapma_pct']:.0f}%")
    w(f"- top symbol share < 40% (curve-fit guard)")
    w("")
    w("**Karar agaci:** v1 (RSI 75/25 + body 0.5) -> n>=500 ise evaluate v1.")
    w("v1 n<500 ise v2 fallback (RSI 70/30 + body 0.4) evaluate.")
    w("")

    # ========================================================================
    # v1 collect + evaluate
    # ========================================================================
    t0 = time.time()
    v1_trades = collect_for_variant(_default_manifest(), "v1", CACHE_V1)
    print(f"\n[v1 done] {time.time()-t0:.1f}s, n={len(v1_trades):,}")

    res_v1 = evaluate("v1 (RSI 75/25, body 0.5)", v1_trades)

    w("## Results - v1 (default, RSI 75/25 + body 0.5)")
    w("")
    w("| Metric | Value |")
    w("|---|---:|")
    w(f"| n trades | {res_v1['n']:,} |")
    w(f"| mean R | {res_v1['mR']:+.4f} |")
    w(f"| sumR | {res_v1['sumR']:+.1f} |")
    w(f"| WR | {res_v1['wr']:.1%} |")
    w(f"| shuffle p-value (n=200) | {res_v1['p_value']:.3f} |")
    w(f"| **verdict** | **{res_v1['verdict']}** |")
    w("")

    # Symbol concentration
    if res_v1["concentration"]:
        w("### v1 Symbol concentration (top 5)")
        w("| Symbol | share |")
        w("|---|---:|")
        for sym, sh in list(res_v1["concentration"].items())[:5]:
            w(f"| {sym} | {sh:.1%} |")
        w("")

    # Regime
    if res_v1["regime"]:
        w("### v1 Regime split")
        w("| Regime | n | mean R | WR |")
        w("|---|---:|---:|---:|")
        for k, v in res_v1["regime"].items():
            w(f"| {k} | {v['n']:,} | {v['mR']:+.4f} | {v['wr']:.1%} |")
        w("")

    # Symbol-out
    if res_v1["symout"]:
        w("### v1 Symbol-out CV (leave-one-out)")
        w("| Excluded | n | mean R | WR |")
        w("|---|---:|---:|---:|")
        for k, v in res_v1["symout"].items():
            w(f"| {k} | {v['n']:,} | {v['mR']:+.4f} | {v['wr']:.1%} |")
        w("")

    # ========================================================================
    # v2 fallback (per karar agaci)
    # ========================================================================
    primary_res = res_v1
    primary_trades = v1_trades
    primary_variant = "v1"

    if res_v1["n"] < GATE["min_n_trades"]:
        w("## Karar agaci: v1 n < 500 -> v2 fallback")
        w("")
        v2_trades = collect_for_variant(_v2_manifest(), "v2", CACHE_V2)
        res_v2 = evaluate("v2 (RSI 70/30, body 0.4)", v2_trades)

        w("## Results - v2 (fallback, RSI 70/30 + body 0.4)")
        w("")
        w("| Metric | Value |")
        w("|---|---:|")
        w(f"| n trades | {res_v2['n']:,} |")
        w(f"| mean R | {res_v2['mR']:+.4f} |")
        w(f"| sumR | {res_v2['sumR']:+.1f} |")
        w(f"| WR | {res_v2['wr']:.1%} |")
        w(f"| shuffle p-value (n=200) | {res_v2['p_value']:.3f} |")
        w(f"| **verdict** | **{res_v2['verdict']}** |")
        w("")

        if res_v2["concentration"]:
            w("### v2 Symbol concentration (top 5)")
            w("| Symbol | share |")
            w("|---|---:|")
            for sym, sh in list(res_v2["concentration"].items())[:5]:
                w(f"| {sym} | {sh:.1%} |")
            w("")

        if res_v2["regime"]:
            w("### v2 Regime split")
            w("| Regime | n | mean R | WR |")
            w("|---|---:|---:|---:|")
            for k, v in res_v2["regime"].items():
                w(f"| {k} | {v['n']:,} | {v['mR']:+.4f} | {v['wr']:.1%} |")
            w("")

        if res_v2["symout"]:
            w("### v2 Symbol-out CV")
            w("| Excluded | n | mean R | WR |")
            w("|---|---:|---:|---:|")
            for k, v in res_v2["symout"].items():
                w(f"| {k} | {v['n']:,} | {v['mR']:+.4f} | {v['wr']:.1%} |")
            w("")

        primary_res = res_v2
        primary_trades = v2_trades
        primary_variant = "v2"

    # ========================================================================
    # Final verdict
    # ========================================================================
    w("## Final Verdict (Standalone)")
    w("")
    w(f"**Primary variant evaluated:** {primary_variant}")
    w(f"**Verdict:** {primary_res['verdict']}")
    w("")
    if primary_res["verdict"] == "PASS":
        w("**STANDALONE PASS** -> proceed to ensemble retest (Step 4).")
        w("")
        w("Save the primary pool path for ensemble script:")
        w(f"- pool path: `{CACHE_V1 if primary_variant=='v1' else CACHE_V2}`")
    else:
        w("**STANDALONE RED** -> archive hypothesis, no ensemble retest.")
        w(f"Fails: {primary_res['fails']}")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\n[report] {REPORT_OUT}")

    # Print to stdout for piping to next script
    print("\n" + "=" * 70)
    print(f"PRIMARY VARIANT: {primary_variant}")
    print(f"VERDICT: {primary_res['verdict']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
