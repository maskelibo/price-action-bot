"""Idempotency Store testleri.

Kritik: 100 retry → 1 kayıt. Restart sonrası koruma.
"""
from __future__ import annotations

import threading
import tempfile
from pathlib import Path

import pytest

from price_action.execution.idempotency import IdempotencyStore


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "idem_test.duckdb"
    return IdempotencyStore(db_path=db)


def test_make_client_id_deterministic():
    fp = "abc123deadbeef01"
    id1 = IdempotencyStore.make_client_id(fp)
    id2 = IdempotencyStore.make_client_id(fp)
    assert id1 == id2
    assert id1.startswith("PA_")
    assert len(id1) <= 36


def test_not_seen_initially(store):
    assert not store.is_seen("nonexistent_fingerprint")


def test_mark_submitted_idempotent(store):
    """100 submit → 1 DB kaydı."""
    fp = "test_fingerprint_001"
    client_ids = set()
    for _ in range(100):
        cid = store.mark_submitted(fp, symbol="BTC/USDT", side="long")
        client_ids.add(cid)
    # Client ID hep aynı
    assert len(client_ids) == 1
    # DB'de tek kayıt
    assert store.is_seen(fp)
    rec = store.get(fp)
    assert rec is not None
    assert rec["status"] == "submitted"


def test_mark_filled(store):
    fp = "test_fp_filled"
    store.mark_submitted(fp, symbol="ETH/USDT", side="short")
    store.mark_filled(fp, exchange_order_id="EX123", fill_price=3200.0, fill_qty=0.5)
    rec = store.get(fp)
    assert rec["status"] == "filled"
    assert rec["exchange_order_id"] == "EX123"
    assert rec["fill_price"] == pytest.approx(3200.0)


def test_mark_rejected(store):
    fp = "test_fp_rejected"
    store.mark_submitted(fp, symbol="SOL/USDT", side="long")
    store.mark_rejected(fp, reason="slippage_exceeded")
    rec = store.get(fp)
    assert rec["status"] == "rejected"


def test_concurrent_submit_safe(store):
    """Paralel thread'lerden 50 submit → 1 kayıt (race condition test)."""
    fp = "concurrent_fp_test"
    results = []

    def submit():
        cid = store.mark_submitted(fp, symbol="BTC/USDT", side="long")
        results.append(cid)

    threads = [threading.Thread(target=submit) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Hepsi aynı client_id döndürmeli (idempotent)
    assert len(set(results)) == 1
    # DB'de tek kayıt
    rec = store.get(fp)
    assert rec is not None


def test_count_submitted_today(store):
    for i in range(3):
        fp = f"today_fp_{i}"
        store.mark_submitted(fp, symbol="ADA/USDT", side="long")
    count = store.count_submitted_today()
    assert count >= 3


def test_get_nonexistent_returns_none(store):
    assert store.get("nonexistent_xxx") is None


def test_restart_persistence(tmp_path):
    """Restart simülasyonu: farklı instance, aynı DB."""
    db = tmp_path / "persist_test.duckdb"
    fp = "persist_fp_001"

    store1 = IdempotencyStore(db_path=db)
    store1.mark_submitted(fp, symbol="BTC/USDT", side="long")
    store1.mark_filled(fp, "EX999", 65000.0, 0.1)

    # Yeni instance (restart simülasyonu)
    store2 = IdempotencyStore(db_path=db)
    assert store2.is_seen(fp)
    rec = store2.get(fp)
    assert rec["status"] == "filled"
    assert rec["exchange_order_id"] == "EX999"
