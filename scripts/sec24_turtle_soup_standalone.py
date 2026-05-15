"""Sec24 — Turtle Soup 20D failed-breakout fade standalone backtest.

Pre-registered hipotez:
  memory/researcher/hypotheses/2026-05-14-turtle-soup-20day-failed-breakout-v2.md

Hard gates (anyone fail -> RED):
  n >= 200
  WR >= 0.45
  mR >= +0.10
  shuffle p < 0.05
  max_R < 10
  Symbol-out CV max |dev| < 30%
  Per-symbol pozitif mR: en az 6/11

Coverage: 11 sym x 5y x 1d. Honest clip hold > 60d -> R <= 1.0
(SEC19 dataset-end artifact lesson).

Orthogonality kontrolu:
  Correlation kontrolleri donchian_breakout, failed_bo_bos_reclaim,
  equal_highs_sweep stratejilerinin trades.pkl dosyalari ile yapilir
  (varsa). Bu dosyalar yoksa skip.
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

STRATEGY_MODULE = "turtle_soup_20d"
STRATEGY_CLASS = "TurtleSoup20DStrategy"

GATE = {
    "n_min": 200,
    "mR_min": 0.10,
    "WR_min": 0.45,
    "p_max": 0.05,
    "max_R_max": 10.0,
    "symout_max_dev": 0.30,
    "per_sym_pos_min": 6,  # of 11
}


def _verify_class_metadata():
    """Engineering SEC21 hook — STRATEGY_CLASS module-level metadata zorunlu."""
    try:
        mod = __import__(f"price_action.strategies.{STRATEGY_MODULE}",
                         fromlist=["STRATEGY_CLASS"])
        sc = getattr(mod, "STRATEGY_CLASS", None)
        return sc
    except Exception as e:
        return f"import-fail: {e}"


def _gather(universe):
    from price_action.backtest.engine import BacktestEngine
    from scripts.run_real_backtest import _load_symbol_ohlcv

    mod = __import__(f"price_action.strategies.{STRATEGY_MODULE}",
                     fromlist=[STRATEGY_CLASS, "_default_manifest"])
    cls = getattr(mod, STRATEGY_CLASS)
    manifest_fn = getattr(mod, "_default_manifest", None)
    if not manifest_fn:
        raise RuntimeError(f"{STRATEGY_MODULE} has no _default_manifest")
    strategy = cls(manifest_fn())

    out = []
    for sym in universe:
        try:
            df = _load_symbol_ohlcv(sym, tf="1d")
            if df is None or df.empty:
                print(f"   SKIP {sym}: empty df")
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
                # Honest clip: hold > 60d -> R<=1.0 (SEC19 lesson)
                R = R_raw if hold_d <= 60 else min(R_raw, 1.0)
                out.append({
                    "entry_ts": entry_ts,
                    "exit_ts": exit_ts,
                    "hold_d": hold_d,
                    "R": R,
                    "R_raw": R_raw,
                    "symbol": sym,
                    "side": str(t["side"]),
                    "strategy": STRATEGY_MODULE,
                    "entry_price": float(t["entry_price"]),
                    "initial_sl": float(t["initial_sl"]),
                })
        except Exception as exc:
            print(f"   ERROR {sym}: {exc}")
            import traceback
            traceback.print_exc()
            continue
    return out


def _shuffle_p(trades, n_perm=2000, seed=42):
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
                "n_artifact": 0, "hold_d_median": 0, "hold_d_p90": 0,
                "by_sym": {}, "by_year": {}, "long_mR": 0.0, "short_mR": 0.0}
    Rs = np.array([t["R"] for t in trades], dtype=float)
    Rs_raw = np.array([t["R_raw"] for t in trades], dtype=float)
    holds = np.array([t["hold_d"] for t in trades])
    p = _shuffle_p(trades)
    n_long = sum(1 for t in trades if t["side"] == "long")
    n_short = sum(1 for t in trades if t["side"] == "short")

    long_R = [t["R"] for t in trades if t["side"] == "long"]
    short_R = [t["R"] for t in trades if t["side"] == "short"]

    by_sym = {}
    for t in trades:
        by_sym.setdefault(t["symbol"], []).append(t["R"])

    by_year = {}
    for t in trades:
        yr = t["entry_ts"].year
        by_year.setdefault(yr, []).append(t["R"])

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
        "long_mR": float(np.mean(long_R)) if long_R else 0.0,
        "short_mR": float(np.mean(short_R)) if short_R else 0.0,
        "p_shuffle": p,
        "n_artifact": int((Rs_raw > 10.0).sum()),
        "hold_d_median": int(np.median(holds)),
        "hold_d_p90": int(np.percentile(holds, 90)),
        "by_sym": {sym: (len(v), float(np.mean(v))) for sym, v in by_sym.items()},
        "by_year": {yr: (len(v), float(np.mean(v))) for yr, v in by_year.items()},
    }


def _symout_cv(trades, universe):
    """Leave-one-symbol-out CV: max |dev| of mR vs full mR."""
    if not trades:
        return None
    Rs_full = np.array([t["R"] for t in trades], dtype=float)
    mR_full = float(Rs_full.mean()) if len(Rs_full) else 0.0
    if abs(mR_full) < 1e-6:
        return None
    devs = []
    for sym_excl in universe:
        Rs = np.array([t["R"] for t in trades if t["symbol"] != sym_excl], dtype=float)
        if len(Rs) == 0:
            continue
        mR = float(Rs.mean())
        dev = (mR - mR_full) / abs(mR_full)
        devs.append((sym_excl, dev))
    if not devs:
        return None
    max_abs = max(abs(d[1]) for d in devs)
    return {"max_abs_dev_pct": float(max_abs * 100.0),
            "details": devs}


def _gate_check(s, sym_cv):
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
    # Per-sym positive count
    pos_count = sum(1 for sym, (nn, mr) in s["by_sym"].items() if mr > 0)
    if pos_count < GATE["per_sym_pos_min"]:
        fails.append(f"per_sym_pos={pos_count}<{GATE['per_sym_pos_min']}")
    # Symbol-out CV
    if sym_cv and sym_cv.get("max_abs_dev_pct", 0) > GATE["symout_max_dev"] * 100:
        fails.append(f"symout_dev={sym_cv['max_abs_dev_pct']:.1f}%>{GATE['symout_max_dev']*100:.0f}%")
    return ("PASS" if not fails else "FAIL"), fails


def _orthogonality_check(my_trades, universe):
    """Trade-day overlap with donchian_breakout / failed_bo_bos_reclaim / equal_highs_sweep.

    Pure trade-date overlap proxy for trigger correlation. Uses entry_ts.date set
    intersection as a fast surrogate for trigger-time correlation.
    """
    if not my_trades:
        return {}
    out = {}
    my_dates = {(t["symbol"], t["entry_ts"].date()) for t in my_trades}

    # Try to load other strategy trade pickles if exist
    other_paths = {
        "donchian_breakout": ROOT / "reports" / "researcher" / "_pa_donchian_trades.pkl",
        "failed_bo_bos_reclaim": ROOT / "reports" / "researcher" / "_pa_failed_bo_trades.pkl",
        "equal_highs_sweep": ROOT / "reports" / "researcher" / "_pa_equal_highs_trades.pkl",
    }

    # If no pickle available, compute on-the-fly proxy using same engine
    # (lightweight: just gather trade-date set for the other strategy)
    from price_action.backtest.engine import BacktestEngine
    from scripts.run_real_backtest import _load_symbol_ohlcv

    for other_name, _path in other_paths.items():
        try:
            mod = __import__(f"price_action.strategies.{other_name}",
                            fromlist=["_default_manifest"])
            # Strategy class name guessing
            cls_name = None
            for attr in dir(mod):
                if attr.endswith("Strategy") and not attr.startswith("_"):
                    cls_name = attr
                    break
            if cls_name is None:
                out[other_name] = None
                continue
            cls = getattr(mod, cls_name)
            manifest_fn = getattr(mod, "_default_manifest", None)
            if manifest_fn is None:
                out[other_name] = None
                continue
            strategy = cls(manifest_fn())
            other_dates = set()
            for sym in universe:
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
                    other_dates.add((sym, pd.Timestamp(t["entry_ts"]).date()))

            if not other_dates:
                out[other_name] = {"n_my": len(my_dates), "n_other": 0, "overlap": 0, "jaccard": 0.0}
                continue
            overlap = len(my_dates & other_dates)
            union = len(my_dates | other_dates)
            jaccard = overlap / union if union > 0 else 0.0
            out[other_name] = {
                "n_my": len(my_dates),
                "n_other": len(other_dates),
                "overlap": overlap,
                "jaccard": float(jaccard),
            }
        except Exception as exc:
            print(f"   ORTHOGONALITY ERROR {other_name}: {exc}")
            out[other_name] = None
    return out


def main():
    print("=" * 100)
    print("Sec24 - Turtle Soup 20D failed-breakout fade standalone backtest")
    print("Coverage: 11 sym x 5y x 1d  | Honest clip hold>60d -> R<=1.0")
    print("=" * 100)
    print()

    # Verify STRATEGY_CLASS metadata
    print("[METADATA AUDIT - Engineering SEC21 hook]")
    sc = _verify_class_metadata()
    if sc != "mean_reversion":
        print(f"  FAIL - STRATEGY_CLASS = {sc!r} (expected 'mean_reversion')")
        return
    print(f"  PASS - STRATEGY_CLASS = 'mean_reversion'")
    print()

    print("[GATHERING TRADES...]")
    trades = _gather(SYMBOLS_11)
    print(f"  Total trades: {len(trades)}")
    print()

    s = _summary(trades, STRATEGY_MODULE)

    print("=" * 100)
    print("STANDALONE STATISTICS")
    print("=" * 100)
    print(f"  n={s['n']}  mR={s['mR']:+.3f}  (raw mR={s['mR_raw']:+.3f})  WR={s['WR']*100:.1f}%")
    print(f"  long n={s['n_long']:4d} mR={s['long_mR']:+.3f}  |  short n={s['n_short']:4d} mR={s['short_mR']:+.3f}")
    print(f"  median_R={s['median_R']:+.3f}  max_R={s['max_R']:.2f}  sumR={s['sumR']:+.2f}")
    print(f"  p_shuffle={s['p_shuffle']:.4f}  hold_median={s['hold_d_median']}d hold_p90={s['hold_d_p90']}d")
    print(f"  artifact_n (R_raw>10)={s['n_artifact']}")
    print()

    # Symbol-out CV
    sym_cv = _symout_cv(trades, SYMBOLS_11)
    if sym_cv:
        print(f"  Symbol-out CV: max |dev|={sym_cv['max_abs_dev_pct']:.1f}%")
        worst = sorted(sym_cv['details'], key=lambda x: -abs(x[1]))[:3]
        for sym, d in worst:
            print(f"    exclude {sym:<14}: dev={d*100:+.1f}%")
    print()

    # Per-symbol
    print("[PER-SYMBOL BREAKDOWN]")
    if s["by_sym"]:
        for sym in SYMBOLS_11:
            if sym in s["by_sym"]:
                nn, mr = s["by_sym"][sym]
                marker = "+" if mr > 0 else "-"
                print(f"  {marker} {sym:<14} n={nn:4d}  mR={mr:+.3f}")
            else:
                print(f"    {sym:<14} (no trades)")
    pos_count = sum(1 for sym, (nn, mr) in s["by_sym"].items() if mr > 0)
    print(f"  TOTAL POSITIVE SYM: {pos_count}/{len(SYMBOLS_11)}")
    print()

    # Per-year
    print("[PER-YEAR BREAKDOWN]")
    for yr in sorted(s["by_year"].keys()):
        nn, mr = s["by_year"][yr]
        marker = "+" if mr > 0 else "-"
        print(f"  {marker} {yr}  n={nn:4d}  mR={mr:+.3f}")
    print()

    # Top 5 / Bottom 5 trade audit (artifact check)
    print("[TOP 5 / BOTTOM 5 TRADE AUDIT - artifact check]")
    trades_sorted = sorted(trades, key=lambda t: -t["R"])
    print("  Top 5 (R desc):")
    for t in trades_sorted[:5]:
        print(f"    {t['symbol']:<10} side={t['side']:<5}  R={t['R']:+.2f}  (raw {t['R_raw']:+.2f})  "
              f"hold={t['hold_d']:3d}d  entry={t['entry_ts'].date()}  exit={t['exit_ts'].date()}")
    print("  Bottom 5 (R asc):")
    for t in trades_sorted[-5:]:
        print(f"    {t['symbol']:<10} side={t['side']:<5}  R={t['R']:+.2f}  (raw {t['R_raw']:+.2f})  "
              f"hold={t['hold_d']:3d}d  entry={t['entry_ts'].date()}  exit={t['exit_ts'].date()}")
    print()

    # Hard gate check
    print("=" * 100)
    print(f"HARD GATE - n>={GATE['n_min']}, mR>={GATE['mR_min']}, WR>{GATE['WR_min']*100:.0f}%, "
          f"p<{GATE['p_max']}, max_R<{GATE['max_R_max']}, "
          f"per_sym_pos>={GATE['per_sym_pos_min']}, symout_dev<{GATE['symout_max_dev']*100:.0f}%")
    print("=" * 100)
    verdict, fails = _gate_check(s, sym_cv)
    info = ", ".join(fails) if fails else "ALL_OK"
    print(f"  [{verdict}] {info}")
    print()

    # Orthogonality (optional, can be slow)
    print("[ORTHOGONALITY - trigger-date overlap with related strategies]")
    print("  (computing... may take a minute)")
    orth = _orthogonality_check(trades, SYMBOLS_11)
    for other_name, info in orth.items():
        if info is None:
            print(f"  {other_name}: SKIP (load error)")
        else:
            print(f"  {other_name}: n_my={info['n_my']} n_other={info['n_other']} "
                  f"overlap={info['overlap']} jaccard={info['jaccard']:.3f}")
    print()

    # Lookahead audit (heuristic)
    print("=" * 100)
    print("LOOKAHEAD AUDIT (heuristic)")
    print("=" * 100)
    import re
    path = ROOT / "src" / "price_action" / "strategies" / f"{STRATEGY_MODULE}.py"
    if path.exists():
        src = path.read_text(encoding="utf-8")
        bad_patterns = [
            r"\.shift\(-\d+\)",
            r"rolling\([^)]*center\s*=\s*True",
        ]
        flags = []
        for pat in bad_patterns:
            ms = re.findall(pat, src)
            if ms:
                flags.append((pat, ms[:3]))
        if flags:
            print(f"  {STRATEGY_MODULE}: SUSPECT - {flags}")
        else:
            print(f"  {STRATEGY_MODULE}: clean (no shift(-n), no rolling(center=True))")
    print()

    # Save results
    import json
    import pickle
    out_dir = ROOT / "reports" / "researcher"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "sec24_turtle_soup_standalone.json"
    summary_dump = {k: v for k, v in s.items() if k not in ("by_sym", "by_year")}
    summary_dump["by_sym"] = {sym: {"n": v[0], "mR": v[1]} for sym, v in s["by_sym"].items()}
    summary_dump["by_year"] = {str(yr): {"n": v[0], "mR": v[1]} for yr, v in s["by_year"].items()}
    summary_dump["gate"] = {"verdict": verdict, "fails": fails}
    summary_dump["orthogonality"] = orth
    if sym_cv:
        summary_dump["sym_cv"] = {"max_abs_dev_pct": sym_cv["max_abs_dev_pct"]}
    with open(summary_path, "w") as f:
        json.dump(summary_dump, f, indent=2, default=str)
    pkl_path = out_dir / "sec24_turtle_soup_trades.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(trades, f)
    print(f"\nSummary saved: {summary_path}")
    print(f"Trades pickle:  {pkl_path}")

    return s, trades, verdict, fails


if __name__ == "__main__":
    main()
