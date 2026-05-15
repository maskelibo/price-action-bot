"""SEC23 — rsi2_extreme_fade OOS Hold-Out Validation (2024-01-01 -> 2025-05-14).

Goal: SEC22'de "rsi=5/ema=150/lb=3" config 27-config grid'inden seçildi (best mR=+0.144,
p=0.045). Selection bias riski yüksek. Bu sprint:

  Phase 1: SELECTED config (rsi=5, ema=150, lb=3) OOS hold-out (2024-2025) test.
  Phase 2: TUM 27 config OOS hold-out -> selected config OOS'ta da en iyi mi?
           Bonferroni alpha = 0.05/27 = 0.001852 (selection bias gate)
  Phase 3: HARD / SOFT / RED gate decision.
  Phase 4: JSON + Markdown rapor.

Causal design:
  - Full OHLCV yüklenir (2021-05 -> 2026-05) -> warmup (EMA200) için
  - Strategy bütün signalleri üretir
  - Trade filtreleme: 2024-01-01 <= entry_ts <= 2025-05-14
  - Cooldown / EMA causality bozulmaz (strategy iç state)

HARD PASS koşulları (hepsi gerekli):
  - OOS n >= 100
  - OOS mR >= +0.10
  - OOS shuffle p < 0.05
  - OOS WR >= 0.42
  - Bonferroni-corrected p < 0.001852
  - max_R < 10

SOFT PASS: HARD'tan 1 madde eksik
RED: 2+ madde fail veya OOS mR < +0.05
"""
from __future__ import annotations

import json
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

# OOS hold-out window
OOS_START = pd.Timestamp("2024-01-01", tz="UTC")
OOS_END   = pd.Timestamp("2025-05-14", tz="UTC")

# Selected ("best") SEC22 config — selection bias canary
SELECTED = {"rsi": 5.0, "ema": 150, "lb": 3}

# Grid (same as SEC22)
GRID_RSI = [5.0, 10.0, 15.0]
GRID_EMA = [150, 200, 300]
GRID_LB  = [3, 5, 7]
N_CONFIGS = len(GRID_RSI) * len(GRID_EMA) * len(GRID_LB)  # 27
BONFERRONI_ALPHA = 0.05 / N_CONFIGS                         # 0.001852

# Shuffle baseline: 50 perm Phase 1; 200 perm Phase 2 (gate alpha cok kucuk)
N_PERM_OOS_FOCUS = 2000  # SELECTED config — fine-grained p
N_PERM_GRID      = 1000  # 27-config grid — yeterli alpha=0.00185 çözünürlüğü için


def _gather_rsi2(rsi_thresh=10.0, ema_period=200, lookback=5,
                 start_dt=None, end_dt=None):
    """Run rsi2_extreme_fade on 11-sym universe with optional entry_ts filter.

    start_dt / end_dt: only keep trades whose entry_ts is in [start_dt, end_dt].
    """
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.rsi2_extreme_fade import (
        RSI2ExtremeFadeStrategy, _default_manifest,
    )
    from scripts.run_real_backtest import _load_symbol_ohlcv

    m = _default_manifest()
    for p in m.signals.patterns:
        if p.id == "rsi2_long":
            p.params["rsi_oversold"] = rsi_thresh
            p.params["ema_trend_period"] = ema_period
            p.params["low_lookback"] = lookback
        elif p.id == "rsi2_short":
            p.params["rsi_overbought"] = 100.0 - rsi_thresh
            p.params["ema_trend_period"] = ema_period
            p.params["high_lookback"] = lookback
    strategy = RSI2ExtremeFadeStrategy(m)

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
                # OOS filter — must be in window
                if start_dt is not None and entry_ts < start_dt:
                    continue
                if end_dt is not None and entry_ts > end_dt:
                    continue
                hold_d = (exit_ts - entry_ts).days
                R_raw = float(t["realized_r_multiple"])
                # SEC22 honest clip: hold>60d capped at +1R (avoid runner fantasy)
                R = R_raw if hold_d <= 60 else min(R_raw, 1.0)
                out.append({
                    "entry_ts": entry_ts, "exit_ts": exit_ts, "hold_d": hold_d,
                    "R": R, "R_raw": R_raw, "symbol": sym, "side": str(t["side"]),
                })
        except Exception as ex:
            print(f"   [WARN] {sym} skipped: {ex}", file=sys.stderr)
            continue
    return out


