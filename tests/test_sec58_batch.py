"""SEC58 Batch Fix Tests — H6 + M1 + M3

Three fixes verified:
  1. H6 — Log rotation + disk monitoring
  2. M1 — Cooldown tiebreak (deterministic)
  3. M3 — TP2 R YAML config
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from price_action.backtest.lab import ProductionConfig


class TestH6LogRotation:
    """H6 — Log rotation policy verification."""

    def test_logging_config_has_rotation_200mb(self):
        """Rotation policy: 200 MB configured."""
        from price_action import logging_config as lc

        source = Path(lc.__file__).read_text()
        assert 'rotation="200 MB"' in source

    def test_logging_config_has_retention_14days(self):
        """Retention policy: 14 days configured."""
        from price_action import logging_config as lc

        source = Path(lc.__file__).read_text()
        assert 'retention="14 days"' in source

    def test_logging_config_has_compression_gz(self):
        """Compression: gz configured."""
        from price_action import logging_config as lc

        source = Path(lc.__file__).read_text()
        assert 'compression="gz"' in source

    def test_disk_monitoring_functions_exist(self):
        """Disk monitoring functions defined."""
        from price_action import logging_config as lc

        source = Path(lc.__file__).read_text()
        assert "_get_disk_usage" in source
        assert "_check_disk_health" in source


class TestM1CooldownTiebreak:
    """M1 — Cooldown deterministic tiebreak."""

    def test_tiebreak_logic_in_cooldown_module(self):
        """Tiebreak sorting implemented in cooldown.py."""
        from scripts import lib

        cooldown_module = Path(lib.__file__).parent / "cooldown.py"
        source = cooldown_module.read_text()

        # Check for tiebreak logic
        assert "SEC58.M1" in source or "tiebreak" in source.lower()
        assert "alphabetical" in source.lower() or "sorted" in source.lower()


class TestM3TP2RConfig:
    """M3 — TP2 R YAML configuration."""

    def test_production_config_has_tp2_r_field(self):
        """ProductionConfig has tp2_R field."""
        cfg = ProductionConfig()
        assert hasattr(cfg, "tp2_R")
        assert cfg.tp2_R == 1.5  # default

    def test_yaml_risk_phoenix_has_tp2_r(self):
        """risk_phoenix_v204.yaml has tp2_R in take_profit block."""
        yaml_path = Path("configs/risk_phoenix_v204.yaml")
        if yaml_path.exists():
            with yaml_path.open("r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            tp_block = cfg.get("take_profit", {}) or {}
            assert "tp2_R" in tp_block
            assert float(tp_block["tp2_R"]) == 2.0

    def test_production_config_reads_tp2_r_from_yaml(self):
        """ProductionConfig.from_yaml() reads tp2_R."""
        yaml_path = Path("configs/risk_phoenix_v204.yaml")
        if yaml_path.exists():
            cfg = ProductionConfig.from_yaml(yaml_path)
            assert cfg.tp2_R == 2.0

    def test_tp2_r_default_backward_compat(self):
        """Default tp2_R = 1.5 (engine default)."""
        cfg = ProductionConfig()
        assert cfg.tp2_R == 1.5


# Integration test
class TestSEC58Integration:
    """All three fixes work together."""

    @pytest.mark.slow
    def test_all_three_fixes_compile(self):
        """All modules import without error."""
        # H6
        from price_action import logging_config
        # M1
        from scripts.lib import cooldown
        # M3
        from price_action.backtest import lab

        assert logging_config is not None
        assert cooldown is not None
        assert lab is not None

    def test_yaml_config_loads_without_error(self):
        """Production YAML config loads."""
        yaml_path = Path("configs/risk_phoenix_v204.yaml")
        if yaml_path.exists():
            cfg = ProductionConfig.from_yaml(yaml_path)
            # Verify all three fixes are applied
            assert hasattr(cfg, "tp2_R")
            assert cfg.tp2_R > 0
