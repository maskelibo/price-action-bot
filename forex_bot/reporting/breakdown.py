"""Per-pair, per-session, per-month breakdowns."""
from __future__ import annotations

import pandas as pd


def _agg(g: pd.DataFrame) -> dict:
    n = len(g)
    if n == 0:
        return {"n_trades": 0}
    wr = float(g["win"].sum()) / n
    pnl = float(g["realized_usd"].sum())
    avg_r = float(g["realized_r"].mean())
    gw = float(g.loc[g["win"], "realized_usd"].sum())
    gl = abs(float(g.loc[~g["win"], "realized_usd"].sum()))
    pf = gw / max(1e-9, gl)
    return {"n_trades": n, "win_rate": wr, "total_pnl_usd": pnl, "avg_r": avg_r, "profit_factor": pf}


def per_session_breakdown(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    rows = {sess: _agg(g) for sess, g in trades.groupby("session")}
    return pd.DataFrame(rows).T


def per_pair_breakdown(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    rows = {pair: _agg(g) for pair, g in trades.groupby("pair")}
    return pd.DataFrame(rows).T


def per_month_breakdown(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    ts = pd.to_datetime(trades["exit_ts"])
    months = ts.dt.strftime("%Y-%m")
    rows = {m: _agg(g) for m, g in trades.groupby(months)}
    return pd.DataFrame(rows).T