def _stats(trades, n_perm=200, seed=42):
    if not trades:
        return None
    Rs = np.array([t["R"] for t in trades], dtype=float)
    n_long = sum(1 for t in trades if t["side"] == "long")
    n_short = sum(1 for t in trades if t["side"] == "short")
    # shuffle (sign-flip null: H0 = trades have no directional edge)
    rng = np.random.default_rng(seed)
    obs = float(Rs.sum())
    null_sums = []
    for _ in range(n_perm):
        signs = rng.choice([-1, 1], size=len(Rs))
        null_sums.append((Rs * signs).sum())
    null_arr = np.array(null_sums)
    p = float((null_arr >= obs).mean())
    # one-sided exact, but with finite n_perm we add 1/(n+1) smoothing
    p_smooth = float(((null_arr >= obs).sum() + 1) / (n_perm + 1))
    return {
        "n": len(trades),
        "mR": float(Rs.mean()),
        "WR": float((Rs > 0).mean()),
        "max_R": float(Rs.max()),
        "min_R": float(Rs.min()),
        "median_R": float(np.median(Rs)),
        "std_R": float(Rs.std()),
        "n_long": n_long, "n_short": n_short,
        "p": p,
        "p_smooth": p_smooth,
        "hold_median": float(np.median([t["hold_d"] for t in trades])),
        "hold_mean": float(np.mean([t["hold_d"] for t in trades])),
        "sum_R": float(Rs.sum()),
    }


def phase1_selected_config_oos():
    print("=" * 100)
    print("PHASE 1 — SELECTED CONFIG OOS HOLD-OUT")
    print(f"  Config: rsi={SELECTED['rsi']}, ema={SELECTED['ema']}, lb={SELECTED['lb']}")
    print(f"  Window: {OOS_START.date()} -> {OOS_END.date()}")
    print(f"  Shuffle: {N_PERM_OOS_FOCUS} permutations")
    print("=" * 100)

    trades = _gather_rsi2(
        rsi_thresh=SELECTED["rsi"],
        ema_period=SELECTED["ema"],
        lookback=SELECTED["lb"],
        start_dt=OOS_START, end_dt=OOS_END,
    )
    s = _stats(trades, n_perm=N_PERM_OOS_FOCUS, seed=42)
    if s is None:
        print("   [ERROR] no trades in window")
        return None, []
    print(f"\n   n={s['n']}  mR={s['mR']:+.4f}  WR={s['WR']*100:.2f}%  "
          f"p={s['p']:.4f} (smooth={s['p_smooth']:.4f})")
    print(f"   max_R={s['max_R']:+.2f}  min_R={s['min_R']:+.2f}  median_R={s['median_R']:+.3f}  "
          f"std_R={s['std_R']:.3f}")
    print(f"   long={s['n_long']} short={s['n_short']}  hold_med={s['hold_median']:.0f}d "
          f"hold_mean={s['hold_mean']:.1f}d  sum_R={s['sum_R']:+.2f}")

    # Top 5 R inspection (artifact gate)
    if trades:
        print("\n   [Top 5 R trades — artifact check]")
        top5 = sorted(trades, key=lambda t: -t["R"])[:5]
        for t in top5:
            print(f"     {t['symbol']:<12} {t['side']:<5} R={t['R']:+.2f} (raw {t['R_raw']:+.2f})  "
                  f"hold={t['hold_d']}d  {t['entry_ts'].date()} -> {t['exit_ts'].date()}")

    # Per-symbol
    print("\n   [Per-symbol breakdown]")
    per_sym = {}
    for t in trades:
        per_sym.setdefault(t["symbol"], []).append(t["R"])
    for sym in SYMBOLS_11:
        Rs = per_sym.get(sym, [])
        if not Rs:
            print(f"     {sym:<12} n=0")
            continue
        Rs_arr = np.array(Rs)
        print(f"     {sym:<12} n={len(Rs):3d}  mR={Rs_arr.mean():+.3f}  "
              f"WR={(Rs_arr>0).mean()*100:5.1f}%  sumR={Rs_arr.sum():+.2f}")

    return s, trades


