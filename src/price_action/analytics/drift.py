"""Drift detection — canlı dağılım vs backtest dağılımı.

Lab Scientist haftalık çalıştırır; eşik aşılırsa Researcher'a uyarı gider.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from price_action.logging_config import logger


@dataclass(frozen=True)
class DriftReport:
    """KS / Welch t / Levene test sonuçları + Bonferroni düzeltmeli p-value."""

    ks_stat: float
    ks_p: float
    welch_t: float
    welch_p: float
    levene_stat: float
    levene_p: float
    n_live: int
    n_backtest: int
    mean_live: float
    mean_backtest: float
    std_live: float
    std_backtest: float
    bonferroni_alpha: float = 0.05
    bonferroni_adjusted_alpha: float = field(init=False)
    drift_detected: bool = field(init=False)
    flagged_tests: list[str] = field(init=False)

    def __post_init__(self) -> None:
        # 3 test → Bonferroni
        n_tests = 3
        adj = self.bonferroni_alpha / n_tests
        flagged: list[str] = []
        if self.ks_p < adj:
            flagged.append("ks")
        if self.welch_p < adj:
            flagged.append("welch_t")
        if self.levene_p < adj:
            flagged.append("levene")
        # frozen dataclass — __setattr__ via object
        object.__setattr__(self, "bonferroni_adjusted_alpha", adj)
        object.__setattr__(self, "flagged_tests", flagged)
        object.__setattr__(self, "drift_detected", len(flagged) > 0)

    def as_dict(self) -> dict:
        d = {
            "ks_stat": self.ks_stat,
            "ks_p": self.ks_p,
            "welch_t": self.welch_t,
            "welch_p": self.welch_p,
            "levene_stat": self.levene_stat,
            "levene_p": self.levene_p,
            "n_live": self.n_live,
            "n_backtest": self.n_backtest,
            "mean_live": self.mean_live,
            "mean_backtest": self.mean_backtest,
            "std_live": self.std_live,
            "std_backtest": self.std_backtest,
            "bonferroni_alpha": self.bonferroni_alpha,
            "bonferroni_adjusted_alpha": self.bonferroni_adjusted_alpha,
            "drift_detected": self.drift_detected,
            "flagged_tests": list(self.flagged_tests),
        }
        return d


def _to_clean_array(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        x = x.values
    arr = np.asarray(x, dtype=float)
    arr = arr[np.isfinite(arr)]
    return arr


def detect_drift(
    live_returns,
    backtest_returns,
    *,
    alpha: float = 0.05,
) -> DriftReport:
    """KS, Welch's t, Levene testleri + Bonferroni adjusted alpha.

    Boş/yetersiz örnekte tüm p-değerler 1.0 ile döner (drift değil).
    """
    live = _to_clean_array(live_returns)
    bt = _to_clean_array(backtest_returns)

    if live.size < 5 or bt.size < 5:
        logger.warning(
            "drift.insufficient_samples",
            extra={"n_live": int(live.size), "n_bt": int(bt.size)},
        )
        return DriftReport(
            ks_stat=0.0, ks_p=1.0,
            welch_t=0.0, welch_p=1.0,
            levene_stat=0.0, levene_p=1.0,
            n_live=int(live.size), n_backtest=int(bt.size),
            mean_live=float(live.mean()) if live.size else 0.0,
            mean_backtest=float(bt.mean()) if bt.size else 0.0,
            std_live=float(live.std(ddof=1)) if live.size > 1 else 0.0,
            std_backtest=float(bt.std(ddof=1)) if bt.size > 1 else 0.0,
            bonferroni_alpha=alpha,
        )

    ks = stats.ks_2samp(live, bt)
    welch = stats.ttest_ind(live, bt, equal_var=False)
    lev = stats.levene(live, bt, center="median")

    return DriftReport(
        ks_stat=float(ks.statistic),
        ks_p=float(ks.pvalue),
        welch_t=float(welch.statistic),
        welch_p=float(welch.pvalue),
        levene_stat=float(lev.statistic),
        levene_p=float(lev.pvalue),
        n_live=int(live.size),
        n_backtest=int(bt.size),
        mean_live=float(live.mean()),
        mean_backtest=float(bt.mean()),
        std_live=float(live.std(ddof=1)),
        std_backtest=float(bt.std(ddof=1)),
        bonferroni_alpha=alpha,
    )
