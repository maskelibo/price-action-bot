"""Pyramid Break-Even SL protect testleri — Seçenek D (2026-05-20).

CEO raporu: reports/ceo/2026-05-20_pyramid_vs_multitarget_conflict.md
Değişiklik: scripts/futures_daemon.py _desired_sl_price() + position_check() wiring.

Test senaryoları:
  1. leg-2 dolmamış → SL davranışı eski (backward-compat / parity)
  2. leg-2 FILLED + mark 1.0R-1.5R arası → SL = break-even (LONG)
  3. leg-2 FILLED + mark 1.0R-1.5R arası → SL = break-even (SHORT)
  4. leg-2 FILLED + mark > TP2 → trailing zaten BE üstünde, regression yok (LONG)
  5. leg-2 FILLED + mark > TP2 → trailing zaten BE üstünde, regression yok (SHORT)
  6. pyramid kapalı pozisyon (pyramid_leg_filled=False default) → hiç etkilenmez
  7. ratchet: BE'ye çekildikten sonra geri gitmiyor (intended_sl <= entry zaten)
  8. mark tam TP2'de (sınır) — leg-2 FILLED → BE döner (TP2 aşılmamış bölge)
  9. mark tam TP2'nin 1 tick üstü — leg-2 FILLED → trailing (TP2 aşılmış bölge)
 10. LONG: intended_sl entry'den düşük (normal) → BE = entry
 11. SHORT: intended_sl entry'den yüksek (normal) → BE = entry
 12. Dejenere: initial_r=0 → intended_sl döner (guard korunuyor)
 13. mark=0 → intended_sl döner (guard korunuyor)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# ─────────────────────────────────────────────────────────────────────────────
# _desired_sl_price'ı daemon modülünden izole import.
# Daemon modülü import sırasında ccxt/DB bağlantısı açmaz — modül-seviye kod
# sadece sabitler ve fonksiyon tanımlarından oluşuyor; exchange bağlantısı
# yalnız çalışma-zamanı fonksiyonları içinde açılır. Ancak ROOT = Path(__file__)
# satırı compile-time değil run-time olduğundan importlib.util ile güvenle
# import edilebilir.
# ─────────────────────────────────────────────────────────────────────────────
import importlib.util

_DAEMON_PATH = ROOT / "scripts" / "futures_daemon.py"
_spec = importlib.util.spec_from_file_location("_futures_daemon_stub", _DAEMON_PATH)
_daemon_mod = importlib.util.module_from_spec(_spec)
# PA_LOG_QUIET ayarla — daemon kendi log handler'ını kuruyor, test ortamında sustur
import os
os.environ.setdefault("PA_LOG_QUIET", "1")
import warnings
warnings.filterwarnings("ignore")
_spec.loader.exec_module(_daemon_mod)  # type: ignore[union-attr]

_desired_sl_price = _daemon_mod._desired_sl_price
_TRAIL_PCT = _daemon_mod._TRAIL_PCT


# ─────────────────────────────────────────────────────────────────────────────
# Sabitler (gerçekçi BTC örneği)
# ─────────────────────────────────────────────────────────────────────────────

ENTRY = 65_000.0
SL    = 63_700.0    # 1R = 1300
R     = abs(ENTRY - SL)   # 1300.0

TP1_LONG = ENTRY + R        # 66_300
TP2_LONG = ENTRY + 1.5 * R  # 66_950

# SHORT mirror
ENTRY_S = 65_000.0
SL_S    = 66_300.0   # 1R = 1300 SHORT
TP1_S   = ENTRY_S - R        # 63_700
TP2_S   = ENTRY_S - 1.5 * R  # 63_050


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: leg-2 dolmamış → backward-compat, SL değişmez (1.0R-1.5R bölgesi)
# ─────────────────────────────────────────────────────────────────────────────

def test_no_pyramid_leg_filled_returns_intended_sl_long():
    """pyramid_leg_filled=False (default) → 1.0R-1.5R arasında orijinal SL."""
    mark = ENTRY + 1.2 * R  # 1.2R, TP2 aşılmamış
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=False)
    assert result == pytest.approx(SL)


def test_no_pyramid_leg_filled_returns_intended_sl_short():
    """pyramid_leg_filled=False (default) → 1.0R-1.5R arasında orijinal SL (SHORT)."""
    mark = ENTRY_S - 1.2 * R   # 1.2R, TP2 aşılmamış
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=False)
    assert result == pytest.approx(SL_S)


def test_default_param_is_false():
    """pyramid_leg_filled varsayılanı False — eski çağıranlar etkilenmez."""
    mark = ENTRY + 1.2 * R
    with_param  = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=False)
    without_param = _desired_sl_price("long", ENTRY, SL, mark)  # default
    assert with_param == pytest.approx(without_param)


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: leg-2 FILLED + mark 1.0R-1.5R arası → BE (LONG)
# ─────────────────────────────────────────────────────────────────────────────

def test_be_protect_long_at_1_0R():
    """Mark tam 1.0R'da, leg-2 FILLED → BE (entry) döner."""
    mark = ENTRY + 1.0 * R   # 66_300 (TP2'nin altı)
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=True)
    assert result == pytest.approx(ENTRY)   # max(entry, intended_sl) = entry


