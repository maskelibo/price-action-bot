"""Confluence scoring: weighted aggregation of pattern + structure + smart-money + volume + session."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConfluenceWeights:
    pattern: float = 0.25
    structure: float = 0.20
    smc: float = 0.20
    volume: float = 0.15
    session: float = 0.10
    trend: float = 0.10


def confluence_score(
    pattern_hit: bool,
    structure_hit: bool,
    smc_hit: bool,
    volume_score: float,
    session_score: float,
    trend_aligned: bool,
    weights: ConfluenceWeights = ConfluenceWeights(),
) -> float:
    """Return scalar in [0,1]."""
    s = 0.0
    if pattern_hit:
        s += weights.pattern
    if structure_hit:
        s += weights.structure
    if smc_hit:
        s += weights.smc
    s += weights.volume * max(0.0, min(1.0, volume_score))
    s += weights.session * max(0.0, min(1.0, session_score))
    if trend_aligned:
        s += weights.trend
    total = (
        weights.pattern + weights.structure + weights.smc
        + weights.volume + weights.session + weights.trend
    )
    return s / total
