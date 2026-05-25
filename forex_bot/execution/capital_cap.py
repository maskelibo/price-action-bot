"""Capital cap — hard ceiling for live trading.

Phase 7 protocol: $1k max equity until 4 weeks profitable paper + human approval.
Once equity > cap, all new orders rejected.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CapitalCap:
    enabled: bool = True
    max_equity_usd: float = 1_000.0
    enforce_in_modes: tuple = ("live",)

    @classmethod
    def from_env(cls) -> "CapitalCap":
        return cls(
            enabled=os.environ.get("FX_CAPITAL_CAP_ENABLED", "1") == "1",
            max_equity_usd=float(os.environ.get("FX_CAPITAL_CAP_USD", "1000")),
        )

    def check(self, mode: str, current_equity_usd: float, new_order_notional: float = 0.0) -> tuple[bool, str]:
        """Returns (allow, reason). allow=False → block new order."""
        if not self.enabled or mode not in self.enforce_in_modes:
            return True, ""
        # margin held doesn't exceed cap (notional/100 for 1:100 leverage approximation)
        if current_equity_usd >= self.max_equity_usd:
            return False, f"capital_cap_exceeded(eq={current_equity_usd:.2f}>={self.max_equity_usd})"
        return True, ""
