"""Faz 14.27 #3 fix: config adapter — 3 schema parity testleri."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class TestConfigAdapter:
    """3 schema → canonical normalize doğru çalışıyor."""

    def test_backtest_flat_to_canonical(self):
        from price_action.config import from_backtest_flat
        flat = {
            "risk_pct": 0.005,
            "max_concurrent": 4,
            "consecutive_loss_pause": 3,
            "daily_dd_halt": 0.025,
            "tp_r": 1.5,
        }
        c = from_backtest_flat(flat)
        assert c.risk_per_trade == 0.005
        assert c.max_open_positions == 4
        assert c.consecutive_losses == 3
        assert c.daily_loss_pct == 0.025
        assert c.tp_r == 1.5

    def test_iterate_equity_to_canonical(self):
        from price_action.config import from_iterate_equity
        equity = {
            "risk_pct": 0.005,
            "max_concurrent": 8,
            "consecutive_loss_pause": 3,
            "daily_dd_halt": 0.02,
        }
        c = from_iterate_equity(equity, tp_r=3.0)
        assert c.risk_per_trade == 0.005
        assert c.max_open_positions == 8
        assert c.consecutive_losses == 3
        assert c.tp_r == 3.0

    def test_live_yaml_canonical_roundtrip(self):
        """LIVE YAML → canonical → YAML dump → load → same canonical."""
        from price_action.config import from_live_yaml, to_live_yaml_dict
        live_cfg = {
            "position_sizing": {"risk_per_trade": 0.005, "backtest_risk_pct": 0.005},
            "concentration_limits": {"max_open_positions": 16, "max_per_symbol_pct": 0.15},
            "drawdown_breakers": {
                "daily_loss_pct": 0.02, "weekly_loss_pct": 0.05,
                "consecutive_losses": 5,
            },
            "execution": {"sl_pct_min": 0.025},
        }
        c1 = from_live_yaml(live_cfg)
        dumped = to_live_yaml_dict(c1)
        c2 = from_live_yaml(dumped)
        assert c1.risk_per_trade == c2.risk_per_trade
        assert c1.max_open_positions == c2.max_open_positions
        assert c1.consecutive_losses == c2.consecutive_losses
        assert c1.sl_pct_min == c2.sl_pct_min

    def test_v63_actual_config_canonical(self):
        """v63 actual config → canonical → expected values."""
        from price_action.config import from_live_yaml
        c = from_live_yaml(ROOT / "configs/risk_phoenix_scalp_15m_rsi2_v63.yaml")
        assert c.risk_per_trade == 0.005
        assert c.max_open_positions == 8
        assert c.consecutive_losses == 3
        assert c.consecutive_loss_pause_days == 1.0

    def test_v11_actual_config_canonical(self):
        """v11 actual config → canonical → expected values."""
        from price_action.config import from_live_yaml
        c = from_live_yaml(ROOT / "configs/risk_phoenix_scalp_15m_vwap_v11.yaml")
        assert c.risk_per_trade == 0.005
        assert c.max_open_positions == 4
        assert c.consecutive_losses == 2

    def test_validation_catches_backtest_only_keys(self):
        """v63 backtest_only key'ler tespit ediyor mu (warning)?"""
        from price_action.config import from_live_yaml, validate_canonical
        # Backtest-only key'leri olan bir config simüle
        cfg_with_legacy = {
            "position_sizing": {"risk_per_trade": 0.005},
            "concentration_limits": {"max_open_positions": 4},
            "drawdown_breakers": {"daily_loss_pct": 0.04, "consecutive_losses": 2},
            "execution": {"sl_pct_min": 0.0, "tp_r": 3.0},  # backtest-only key
            "strategy_portfolio": {
                "max_concurrent_positions": 4,
                "consecutive_loss_pause_n": 2,
            },
        }
        c = from_live_yaml(cfg_with_legacy)
        errors = validate_canonical(c)
        # En az 1 WARNING (backtest-only keys present)
        assert any("backtest-only" in e for e in errors), f"Errors: {errors}"

    def test_validation_passes_clean_canonical(self):
        """Temiz canonical config → 0 error."""
        from price_action.config import from_live_yaml, validate_canonical
        c = from_live_yaml({
            "position_sizing": {"risk_per_trade": 0.005},
            "concentration_limits": {"max_open_positions": 8},
            "drawdown_breakers": {"daily_loss_pct": 0.04, "consecutive_losses": 3},
            "execution": {"sl_pct_min": 0.0},
        })
        errors = validate_canonical(c)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_lab_iterate_v9_matches_v11(self):
        """iterate v9 (risk_pct=0.005, max_concurrent=4, consecutive=2) → v11 ile aynı."""
        from price_action.config import from_iterate_equity, from_live_yaml
        v9 = from_iterate_equity({
            "risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 2,
        }, tp_r=1.5)
        v11_live = from_live_yaml(ROOT / "configs/risk_phoenix_scalp_15m_vwap_v11.yaml")
        # Backtest v9 ile LIVE v11 aynı semantic config olmalı (parity)
        assert v9.risk_per_trade == v11_live.risk_per_trade
        assert v9.max_open_positions == v11_live.max_open_positions
        assert v9.consecutive_losses == v11_live.consecutive_losses
