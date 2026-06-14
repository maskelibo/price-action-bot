"""Pyramid Break-Even SL protect testleri — Seçenek D + trail sıkılaştırma (2026-06-01).

CEO raporu: reports/ceo/2026-05-20_pyramid_vs_multitarget_conflict.md
Değişiklik: scripts/futures_daemon.py _desired_sl_price() + position_check() wiring.

2026-06-01 trail sıkılaştırma (XLM kâr→zarar vakası):
  - Trail ARTIK TP1 (1R) sonrası başlıyor (eski: TP2 = 1.5R sonrası).
  - pyramid_leg_filled=False: mark >= TP1 → trailing LONG: max(entry, mark*(1-pct)).
  - pyramid_leg_filled=True: mark < TP1 → BE; mark >= TP1 → trailing.

Test senaryoları:
  1. leg-2 dolmamış, mark 1.0R-1.5R arası → TP1 geçildi, trail aktif (YENİ DAVRANIŞ)
  2. leg-2 FILLED + mark 1.0R-1.5R arası → SL = break-even (pyramid) veya trail (no pyr)
  3. leg-2 FILLED + mark 1.0R-1.5R arası → SL = break-even (SHORT)
  4. leg-2 FILLED + mark > TP2 → trailing zaten BE üstünde, regression yok (LONG)
  5. leg-2 FILLED + mark > TP2 → trailing zaten BE üstünde, regression yok (SHORT)
  6. pyramid kapalı pozisyon (pyramid_leg_filled=False) → TP1 sonrası trail aktif
  7. ratchet: BE'ye çekildikten sonra geri gitmiyor
  8. mark tam TP1'de (sınır) — leg-2 FILLED → trail başlar (yeni: TP1 eşiği)
  9. mark TP1 + 0.01 → trail formülü (yeni: TP1 bazlı)
 10. LONG: BE kilidi entry garantili
 11. SHORT: BE kilidi entry garantili
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
SL = 63_700.0  # 1R = 1300
R = abs(ENTRY - SL)  # 1300.0

TP1_LONG = ENTRY + R  # 66_300
TP2_LONG = ENTRY + 1.5 * R  # 66_950

# SHORT mirror
ENTRY_S = 65_000.0
SL_S = 66_300.0  # 1R = 1300 SHORT
TP1_S = ENTRY_S - R  # 63_700
TP2_S = ENTRY_S - 1.5 * R  # 63_050


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: leg-2 dolmamış → backward-compat, SL değişmez (1.0R-1.5R bölgesi)
# ─────────────────────────────────────────────────────────────────────────────


def test_no_pyramid_leg_filled_trail_active_at_tp1_long():
    """YENİ DAVRANIŞ (2026-06-01): pyramid_leg_filled=False, mark 1.2R (TP1 geçildi)
    → trail aktif: max(entry, mark*(1-trail_pct)), orijinal SL döndürülmez."""
    mark = ENTRY + 1.2 * R  # 1.2R > 1.0R = TP1 → trail aktif
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=False)
    expected_trail = mark * (1.0 - _TRAIL_PCT)
    expected = max(ENTRY, expected_trail)
    assert result == pytest.approx(expected)
    # BE kilidi: SL >= entry
    assert result >= ENTRY


def test_no_pyramid_leg_filled_trail_active_at_tp1_short():
    """YENİ DAVRANIŞ: pyramid_leg_filled=False, mark 1.2R (SHORT TP1 geçildi)
    → trail aktif: min(entry, mark*(1+trail_pct))."""
    mark = ENTRY_S - 1.2 * R  # SHORT: TP1 geçildi
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=False)
    expected_trail = mark * (1.0 + _TRAIL_PCT)
    expected = min(ENTRY_S, expected_trail)
    assert result == pytest.approx(expected)
    # BE kilidi: SL <= entry (SHORT)
    assert result <= ENTRY_S


def test_default_param_is_false():
    """pyramid_leg_filled varsayılanı False — explicit False ile aynı sonuç."""
    mark = ENTRY + 1.2 * R
    with_param = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=False)
    without_param = _desired_sl_price("long", ENTRY, SL, mark)  # default
    assert with_param == pytest.approx(without_param)


def test_below_tp1_no_trail_long():
    """Mark < TP1 → trail YOK, orijinal SL döner (TP1 eşiği korunuyor)."""
    mark = ENTRY + 0.8 * R  # 0.8R < 1.0R TP1
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=False)
    assert result == pytest.approx(SL)


def test_below_tp1_no_trail_short():
    """Mark SHORT TP1'e ulaşmadı → orijinal SL döner."""
    mark = ENTRY_S - 0.8 * R  # 0.8R < 1.0R TP1 (SHORT)
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=False)
    assert result == pytest.approx(SL_S)


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: leg-2 FILLED + mark 1.0R-1.5R arası → BE (LONG)
# ─────────────────────────────────────────────────────────────────────────────


