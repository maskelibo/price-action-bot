"""Sec25 — Track D Volume Microstructure standalone backtest.

Tests 4 pre-registered hypotheses:
  HYP-D1  vsa_sos_effort_up        (VSA SOS — long trend continuation)
  HYP-D2  vsa_sow_effort_down      (VSA SOW — short trend continuation)
  HYP-D3  vsa_bag_holding          (VSA absorption — long mean-reversion)
  HYP-D4  weis_wave_divergence     (Weis wave volume divergence — both)

Coverage: 11 sym x 5y x 1d. Honest clip hold>60d -> R<=1.0 (SEC19 dataset-end fix).

IS / OOS split (selection bias gate, SEC23 lesson):
  IS  = 2021-2023 (3y in-sample)
  OOS = 2024-01 → end (out-of-sample hold-out)

Hard gates (per hypothesis):
  n_min          = 200
  mR_min         = +0.10  (honest clip)
  WR_min         = 0.45
  shuffle_p_max  = 0.05   (n_perm=2000)
  max_R_max      = 10.0   (artifact gate)
  symout_dev_max = 0.30   (leave-one-symbol-out CV)
  per_sym_pos    = 6 / 11
  OOS_mR_min     = +0.05  (sign + magnitude check)

Bonferroni: 4 hypotheses × 9 grid cells = 36 tests. Default config tested
without grid sweep here (grid kept for future param tuning). Per-test alpha =
0.05 / 4 = 0.0125 if interpreting as 4 simultaneous hypothesis tests.
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

# Strategy list: (module, class, hypothesis_id)
STRATEGIES = [
    ("vsa_sos_effort_up",   "VSASoSEffortUpStrategy",     "HYP-D1"),
    ("vsa_sow_effort_down", "VSASoWEffortDownStrategy",   "HYP-D2"),
    ("vsa_bag_holding",     "VSABagHoldingStrategy",      "HYP-D3"),
    ("weis_wave_divergence","WeisWaveDivergenceStrategy", "HYP-D4"),
]

GATE = {
    "n_min": 200,
    "mR_min": 0.10,
    "WR_min": 0.45,
    "p_max": 0.05,
    "max_R_max": 10.0,
    "symout_max_dev": 0.30,
    "per_sym_pos_min": 6,
    "OOS_mR_min": 0.05,
}

OOS_START = pd.Timestamp("2024-01-01", tz="UTC")


def _verify_class_metadata(module_name: str):
    """Engineering SEC21 hook — STRATEGY_CLASS module-level metadata zorunlu."""
    try:
        mod = __import__(f"price_action.strategies.{module_name}",
                         fromlist=["STRATEGY_CLASS"])
        sc = getattr(mod, "STRATEGY_CLASS", None)
        return sc
    except Exception as e:
        return f"import-fail: {e}"


def _gather_one_strategy(module_name: str, class_name: str, universe):
    """Run one strategy on all symbols, return list of trade dicts."""
    from price_action.backtest.engine import BacktestEngine
    from scripts.run_real_backtest import _load_symbol_ohlcv

    mod = __import__(f"price_action.strategies.{module_name}",
                     fromlist=[class_name, "_default_manifest"])
    cls = getattr(mod, class_name)
    manifest_fn = getattr(mod, "_default_manifest", None)
    if not manifest_fn:
        raise RuntimeError(f"{module_name} has no _default_manifest")
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


def _split_is_oos(trades):
    """Split by entry_ts: IS=before OOS_START, OOS=after.

    Handle tz-aware/naive timestamp mismatch gracefully.
    """
    def _safe_lt(ts_a, ts_b):
        # Coerce both to tz-naive for comparison if mismatched
        if ts_a.tzinfo is not None and ts_b.tzinfo is None:
            return ts_a.tz_localize(None) < ts_b
        if ts_a.tzinfo is None and ts_b.tzinfo is not None:
            return ts_a < ts_b.tz_localize(None)
        return ts_a < ts_b
    is_trades = [t for t in trades if _safe_lt(t["entry_ts"], OOS_START)]
    oos_trades = [t for t in trades if not _safe_lt(t["entry_ts"], OOS_START)]
    return is_trades, oos_trades


def _gate_check(s_is, s_oos, sym_cv):
    """8-gate hard check (IS + OOS)."""
    fails = []
    if s_is["n"] < GATE["n_min"]:
        fails.append(f"n_IS={s_is['n']}<{GATE['n_min']}")
    if s_is["WR"] < GATE["WR_min"]:
        fails.append(f"WR_IS={s_is['WR']*100:.1f}<{GATE['WR_min']*100:.0f}")
    if s_is["mR"] < GATE["mR_min"]:
        fails.append(f"mR_IS={s_is['mR']:+.3f}<{GATE['mR_min']}")
    if s_is["p_shuffle"] is None or s_is["p_shuffle"] >= GATE["p_max"]:
        pval = f"{s_is['p_shuffle']:.4f}" if s_is["p_shuffle"] is not None else "None"
        fails.append(f"p_IS={pval}>={GATE['p_max']}")
    if s_is["max_R"] >= GATE["max_R_max"]:
        fails.append(f"maxR_IS={s_is['max_R']:.2f}>={GATE['max_R_max']}")
    pos_count = sum(1 for sym, (nn, mr) in s_is["by_sym"].items() if mr > 0)
    if pos_count < GATE["per_sym_pos_min"]:
        fails.append(f"per_sym_pos_IS={pos_count}<{GATE['per_sym_pos_min']}")
    if sym_cv and sym_cv.get("max_abs_dev_pct", 0) > GATE["symout_max_dev"] * 100:
        fails.append(f"symout_dev_IS={sym_cv['max_abs_dev_pct']:.1f}%>{GATE['symout_max_dev']*100:.0f}%")
    # OOS gate
    if s_oos["n"] > 0:
        if s_oos["mR"] < GATE["OOS_mR_min"]:
            fails.append(f"mR_OOS={s_oos['mR']:+.3f}<{GATE['OOS_mR_min']}")
        # Sign consistency
        if s_is["mR"] > 0 and s_oos["mR"] < 0:
            fails.append("sign_flip_IS_pos_OOS_neg")
    else:
        fails.append("n_OOS=0")
    return ("PASS" if not fails else "FAIL"), fails


def _audit_lookahead(module_name):
    import re
    path = ROOT / "src" / "price_action" / "strategies" / f"{module_name}.py"
    if not path.exists():
        return ["FILE NOT FOUND"]
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
    return flags


def _process_strategy(module_name, class_name, hyp_id):
    print(f"\n{'=' * 100}\n[{hyp_id}] {module_name}  (class: {class_name})\n{'=' * 100}")

    sc = _verify_class_metadata(module_name)
    print(f"[METADATA] STRATEGY_CLASS = {sc!r}")

    # Lookahead audit
    flags = _audit_lookahead(module_name)
    if flags:
        print(f"[LOOKAHEAD] SUSPECT - {flags}")
    else:
        print(f"[LOOKAHEAD] clean")

    print(f"\n[GATHERING TRADES] symbols={len(SYMBOLS_11)}")
    trades = _gather_one_strategy(module_name, class_name, SYMBOLS_11)
    print(f"  Total trades: {len(trades)}")

    # Full sample summary
    s_full = _summary(trades, module_name)
    is_trades, oos_trades = _split_is_oos(trades)
    s_is = _summary(is_trades, module_name + "_IS")
    s_oos = _summary(oos_trades, module_name + "_OOS")

    print(f"\n[FULL  ] n={s_full['n']}  mR={s_full['mR']:+.3f} (raw {s_full['mR_raw']:+.3f})  WR={s_full['WR']*100:.1f}%  "
          f"p={s_full['p_shuffle']}  max_R={s_full['max_R']:.2f}  long={s_full['n_long']} short={s_full['n_short']}")
    print(f"[IS    ] n={s_is['n']}  mR={s_is['mR']:+.3f}  WR={s_is['WR']*100:.1f}%  "
          f"p={s_is['p_shuffle']}  max_R={s_is['max_R']:.2f}")
    print(f"[OOS   ] n={s_oos['n']}  mR={s_oos['mR']:+.3f}  WR={s_oos['WR']*100:.1f}%  "
          f"p={s_oos['p_shuffle']}  max_R={s_oos['max_R']:.2f}")

    sym_cv = _symout_cv(is_trades, SYMBOLS_11)
    if sym_cv:
        print(f"  Symbol-out CV (IS): max |dev|={sym_cv['max_abs_dev_pct']:.1f}%")
        worst = sorted(sym_cv['details'], key=lambda x: -abs(x[1]))[:3]
        for sym, d in worst:
            print(f"    exclude {sym:<14}: dev={d*100:+.1f}%")

    print(f"\n[PER-SYMBOL IS]")
    for sym in SYMBOLS_11:
        if sym in s_is["by_sym"]:
            nn, mr = s_is["by_sym"][sym]
            marker = "+" if mr > 0 else "-"
            print(f"  {marker} {sym:<14} n={nn:4d} mR={mr:+.3f}")
        else:
            print(f"    {sym:<14} (no IS trades)")
    pos_count = sum(1 for sym, (nn, mr) in s_is["by_sym"].items() if mr > 0)
    print(f"  TOTAL POSITIVE SYM (IS): {pos_count}/{len(SYMBOLS_11)}")

    print(f"\n[PER-YEAR IS+OOS]")
    for yr in sorted(s_full["by_year"].keys()):
        nn, mr = s_full["by_year"][yr]
        marker = "+" if mr > 0 else "-"
        oos_marker = " (OOS)" if yr >= 2024 else " (IS)"
        print(f"  {marker} {yr}{oos_marker}  n={nn:4d}  mR={mr:+.3f}")

    if trades:
        trades_sorted = sorted(trades, key=lambda t: -t["R"])
        print(f"\n[TOP 3 / BOTTOM 3 TRADE AUDIT]")
        print("  Top 3:")
        for t in trades_sorted[:3]:
            print(f"    {t['symbol']:<10} {t['side']:<5} R={t['R']:+.2f} (raw {t['R_raw']:+.2f}) "
                  f"hold={t['hold_d']:3d}d entry={t['entry_ts'].date()}")
        print("  Bottom 3:")
        for t in trades_sorted[-3:]:
            print(f"    {t['symbol']:<10} {t['side']:<5} R={t['R']:+.2f} (raw {t['R_raw']:+.2f}) "
                  f"hold={t['hold_d']:3d}d entry={t['entry_ts'].date()}")

    verdict, fails = _gate_check(s_is, s_oos, sym_cv)
    info = ", ".join(fails) if fails else "ALL_OK"
    print(f"\n[HARD GATE] {verdict} - {info}")

    return {
        "hyp_id": hyp_id,
        "module": module_name,
        "strategy_class": sc,
        "n_full": s_full["n"],
        "mR_full": s_full["mR"],
        "WR_full": s_full["WR"],
        "p_full": s_full["p_shuffle"],
        "max_R": s_full["max_R"],
        "n_artifact": s_full["n_artifact"],
        "n_IS": s_is["n"],
        "mR_IS": s_is["mR"],
        "WR_IS": s_is["WR"],
        "p_IS": s_is["p_shuffle"],
        "n_OOS": s_oos["n"],
        "mR_OOS": s_oos["mR"],
        "WR_OOS": s_oos["WR"],
        "p_OOS": s_oos["p_shuffle"],
        "symout_dev": sym_cv.get("max_abs_dev_pct") if sym_cv else None,
        "per_sym_pos_IS": pos_count,
        "long_mR": s_full["long_mR"],
        "short_mR": s_full["short_mR"],
        "n_long": s_full["n_long"],
        "n_short": s_full["n_short"],
        "by_year": {str(yr): {"n": v[0], "mR": v[1]} for yr, v in s_full["by_year"].items()},
        "by_sym_IS": {sym: {"n": v[0], "mR": v[1]} for sym, v in s_is["by_sym"].items()},
        "verdict": verdict,
        "fails": fails,
    }, trades


def main():
    print("=" * 100)
    print("SEC25 - Track D Volume Microstructure  4 hypotheses standalone backtest")
    print("Coverage: 11 sym x 5y x 1d.  IS=2021-2023, OOS=2024-2025.")
    print("Honest clip: hold>60d -> R<=1.0.")
    print("=" * 100)

    results = []
    all_trades = {}
    for module, cls_name, hyp_id in STRATEGIES:
        try:
            res, trades = _process_strategy(module, cls_name, hyp_id)
            results.append(res)
            all_trades[module] = trades
        except Exception as exc:
            print(f"\n[FATAL] {hyp_id} {module}: {exc}")
            import traceback
            traceback.print_exc()
            results.append({"hyp_id": hyp_id, "module": module, "verdict": "ERROR",
                            "fails": [str(exc)]})

    # ===== Summary table =====
    print("\n" + "=" * 100)
    print("SEC25 SUMMARY TABLE")
    print("=" * 100)
    print(f"{'HYP':<8}{'Strategy':<24}{'n_IS':>6}{'mR_IS':>9}{'WR_IS':>8}"
          f"{'p_IS':>9}{'n_OOS':>7}{'mR_OOS':>9}{'WR_OOS':>8}{'Verdict':>10}")
    print("-" * 110)
    for r in results:
        if r.get("verdict") == "ERROR":
            print(f"{r['hyp_id']:<8}{r['module'][:22]:<24} {' ERROR ' + ', '.join(r.get('fails', [])[:1])[:50]}")
            continue
        print(f"{r['hyp_id']:<8}{r['module'][:22]:<24}"
              f"{r.get('n_IS', 0):>6}"
              f"{r.get('mR_IS', 0):+9.3f}"
              f"{r.get('WR_IS', 0)*100:>7.1f}%"
              f"{r.get('p_IS', 0) if r.get('p_IS') is not None else 999:>9.4f}"
              f"{r.get('n_OOS', 0):>7}"
              f"{r.get('mR_OOS', 0):+9.3f}"
              f"{r.get('WR_OOS', 0)*100:>7.1f}%"
              f"{r.get('verdict', '?'):>10}")
    print("-" * 110)

    # Save full results
    import json
    import pickle
    out_dir = ROOT / "reports" / "researcher"
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_path = out_dir / "sec25_volume_standalone.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSummary saved: {summary_path}")

    pkl_path = out_dir / "sec25_volume_trades.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(all_trades, f)
    print(f"Trades pickle:  {pkl_path}")

    # Bonferroni reminder
    print(f"\n[BONFERRONI] 4 hypotheses tested: per-test alpha = 0.05/4 = 0.0125")
    print(f"             For PASS, p_shuffle should be < 0.0125 (Bonferroni-conservative).")

    return results, all_trades


if __name__ == "__main__":
    main()
