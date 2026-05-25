"""News guard: blackout window around high-impact events; stop-tightening for open positions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from .calendar import EconomicEvent, load_cached_calendar


@dataclass
class NewsGuard:
    """Blocks entries in [-pre_minutes, +post_minutes] around high-impact events; signals stop-tightening.

    Lifecycle:
      - is_blackout(ts, pair) → bool (block new entries)
      - should_tighten_stop(ts, pair, sl_dist_pips, current_atr_pips) → tightening factor 0..1 (0 = no change, 1 = halve SL)
    """
    pre_minutes: int = 30
    post_minutes: int = 30
    impact_levels: tuple = ("high",)
    events: list = None  # type: ignore

    def __post_init__(self):
        if self.events is None:
            self.events = load_cached_calendar()

    def upcoming_events(self, ts: datetime, pair: str, window_min: int = 120) -> list[EconomicEvent]:
        ts = self._utc(ts)
        end = ts + timedelta(minutes=window_min)
        return [
            e for e in self.events
            if e.impact in self.impact_levels
            and e.affects_pair(pair)
            and ts - timedelta(minutes=self.pre_minutes) <= e.ts_utc <= end
        ]

    def is_blackout(self, ts: datetime, pair: str) -> tuple[bool, Optional[EconomicEvent]]:
        ts = self._utc(ts)
        for e in self.events:
            if e.impact not in self.impact_levels or not e.affects_pair(pair):
                continue
            if e.ts_utc - timedelta(minutes=self.pre_minutes) <= ts <= e.ts_utc + timedelta(minutes=self.post_minutes):
                return True, e
        return False, None

    def should_tighten_stop(self, ts: datetime, pair: str, lookahead_minutes: int = 60) -> bool:
        """True if a high-impact event is within `lookahead_minutes` for this pair (open positions)."""
        ts = self._utc(ts)
        for e in self.events:
            if e.impact not in self.impact_levels or not e.affects_pair(pair):
                continue
            if ts < e.ts_utc <= ts + timedelta(minutes=lookahead_minutes):
                return True
        return False

    @staticmethod
    def _utc(ts: datetime) -> datetime:
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
