"""Session tagger tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from forex_bot.session.tagger import (
    SESSION_END_HOUR_UTC, session_minutes_remaining, session_score_for_pair,
    tag_session, tag_session_series,
)


def test_tag_session_basic():
    assert tag_session(datetime(2024, 1, 8, 8, 0, tzinfo=timezone.utc)) == "london"
    assert tag_session(datetime(2024, 1, 8, 13, 0, tzinfo=timezone.utc)) == "london_ny_overlap"
    assert tag_session(datetime(2024, 1, 8, 17, 0, tzinfo=timezone.utc)) == "ny"
    assert tag_session(datetime(2024, 1, 8, 22, 0, tzinfo=timezone.utc)) == "asia"
    assert tag_session(datetime(2024, 1, 8, 4, 0, tzinfo=timezone.utc)) == "asia"


def test_tag_session_weekend():
    # Saturday
    assert tag_session(datetime(2024, 1, 6, 12, 0, tzinfo=timezone.utc)) == "off"
    # Friday 22:00
    assert tag_session(datetime(2024, 1, 5, 22, 0, tzinfo=timezone.utc)) == "off"
    # Sunday 20:00 (before reopen)
    assert tag_session(datetime(2024, 1, 7, 20, 0, tzinfo=timezone.utc)) == "off"
    # Sunday 21:30 (Asia open)
    assert tag_session(datetime(2024, 1, 7, 21, 30, tzinfo=timezone.utc)) == "asia"


def test_session_series():
    idx = pd.date_range("2024-01-08 00:00", "2024-01-08 23:45", freq="15min", tz="UTC")
    s = tag_session_series(idx)
    assert (s == "london").sum() > 0
    assert (s == "london_ny_overlap").sum() > 0


def test_session_minutes_remaining():
    assert session_minutes_remaining(datetime(2024, 1, 8, 8, 0)) == 4 * 60
    assert session_minutes_remaining(datetime(2024, 1, 8, 17, 30)) == 3 * 60 + 30


def test_pair_session_score():
    assert session_score_for_pair("EURUSD", "london") == 1.0
    assert session_score_for_pair("AUDUSD", "asia") >= 0.85
    assert session_score_for_pair("EURUSD", "off") == 0.0