def phase2_grid_oos():
    print("\n" + "=" * 100)
    print(f"PHASE 2 — FULL 27-CONFIG GRID OOS (Bonferroni alpha={BONFERRONI_ALPHA:.5f})")
    print("=" * 100)

    sweep = []
    n_total = N_CONFIGS
    idx = 0
    for rsi_th in GRID_RSI:
        for ema_p in GRID_EMA:
            for lb in GRID_LB:
                idx += 1
                tr = _gather_rsi2(
                    rsi_thresh=rsi_th, ema_period=ema_p, lookback=lb,
                    start_dt=OOS_START, end_dt=OOS_END,
                )
                ss = _stats(tr, n_perm=N_PERM_GRID, seed=42) if tr else None
                row = {"rsi": rsi_th, "ema": ema_p, "lb": lb}
                if ss is not None:
                    row.update(ss)
                else:
                    row.update({"n": 0, "mR": 0.0, "WR": 0.0, "p": 1.0,
                                "p_smooth": 1.0, "max_R": 0.0, "min_R": 0.0,
                                "median_R": 0.0, "std_R": 0.0,
                                "n_long": 0, "n_short": 0,
                                "hold_median": 0.0, "hold_mean": 0.0, "sum_R": 0.0})
                bonf_pass = row["p_smooth"] < BONFERRONI_ALPHA
                row["bonf_pass"] = bool(bonf_pass)
                sweep.append(row)
                mark_sel = ("*SEL*" if (rsi_th == SELECTED["rsi"] and
                                         ema_p == SELECTED["ema"] and
                                         lb == SELECTED["lb"]) else "")
                print(f"   [{idx:>2}/{n_total}] rsi={rsi_th:>5.1f} ema={ema_p:>3d} lb={lb}  "
                      f"n={row['n']:>4d} mR={row['mR']:+.3f} WR={row['WR']*100:>5.1f}% "
                      f"p={row['p_smooth']:.4f} maxR={row['max_R']:>5.2f}  "
                      f"{'BONF' if bonf_pass else '----'} {mark_sel}")

    # Rank by mR
    sweep_sorted = sorted(sweep, key=lambda r: -r["mR"])
    print("\n   [TOP 5 by OOS mR]")
    for i, row in enumerate(sweep_sorted[:5]):
        mark = " *SEL*" if (row["rsi"] == SELECTED["rsi"] and row["ema"] == SELECTED["ema"]
                              and row["lb"] == SELECTED["lb"]) else ""
        print(f"     #{i+1}  rsi={row['rsi']:.1f} ema={row['ema']} lb={row['lb']}  "
              f"n={row['n']:4d} mR={row['mR']:+.3f} p={row['p_smooth']:.4f}{mark}")

    # Where does SELECTED rank?
    sel_idx = None
    for i, row in enumerate(sweep_sorted):
        if (row["rsi"] == SELECTED["rsi"] and row["ema"] == SELECTED["ema"]
                and row["lb"] == SELECTED["lb"]):
            sel_idx = i
            break
    print(f"\n   SELECTED config OOS rank: #{sel_idx + 1 if sel_idx is not None else 'NA'} / {n_total}")

    return sweep, sweep_sorted, sel_idx


