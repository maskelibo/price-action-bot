"""Combo-A: brooks 8-FX across THREE sizing modes on the IDENTICAL engine + trades.

Modes (all share the same upstream-admitted trade list + same R outcomes):
  1) compounding    : risk_d = equity * 1%        (baseline, scales with equity)
  2) fixed_notional : risk_d = $100 fixed          (1% of initial 10k, never scales)
  3) rebased_risk   : risk_d = anchor_equity * 1%, anchor reset MONTHLY but CAPPED at
                      2x initial-capital-implied anchor (i.e. risk dollar capped so a
                      single explosive run cannot compound path into the millions).

Engine logic is the byte-identical faithful_replay from brooks_8fx_monthly_breakdown,
parameterised by a risk-dollar function. DD breakers + margin gating use the SAME
equity the engine tracks (so accounting stays self-consistent per mode).

Honest framing: NO iid MC. Same trades, same order, only the $-per-R sizing differs.
"""
from __future__ import annotations
import os, sys, pickle
from pathlib import Path
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yaml
from datetime import timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from price_action.backtest.lab import production_replay
from scripts.brooks_8fx_honest_cap import risk_parity_trades, apply_net_usd_cap, build_cfg

RISK_PCT = 0.01
NET_USD_CAP = 3
GROSS_CAP = 6
INIT = 10_000.0
FIXED_RISK = INIT * RISK_PCT          # $100
REBASE_CAP_MULT = 2.0                  # risk-anchor capped at 2x initial -> max $200 risk/trade


def make_risk_fn(mode):
    """Return f(equity, anchor) -> risk_dollar. anchor = monthly-rebased equity."""
    if mode == "compounding":
        return lambda equity, anchor: equity * RISK_PCT
    if mode == "fixed_notional":
        return lambda equity, anchor: FIXED_RISK
    if mode == "rebased_risk":
        # risk = anchor*1% but anchor capped at REBASE_CAP_MULT * INIT
        cap_anchor = REBASE_CAP_MULT * INIT
        return lambda equity, anchor: min(anchor, cap_anchor) * RISK_PCT
    raise ValueError(mode)


def faithful_replay(filtered, cfg, mode):
    """Byte-identical to brooks_8fx_monthly_breakdown.faithful_replay EXCEPT risk_d
    is supplied by make_risk_fn(mode). monthly_anchor doubles as risk rebase anchor."""
    risk_fn = make_risk_fn(mode)
    filtered = sorted(filtered, key=lambda t: t["entry_ts"])
    equity = cash = cfg.initial_capital
    open_pos = []
    eq_curve = [cfg.initial_capital]
    ledger = []
    daily_anchor = weekly_anchor = monthly_anchor = cfg.initial_capital
    first = filtered[0]["entry_ts"]
    last_d, last_w, last_m = first.date(), first.isocalendar()[1], first.month
    blocked_until = None
    last_entry = {}
    peak_equity = cfg.initial_capital
    lev = cfg.leverage

    def close_due(now):
        nonlocal cash, equity, peak_equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                peak_equity = max(peak_equity, equity)
                eq_curve.append(equity)
                ledger.append({
                    "entry_ts": p["entry_ts"], "exit_ts": p["exit_ts"],
                    "symbol": p["symbol"], "side": p["side"], "R": p["R"],
                    "pnl": pnl, "win": pnl > 0, "entry_equity": p["entry_equity"],
                    "risk_d": p["risk"], "equity_after": equity,
                })
            else:
                still.append(p)
        open_pos[:] = still

    for t in filtered:
        close_due(t["entry_ts"])
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue
        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).total_seconds() < cfg.same_symbol_side_cooldown_days * 86400.0:
            continue
        cd, cw, cm = t["entry_ts"].date(), t["entry_ts"].isocalendar()[1], t["entry_ts"].month
        if cd != last_d: daily_anchor = equity; last_d = cd
        if cw != last_w: weekly_anchor = equity; last_w = cw
        if cm != last_m: monthly_anchor = equity; last_m = cm
        if blocked_until and t["entry_ts"] < blocked_until:
            continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= cfg.daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=getattr(cfg, "daily_halt_days", 1)); continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= cfg.weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=getattr(cfg, "weekly_halt_days", 7)); continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= cfg.monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=getattr(cfg, "monthly_halt_days", 30)); continue
        if len(open_pos) >= cfg.max_concurrent:
            continue
        risk_d = risk_fn(equity, monthly_anchor)
        notional = risk_d / sl_pct
        margin = notional / lev
        if margin > cash:
            continue
        cash -= margin
        last_entry[key] = t["entry_ts"]
        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"], "margin": margin,
            "notional": notional, "risk": risk_d, "R": t["R"], "symbol": t["symbol"],
            "side": t["side"], "sl_pct": sl_pct, "entry_equity": equity,
        })
    if open_pos:
        last = max(p["exit_ts"] for p in open_pos)
        close_due(last + timedelta(seconds=1))
    return pd.DataFrame(ledger), eq_curve, equity


