"""HYP-2026-06-02-exit-parity-vsa-widestop — REUSES deployed harness.

Backtest-only. Adds a runner force-exit / time-stop to the LIVE_DAEMON exit
(4% pct-trail + BE-lock + trail-from-TP1) and sweeps time-stop in {20,30,40}.
Compares vs (a) LIVE_DAEMON as-is (no time-stop, the +56.8%/mo artifact) and
(b) BASELINE (the validated honest edge).

Reuses scripts/crypto_winner_let_run_vsa_exit.py::gather() (real BacktestEngine)
+ src/price_action/backtest/lab.py::production_replay() VERBATIM. Same entries
(vsa_climax_test + widestop sl_pct>=0.025), same 19-symbol live universe, 15m
full history, risk 0.5%, live YAML mechanics. Primary fee = 55bps round-trip.

Usage: .venv/bin/python scripts/_champ_exit_parity_timestop.py
"""
from __future__ import annotations
import os, sys, json
from pathlib import Path
os.environ["PA_DUCKDB_READ_ONLY"] = "true"
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import importlib.util
spec = importlib.util.spec_from_file_location(
    "wlr", str(ROOT / "scripts" / "crypto_winner_let_run_vsa_exit.py"))
wlr = importlib.util.module_from_spec(spec); spec.loader.exec_module(wlr)

from price_action.backtest.lab import ProductionConfig, production_replay
from dataclasses import replace

YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
SYMS = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","ADA/USDT","AVAX/USDT",
        "LINK/USDT","DOT/USDT","DOGE/USDT","XRP/USDT","ZEC/USDT","NEAR/USDT",
        "FIL/USDT","XLM/USDT","TRX/USDT","UNI/USDT","ATOM/USDT","AAVE/USDT","ALGO/USDT"]
SL_PCT_MIN = 0.025
RISK_PCT = 0.005

# ---- LIVE_DAEMON exit base (§11 faithful approx) ----
LIVE_BASE = dict(
    runner_trail_pct=0.04, runner_trail_mult=1.5, trail_activate_stage=1,
    tp1_R=1.0, tp2_R=1.5, tp1_close_pct=0.25, tp2_close_pct=0.25,
    force_exit_from_entry=False)

EXITS = {
    # comparators
    "BASELINE": dict(
        runner_trail_mult=1.5, trail_activate_stage=2,
        tp1_R=1.0, tp2_R=1.5, tp1_close_pct=0.30, tp2_close_pct=0.30,
        runner_force_exit_method="time", runner_force_exit_bars=30,
        force_exit_from_entry=False),
    "LIVE_DAEMON_notimestop": {**LIVE_BASE,
        "runner_force_exit_method": "atr_only", "runner_force_exit_bars": None},
    # the variant under test: LIVE + runner time-stop, swept
    "LIVE_ts20": {**LIVE_BASE, "runner_force_exit_method": "time", "runner_force_exit_bars": 20},
    "LIVE_ts30": {**LIVE_BASE, "runner_force_exit_method": "time", "runner_force_exit_bars": 30},
    "LIVE_ts40": {**LIVE_BASE, "runner_force_exit_method": "time", "runner_force_exit_bars": 40},
}

# honest 55bps round-trip: taker 27.5bps/leg x2 = 55bps, slippage 0
FEE_55 = dict(fees={"taker": 0.00275, "maker": -0.00010}, slippage_bps=0.0)


def build_cfg():
    c = ProductionConfig.from_yaml(str(YAML))
    return replace(c, risk_pct=RISK_PCT, sl_pct_min=max(c.sl_pct_min, SL_PCT_MIN))


def cont_dd(eq):
    peak = eq[0]; mdd = 0.0
    for v in eq:
        peak = max(peak, v); mdd = min(mdd, (v - peak) / peak if peak > 0 else 0.0)
    return mdd * 100.0


def monthly_from_replay(res, cfg):
    eq = res.equity_curve or []; ts = res.entry_ts_list or []
    if len(eq) < 2 or not ts:
        return pd.Series(dtype=float)
    n = min(len(eq) - 1, len(ts))
    stamps = pd.to_datetime(ts[:n], utc=True)
    df = pd.DataFrame({"ts": stamps, "eq": eq[1:n + 1]})
    df["m"] = df["ts"].dt.to_period("M")
    me = df.groupby("m")["eq"].last()
    prev = me.shift(1, fill_value=cfg.initial_capital)
    return (me / prev - 1.0) * 100.0


def daily_sharpe(res):
    eq = res.equity_curve or []; ts = res.entry_ts_list or []
    n = min(len(eq) - 1, len(ts))
    if n < 2:
        return 0.0, 0.0
    stamps = pd.to_datetime(ts[:n], utc=True)
    df = pd.DataFrame({"ts": stamps, "eq": eq[1:n + 1]})
    df["d"] = df["ts"].dt.floor("D")
    de = df.groupby("d")["eq"].last()
    full = pd.date_range(de.index.min(), de.index.max(), freq="D", tz="UTC")
    de = de.reindex(full).ffill().bfill()
    rets = de.pct_change().dropna()
    if rets.std() <= 0:
        return 0.0, 0.0
    return float(rets.mean() / rets.std() * np.sqrt(365)), float(rets.mean() / rets.std())


