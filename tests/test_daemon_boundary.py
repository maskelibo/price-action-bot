"""next_tf_boundary edge case testleri — özellikle UTC midnight crossings.

FIX 2026-05-28 (audit-Y8): Audit raporu "midnight boundary off-by-one risk"
işaretlemişti — kod (futures_daemon.py:992-1003) görsel olarak doğru ama
hiç testi yoktu. Aşağıdaki testler 23:xx → 00:00 (yarın) geçişlerini
sabit `now` mock'u ile doğrular.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

# Daemon code path: scripts/futures_daemon.py
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from scripts.futures_daemon import next_tf_boundary, next_15m_boundary, next_5m_boundary  # noqa: E402


def _make_now(year, month, day, hour, minute, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


@pytest.mark.parametrize("hour,minute,expected_hour,expected_minute,day_delta", [
    # Sıradan içeride
    (14, 7, 14, 15, 0),
    (14, 14, 14, 15, 0),
    (14, 15, 14, 30, 0),  # tam :15'te sonraki :30
    (14, 45, 15, 0, 0),
    (14, 59, 15, 0, 0),
    # Saat geçişi (hour rollover)
    (15, 50, 16, 0, 0),
    # YARIM midnight crossing
    (23, 45, 0, 0, 1),  # 23:45 → ertesi gün 00:00
    (23, 59, 0, 0, 1),  # 23:59 → ertesi gün 00:00
    # Tam gece yarısı başlangıcı
    (0, 0, 0, 15, 0),
    (0, 14, 0, 15, 0),
])
def test_next_15m_boundary(hour, minute, expected_hour, expected_minute, day_delta):
    """15m boundary edge case'leri — özellikle midnight UTC crossing."""
    fixed_now = _make_now(2026, 5, 28, hour, minute)
    with patch("scripts.futures_daemon.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        # diğer datetime attribute'lar gerçek datetime'a yönlendir
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        # timedelta'yi mock'lamamamız lazım — kod kendi tarafında timedelta import ediyor
        result = next_tf_boundary(15)
    expected_date = (fixed_now + timedelta(days=day_delta)).date()
    assert result.date() == expected_date, (
        f"date mismatch: input={fixed_now}, got={result}, expected_date={expected_date}"
    )
    assert result.hour == expected_hour, f"hour mismatch: input={fixed_now}, got={result}"
    assert result.minute == expected_minute, f"minute mismatch: input={fixed_now}, got={result}"
    assert result.second == 0
    assert result.microsecond == 0
    assert result.tzinfo == timezone.utc


@pytest.mark.parametrize("hour,minute,expected_hour,expected_minute,day_delta", [
    (14, 7, 14, 10, 0),
    (14, 13, 14, 15, 0),
    (14, 58, 15, 0, 0),
    (23, 56, 0, 0, 1),  # midnight
    (23, 59, 0, 0, 1),
    (0, 0, 0, 5, 0),
])
def test_next_5m_boundary(hour, minute, expected_hour, expected_minute, day_delta):
    """5m boundary edge case'leri."""
    fixed_now = _make_now(2026, 5, 28, hour, minute)
    with patch("scripts.futures_daemon.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = next_tf_boundary(5)
    expected_date = (fixed_now + timedelta(days=day_delta)).date()
    assert result.date() == expected_date
    assert result.hour == expected_hour
    assert result.minute == expected_minute
    assert result.tzinfo == timezone.utc


def test_boundary_never_returns_past():
    """Boundary HER ZAMAN now'dan strictly büyük olmalı — geçmişe dönüş yok."""
    for hour in range(24):
        for minute in (0, 1, 14, 15, 16, 29, 30, 44, 45, 59):
            fixed_now = _make_now(2026, 5, 28, hour, minute)
            with patch("scripts.futures_daemon.datetime") as mock_dt:
                mock_dt.now.return_value = fixed_now
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                result = next_tf_boundary(15)
            assert result > fixed_now, (
                f"boundary {result} <= now {fixed_now} — geçmişe dönüş!"
            )


def test_boundary_aligned_to_tf_grid():
    """Sonuç her zaman tf-grid'e hizalı (15m için :00, :15, :30, :45)."""
    for hour in range(24):
        for minute in (0, 7, 14, 15, 23, 30, 44, 45, 58):
            fixed_now = _make_now(2026, 5, 28, hour, minute)
            with patch("scripts.futures_daemon.datetime") as mock_dt:
                mock_dt.now.return_value = fixed_now
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                result = next_tf_boundary(15)
            assert result.minute in (0, 15, 30, 45), (
                f"15m grid hizalanmadı: input={fixed_now}, got={result.minute}"
            )
            assert result.second == 0
            assert result.microsecond == 0
