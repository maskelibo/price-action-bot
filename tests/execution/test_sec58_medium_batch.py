"""SEC58 Medium Batch — M2 / M4 / M6 / L2 unit testleri.

M2  — Orphan order race condition: pyramid leg-1 SL hit + leg-2 PENDING/SUBMITTED
       100x concurrent simulate → 0 orphan leg (idempotent cancel).
M4  — returns_df TTL cache: 15 dk hit, TTL expire, reset, thread-safe.
M6  — Adaptive leverage retry: margin error → cascade 3x → 2x → 1x.
L2  — Pyramid DB persistence: upsert / load_all / delete / startup recovery.
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.execution.pyramid_router import (
    PyramidLeg,
    PyramidPosition,
    PyramidRouter,
    _make_client_order_id,
    build_position_from_signal,
)


# ─────────────────────────────────────────────────────────────────────────────
# Ortak fixture helpers
# ─────────────────────────────────────────────────────────────────────────────

ENTRY_PRICE = 65_000.0
SL_PRICE = 63_700.0
INITIAL_R = abs(ENTRY_PRICE - SL_PRICE)   # 1300.0
TRIG_LEG2 = ENTRY_PRICE + 1.0 * INITIAL_R  # 66_300
TS = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)


def _make_position(extra_legs: list[PyramidLeg] | None = None) -> PyramidPosition:
    entry_leg = PyramidLeg(
        leg_num=1, leg_state="FILLED", leg_qty=0.01,
        leg_price=ENTRY_PRICE, client_order_id="PA_test123456789_L1",
        fill_price=ENTRY_PRICE, filled_at=TS,
    )
    pos = PyramidPosition(
        parent_position_id="test123456789_base",
        symbol="BTC/USDT", side="LONG",
        entry_price=ENTRY_PRICE, sl_price=SL_PRICE, initial_R=INITIAL_R,
        legs=[entry_leg],
        pyramid_triggers=[1.0, 1.5],
        pyramid_sizes=[0.50, 0.30],
    )
    for leg in (extra_legs or []):
        pos.legs.append(leg)
    return pos


def _make_router(
    exchange=None, idem=None, slippage=None, post_only_enabled=False
) -> PyramidRouter:
    if exchange is None:
        exchange = MagicMock()
    if idem is None:
        idem = MagicMock()
        idem.is_seen.return_value = False
    if slippage is None:
        slippage = MagicMock()
        slippage.record_fill.return_value = 0.0
    return PyramidRouter(
        exchange=exchange,
        idempotency_store=idem,
        slippage_tracker=slippage,
        post_only_enabled=post_only_enabled,
        fallback_seconds=1,
        slippage_limit_bps=25.0,
        mode="paper",
    )


# =============================================================================
# M2 — Orphan order race condition tests
# =============================================================================

class TestM2OrphanRaceCondition:
    """Pyramid leg-1 SL hit + leg-2 PENDING concurrent simulate — 0 orphan."""

    def test_sl_hit_while_leg2_pending_no_orphan(self):
        """SL hit geldiğinde PENDING leg-2 CANCELED olmalı (tek thread)."""
        ex = MagicMock()
        pos = _make_position([
            PyramidLeg(
                leg_num=2, leg_state="PENDING", leg_qty=0.005,
                leg_price=TRIG_LEG2, client_order_id="PA_test123456789_L2",
            )
        ])
        router = _make_router(exchange=ex)
        router.on_position_check(pos, SL_PRICE - 100.0, TS)
        leg2 = pos.leg_for_num(2)
        assert leg2 is not None
        assert leg2.leg_state == "CANCELED"

    def test_sl_hit_while_leg2_submitted_cancel_called(self):
        """SL hit geldiğinde SUBMITTED leg-2 exchange.cancel_order çağrılmalı."""
        ex = MagicMock()
        ex.cancel_order.return_value = {"status": "canceled"}
        pos = _make_position([
            PyramidLeg(
                leg_num=2, leg_state="SUBMITTED", leg_qty=0.005,
                leg_price=TRIG_LEG2, client_order_id="PA_test123456789_L2",
                exchange_order_id="EX_999",
            )
        ])
        router = _make_router(exchange=ex)
        router.on_position_check(pos, SL_PRICE - 1.0, TS)
        ex.cancel_order.assert_called_once_with("EX_999", "BTC/USDT")
        assert pos.leg_for_num(2).leg_state == "CANCELED"

    def test_concurrent_sl_hit_idempotent_cancel(self):
        """100x concurrent on_position_check(SL) — leg-2 CANCELED, no double submit."""
        ex = MagicMock()
        ex.cancel_order.return_value = {"status": "canceled"}
        ex.create_market_order.return_value = {
            "id": "X", "status": "closed", "average": TRIG_LEG2, "filled": 0.005
        }

        pos = _make_position([
            PyramidLeg(
                leg_num=2, leg_state="SUBMITTED", leg_qty=0.005,
                leg_price=TRIG_LEG2, client_order_id="PA_test123456789_L2",
                exchange_order_id="EX_CONCURRENT",
            )
        ])

        router = _make_router(exchange=ex)
        errors: list[str] = []
        n_threads = 100

        def _sl_check():
            try:
                router.on_position_check(pos, SL_PRICE - 50.0, TS)
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=_sl_check) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Thread errors: {errors}"
        leg2 = pos.leg_for_num(2)
        assert leg2 is not None
        assert leg2.leg_state == "CANCELED", f"Expected CANCELED, got {leg2.leg_state}"
        # cancel_order en fazla 1 kez çağrılmalı (idempotent — lock korur)
        assert ex.cancel_order.call_count == 1, (
            f"cancel_order {ex.cancel_order.call_count}x çağrıldı (orphan!)"
        )
        # create_market_order HİÇ çağrılmamalı (SL → trigger detect skip)
        ex.create_market_order.assert_not_called()

    def test_concurrent_trigger_no_double_submit(self):
        """100x concurrent on_position_check(trigger) — leg-2 tek kez submit."""
        ex = MagicMock()
        ex.create_market_order.return_value = {
            "id": "TRIG_X", "status": "closed",
            "average": TRIG_LEG2, "filled": 0.005,
        }
        idem = MagicMock()
        idem.is_seen.return_value = False  # hiç görülmedi

        pos = _make_position()
        router = _make_router(exchange=ex, idem=idem, post_only_enabled=False)
        errors: list[str] = []
        n_threads = 100

        def _trigger_check():
            try:
                router.on_position_check(pos, TRIG_LEG2, TS)
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=_trigger_check) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Thread errors: {errors}"
        leg2 = pos.leg_for_num(2)
        assert leg2 is not None
        # leg-2 oluşturulmuş ama _leg_already_handled() lock altında çalıştığı için
        # create_market_order sadece 1 kez çağrılmalı ya da idem.is_seen True dönmeli.
        # Test amacı: duplicate order YOK.
        # İlk submit sonrası leg_state SUBMITTED/FILLED → sonrakiler _leg_already_handled=True.
        assert ex.create_market_order.call_count <= 1, (
            f"create_market_order {ex.create_market_order.call_count}x çağrıldı (DUPLICATE!)"
        )

    def test_sl_hit_cancel_fails_gracefully_no_raise(self):
        """exchange.cancel_order hata verse bile leg CANCELED, exception yutulur."""
        ex = MagicMock()
        ex.cancel_order.side_effect = Exception("Order already canceled")
        pos = _make_position([
            PyramidLeg(
                leg_num=2, leg_state="SUBMITTED", leg_qty=0.005,
                leg_price=TRIG_LEG2, client_order_id="PA_test123456789_L2",
                exchange_order_id="EX_GONE",
            )
        ])
        router = _make_router(exchange=ex)
        # exception raise etmemeli
        router.on_position_check(pos, SL_PRICE - 1.0, TS)
        assert pos.leg_for_num(2).leg_state == "CANCELED"

    def test_filled_leg_never_canceled_on_sl(self):
        """FILLED leg SL'de dokunulmaz (zaten kapanmış)."""
        ex = MagicMock()
        pos = _make_position([
            PyramidLeg(
                leg_num=2, leg_state="FILLED", leg_qty=0.005,
                leg_price=TRIG_LEG2, client_order_id="PA_test123456789_L2",
                fill_price=TRIG_LEG2, exchange_order_id="EX_FILLED",
            )
        ])
        router = _make_router(exchange=ex)
        router.on_position_check(pos, SL_PRICE - 100.0, TS)
        assert pos.leg_for_num(2).leg_state == "FILLED"
        ex.cancel_order.assert_not_called()


