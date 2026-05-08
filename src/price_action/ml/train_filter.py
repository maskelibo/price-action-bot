"""Walk-forward XGBoost training — backtest trade'lerini "kâr/zarar" sınıflarına ayırma.

Sızıntısız chained walk-forward: train pencereleri tarihte ilerler, test pencereleri
hep geleceğe bakar; bir test bar'ı bir sonraki turun train'ine dahil olur.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from price_action.logging_config import logger

try:
    import xgboost as xgb
except ImportError:  # pragma: no cover
    xgb = None


@dataclass(frozen=True)
class WalkForwardSplit:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass
class WalkForwardModel:
    """Tek dilim — sınıflandırıcı + dönem + metrik."""

    model: Any
    split: WalkForwardSplit
    train_size: int
    test_size: int
    test_accuracy: float
    test_auc: float
    feature_names: list[str]


def make_walk_forward_splits(
    index: pd.DatetimeIndex,
    *,
    train_size: int,
    test_size: int,
    step: int | None = None,
) -> list[WalkForwardSplit]:
    """Index üzerinde train_size + test_size pencereleri kaydır.

    `step` verilmezse `test_size` kadar kayar (chained, non-overlap test'ler).
    """
    if len(index) < train_size + test_size:
        return []
    step = step or test_size
    out: list[WalkForwardSplit] = []
    start = 0
    while start + train_size + test_size <= len(index):
        tr_s = index[start]
        tr_e = index[start + train_size - 1]
        te_s = index[start + train_size]
        te_e = index[start + train_size + test_size - 1]
        out.append(WalkForwardSplit(tr_s, tr_e, te_s, te_e))
        start += step
    return out


def train_walk_forward(
    features_df: pd.DataFrame,
    labels: pd.Series,
    splits: list[WalkForwardSplit] | None = None,
    *,
    train_size: int = 200,
    test_size: int = 60,
    xgb_params: dict | None = None,
    save_dir: Path | str | None = None,
) -> list[WalkForwardModel]:
    """Walk-forward chained eğitim.

    `features_df` — index=DateTime. `labels` — aynı index, 0/1.
    `splits` verilmezse `train_size`/`test_size` ile otomatik üretilir.

    Her dilim için ayrı model fit edilir; `save_dir` verildiyse joblib ile diske
    yazılır (`fold_<i>.joblib`).
    """
    if xgb is None:
        raise RuntimeError("xgboost yüklü değil — `pip install xgboost`")
    if features_df is None or features_df.empty:
        return []

    df = features_df.copy().sort_index()
    y = labels.reindex(df.index).astype(int)
    df = df.loc[y.dropna().index]
    y = y.loc[df.index]

    if splits is None:
        splits = make_walk_forward_splits(df.index, train_size=train_size, test_size=test_size)
    if not splits:
        logger.warning("train_walk_forward.no_splits", extra={"n": len(df)})
        return []

    params = {
        "max_depth": 4,
        "learning_rate": 0.05,
        "n_estimators": 200,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "n_jobs": 1,
        "random_state": 42,
        "tree_method": "hist",
    }
    if xgb_params:
        params.update(xgb_params)

    feat_cols = list(df.columns)
    out: list[WalkForwardModel] = []
    for i, sp in enumerate(splits):
        train_mask = (df.index >= sp.train_start) & (df.index <= sp.train_end)
        test_mask = (df.index >= sp.test_start) & (df.index <= sp.test_end)
        X_tr, y_tr = df.loc[train_mask, feat_cols], y.loc[train_mask]
        X_te, y_te = df.loc[test_mask, feat_cols], y.loc[test_mask]
        if len(X_tr) < 20 or len(X_te) < 5:
            logger.debug("train_walk_forward.skip_small", extra={"i": i})
            continue
        # Sınıf dengesizliği
        pos = float((y_tr == 1).sum())
        neg = float((y_tr == 0).sum())
        spw = (neg / pos) if pos > 0 else 1.0
        model = xgb.XGBClassifier(scale_pos_weight=spw, **params)
        model.fit(X_tr.values, y_tr.values)
        prob = model.predict_proba(X_te.values)[:, 1]
        pred = (prob >= 0.5).astype(int)
        acc = float((pred == y_te.values).mean()) if len(y_te) else 0.0
        auc = _safe_auc(y_te.values, prob)
        wfm = WalkForwardModel(
            model=model,
            split=sp,
            train_size=int(len(X_tr)),
            test_size=int(len(X_te)),
            test_accuracy=acc,
            test_auc=auc,
            feature_names=feat_cols,
        )
        out.append(wfm)
        logger.info(
            "train_walk_forward.fold_done",
            extra={"i": i, "acc": acc, "auc": auc, "n_tr": len(X_tr), "n_te": len(X_te)},
        )
        if save_dir:
            save_path = Path(save_dir)
            save_path.mkdir(parents=True, exist_ok=True)
            joblib.dump(
                {
                    "model": model,
                    "split": sp,
                    "feature_names": feat_cols,
                    "metrics": {"accuracy": acc, "auc": auc},
                },
                save_path / f"fold_{i:02d}.joblib",
            )
    return out


def _safe_auc(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    if len(np.unique(y_true)) < 2:
        return 0.5
    try:
        from sklearn.metrics import roc_auc_score

        return float(roc_auc_score(y_true, y_prob))
    except Exception:
        return 0.5


def save_final_model(models: list[WalkForwardModel], path: Path | str) -> None:
    """En son dilimin modelini "production" olarak kaydet."""
    if not models:
        raise ValueError("hiç eğitilmiş model yok")
    last = models[-1]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": last.model,
            "feature_names": last.feature_names,
            "trained_until": last.split.test_end,
        },
        path,
    )
    logger.info("train_walk_forward.saved", extra={"path": str(path)})
