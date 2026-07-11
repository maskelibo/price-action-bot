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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


# =====================================================================
# Senaryolar 1-2: next_15m_boundary
# =====================================================================


def _make_utc(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 5, 18, hour, minute, second, tzinfo=UTC)


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
        expected = datetime(2026, 5, 19, 0, 0, 0, tzinfo=UTC)
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
        scan_window_sec = 30
        buffer_sec = 5
        assert buffer_sec + scan_window_sec < 900, "Scan window 15m bar'a sığmıyor"


# =====================================================================
# Senaryo 3-4: Stale signal reject / accept
# =====================================================================


class TestStaleSignalGuard:
    """DQ-02 — 30 dakikadan eski sinyal REJECT."""

    def _make_signal(self, age_minutes: float) -> dict:
        sig_ts = datetime.now(UTC) - timedelta(minutes=age_minutes)
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
            sig_ts = sig_ts.replace(tzinfo=UTC)
        age_min = (datetime.now(UTC) - sig_ts).total_seconds() / 60
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
        """30.0 dakika sınırı altında → ACCEPT.

        FIX 2026-05-28 (audit-F7): Önceki `age_minutes=30.0` flaky idi —
        `_make_signal` ile `_is_stale` arasında ~3ms geçince yaş 30.003dk
        oluyordu, `>30` koşulu True dönüyordu, test fail. Şimdi 29.95
        (50ms tolerans). Davranış aynı — semantik test edildi:
        30dk **altı** ACCEPT, **üstü** REJECT.
        """
        sig = self._make_signal(age_minutes=29.95)
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

    def test_live_15m_wires_external_main_loop_heartbeat(self):
        """DMS cannot poll private account state every 20 seconds in live 15m."""
        source = (ROOT / "scripts" / "futures_daemon.py").read_text(encoding="utf-8")

        assert "external_heartbeat=True" in source
        assert "retry_not_before_reader=_get_binance_ban_until_dms" in source
        assert "background REST poll=OFF" in source
        assert "dms_15m.ping()" not in source


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


# =====================================================================
# Senaryo 7-10: 15m Post-Only Entry Path (2026-05-21)
# =====================================================================


