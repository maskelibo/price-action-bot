"""Config adapter — backtest / iterate / LIVE schema parity layer.

FIX 2026-05-28 (Faz 14.27 #3): 3 farklı config schema vardı:
  1. **lab.py flat:** `risk_pct, max_concurrent` (direct attribute access)
  2. **iterate_orchestrator nested:** `equity.{risk_pct, max_concurrent, consecutive_loss_pause}`
  3. **LIVE RiskOfficer canonical:** `position_sizing.risk_per_trade,
     concentration_limits.max_open_positions, drawdown_breakers.consecutive_losses`

Önceki bug: v63 + v11 config'leri backtest schema'sında yazıldı, LIVE bot bunları
**silently ignore** ediyordu → backtest sonuçları live'da reproduce edilmezdi.
P0-2 (config schema parity) bu konuşmada fix edildi ama TEKRAR olmaması için
bu adapter standart hale getirir.
"""
from .adapter import (
    CanonicalRiskConfig,
    from_backtest_flat,
    from_iterate_equity,
    from_live_yaml,
    to_live_yaml_dict,
    validate_canonical,
)

__all__ = [
    "CanonicalRiskConfig",
    "from_backtest_flat",
    "from_iterate_equity",
    "from_live_yaml",
    "to_live_yaml_dict",
    "validate_canonical",
]
