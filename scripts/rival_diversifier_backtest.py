"""Rival/diversifier hunt vs canli 15m vsa_climax_test.

Adaylar:
  - vsa_climax_test   (BASELINE — canli bot)
  - donchian_breakout (trend-following momentum — VSA fade'in tersi mekanizma)
  - session_orb       (00:00 UTC opening-range breakout — zaman-tabanli momentum)

Dürüstlük:
  - Gercek engine (BacktestEngine) — fee + slippage net, calendar-day Sharpe.
  - 55bps round-trip (taker=0.00275/leg) + 100bps stres (taker=0.005/leg).
  - mean_R_after_fees = trades.realized_r_multiple ortalamasi (fee net).
  - MaxDD + monthly ROI = equity_curve'den (calendar-day, no annualization sismesi).
  - Robustness: walk-forward (yillik OOS), shuffle baseline, symbol-out.
  - Korelasyon: aylik R-toplamlari vs vsa (cesitlendirme degeri).
"""
from __future__ import annotations

import os
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ.setdefault("PA_LOG_QUIET", "1")
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

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
           "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]
TF = "15m"
START = datetime(2021, 5, 16, tzinfo=timezone.utc)
END = datetime(2026, 5, 22, tzinfo=timezone.utc)
CAP = 10_000.0

_DB = Path("/tmp/market_snapshot.duckdb")
_DB = _DB if _DB.exists() else (ROOT / "data" / "market.duckdb")
_CACHE: dict[tuple, pd.DataFrame] = {}


def loader(symbol: str, tf: str, start, end) -> pd.DataFrame:
    key = (symbol, tf)
    if key not in _CACHE:
        con = duckdb.connect(str(_DB), read_only=True)
        df = con.execute(
            "SELECT ts, open, high, low, close, volume FROM ohlcv "
            "WHERE venue='binance' AND symbol=? AND timeframe=? ORDER BY ts",
            [symbol, tf],
        ).fetchdf()
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


def donchian_15m_manifest() -> StrategyManifest:
    """Donchian — 15m intraday adaptasyon. Entry 55-bar, exit 20-bar,
    squeeze KAPALI (kripto 15m'de cok katiydi), Kaufman ER>=0.30 trend filtresi."""
    raw = {
        "name": "donchian_breakout", "version": "15m-rival-1.0",
        "description": "Donchian 55-bar breakout, 15m intraday, squeeze off.",
        "signals": {
            "patterns": [{"id": "donchian_breakout", "enabled": True, "weight": 1.0,
                          "params": {"entry_period": 55, "exit_period": 20,
                                     "squeeze_required": False}}],
            "filters": {"atr_min_pct": 0.003, "kaufman_er_min": 0.30},
            "confluence": {"method": "weighted_sum", "min_score": 1.0},
        },
        "risk": {"take_profit": {"method": "r_multiple", "primary_R": 1.5},
                 "stop_loss": {"method": "donchian", "atr_buffer": 0.0}},
        "backtest": {"warmup_bars": 60, "initial_capital_usdt": CAP},
    }
    return StrategyManifest.model_validate(raw)


def build(name: str) -> object:
    if name == "vsa_climax_test":
        return VSAClimaxTestStrategy(vsa_mf())
    if name == "donchian_breakout":
        return DonchianBreakoutStrategy(donchian_15m_manifest())
    if name == "session_orb":
        return SessionORBStrategy(orb_mf())
    raise ValueError(name)


def monthly_metrics(eq: pd.Series) -> dict:
    if eq.empty or len(eq) < 2:
        return dict(monthly_roi_mean=0.0, monthly_neg=0, monthly_n=0, max_dd=0.0)
    eq = eq.copy(); eq.index = pd.to_datetime(eq.index, utc=True)
    m = eq.resample("ME").last()
    m_prev = m.shift(1, fill_value=eq.iloc[0])
    mret = (m / m_prev - 1.0).dropna()
    peak = eq.cummax(); dd = (eq - peak) / peak
    return dict(
        monthly_roi_mean=float(mret.mean()) * 100,
        monthly_neg=int((mret < 0).sum()),
        monthly_n=int(len(mret)),
        max_dd=float(dd.min()) * 100,
        monthly_series=mret,
    )


def run_engine(name: str, taker: float, slip: float, universe=None, start=START, end=END):
    eng = BacktestEngine()
    strat = build(name)
    res = eng.run(
        strat, universe or SYMBOLS, start=start, end=end,
        fees={"taker": taker, "maker": -0.00010}, slippage_bps=slip,
        initial_capital=CAP, timeframe=TF, ohlcv_provider=loader,
    )
    tr = res.trades
    mean_R = float(tr["realized_r_multiple"].mean()) if not tr.empty else 0.0
    win = float((tr["realized_r_multiple"] > 0).mean()) * 100 if not tr.empty else 0.0
    mm = monthly_metrics(res.equity_curve)
    sharpe = float(res.kpis.get("sharpe", 0.0))
    return dict(name=name, n_trades=res.n_trades, mean_R=mean_R, win=win,
                max_dd=mm["max_dd"], monthly_roi=mm["monthly_roi_mean"],
                monthly_neg=mm["monthly_neg"], monthly_n=mm["monthly_n"],
                sharpe=sharpe, equity=res.equity_curve, trades=tr,
                monthly_series=mm.get("monthly_series"))


