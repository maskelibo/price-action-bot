"""Cost model: spread, commission, swap, slippage, weekend gap.

All costs in pip / USD terms; converted using contracts.pip_value for given lots.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..contracts import pip_value
from ..session.tagger import tag_session


@dataclass
class CostConfig:
    # Spread (pips) per pair per session — defaults from observed retail brokers
    spread_base_pips: dict = field(default_factory=lambda: {
        "EURUSD": 0.6, "GBPUSD": 0.9, "AUDUSD": 0.8, "NZDUSD": 1.2,
        "USDCAD": 1.0, "USDCHF": 1.1, "EURGBP": 1.0,
        "USDJPY": 0.7, "EURJPY": 1.2, "GBPJPY": 1.8,
    })
    spread_session_mult: dict = field(default_factory=lambda: {
        "asia": 1.5, "london": 0.9, "london_ny_overlap": 0.8, "ny": 1.0, "off": 3.0,
    })
    commission_per_lot_round_turn_usd: float = 7.0
    # Swap rates per lot per night (USD); positive = paid TO trader, negative = paid BY trader
    swap_long_per_lot: dict = field(default_factory=lambda: {
        "EURUSD": -3.5, "GBPUSD": -2.0, "AUDUSD": 0.5, "NZDUSD": 0.3,
        "USDCAD": -1.5, "USDCHF": -1.8, "EURGBP": -2.5,
        "USDJPY": 4.0, "EURJPY": 1.5, "GBPJPY": 3.0,
    })
    swap_short_per_lot: dict = field(default_factory=lambda: {
        "EURUSD": 1.0, "GBPUSD": -0.5, "AUDUSD": -3.5, "NZDUSD": -3.0,
        "USDCAD": -0.8, "USDCHF": 0.5, "EURGBP": 0.3,
        "USDJPY": -7.0, "EURJPY": -4.0, "GBPJPY": -5.5,
    })
    # Slippage (pips) on entry/exit market orders; stop-out gets stop_slippage
    market_slippage_pips: float = 0.8
    stop_slippage_pips: float = 3.0
    # Weekend gap: Fri close → Mon open expected adverse move in pips
    weekend_gap_pips_p50: float = 4.0
    weekend_gap_pips_p95: float = 12.0


class CostModel:
    def __init__(self, cfg: Optional[CostConfig] = None):
        self.cfg = cfg or CostConfig()

    def spread_pips(self, pair: str, ts: datetime) -> float:
        sess = tag_session(ts)
        base = self.cfg.spread_base_pips.get(pair, 1.0)
        mult = self.cfg.spread_session_mult.get(sess, 1.0)
        return base * mult

    def commission_usd(self, lots: float) -> float:
        return self.cfg.commission_per_lot_round_turn_usd * lots

    def swap_usd(self, pair: str, side: str, lots: float, nights: int) -> float:
        per_lot = self.cfg.swap_long_per_lot.get(pair, 0.0) if side == "long" \
            else self.cfg.swap_short_per_lot.get(pair, 0.0)
        # triple swap on Wednesday rollover (Forex convention) — approximate by *1.4 on weekly avg
        return per_lot * lots * nights

    def market_slippage_pips(self) -> float:
        return self.cfg.market_slippage_pips

    def stop_slippage_pips(self) -> float:
        return self.cfg.stop_slippage_pips

    def weekend_gap_pips(self, severity: float = 0.5) -> float:
        """severity in [0,1]; 0.5 = median, 0.95 = tail risk."""
        if severity <= 0.5:
            return self.cfg.weekend_gap_pips_p50 * (severity / 0.5)
        return self.cfg.weekend_gap_pips_p50 + (
            (self.cfg.weekend_gap_pips_p95 - self.cfg.weekend_gap_pips_p50)
            * ((severity - 0.5) / 0.45)
        )

    def total_entry_cost_usd(self, pair: str, lots: float, ts: datetime) -> tuple[float, float]:
        """Returns (cost_usd_total, spread_pips_applied)."""
        spr = self.spread_pips(pair, ts)
        slip = self.market_slippage_pips()
        cost_pips = (spr / 2.0) + slip  # half spread on entry
        pv = pip_value(pair, lots=lots)
        cost_usd = cost_pips * pv + self.commission_usd(lots) / 2.0
        return cost_usd, spr

    def total_exit_cost_usd(self, pair: str, lots: float, ts: datetime, stopped_out: bool = False) -> tuple[float, float]:
        spr = self.spread_pips(pair, ts)
        slip = self.stop_slippage_pips() if stopped_out else self.market_slippage_pips()
        cost_pips = (spr / 2.0) + slip
        pv = pip_value(pair, lots=lots)
        cost_usd = cost_pips * pv + self.commission_usd(lots) / 2.0
        return cost_usd, spr