def walk_forward(trades, cfg, train_yrs=3, test_mo=6, step_mo=3):
    """Walk-forward: count test windows with positive total return. Entries are the
    same across windows (exit fixed); we slice the trade pool by entry_ts and replay
    each TEST window independently. Returns (pos_windows, total_windows, detail)."""
    if not trades:
        return 0, 0, []
    pool = sorted(trades, key=lambda x: x["entry_ts"])
    t0 = pd.Timestamp(pool[0]["entry_ts"]); t1 = pd.Timestamp(pool[-1]["entry_ts"])
    detail = []; pos = 0; tot = 0
    test_start = t0 + pd.DateOffset(years=train_yrs)
    while test_start < t1:
        test_end = test_start + pd.DateOffset(months=test_mo)
        win = [t for t in pool if test_start <= pd.Timestamp(t["entry_ts"]) < test_end]
        if len(win) >= 20:
            res = production_replay(win, cfg)
            ret = (res.final_equity / cfg.initial_capital - 1.0) * 100.0
            tot += 1; pos += 1 if ret > 0 else 0
            detail.append((str(test_start.date()), str(test_end.date()), len(win), round(ret, 2)))
        test_start = test_start + pd.DateOffset(months=step_mo)
    return pos, tot, detail


def run_one(exit_name, exit_cfg, cfg):
    wlr.FEES = FEE_55["fees"]; wlr.SLIPPAGE_BPS = FEE_55["slippage_bps"]
    all_trades = []
    for s in SYMS:
        all_trades += wlr.gather(s, exit_cfg)
    widestop = [t for t in all_trades if wlr.sl_pct_of(t) >= SL_PCT_MIN]
    pool = sorted(widestop, key=lambda x: x["entry_ts"])
    R = np.array([t["R"] for t in widestop]) if widestop else np.array([0.0])
    res = production_replay(pool, cfg)
    mr = monthly_from_replay(res, cfg)
    dd = cont_dd(res.equity_curve)
    sh_ann, sh_raw = daily_sharpe(res)
    wins = R[R > 0]
    thr = np.percentile(R, 95)
    top5 = float(R[R >= thr].sum() / wins.sum() * 100) if wins.sum() > 0 else 0.0
    wf_pos, wf_tot, wf_detail = walk_forward(widestop, cfg)
    # median hold of runner phase proxy: median hold_h
    holds = [t.get("hold_h", 0) for t in widestop]
    return dict(
        exit=exit_name, n_widestop=len(widestop), n_replay=res.trades,
        mean_R=float(R.mean()), win=float((R > 0).mean() * 100),
        pos_mo=float((mr > 0).mean() * 100) if len(mr) else 0.0,
        mean_mo=float(mr.mean()) if len(mr) else 0.0,
        med_mo=float(mr.median()) if len(mr) else 0.0,
        n_mo=len(mr), neg_mo=int((mr < 0).sum()),
        sharpe_ann=sh_ann, sharpe_raw=sh_raw, maxdd=dd,
        best_mo=float(mr.max()) if len(mr) else 0.0,
        worst_mo=float(mr.min()) if len(mr) else 0.0,
        total_ret=(res.final_equity / cfg.initial_capital - 1.0) * 100.0,
        top5_share=top5, hold_med_h=float(np.median(holds)) if holds else 0.0,
        wf_pos=wf_pos, wf_tot=wf_tot, wf_detail=wf_detail,
        monthly={str(p): float(v) for p, v in mr.items()},
    )


def main():
    cfg = build_cfg()
    order = ["BASELINE", "LIVE_DAEMON_notimestop", "LIVE_ts20", "LIVE_ts30", "LIVE_ts40"]
    results = {}
    for ename in order:
        print(f"running {ename} @55bps ...", flush=True)
        r = run_one(ename, EXITS[ename], cfg)
        results[ename] = r
        print(f"  n={r['n_widestop']} replay={r['n_replay']} meanR={r['mean_R']:+.3f} "
              f"win={r['win']:.1f}% pos_mo={r['pos_mo']:.1f}% mean_mo={r['mean_mo']:+.2f}% "
              f"med_mo={r['med_mo']:+.2f}% DD={r['maxdd']:+.1f}% Sh={r['sharpe_ann']:+.2f} "
              f"top5={r['top5_share']:.1f}% WF={r['wf_pos']}/{r['wf_tot']} tot={r['total_ret']:+.0f}%",
              flush=True)

    print("\n========== EXIT-PARITY TIME-STOP TABLE (@55bps) ==========")
    hdr = (f"{'exit':<22} {'%posMo':>7} {'meanMo':>8} {'medMo':>8} {'meanR':>7} {'win%':>6} "
           f"{'Sharpe':>7} {'MaxDD':>8} {'top5%R':>7} {'WF+':>7} {'trades':>7} {'totRet%':>12}")
    print(hdr)
    for ename in order:
        r = results[ename]
        print(f"{r['exit']:<22} {r['pos_mo']:>6.1f}% {r['mean_mo']:>+7.2f}% {r['med_mo']:>+7.2f}% "
              f"{r['mean_R']:>+7.3f} {r['win']:>5.1f}% {r['sharpe_ann']:>+7.2f} {r['maxdd']:>+7.1f}% "
              f"{r['top5_share']:>6.1f}% {r['wf_pos']:>3}/{r['wf_tot']:<3} {r['n_replay']:>7} "
              f"{r['total_ret']:>+12.0f}")

    print("\n--- walk-forward detail (test windows, total return %) ---")
    for ename in order:
        r = results[ename]
        wins = ", ".join(f"{d[0]}:{d[3]:+.0f}%" for d in r["wf_detail"])
        print(f"{ename:<22} {r['wf_pos']}/{r['wf_tot']}  [{wins}]")

    json.dump(results, open("/tmp/champ_exit_parity_timestop.json", "w"), indent=2)
    print("\n[dumped /tmp/champ_exit_parity_timestop.json]")


if __name__ == "__main__":
    main()
