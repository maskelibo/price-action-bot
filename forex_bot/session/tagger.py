"""Session tagging (UTC).

Convention (approximation, ignores DST shifts of ±1h):
- Asia:                 21:00 (Sun open) – 07:00 UTC
- London:               07:00 – 12:00 UTC
- London-NY overlap:    12:00 – 16:00 UTC (high vol, special handling)
- NY (post-overlap):    16:00 – 21:00 UTC
- Off (weekend):        Fri 21:00 – Sun 21:00

Caller passes a UTC datetime (timezone-aware) and gets back a Session string.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Literal

import numpy as np
import pandas as pd

from ..contracts import Session


def tag_session(ts: datetime) -> Session:
    if ts.tzinfo is None:
        # treat naive as UTC
        ts = ts.replace(tzinfo=None)
    dow = ts.weekday()
    h = ts.hour
    if dow == 5 or (dow == 6 and h < 21) or (dow == 4 and h >= 21):
        return "off"
    if 7 <= h < 12:
        return "london"
    if 12 <= h < 16:
        return "london_ny_overlap"
    if 16 <= h < 21:
        return "ny"
    return "asia"


def tag_session_series(idx: pd.DatetimeIndex) -> pd.Series:
    import numpy as np
    if idx.tz is None:
        idx_utc = idx.tz_localize("UTC")
    else:
        idx_utc = idx.tz_convert("UTC")
    dow = np.asarray(idx_utc.dayofweek)
    h = np.asarray(idx_utc.hour)
    out = pd.Series("off", index=idx, dtype=object)
    weekend = ((dow == 5) | ((dow == 6) & (h < 21)) | ((dow == 4) & (h >= 21)))
    asia = (~weekend) & ((h >= 21) | (h < 7))
    london = (~weekend) & (h >= 7) & (h < 12)
    overlap = (~weekend) & (h >= 12) & (h < 16)
    ny = (~weekend) & (h >= 16) & (h < 21)
    out.loc[asia] = "asia"
    out.loc[london] = "london"
    out.loc[overlap] = "london_ny_overlap"
    out.loc[ny] = "ny"
    return out


SESSION_END_HOUR_UTC = {
    "asia": 7, "london": 12, "london_ny_overlap": 16, "ny": 21, "off": 21,
}


def session_minutes_remaining(ts: datetime) -> int:
    sess = tag_session(ts)
    end_h = SESSION_END_HOUR_UTC[sess]
    end_minute = end_h * 60
    cur_minute = ts.hour * 60 + ts.minute
    # asia wraps midnight: from 21:00 prev day to 07:00 current day
    if sess == "asia" and ts.hour >= 21:
        return (24 - ts.hour) * 60 + 7 * 60 - ts.minute
    rem = end_minute - cur_minute
    return max(0, rem)


# pair → session quality score (heuristic, used as confluence factor)
PAIR_SESSION_SCORE = {
    "EURUSD": {"asia": 0.40, "london": 1.00, "london_ny_overlap": 1.00, "ny": 0.85, "off": 0.0},
    "GBPUSD": {"asia": 0.30, "london": 1.00, "london_ny_overlap": 1.00, "ny": 0.85, "off": 0.0},
    "USDJPY": {"asia": 0.85, "london": 0.85, "london_ny_overlap": 1.00, "ny": 1.00, "off": 0.0},
    "AUDUSD": {"asia": 0.90, "london": 0.70, "london_ny_overlap": 0.85, "ny": 0.70, "off": 0.0},
    "USDCAD": {"asia": 0.30, "london": 0.65, "london_ny_overlap": 1.00, "ny": 1.00, "off": 0.0},
    "NZDUSD": {"asia": 0.90, "london": 0.70, "london_ny_overlap": 0.85, "ny": 0.70, "off": 0.0},
    "USDCHF": {"asia": 0.35, "london": 1.00, "london_ny_overlap": 0.95, "ny": 0.75, "off": 0.0},
    "EURJPY": {"asia": 0.75, "london": 1.00, "london_ny_overlap": 1.00, "ny": 0.85, "off": 0.0},
    "GBPJPY": {"asia": 0.75, "london": 1.00, "london_ny_overlap": 1.00, "ny": 0.85, "off": 0.0},
    "EURGBP": {"asia": 0.25, "london": 1.00, "london_ny_overlap": 0.90, "ny": 0.55, "off": 0.0},
}


def session_score_for_pair(pair: str, session: Session) -> float:
    return PAIR_SESSION_SCORE.get(pair, {}).get(session, 0.5)
