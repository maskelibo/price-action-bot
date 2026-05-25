"""News guard: high-impact economic calendar parsing + entry blackout."""
from .calendar import EconomicEvent, load_cached_calendar, fetch_forexfactory_week
from .guard import NewsGuard

__all__ = ["EconomicEvent", "load_cached_calendar", "fetch_forexfactory_week", "NewsGuard"]
