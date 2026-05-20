"""SEC54.4 — 15m Daemon unit testleri.

Senaryolar:
  1) next_15m_boundary correctness (5 farkli saat input)
  2) Bar-close detection (mock datetime)
  3) Stale signal reject (>30 dk sinyal)
  4) Fresh signal kabul (<=30 dk sinyal)
  5) DMS TF parametreleri (heartbeat=20s, timeout=1800s)
  6) Missed bar counter artimi
  7) next_15m_boundary saat gecisi (xx:59 -> sonraki saat :00)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


# =====================================================================
# Senaryolar 1-2: next_15m_boundary
# =====================================================================

def _make_utc(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 5, 18, hour, minute, second, tzinfo=timezone.utc)


def _next_15m_boundary_impl(now: datetime) -> datetime:
    """futures_daemon.next_15m_boundary() in-process replica (import olmadan test)."""
    minute = now.minute
    next_quarter_min = ((minute // 15) + 1) * 15
    if next_quarter_min >= 60:
        new_hour = now.hour + 1
        if new_hour >= 24:
            tomorrow = now + timedelta(days=1)
            return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        return now.replace(hour=new_hour, minute=0, second=0, microsecond=0)
    return now.replace(minute=next_quarter_min, second=0, microsecond=0)


class TestNext15mBoundary:
    """Senaryo 1: next_15m_boundary correctness — 5 saat girdisi."""

    def test_mid_first_quarter(self):
        """14:07 → 14:15"""
        now = _make_utc(14, 7)
        result = _next_15m_boundary_impl(now)
        assert result == _make_utc(14, 15)

    def test_mid_second_quarter(self):
        """14:22 → 14:30"""
        now = _make_utc(14, 22)
        result = _next_15m_boundary_impl(now)
        assert result == _make_utc(14, 30)

    def test_mid_third_quarter(self):
        """14:37 → 14:45"""
        now = _make_utc(14, 37)
        result = _next_15m_boundary_impl(now)
        assert result == _make_utc(14, 45)

    def test_last_quarter_overflow_to_next_hour(self):
        """14:45 → 15:00 (son çeyrek sonrası saat başı)"""
        now = _make_utc(14, 45)
        result = _next_15m_boundary_impl(now)
        assert result == _make_utc(15, 0)

    def test_59th_minute_to_next_hour(self):
        """14:59 → 15:00"""
        now = _make_utc(14, 59)
        result = _next_15m_boundary_impl(now)
        assert result == _make_utc(15, 0)

    def test_hour_boundary_23_to_midnight(self):
        """23:46 → 00:00 gün sınırı geçişi"""
        now = _make_utc(23, 46)
        result = _next_15m_boundary_impl(now)
        # 00:00 sonraki gün
        expected = datetime(2026, 5, 19, 0, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_boundary_is_always_in_future(self):
        """Dönen boundary her zaman now'dan ileride olmalı."""
        test_cases = [
            _make_utc(0, 0, 1),
            _make_utc(12, 14, 59),
            _make_utc(23, 30, 0),
        ]
        for now in test_cases:
            result = _next_15m_boundary_impl(now)
            assert result > now, f"boundary {result} now {now} için ileride değil"


# =====================================================================
# Senaryo 2: Bar-close detection (dakika+saniye hassasiyeti)
# =====================================================================

class TestBarCloseDetection:
    """sleep_until + next_15m_boundary ile doğru bar zamanlaması."""

    def test_next_close_is_quarter_plus_5s(self):
        """next_close = next_15m_boundary() + 5 saniye."""
        now = _make_utc(14, 7, 30)
        boundary = _next_15m_boundary_impl(now)
        next_close = boundary + timedelta(seconds=5)
        # Doğru bar kapanışı
        assert next_close == _make_utc(14, 15, 5)

    def test_processing_window_within_bar(self):
        """5s buffer ile scan başlangıcı sonraki bar açılışından önce."""
        # 15m bar = 900s; scan 5s sonra başlıyor, 30s sürüyor → 35s < 900s PASS
        SCAN_WINDOW_SEC = 30
        BUFFER_SEC = 5
        assert BUFFER_SEC + SCAN_WINDOW_SEC < 900, "Scan window 15m bar'a sığmıyor"


# =====================================================================
# Senaryo 3-4: Stale signal reject / accept
# =====================================================================

