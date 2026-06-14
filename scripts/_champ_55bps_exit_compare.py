"""55bps exit comparison — REUSES deployed gather()+production_replay() harness.

Runs the SAME vsa_climax_test entries (widestop sl_pct>=0.025, 19-symbol live
universe, 15m, full history) through THREE exits, each at 55bps round-trip AND
0bps for reference:

  1. BASELINE      — TP1 30%@1R / TP2 30%@1.5R / runner 40%, ATR-trail 1.5,
                     time-stop 30 bars (NOT from entry). The "validated edge".
  2. DEPLOYED_YAML — winner-let-run: TP1 25%@1R / TP2 25%@1.5R / runner 50%,
                     ATR-trail 3.0 + force-exit-from-entry time/30.
  3. LIVE_DAEMON   — hand-coded ~4% pct-trail from futures_daemon._desired_sl_price:
                     TP1 25%@1R / TP2 25%@1.5R / runner 50%, BE-lock + price-pct
                     trail 0.04 ACTIVATING FROM TP1(+1R), NO force-exit/time-stop.
                     Engine native equivalent: runner_trail_pct=0.04,
                     trail_activate_stage=1 (trail from TP1), runner_force_exit
                     atr_only/None. (peak*(1-pct) == ratcheted mark*(1-pct).)

FEE MODEL: engine charges taker on BOTH legs ((entry+exit)*q*taker) + entry-leg
slippage. To get a clean HONEST 55bps round-trip we set slippage_bps=0 and
taker=0.00275 (27.5bps/leg x 2 = 55bps round-trip). 0bps = taker 0, slip 0.

Usage: .venv/bin/python scripts/_champ_55bps_exit_compare.py
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

# ----- THREE exits as engine constructor knobs -----
EXITS = {
    "BASELINE": dict(
        runner_trail_mult=1.5, trail_activate_stage=2,
        tp1_R=1.0, tp2_R=1.5, tp1_close_pct=0.30, tp2_close_pct=0.30,
        runner_force_exit_method="time", runner_force_exit_bars=30,
        force_exit_from_entry=False),
    "DEPLOYED_YAML": dict(
        runner_trail_mult=3.0, trail_activate_stage=2,
        tp1_R=1.0, tp2_R=1.5, tp1_close_pct=0.25, tp2_close_pct=0.25,
        runner_force_exit_method="time", runner_force_exit_bars=30,
        force_exit_from_entry=True),
    "LIVE_DAEMON": dict(
        # price-pct trail 4% activating from TP1 (+1R); BE-lock at stage>=1;
        # NO time/force-exit (atr_only/None). runner_trail_pct overrides ATR mult.
        runner_trail_pct=0.04, runner_trail_mult=1.5, trail_activate_stage=1,
        tp1_R=1.0, tp2_R=1.5, tp1_close_pct=0.25, tp2_close_pct=0.25,
        runner_force_exit_method="atr_only", runner_force_exit_bars=None,
        force_exit_from_entry=False),
}

# ----- fee scenarios: (taker_per_leg, slippage_bps) -> round-trip bps -----
FEE_SCEN = {
    "55bps": dict(fees={"taker": 0.00275, "maker": -0.00010}, slippage_bps=0.0),  # 27.5*2=55
    "0bps":  dict(fees={"taker": 0.0,     "maker": 0.0},       slippage_bps=0.0),
}


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


def run_one(exit_name, exit_cfg, fee_name, fee_cfg, cfg):
    # set fee scenario on the reused harness, then gather (re-runs engine path)
    wlr.FEES = fee_cfg["fees"]
    wlr.SLIPPAGE_BPS = fee_cfg["slippage_bps"]
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
    return dict(
        exit=exit_name, fee=fee_name, n_widestop=len(widestop),
        n_replay=res.trades, mean_R=float(R.mean()), win=float((R > 0).mean() * 100),
        pos_mo=float((mr > 0).mean() * 100) if len(mr) else 0.0,
        mean_mo=float(mr.mean()) if len(mr) else 0.0,
        med_mo=float(mr.median()) if len(mr) else 0.0,
        n_mo=len(mr), neg_mo=int((mr < 0).sum()),
        sharpe_ann=sh_ann, sharpe_raw=sh_raw, maxdd=dd,
        best_mo=float(mr.max()) if len(mr) else 0.0,
        worst_mo=float(mr.min()) if len(mr) else 0.0,
        total_ret=(res.final_equity / cfg.initial_capital - 1.0) * 100.0,
        monthly={str(p): float(v) for p, v in mr.items()},
        R_top5_share=(float(R[R >= np.percentile(R, 95)].sum() / R[R > 0].sum() * 100)
                      if (R > 0).sum() > 0 else 0.0),
    )


def main():
    cfg = build_cfg()
    results = {}
    for ename, ecfg in EXITS.items():
        for fname, fcfg in FEE_SCEN.items():
            key = f"{ename}@{fname}"
            print(f"running {key} ...", flush=True)
            results[key] = run_one(ename, ecfg, fname, fcfg, cfg)
            r = results[key]
            print(f"  n={r['n_widestop']} replay={r['n_replay']} meanR={r['mean_R']:+.3f} "
                  f"win={r['win']:.1f}% pos_mo={r['pos_mo']:.1f}% mean_mo={r['mean_mo']:+.2f}% "
                  f"med_mo={r['med_mo']:+.2f}% DD={r['maxdd']:+.1f}% Sh={r['sharpe_ann']:+.2f}",
                  flush=True)

    print("\n========== 55bps COMPARISON TABLE ==========")
    hdr = f"{'exit':<14} {'fee':>6} {'%posMo':>7} {'meanMo':>8} {'medMo':>8} {'meanR':>7} {'win%':>6} {'Sharpe':>7} {'MaxDD':>8} {'trades':>7}"
    print(hdr)
    for k, r in results.items():
        print(f"{r['exit']:<14} {r['fee']:>6} {r['pos_mo']:>6.1f}% {r['mean_mo']:>+7.2f}% "
              f"{r['med_mo']:>+7.2f}% {r['mean_R']:>+7.3f} {r['win']:>5.1f}% "
              f"{r['sharpe_ann']:>+7.2f} {r['maxdd']:>+7.1f}% {r['n_replay']:>7}")

    json.dump(results, open("/tmp/champ_55bps.json", "w"), indent=2)
    print("\n[dumped /tmp/champ_55bps.json]")


if __name__ == "__main__":
    main()
