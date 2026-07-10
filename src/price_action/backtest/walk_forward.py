"""Walk-forward + Optuna parametre optimizasyonu + multiple-testing düzeltmesi.

`agents/researcher.md` SOP-3: rolling 3y train / 6m test, step 3m.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field

from price_action.logging_config import logger
from price_action.strategies.base import StrategyManifest

# metrics.compute_kpis ppy=365'i ZORLAR (günlük base) ve n_obs=günlük bar sayısı.
# Sharpe t-testinin per-period sharpe'ı için yıllık sharpe bu değere bölünmeli;
# aksi halde sqrt(365)≈19.1× t-şişmesi olur (P2 lab-istatistik fix). Bu sabit
# metrics.compute_kpis'in zorladığı ppy ile SENKRON kalmalı.
_WF_ANNUALIZATION_PPY = 365.0


# =====================================================================
# Multiple testing correction
# =====================================================================


def multiple_testing_correction(
    pvalues: list[float],
    *,
    method: str = "fdr_bh",
    alpha: float = 0.05,
) -> list[float]:
    """Bonferroni veya Benjamini-Hochberg FDR düzeltmesi.

    `method`:
        "bonferroni": p_adj = min(1, p * n)
        "fdr_bh":     standart BH prosedürü → adj p
    """
    pvals = np.asarray(pvalues, dtype=float)
    n = len(pvals)
    if n == 0:
        return []
    if method == "bonferroni":
        return [float(min(1.0, p * n)) for p in pvals]
    if method == "fdr_bh":
        # Sıralı BH
        order = np.argsort(pvals)
        ranked = pvals[order]
        adj = ranked * n / (np.arange(1, n + 1))
        # Monoton azalan üstten cumulative min
        adj = np.minimum.accumulate(adj[::-1])[::-1]
        adj = np.clip(adj, 0, 1)
        # Orjinal sıraya geri koy
        out = np.empty_like(adj)
        out[order] = adj
        return [float(x) for x in out]
    raise ValueError(f"unsupported method: {method}")


# =====================================================================
# Result schema
# =====================================================================


class FoldResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    fold_id: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    best_params: dict[str, Any]
    train_kpis: dict[str, float]
    test_kpis: dict[str, float]


class WFResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    strategy_name: str
    n_folds: int
    folds: list[FoldResult]
    aggregate_kpis: dict[str, float]
    n_trials_total: int
    pvalues_adjusted: list[float] = Field(default_factory=list)


# =====================================================================
# WalkForward
# =====================================================================


class WalkForward:
    """Rolling walk-forward + Optuna optimizasyonu."""

    def __init__(
        self,
        *,
        train_years: int = 2,
        test_months: int = 6,
        step_months: int = 3,
        n_trials: int = 50,
        objective: str = "oos_sharpe",
        engine_factory: Callable[[], Any] | None = None,
        loader: Callable[[str, str, datetime, datetime], Any] | None = None,
    ) -> None:
        self.train_years = train_years
        self.test_months = test_months
        self.step_months = step_months
        self.n_trials = n_trials
        self.objective = objective
        self.engine_factory = engine_factory
        self.loader = loader
        self._log = logger.bind(component="walk_forward")

    # ----- core -----
    def run(
        self,
        strategy_yaml: str | Path,
        *,
        universe: list[str],
        start: datetime,
        end: datetime,
        param_space: dict[str, dict[str, Any]] | None = None,
    ) -> WFResult:
        """Walk-forward yürüt."""
        from price_action.backtest.engine import BacktestEngine

        if self.engine_factory is None:
            self.engine_factory = BacktestEngine
        with Path(strategy_yaml).open("r", encoding="utf-8") as f:
            base_manifest_raw = yaml.safe_load(f)
        if param_space is None:
            param_space = base_manifest_raw.get("walk_forward", {}).get("parameter_space", {}) or {}

        folds = self._build_folds(start, end)
        fold_results: list[FoldResult] = []
        n_trials_total = 0
        for f_id, (tr_s, tr_e, te_s, te_e) in enumerate(folds):
            self._log.bind(fold=f_id, train=(tr_s, tr_e), test=(te_s, te_e)).info("wf.fold.start")
            best_params, train_kpis, n_trials = self._optimize_fold(
                base_manifest_raw=base_manifest_raw,
                universe=universe,
                tr_s=tr_s,
                tr_e=tr_e,
                param_space=param_space,
            )
            n_trials_total += n_trials
            test_kpis = self._evaluate(
                base_manifest_raw,
                best_params,
                universe,
                te_s,
                te_e,
            )
            fold_results.append(
                FoldResult(
                    fold_id=f_id,
                    train_start=tr_s,
                    train_end=tr_e,
                    test_start=te_s,
                    test_end=te_e,
                    best_params=best_params,
                    train_kpis=train_kpis,
                    test_kpis=test_kpis,
                )
            )

        # Agrega
        agg = self._aggregate(fold_results)
        # P-value yaklaşığı: her fold'un sharpe'ından yapılan tek-örneklem t test
        pvalues = self._approx_pvalues(fold_results)
        pvals_adj = multiple_testing_correction(pvalues, method="fdr_bh")

        return WFResult(
            strategy_name=base_manifest_raw.get("name", "unknown"),
            n_folds=len(fold_results),
            folds=fold_results,
            aggregate_kpis=agg,
            n_trials_total=n_trials_total,
            pvalues_adjusted=pvals_adj,
        )

    # ----- folds -----
    def _build_folds(
        self, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime, datetime, datetime]]:
        out = []
        train_delta = timedelta(days=self.train_years * 365)
        test_delta = timedelta(days=self.test_months * 30)
        step_delta = timedelta(days=self.step_months * 30)

        cursor = start
        while cursor + train_delta + test_delta <= end:
            tr_s = cursor
            tr_e = cursor + train_delta
            te_s = tr_e
            te_e = tr_e + test_delta
            out.append((tr_s, tr_e, te_s, te_e))
            cursor += step_delta
        return out

    # ----- optimization -----
    def _optimize_fold(
        self,
        *,
        base_manifest_raw: dict[str, Any],
        universe: list[str],
        tr_s: datetime,
        tr_e: datetime,
        param_space: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, float], int]:
        try:
            import optuna
        except ImportError:
            self._log.warning("optuna_not_installed_using_default_params")
            kpis = self._evaluate(base_manifest_raw, {}, universe, tr_s, tr_e)
            return {}, kpis, 1

        def objective(trial: optuna.Trial) -> float:
            params: dict[str, Any] = {}
            for key, spec in param_space.items():
                t = spec.get("type", "float")
                low = spec["low"]
                high = spec["high"]
                step = spec.get("step")
                if t == "int":
                    params[key] = trial.suggest_int(key, int(low), int(high), step=int(step or 1))
                else:
                    params[key] = trial.suggest_float(key, float(low), float(high), step=step)
            kpis = self._evaluate(base_manifest_raw, params, universe, tr_s, tr_e)
            target = kpis.get(self._objective_key(), 0.0)
            return float(target)

        try:
            study = optuna.create_study(
                direction="maximize",
                sampler=optuna.samplers.TPESampler(seed=42),
                pruner=optuna.pruners.MedianPruner(),
            )
            study.optimize(objective, n_trials=self.n_trials, show_progress_bar=False)
            best = dict(study.best_params)
            # Tekrar değerlendir (KPI seti almak için)
            train_kpis = self._evaluate(base_manifest_raw, best, universe, tr_s, tr_e)
            return best, train_kpis, len(study.trials)
        except Exception as exc:
            self._log.bind(err=str(exc)).warning("optuna.error_falling_back")
            kpis = self._evaluate(base_manifest_raw, {}, universe, tr_s, tr_e)
            return {}, kpis, 1

    def _objective_key(self) -> str:
        return {
            "oos_sharpe": "sharpe",
            "calmar": "calmar",
            "profit_factor": "profit_factor",
        }.get(self.objective, "sharpe")

    # ----- single backtest -----
    def _evaluate(
        self,
        base_raw: dict[str, Any],
        params: dict[str, Any],
        universe: list[str],
        s: datetime,
        e: datetime,
    ) -> dict[str, float]:
        raw = deepcopy(base_raw)
        for key, val in params.items():
            _set_dotted(raw, key, val)
        manifest = StrategyManifest.model_validate(raw)
        from price_action.strategies.classic_pa import ClassicPriceActionStrategy

        strat = ClassicPriceActionStrategy(manifest)
        engine = self.engine_factory()  # type: ignore[misc]
        if self.loader is not None and getattr(engine, "store_load", None) is None:
            engine.store_load = self.loader
        timeframe = manifest.timeframes.decision
        try:
            result = engine.run(
                strat,
                universe,
                start=s,
                end=e,
                fees=manifest.backtest.fees,
                slippage_bps=manifest.backtest.slippage_bps,
                initial_capital=manifest.backtest.initial_capital_usdt,
                timeframe=timeframe,
            )
            return result.kpis
        except Exception as exc:  # pragma: no cover
            logger.bind(err=str(exc)).warning("wf._evaluate.fail")
            return {"sharpe": 0.0, "calmar": 0.0, "max_drawdown": 0.0}

    # ----- aggregate -----
    @staticmethod
    def _aggregate(folds: list[FoldResult]) -> dict[str, float]:
        if not folds:
            return {}
        # OOS metriklerinin ortalaması + min + pos slice ratio
        keys = set().union(*[f.test_kpis.keys() for f in folds])
        agg: dict[str, float] = {}
        for k in keys:
            vals = [f.test_kpis.get(k, 0.0) for f in folds]
            agg[f"oos_{k}_mean"] = float(np.mean(vals))
            agg[f"oos_{k}_min"] = float(np.min(vals))
            agg[f"oos_{k}_max"] = float(np.max(vals))
        # In-sample / out-of-sample tutarlılığı
        train_sr = [f.train_kpis.get("sharpe", 0.0) for f in folds]
        oos_sr = [f.test_kpis.get("sharpe", 0.0) for f in folds]
        agg["wf_positive_slice_ratio"] = float(np.mean([1.0 if x > 0 else 0.0 for x in oos_sr]))
        if train_sr and np.mean(train_sr) != 0:
            agg["is_oos_consistency"] = float(np.mean(oos_sr) / np.mean(train_sr))
        return agg

    @staticmethod
    def _approx_pvalues(folds: list[FoldResult]) -> list[float]:
        """Her fold için kaba p-value yaklaşımı.

        Sharpe'ı normalize edip 1-sided test (daha iyi yaklaşım için
        fold içi günlük returns gerekir). Burada ground-truth değil placeholder."""
        out = []
        for f in folds:
            sr = f.test_kpis.get("sharpe", 0.0)
            n = max(f.test_kpis.get("n_obs", 1.0), 1.0)
            # FIX 2026-07-10 (P2 lab-istatistik, WF p-değeri 19× şişme): sr YILLIK
            # (compute_kpis ppy=365 zorlar), n GÜNLÜK bar sayısı. Sharpe t-testi
            # PER-PERIOD sharpe ister; yıllık sr'yi doğrudan koymak annualization
            # sqrt'ini İKİ KEZ uygular → t sqrt(365)=19.1× şişer → tüm p→0 → FDR
            # her şeyi "anlamlı" onaylar. Doğru: t = (sr/sqrt(ppy))*sqrt(n)=sr*sqrt(n/ppy).
            t = sr * np.sqrt(n / _WF_ANNUALIZATION_PPY)
            # 1-sided: P(Z > t)
            from math import erf, sqrt

            p = 0.5 * (1 - erf(t / sqrt(2)))
            out.append(float(p))
        return out


def _set_dotted(d: dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    cur = d
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


__all__ = [
    "FoldResult",
    "WFResult",
    "WalkForward",
    "multiple_testing_correction",
]
