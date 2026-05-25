"""Volatility-targeted sizing (port from src/price_action/risk/vol_target.py).

Concept: scale risk_per_trade by target_atr_pct / current_atr_pct, clamped.
- High vol → smaller positions (capital protection)
- Low vol → larger positions (opportunity capture)

Crypto test: 1.7× σ reduction with ~10% return drop — robust risk-adj uplift.
Forex expect: similar uplift on JPY pairs (more vol regimes), modest on majors.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VolTargetConfig:
    enabled: bool = False
    target_atr_pct: float = 0.0015  # forex 15m: 0.15% typical
    min_factor: float = 0.20
    max_factor: float = 1.50


def vol_target_factor(atr_pct_at_entry: float, config: VolTargetConfig) -> float:
    if not config.enabled or config.target_atr_pct <= 0 or atr_pct_at_entry <= 0:
        return 1.0
    raw = config.target_atr_pct / atr_pct_at_entry
    return max(config.min_factor, min(config.max_factor, raw))


def apply_vol_target(base_risk: float, atr_pct: float, config: VolTargetConfig) -> float:
    return base_risk * vol_target_factor(atr_pct, config)
