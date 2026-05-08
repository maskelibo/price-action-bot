"""Vol-target sizing testleri."""
from __future__ import annotations

import pytest

from price_action.risk.vol_target import (
    VolTargetConfig,
    apply_vol_target,
    from_risk_yaml,
    vol_target_factor,
)


class TestVolTargetFactor:
    def test_disabled_returns_one(self):
        cfg = VolTargetConfig(enabled=False)
        assert vol_target_factor(0.05, cfg) == 1.0

    def test_target_equals_current(self):
        cfg = VolTargetConfig(enabled=True, target_atr_pct=0.04)
        assert vol_target_factor(0.04, cfg) == 1.0

    def test_high_vol_reduces_size(self):
        cfg = VolTargetConfig(enabled=True, target_atr_pct=0.04)
        # ATR %8 → factor 0.5
        assert vol_target_factor(0.08, cfg) == 0.5

    def test_low_vol_boosts_size(self):
        cfg = VolTargetConfig(enabled=True, target_atr_pct=0.04, max_factor=1.5)
        # ATR %2 → factor 2.0 → clamped to 1.5
        assert vol_target_factor(0.02, cfg) == 1.5

    def test_extreme_high_vol_clamped(self):
        cfg = VolTargetConfig(enabled=True, target_atr_pct=0.04, min_factor=0.2)
        # ATR %50 → factor 0.08 → clamped to 0.2
        assert vol_target_factor(0.50, cfg) == 0.2

    def test_zero_atr_returns_one(self):
        cfg = VolTargetConfig(enabled=True, target_atr_pct=0.04)
        assert vol_target_factor(0.0, cfg) == 1.0

    def test_negative_target_returns_one(self):
        cfg = VolTargetConfig(enabled=True, target_atr_pct=-1.0)
        assert vol_target_factor(0.04, cfg) == 1.0

    def test_within_bounds(self):
        cfg = VolTargetConfig(enabled=True, target_atr_pct=0.04, min_factor=0.5, max_factor=2.0)
        # ATR %5 → factor 0.8 (range içinde)
        assert vol_target_factor(0.05, cfg) == pytest.approx(0.8)


class TestApplyVolTarget:
    def test_disabled_pass_through(self):
        cfg = VolTargetConfig(enabled=False)
        assert apply_vol_target(100.0, 0.10, cfg) == 100.0

    def test_high_vol_reduces_risk(self):
        cfg = VolTargetConfig(enabled=True, target_atr_pct=0.04)
        # base $100, ATR %8 → factor 0.5 → $50
        assert apply_vol_target(100.0, 0.08, cfg) == 50.0

    def test_low_vol_boosts_risk_capped(self):
        cfg = VolTargetConfig(enabled=True, target_atr_pct=0.04, max_factor=1.5)
        # base $100, ATR %2 → factor 1.5 (clamped) → $150
        assert apply_vol_target(100.0, 0.02, cfg) == 150.0


class TestFromRiskYaml:
    def test_full_config(self):
        cfg = from_risk_yaml({
            "vol_target": {
                "enabled": True,
                "target_atr_pct": 0.05,
                "min_factor": 0.30,
                "max_factor": 2.00,
            }
        })
        assert cfg.enabled is True
        assert cfg.target_atr_pct == 0.05
        assert cfg.min_factor == 0.30
        assert cfg.max_factor == 2.00

    def test_missing_section_defaults(self):
        cfg = from_risk_yaml({})
        assert cfg.enabled is False
        assert cfg.target_atr_pct == 0.04

    def test_partial_section(self):
        cfg = from_risk_yaml({"vol_target": {"enabled": True}})
        assert cfg.enabled is True
        assert cfg.target_atr_pct == 0.04  # default

    def test_disabled_explicit(self):
        cfg = from_risk_yaml({"vol_target": {"enabled": False, "target_atr_pct": 0.05}})
        assert cfg.enabled is False
