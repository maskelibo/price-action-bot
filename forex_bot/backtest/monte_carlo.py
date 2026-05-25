"""Monte Carlo trade-sequence shuffle: P5/P50/P95 distribution of ROI and DD."""
from __future__ import annotations

import numpy as np
import pandas as pd


def monte_carlo_shuffle(trades: pd.DataFrame, n_iter: int = 1000, initial: float = 10_000.0, seed: int = 42) -> dict:
    if trades.empty:
        return {"p5_roi": 0.0, "p50_roi": 0.0, "p95_roi": 0.0, "p5_dd": 0.0, "p50_dd": 0.0, "p95_dd": 0.0}
    rng = np.random.default_rng(seed)
    pnls = trades["realized_usd"].to_numpy()
    final_balances = np.zeros(n_iter)
    max_dds = np.zeros(n_iter)
    for k in range(n_iter):
        shuffled = rng.permutation(pnls)
        eq = initial + np.cumsum(shuffled)
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak
        final_balances[k] = eq[-1]
        max_dds[k] = dd.min()
    roi = (final_balances / initial - 1.0) * 100.0
    dd_pct = max_dds * 100.0
    return {
        "p5_roi": float(np.percentile(roi, 5)),
        "p50_roi": float(np.percentile(roi, 50)),
        "p95_roi": float(np.percentile(roi, 95)),
        "p5_dd": float(np.percentile(dd_pct, 5)),
        "p50_dd": float(np.percentile(dd_pct, 50)),
        "p95_dd": float(np.percentile(dd_pct, 95)),
        "n_iter": n_iter,
    }
