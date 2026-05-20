"""Economic calendar parser.

Primary source: ForexFactory weekly JSON feed (cached).
Fallback: bundled static high-impact events CSV.

Each event carries: ts_utc, currency, impact (high|medium|low), title, country.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore


@dataclass(frozen=True)
class EconomicEvent:
    ts_utc: datetime
    currency: str
    impact: str
    title: str
    country: str = ""

    def affects_pair(self, pair: str) -> bool:
        base, quote = pair[:3], pair[3:]
        return self.currency in (base, quote)


HIGH_IMPACT_TITLES = {
    "Non-Farm Employment Change", "NFP", "FOMC Statement", "Federal Funds Rate",
    "ECB Press Conference", "Main Refinancing Rate", "BOE Inflation Report",
    "Official Bank Rate", "CPI m/m", "Core CPI m/m", "Unemployment Rate",
    "GDP q/q", "Retail Sales m/m",
}


def load_cached_calendar(csv_path: Optional[Path] = None) -> list[EconomicEvent]:
    if csv_path is None:
        csv_path = Path(__file__).parent / "cached_calendar.csv"
    if not csv_path.exists():
        return []
    out: list[EconomicEvent] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = datetime.fromisoformat(row["ts_utc"]).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            out.append(EconomicEvent(
                ts_utc=ts,
                currency=row["currency"].upper(),
                impact=row["impact"].lower(),
                title=row.get("title", ""),
                country=row.get("country", ""),
            ))
    return out


def fetch_forexfactory_week() -> list[EconomicEvent]:
    """Fetch current-week JSON from ForexFactory. Returns [] on failure."""
    if requests is None:
        return []
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []
    out: list[EconomicEvent] = []
    for item in data:
        ts_str = item.get("date") or item.get("datetime")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            continue
        out.append(EconomicEvent(
            ts_utc=ts,
            currency=(item.get("country") or item.get("currency") or "").upper()[:3],
            impact=(item.get("impact") or "").lower(),
            title=item.get("title", ""),
            country=item.get("country", ""),
        ))
    return out


def filter_high_impact(events: Iterable[EconomicEvent]) -> list[EconomicEvent]:
    return [e for e in events if e.impact == "high"]
