"""V3 low-correlation ENTRY diversifier hunt vs LIVE champion (vsa_climax_test 15m WIDESTOP).

GOAL: find a deployable ENTRY signal that ADDS to the champion via diversification —
positive net edge AND |rho(daily_pnl, vsa)| < 0.30. Marginal portfolio Sharpe is the real metric.

CANDIDATES (structurally orthogonal to VSA-climax = volume-climax + spread reversal):
  - vsa_climax_test   (BASELINE — the live champion ENTRY; same WIDESTOP sl_pct>=0.025 gate)
  - donchian_breakout (55-bar trend-continuation breakout; fires when price makes new extreme — opposite condition to climax-fade)
  - session_orb       (00:00 UTC opening-range breakout; time-based momentum)

HONESTY:
  - REAL BacktestEngine, 55bps round-trip (taker=0.00275/leg) + 5bps slippage.
  - WIDESTOP sl_pct>=0.025 fee-erosion gate applied to ALL entries (same as champion).
  - DAILY PnL series built from trades (PnL booked at exit_ts.date()) — this is the
    champion's correlation reference (task spec), NOT monthly.
  - calendar-day Sharpe (honest, ann sqrt(365)) from the daily PnL series.
  - Correlation: Pearson on daily PnL (overlapping trading days only).
  - Marginal portfolio Sharpe: champion-alone vs equal-risk champion+candidate combined daily PnL.
  - Shuffle baseline: log-return permutation null; mean_R must beat null.
  - Walk-forward: yearly OOS slices.

Read-only DB. No daemon touch.
Usage: .venv/bin/python scripts/_v3_lowcorr_entry_hunt.py
"""
from __future__ import annotations

import os, sys, warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ.setdefault("PA_LOG_QUIET", "1")
os.environ["PA_DUCKDB_READ_ONLY"] = "true"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

import numpy as np
import pandas as pd
import duckdb

from price_action.backtest.engine import BacktestEngine
from price_action.strategies.vsa_climax_test import VSAClimaxTestStrategy, _default_manifest as vsa_mf
from price_action.strategies.donchian_breakout import DonchianBreakoutStrategy
from price_action.strategies.session_orb import SessionORBStrategy, _default_manifest as orb_mf
from price_action.strategies.base import StrategyManifest

# Full LIVE champion 19-symbol universe
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
           "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT",
           "ZEC/USDT", "NEAR/USDT", "FIL/USDT", "XLM/USDT", "TRX/USDT",
           "UNI/USDT", "ATOM/USDT", "AAVE/USDT", "ALGO/USDT"]
TF = "15m"
START = datetime(2021, 5, 16, tzinfo=timezone.utc)
END = datetime(2026, 6, 1, tzinfo=timezone.utc)
CAP = 10_000.0
SL_PCT_MIN = 0.025  # WIDESTOP fee-erosion gate (champion parity)

DB = ROOT / "data" / "market.duckdb"
_CACHE: dict[tuple, pd.DataFrame] = {}


def loader(symbol, tf, start, end):
    key = (symbol, tf)
    if key not in _CACHE:
        con = duckdb.connect(str(DB), read_only=True)
        df = con.execute(
            "SELECT ts, open, high, low, close, volume FROM ohlcv "
            "WHERE symbol=? AND timeframe=? ORDER BY ts", [symbol, tf]).fetchdf()
        con.close()
        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
        _CACHE[key] = df
    df = _CACHE[key]
    if df.empty:
        return df
    s = pd.Timestamp(start); e = pd.Timestamp(end)
    out = df[(df["ts"] >= s) & (df["ts"] <= e)].copy()
    out["symbol"] = symbol; out["timeframe"] = tf; out["venue"] = "binance"
    return out


def donchian_manifest():
    raw = {
        "name": "donchian_breakout", "version": "15m-rival-1.0",
        "description": "Donchian 55-bar breakout, 15m, squeeze off, ER>=0.30.",
        "signals": {
            "patterns": [{"id": "donchian_breakout", "enabled": True, "weight": 1.0,
                          "params": {"entry_period": 55, "exit_period": 20,
                                     "squeeze_required": False}}],
            "filters": {"atr_min_pct": 0.003, "kaufman_er_min": 0.30},
            "confluence": {"method": "weighted_sum", "min_score": 1.0}},
        "risk": {"take_profit": {"method": "r_multiple", "primary_R": 1.5},
                 "stop_loss": {"method": "donchian", "atr_buffer": 0.0}},
        "backtest": {"warmup_bars": 60, "initial_capital_usdt": CAP}}
    return StrategyManifest.model_validate(raw)


