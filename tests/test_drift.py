"""Drift detection — KS test sentetik benzer/farklı dağılımlarda."""
from __future__ import annotations

import numpy as np
import pytest

from price_action.analytics.drift import detect_drift


def test_drift_similar_distributions_no_drift():
    rng = np.random.default_rng(42)
    a = rng.normal(0, 1, size=500)
    b = rng.normal(0, 1, size=500)
    rep = detect_drift(a, b)
    # Yaklaşık aynı dağılım — drift bayrağı kalkmamalı
    assert rep.drift_detected is False
    assert rep.ks_p > rep.bonferroni_adjusted_alpha


def test_drift_different_means_detected():
    rng = np.random.default_rng(7)
    a = rng.normal(0.0, 1.0, size=500)
    b = rng.normal(2.0, 1.0, size=500)
    rep = detect_drift(a, b)
    assert rep.drift_detected is True
    assert "ks" in rep.flagged_tests or "welch_t" in rep.flagged_tests


def test_drift_different_variances_detected():
    rng = np.random.default_rng(11)
    a = rng.normal(0, 1, size=500)
    b = rng.normal(0, 4, size=500)
    rep = detect_drift(a, b)
    assert rep.drift_detected is True
    assert "levene" in rep.flagged_tests


def test_drift_insufficient_samples():
    rep = detect_drift([0.1, 0.2], [0.3, 0.4])
    assert rep.drift_detected is False
    assert rep.ks_p == 1.0


def test_drift_report_as_dict_has_keys():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, size=100)
    b = rng.normal(0, 1, size=100)
    rep = detect_drift(a, b)
    d = rep.as_dict()
    for key in (
        "ks_stat",
        "ks_p",
        "welch_t",
        "welch_p",
        "levene_stat",
        "levene_p",
        "n_live",
        "n_backtest",
        "drift_detected",
        "flagged_tests",
        "bonferroni_adjusted_alpha",
    ):
        assert key in d


def test_bonferroni_alpha_division():
    rep = detect_drift(
        np.linspace(-1, 1, 100), np.linspace(-1, 1, 100), alpha=0.06
    )
    assert rep.bonferroni_adjusted_alpha == pytest.approx(0.02)
