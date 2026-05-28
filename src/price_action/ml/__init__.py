"""ML — feature builder, walk-forward XGBoost trainer, inference wrapper.

FIX 2026-05-28 (Faz 14.27 #2): Lazy import + graceful degrade.
Önceki bug: eager `from .train_filter import ...` xgboost'u her zaman
yükleliyordu → libomp.dylib eksikse SubModule import (örn meta_labeling) de
crash ediyordu → test_meta_labeling collection FAIL.

Şimdi: features eager (xgboost YOK), train_filter + inference lazy
(__getattr__ on-demand). xgboost yoksa ML training devre dışı ama diğer ML
fonksiyonları (features, meta_labeling) çalışır.
"""
from __future__ import annotations

from .features import FeatureSpec, build_features

__all__ = [
    "build_features",
    "FeatureSpec",
    "train_walk_forward",
    "WalkForwardSplit",
    "MLFilter",
]


def __getattr__(name: str):
    """Lazy import — xgboost gerektirenler sadece çağrılınca yüklenir."""
    if name in ("train_walk_forward", "WalkForwardSplit"):
        from .train_filter import WalkForwardSplit, train_walk_forward
        return {"train_walk_forward": train_walk_forward,
                "WalkForwardSplit": WalkForwardSplit}[name]
    if name == "MLFilter":
        from .inference import MLFilter
        return MLFilter
    raise AttributeError(f"module 'price_action.ml' has no attribute {name!r}")