def shuffle_baseline(name: str, taker: float, slip: float, seed: int = 7) -> float:
    """Null modeli: ayni sembol seti ama bar getirileri shuffle edilmis.
    Sinyallerin gercek getiriyle iliskisini kirar -> edge null'a duser mi?
    Mean_R doner."""
    rng = np.random.default_rng(seed)

    def shuf_loader(symbol, tf, start, end):
        df = loader(symbol, tf, start, end)
        if df.empty:
            return df
        df = df.copy()
        # log-return permutasyonu (close), high/low/open close'tan turetilir
        c = df["close"].to_numpy()
        rets = np.diff(np.log(c))
        rng.shuffle(rets)
        new_c = c[0] * np.exp(np.concatenate([[0.0], np.cumsum(rets)]))
        scale = new_c / c
        df["close"] = new_c
        df["open"] = df["open"].to_numpy() * scale
        df["high"] = df["high"].to_numpy() * scale
        df["low"] = df["low"].to_numpy() * scale
        return df

    eng = BacktestEngine()
    res = eng.run(build(name), SYMBOLS, start=START, end=END,
                  fees={"taker": taker, "maker": -0.00010}, slippage_bps=slip,
                  initial_capital=CAP, timeframe=TF, ohlcv_provider=shuf_loader)
    tr = res.trades
    return float(tr["realized_r_multiple"].mean()) if not tr.empty else 0.0


def main():
    print("=" * 78, flush=True)
    print(f"RIVAL HUNT — {TF} | {len(SYMBOLS)} sym | {START.date()}..{END.date()} | cap={CAP:.0f}", flush=True)
    print("=" * 78, flush=True)

    names = ["vsa_climax_test", "donchian_breakout", "session_orb"]
    COSTS = [("55bps", 0.00275, 5.0), ("100bps", 0.005, 10.0)]

    results = {}
    print("\n[1] HEAD-TO-HEAD (full sample)", flush=True)
    hdr = f"{'strategy':<20}{'cost':<8}{'n':>6}{'mean_R':>9}{'win%':>7}{'maxDD%':>8}{'mROI%':>8}{'neg':>6}{'shrp':>7}"
    print(hdr); print("-" * len(hdr), flush=True)
    for nm in names:
        for clabel, tk, sl in COSTS:
            r = run_engine(nm, tk, sl)
            results[(nm, clabel)] = r
            print(f"{nm:<20}{clabel:<8}{r['n_trades']:>6}{r['mean_R']:>9.3f}{r['win']:>7.1f}"
                  f"{r['max_dd']:>8.1f}{r['monthly_roi']:>8.2f}{r['monthly_neg']:>4}/{r['monthly_n']:<2}{r['sharpe']:>7.2f}")

    print("\n[2] SHUFFLE BASELINE (null model — mean_R should collapse toward 0)", flush=True)
    print(f"{'strategy':<20}{'real_R(55)':>12}{'shuffle_R':>12}{'verdict':>20}", flush=True)
    for nm in names:
        real = results[(nm, "55bps")]["mean_R"]
        shuf = shuffle_baseline(nm, 0.00275, 5.0)
        verdict = "BEATS NULL" if real > shuf + 0.02 else "FAILS (~null)"
        print(f"{nm:<20}{real:>12.3f}{shuf:>12.3f}{verdict:>20}", flush=True)

    print("\n[3] WALK-FORWARD (yearly OOS slices, 55bps)", flush=True)
    years = [(2021, 2022), (2022, 2023), (2023, 2024), (2024, 2025), (2025, 2026)]
    print(f"{'strategy':<20}" + "".join(f"{y[0]:>9}" for y in years) + f"{'OOS_neg':>9}", flush=True)
    wf = {}
    for nm in names:
        cells = []
        neg = 0
        for ys, ye in years:
            s = datetime(ys, 5, 16, tzinfo=timezone.utc)
            e = datetime(ye, 5, 16, tzinfo=timezone.utc)
            r = run_engine(nm, 0.00275, 5.0, start=s, end=e)
            cells.append(r["mean_R"])
            if r["mean_R"] < 0:
                neg += 1
        wf[nm] = cells
        print(f"{nm:<20}" + "".join(f"{c:>9.3f}" for c in cells) + f"{neg:>6}/{len(years)}", flush=True)

    if os.environ.get("RIVAL_SYMOUT", "1") == "1":
        print("\n[4] SYMBOL-OUT (drop-one CV, mean_R range, 55bps)", flush=True)
        print(f"{'strategy':<20}{'full_R':>9}{'min_R':>9}{'max_R':>9}{'spread':>9}", flush=True)
        for nm in names:
            full = results[(nm, "55bps")]["mean_R"]
            rs = []
            for drop in SYMBOLS:
                uni = [s for s in SYMBOLS if s != drop]
                r = run_engine(nm, 0.00275, 5.0, universe=uni)
                rs.append(r["mean_R"])
            print(f"{nm:<20}{full:>9.3f}{min(rs):>9.3f}{max(rs):>9.3f}{max(rs)-min(rs):>9.3f}", flush=True)

    print("\n[5] CORRELATION vs VSA (monthly return series, full sample 55bps)", flush=True)
    base = results[("vsa_climax_test", "55bps")]["monthly_series"]
    print(f"{'strategy':<20}{'corr_to_vsa':>14}{'note':>30}", flush=True)
    for nm in names:
        ms = results[(nm, "55bps")]["monthly_series"]
        if ms is None or base is None:
            print(f"{nm:<20}{'n/a':>14}", flush=True)
            continue
        j = pd.concat([base.rename("vsa"), ms.rename(nm)], axis=1).dropna()
        corr = float(j["vsa"].corr(j[nm])) if len(j) > 3 else float("nan")
        note = "(self)" if nm == "vsa_climax_test" else ("LOW-CORR DIVERSIFIER" if abs(corr) < 0.3 else "")
        print(f"{nm:<20}{corr:>14.3f}{note:>30}", flush=True)

    print("\nDONE.", flush=True)


if __name__ == "__main__":
    main()
