"""Champion characterization — REUSES the deployed winner-let-run harness.

Reuses gather() (real BacktestEngine) + production_replay() from
scripts/crypto_winner_let_run_vsa_exit.py / src/price_action/backtest/lab.py.
Exit knobs = EXACT LIVE deploy (TP1 25%@1.0R, TP2 25%@1.5R, runner 50%,
trail mult 3.0, force-exit time/30 from entry). Universe = full 19-symbol
live config. sl_pct_min=0.025 (WIDESTOP). risk 0.5%. fees taker 55bps round
already inside config (fee_bps_per_trade=15 in replay) + we report 55bps & 0bps
at the per-trade R layer (engine fees taker 7.5bps/leg + slippage 5bps).

Usage: .venv/bin/python scripts/champion_characterize.py
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

# REUSE the deployed harness functions verbatim
import importlib.util
spec = importlib.util.spec_from_file_location(
    "wlr", str(ROOT / "scripts" / "crypto_winner_let_run_vsa_exit.py"))
wlr = importlib.util.module_from_spec(spec); spec.loader.exec_module(wlr)

from price_action.backtest.lab import ProductionConfig, production_replay
from dataclasses import replace

YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
# FULL LIVE 19-symbol universe (config strategy_portfolio.symbols)
SYMS = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","ADA/USDT","AVAX/USDT",
        "LINK/USDT","DOT/USDT","DOGE/USDT","XRP/USDT","ZEC/USDT","NEAR/USDT",
        "FIL/USDT","XLM/USDT","TRX/USDT","UNI/USDT","ATOM/USDT","AAVE/USDT","ALGO/USDT"]
SL_PCT_MIN = 0.025
RISK_PCT = 0.005

# EXACT deployed exit: live daemon = TP1 25%@1R + TP2 25%@1.5R + runner 50%,
# trail mult 3.0 (YAML stop_loss.trailing.multiplier, fixed 2026-05-29),
# force-exit from entry time/30 (winner-let-run, V1a_fe family).
DEPLOY_EXIT = dict(
    runner_trail_mult=3.0, trail_activate_stage=2,
    tp1_R=1.0, tp2_R=1.5, tp1_close_pct=0.25, tp2_close_pct=0.25,
    runner_force_exit_method="time", runner_force_exit_bars=30,
    force_exit_from_entry=True,
)


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


def daily_curve(res, cfg):
    """Calendar-day equity for HONEST daily Sharpe (no annualization inflation)."""
    eq = res.equity_curve or []; ts = res.entry_ts_list or []
    n = min(len(eq) - 1, len(ts))
    if n < 2:
        return pd.Series(dtype=float)
    stamps = pd.to_datetime(ts[:n], utc=True)
    df = pd.DataFrame({"ts": stamps, "eq": eq[1:n + 1]})
    df["d"] = df["ts"].dt.floor("D")
    de = df.groupby("d")["eq"].last()
    # reindex to full calendar range, ffill (flat days = no trade closes)
    full = pd.date_range(de.index.min(), de.index.max(), freq="D", tz="UTC")
    de = de.reindex(full).ffill().bfill()
    rets = de.pct_change().dropna()
    return rets


def main():
    print("Gathering trades through REAL engine (deployed exit) for 19 symbols...")
    all_trades = []
    per_sym_raw = {}
    for s in SYMS:
        t = wlr.gather(s, DEPLOY_EXIT)
        per_sym_raw[s] = t
        all_trades += t
        print(f"  {s:<10} raw_trades={len(t)}")

    cfg = build_cfg()

    # ===== headline edge: per-trade R at 55bps (engine, sl_pct>=0.025) and 0bps =====
    # The gather() trades already carry engine fees (taker 7.5bps/leg + 5bps slip
    # = ~55bps round-trip on a ~4% stop -> ~0.14R). For 0bps we re-derive a
    # fee-add-back is not analytically clean (exit path embeds fee), so we report
    # the 55bps engine R (deployed reality) and a 0bps APPROX by adding back the
    # per-trade round-trip fee in R units (fee_bps/leg*2 / sl_pct).
    widestop = [t for t in all_trades if wlr.sl_pct_of(t) >= SL_PCT_MIN]
    R55 = np.array([t["R"] for t in widestop])

    def fee_R(t):
        sp = wlr.sl_pct_of(t)
        # round-trip taker 7.5bps*2 + slippage 5bps*2 = 25bps total on notional
        return (0.00075 * 2 + 0.00005 * 2) / sp if sp > 0 else 0.0
    R0 = np.array([t["R"] + fee_R(t) for t in widestop])

    print("\n=== HEADLINE (widestop subset, n={}) ===".format(len(widestop)))
    print(f"mean_R @55bps(deployed) = {R55.mean():+.4f}   win% = {(R55>0).mean()*100:.1f}")
    print(f"mean_R @0bps(approx)    = {R0.mean():+.4f}   win% = {(R0>0).mean()*100:.1f}")
    print(f"fee drag (R)            = {(R0.mean()-R55.mean()):+.4f}")

    # ===== portfolio replay (deployed config) -> monthly, DD, daily Sharpe =====
    pool = sorted(widestop, key=lambda x: x["entry_ts"])
    res = production_replay(pool, cfg)
    mr = monthly_from_replay(res, cfg)
    dret = daily_curve(res, cfg)
    total_ret = (res.final_equity / cfg.initial_capital - 1.0) * 100.0
    dd = cont_dd(res.equity_curve)
    sharpe_daily = (dret.mean() / dret.std() * np.sqrt(365)) if dret.std() > 0 else 0.0
    sharpe_daily_raw = (dret.mean() / dret.std()) if dret.std() > 0 else 0.0

    print("\n=== PORTFOLIO REPLAY (deployed cfg, risk0.5%, sl>=0.025) ===")
    print(f"n_trades(replayed) = {res.trades}   total_return = {total_ret:+.1f}%")
    print(f"win_rate = {res.win_rate*100:.1f}%   avg_R = {res.avg_r:+.4f}")
    print(f"continuous-curve MaxDD = {dd:+.1f}%")
    print(f"calendar-day Sharpe (ann sqrt365) = {sharpe_daily:+.2f}   (raw daily = {sharpe_daily_raw:+.4f})")

    # ===== monthly ROI distribution =====
    print("\n=== MONTHLY ROI DISTRIBUTION ===")
    print(f"n_months = {len(mr)}   %positive = {(mr>0).mean()*100:.1f}%")
    print(f"mean = {mr.mean():+.2f}%   median = {mr.median():+.2f}%")
    print(f"best = {mr.max():+.2f}% ({mr.idxmax()})   worst = {mr.min():+.2f}% ({mr.idxmin()})")
    print(f"std = {mr.std():.2f}%   neg months = {(mr<0).sum()}/{len(mr)}")
    # yearly
    yr = mr.copy(); yr.index = [p.year for p in mr.index]
    print("\n  per-year mean monthly ROI:")
    for y in sorted(set(yr.index)):
        v = yr[yr.index == y]
        print(f"    {y}: mean={v.mean():+.2f}%/mo  n={len(v)}  pos={int((v>0).sum())}/{len(v)}")

    # ===== per-symbol breakdown =====
    print("\n=== PER-SYMBOL BREAKDOWN (widestop subset) ===")
    rows = []
    for s in SYMS:
        ws = [t for t in per_sym_raw[s] if wlr.sl_pct_of(t) >= SL_PCT_MIN]
        if not ws:
            rows.append((s, 0, 0.0, 0.0, 0.0)); continue
        Rs = np.array([t["R"] for t in ws])
        rows.append((s, len(Rs), float(Rs.mean()), float(Rs.sum()),
                     float((Rs > 0).mean() * 100)))
    rows.sort(key=lambda x: x[3], reverse=True)  # by total R contribution
    tot_sumR = sum(r[3] for r in rows)
    print(f"{'symbol':<10} {'n':>5} {'meanR':>7} {'sumR':>8} {'%contrib':>8} {'win%':>6}")
    for s, n, mR, sR, wp in rows:
        pct = sR / tot_sumR * 100 if tot_sumR else 0
        print(f"{s:<10} {n:>5} {mR:>+7.3f} {sR:>+8.1f} {pct:>+7.1f}% {wp:>5.1f}%")
    print(f"{'TOTAL':<10} {sum(r[1] for r in rows):>5} {'':>7} {tot_sumR:>+8.1f}")

    # ===== regime split (BTC realized-vol tertiles as proxy) =====
    print("\n=== REGIME SPLIT (BTC 30-bar realized vol tertiles on 15m) ===")
    import duckdb
    con = duckdb.connect(str(ROOT / "data" / "market.duckdb"), read_only=True)
    btc = con.execute("SELECT ts,close FROM ohlcv WHERE venue='binance' AND symbol='BTC/USDT' AND timeframe='15m' ORDER BY ts").fetchdf()
    con.close()
    btc["ts"] = pd.to_datetime(btc["ts"], utc=True)
    btc = btc.sort_values("ts").reset_index(drop=True)
    btc["ret"] = np.log(btc["close"]).diff()
    btc["rv"] = btc["ret"].rolling(96).std()  # ~1 day realized vol
    btc = btc.dropna(subset=["rv"])
    q1, q2 = btc["rv"].quantile([1/3, 2/3])
    def regime_of(ts):
        idx = btc["ts"].searchsorted(ts) - 1
        if idx < 0 or idx >= len(btc):
            return "unk"
        rv = btc["rv"].iloc[idx]
        return "low_vol(range)" if rv <= q1 else ("high_vol(trend)" if rv >= q2 else "mid_vol")
    reg = {"low_vol(range)": [], "mid_vol": [], "high_vol(trend)": [], "unk": []}
    for t in widestop:
        reg[regime_of(t["entry_ts"])].append(t["R"])
    for k in ["low_vol(range)", "mid_vol", "high_vol(trend)"]:
        a = np.array(reg[k])
        if len(a):
            print(f"  {k:<18} n={len(a):>6} meanR={a.mean():+.3f} sumR={a.sum():+.1f} win%={(a>0).mean()*100:.1f}")
        else:
            print(f"  {k:<18} (empty)")

    # dump machine-readable
    out = dict(
        headline=dict(n=len(widestop), mR_55=float(R55.mean()), mR_0=float(R0.mean()),
                      win=float((R55>0).mean()*100), total_ret=total_ret,
                      maxdd=dd, sharpe_daily_ann=float(sharpe_daily),
                      sharpe_daily_raw=float(sharpe_daily_raw), n_replay=res.trades),
        monthly=dict(n=len(mr), pos_pct=float((mr>0).mean()*100), mean=float(mr.mean()),
                     median=float(mr.median()), best=float(mr.max()), worst=float(mr.min()),
                     std=float(mr.std()), neg=int((mr<0).sum())),
        per_symbol=[dict(sym=s, n=n, mR=mR, sumR=sR, contrib_pct=(sR/tot_sumR*100 if tot_sumR else 0), win=wp)
                    for s, n, mR, sR, wp in rows],
        regime={k: dict(n=len(reg[k]), mR=float(np.mean(reg[k])) if reg[k] else 0,
                        sumR=float(np.sum(reg[k])) if reg[k] else 0)
                for k in ["low_vol(range)","mid_vol","high_vol(trend)"]},
        monthly_series={str(p): float(v) for p, v in mr.items()},
    )
    json.dump(out, open("/tmp/champion_char.json", "w"), indent=2)
    print("\n[dumped /tmp/champion_char.json]")


if __name__ == "__main__":
    main()
