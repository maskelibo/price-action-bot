"""Slippage ölçüm tamiri — execution paketi 2026-07-10 (0.0 bps bug).

Kök-neden (DB-kanıtlı: 269/303 fill = 0.0, HER sıfır expected==realized):
  Fix A (koruma TP/SL): daemon `_prot_fill_px`'i HEM expected HEM realized
    geçiyordu → fill kendi benchmark'ı → %100 exit 0.0 bps by construction.
  Fix B (giriş): `realized_price=_avg_px`; _avg_px borsa avg vermezse _cur_px'e
    (arrival) düşüyordu → realized==expected → sahte 0.0 (167 market girişi).

İki fix de MEASUREMENT-ONLY: _avg_px/_prot_fill_px (journal/idem/notional) ve
hiçbir trade-kararı değişkeni değişmez; yalnız slippage kaydının referansı düzelir.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.futures_daemon as fd  # noqa: E402
from price_action.execution.slippage_tracker import SlippageTracker  # noqa: E402

# ---------------------------------------------------------------------------
# Pure helper: _slip_expected_from_trigger (Fix A referansı)
# ---------------------------------------------------------------------------


def test_expected_from_trigger_uses_trigger_when_positive():
    assert fd._slip_expected_from_trigger(100.0, 99.5) == 100.0


def test_expected_from_trigger_falls_back_to_fill_when_trigger_zero():
    # trigger yoksa (0) → fill'e döner = dürüst-0 (expected==realized)
    assert fd._slip_expected_from_trigger(0.0, 99.5) == 99.5


def test_expected_from_trigger_falls_back_when_trigger_none():
    assert fd._slip_expected_from_trigger(None, 99.5) == 99.5


# ---------------------------------------------------------------------------
# Pure helper: _slip_realized_from_order (Fix B gerçek-fiyat türetici)
# ---------------------------------------------------------------------------


def test_realized_from_order_prefers_order_average():
    assert fd._slip_realized_from_order(50.2, 50.1, 50.3) == 50.2


def test_realized_from_order_falls_to_price_then_fetched():
    assert fd._slip_realized_from_order(None, 50.1, 50.3) == 50.1
    assert fd._slip_realized_from_order(None, None, 50.3) == 50.3


def test_realized_from_order_none_when_unmeasurable():
    # Hiçbir gerçek fiyat yok → None (çağıran arrival'a düşer, sahte değer YAZMAZ)
    assert fd._slip_realized_from_order(None, None, None) is None
    assert fd._slip_realized_from_order(0, 0, 0) is None


def test_realized_from_order_skips_non_numeric():
    assert fd._slip_realized_from_order("x", None, 50.3) == 50.3


# ---------------------------------------------------------------------------
# record_fill DAVRANIŞI — protective (Fix A) uçtan uca
# ---------------------------------------------------------------------------


def _tracker(tmp_path) -> SlippageTracker:
    return SlippageTracker(db_path=tmp_path / "fills.duckdb")


def test_protective_old_bug_shape_records_zero(tmp_path):
    """ESKİ hata belgesi: expected==realized (ikisi de _prot_fill_px) → 0.0."""
    st = _tracker(tmp_path)
    bps = st.record_fill(
        fill_id="prot_x_sl",
        ts=datetime.now(UTC),
        symbol="DOGE/USDT",
        strategy="vsa_sl",
        side="long",
        expected_price=100.0,
        realized_price=100.0,  # eski daemon şekli
        quantity=10.0,
        fee_usdt=0.0,
        is_maker=True,
        order_type="algo_stop_market",
        mode="paper",
        fill_type="sl",
        tf="15m",
    )
    assert bps == 0.0  # bug: fill kendi benchmark'ı


def test_protective_fixed_shape_records_real_slippage(tmp_path):
    """FIX A: expected=trigger=100, realized=fill=99.5 → |50| bps (gerçek stop-slip)."""
    st = _tracker(tmp_path)
    # daemon artık _slip_expected_from_trigger(trigger, fill) geçiyor
    expected = fd._slip_expected_from_trigger(100.0, 99.5)
    bps = st.record_fill(
        fill_id="prot_y_sl",
        ts=datetime.now(UTC),
        symbol="DOGE/USDT",
        strategy="vsa_sl",
        side="long",
        expected_price=expected,
        realized_price=99.5,
        quantity=10.0,
        fee_usdt=0.0,
        is_maker=True,
        order_type="algo_stop_market",
        mode="paper",
        fill_type="sl",
        tf="15m",
    )
    assert abs(bps) == 50.0  # 0.5% = 50bps; artık 0.0 DEĞİL


# ---------------------------------------------------------------------------
# record_fill DAVRANIŞI — entry (Fix B) uçtan uca
# ---------------------------------------------------------------------------


def test_entry_unmeasurable_records_zero(tmp_path):
    """avg yok → realized _cur_px'e düşer → expected==realized → 0.0 (dürüst)."""
    st = _tracker(tmp_path)
    cur_px = 50.0
    realized = fd._slip_realized_from_order(None, None, None)  # -> None
    bps = st.record_fill(
        fill_id="entry_1",
        ts=datetime.now(UTC),
        symbol="X/USDT",
        strategy="grimes",
        side="long",
        expected_price=cur_px,
        realized_price=(realized if realized else cur_px),
        quantity=1.0,
        fee_usdt=0.0,
        is_maker=False,
        order_type="market",
        mode="paper",
        fill_type="entry",
        tf="15m",
    )
    assert bps == 0.0