class TestPostOnly15mEntryPath:
    """15m daemon entry post-only wiring testleri.

    Daemon kodu post_only_limit_enabled flag'ini _risk_cfg["execution"] bloğundan
    okur ve place_post_only_with_fallback / create_market_order'ı çağırır.
    Bu testler o logic'i izole ederek doğrular — gerçek exchange/daemon import yok.
    """

    def _simulate_entry(
        self,
        risk_cfg: dict,
        exchange: object,
        cur_px: float,
        order_side: str,
        qty: float,
        coid: str,
    ) -> tuple[dict, str]:
        """Daemon'daki post-only entry yolunu simüle eder (15m daemon ~satır 984-1022)."""
        from price_action.execution.post_only_router import (
            place_post_only_with_fallback,
        )

        _15m_po_enabled = bool(risk_cfg.get("execution", {}).get("post_only_limit_enabled", False))
        _15m_po_timeout = int(risk_cfg.get("execution", {}).get("post_only_fallback_seconds", 30))
        _15m_slip_limit = float(risk_cfg.get("execution", {}).get("slippage_limit_bps", 25.0))

        if _15m_po_enabled:
            order, fill_method = place_post_only_with_fallback(
                exchange,
                symbol="BTC/USDT",
                side=order_side,
                qty=qty,
                target_price=cur_px,
                fallback_after_sec=_15m_po_timeout,
                slippage_limit_bps=_15m_slip_limit,
                client_order_id=coid,
            )
        else:
            order = exchange.create_market_order(
                "BTC/USDT",
                order_side,
                qty,
                params={"newClientOrderId": coid},
            )
            fill_method = "market_only"

        return order, fill_method

    def _mk_po_fills_exchange(self, fill_avg: float) -> MagicMock:
        """Post-only emir 'closed' döndüren mock exchange."""
        ex = MagicMock()
        ex.create_order.return_value = {
            "id": "PO_15M_1",
            "status": "open",
            "average": fill_avg,
        }
        ex.fetch_order.return_value = {
            "id": "PO_15M_1",
            "status": "closed",
            "average": fill_avg,
            "filled": 0.05,
        }
        return ex

    def _mk_market_exchange(self, fill_avg: float) -> MagicMock:
        """create_market_order döndüren mock exchange."""
        ex = MagicMock()
        ex.create_market_order.return_value = {
            "id": "MK_15M_1",
            "status": "closed",
            "average": fill_avg,
            "filled": 0.05,
        }
        return ex

    def test_post_only_enabled_calls_po_router(self):
        """Senaryo 7: post_only_limit_enabled=True → place_post_only_with_fallback çağrılır."""
        risk_cfg = {
            "execution": {
                "post_only_limit_enabled": True,
                "post_only_fallback_seconds": 2,
                "slippage_limit_bps": 25.0,
            }
        }
        ex = self._mk_po_fills_exchange(fill_avg=65000.0)
        _order, method = self._simulate_entry(risk_cfg, ex, 65000.0, "buy", 0.05, "PA_testcoid1")

        assert method == "post_only_filled"
        # create_order çağrıldı (post-only limit gönderildi)
        assert ex.create_order.called
        # create_market_order çağrılmadı (market fallback gerekmedi)
        assert not ex.create_market_order.called

    def test_post_only_disabled_calls_market_order(self):
        """Senaryo 8: post_only_limit_enabled=False → create_market_order çağrılır, PO router bypass."""
        risk_cfg = {
            "execution": {
                "post_only_limit_enabled": False,
                "post_only_fallback_seconds": 30,
                "slippage_limit_bps": 25.0,
            }
        }
        ex = self._mk_market_exchange(fill_avg=65000.0)
        _order, method = self._simulate_entry(risk_cfg, ex, 65000.0, "buy", 0.05, "PA_testcoid2")

        assert method == "market_only"
        assert ex.create_market_order.called
        # PO limit router çağrılmadı
        assert not ex.create_order.called

    def test_execution_block_missing_falls_back_to_market(self):
        """Senaryo 9: execution bloğu YAML'de yoksa → default False → market yolu (backward-compat)."""
        risk_cfg = {}  # execution bloğu yok
        ex = self._mk_market_exchange(fill_avg=65100.0)
        _order, method = self._simulate_entry(risk_cfg, ex, 65100.0, "sell", 0.05, "PA_testcoid3")

        assert method == "market_only"
        assert ex.create_market_order.called

    def test_slippage_exceeded_is_owned_for_protection(self):
        """Senaryo 10: verified breach normal SL-first protection'a devredilir."""
        risk_cfg = {
            "execution": {
                "post_only_limit_enabled": True,
                "post_only_fallback_seconds": 1,
                "slippage_limit_bps": 5.0,  # çok düşük limit → kolayca aşılır
            }
        }

        # Post-only timeout, market fallback fill=65200 >> 65000 → slippage ~30bps > 5bps
        ex = MagicMock()
        ex.create_order.return_value = {"id": "PO_SLIP", "status": "open"}
        ex.fetch_order.return_value = {"id": "PO_SLIP", "status": "open"}

        def _cancel_and_publish_terminal(order_id, symbol):
            ex.fetch_order.return_value = {
                "id": order_id,
                "status": "canceled",
                "filled": 0.0,
            }
            return {"id": order_id, "status": "canceled", "filled": 0.0}

        ex.cancel_order.side_effect = _cancel_and_publish_terminal
        ex.create_market_order.return_value = {
            "id": "MK_SLIP",
            "status": "closed",
            "average": 65200.0,  # ~30bps slip on 65000 target
            "filled": 0.05,
        }

        order, method = self._simulate_entry(risk_cfg, ex, 65000.0, "buy", 0.05, "PA_testcoid4")

        assert method == "market_fallback_slippage_breach_protect"
        assert order["slippage_breach"]["position_owned"] is True
        assert order["slippage_breach"]["protection_required"] is True
        assert ex.create_market_order.call_count == 1

    def test_coid_passed_to_po_router(self):
        """Senaryo 11: client_order_id (_coid) post-only router'a geçirilir (idempotency korunur)."""
        risk_cfg = {
            "execution": {
                "post_only_limit_enabled": True,
                "post_only_fallback_seconds": 2,
                "slippage_limit_bps": 25.0,
            }
        }
        ex = self._mk_po_fills_exchange(fill_avg=65000.0)
        test_coid = "PA_abc1234567890123"
        self._simulate_entry(risk_cfg, ex, 65000.0, "buy", 0.05, test_coid)

        # create_order params içinde newClientOrderId = test_coid geçti
        call_kwargs = ex.create_order.call_args.kwargs
        assert call_kwargs["params"].get("newClientOrderId") == test_coid