def test_be_protect_long_at_1_0R():
    """Mark tam 1.0R'da, leg-2 FILLED → BE (entry) döner."""
    mark = ENTRY + 1.0 * R  # 66_300 (TP2'nin altı)
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=True)
    assert result == pytest.approx(ENTRY)  # max(entry, intended_sl) = entry


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
    assert result > SL  # break-even > original SL


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: leg-2 FILLED + mark 1.0R-1.5R arası → BE (SHORT)
# ─────────────────────────────────────────────────────────────────────────────


def test_be_protect_short_at_1_0R():
    """Mark tam 1.0R'da (SHORT), leg-2 FILLED → BE (entry) döner."""
    mark = ENTRY_S - 1.0 * R  # 63_700
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    assert result == pytest.approx(ENTRY_S)  # min(entry, intended_sl) = entry


def test_be_protect_short_at_1_3R():
    """Mark 1.3R'da (SHORT), leg-2 FILLED → BE döner."""
    mark = ENTRY_S - 1.3 * R
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    assert result == pytest.approx(ENTRY_S)


def test_be_protect_short_be_below_intended_sl():
    """BE (entry) her zaman intended_sl'den iyi (daha düşük, SHORT)."""
    mark = ENTRY_S - 1.2 * R
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    assert result < SL_S  # break-even < original SL (SHORT için lehe = daha düşük SL)


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: leg-2 FILLED + mark > TP2 → trailing (LONG) — BE geçilmiş, regression yok
# ─────────────────────────────────────────────────────────────────────────────


def test_trailing_after_tp2_long_no_regression():
    """TP2 aşıldıktan sonra (mark=2R) trailing aktif.
    YENİ DAVRANIŞ: max(entry, mark*(1-pct)).
    sl_pct=0.025 + trail_pct=0.04: trail eşiği ~2.08R → 2R'de hala BE(entry).
    Temel garanti: SL >= entry (asla zarara dönmez) + iki çağrı eşit."""
    mark = ENTRY + 2.0 * R  # TP2 = 1.5R aşıldı
    result_with_be = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=True)
    result_without_be = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=False)
    # Her iki çağrı da trail formülüne giriyor (TP1 geçildi)
    assert result_with_be == pytest.approx(result_without_be)
    # BE kilidi: SL >= entry (asla zarara dönmez)
    assert result_with_be >= ENTRY


def test_trailing_after_tp2_long_above_be():
    """Trailing SL her zaman entry (BE) üstünde kalmalı (1.6R mark)."""
    mark = ENTRY + 1.6 * R  # az ötesi TP2
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=True)
    assert result >= ENTRY  # BE veya üstü


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: leg-2 FILLED + mark > TP2 → trailing (SHORT) — regression yok
# ─────────────────────────────────────────────────────────────────────────────


def test_trailing_after_tp2_short_no_regression():
    """TP2 aşıldıktan sonra (SHORT) trailing aktif; BE ile aynı davranış.
    YENİ DAVRANIŞ: min(entry, mark*(1+pct)). BE kilidi: SL <= entry."""
    mark = ENTRY_S - 2.0 * R  # SHORT TP2 = 1.5R aşıldı
    result_with_be = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    result_without_be = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=False)
    assert result_with_be == pytest.approx(result_without_be)
    # BE kilidi: SL <= entry (SHORT'ta asla zarara dönmez)
    assert result_with_be <= ENTRY_S


def test_trailing_after_tp2_short_below_be():
    """Trailing SL, SHORT entry (BE) altında kalmalı."""
    mark = ENTRY_S - 1.6 * R
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    assert result <= ENTRY_S


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: pyramid kapalı pozisyon → hiç etkilenmez (legacy / non-pyramid)
# ─────────────────────────────────────────────────────────────────────────────


