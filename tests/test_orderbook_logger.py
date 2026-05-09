"""Birim testleri — orderbook_logger.py

Test kapsamı:
    1. compute_imbalance — normal, dengeli
    2. compute_imbalance — boş kitap (edge case)
    3. compute_imbalance — asimetrik derinlikler (bid-heavy, ask-heavy)
    4. compute_imbalance — top_n kırpma (limit=5, 10 seviye varken)
    5. is_imbalance_aligned — long + bid-heavy → True; short + bid-heavy → False
    6. OrderbookLogger.log_signal_orderbook — sahte exchange ile tam akış (DB+hesap)

NOT: Ağ çağrısı yapılmaz. DuckDB in-memory veya tmp path kullanılır.
"""
from __future__ import annotations

import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from price_action.data.orderbook_logger import (
    OrderbookLogger,
    compute_imbalance,
    fetch_orderbook_snapshot,
    is_imbalance_aligned,
)


# ---------------------------------------------------------------------------
# Test 1: compute_imbalance — normal dengeli kitap
# ---------------------------------------------------------------------------
def test_compute_imbalance_balanced():
    """Eşit bid/ask hacminde imbalance sıfır olmalı."""
    bids = [[100.0, 10.0], [99.5, 10.0], [99.0, 10.0]]
    asks = [[100.5, 10.0], [101.0, 10.0], [101.5, 10.0]]
    result = compute_imbalance(bids, asks, top_n=3)
    assert result == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Test 2: compute_imbalance — boş kitap (edge case)
# ---------------------------------------------------------------------------
def test_compute_imbalance_empty_book():
    """Boş bid veya ask listesi → 0.0, crash yok."""
    assert compute_imbalance([], [], top_n=5) == 0.0
    assert compute_imbalance([[100.0, 5.0]], [], top_n=5) == 1.0
    assert compute_imbalance([], [[100.0, 5.0]], top_n=5) == -1.0


# ---------------------------------------------------------------------------
# Test 3: compute_imbalance — asimetrik derinlikler
# ---------------------------------------------------------------------------
def test_compute_imbalance_asymmetric():
    """Bid ağırlıklı kitap → pozitif imbalance; ask ağırlıklı → negatif."""
    # Bid ağırlıklı: 90 birim bid, 10 birim ask
    bids = [[100.0, 45.0], [99.5, 45.0]]
    asks = [[100.5, 10.0]]
    imb = compute_imbalance(bids, asks, top_n=5)
    # (90 - 10) / (90 + 10) = 80/100 = 0.8
    assert imb == pytest.approx(0.8, abs=1e-9)

    # Ask ağırlıklı: 10 birim bid, 90 birim ask
    bids2 = [[100.0, 10.0]]
    asks2 = [[100.5, 45.0], [101.0, 45.0]]
    imb2 = compute_imbalance(bids2, asks2, top_n=5)
    # (10 - 90) / (10 + 90) = -80/100 = -0.8
    assert imb2 == pytest.approx(-0.8, abs=1e-9)


# ---------------------------------------------------------------------------
# Test 4: compute_imbalance — top_n kırpma
# ---------------------------------------------------------------------------
def test_compute_imbalance_top_n_clipping():
    """top_n=2 → sadece ilk 2 seviye hesaba katılır."""
    # İlk 2 seviye: bid=20, ask=20 → imbalance=0
    # 3. seviye: bid=1000 (dahil edilmemeli)
    bids = [[100.0, 10.0], [99.5, 10.0], [99.0, 1000.0]]
    asks = [[100.5, 10.0], [101.0, 10.0], [101.5, 5.0]]
    result_2 = compute_imbalance(bids, asks, top_n=2)
    assert result_2 == pytest.approx(0.0, abs=1e-9)

    # top_n=3 → 3. seviye dahil: bid=1020, ask=25 → pozitif
    result_3 = compute_imbalance(bids, asks, top_n=3)
    assert result_3 > 0.9  # (1020-25)/(1020+25) ≈ 0.952