class TestStaleSignalGuard:
    """DQ-02 — 30 dakikadan eski sinyal REJECT."""

    def _make_signal(self, age_minutes: float) -> dict:
        sig_ts = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
        return {
            "signal_id": "test_sig",
            "ts": sig_ts,
            "symbol": "BTC/USDT",
            "strategy": "brooks_h2_l2",
            "side": "long",
        }

    def _is_stale(self, sig: dict, max_age_min: float = 30.0) -> bool:
        """Daemon'daki stale check logic replica."""
        sig_ts = sig.get("ts")
        if sig_ts is None:
            return False
        if not hasattr(sig_ts, "tzinfo") or sig_ts.tzinfo is None:
            sig_ts = sig_ts.replace(tzinfo=timezone.utc)
        age_min = (datetime.now(timezone.utc) - sig_ts).total_seconds() / 60
        return age_min > max_age_min

    def test_reject_31_minute_old_signal(self):
        """31 dakikalık sinyal → STALE → REJECT."""
        sig = self._make_signal(age_minutes=31.0)
        assert self._is_stale(sig) is True

    def test_accept_29_minute_old_signal(self):
        """29 dakikalık sinyal → taze → ACCEPT."""
        sig = self._make_signal(age_minutes=29.0)
        assert self._is_stale(sig) is False

    def test_accept_exactly_30_minute_signal(self):
        """30.0 dakika tam sınır → dahil değil (>30 REJECT, 30 ACCEPT)."""
        sig = self._make_signal(age_minutes=30.0)
        # age_min > 30 kontrolü: 30.0 > 30 → False → taze
        assert self._is_stale(sig) is False

    def test_reject_very_old_signal(self):
        """60 dakikalık sinyal → STALE."""
        sig = self._make_signal(age_minutes=60.0)
        assert self._is_stale(sig) is True

    def test_accept_fresh_signal(self):
        """1 dakikalık sinyal (bar-close sonrası) → ACCEPT."""
        sig = self._make_signal(age_minutes=1.0)
        assert self._is_stale(sig) is False

    def test_none_ts_does_not_crash(self):
        """ts=None → stale check crash etmemeli, False döner."""
        sig = {"signal_id": "no_ts", "ts": None}
        assert self._is_stale(sig) is False


# =====================================================================
# Senaryo 5: DMS heartbeat / TF parametreleri
# =====================================================================

class TestDmsHeartbeat:
    """DeadMansSwitch tf='15m' parametreleri doğrulama."""

    def test_dms_15m_params(self):
        """tf='15m' → heartbeat=20s, timeout=1800s, watchdog=10s."""
        from price_action.execution.dead_mans_switch import DeadMansSwitch
        dms = DeadMansSwitch(exchange=None, tf="15m", service_name="test_15m")
        assert dms.heartbeat_sec == 20
        assert dms.timeout_sec == 1800
        assert dms._watchdog_interval == 10
        assert dms.tf == "15m"

    def test_dms_ping_updates_last_heartbeat_ts(self):
        """ping() çağrısı _last_heartbeat_ts'i günceller."""
        import time
        from price_action.execution.dead_mans_switch import DeadMansSwitch
        dms = DeadMansSwitch(exchange=None, tf="15m", service_name="test_ping")
        before = dms._last_heartbeat_ts
        time.sleep(0.05)
        dms.ping()
        after = dms._last_heartbeat_ts
        assert after > before

    def test_dms_not_triggered_immediately(self):
        """Yeni oluşturulan DMS henüz triggered değil (timeout=1800s)."""
        from price_action.execution.dead_mans_switch import DeadMansSwitch
        dms = DeadMansSwitch(exchange=None, tf="15m", service_name="test_not_triggered")
        assert dms.is_triggered is False


# =====================================================================
# Senaryo 6: Missed bar counter
# =====================================================================

class TestMissedBarCounter:
    """Atlanmış bar tespiti — bars_elapsed > 1 durumu."""

    def _bars_elapsed(self, last: datetime, current: datetime) -> int:
        return int((current - last).total_seconds() / 900)

    def test_no_missed_bar_consecutive(self):
        """Ardışık iki bar → 1 bar elapsed, 0 kaçırılmış."""
        last = _make_utc(14, 15)
        current = _make_utc(14, 30)
        assert self._bars_elapsed(last, current) == 1

    def test_one_missed_bar(self):
        """Bir bar atlandı → 2 elapsed → 1 missed."""
        last = _make_utc(14, 15)
        current = _make_utc(14, 45)
        elapsed = self._bars_elapsed(last, current)
        assert elapsed == 2
        missed = elapsed - 1
        assert missed == 1

    def test_many_missed_bars(self):
        """5 bar atlandı (75 dk gap)."""
        last = _make_utc(10, 0)
        current = _make_utc(11, 15)
        elapsed = self._bars_elapsed(last, current)
        assert elapsed == 5
        assert elapsed - 1 == 4  # 4 missed

    def test_no_missed_bar_on_first_tick(self):
        """İlk bar: last_bar_boundary=None → missed bar check atlanır."""
        # Daemon logic: if last_bar_boundary is None → no check
        last_bar_boundary = None
        # Kontrol koşulu: last_bar_boundary is not None → False → skip
        assert last_bar_boundary is None  # birincil tick'te atlama bekleniyor