def test_entry_genuine_average_records_real_slippage(tmp_path):
    """FIX B: borsa avg=50.2, arrival=50.0 → 40 bps (eski kod 0.0 yazardı)."""
    st = _tracker(tmp_path)
    cur_px = 50.0
    realized = fd._slip_realized_from_order(None, None, 50.2)  # fetch avg
    bps = st.record_fill(
        fill_id="entry_2",
        ts=datetime.now(UTC),
        symbol="X/USDT",
        strategy="grimes",
        side="long",
        expected_price=cur_px,
        realized_price=(realized if realized else cur_px),
        quantity=1.0,
        fee_usdt=0.0,
        is_maker=False,
        order_type="market",
        mode="paper",
        fill_type="entry",
        tf="15m",
    )
    assert abs(bps - 40.0) < 1e-9


def test_entry_correct_fills_unchanged_regression(tmp_path):
    """REGRESYON KALKANI: borsa avg zaten mevcut olan 34 doğru fill AYNI kalır.
    _slip_realized_from_order(order_avg) == eski _avg_px → aynı bps."""
    st = _tracker(tmp_path)
    cur_px = 50.0
    # eski davranış: _avg_px = order.average = 50.15
    realized = fd._slip_realized_from_order(50.15, None, None)
    assert realized == 50.15  # _avg_px ile birebir aynı kaynak
    bps = st.record_fill(
        fill_id="entry_3",
        ts=datetime.now(UTC),
        symbol="X/USDT",
        strategy="grimes",
        side="long",
        expected_price=cur_px,
        realized_price=realized,
        quantity=1.0,
        fee_usdt=0.0,
        is_maker=False,
        order_type="limit",
        mode="paper",
        fill_type="entry",
        tf="15m",
    )
    assert abs(bps - 30.0) < 1e-9  # (50.15-50)/50*1e4 = 30bps, eskisiyle aynı


# ---------------------------------------------------------------------------
# Kaynak-pin: daemon çağrı yerleri fix'leri gerçekten kullanıyor
# ---------------------------------------------------------------------------


def test_daemon_source_wires_both_fixes():
    src = (ROOT / "scripts" / "futures_daemon.py").read_text(encoding="utf-8")
    # Fix A: koruma expected'i trigger helper'ından
    assert "_slip_expected_from_trigger(" in src
    assert "expected_price=_prot_fill_px,\n" not in src  # eski aynı-değişken şekli gitti
    # Fix B: giriş realized'i ayrı ölçüm değişkeninden, _avg_px değil
    assert "_slip_realized_px" in src
    assert "realized_price=_avg_px,\n" not in src  # eski journal-değeri realized gitti
    assert "_slip_realized_from_order(" in src


def test_slippage_tracker_has_module_json_import():
    """json modül-seviyesinde import edilmeli (outlier yolu NameError yemesin)."""
    src = (ROOT / "src" / "price_action" / "execution" / "slippage_tracker.py").read_text(
        encoding="utf-8"
    )
    assert "\nimport json\n" in src