# ---------------------------------------------------------------------------
# Test 5: is_imbalance_aligned
# ---------------------------------------------------------------------------
def test_is_imbalance_aligned():
    """Yön + imbalance alignment mantığı."""
    # Long sinyal + bid-heavy (0.7 > 0.6) → True
    assert is_imbalance_aligned(0.7, "long", threshold=0.6) is True

    # Long sinyal + ask-heavy (-0.7) → False
    assert is_imbalance_aligned(-0.7, "long", threshold=0.6) is False

    # Long sinyal + zayıf imbalance (0.3 < 0.6) → False
    assert is_imbalance_aligned(0.3, "long", threshold=0.6) is False

    # Short sinyal + ask-heavy (-0.8) → True
    assert is_imbalance_aligned(-0.8, "short", threshold=0.6) is True

    # Short sinyal + bid-heavy (+0.8) → False
    assert is_imbalance_aligned(0.8, "short", threshold=0.6) is False

    # Eşik tam üzerinde değil (tam eşit = False, çünkü >= eşiği)
    assert is_imbalance_aligned(0.6, "long", threshold=0.6) is True
    assert is_imbalance_aligned(0.59, "long", threshold=0.6) is False


# ---------------------------------------------------------------------------
# Test 6: OrderbookLogger tam akış (sahte exchange, tmp DuckDB)
# ---------------------------------------------------------------------------
def test_orderbook_logger_full_flow(tmp_path: Path):
    """Sahte ccxt exchange ile tam log akışı: fetch → compute → DuckDB → query."""
    # Sahte orderbook verisi
    fake_bids = [[100.0, 50.0], [99.5, 30.0], [99.0, 20.0], [98.5, 10.0], [98.0, 5.0]]
    fake_asks = [[100.5, 10.0], [101.0, 10.0], [101.5, 5.0], [102.0, 5.0], [102.5, 5.0]]

    # Sahte exchange nesnesi
    mock_exchange = MagicMock()
    mock_exchange.fetch_order_book.return_value = {
        "bids": fake_bids,
        "asks": fake_asks,
    }

    db_path = tmp_path / "test_orderbook.duckdb"
    ob_logger = OrderbookLogger(db_path=db_path, top_n_default=5)

    signal_info = {
        "symbol": "BTC/USDT",
        "venue": "binance",
        "direction": "long",
        "bar_ts": "2026-05-09T00:05:00+00:00",
        "pattern_id": "bullish_engulfing",
        "confidence": 0.72,
        "trade_id": "paper-faz6-test123",
    }

    snapshot = ob_logger.log_signal_orderbook(
        signal_info=signal_info,
        exchange=mock_exchange,
        top_n=5,
    )

    # Snapshot döndü (pydantic varsa)
    if snapshot is not None:
        assert snapshot.symbol == "BTC/USDT"
        assert snapshot.direction == "long"
        assert -1.0 <= snapshot.imbalance <= 1.0
        assert snapshot.top_n == 5
        assert snapshot.fetch_latency_ms >= 0.0

        # Beklenen imbalance: bid_vol=115, ask_vol=35 → (115-35)/(115+35) = 80/150 ≈ 0.533
        expected_imb = (115.0 - 35.0) / (115.0 + 35.0)
        assert snapshot.imbalance == pytest.approx(expected_imb, abs=1e-6)

    # DuckDB'de kayıt var mı?
    recent = ob_logger.query_recent(limit=10)
    assert len(recent) == 1
    row = recent[0]
    assert row["symbol"] == "BTC/USDT"
    assert row["direction"] == "long"
    assert row["pattern_id"] == "bullish_engulfing"
    assert abs(row["imbalance"] - (115.0 - 35.0) / (115.0 + 35.0)) < 1e-6

    # Exchange çağrısı yapıldı mı?
    mock_exchange.fetch_order_book.assert_called_once_with("BTC/USDT", limit=20)


# ---------------------------------------------------------------------------
# Test 7 (bonus): fetch_orderbook_snapshot network hatası → None
# ---------------------------------------------------------------------------
def test_fetch_orderbook_snapshot_network_error():
    """Network hatasında None döner, exception fırlatmaz."""
    mock_exchange = MagicMock()
    mock_exchange.fetch_order_book.side_effect = Exception("Connection timeout")

    result = fetch_orderbook_snapshot(
        symbol="ETH/USDT",
        venue="binance",
        limit=10,
        exchange=mock_exchange,
    )
    assert result is None


# ---------------------------------------------------------------------------
# Test 8 (bonus): correlation_summary — boş DB
# ---------------------------------------------------------------------------
def test_correlation_summary_empty(tmp_path: Path):
    """Boş DB'de correlation_summary crash olmamalı, boş/sıfır dict döndürmeli."""
    db_path = tmp_path / "empty_ob.duckdb"
    ob_logger = OrderbookLogger(db_path=db_path)
    summary = ob_logger.correlation_summary()
    # Boş DB'de ya {} ya da sıfır değerler
    assert isinstance(summary, dict)
    if summary:
        assert summary.get("total_snapshots", 0) == 0
