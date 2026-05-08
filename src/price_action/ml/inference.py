"""ML filter inference — sinyal kabul / red kararı.

Walk-forward eğitimden çıkan en son modeli yükler, feature satırı ile
`accept(signal, features) -> (bool, prob)` döner.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger


class MLFilter:
    """Sinyal sonrası geç-aşama filtre."""

    def __init__(self, model_path: Path | str | None = None, *, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self.model: Any = None
        self.feature_names: list[str] = []
        self.trained_until = None
        if model_path:
            self.load(model_path)

    def load(self, model_path: Path | str) -> None:
        path = Path(model_path)
        if not path.exists():
            logger.warning("mlfilter.no_model", extra={"path": str(path)})
            return
        bundle = joblib.load(path)
        self.model = bundle["model"]
        self.feature_names = list(bundle.get("feature_names", []))
        self.trained_until = bundle.get("trained_until")
        logger.info(
            "mlfilter.loaded",
            extra={"path": str(path), "n_features": len(self.feature_names)},
        )

    def is_ready(self) -> bool:
        return self.model is not None

    def accept(
        self,
        signal: Signal,
        features: pd.Series | dict | pd.DataFrame,
    ) -> tuple[bool, float]:
        """Sinyali kabul edersen `(True, prob)`, aksi halde `(False, prob)`.

        Model yoksa pas geçer (sinyali kabul eder, prob=0.5 döner).
        """
        if self.model is None:
            return True, 0.5

        x = self._features_to_vector(features)
        try:
            prob = float(self.model.predict_proba(x.reshape(1, -1))[0, 1])
        except Exception as exc:
            logger.warning(
                "mlfilter.predict_failed",
                extra={"err": str(exc)[:200], "signal": signal.fingerprint()},
            )
            return True, 0.5
        accepted = prob >= self.threshold
        logger.debug(
            "mlfilter.decision",
            extra={"signal": signal.fingerprint(), "prob": prob, "accept": accepted},
        )
        return accepted, prob

    def _features_to_vector(self, features) -> np.ndarray:
        if isinstance(features, pd.DataFrame):
            row = features.iloc[-1]
        elif isinstance(features, pd.Series):
            row = features
        elif isinstance(features, dict):
            row = pd.Series(features, dtype=float)
        else:
            raise TypeError(f"unsupported features type: {type(features)!r}")
        if self.feature_names:
            arr = np.array([float(row.get(c, 0.0)) for c in self.feature_names], dtype=float)
        else:
            arr = row.to_numpy(dtype=float)
        # NaN safe
        arr = np.where(np.isfinite(arr), arr, 0.0)
        return arr