# =============================================================================
# M4 — returns_df TTL cache tests
# =============================================================================

class TestM4ReturnsDfTTLCache:
    """build_returns_df() TTL cache: hit, expire, thread-safe."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """Her test öncesi cache sıfırla."""
        from scripts.lib.risk_integration import reset_returns_df_cache
        reset_returns_df_cache()
        yield
        reset_returns_df_cache()

    def _make_mock_returns(self, symbols: list[str]):
        """Dummy DataFrame (2 kolon, 90 satır)."""
        import pandas as pd
        import numpy as np
        rng = np.random.default_rng(42)
        data = {s: rng.normal(0, 0.01, 90) for s in symbols}
        return pd.DataFrame(data)

    def test_cache_hit_returns_same_data(self, tmp_path):
        """İkinci çağrı cache'ten geldi — doğrudan cache insert + read."""
        import pandas as pd
        import time as _time
        from scripts.lib.risk_integration import (
            build_returns_df, _RETURNS_DF_CACHE,
        )

        dummy = self._make_mock_returns(["BTC/USDT"])
        _cache_key = (("BTC/USDT",), 90, str(tmp_path / "market.duckdb"), "1d", "binance")
        _RETURNS_DF_CACHE[_cache_key] = (_time.monotonic(), dummy)

        result = build_returns_df(
            ["BTC/USDT"], days=90,
            market_db=tmp_path / "market.duckdb",
        )
        # Cache hit → result == dummy (kopya)
        pd.testing.assert_frame_equal(result, dummy)

    def test_cache_miss_on_ttl_expire(self, tmp_path):
        """TTL aşıldıysa cache miss → expired key silinir, DB sorgusu tetiklenir."""
        import pandas as pd
        import time as _time
        from scripts.lib.risk_integration import (
            build_returns_df, _RETURNS_DF_CACHE, _RETURNS_DF_TTL_SEC,
        )

        dummy = self._make_mock_returns(["ETH/USDT"])
        _cache_key = (("ETH/USDT",), 90, str(tmp_path / "market.duckdb"), "1d", "binance")
        # Çok eski bir timestamp koy (TTL kesinlikle aşılmış)
        _RETURNS_DF_CACHE[_cache_key] = (_time.monotonic() - _RETURNS_DF_TTL_SEC - 1, dummy)

        # build_returns_df çağırınca cache miss → DB'ye gidecek ama test DB yok → empty df
        # price_action.data.store içinde lazy import kullanılıyor; boş DB → empty rows → empty df
        result = build_returns_df(
            ["ETH/USDT"], days=90,
            market_db=tmp_path / "market.duckdb",  # boş/yeni DB
        )
        # Boş DB → empty df döner
        assert isinstance(result, pd.DataFrame)
        # Eski (expired) kayıt temizlenmiş olmalı (build_returns_df lock altında siler)
        assert _cache_key not in _RETURNS_DF_CACHE

    def test_cache_key_includes_symbols_order_invariant(self, tmp_path):
        """Farklı sıradaki aynı semboller aynı cache key'e düşmeli."""
        from scripts.lib.risk_integration import _RETURNS_DF_CACHE
        import pandas as pd
        import time as _time

        # Manuel key oluştur: her iki sıralamayla
        syms_a = ["BTC/USDT", "ETH/USDT"]
        syms_b = ["ETH/USDT", "BTC/USDT"]  # ters sıra
        dummy = self._make_mock_returns(syms_a)

        key_a = (tuple(sorted(syms_a)), 90, str(tmp_path / "market.duckdb"), "1d", "binance")
        key_b = (tuple(sorted(syms_b)), 90, str(tmp_path / "market.duckdb"), "1d", "binance")
        assert key_a == key_b, "Sıra bağımsız key tutarlı değil"

        # Key_a ile cache'e yaz
        _RETURNS_DF_CACHE[key_a] = (_time.monotonic(), dummy)

        from scripts.lib.risk_integration import build_returns_df
        result = build_returns_df(
            syms_b, days=90,   # ters sıra
            market_db=tmp_path / "market.duckdb",
        )
        pd.testing.assert_frame_equal(result, dummy)

    def test_cache_thread_safe_no_corruption(self, tmp_path):
        """20 thread eş zamanlı cache read/write — bozulma yok."""
        import pandas as pd
        import time as _time
        from scripts.lib.risk_integration import _RETURNS_DF_CACHE, build_returns_df

        dummy = self._make_mock_returns(["SOL/USDT"])
        key = (("SOL/USDT",), 90, str(tmp_path / "market.duckdb"), "1d", "binance")
        _RETURNS_DF_CACHE[key] = (_time.monotonic(), dummy)

        errors: list[str] = []
        results: list[pd.DataFrame] = []
        lock = threading.Lock()

        def _read():
            try:
                df = build_returns_df(
                    ["SOL/USDT"], days=90,
                    market_db=tmp_path / "market.duckdb",
                )
                with lock:
                    results.append(df)
            except Exception as exc:
                with lock:
                    errors.append(str(exc))

        threads = [threading.Thread(target=_read) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Cache thread errors: {errors}"
        assert len(results) == 20
        for df in results:
            pd.testing.assert_frame_equal(df, dummy)

    def test_empty_symbols_bypasses_cache(self, tmp_path):
        """Boş sembol listesi → empty df, cache bypass (key oluşmaz)."""
        import pandas as pd
        from scripts.lib.risk_integration import build_returns_df, _RETURNS_DF_CACHE

        before = len(_RETURNS_DF_CACHE)
        result = build_returns_df([], days=90, market_db=tmp_path / "market.duckdb")
        assert result.empty
        assert len(_RETURNS_DF_CACHE) == before  # cache'e yeni key eklenmedi

    def test_reset_clears_all_entries(self, tmp_path):
        """reset_returns_df_cache() tüm cache'i temizler."""
        import time as _time
        import pandas as pd
        from scripts.lib.risk_integration import _RETURNS_DF_CACHE, reset_returns_df_cache

        dummy = self._make_mock_returns(["ADA/USDT"])
        key = (("ADA/USDT",), 90, str(tmp_path / "market.duckdb"), "1d", "binance")
        _RETURNS_DF_CACHE[key] = (_time.monotonic(), dummy)
        assert len(_RETURNS_DF_CACHE) > 0

        reset_returns_df_cache()
        assert len(_RETURNS_DF_CACHE) == 0


# =============================================================================
# M6 — Adaptive leverage retry tests
# =============================================================================

class TestM6AdaptiveLeverageRetry:
    """_submit_order_with_adaptive_leverage: margin error cascade + non-margin raise."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from scripts.futures_trade_daily import (
            _submit_order_with_adaptive_leverage,
            _is_margin_error,
        )
        self.submit_fn = _submit_order_with_adaptive_leverage
        self.is_margin = _is_margin_error

    def _make_exchange(self, order_return=None, fail_until_lev: int = 0):
        """exchange mock: leverage ≥ fail_until_lev → success, altı → margin error."""
        ex = MagicMock()
        _lev_set = [None]

        def _set_lev(lev, sym):
            _lev_set[0] = lev

        ex.set_leverage.side_effect = _set_lev

        _base_order = order_return or {
            "id": "OK_ORDER", "status": "closed",
            "average": 65_000.0, "filled": 0.01,
        }

        def _market_order(sym, side, qty):
            cur_lev = _lev_set[0]
            if cur_lev is not None and cur_lev > fail_until_lev:
                raise Exception("insufficient margin -2019")
            return _base_order

        ex.create_market_order.side_effect = _market_order
        return ex

    def test_is_margin_error_keywords(self):
        """_is_margin_error bilinen keyword'ları tanımalı."""
        assert self.is_margin(Exception("insufficient margin"))
        assert self.is_margin(Exception("Not enough balance -2019"))
        assert self.is_margin(Exception("Margin error: balance"))
        assert not self.is_margin(Exception("Network timeout"))
        assert not self.is_margin(Exception("Invalid symbol"))

    def test_success_first_attempt_no_cascade(self):
        """İlk denemede başarılı → cascade yok, leverage_used = base_lev."""
        ex = MagicMock()
        ex.create_market_order.return_value = {
            "id": "X", "status": "closed", "average": 65_000.0, "filled": 0.01
        }
        order, lev_used, method = self.submit_fn(
            ex, "BTC/USDT", "buy", 0.01, 3
        )
        assert lev_used == 3
        assert method == "market_only"
        assert order["id"] == "X"
        # setup_leverage sadece 1 kez çağrıldı
        assert ex.set_leverage.call_count == 1

    def test_cascade_3x_margin_fail_then_2x_success(self):
        """3x margin fail → 2x başarılı. lev_used=2."""
        ex = MagicMock()
        _attempts: list[int] = []

        def _set_lev(lev, sym):
            _attempts.append(lev)

        ex.set_leverage.side_effect = _set_lev

        def _market_order(sym, side, qty):
            cur = _attempts[-1] if _attempts else 3
            if cur == 3:
                raise Exception("insufficient margin -2019")
            return {"id": "FALLBACK_2X", "status": "closed", "average": 65_000.0, "filled": 0.01}

        ex.create_market_order.side_effect = _market_order

        order, lev_used, method = self.submit_fn(
            ex, "BTC/USDT", "buy", 0.01, 3
        )
        assert lev_used == 2
        assert order["id"] == "FALLBACK_2X"
        # setup_leverage 2 kez çağrıldı: 3x (fail) + 2x (success)
        assert ex.set_leverage.call_count == 2
        assert _attempts == [3, 2]

    def test_cascade_full_3x_2x_1x(self):
        """3x + 2x margin fail → 1x başarılı."""
        ex = MagicMock()
        _attempts: list[int] = []

        def _set_lev(lev, sym):
            _attempts.append(lev)

        ex.set_leverage.side_effect = _set_lev

        def _market_order(sym, side, qty):
            cur = _attempts[-1] if _attempts else 3
            if cur > 1:
                raise Exception("not enough balance")
            return {"id": "1X_ORDER", "status": "closed", "average": 65_000.0, "filled": 0.01}

        ex.create_market_order.side_effect = _market_order

        order, lev_used, method = self.submit_fn(
            ex, "BTC/USDT", "buy", 0.01, 3
        )
        assert lev_used == 1
        assert order["id"] == "1X_ORDER"
        assert _attempts == [3, 2, 1]

    def test_all_cascade_fail_raises(self):
        """3x + 2x + 1x hepsi margin fail → son exception raise."""
        ex = MagicMock()
        ex.create_market_order.side_effect = Exception("insufficient margin -2019")

        with pytest.raises(Exception, match="insufficient margin"):
            self.submit_fn(ex, "BTC/USDT", "buy", 0.01, 3)

        # 3 deneme: 3x + 2x + 1x
        assert ex.set_leverage.call_count == 3

    def test_non_margin_error_no_cascade(self):
        """Network hatası → cascade YOK, direkt raise."""
        ex = MagicMock()
        ex.create_market_order.side_effect = Exception("Connection timeout")

        with pytest.raises(Exception, match="Connection timeout"):
            self.submit_fn(ex, "BTC/USDT", "buy", 0.01, 3)

        # Sadece ilk deneme (3x) → fail, cascade yok
        assert ex.set_leverage.call_count == 1
        assert ex.create_market_order.call_count == 1

    def test_base_leverage_1x_no_cascade(self):
        """base_leverage=1 → cascade dizisi [1], tek deneme."""
        ex = MagicMock()
        ex.create_market_order.side_effect = Exception("insufficient margin")

        with pytest.raises(Exception):
            self.submit_fn(ex, "BTC/USDT", "buy", 0.01, 1)

        assert ex.set_leverage.call_count == 1
        assert ex.create_market_order.call_count == 1

    def test_cascade_updates_leverage_used_returned(self):
        """Cascade sonrası dönen lev_used, gerçekte kullanılan leverage."""
        ex = MagicMock()
        _lev_set: list[int] = []

        def _set_lev(lev, sym):
            _lev_set.append(lev)

        ex.set_leverage.side_effect = _set_lev

        def _market(sym, side, qty):
            if _lev_set[-1] >= 3:
                raise Exception("margin insufficient")
            return {"id": "Y", "status": "closed", "average": 65000.0, "filled": 0.01}

        ex.create_market_order.side_effect = _market

        order, lev_used, _ = self.submit_fn(ex, "BTC/USDT", "buy", 0.01, 5)
        # 5x fail, 2x success (cascade: [5, 2, 1] → 5 fail, 2 success)
        # Not: cascade degerleri: [5, 2, 1] (base=5 → 2 → 1)
        assert lev_used == 2
        assert order["id"] == "Y"


# =============================================================================
# L2 — Pyramid DB persistence tests
# =============================================================================

class TestL2PyramidStore:
    """PyramidStore: upsert / load_all / delete / recovery."""

    @pytest.fixture
    def store(self, tmp_path):
        from price_action.execution.pyramid_store import PyramidStore
        return PyramidStore(db_path=tmp_path / "pyramid_test.duckdb")

    def _make_pyr_pos(self, pos_id: str = "pos_abc123") -> PyramidPosition:
        entry_leg = PyramidLeg(
            leg_num=1, leg_state="FILLED", leg_qty=0.01,
            leg_price=ENTRY_PRICE, client_order_id=f"PA_{pos_id}_L1",
            fill_price=ENTRY_PRICE, filled_at=TS,
        )
        return PyramidPosition(
            parent_position_id=pos_id,
            symbol="BTC/USDT", side="LONG",
            entry_price=ENTRY_PRICE, sl_price=SL_PRICE, initial_R=INITIAL_R,
            legs=[entry_leg],
            pyramid_triggers=[1.0, 1.5],
            pyramid_sizes=[0.50, 0.30],
        )

    def test_upsert_and_count(self, store):
        """upsert_position sonrası count_positions() == 1."""
        pos = self._make_pyr_pos()
        store.upsert_position(pos)
        assert store.count_positions() == 1

    def test_load_all_returns_correct_position(self, store):
        """load_all() doğru symbol/side/prices döndürmeli."""
        pos = self._make_pyr_pos("pos_load_test")
        store.upsert_position(pos)

        loaded = store.load_all()
        assert "pos_load_test" in loaded
        lp = loaded["pos_load_test"]
        assert lp.symbol == "BTC/USDT"
        assert lp.side == "LONG"
        assert lp.entry_price == pytest.approx(ENTRY_PRICE)
        assert lp.sl_price == pytest.approx(SL_PRICE)
        assert lp.initial_R == pytest.approx(INITIAL_R)
        assert lp.pyramid_triggers == [1.0, 1.5]
        assert lp.pyramid_sizes == [0.50, 0.30]

    def test_load_all_returns_legs(self, store):
        """load_all() tüm leg'leri yüklemeli."""
        pos = self._make_pyr_pos("pos_legs")
        pos.legs.append(PyramidLeg(
            leg_num=2, leg_state="SUBMITTED", leg_qty=0.005,
            leg_price=TRIG_LEG2, client_order_id="PA_pos_legs_L2",
            exchange_order_id="EX_123",
        ))
        store.upsert_position(pos)

        loaded = store.load_all()["pos_legs"]
        assert len(loaded.legs) == 2
        leg2 = loaded.leg_for_num(2)
        assert leg2 is not None
        assert leg2.leg_state == "SUBMITTED"
        assert leg2.exchange_order_id == "EX_123"

    def test_upsert_idempotent(self, store):
        """Aynı pozisyon iki kez upsert → count hala 1."""
        pos = self._make_pyr_pos("pos_idem")
        store.upsert_position(pos)
        pos.sl_price = SL_PRICE - 100.0  # değişiklik simüle et
        store.upsert_position(pos)
        assert store.count_positions() == 1

    def test_upsert_updates_sl_price(self, store):
        """upsert sonrası sl_price güncellenmeli."""
        pos = self._make_pyr_pos("pos_update")
        store.upsert_position(pos)
        pos.sl_price = 62_000.0
        store.upsert_position(pos)

        loaded = store.load_all()["pos_update"]
        assert loaded.sl_price == pytest.approx(62_000.0)

    def test_delete_position(self, store):
        """delete_position sonrası load_all'da görünmemeli."""
        pos = self._make_pyr_pos("pos_del")
        store.upsert_position(pos)
        assert store.count_positions() == 1

        store.delete_position("pos_del")
        assert store.count_positions() == 0
        assert "pos_del" not in store.load_all()

    def test_multiple_positions(self, store):
        """Birden fazla pozisyon saklanabilmeli."""
        for i in range(5):
            store.upsert_position(self._make_pyr_pos(f"pos_{i:03d}"))
        assert store.count_positions() == 5
        loaded = store.load_all()
        assert len(loaded) == 5
        for i in range(5):
            assert f"pos_{i:03d}" in loaded

    def test_startup_recovery(self, tmp_path):
        """Restart: aynı DB'yi yeni PyramidStore ile aç → pozisyon yükleniyor."""
        from price_action.execution.pyramid_store import PyramidStore
        db = tmp_path / "recover.duckdb"

        # İlk session: pozisyon kaydet
        store1 = PyramidStore(db_path=db)
        pos = self._make_pyr_pos("pos_recover")
        pos.legs.append(PyramidLeg(
            leg_num=2, leg_state="PENDING", leg_qty=0.005,
            leg_price=TRIG_LEG2, client_order_id="PA_pos_recover_L2",
        ))
        store1.upsert_position(pos)

        # İkinci session (restart simülasyonu)
        store2 = PyramidStore(db_path=db)
        recovered = store2.load_all()

        assert "pos_recover" in recovered
        rp = recovered["pos_recover"]
        assert rp.symbol == "BTC/USDT"
        assert len(rp.legs) == 2
        leg2 = rp.leg_for_num(2)
        assert leg2 is not None
        assert leg2.leg_state == "PENDING"

    def test_delete_closed_legs_keeps_pending(self, store):
        """delete_closed_legs: CANCELED/REJECTED sil, PENDING/SUBMITTED koru."""
        pos = self._make_pyr_pos("pos_dclean")
        pos.legs.append(PyramidLeg(
            leg_num=2, leg_state="PENDING", leg_qty=0.005,
            leg_price=TRIG_LEG2, client_order_id="PA_pos_dclean_L2",
        ))
        pos.legs.append(PyramidLeg(
            leg_num=3, leg_state="CANCELED", leg_qty=0.003,
            leg_price=TRIG_LEG2 + 600, client_order_id="PA_pos_dclean_L3",
        ))
        store.upsert_position(pos)

        store.delete_closed_legs("pos_dclean")
        loaded = store.load_all()["pos_dclean"]
        # Leg-1 (FILLED) + Leg-2 (PENDING) korunur, Leg-3 (CANCELED) silinir
        remaining_nums = {lg.leg_num for lg in loaded.legs}
        assert 2 in remaining_nums, "PENDING leg-2 silinmemeli"
        assert 3 not in remaining_nums, "CANCELED leg-3 silinmeli"

    def test_concurrent_upsert_safe(self, store):
        """20 thread eş zamanlı upsert → bozulma yok."""
        errors: list[str] = []

        def _write(i: int):
            try:
                p = self._make_pyr_pos(f"pos_conc_{i:02d}")
                store.upsert_position(p)
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert errors == [], f"Concurrent upsert errors: {errors}"
        assert store.count_positions() == 20
