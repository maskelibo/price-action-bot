#!/usr/bin/env python
"""Faz 7 — Parameter Sweep Runner.

Backtest pool'undan filtre/sizing parametrelerini deneyerek metric
tablosu üretir. Pool zaten sec53_*.pkl içinde — biz sadece replay edip
SL/TP/risk grid'i ile R-multiple metriği hesaplıyoruz (no re-simulation).

Pool schema (list[dict]):
    entry_ts, exit_ts, entry_price, initial_sl, R, peak_R,
    symbol, side, conf, strategy, vol_z

R-multiple replay semantik:
    sl_pct        = |initial_sl - entry_price| / entry_price
    sl_multiplier = filtre: sl_pct >= sl_multiplier * sl_pct_base
                    (sl_pct_base config'ten — P1c için 0.030, default 0.025)
    tp_r          = TP override: peak_R >= tp_r => exit at +tp_r,
                    aksi takdirde realized R (negatif veya kucuk pozitif)
    risk_pct      = sizing (mean_R ile çarpan değil — sum_R'yi $ cinsinden
                    hesaba katmak için bilgilendirici)

Per-cell metric:
    n_trades, win_rate, mean_R, sum_R, sharpe_like (=mean_R/std_R*sqrt(n)),
    mean_R_after_fees (taker 15bps RT = 0.0030 R-eşdeğer, sl_pct'e bağlı)

Per-regime breakdown:
    BTC EMA200 üstü = bull, altı = bear (basit proxy)
    range = ATR%/price < threshold (skipped — sub-daily data yok burada,
            sade bull/bear bölünmesi yapıyoruz).

CLI:
    .venv/bin/python scripts/param_sweep_runner.py \\
        --strategy vsa_climax_test \\
        --pool data/sec53_5m_pool_v11_vm20.pkl
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import pickle
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Taker fee RT (Binance USDT-M taker = 5bps; round-trip = 10bps).
# Tutucu olsun: 15bps RT — R-multiple eşdeğeri = 0.0015 / sl_pct.
FEE_RT_PCT = 0.0015


# ---------------------------------------------------------------------------
# Grid + pool loaders
# ---------------------------------------------------------------------------

def iter_grid(grids: Mapping[str, Iterable[Any]]) -> list[dict[str, Any]]:
    """Cartesian product of grid axes — returns list of cell dicts."""
    keys = list(grids.keys())
    values = [list(grids[k]) for k in keys]
    cells = []
    for combo in itertools.product(*values):
        cells.append(dict(zip(keys, combo)))
    return cells


def load_pool(pool_path: Path) -> pd.DataFrame:
    """Pool .pkl (list[dict]) → DataFrame with derived sl_pct column."""
    with open(pool_path, "rb") as f:
        records = pickle.load(f)
    df = pd.DataFrame(records)
    # Derived columns
    df["sl_pct"] = (df["initial_sl"] - df["entry_price"]).abs() / df["entry_price"]
    # Normalize timezone
    if "entry_ts" in df.columns:
        df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
    return df


# ---------------------------------------------------------------------------
# Per-cell metric calculation
# ---------------------------------------------------------------------------

@dataclass
class CellMetric:
    params: dict[str, Any]
    n_trades: int
    win_rate: float
    mean_R: float
    sum_R: float
    std_R: float
    sharpe_like: float
    mean_R_after_fees: float
    regime_breakdown: dict[str, dict[str, float]]

    def to_row(self) -> dict[str, Any]:
        row = dict(self.params)
        row.update({
            "n_trades": self.n_trades,
            "win_rate": round(self.win_rate, 4),
            "mean_R": round(self.mean_R, 4),
            "sum_R": round(self.sum_R, 2),
            "std_R": round(self.std_R, 4),
            "sharpe_like": round(self.sharpe_like, 4),
            "mean_R_after_fees": round(self.mean_R_after_fees, 4),
        })
        for regime, stats in self.regime_breakdown.items():
            for k, v in stats.items():
                row[f"{regime}_{k}"] = round(v, 4) if isinstance(v, float) else v
        return row


def apply_cell(
    df: pd.DataFrame,
    sl_multiplier: float,
    tp_r: float,
    risk_pct: float,
    sl_pct_base: float,
    regime_series: pd.Series | None = None,
) -> CellMetric:
    """Apply cell parameters to pool and compute metrics."""
    # 1) Filter: sl_pct must be >= sl_multiplier * sl_pct_base
    sl_threshold = sl_multiplier * sl_pct_base
    sub = df[df["sl_pct"] >= sl_threshold]
    if len(sub) == 0:
        return CellMetric(
            params={"sl_multiplier": sl_multiplier, "tp_r": tp_r, "risk_pct": risk_pct},
            n_trades=0, win_rate=0.0, mean_R=0.0, sum_R=0.0, std_R=0.0,
            sharpe_like=0.0, mean_R_after_fees=0.0, regime_breakdown={},
        )

    # 2) TP override: if peak_R >= tp_r, exit at +tp_r; else use realized R
    realized_R = sub["R"].to_numpy()
    peak_R = sub["peak_R"].to_numpy()
    new_R = np.where(peak_R >= tp_r, float(tp_r), realized_R)

    # 3) Fee model — taker RT = FEE_RT_PCT, in R units = FEE_RT_PCT / sl_pct
    sl_pct_arr = sub["sl_pct"].to_numpy()
    fee_R = FEE_RT_PCT / np.maximum(sl_pct_arr, 1e-6)
    new_R_net = new_R - fee_R

    n = len(new_R)
    win_rate = float((new_R > 0).mean())
    mean_R = float(new_R.mean())
    sum_R = float(new_R.sum())
    std_R = float(new_R.std(ddof=1)) if n > 1 else 0.0
    sharpe_like = (mean_R / std_R * math.sqrt(n)) if std_R > 0 else 0.0
    mean_R_after_fees = float(new_R_net.mean())

    # 4) Regime breakdown (bull/bear). regime_series indexed by entry_ts.
    regime_breakdown: dict[str, dict[str, float]] = {}
    if regime_series is not None and len(regime_series) > 0:
        ts = sub["entry_ts"].to_numpy()
        # Map each trade's entry_ts to nearest <= regime_series timestamp
        regime_labels = regime_series.reindex(
            pd.DatetimeIndex(ts), method="ffill"
        ).to_numpy()
        for regime in ("bull", "bear"):
            mask = regime_labels == regime
            if mask.sum() == 0:
                regime_breakdown[regime] = {"n": 0, "mean_R": 0.0, "win_rate": 0.0}
                continue
            r_sub = new_R[mask]
            regime_breakdown[regime] = {
                "n": int(mask.sum()),
                "mean_R": float(r_sub.mean()),
                "win_rate": float((r_sub > 0).mean()),
            }

    return CellMetric(
        params={"sl_multiplier": sl_multiplier, "tp_r": tp_r, "risk_pct": risk_pct},
        n_trades=n, win_rate=win_rate, mean_R=mean_R, sum_R=sum_R,
        std_R=std_R, sharpe_like=sharpe_like,
        mean_R_after_fees=mean_R_after_fees,
        regime_breakdown=regime_breakdown,
    )


# ---------------------------------------------------------------------------
# Regime detection (BTC EMA200 daily proxy)
# ---------------------------------------------------------------------------

def build_regime_series(df: pd.DataFrame) -> pd.Series:
    """Use BTC trades to approximate bull/bear regime via 200-bar EMA of price.

    Sade: pool'da BTC entry_price'tan günlük ortalama → EMA(200) → bull/bear.
    Range gerekirse ATR ile ayrıştırılır; burada sade tutuyoruz.
    """
    btc = df[df["symbol"].astype(str).str.startswith("BTC")].copy()
    if len(btc) == 0:
        return pd.Series([], dtype="object")
    btc = btc.assign(date=pd.to_datetime(btc["entry_ts"], utc=True).dt.floor("1D"))
    daily = btc.groupby("date")["entry_price"].mean().sort_index()
    if len(daily) < 10:
        # Insufficient history → label all bars 'bull' as neutral default.
        regime = pd.Series("bull", index=daily.index, name="regime")
    else:
        ema = daily.ewm(span=min(200, max(10, len(daily) // 3)), adjust=False).mean()
        regime = pd.Series(
            np.where(daily >= ema, "bull", "bear"),
            index=daily.index,
            name="regime",
        )
    if regime.index.tz is None:
        regime.index = regime.index.tz_localize("UTC")
    else:
        regime.index = regime.index.tz_convert("UTC")
    return regime


# ---------------------------------------------------------------------------
# Top-N ranking + markdown report
# ---------------------------------------------------------------------------

def rank_top(cells: list[CellMetric], n: int = 5, key: str = "sharpe_like") -> list[CellMetric]:
    """Rank cells by `key` desc; skip cells with n_trades < 30 (under-powered)."""
    eligible = [c for c in cells if c.n_trades >= 30]
    return sorted(eligible, key=lambda c: getattr(c, key), reverse=True)[:n]


def write_markdown_report(
    output_path: Path,
    strategy: str,
    pool_path: Path,
    grids: Mapping[str, Iterable[Any]],
    cells: list[CellMetric],
    top5: list[CellMetric],
    date_range: tuple[pd.Timestamp, pd.Timestamp],
    sl_pct_base: float,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append(f"# Param Sweep — {strategy}")
    lines.append("")
    lines.append(f"_Generated: {datetime.now(timezone.utc).isoformat()}_")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append(f"- **Strategy:** `{strategy}`")
    lines.append(f"- **Pool:** `{pool_path}`")
    lines.append(f"- **Date range:** {date_range[0]} → {date_range[1]}")
    lines.append(f"- **sl_pct_base:** {sl_pct_base}")
    lines.append(f"- **Cells:** {len(cells)} (eligible n>=30: {sum(1 for c in cells if c.n_trades >= 30)})")
    lines.append("- **Grids:**")
    for k, v in grids.items():
        lines.append(f"  - `{k}`: {list(v)}")
    lines.append("")

    lines.append("## Top 5 cells (by sharpe_like)")
    lines.append("")
    lines.append("| Rank | sl_mult | tp_r | risk_pct | n | win% | mean_R | sum_R | sharpe_like | mean_R_net |")
    lines.append("|------|---------|------|----------|---|------|--------|-------|-------------|------------|")
    for i, c in enumerate(top5, 1):
        p = c.params
        lines.append(
            f"| {i} | {p['sl_multiplier']} | {p['tp_r']} | {p['risk_pct']} | "
            f"{c.n_trades} | {c.win_rate * 100:.2f} | {c.mean_R:.3f} | "
            f"{c.sum_R:.1f} | {c.sharpe_like:.3f} | {c.mean_R_after_fees:.3f} |"
        )
    lines.append("")

    # Heatmaps (2 axis sliced — fix risk_pct at median, sweep sl_mult × tp_r)
    lines.append("## Heatmap — mean_R (risk_pct fixed at median)")
    lines.append("")
    risk_values = sorted(set(c.params["risk_pct"] for c in cells))
    sl_values = sorted(set(c.params["sl_multiplier"] for c in cells))
    tp_values = sorted(set(c.params["tp_r"] for c in cells))
    fixed_risk = risk_values[len(risk_values) // 2] if risk_values else None
    if fixed_risk is not None:
        lines.append(f"_risk_pct = {fixed_risk}_")
        lines.append("")
        header = "| sl_mult \\ tp_r | " + " | ".join(str(t) for t in tp_values) + " |"
        sep = "|" + "---|" * (len(tp_values) + 1)
        lines.append(header)
        lines.append(sep)
        cell_map = {(c.params["sl_multiplier"], c.params["tp_r"], c.params["risk_pct"]): c for c in cells}
        for sl in sl_values:
            row = [f"**{sl}**"]
            for tp in tp_values:
                c = cell_map.get((sl, tp, fixed_risk))
                row.append(f"{c.mean_R:.3f}" if c else "n/a")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    # Per-regime breakdown for top cell
    if top5:
        lines.append("## Top cell — regime breakdown")
        lines.append("")
        top = top5[0]
        if top.regime_breakdown:
            lines.append("| regime | n | mean_R | win_rate |")
            lines.append("|--------|---|--------|----------|")
            for regime, stats in top.regime_breakdown.items():
                lines.append(
                    f"| {regime} | {stats.get('n', 0)} | "
                    f"{stats.get('mean_R', 0):.3f} | "
                    f"{stats.get('win_rate', 0) * 100:.2f}% |"
                )
            lines.append("")

    lines.append("## Conclusion")
    lines.append("")
    if top5:
        best = top5[0]
        p = best.params
        lines.append(
            f"**Recommended tuning:** sl_multiplier={p['sl_multiplier']}, "
            f"tp_r={p['tp_r']}, risk_pct={p['risk_pct']} "
            f"(mean_R={best.mean_R:.3f}, sharpe_like={best.sharpe_like:.3f}, "
            f"n={best.n_trades}, win_rate={best.win_rate * 100:.2f}%)."
        )
    else:
        lines.append("No eligible cells found (n_trades < 30 for all combinations).")
    lines.append("")

    output_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_sweep(
    strategy: str,
    pool_path: Path,
    grids: dict[str, Iterable[Any]],
    output_path: Path,
    sl_pct_base: float = 0.025,
    drop_strategies: list[str] | None = None,
    enable_regime: bool = True,
) -> dict[str, Any]:
    """Execute grid sweep and write markdown report."""
    pool_path = Path(pool_path)
    output_path = Path(output_path)

    df = load_pool(pool_path)
    df_strat = df[df["strategy"] == strategy].copy()
    if drop_strategies:
        df_strat = df_strat[~df_strat["strategy"].isin(drop_strategies)]
    if len(df_strat) == 0:
        raise ValueError(f"No trades for strategy={strategy!r} in pool {pool_path}")

    date_range = (df_strat["entry_ts"].min(), df_strat["entry_ts"].max())
    regime_series = build_regime_series(df) if enable_regime else None

    cells_params = iter_grid(grids)
    metrics: list[CellMetric] = []
    for params in cells_params:
        m = apply_cell(
            df_strat,
            sl_multiplier=float(params["sl_multiplier"]),
            tp_r=float(params["tp_r"]),
            risk_pct=float(params["risk_pct"]),
            sl_pct_base=sl_pct_base,
            regime_series=regime_series,
        )
        metrics.append(m)

    top5 = rank_top(metrics, n=5)
    write_markdown_report(
        output_path, strategy, pool_path, grids, metrics, top5, date_range, sl_pct_base,
    )

    return {
        "n_cells": len(metrics),
        "top5": [c.to_row() for c in top5],
        "best": top5[0].to_row() if top5 else None,
        "output": str(output_path),
        "date_range": [str(date_range[0]), str(date_range[1])],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_grids_yaml(path: Path, strategy: str) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    """Load grids and per-strategy overrides from YAML."""
    import yaml
    cfg = yaml.safe_load(path.read_text()) or {}
    grids = dict(cfg.get("default_grid", {}))
    per = (cfg.get("per_strategy") or {}).get(strategy, {}) or {}
    if "grid" in per:
        grids.update(per["grid"])
    overrides = {k: v for k, v in per.items() if k != "grid"}
    return grids, overrides


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Parameter Sweep Runner")
    p.add_argument("--strategy", required=True)
    p.add_argument("--pool", required=False, type=Path,
                   default=Path("data/sec53_5m_pool_v11_vm20.pkl"))
    p.add_argument("--grids-yaml", type=Path,
                   default=Path("configs/param_sweep_grids.yaml"))
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--sl-pct-base", type=float, default=None)
    p.add_argument("--no-regime", action="store_true")
    p.add_argument("--limit-cells", type=int, default=None,
                   help="If set, run only first N cells (for smoke tests).")
    args = p.parse_args(argv)

    if args.grids_yaml.exists():
        grids, overrides = _load_grids_yaml(args.grids_yaml, args.strategy)
        pool = Path(overrides.get("pool", args.pool))
        sl_pct_base = args.sl_pct_base if args.sl_pct_base is not None \
            else float(overrides.get("sl_pct_min", 0.025))
        drop_strategies = overrides.get("drop_strategies") or None
    else:
        grids = {
            "sl_multiplier": [1.0, 1.25, 1.5, 1.75, 2.0],
            "tp_r": [1.0, 1.2, 1.5, 2.0],
            "risk_pct": [0.003, 0.005, 0.007, 0.010],
        }
        pool = args.pool
        sl_pct_base = args.sl_pct_base or 0.025
        drop_strategies = None

    if args.limit_cells:
        # Limit by truncating cartesian: take first product axis values.
        # Sade çözüm — sl_multiplier'ı kısalt.
        new = dict(grids)
        n = args.limit_cells
        flat = iter_grid(grids)[:n]
        # Convert back to per-axis sets containing only used values
        new = {k: sorted(set(c[k] for c in flat)) for k in new}
        grids = new

    output = args.output or Path(
        f"reports/param_sweep/{args.strategy}-{datetime.now(timezone.utc).date().isoformat()}.md"
    )

    result = run_sweep(
        strategy=args.strategy,
        pool_path=pool,
        grids=grids,
        output_path=output,
        sl_pct_base=sl_pct_base,
        drop_strategies=drop_strategies,
        enable_regime=not args.no_regime,
    )

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
