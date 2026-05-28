"""Backtest metrikleri.

- Sharpe, Sortino, Calmar
- MaxDD, profit factor, win rate, expectancy
- MAE / MFE
- Deflated Sharpe Ratio (Lopez de Prado, 2014)

Tüm fonksiyonlar pure & vectorized.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

ANNUALIZATION = {
    "1m": 365 * 24 * 60,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "1h": 365 * 24,
    "4h": 365 * 6,
    "1d": 365,
    "1w": 52,
}


# =====================================================================
# Equity-curve metrics
# =====================================================================

def _returns_from_equity(equity: pd.Series) -> pd.Series:
    if equity is None or len(equity) < 2:
        return pd.Series(dtype=float)
    return equity.pct_change().dropna()


def sharpe(returns: pd.Series, periods_per_year: int = 365, rf: float = 0.0) -> float:
    if returns is None or returns.empty or returns.std(ddof=0) == 0:
        return 0.0
    excess = returns - rf / periods_per_year
    return float(np.sqrt(periods_per_year) * excess.mean() / excess.std(ddof=0))


def sortino(returns: pd.Series, periods_per_year: int = 365, rf: float = 0.0) -> float:
    if returns is None or returns.empty:
        return 0.0
    excess = returns - rf / periods_per_year
    downside = excess[excess < 0]
    if downside.empty or downside.std(ddof=0) == 0:
        return 0.0
    return float(np.sqrt(periods_per_year) * excess.mean() / downside.std(ddof=0))


def max_drawdown(equity: pd.Series) -> float:
    if equity is None or equity.empty:
        return 0.0
    rolling_max = equity.cummax()
    dd = equity / rolling_max - 1.0
    return float(dd.min())


def calmar(equity: pd.Series, periods_per_year: int = 365) -> float:
    if equity is None or len(equity) < 2:
        return 0.0
    returns = _returns_from_equity(equity)
    n = len(returns)
    if n == 0:
        return 0.0
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (periods_per_year / n) - 1.0
    mdd = abs(max_drawdown(equity))
    if mdd == 0:
        return 0.0
    return float(cagr / mdd)


# =====================================================================
# Trade-level metrics
# =====================================================================

def profit_factor(trade_pnls: pd.Series) -> float:
    if trade_pnls is None or trade_pnls.empty:
        return 0.0
    wins = trade_pnls[trade_pnls > 0].sum()
    losses = -trade_pnls[trade_pnls < 0].sum()
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins / losses)


def win_rate(trade_pnls: pd.Series) -> float:
    if trade_pnls is None or trade_pnls.empty:
        return 0.0
    return float((trade_pnls > 0).mean())


def expectancy(trade_pnls: pd.Series) -> float:
    if trade_pnls is None or trade_pnls.empty:
        return 0.0
    return float(trade_pnls.mean())


def avg_win_loss(trade_pnls: pd.Series) -> tuple[float, float]:
    if trade_pnls is None or trade_pnls.empty:
        return 0.0, 0.0
    wins = trade_pnls[trade_pnls > 0]
    losses = trade_pnls[trade_pnls < 0]
    return float(wins.mean()) if not wins.empty else 0.0, float(losses.mean()) if not losses.empty else 0.0


# =====================================================================
# MAE / MFE
# =====================================================================

def mae_mfe(
    trade_paths: list[pd.Series],
) -> tuple[list[float], list[float]]:
    """Her trade için MAE (max adverse excursion %) ve MFE (max favorable %)."""
    maes: list[float] = []
    mfes: list[float] = []
    for path in trade_paths:
        if path is None or path.empty:
            maes.append(0.0)
            mfes.append(0.0)
            continue
        entry = float(path.iloc[0])
        if entry == 0:
            maes.append(0.0)
            mfes.append(0.0)
            continue
        ret = path / entry - 1.0
        maes.append(float(ret.min()))
        mfes.append(float(ret.max()))
    return maes, mfes


# =====================================================================
# Deflated Sharpe Ratio
# =====================================================================

def deflated_sharpe_ratio(
    sr_observed: float,
    *,
    n_trials: int,
    sr_variance: float | None = None,
    skew: float = 0.0,
    kurt: float = 3.0,
    n_obs: int = 252,
) -> float:
    """Lopez de Prado (2014) — DSR.

    DSR = Phi[(SR - E[max SR]) * sqrt(n-1) / sqrt(1 - skew*SR + (kurt-1)/4 * SR^2)]

    `n_trials`: kaç parametre / strateji denendi (multiple-testing düzeltmesi için).
    `sr_variance`: trial'lar arası SR varyansı; verilmezse 1.0 (konservatif).
    """
    if n_trials <= 1:
        return 0.5  # tekil deneme; tanımsız — neutral döner
    if sr_variance is None or sr_variance <= 0:
        sr_variance = 1.0

    # Euler-Mascheroni constant
    em = 0.5772156649
    # E[max SR] yaklaşımı (independent trials, Z dağılımı)
    z_alpha = (1 - em) * _norm_inv(1 - 1.0 / n_trials) + em * _norm_inv(
        1 - 1.0 / (n_trials * math.e)
    )
    e_max = math.sqrt(sr_variance) * z_alpha

    denom = math.sqrt(max(1.0 - skew * sr_observed + (kurt - 1) / 4.0 * sr_observed**2, 1e-12))
    dsr = _norm_cdf((sr_observed - e_max) * math.sqrt(max(n_obs - 1, 1)) / denom)
    return float(dsr)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_inv(p: float) -> float:
    """Beasley-Springer-Moro yaklaşımı."""
    if not 0.0 < p < 1.0:
        return 0.0
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / (
            ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1))
    if p <= phigh:
        q = p - 0.5
        r = q*q
        return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q / (
            (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1))
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / (
        ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1))


# =====================================================================
# Compose
# =====================================================================

def compute_kpis(
    equity: pd.Series,
    trade_pnls: pd.Series | None = None,
    *,
    timeframe: str = "1d",
    n_trials: int = 1,
) -> dict[str, float]:
    """Tek seferde tüm KPI'leri hesapla.

    FIX 2026-05-28 (audit-F3): Sharpe annualization bug — fixed.
    Önceki bug: equity_curve `15m` frequency'de reindex'liydi (engine.py:239
    `full_index = pd.date_range(..., freq="15min")`) ama Sharpe
    `ANNUALIZATION["15m"]=35040` ile annualize ediliyordu. Equity %99 flat
    (trade exit'leri arası dolduruluş `ffill`), `pct_change` %99 sıfır.
    `sqrt(35040) ≈ 187` ile near-zero mean amplify → **3-5× abartılı Sharpe**.

    Çözüm: equity'yi GÜNLÜK aggregate'e indir (`resample("1D").last().ffill()`)
    + `ppy=365` zorla. Sharpe/Sortino/Calmar/CAGR hepsi tutarlı günlük base.
    `timeframe` parametresi backward compat için duruyor ama Sharpe'a
    etki etmiyor; sadece eski caller'lar kırılmasın diye.

    Etki: CAGR matematiksel olarak değişmez (önceki formülü 35040/n_obs
    ile yıllık üs olarak doğru hesaplıyordu). Sharpe DAHA DÜŞÜK ama dürüst.
    """
    # FIX 2026-05-28 (audit-F3): equity'yi günlük aggregate
    if isinstance(equity.index, pd.DatetimeIndex) and len(equity) > 1:
        try:
            daily_equity = equity.resample("1D").last().ffill().dropna()
            if daily_equity.empty:
                daily_equity = equity
        except Exception:
            # tz/freq issue → fallback
            daily_equity = equity
    else:
        daily_equity = equity  # zaten daily veya time-index yok

    ppy = 365  # FIX 2026-05-28 (audit-F3): günlük base, zorlama
    rets = _returns_from_equity(daily_equity)
    sr = sharpe(rets, periods_per_year=ppy)
    so = sortino(rets, periods_per_year=ppy)
    mdd = max_drawdown(equity)  # DD intraday equity üzerinden (peak doğru)
    cm = calmar(daily_equity, periods_per_year=ppy)
    pf = profit_factor(trade_pnls) if trade_pnls is not None else 0.0
    wr = win_rate(trade_pnls) if trade_pnls is not None else 0.0
    ex = expectancy(trade_pnls) if trade_pnls is not None else 0.0
    aw, al = avg_win_loss(trade_pnls) if trade_pnls is not None else (0.0, 0.0)
    skew = float(rets.skew()) if not rets.empty else 0.0
    kurt = float(rets.kurt()) + 3.0 if not rets.empty else 3.0  # excess→raw
    dsr = deflated_sharpe_ratio(
        sr,
        n_trials=n_trials,
        skew=skew,
        kurt=kurt,
        n_obs=len(rets) if not rets.empty else 1,
    )
    cagr = (
        float((daily_equity.iloc[-1] / daily_equity.iloc[0]) ** (ppy / max(len(rets), 1)) - 1.0)
        if not rets.empty and daily_equity.iloc[0] > 0
        else 0.0
    )
    return {
        "sharpe": sr,
        "sortino": so,
        "calmar": cm,
        "max_drawdown": mdd,
        "profit_factor": pf,
        "win_rate": wr,
        "expectancy": ex,
        "avg_win": aw,
        "avg_loss": al,
        "deflated_sharpe": dsr,
        "cagr": cagr,
        "n_trades": float(len(trade_pnls) if trade_pnls is not None else 0),
        "n_obs": float(len(rets)),
    }


__all__ = [
    "ANNUALIZATION",
    "avg_win_loss",
    "calmar",
    "compute_kpis",
    "deflated_sharpe_ratio",
    "expectancy",
    "mae_mfe",
    "max_drawdown",
    "profit_factor",
    "sharpe",
    "sortino",
    "win_rate",
]
