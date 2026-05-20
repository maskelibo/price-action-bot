"""Pair correlation gate for portfolio risk."""
from __future__ import annotations

from dataclasses import dataclass

from ..data.universe import correlation_between


@dataclass
class CorrelationGate:
    max_pairwise_corr: float = 0.70
    reduction_factor: float = 0.5
    hard_block_at: float = 0.90

    def evaluate(self, new_pair: str, open_pairs: list[str], new_side: str, side_map: dict[str, str]) -> tuple[bool, float, str]:
        """Return (allow, size_multiplier, reason).

        - Open positions correlated > hard_block_at with same direction → block.
        - Open positions correlated > max_pairwise_corr with same direction → size × reduction_factor.
        - Negative correlation + opposite direction → counts as same-direction risk.
        """
        worst_eff = 0.0
        for op in open_pairs:
            if op == new_pair:
                continue
            rho = correlation_between(new_pair, op)
            same_dir = side_map.get(op) == new_side
            # effective same-direction correlation (negate if opposite-side and rho negative)
            if same_dir:
                eff = rho
            else:
                eff = -rho
            if abs(eff) > abs(worst_eff):
                worst_eff = eff
        if worst_eff >= self.hard_block_at:
            return False, 0.0, f"corr_hard_block({worst_eff:.2f})"
        if worst_eff >= self.max_pairwise_corr:
            return True, self.reduction_factor, f"corr_reduced({worst_eff:.2f})"
        return True, 1.0, ""
