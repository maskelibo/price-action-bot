"""reconcile fail-closed — kapanış sprinti 2026-07-08 (dalga-4 T8-DR6 CRIT).

_fetch_exchange_positions ccxt auth fail olunca EMEKLİ futures15m.stderr.log'dan
eski pozisyon okuyup boş-OLMAYAN liste döndürüyor (source='log_parse'). reconcile()
SAFE_MODE'u yalnız len(exchange)==0 ile tetikliyordu → fallback dolu olunca atlanıp
canlı journal'daki açık pozisyonları "orphan" sanıp YANLIŞ kapatıyor (07:16
AAVE/ZEC kazası bunu canlı kanıtladı — journal'a 2 yanlış reconcile_orphan yazıldı).

Fix: _should_skip_reconcile saf-fonksiyonu — exchange ccxt'ten gelmiyorsa
(herhangi biri log_parse) VE journal'da açık varsa → SKIP (fail-closed).
orphan-close yalnız GERÇEK borsa okumasıyla yapılır.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.reconcile_journal as rj  # noqa: E402


def _ex(source: str, n: int = 2) -> dict:
    return {
        f"SYM{i}/USDT": {"symbol": f"SYM{i}/USDT", "side": "long", "qty": 1.0, "source": source}
        for i in range(n)
    }


def _journal(n: int = 3) -> list:
    return [{"symbol": f"J{i}/USDT", "side": "long", "fill_qty": 1.0} for i in range(n)]


def test_skip_when_exchange_empty_and_journal_open():
    """Mevcut SAFE_MODE korunur: borsa boş + journal açık → skip."""
    skip, reason = rj._should_skip_reconcile({}, _journal(3))
    assert skip is True
    assert "empty" in reason.lower() or "boş" in reason.lower()


def test_skip_when_exchange_from_log_fallback():
    """YENİ: exchange log-fallback'ten (ccxt fail) + journal açık → skip.
    Bu, 07:16 AAVE/ZEC yanlış-orphan kazasını önler."""
    skip, reason = rj._should_skip_reconcile(_ex("log_parse", 2), _journal(3))
    assert skip is True
    assert "log" in reason.lower() or "ccxt" in reason.lower() or "güvenilmez" in reason.lower()


def test_proceed_when_exchange_from_ccxt():
    """Gerçek ccxt okuması → reconcile devam eder (orphan-close serbest)."""
    skip, _ = rj._should_skip_reconcile(_ex("ccxt", 2), _journal(3))
    assert skip is False


def test_proceed_when_no_journal_open():
    """Journal boşsa orphan riski yok → devam (phantom-only yol)."""
    skip, _ = rj._should_skip_reconcile(_ex("log_parse", 2), [])
    assert skip is False


def test_mixed_source_is_unsafe():
    """Karışık kaynak (biri log_parse) → güvenilmez → skip."""
    ex = {
        **_ex("ccxt", 1),
        "X/USDT": {"symbol": "X/USDT", "side": "long", "qty": 1.0, "source": "log_parse"},
    }
    skip, _ = rj._should_skip_reconcile(ex, _journal(2))
    assert skip is True


def test_missing_source_treated_as_unsafe():
    """source alanı yoksa (bilinmeyen köken) → güvenli tarafta skip."""
    ex = {"X/USDT": {"symbol": "X/USDT", "side": "long", "qty": 1.0}}
    skip, _ = rj._should_skip_reconcile(ex, _journal(2))
    assert skip is True
