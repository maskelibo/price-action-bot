"""Ops Engineer utilities — heartbeat, throttling, dashboard, kill-switch.

Modules:
  - telegram_throttle: Alarm de-duplication + digest engine
  - paper_gate: Paper trading gate (K1-K6 checks, SEC54.7)
  - (future) risk_health: Service SLA checks
  - (future) prometheus_exporter: Metrics collection
"""
from .paper_gate import (
    GateResult,
    PaperGate,
    PaperGateConfig,
)
from .telegram_throttle import (
    TelegramThrottle,
    get_telegram_throttle,
    reset_telegram_throttle,
)

__all__ = [
    "TelegramThrottle",
    "get_telegram_throttle",
    "reset_telegram_throttle",
    "PaperGate",
    "PaperGateConfig",
    "GateResult",
]
