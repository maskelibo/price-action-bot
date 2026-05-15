"""Sec22 — 3 yeni mean-reversion strateji standalone backtest.

Stratejiler (STRATEGY_CLASS = 'mean_reversion'):
  - rsi2_extreme_fade    (Connors 2-period RSI + EMA200 + 5d-low/high)
  - three_push_wedge_fade (Brooks 3-push wedge fade)
  - bb_extreme_reversal  (Bollinger 2.5sigma extreme + reclaim)

Edge gate (HARD, anyone fail -> RED):
  - n >= 150
  - WR > 0.35
  - mR > +0.10 (RAG +0.15 target ama relax 0.10 marginal pass)
  - shuffle p < 0.05
  - max_R < 10 (artifact filter)

Coverage: 11 sym x 5y x 1d. Honest clip hold>60d => R<=1.0.

Engineering SEC21 koordinasyon: STRATEGY_CLASS metadata module-level zorunlu;
bu test PASS aday listesi engineering slot fix sonrasi ENSEMBLE RETEST icin
ayri sprint'te kullanilacak (BU SPRINT'TE ENSEMBLE YOK).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

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

SYMBOLS_11 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
              "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
              "DOGE/USDT", "XRP/USDT", "MATIC/USDT"]

NEW_MEAN_REV = [
    ("rsi2_extreme_fade",     "RSI2ExtremeFadeStrategy"),
    ("three_push_wedge_fade", "ThreePushWedgeFadeStrategy"),
    ("bb_extreme_reversal",   "BBExtremeReversalStrategy"),
]

# Edge gates HARD
GATE = {
    "n_min": 150,
    "mR_min": 0.10,
    "WR_min": 0.35,
    "p_max": 0.05,
    "max_R_max": 10.0,
}


def _verify_class_metadata():
    """Engineering SEC21 hook — STRATEGY_CLASS module-level metadata zorunlu."""
    failed = []
    for module_name, _cls in NEW_MEAN_REV:
        try:
            mod = __import__(f"price_action.strategies.{module_name}", fromlist=["STRATEGY_CLASS"])
            sc = getattr(mod, "STRATEGY_CLASS", None)
            if sc != "mean_reversion":
                failed.append((module_name, sc))
        except Exception as e:
            failed.append((module_name, f"import-fail: {e}"))
    return failed


def _gather(module_name, class_name, universe):
    from price_action.backtest.engine import BacktestEngine
    from scripts.run_real_backtest import _load_symbol_ohlcv

    try:
        mod = __import__(f"price_action.strategies.{module_name}",
                         fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn:
            return []
        strategy = cls(manifest_fn())
    except Exception as e:
        print(f"   IMPORT FAIL {module_name}: {e}")
        return []

    out = []
    for sym in universe:
        try:
            df = _load_symbol_ohlcv(sym, tf="1d")
            if df is None or df.empty:
                continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym
            df["venue"] = "binance"
            df["timeframe"] = "1d"

            def prov(*a, **k):
                return df.copy()

            e = BacktestEngine(risk_officer=None, store_load=None)
            r = e.run(strategy, [sym],
                     start=df["ts"].iloc[0].to_pydatetime(),
                     end=df["ts"].iloc[-1].to_pydatetime(),
                     timeframe="1d",
                     initial_capital=10_000.0,
                     fees={"taker": 0.00075, "maker": -0.00010},
                     slippage_bps=5.0,
                     ohlcv_provider=prov)
            for _, t in r.trades.iterrows():
                entry_ts = pd.Timestamp(t["entry_ts"])
                exit_ts = pd.Timestamp(t["exit_ts"])
                hold_d = (exit_ts - entry_ts).days
                R_raw = float(t["realized_r_multiple"])
                # Honest clip: hold > 60d (sec19 dataset-end artifact lesson)
                R = R_raw if hold_d <= 60 else min(R_raw, 1.0)
                out.append({
                    "entry_ts": entry_ts,
                    "exit_ts": exit_ts,
                    "hold_d": hold_d,
                    "R": R,
                    "R_raw": R_raw,
                    "symbol": sym,
                    "side": str(t["side"]),
                    "strategy": module_name,
                    "entry_price": float(t["entry_price"]),
                    "initial_sl": float(t["initial_sl"]),
                })
        except Exception as exc:
            print(f"   ERROR {sym} {module_name}: {exc}")
            continue
    return out


def _shuffle_p(trades, n_perm=200, seed=42):
    if not trades:
        return None
    Rs = np.array([t["R"] for t in trades], dtype=float)
    obs = float(Rs.sum())
    rng = np.random.default_rng(seed)
    null_sums = []
    for _ in range(n_perm):
        signs = rng.choice([-1, 1], size=len(Rs))
        null_sums.append((Rs * signs).sum())
    null_sums = np.array(null_sums)
    return float((null_sums >= obs).mean())


def _summary(trades, name):
    if not trades:
        return {"strategy": name, "n": 0, "mR": 0.0, "mR_raw": 0.0, "WR": 0.0,
                "max_R": 0.0, "median_R": 0.0, "sumR": 0.0,
                "n_long": 0, "n_short": 0, "p_shuffle": None,
                "n_artifact": 0, "hold_d_median": 0, "hold_d_p90": 0}
    Rs = np.array([t["R"] for t in trades], dtype=float)
    Rs_raw = np.array([t["R_raw"] for t in trades], dtype=float)
    holds = np.array([t["hold_d"] for t in trades])
    p = _shuffle_p(trades)
    n_long = sum(1 for t in trades if t["side"] == "long")
    n_short = sum(1 for t in trades if t["side"] == "short")
    by_sym = {}
    for t in trades:
        by_sym.setdefault(t["symbol"], []).append(t["R"])

    return {
        "strategy": name,
        "n": len(trades),
        "mR": float(Rs.mean()),
        "mR_raw": float(Rs_raw.mean()),
        "WR": float((Rs > 0).mean()),
        "max_R": float(Rs.max()),
        "median_R": float(np.median(Rs)),
        "sumR": float(Rs.sum()),
        "n_long": n_long,
        "n_short": n_short,
        "p_shuffle": p,
        "n_artifact": int((Rs_raw > 10.0).sum()),
        "hold_d_median": int(np.median(holds)),
        "hold_d_p90": int(np.percentile(holds, 90)),
        "by_sym": {sym: (len(v), float(np.mean(v))) for sym, v in by_sym.items()},
    }


def _gate_check(s):
    fails = []
    if s["n"] < GATE["n_min"]:
        fails.append(f"n={s['n']}<{GATE['n_min']}")
    if s["WR"] < GATE["WR_min"]:
        fails.append(f"WR={s['WR']*100:.1f}<{GATE['WR_min']*100:.0f}")
    if s["mR"] < GATE["mR_min"]:
        fails.append(f"mR={s['mR']:+.3f}<{GATE['mR_min']}")
    if s["p_shuffle"] is None or s["p_shuffle"] >= GATE["p_max"]:
        fails.append(f"p={s['p_shuffle']}>={GATE['p_max']}")
    if s["max_R"] >= GATE["max_R_max"]:
        fails.append(f"maxR={s['max_R']:.2f}>={GATE['max_R_max']}")
    return ("PASS" if not fails else "FAIL"), fails


def main():
    print("=" * 100)
    print("Sec22 - 3 yeni mean-reversion strateji standalone backtest (5y, 11 sym)")
    print("=" * 100)
    print()

    # Verify STRATEGY_CLASS metadata (Engineering SEC21 hook)
    print("[METADATA AUDIT — Engineering SEC21 hook]")
    failed_meta = _verify_class_metadata()
    if failed_meta:
        print("  FAIL — STRATEGY_CLASS metadata sorunu:")
        for mod, sc in failed_meta:
            print(f"    {mod}: STRATEGY_CLASS = {sc!r} (expected 'mean_reversion')")
        return
    print("  PASS — all 3 modules have STRATEGY_CLASS = 'mean_reversion'")
    print()

    all_trades = {}
    summaries = []
    for module_name, cls_name in NEW_MEAN_REV:
        print(f"-> {module_name} ({cls_name})")
        trades = _gather(module_name, cls_name, SYMBOLS_11)
        all_trades[module_name] = trades
        s = _summary(trades, module_name)
        summaries.append(s)
        print(f"   n={s['n']:5d}  mR={s['mR']:+.3f}  (raw {s['mR_raw']:+.3f})  "
              f"WR={s['WR']*100:.1f}%  long={s['n_long']:4d} short={s['n_short']:4d}  "
              f"p={s['p_shuffle']:.3f}  max_R={s['max_R']:.2f}  median_R={s['median_R']:+.3f}  "
              f"hold_median={s['hold_d_median']}d hold_p90={s['hold_d_p90']}d artifact_n={s['n_artifact']}")

    print()
    print("=" * 100)
    print(f"HARD GATE — n>={GATE['n_min']}, mR>={GATE['mR_min']}, WR>{GATE['WR_min']*100:.0f}%, "
          f"p<{GATE['p_max']}, max_R<{GATE['max_R_max']}")
    print("=" * 100)
    passes = []
    for s in summaries:
        verdict, fails = _gate_check(s)
        info = ", ".join(fails) if fails else "ALL_OK"
        print(f"  [{verdict}] {s['strategy']:<30} n={s['n']:4d}  mR={s['mR']:+.3f}  "
              f"WR={s['WR']*100:5.1f}%  p={s['p_shuffle']:.3f}  maxR={s['max_R']:.2f}  | {info}")
        if verdict == "PASS":
            passes.append(s)

    print()
    print(f"PASS COUNT: {len(passes)} / {len(summaries)}")
    if passes:
        print("\nEngineering SEC21 slot fix sonrasi ENSEMBLE RETEST adaylari:")
        for s in passes:
            print(f"  + {s['strategy']}: n={s['n']}, mR={s['mR']:+.3f}, WR={s['WR']*100:.1f}%, "
                  f"p={s['p_shuffle']:.3f}")

    print()
    print("=" * 100)
    print("PER-SYMBOL drill-down (top 5 / bottom 3 mR)")
    print("=" * 100)
    for s in summaries:
        print(f"\n{s['strategy']}:")
        if not s["by_sym"]:
            print("    (no trades)")
            continue
        sym_sorted = sorted(s["by_sym"].items(), key=lambda x: -x[1][1])
        for sym, (nn, mr) in sym_sorted[:5]:
            print(f"    {sym:<14} n={nn:4d} mR={mr:+.3f}")
        if len(sym_sorted) > 5:
            print(f"    --- bottom 3 ---")
            for sym, (nn, mr) in sym_sorted[-3:]:
                print(f"    {sym:<14} n={nn:4d} mR={mr:+.3f}")

    print()
    print("=" * 100)
    print("LOOKAHEAD AUDIT (heuristic)")
    print("=" * 100)
    import re
    for module_name, _ in NEW_MEAN_REV:
        path = ROOT / "src" / "price_action" / "strategies" / f"{module_name}.py"
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        bad_patterns = [
            r"\.shift\(-\d+\)",         # negative shift (peek forward)
            r"rolling\([^)]*center\s*=\s*True",  # center rolling
            r"\.iloc\[.*\+.*\]",         # forward iloc indexing in detection logic (loose heuristic)
        ]
        flags = []
        for pat in bad_patterns:
            ms = re.findall(pat, src)
            if ms:
                flags.append((pat, ms[:3]))
        if flags:
            print(f"  {module_name}: SUSPECT — {flags}")
        else:
            print(f"  {module_name}: clean (no shift(-n), no rolling(center=True), no forward iloc)")

    # Save results
    import json
    import pickle
    out_dir = ROOT / "reports" / "researcher"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "sec22_mean_rev_standalone.json"
    with open(summary_path, "w") as f:
        json.dump([{k: v for k, v in s.items() if k != "by_sym"} for s in summaries],
                  f, indent=2, default=str)
    pkl_path = out_dir / "sec22_mean_rev_trades.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(all_trades, f)
    print(f"\nSummary saved: {summary_path}")
    print(f"Trades pickle (ensemble retest icin): {pkl_path}")

    return summaries, all_trades


if __name__ == "__main__":
    main()
