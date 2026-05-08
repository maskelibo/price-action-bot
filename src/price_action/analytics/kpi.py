"""KPI hesaplama — Sharpe, Sortino, Calmar, MaxDD, profit factor, expectancy ...

Kripto 7/24 olduğu için annualization factor = 365 (1d data için sqrt(365)).
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from price_action.logging_config import logger

# Kripto 7/24 → 365
ANNUALIZATION_FACTOR_DAILY = 365
SQRT_ANN = float(np.sqrt(ANNUALIZATION_FACTOR_DAILY))


# =====================================================================
# Düşük seviye yardımcılar
# =====================================================================

def _to_returns(equity: pd.Series) -> pd.Series:
    if equity.empty:
        return equity
    eq = equity.astype(float)
    return eq.pct_change().dropna()


def sharpe(returns: pd.Series, rf: float = 0.0) -> float:
    if returns.empty:
        return 0.0
    excess = returns - rf / ANNUALIZATION_FACTOR_DAILY
    sd = excess.std(ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return 0.0
    return float(excess.mean() / sd * SQRT_ANN)


def sortino(returns: pd.Series, rf: float = 0.0, target: float = 0.0) -> float:
    if returns.empty:
        return 0.0
    excess = returns - rf / ANNUALIZATION_FACTOR_DAILY
    downside = excess[excess < target]
    if downside.empty:
        return 0.0
    dd = np.sqrt((downside ** 2).mean())
    if dd == 0 or not np.isfinite(dd):
        return 0.0
    return float(excess.mean() / dd * SQRT_ANN)


def max_drawdown(equity: pd.Series) -> float:
    """Negatif sayı olarak döner (-0.18 = %18 DD)."""
    if equity.empty:
        return 0.0
    eq = equity.astype(float)
    peak = eq.cummax()
    dd = (eq - peak) / peak
    return float(dd.min()) if not dd.empty else 0.0


def calmar(returns: pd.Series, equity: pd.Series) -> float:
    if returns.empty or equity.empty:
        return 0.0
    annual_return = float(returns.mean() * ANNUALIZATION_FACTOR_DAILY)
    mdd = abs(max_drawdown(equity))
    if mdd == 0:
        return 0.0
    return annual_return / mdd


def profit_factor(pnl_series: pd.Series) -> float:
    if pnl_series.empty:
        return 0.0
    wins = float(pnl_series[pnl_series > 0].sum())
    losses = float(-pnl_series[pnl_series < 0].sum())
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def win_rate(pnl_series: pd.Series) -> float:
    if pnl_series.empty:
        return 0.0
    return float((pnl_series > 0).mean())


def expectancy_r(r_multiples: pd.Series) -> float:
    """Trade başına beklenti, R cinsinden."""
    if r_multiples.empty:
        return 0.0
    return float(r_multiples.mean())


# =====================================================================
# Üst seviye API
# =====================================================================

def compute_kpis(trades_df: pd.DataFrame, equity_curve: pd.Series | None = None) -> dict:
    """Trade DF + opsiyonel equity curve'den standart KPI sözlüğü üret.

    `trades_df` beklenen kolonlar (eksikler 0 sayılır):
        realized_pnl_usdt, realized_r_multiple, mae_pct, mfe_pct, exit_ts
    `equity_curve` index=DateTime, value=USDT bakiye.
    """
    if trades_df is None:
        trades_df = pd.DataFrame()

    pnl = pd.to_numeric(trades_df.get("realized_pnl_usdt", pd.Series(dtype=float)), errors="coerce").dropna()
    r_mult = pd.to_numeric(
        trades_df.get("realized_r_multiple", pd.Series(dtype=float)), errors="coerce"
    ).dropna()
    mae = pd.to_numeric(trades_df.get("mae_pct", pd.Series(dtype=float)), errors="coerce").dropna()
    mfe = pd.to_numeric(trades_df.get("mfe_pct", pd.Series(dtype=float)), errors="coerce").dropna()

    if equity_curve is None or equity_curve.empty:
        # Trade pnl'lerinden synthetic equity üret (varsa)
        equity_curve = _synthetic_equity_from_trades(trades_df)

    rets = _to_returns(equity_curve) if equity_curve is not None else pd.Series(dtype=float)

    avg_win = float(pnl[pnl > 0].mean()) if (pnl > 0).any() else 0.0
    avg_loss = float(pnl[pnl < 0].mean()) if (pnl < 0).any() else 0.0

    kpis = {
        "n_trades": int(len(pnl)),
        "net_pnl_usdt": float(pnl.sum()) if not pnl.empty else 0.0,
        "win_rate": win_rate(pnl),
        "profit_factor": profit_factor(pnl),
        "expectancy_r": expectancy_r(r_mult),
        "avg_win_usdt": avg_win,
        "avg_loss_usdt": avg_loss,
        "sharpe": sharpe(rets),
        "sortino": sortino(rets),
        "calmar": calmar(rets, equity_curve) if equity_curve is not None else 0.0,
        "max_drawdown": max_drawdown(equity_curve) if equity_curve is not None else 0.0,
        "avg_mae_pct": float(mae.mean()) if not mae.empty else 0.0,
        "avg_mfe_pct": float(mfe.mean()) if not mfe.empty else 0.0,
    }
    return kpis


def _synthetic_equity_from_trades(trades_df: pd.DataFrame, initial: float = 10_000.0) -> pd.Series:
    if trades_df.empty or "exit_ts" not in trades_df.columns:
        return pd.Series(dtype=float)
    df = trades_df.sort_values("exit_ts").copy()
    df["exit_ts"] = pd.to_datetime(df["exit_ts"])
    eq = initial + df["realized_pnl_usdt"].fillna(0).cumsum()
    eq.index = df["exit_ts"]
    eq.name = "equity"
    return eq


# =====================================================================
# Regime split
# =====================================================================

def regime_split(
    trades_df: pd.DataFrame,
    market_data: pd.DataFrame,
    *,
    btc_ema_period: int = 200,
    vol_window: int = 20,
) -> dict[str, dict]:
    """Trade'leri (entry_ts) bull/bear/range rejimlerine ayır ve KPI üret.

    `market_data`: index=DateTime, kolon=`close` (BTC günlük). `volume` opsiyonel,
    yoksa volatilite (close pct_change std) ile range tespit edilir.
    """
    out: dict[str, dict] = {"bull": {}, "bear": {}, "range": {}}
    if trades_df is None or trades_df.empty or market_data is None or market_data.empty:
        return out
    md = market_data.copy()
    md.index = pd.to_datetime(md.index)
    md = md.sort_index()
    md["ema"] = md["close"].ewm(span=btc_ema_period, adjust=False).mean()
    md["ret"] = md["close"].pct_change()
    md["vol"] = md["ret"].rolling(vol_window, min_periods=max(2, vol_window // 4)).std()
    vol_median = md["vol"].median()

    def regime_of(ts: pd.Timestamp) -> str:
        try:
            row = md.loc[md.index <= ts].iloc[-1]
        except IndexError:
            return "range"
        bull_cond = bool(row["close"] > row["ema"])
        vol_low = bool(row["vol"] is not None and row["vol"] < vol_median)
        if vol_low:
            return "range"
        return "bull" if bull_cond else "bear"

    df = trades_df.copy()
    df["entry_ts"] = pd.to_datetime(df["entry_ts"])
    df["regime"] = df["entry_ts"].map(regime_of)

    for r in ("bull", "bear", "range"):
        sub = df[df["regime"] == r]
        out[r] = compute_kpis(sub)
        out[r]["n_trades"] = int(len(sub))
    return out


# =====================================================================
# Attribution
# =====================================================================

def attribution(
    trades_df: pd.DataFrame,
    by: Literal["strategy", "symbol", "pattern"] = "strategy",
) -> pd.DataFrame:
    """Strateji / sembol / pattern bazında PnL atfı."""
    if trades_df is None or trades_df.empty:
        return pd.DataFrame(columns=["group", "n_trades", "net_pnl", "win_rate", "expectancy_r"])
    col_map = {"strategy": "strategy_id", "symbol": "symbol", "pattern": "pattern_id"}
    col = col_map[by]
    if col not in trades_df.columns:
        logger.warning("attribution.missing_col", extra={"col": col})
        return pd.DataFrame(columns=["group", "n_trades", "net_pnl", "win_rate", "expectancy_r"])
    grouped = trades_df.groupby(col)
    rows = []
    for name, sub in grouped:
        rows.append(
            {
                "group": name,
                "n_trades": len(sub),
                "net_pnl": float(sub["realized_pnl_usdt"].sum()),
                "win_rate": win_rate(sub["realized_pnl_usdt"]),
                "expectancy_r": expectancy_r(
                    pd.to_numeric(sub.get("realized_r_multiple", pd.Series(dtype=float)), errors="coerce")
                ),
                "profit_factor": profit_factor(sub["realized_pnl_usdt"]),
            }
        )
    df = pd.DataFrame(rows).sort_values("net_pnl", ascending=False).reset_index(drop=True)
    return df