def continuous_max_dd(eq_curve):
    peak = eq_curve[0]; mdd = 0.0
    for v in eq_curve:
        peak = max(peak, v)
        dd = (v - peak) / peak if peak > 0 else 0.0
        mdd = min(mdd, dd)
    return mdd * 100.0


def monthly_table(led):
    led = led.sort_values("exit_ts").reset_index(drop=True)
    led["ym"] = pd.to_datetime(led["exit_ts"], utc=True).dt.to_period("M")
    months = pd.period_range("2020-01", "2025-12", freq="M")
    eq_idx = led[["exit_ts", "equity_after"]].copy()
    eq_idx["exit_ts"] = pd.to_datetime(eq_idx["exit_ts"], utc=True)
    rows = []
    prev_end = INIT
    for m in months:
        m_end = (m + 1).to_timestamp().tz_localize("UTC")
        mt = led[led["ym"] == m]
        n = len(mt)
        closed_le = eq_idx[eq_idx["exit_ts"] < m_end]
        end_eq = closed_le["equity_after"].iloc[-1] if len(closed_le) else prev_end
        start_eq = prev_end
        roi = (end_eq - start_eq) / start_eq * 100 if start_eq else float("nan")
        sumR = float(mt["R"].sum()) if n else 0.0
        seq = [start_eq] + list(mt.sort_values("exit_ts")["equity_after"].values)
        peak = seq[0]; mdd = 0.0
        for v in seq:
            peak = max(peak, v); dd = (v - peak) / peak if peak > 0 else 0.0
            mdd = min(mdd, dd)
        rows.append({"month": str(m), "n": n, "sumR": sumR, "roi": roi,
                     "mdd": mdd * 100, "end_eq": end_eq})
        prev_end = end_eq
    return pd.DataFrame(rows)


