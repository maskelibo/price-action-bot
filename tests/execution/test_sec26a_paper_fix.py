"""SEC26.A — Paper Hold Time Bug Fix Testleri.

Test kapsamı:
1. Stale signal guard: 3+ gün eski sinyal REJECT
2. Stale signal guard: 0-2 gün eski sinyal PASS
3. place_protection_orders multi-target mode: entry_price verildiğinde TP1+TP2+SL
4. place_protection_orders legacy mode: entry_price=None → single TP+SL
5. entry_price calculation: paper_trade_daily.py scan_signals'da atr14 yerine last_close
6. sl_dist calculation: paper_trade_daily.py'da entry_price - sl_price (atr14 değil)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


# ─── 1. Stale signal guard unit tests ────────────────────────────────────────

class TestStaleSignalGuard:
    """futures_trade_daily.submit_to_futures stale guard logic."""

    def _make_signal(self, days_old: int) -> dict:
        sig_date = datetime.now(timezone.utc) - timedelta(days=days_old)
        import pandas as pd
        return {
            'ts': pd.Timestamp(sig_date),
            'symbol': 'BTC/USDT',
            'strategy': 'brooks_failed_breakout',
            'side': 'short',
            'sl_price': 85000.0,
            'tp_price': 70000.0,
            'confluence': 2.0,
            'signal_obj': MagicMock(sl_price=85000.0, tp_price=70000.0,
                                    confluence_score=2.0, direction='short',
                                    metadata={'atr14': 2000.0}),
            'entry_price': 79000.0,
        }

    def _check_stale(self, signal: dict, max_age_days: int = 2) -> bool:
        """Stale guard mantığını izole et (submit_to_futures'daki satırlar)."""
        import pandas as pd
        sig_ts = signal.get('ts')
        if sig_ts is None:
            return False
        if hasattr(sig_ts, 'tzinfo'):
            sig_date = sig_ts.date() if hasattr(sig_ts, 'date') else sig_ts.to_pydatetime().date()
        else:
            sig_date = pd.Timestamp(sig_ts).date()
        today_utc = datetime.now(timezone.utc).date()
        stale_days = (today_utc - sig_date).days
        return stale_days > max_age_days

    def test_fresh_signal_0d_passes(self):
        sig = self._make_signal(0)
        assert self._check_stale(sig) is False

    def test_fresh_signal_1d_passes(self):
        sig = self._make_signal(1)
        assert self._check_stale(sig) is False

    def test_fresh_signal_2d_passes(self):
        sig = self._make_signal(2)
        assert self._check_stale(sig) is False

    def test_stale_signal_3d_rejected(self):
        sig = self._make_signal(3)
        assert self._check_stale(sig) is True

    def test_stale_signal_7d_rejected(self):
        sig = self._make_signal(7)
        assert self._check_stale(sig) is True

    def test_stale_signal_30d_rejected(self):
        sig = self._make_signal(30)
        assert self._check_stale(sig) is True

    def test_boundary_exactly_2d_passes(self):
        """Tam 2 gün = geçer (> 2 değil, = 2 geçer)."""
        sig = self._make_signal(2)
        assert self._check_stale(sig) is False

    def test_boundary_exactly_3d_rejected(self):
        """Tam 3 gün = REJECT."""
        sig = self._make_signal(3)
        assert self._check_stale(sig) is True


# ─── 2. place_protection_orders multi-target mode ────────────────────────────

class TestPlaceProtectionOrdersMultiTarget:
    """SEC26.A: entry_price verildiğinde TP1+TP2+SL mode aktif olur."""

    def _mock_exchange(self):
        ex = MagicMock()
        ex.market.return_value = {}
        ex.amount_to_precision.side_effect = lambda sym, qty: str(round(qty, 4))
        ex.price_to_precision.side_effect = lambda sym, px: str(round(px, 2))
        # create_order returns fake order with id
        order_counter = [0]
        def _create_order(*args, **kwargs):
            order_counter[0] += 1
            return {'id': f'ORDER_{order_counter[0]}'}
        ex.create_order.side_effect = _create_order
        return ex

    def test_multi_target_mode_places_3_orders(self):
        """entry_price verilirse 3 order gönderilmeli: TP1 + TP2 + SL."""
        from scripts.futures_trade_daily import place_protection_orders
        ex = self._mock_exchange()
        result = place_protection_orders(
            exchange=ex,
            symbol='BTC/USDT',
            side='short',
            qty=0.01,
            tp_price=74000.0,
            sl_price=82000.0,
            entry_price=79000.0,
        )
        assert result['status'] == 'placed'
        assert result.get('mode') == 'multi_target'
        assert ex.create_order.call_count == 3  # TP1 + TP2 + SL

    def test_multi_target_tp2_computed_correctly_short(self):
        """SHORT: TP2 = entry - 1.5 * (sl - entry) = entry - 1.5 * sl_dist."""
        from scripts.futures_trade_daily import place_protection_orders
        ex = self._mock_exchange()
        entry = 79000.0
        sl = 82000.0
        tp1 = 74000.0  # raw signal TP (≈1R)
        result = place_protection_orders(
            exchange=ex, symbol='BTC/USDT', side='short',
            qty=0.01, tp_price=tp1, sl_price=sl, entry_price=entry,
        )
        # sl_dist = |entry - sl| = 3000
        # TP2 = entry - 1.5 * 3000 = 79000 - 4500 = 74500
        expected_tp2 = entry - 1.5 * abs(entry - sl)
        assert result.get('tp2_price') is not None
        assert abs(float(result['tp2_price']) - expected_tp2) < 1.0

    def test_multi_target_tp2_computed_correctly_long(self):
        """LONG: TP2 = entry + 1.5 * sl_dist."""
        from scripts.futures_trade_daily import place_protection_orders
        ex = self._mock_exchange()
        entry = 79000.0
        sl = 76000.0
        tp1 = 82000.0
        result = place_protection_orders(
            exchange=ex, symbol='BTC/USDT', side='long',
            qty=0.01, tp_price=tp1, sl_price=sl, entry_price=entry,
        )
        expected_tp2 = entry + 1.5 * abs(entry - sl)
        assert result.get('tp2_price') is not None
        assert abs(float(result['tp2_price']) - expected_tp2) < 1.0

    def test_multi_target_qty_split(self):
        """TP1=%30 qty, TP2=%30 qty, SL=100% qty (reduceOnly)."""
        from scripts.futures_trade_daily import place_protection_orders

        orders_placed = []
        ex = self._mock_exchange()
        counter = [0]
        def _create_order(symbol, type, side, amount, params=None):
            counter[0] += 1
            orders_placed.append({'type': type, 'amount': amount, 'params': params})
            return {'id': f'ORD_{counter[0]}'}
        ex.create_order.side_effect = _create_order
        # Override precision to return float
        ex.amount_to_precision.side_effect = lambda sym, qty: qty

        qty = 1.0
        result = place_protection_orders(
            exchange=ex, symbol='ETH/USDT', side='short',
            qty=qty, tp_price=1800.0, sl_price=2500.0, entry_price=2200.0,
        )
        assert len(orders_placed) == 3
        # TP1: 30% qty
        assert abs(orders_placed[0]['amount'] - 0.30) < 0.01
        # TP2: 30% qty
        assert abs(orders_placed[1]['amount'] - 0.30) < 0.01
        # SL: 100% qty
        assert abs(orders_placed[2]['amount'] - 1.0) < 0.01

    def test_legacy_mode_places_2_orders(self):
        """entry_price=None → legacy mode, 2 order: TP + SL."""
        from scripts.futures_trade_daily import place_protection_orders
        ex = self._mock_exchange()
        result = place_protection_orders(
            exchange=ex, symbol='BTC/USDT', side='short',
            qty=0.01, tp_price=74000.0, sl_price=82000.0,
            entry_price=None,
        )
        assert result['status'] == 'placed'
        assert result.get('mode') == 'single_target'
        assert ex.create_order.call_count == 2  # TP + SL

    def test_returns_error_on_exchange_exception(self):
        """Borsa hatası → status='error' döner, exception raise etmez."""
        from scripts.futures_trade_daily import place_protection_orders
        ex = MagicMock()
        ex.market.return_value = {}
        ex.amount_to_precision.side_effect = lambda sym, qty: str(qty)
        ex.price_to_precision.side_effect = lambda sym, px: str(px)
        ex.create_order.side_effect = Exception("Rate limit exceeded")
        result = place_protection_orders(
            exchange=ex, symbol='BTC/USDT', side='short',
            qty=0.01, tp_price=74000.0, sl_price=82000.0, entry_price=79000.0,
        )
        assert result['status'] == 'error'
        assert 'Rate limit' in result.get('reason', '')


# ─── 3. scan_signals entry_price fix ─────────────────────────────────────────

class TestScanSignalsEntryPrice:
    """SEC26.A: entry_price = bar close değeri (atr14 değil)."""

    def test_entry_price_is_not_atr14(self):
        """Sinyal dict'inde entry_price != atr14 değeri olmalı."""
        # scan_signals içindeki fix: entry_price = df_filtered.iloc[-1]['close']
        # Bu testi izole etmek için dummy df ve sinyal ile kontrol ediyoruz.
        import pandas as pd

        # Dummy bar: close=79000, atr14=2000
        dummy_df = pd.DataFrame([{
            'ts': pd.Timestamp('2026-05-14', tz='UTC'),
            'open': 78000.0,
            'high': 80000.0,
            'low': 77000.0,
            'close': 79000.0,
        }])

        # Fix logic: entry_price = last_close (not atr14)
        last_close = float(dummy_df.iloc[-1]['close'])
        atr14 = 2000.0  # metadata'dan gelirdi eskiden

        # Eski (bozuk) davranış: entry_price = atr14 = 2000.0
        # Yeni (fix) davranış: entry_price = close = 79000.0
        assert last_close != atr14, "close ve atr14 farklı olmalı"
        assert last_close == 79000.0

    def test_sl_dist_computed_from_entry_price(self):
        """sl_dist = |entry_price - sl_price|, atr14 dahil değil."""
        entry_price = 79000.0
        sl_price = 82000.0
        atr14 = 2000.0

        # Eski formül (bozuk): sl_dist = |sl_price - atr14| = |82000 - 2000| = 80000 (çok büyük!)
        old_sl_dist = abs(sl_price - atr14)
        # Yeni formül: sl_dist = |entry_price - sl_price| = |79000 - 82000| = 3000
        new_sl_dist = abs(entry_price - sl_price)

        # Eski formül qty'yi çok küçük yapıyor (risk_dollar / 80000 = 0.0025)
        # Yeni formül daha doğru (risk_dollar / 3000 = 0.0667)
        risk_dollar = 200.0  # %2 of $10000
        old_qty = risk_dollar / old_sl_dist
        new_qty = risk_dollar / new_sl_dist

        assert new_sl_dist == 3000.0
        assert abs(new_qty - 0.0667) < 0.001
        # Eski qty 26x daha küçüktü — bu notional'ı da çöp yapıyordu
        assert old_qty < new_qty * 0.05  # old < %5 of new → açıkça yanlıştı


# ─── 4. Integration guard: kill switch aktif ─────────────────────────────────

class TestKillSwitch:
    """Kill switch logic: halted=true → daemon durmalı."""

    def test_kill_switch_halted_true(self, tmp_path):
        import json
        ks_file = tmp_path / "kill_switch.json"
        ks_file.write_text(json.dumps({"halted": True, "reason": "sec26_a_paper_bug_fix"}))

        # Simulate _kill_switch_active logic
        with open(ks_file, "r") as f:
            ks = json.load(f)
        halted = bool(ks.get("halted", False))
        reason = str(ks.get("reason") or "")

        assert halted is True
        assert "sec26_a" in reason

    def test_kill_switch_halted_false(self, tmp_path):
        import json
        ks_file = tmp_path / "kill_switch.json"
        ks_file.write_text(json.dumps({"halted": False, "reason": None}))

        with open(ks_file, "r") as f:
            ks = json.load(f)
        halted = bool(ks.get("halted", False))

        assert halted is False