def build(name):
    if name == "vsa_climax_test":
        return VSAClimaxTestStrategy(vsa_mf())
    if name == "donchian_breakout":
        return DonchianBreakoutStrategy(donchian_manifest())
    if name == "session_orb":
        return SessionORBStrategy(orb_mf())
    raise ValueError(name)


def apply_widestop(trades: pd.DataFrame) -> pd.DataFrame:
    """WIDESTOP fee-erosion gate: keep only trades whose initial stop distance >= 2.5%
    of entry price. Mirrors the champion's sl_pct>=0.025 gate."""
    if trades.empty:
        return trades
    cols = set(trades.columns)
    if {"entry_price", "initial_sl"}.issubset(cols):
        sl_pct = (trades["entry_price"] - trades["initial_sl"]).abs() / trades["entry_price"]
        return trades[sl_pct >= SL_PCT_MIN].copy()
    if "initial_sl_pct" in cols:
        return trades[trades["initial_sl_pct"].abs() >= SL_PCT_MIN].copy()
    return trades  # no sl columns -> cannot gate (report ungated)


def daily_pnl(trades: pd.DataFrame) -> pd.Series:
    """Daily realized-PnL series (booked at exit date). Champion's corr reference."""
    if trades.empty:
        return pd.Series(dtype=float)
    t = trades.copy()
    t["d"] = pd.to_datetime(t["exit_ts"], utc=True).dt.normalize()
    return t.groupby("d")["realized_pnl_usdt"].sum().sort_index()


def cal_sharpe(dp: pd.Series, full_idx: pd.DatetimeIndex) -> float:
    """Calendar-day Sharpe: reindex onto every calendar day (0 on no-trade days)."""
    if dp.empty:
        return 0.0
    s = dp.reindex(full_idx, fill_value=0.0)
    mu, sd = s.mean(), s.std(ddof=1)
    return float(mu / sd * np.sqrt(365.0)) if sd > 0 else 0.0


def run(name, start=START, end=END, universe=None, taker=0.00275, slip=5.0, gate=True):
    eng = BacktestEngine()
    res = eng.run(build(name), universe or SYMBOLS, start=start, end=end,
                  fees={"taker": taker, "maker": -0.00010}, slippage_bps=slip,
                  initial_capital=CAP, timeframe=TF, ohlcv_provider=loader)
    tr = res.trades
    if gate:
        tr = apply_widestop(tr)
    return tr


def stats(tr: pd.DataFrame, full_idx):
    if tr.empty:
        return dict(n=0, mean_R=0.0, win=0.0, sharpe=0.0, maxdd=0.0, total_pnl=0.0)
    dp = daily_pnl(tr)
    eq = CAP + dp.reindex(full_idx, fill_value=0.0).cumsum()
    peak = eq.cummax(); dd = ((eq - peak) / peak).min() * 100
    return dict(
        n=len(tr),
        mean_R=float(tr["realized_r_multiple"].mean()),
        win=float((tr["realized_r_multiple"] > 0).mean()) * 100,
        sharpe=cal_sharpe(dp, full_idx),
        maxdd=float(dd),
        total_pnl=float(tr["realized_pnl_usdt"].sum()),
        dp=dp)


def shuffle_mean_R(name, seed=7):
    rng = np.random.default_rng(seed)

    def shuf_loader(symbol, tf, start, end):
        df = loader(symbol, tf, start, end)
        if df.empty:
            return df
        df = df.copy()
        c = df["close"].to_numpy()
        rets = np.diff(np.log(c)); rng.shuffle(rets)
        new_c = c[0] * np.exp(np.concatenate([[0.0], np.cumsum(rets)]))
        scale = new_c / c
        for col in ("open", "high", "low"):
            df[col] = df[col].to_numpy() * scale
        df["close"] = new_c
        return df

    eng = BacktestEngine()
    res = eng.run(build(name), SYMBOLS, start=START, end=END,
                  fees={"taker": 0.00275, "maker": -0.00010}, slippage_bps=5.0,
                  initial_capital=CAP, timeframe=TF, ohlcv_provider=shuf_loader)
    tr = apply_widestop(res.trades)
    return float(tr["realized_r_multiple"].mean()) if not tr.empty else 0.0


