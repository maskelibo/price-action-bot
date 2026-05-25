"""Strategy ABC + manifest loader."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

from ..contracts import Signal


@dataclass
class StrategyManifest:
    name: str
    enabled: bool = True
    confluence_threshold: float = 0.55
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0
    rr_min: float = 1.5
    sessions_allowed: list = field(default_factory=lambda: ["london", "london_ny_overlap", "ny"])
    params: dict = field(default_factory=dict)


class Strategy(ABC):
    name: str = "base"

    def __init__(self, manifest: Optional[StrategyManifest] = None):
        self.manifest = manifest or StrategyManifest(name=self.name)

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame, pair: str) -> list[Signal]:
        """Return candidate signals; engine/SignalGenerator applies session/news filters and confluence threshold."""
        ...

    def _emit(
        self,
        pair: str,
        ts,
        side: str,
        entry: float,
        sl: float,
        tp: list[float],
        confluence: float,
        session,
        pattern: str,
        sl_pips: float,
        meta: dict,
    ) -> Signal:
        rr = abs(tp[0] - entry) / max(1e-9, abs(entry - sl))
        return Signal(
            pair=pair, side=side, ts=ts, entry_price=entry,
            sl_price=sl, tp_prices=tp, confluence=confluence,
            strategy=self.name, session=session, pattern=pattern,
            sl_pips=sl_pips, rr=rr, meta=meta,
        )


def load_pair_strategies(pair: str, configs_dir: Path) -> list[StrategyManifest]:
    if yaml is None:
        return []
    path = configs_dir / "pairs" / f"{pair}.yaml"
    if not path.exists():
        return []
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for entry in cfg.get("strategies", []):
        out.append(StrategyManifest(**entry))
    return out
