"""reconcile sembol normalizasyonu — kapanış sprinti 2026-07-09 (T8-DR6 devamı).

get_futures_exchange (doğru auth) ccxt-unified "NEAR/USDT:USDT" formatı döndürür;
journal "NEAR/USDT" tutar. _fetch_exchange_positions ":USDT" suffix'ini strip
etmezse orphan/phantom eşleştirmesi HER pozisyonu hem orphan hem phantom sanar
(9 Tem 19:10 kazası — 2 açık pozisyon yanlış orphan-close yazıldı).

Bu testler CANLI BORSAYA DOKUNMAZ — get_futures_exchange mock'lanır.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.reconcile_journal as rj  # noqa: E402


def _mock_ex(positions: list[dict]) -> MagicMock:
    ex = MagicMock()
    ex.fetch_positions.return_value = positions
    return ex


def test_fetch_normalizes_colon_usdt_suffix():
    """ccxt 'NEAR/USDT:USDT' → journal formatı 'NEAR/USDT'."""
    ex = _mock_ex(
        [{"symbol": "NEAR/USDT:USDT", "side": "short", "contracts": 391.0, "entryPrice": 1.9}]
    )
    with patch("scripts.futures_trade_daily.get_futures_exchange", return_value=ex):
        out = rj._fetch_exchange_positions()
    assert "NEAR/USDT" in out, f"sembol normalize edilmedi: {list(out.keys())}"
    assert "NEAR/USDT:USDT" not in out
    assert out["NEAR/USDT"]["source"] == "ccxt"


def test_reconcile_matches_journal_when_symbols_align(tmp_path, monkeypatch):
    """Sembol-format düzeltilince mutabık journal → 0 orphan, 0 phantom.

    9 Tem kazasının regresyon-önleyicisi: aynı pozisyonlar (journal 'NEAR/USDT',
    borsa 'NEAR/USDT:USDT') artık YANLIŞ orphan/phantom üretmemeli.
    """
    # İzole test journal'ı kur
    jpath = tmp_path / "test_journal.duckdb"
    con = duckdb.connect(str(jpath))
    con.execute("""
        CREATE TABLE futures_signals (
            signal_id VARCHAR PRIMARY KEY, ts TIMESTAMP, symbol VARCHAR, strategy VARCHAR,
            side VARCHAR, fill_price DOUBLE, fill_qty DOUBLE, notional_usdt DOUBLE,
            sl_price DOUBLE, tp_price DOUBLE, status VARCHAR
        )""")
    con.execute("CREATE TABLE futures_trades_closed (trade_id VARCHAR PRIMARY KEY)")
    con.execute(
        "CREATE TABLE futures_partial_closes (close_id VARCHAR, trade_id VARCHAR, qty_closed DOUBLE)"
    )
    from datetime import UTC, datetime

    con.execute(
        "INSERT INTO futures_signals VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            "sig_near",
            datetime.now(UTC),
            "NEAR/USDT",
            "vsa",
            "short",
            1.9,
            391.0,
            748.0,
            2.0,
            1.8,
            "filled",
        ],
    )
    con.commit()
    con.close()

    monkeypatch.setattr(rj, "_JOURNAL", jpath)
    monkeypatch.setattr(rj, "_REPORT_DIR", tmp_path / "reports")

    # Borsa: aynı pozisyon ama ccxt-unified format
    ex = _mock_ex(
        [{"symbol": "NEAR/USDT:USDT", "side": "short", "contracts": 391.0, "entryPrice": 1.9}]
    )
    with patch("scripts.futures_trade_daily.get_futures_exchange", return_value=ex):
        stats = rj.reconcile()

    assert stats["exchange_fetch_ok"] is True  # gerçek ccxt okuması
    assert (
        stats["orphans_closed"] == 0
    ), "mutabık pozisyon YANLIŞ orphan-close edildi (kaza regresyonu)"
    assert stats["phantoms"] == 0, "mutabık pozisyon YANLIŞ phantom sanıldı (kaza regresyonu)"
    assert stats["in_sync"] == 1


def test_reconcile_still_detects_genuine_orphan(tmp_path, monkeypatch):
    """Gerçek orphan (journal'da var, borsada YOK) hâlâ tespit edilmeli."""
    jpath = tmp_path / "test_journal2.duckdb"
    con = duckdb.connect(str(jpath))
    con.execute("""
        CREATE TABLE futures_signals (
            signal_id VARCHAR PRIMARY KEY, ts TIMESTAMP, symbol VARCHAR, strategy VARCHAR,
            side VARCHAR, fill_price DOUBLE, fill_qty DOUBLE, notional_usdt DOUBLE,
            sl_price DOUBLE, tp_price DOUBLE, status VARCHAR
        )""")
    con.execute("CREATE TABLE futures_trades_closed (trade_id VARCHAR PRIMARY KEY)")
    con.execute(
        "CREATE TABLE futures_partial_closes (close_id VARCHAR, trade_id VARCHAR, qty_closed DOUBLE)"
    )
    from datetime import UTC, datetime

    # Journal'da XLM açık ama borsada NEAR var → XLM gerçek orphan
    con.execute(
        "INSERT INTO futures_signals VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            "sig_xlm",
            datetime.now(UTC),
            "XLM/USDT",
            "vsa",
            "long",
            0.25,
            3731.0,
            900.0,
            0.24,
            0.27,
            "filled",
        ],
    )
    con.commit()
    con.close()
    monkeypatch.setattr(rj, "_JOURNAL", jpath)
    monkeypatch.setattr(rj, "_REPORT_DIR", tmp_path / "reports")

    ex = _mock_ex(
        [{"symbol": "NEAR/USDT:USDT", "side": "short", "contracts": 391.0, "entryPrice": 1.9}]
    )
    ex.fapiPrivateGetAllOrders.return_value = []
    # record_close DB yazımını mock'la (bu test orphan TESPİTİNİ doğrular,
    # TradeJournal şema entegrasyonunu değil).
    mock_tj = MagicMock()
    mock_tj.record_close.return_value = True
    mock_tj.get_partial_pnl_sum.return_value = 0.0
    with (
        patch("scripts.futures_trade_daily.get_futures_exchange", return_value=ex),
        patch("price_action.execution.trade_journal.TradeJournal", return_value=mock_tj),
    ):
        stats = rj.reconcile()

    assert stats["exchange_fetch_ok"] is True
    # XLM journal'da açık, borsada yok → orphan tespit edilmeli
    assert stats["orphans_closed"] == 1, "gerçek orphan tespit edilmedi"


def test_no_ccxt_import_of_wrong_env():
    """Kaynak-pin: artık hayalet PA_BINANCE_API_KEY + set_sandbox kullanılmıyor."""
    src = (ROOT / "scripts" / "reconcile_journal.py").read_text(encoding="utf-8")
    assert "get_futures_exchange" in src
    # Gerçek KULLANIM aranır (yorumda anılması serbest — kök-neden açıklaması)
    assert 'os.environ.get("PA_BINANCE_API_KEY"' not in src, "hayalet env hâlâ kullanılıyor"
    assert "ex.set_sandbox_mode(True)" not in src, "deprecated sandbox hâlâ çağrılıyor"
    assert 'split(":")[0]' in src, "sembol normalizasyonu yok"