def test_be_protect_long_at_1_2R():
    """Mark 1.2R'da, leg-2 FILLED → BE döner."""
    mark = ENTRY + 1.2 * R
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=True)
    assert result == pytest.approx(ENTRY)


def test_be_protect_long_at_1_49R():
    """Mark TP2'ye çok yakın (1.49R), leg-2 FILLED → hala BE (aşılmadı)."""
    mark = ENTRY + 1.49 * R
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=True)
    assert result == pytest.approx(ENTRY)


def test_be_protect_long_be_above_intended_sl():
    """BE (entry) her zaman intended_sl'den iyi (daha yüksek, LONG)."""
    mark = ENTRY + 1.2 * R
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=True)
    assert result > SL    # break-even > original SL


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: leg-2 FILLED + mark 1.0R-1.5R arası → BE (SHORT)
# ─────────────────────────────────────────────────────────────────────────────

def test_be_protect_short_at_1_0R():
    """Mark tam 1.0R'da (SHORT), leg-2 FILLED → BE (entry) döner."""
    mark = ENTRY_S - 1.0 * R   # 63_700
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    assert result == pytest.approx(ENTRY_S)   # min(entry, intended_sl) = entry


def test_be_protect_short_at_1_3R():
    """Mark 1.3R'da (SHORT), leg-2 FILLED → BE döner."""
    mark = ENTRY_S - 1.3 * R
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    assert result == pytest.approx(ENTRY_S)


def test_be_protect_short_be_below_intended_sl():
    """BE (entry) her zaman intended_sl'den iyi (daha düşük, SHORT)."""
    mark = ENTRY_S - 1.2 * R
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    assert result < SL_S   # break-even < original SL (SHORT için lehe = daha düşük SL)


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: leg-2 FILLED + mark > TP2 → trailing (LONG) — BE geçilmiş, regression yok
# ─────────────────────────────────────────────────────────────────────────────

def test_trailing_after_tp2_long_no_regression():
    """TP2 aşıldıktan sonra trailing aktif; BE ile karşılaştırıldığında daha iyi."""
    mark = ENTRY + 2.0 * R   # TP2 = 1.5R aşıldı
    result_with_be    = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=True)
    result_without_be = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=False)
    # TP2 aşılmış bölgede: iki çağrı da aynı trailing formülüne girer
    assert result_with_be == pytest.approx(result_without_be)
    # Trailing SL, TP1'den (1R) yüksek olmalı
    assert result_with_be >= TP1_LONG


def test_trailing_after_tp2_long_above_be():
    """Trailing SL her zaman entry (BE) üstünde kalmalı (1.6R mark)."""
    mark = ENTRY + 1.6 * R   # az ötesi TP2
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=True)
    assert result >= ENTRY   # BE veya üstü


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: leg-2 FILLED + mark > TP2 → trailing (SHORT) — regression yok
# ─────────────────────────────────────────────────────────────────────────────

def test_trailing_after_tp2_short_no_regression():
    """TP2 aşıldıktan sonra (SHORT) trailing aktif; BE ile aynı davranış."""
    mark = ENTRY_S - 2.0 * R   # SHORT TP2 = 1.5R aşıldı
    result_with_be    = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    result_without_be = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=False)
    assert result_with_be == pytest.approx(result_without_be)
    assert result_with_be <= TP1_S   # trailing SL, TP1 (1R) altında olmalı (SHORT)


def test_trailing_after_tp2_short_below_be():
    """Trailing SL, SHORT entry (BE) altında kalmalı."""
    mark = ENTRY_S - 1.6 * R
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    assert result <= ENTRY_S


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: pyramid kapalı pozisyon → hiç etkilenmez (legacy / non-pyramid)
# ─────────────────────────────────────────────────────────────────────────────

def test_non_pyramid_position_unaffected():
    """pyramid_leg_filled=False (default) → mevcut single-leg pozisyonlar etkilenmez."""
    # Fiyat mark 1.0R-1.5R arasında
    mark = ENTRY + 1.2 * R
    result = _desired_sl_price("long", ENTRY, SL, mark)  # parametre verilmedi
    assert result == pytest.approx(SL)
    # mark TP2 üstünde → trailing (TP1'e eşit veya üstü)
    mark2 = ENTRY + 2.5 * R
    result2 = _desired_sl_price("long", ENTRY, SL, mark2)
    assert result2 >= TP1_LONG   # trailing aktif (min: TP1 seviyesinde clamp)


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: ratchet — BE'ye çekildikten sonra geri gitmiyor
# ─────────────────────────────────────────────────────────────────────────────