def phase3_gate_decision(s_sel, sel_idx, sweep_sorted):
    print("\n" + "=" * 100)
    print("PHASE 3 — HARD / SOFT / RED GATE DECISION (SELECTED config)")
    print("=" * 100)

    if s_sel is None:
        print("   [ERROR] selected config produced no trades — RED")
        return {"decision": "RED", "fails": ["no trades"], "checks": {}}

    checks = {
        "n>=100":             {"value": s_sel["n"],          "thresh": 100,    "pass": s_sel["n"] >= 100},
        "mR>=+0.10":          {"value": s_sel["mR"],         "thresh": 0.10,   "pass": s_sel["mR"] >= 0.10},
        "p<0.05":             {"value": s_sel["p_smooth"],   "thresh": 0.05,   "pass": s_sel["p_smooth"] < 0.05},
        "WR>=0.42":           {"value": s_sel["WR"],         "thresh": 0.42,   "pass": s_sel["WR"] >= 0.42},
        "p<Bonferroni":       {"value": s_sel["p_smooth"],   "thresh": BONFERRONI_ALPHA,
                                "pass": s_sel["p_smooth"] < BONFERRONI_ALPHA},
        "max_R<10":           {"value": s_sel["max_R"],      "thresh": 10.0,   "pass": s_sel["max_R"] < 10.0},
    }

    fails = [k for k, v in checks.items() if not v["pass"]]
    n_fails = len(fails)
    print(f"\n   {'Gate':<22} {'Value':>12} {'Threshold':>12} {'Pass':>6}")
    print(f"   {'-'*22} {'-'*12} {'-'*12} {'-'*6}")
    for k, v in checks.items():
        thr_str = f"{v['thresh']}" if isinstance(v['thresh'], int) else f"{v['thresh']:.4f}"
        val_str = f"{v['value']:.4f}" if isinstance(v['value'], float) else f"{v['value']}"
        ok = "PASS" if v["pass"] else "FAIL"
        print(f"   {k:<22} {val_str:>12} {thr_str:>12} {ok:>6}")

    # Selection bias additional gate (Phase 2 ranking)
    sel_top3 = sel_idx is not None and sel_idx < 3
    selection_bias_concern = sel_idx is not None and sel_idx >= N_CONFIGS // 2  # bottom half
    print(f"\n   Selection bias check: SELECTED OOS rank #{sel_idx+1 if sel_idx is not None else 'NA'} / {N_CONFIGS}")
    print(f"     -> top 3?           {'YES' if sel_top3 else 'NO'}")
    print(f"     -> bottom half (selection bias evidence)? "
          f"{'YES' if selection_bias_concern else 'NO'}")

    # Hard / soft / red
    hard_fail_thresh_red = s_sel["mR"] < 0.05
    print(f"\n   Catastrophic mR<+0.05 check: mR={s_sel['mR']:+.4f}  "
          f"{'AUTO-RED' if hard_fail_thresh_red else 'ok'}")

    if hard_fail_thresh_red:
        decision = "RED"
        reason = f"OOS mR={s_sel['mR']:+.4f} < +0.05 catastrophic threshold"
    elif n_fails == 0:
        decision = "HARD PASS"
        reason = "all gates passed"
    elif n_fails == 1:
        decision = "SOFT PASS"
        reason = f"1 gate failed: {fails[0]}"
    else:
        decision = "RED"
        reason = f"{n_fails} gates failed: {', '.join(fails)}"

    # Auxiliary penalty: selection-bias bottom-half
    if decision in ("HARD PASS", "SOFT PASS") and selection_bias_concern:
        decision = "RED-SELECTION-BIAS"
        reason = f"selection bias detected: OOS rank {sel_idx+1}/{N_CONFIGS} (bottom half)"

    print(f"\n   ==> DECISION: {decision}")
    print(f"   ==> Reason: {reason}")

    return {
        "decision": decision,
        "reason": reason,
        "checks": checks,
        "fails": fails,
        "n_fails": n_fails,
        "selected_oos_rank": sel_idx + 1 if sel_idx is not None else None,
        "selected_oos_top3": sel_top3,
        "selection_bias_concern": selection_bias_concern,
    }


def main():
    print("\nSEC23 — rsi2_extreme_fade OOS Hold-Out Validation\n")

    # Phase 1
    s_sel, trades_sel = phase1_selected_config_oos()

    # Phase 2
    sweep, sweep_sorted, sel_idx = phase2_grid_oos()

    # Phase 3
    gate = phase3_gate_decision(s_sel, sel_idx, sweep_sorted)

    # Save JSON
    out_path = ROOT / "reports" / "researcher" / "sec23_rsi2_oos.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "sprint": "SEC23",
        "strategy": "rsi2_extreme_fade",
        "selected_config": SELECTED,
        "oos_window": {"start": str(OOS_START.date()), "end": str(OOS_END.date())},
        "symbols": SYMBOLS_11,
        "n_perm_focus": N_PERM_OOS_FOCUS,
        "n_perm_grid": N_PERM_GRID,
        "bonferroni_alpha": BONFERRONI_ALPHA,
        "selected_oos_stats": s_sel,
        "grid_oos": sweep,
        "grid_sorted_by_mR": sweep_sorted,
        "selected_oos_rank": sel_idx + 1 if sel_idx is not None else None,
        "gate": gate,
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\n   Saved JSON: {out_path}")


if __name__ == "__main__":
    main()