def main():
    full_idx = pd.date_range(START.replace(tzinfo=timezone.utc), END, freq="D", tz="UTC")
    names = ["vsa_climax_test", "donchian_breakout", "session_orb"]
    print("=" * 84, flush=True)
    print(f"V3 LOW-CORR ENTRY HUNT — {TF} | {len(SYMBOLS)} sym | {START.date()}..{END.date()} | 55bps | WIDESTOP sl>={SL_PCT_MIN}", flush=True)
    print("=" * 84, flush=True)

    R = {}
    print("\n[1] EDGE (full sample, 55bps, WIDESTOP-gated)", flush=True)
    h = f"{'strategy':<20}{'n':>7}{'mean_R':>9}{'win%':>7}{'calSharpe':>11}{'maxDD%':>9}{'totalPnL$':>12}"
    print(h); print("-" * len(h), flush=True)
    for nm in names:
        tr = run(nm)
        st = stats(tr, full_idx)
        R[nm] = st
        print(f"{nm:<20}{st['n']:>7}{st['mean_R']:>9.3f}{st['win']:>7.1f}{st['sharpe']:>11.2f}{st['maxdd']:>9.1f}{st['total_pnl']:>12.0f}", flush=True)

    print("\n[2] SHUFFLE BASELINE (null — mean_R should collapse)", flush=True)
    print(f"{'strategy':<20}{'real_R':>9}{'shuf_R':>9}{'verdict':>16}", flush=True)
    for nm in names:
        real = R[nm]["mean_R"]; shuf = shuffle_mean_R(nm)
        v = "BEATS NULL" if real > shuf + 0.02 else "FAILS(~null)"
        print(f"{nm:<20}{real:>9.3f}{shuf:>9.3f}{v:>16}", flush=True)

    print("\n[3] WALK-FORWARD (yearly OOS, mean_R, 55bps WIDESTOP)", flush=True)
    years = [(2021, 2022), (2022, 2023), (2023, 2024), (2024, 2025), (2025, 2026)]
    print(f"{'strategy':<20}" + "".join(f"{y[0]:>9}" for y in years) + f"{'neg':>6}", flush=True)
    for nm in names:
        cells, neg = [], 0
        for ys, ye in years:
            s = datetime(ys, 5, 16, tzinfo=timezone.utc); e = datetime(ye, 5, 16, tzinfo=timezone.utc)
            tr = run(nm, start=s, end=e)
            mr = float(tr["realized_r_multiple"].mean()) if not tr.empty else 0.0
            cells.append(mr); neg += (mr < 0)
        print(f"{nm:<20}" + "".join(f"{c:>9.3f}" for c in cells) + f"{neg:>4}/{len(years)}", flush=True)

    print("\n[4] DAILY-PnL CORRELATION vs CHAMPION (vsa_climax_test) — task reference", flush=True)
    base = R["vsa_climax_test"]["dp"]
    print(f"{'strategy':<20}{'rho_daily':>11}{'n_overlap_days':>16}{'note':>26}", flush=True)
    rhos = {}
    for nm in names:
        dp = R[nm]["dp"]
        j = pd.concat([base.rename("vsa"), dp.rename(nm)], axis=1).dropna()
        rho = float(j["vsa"].corr(j[nm])) if len(j) > 5 else float("nan")
        rhos[nm] = rho
        note = "(self)" if nm == "vsa_climax_test" else ("LOW-CORR DIVERSIFIER" if abs(rho) < 0.30 else "correlated")
        print(f"{nm:<20}{rho:>11.3f}{len(j):>16}{note:>26}", flush=True)

    print("\n[5] MARGINAL PORTFOLIO SHARPE (champion-alone vs champion+candidate, equal-risk daily PnL)", flush=True)
    champ_dp = base.reindex(full_idx, fill_value=0.0)
    champ_sh = cal_sharpe(base, full_idx)
    # normalize each leg to unit daily-vol so combination is risk-balanced (not $-scale-driven)
    def unit(dp):
        s = dp.reindex(full_idx, fill_value=0.0)
        sd = s.std(ddof=1)
        return s / sd if sd > 0 else s
    champ_u = unit(base)
    print(f"{'combo':<34}{'sharpe':>10}{'delta_vs_champ':>16}", flush=True)
    print(f"{'champion alone':<34}{champ_sh:>10.3f}{0.0:>16.3f}", flush=True)
    for nm in names:
        if nm == "vsa_climax_test":
            continue
        cand_u = unit(R[nm]["dp"])
        combo = 0.5 * champ_u + 0.5 * cand_u
        mu, sd = combo.mean(), combo.std(ddof=1)
        combo_sh = float(mu / sd * np.sqrt(365.0)) if sd > 0 else 0.0
        print(f"{('champion + ' + nm):<34}{combo_sh:>10.3f}{combo_sh - champ_sh:>16.3f}", flush=True)

    print("\nDONE.", flush=True)


if __name__ == "__main__":
    main()