def test_ratchet_be_does_not_go_back():
    """BE = entry > intended_sl; fonksiyon BE döndürür, intended_sl'e dönmez."""
    # LONG: entry=65000, sl=63700 → BE=65000 > sl
    mark_be = ENTRY + 1.1 * R   # 1.1R, leg-2 FILLED
    be_result = _desired_sl_price("long", ENTRY, SL, mark_be, pyramid_leg_filled=True)
    assert be_result == pytest.approx(ENTRY)
    # BE (65000) > SL (63700) → ratchet (bekçide max ile koru) ile geri gidemez
    assert be_result > SL


def test_ratchet_short_be_does_not_go_back():
    """SHORT: BE = entry < intended_sl; fonksiyon BE döndürür."""
    mark_be = ENTRY_S - 1.1 * R
    be_result = _desired_sl_price("short", ENTRY_S, SL_S, mark_be, pyramid_leg_filled=True)
    assert be_result == pytest.approx(ENTRY_S)
    assert be_result < SL_S


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Mark tam TP2'de — sınır davranışı
# ─────────────────────────────────────────────────────────────────────────────

def test_mark_exactly_at_tp2_long_leg_filled():
    """Mark tam TP2 = entry + 1.5R → 'mark <= tp2' koşulu True → BE döner."""
    mark = TP2_LONG   # tam sınır
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=True)
    assert result == pytest.approx(ENTRY)   # TP2 aşılmamış → BE


def test_mark_exactly_at_tp2_short_leg_filled():
    """Mark tam TP2 (SHORT) → 'mark >= tp2' koşulu True → BE döner."""
    mark = TP2_S
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    assert result == pytest.approx(ENTRY_S)


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: Mark 1 tick TP2 üstü — trailing bölgesi
# ─────────────────────────────────────────────────────────────────────────────

def test_mark_just_above_tp2_long_leg_filled():
    """Mark TP2 + 0.01 → trailing formülü devreye girer."""
    mark = TP2_LONG + 0.01
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=True)
    # Trailing: max(TP1, mark * (1 - _TRAIL_PCT))
    expected = max(TP1_LONG, mark * (1.0 - _TRAIL_PCT))
    assert result == pytest.approx(expected)
    assert result > ENTRY   # trailing BE üstünde


def test_mark_just_above_tp2_short_leg_filled():
    """Mark TP2 - 0.01 (SHORT) → trailing formülü devreye girer."""
    mark = TP2_S - 0.01
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    expected = min(TP1_S, mark * (1.0 + _TRAIL_PCT))
    assert result == pytest.approx(expected)
    assert result < ENTRY_S


# ─────────────────────────────────────────────────────────────────────────────
# Test 10-11: max()/min() semantiği — BE her zaman intended_sl'den iyi
# ─────────────────────────────────────────────────────────────────────────────

def test_long_max_semantics_be_always_gte_intended_sl():
    """LONG: max(entry, intended_sl) = entry çünkü entry > intended_sl her zaman."""
    # Bu testte entry <= intended_sl (tersine çevrilmiş, savunma testi)
    entry_inv = 65_000.0
    sl_inv = 65_500.0   # SL entry'den yüksek (hatalı giriş, ama savunma)
    mark = entry_inv + 1.2 * abs(entry_inv - sl_inv)
    result = _desired_sl_price("long", entry_inv, sl_inv, mark, pyramid_leg_filled=True)
    # max(entry_inv, sl_inv) = sl_inv (65500) — daha iyi SL zaten var, korunur
    assert result == pytest.approx(max(entry_inv, sl_inv))


def test_short_min_semantics_be_always_lte_intended_sl():
    """SHORT: min(entry, intended_sl) = entry çünkü entry < intended_sl her zaman."""
    entry_inv = 65_000.0
    sl_inv = 64_500.0   # SL entry'den düşük (hatalı giriş)
    mark = entry_inv - 1.2 * abs(entry_inv - sl_inv)
    result = _desired_sl_price("short", entry_inv, sl_inv, mark, pyramid_leg_filled=True)
    assert result == pytest.approx(min(entry_inv, sl_inv))


# ─────────────────────────────────────────────────────────────────────────────
# Test 12-13: Dejenere guard — mevcut davranış korunuyor
# ─────────────────────────────────────────────────────────────────────────────

def test_degenerate_initial_r_zero():
    """initial_r=0 → guard devreye girer, intended_sl döner (BE bile olsa)."""
    result = _desired_sl_price("long", 65_000.0, 65_000.0, 65_000.0, pyramid_leg_filled=True)
    assert result == pytest.approx(65_000.0)


def test_degenerate_mark_zero():
    """mark=0 → guard devreye girer, intended_sl döner."""
    result = _desired_sl_price("long", ENTRY, SL, 0.0, pyramid_leg_filled=True)
    assert result == pytest.approx(SL)
