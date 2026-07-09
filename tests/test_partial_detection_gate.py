"""A1-01 partial-tespit kapısı — dalga-5 (2026-07-10).

W1-S1 (sl_order_id senkronu) yan etkisi: TP1 kısmi dolduğunda SL hâlâ açık →
eski kapı `(not tp_open and not sl_open) or sl_gone_pos_flat` iki dalda da False
→ partial HİÇ tespit edilmiyordu → futures_partial_closes boş → ts30 runner
time-stop çıpasız (turnuva-valide çıkış canlıda sessizce iptal). W1-S1 öncesi
tespit bayat-SL-ID KAZASIYLA çalışıyordu; S1 kazayı kapatınca tespit öldü.

Fix: _should_check_protection_fills saf fonksiyonu + TP-kayıp+pozisyon-açık dalı.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.futures_daemon as fd  # noqa: E402

check = fd._should_check_protection_fills


def test_tp1_partial_with_sl_still_open_now_detected():
    """A1-01 ÇEKIRDEK VAKA: TP1 doldu (açık sette yok), SL hâlâ açık, pozisyonda
    qty var → history sorgusuna GİRİLMELİ. Eski kod: False (partial ölümü)."""
    assert check(tp_oid="TP1", sl_oid="SL1", tp_open=False, sl_open=True, qty_now=5.0) is True


def test_both_open_no_action():
    """TP+SL ikisi de borsada duruyor → hiçbir şey olmadı, sorgu yok."""
    assert check(tp_oid="TP1", sl_oid="SL1", tp_open=True, sl_open=True, qty_now=5.0) is False


def test_both_gone_full_close_detected():
    """İkisi de kayıp → tam kapanış yolu (mevcut davranış korunur)."""
    assert check(tp_oid="TP1", sl_oid="SL1", tp_open=False, sl_open=False, qty_now=0.0) is True


def test_sl_gone_pos_flat_detected():
    """SL kayıp + pozisyon flat (TP açık kalmış olsa da) → tam kapanış
    (2026-06-11 ZEC+ATOM kuralı korunur)."""
    assert check(tp_oid="TP1", sl_oid="SL1", tp_open=True, sl_open=False, qty_now=0.0) is True


def test_sl_gone_but_pos_open_tp_open_no_false_trigger():
    """SL cancel-replace ANINDA (yeni SL henüz sette görünmüyor olabilir) +
    pozisyon açık + TP açık → tetikleme YOK (yanlış-partial koruması)."""
    assert check(tp_oid="TP1", sl_oid="SL_OLD", tp_open=True, sl_open=False, qty_now=5.0) is False


def test_no_tp_id_position_open_sl_open():
    """TP id yok (tek-emir modu) + SL açık + pozisyon açık → sorgu yok."""
    assert check(tp_oid=None, sl_oid="SL1", tp_open=False, sl_open=True, qty_now=5.0) is False


def test_tp_gone_flat_position_full_close():
    """TP kayıp + pozisyon flat + SL kayıp → tam kapanış dalı."""
    assert check(tp_oid="TP1", sl_oid="SL1", tp_open=False, sl_open=False, qty_now=0.0) is True


def test_daemon_uses_pure_function():
    """Kaynak-pin: fill-detection döngüsü saf fonksiyonu çağırıyor."""
    src = (ROOT / "scripts" / "futures_daemon.py").read_text(encoding="utf-8")
    assert src.count("_should_check_protection_fills(") >= 2  # def + çağrı
    # eski inline koşul kalmadı
    assert "if (not tp_open and not sl_open) or _sl_gone_pos_flat:" not in src