def test_non_pyramid_position_trail_from_tp1():
    """YENİ DAVRANIŞ: pyramid_leg_filled=False → single-leg pozisyon TP1'den trail.
    mark < TP1: orijinal SL. mark >= TP1: trail aktif (BE + pct-trail)."""
    # mark < TP1: trail yok
    mark_below = ENTRY + 0.9 * R
    result_below = _desired_sl_price("long", ENTRY, SL, mark_below)
    assert result_below == pytest.approx(SL)
    # mark = 1.2R > TP1: trail aktif
    mark_above = ENTRY + 1.2 * R
    result_above = _desired_sl_price("long", ENTRY, SL, mark_above)
    expected = max(ENTRY, mark_above * (1.0 - _TRAIL_PCT))
    assert result_above == pytest.approx(expected)
    assert result_above >= ENTRY  # BE kilidi
    # mark TP2 üstünde → trailing (BE üstünde)
    mark2 = ENTRY + 2.5 * R
    result2 = _desired_sl_price("long", ENTRY, SL, mark2)
    assert result2 >= ENTRY  # trailing BE üstünde


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: ratchet — BE'ye çekildikten sonra geri gitmiyor
# ─────────────────────────────────────────────────────────────────────────────


def test_ratchet_be_does_not_go_back():
    """BE = entry > intended_sl; fonksiyon BE döndürür, intended_sl'e dönmez."""
    # LONG: entry=65000, sl=63700 → BE=65000 > sl
    mark_be = ENTRY + 1.1 * R  # 1.1R, leg-2 FILLED
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
    """Mark tam TP2 = entry + 1.5R → TP1 aşıldı (TP2 > TP1) → trail aktif.
    YENİ DAVRANIŞ: TP1'den itibaren trail; TP2'de trail = max(entry, TP2*(1-pct))."""
    mark = TP2_LONG  # 1.5R > 1.0R → trail aktif
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=True)
    expected = max(ENTRY, mark * (1.0 - _TRAIL_PCT))
    assert result == pytest.approx(expected)
    assert result >= ENTRY  # BE kilidi


def test_mark_exactly_at_tp2_short_leg_filled():
    """Mark tam TP2 (SHORT) → TP1 aşıldı → trail aktif.
    YENİ DAVRANIŞ: min(entry, TP2*(1+pct))."""
    mark = TP2_S
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    expected = min(ENTRY_S, mark * (1.0 + _TRAIL_PCT))
    assert result == pytest.approx(expected)
    assert result <= ENTRY_S  # BE kilidi


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: Mark 1 tick TP2 üstü — trailing bölgesi
# ─────────────────────────────────────────────────────────────────────────────


def test_mark_just_above_tp2_long_leg_filled():
    """Mark TP2 + 0.01 → trail aktif (TP1'den beri zaten aktifti).
    YENİ formül: max(entry, mark*(1-pct))  (TP1 clamp kaldırıldı, entry clamp var)."""
    mark = TP2_LONG + 0.01
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=True)
    expected = max(ENTRY, mark * (1.0 - _TRAIL_PCT))
    assert result == pytest.approx(expected)
    assert result >= ENTRY  # BE kilidi


def test_mark_just_above_tp2_short_leg_filled():
    """Mark TP2 - 0.01 (SHORT) → trail aktif.
    YENİ formül: min(entry, mark*(1+pct))."""
    mark = TP2_S - 0.01
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    expected = min(ENTRY_S, mark * (1.0 + _TRAIL_PCT))
    assert result == pytest.approx(expected)
    assert result <= ENTRY_S  # BE kilidi


# ─────────────────────────────────────────────────────────────────────────────
# Test 10-11: max()/min() semantiği — BE her zaman intended_sl'den iyi
# ─────────────────────────────────────────────────────────────────────────────


def test_long_be_kilidi_sl_asla_entry_altina_dusmez():
    """LONG: mark >= TP1 → trail aktif → BE kilidi: SL >= entry her zaman.
    Normal giriş (sl < entry): SL = max(entry, mark*(1-pct)) >= entry."""
    mark = ENTRY + 1.2 * R  # normal senaryo
    result = _desired_sl_price("long", ENTRY, SL, mark, pyramid_leg_filled=True)
    assert result >= ENTRY  # BE kilidi: asla zarar yok


def test_short_be_kilidi_sl_asla_entry_ustune_cikmaz():
    """SHORT: mark <= TP1 → trail aktif → BE kilidi: SL <= entry her zaman.
    Normal giriş (sl > entry): SL = min(entry, mark*(1+pct)) <= entry."""
    mark = ENTRY_S - 1.2 * R  # normal senaryo
    result = _desired_sl_price("short", ENTRY_S, SL_S, mark, pyramid_leg_filled=True)
    assert result <= ENTRY_S  # BE kilidi: asla zarar yok


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
