"""KPI summary helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd


def summarize_kpis(trades: pd.DataFrame, equity: pd.Series, init: float, final: float) -> dict:
    n = len(trades)
    if n == 0 or equity.empty:
        return {"n_trades": 0}
    wr = float(trades["win"].sum()) / n
    gross_win = float(trades.loc[trades["win"], "realized_usd"].sum())
    gross_loss = abs(float(trades.loc[~trades["win"], "realized_usd"].sum()))
    pf = gross_win / max(1e-9, gross_loss)
    expectancy_r = float(trades["realized_r"].mean())
    rets = equity.pct_change().dropna()
    sharpe = (rets.mean() / rets.std()) * np.sqrt(96 * 252) if rets.std() > 0 else 0.0
    downside = rets[rets < 0]
    sortino = (rets.mean() / downside.std()) * np.sqrt(96 * 252) if not downside.empty and downside.std() > 0 else 0.0
    peak = equity.cummax()
    dd = (equity - peak) / peak
    maxdd = float(dd.min()) if not dd.empty else 0.0
    days = max(1, (equity.index[-1] - equity.index[0]).total_seconds() / 86400)
    years = days / 365.25
    cagr = (final / init) ** (1 / max(0.01, years)) - 1 if final > 0 else -1.0
    calmar = abs(cagr / maxdd) if maxdd < 0 else 0.0
    return {
        "n_trades": n, "win_rate": wr,
        "profit_factor": pf, "expectancy_r": expectancy_r,
        "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
        "max_dd_pct": maxdd * 100.0,
        "cagr_pct": cagr * 100.0,
        "return_total_pct": (final / init - 1.0) * 100.0,
    }
