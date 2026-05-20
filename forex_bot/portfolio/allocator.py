"""Portfolio allocator: rank multiple RiskedOrders, enforce hard caps."""
from __future__ import annotations

from dataclasses import dataclass

from ..contracts import RiskedOrder, Reject


@dataclass
class PortfolioAllocator:
    max_open_positions: int = 6
    max_per_pair_pct: float = 0.20
    category_caps: dict | None = None

    def prioritize(self, orders: list[RiskedOrder], account_open: dict) -> tuple[list[RiskedOrder], list[Reject]]:
        accepted: list[RiskedOrder] = []
        rejected: list[Reject] = []
        # rank by confluence × RR
        orders_sorted = sorted(
            orders,
            key=lambda o: (o.signal.confluence * o.signal.rr),
            reverse=True,
        )
        seen_pairs = set(account_open.keys())
        for o in orders_sorted:
            if len(accepted) + len(account_open) >= self.max_open_positions:
                rejected.append(Reject(signal=o.signal, rejected_by="portfolio", reason="max_positions"))
                continue
            if o.signal.pair in seen_pairs:
                rejected.append(Reject(signal=o.signal, rejected_by="portfolio", reason="pair_dup"))
                continue
            accepted.append(o)
            seen_pairs.add(o.signal.pair)
        return accepted, rejected