def main():
    d = pickle.load(open("/tmp/rt_trades.pkl", "rb"))
    trades, selected = d["trades"], d["selected"]
    raw = yaml.safe_load((ROOT / "configs" / "risk_forex.yaml").read_text())
    cfg = build_cfg(raw, max_concurrent=GROSS_CAP).with_overrides(risk_pct=RISK_PCT)
    pooled = risk_parity_trades(trades, selected)
    admitted = apply_net_usd_cap(pooled, NET_USD_CAP, gross_cap=GROSS_CAP)

    # validate compounding vs canonical
    canon = production_replay(admitted, cfg)
    results = {}
    for mode in ["compounding", "fixed_notional", "rebased_risk"]:
        led, eq, final = faithful_replay(admitted, cfg, mode)
        results[mode] = {"led": led, "eq": eq, "final": final,
                         "tbl": monthly_table(led),
                         "maxdd": continuous_max_dd(eq)}
    cf = results["compounding"]["final"]
    print(f"VALIDATION compounding: canon={canon.final_equity:.2f} mine={cf:.2f} "
          f"diff={abs(canon.final_equity-cf):.4f} trades={len(results['compounding']['led'])}")

    pickle.dump({m: {"tbl": results[m]["tbl"], "eq": results[m]["eq"],
                     "final": results[m]["final"], "maxdd": results[m]["maxdd"],
                     "sumR": float(results[m]["led"]["R"].sum())}
                 for m in results}, open("/tmp/combo_a.pkl", "wb"))

    # ---- summary table ----
    print("\n=== MODE COMPARISON (monthly ROI distribution, 72 months) ===")
    hdr = f"{'mode':<16}{'final$':>14}{'x':>7}{'sumR':>8}{'meanROI%':>9}{'medROI%':>9}{'stdROI%':>9}{'negM':>5}{'worstM%':>9}{'MaxDD%':>9}{'Sharpe':>8}"
    print(hdr); print("-" * len(hdr))
    summ = {}
    for m in ["compounding", "fixed_notional", "rebased_risk"]:
        tbl = results[m]["tbl"]
        roi = tbl["roi"].replace([np.inf, -np.inf], np.nan).dropna()
        active = tbl[tbl["n"] > 0]
        roi_a = active["roi"]
        sharpe = roi_a.mean() / roi_a.std() * np.sqrt(12) if roi_a.std() > 0 else float("nan")
        neg = int((active["roi"] < 0).sum())
        summ[m] = {"final": results[m]["final"], "sumR": float(results[m]["led"]["R"].sum()),
                   "mean": roi_a.mean(), "med": roi_a.median(), "std": roi_a.std(),
                   "neg": neg, "worst": roi_a.min(), "maxdd": results[m]["maxdd"], "sharpe": sharpe}
        print(f"{m:<16}{results[m]['final']:>14,.0f}{results[m]['final']/INIT:>7.1f}"
              f"{summ[m]['sumR']:>8.0f}{roi_a.mean():>9.2f}{roi_a.median():>9.2f}{roi_a.std():>9.2f}"
              f"{neg:>5}{roi_a.min():>9.1f}{results[m]['maxdd']:>9.1f}{sharpe:>8.2f}")

    # ---- the false-loss months ----
    print("\n=== FALSE-LOSS MONTHS (sumR>0 in compounding but ROI<=0) ===")
    cmp_tbl = results["compounding"]["tbl"].set_index("month")
    false_months = cmp_tbl[(cmp_tbl["sumR"] > 0) & (cmp_tbl["roi"] <= 0) & (cmp_tbl["n"] > 0)].index.tolist()
    print(f"detected {len(false_months)}: {false_months}\n")
    h = f"{'month':<10}{'n':>4}{'sumR':>7} | {'CMP roi%':>9}{'CMP mdd%':>9} | {'FIX roi%':>9}{'FIX mdd%':>9} | {'REB roi%':>9}{'REB mdd%':>9}"
    print(h); print("-" * len(h))
    ft = {m: results[m]["tbl"].set_index("month") for m in results}
    for mo in false_months:
        c, f, r = ft["compounding"].loc[mo], ft["fixed_notional"].loc[mo], ft["rebased_risk"].loc[mo]
        print(f"{mo:<10}{int(c['n']):>4}{c['sumR']:>7.1f} | {c['roi']:>9.2f}{c['mdd']:>9.2f} | "
              f"{f['roi']:>9.2f}{f['mdd']:>9.2f} | {r['roi']:>9.2f}{r['mdd']:>9.2f}")

    # all negative months count by mode for context
    print("\n=== NEG-MONTH ROSTER (active months only) ===")
    for m in ["compounding", "fixed_notional", "rebased_risk"]:
        tbl = results[m]["tbl"]; act = tbl[tbl["n"] > 0]
        negs = act[act["roi"] < 0]
        truel = negs[negs["sumR"] < 0]
        print(f"{m:<16} neg-months={len(negs):>2}  of-which-true(sumR<0)={len(truel):>2}  "
              f"false(sumR>0)={len(negs)-len(truel):>2}")


if __name__ == "__main__":
    main()
