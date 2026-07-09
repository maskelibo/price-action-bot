"""F4 retry-koruma zinciri — kapanış sprinti 2026-07-10 (DERIN_DENETIM F4 CRIT).

Deferred-retry başarısı KORUMASIZ (SL/TP'siz) + JOURNAL'SIZ pozisyon
bırakıyordu — eski kod yorumu itiraf ediyordu ('journal yazma daemonun işi')
ama daemon timeout dalında fill'den habersizdi. Üstüne: exchange init hayalet
env (PA_BINANCE_*, boş) kullanıyordu ve 'side' long/short'u ccxt'ye ham
geçiyordu — retry yolu fiilen HİÇ uçtan uca çalışmamıştı.

Fix: get_futures_exchange + side haritası + çift-giriş kalkanı
(_check_existing_fill) + _finalize_fill (koruma→journal→idempotency).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.process_pending_entries as ppe  # noqa: E402


class FakeExchange:
    """create_order/fetch_order çağrılarını kaydeden minimal borsa."""

    def __init__(self, existing_orders=None):
        self.orders_created = []
        self.existing = existing_orders or {}  # coid -> order dict
        self.cancelled = []
        self._i = 0

    def amount_to_precision(self, symbol, x):
        return str(x)

    def price_to_precision(self, symbol, x):
        return str(x)

    def create_order(self, symbol, type, side, amount, params):
        self._i += 1
        self.orders_created.append(
            {"symbol": symbol, "type": type, "side": side, "amount": amount, "params": dict(params)}
        )
        return {"id": f"ord{self._i}"}

    def create_market_order(self, symbol, side, amount, params=None):
        self._i += 1
        self.orders_created.append(
            {
                "symbol": symbol,
                "type": "MARKET",
                "side": side,
                "amount": amount,
                "params": dict(params or {}),
            }
        )
        return {"id": f"mkt{self._i}", "filled": amount, "average": 100.0}

    def fetch_order(self, order_id, symbol, params=None):
        coid = (params or {}).get("origClientOrderId")
        if coid is not None:
            if coid in self.existing:
                return self.existing[coid]
            raise Exception("OrderNotFound")
        return {"id": order_id, "filled": 2.0, "average": 100.0}

    def cancel_order(self, order_id, symbol):
        self.cancelled.append(order_id)


def _entry(**over):
    e = {
        "ts": datetime.now(UTC).isoformat(),
        "symbol": "DOGE/USDT",
        "strategy": "vsa_climax_test",
        "side": "short",
        "qty": 2327.0,
        "entry_px": 0.155,
        "sl_price": 0.1638,
        "tp_price": 0.1497,
        "leverage": 1,
        "client_order_id": "PA_abc123",
        "attempts": 1,
        "max_attempts": 2,
    }
    e.update(over)
    return e


def _init_journal(path: Path) -> None:
    import os

    os.environ.setdefault("PA_BOT_NAME", "f4test")
    con = duckdb.connect(str(path))
    con.execute("""CREATE TABLE futures_signals (
        signal_id VARCHAR PRIMARY KEY, ts TIMESTAMP, symbol VARCHAR, strategy VARCHAR,
        side VARCHAR, sl_price DOUBLE, tp_price DOUBLE, confluence DOUBLE,
        leverage INTEGER, status VARCHAR, order_id VARCHAR, fill_price DOUBLE,
        fill_qty DOUBLE, notional_usdt DOUBLE, margin_usdt DOUBLE, notes VARCHAR)""")
    con.execute("""CREATE TABLE futures_protection_orders (
        prot_id VARCHAR PRIMARY KEY, ts TIMESTAMP, signal_id VARCHAR, symbol VARCHAR,
        side VARCHAR, qty DOUBLE, tp_price DOUBLE, sl_price DOUBLE,
        tp_order_id VARCHAR, sl_order_id VARCHAR, status VARCHAR, notes VARCHAR)""")
    con.commit()
    con.close()


def test_finalize_places_protection_with_queue_sl_tp(tmp_path):
    """ÇEKİRDEK: retry-fill sonrası SL (kuyruk sl_price'ında, reduceOnly) + TP kondu."""
    j = tmp_path / "j.duckdb"
    _init_journal(j)
    ex = FakeExchange()
    order = {"id": "mkt1", "filled": 2327.0, "average": 0.1551}
    res = ppe._finalize_fill(_entry(), order, ex, str(j), str(tmp_path / "idem.duckdb"))
    assert res["protection"] == "placed"
    sls = [o for o in ex.orders_created if o["type"] == "STOP_MARKET"]
    tps = [o for o in ex.orders_created if o["type"] == "TAKE_PROFIT_MARKET"]
    assert len(sls) == 1
    assert abs(float(sls[0]["params"]["stopPrice"]) - 0.1638) < 1e-9
    assert sls[0]["params"]["reduceOnly"] is True
    assert sls[0]["side"] == "BUY"  # short pozisyonun SL'i BUY
    assert len(tps) >= 1
    assert abs(sls[0]["amount"] - 2327.0) < 1e-6  # SL tam qty


def test_finalize_inserts_journal_rows(tmp_path):
    j = tmp_path / "j.duckdb"
    _init_journal(j)
    ex = FakeExchange()
    order = {"id": "mkt1", "filled": 2327.0, "average": 0.1551}
    res = ppe._finalize_fill(_entry(), order, ex, str(j), str(tmp_path / "idem.duckdb"))
    assert res["journal"] is True
    con = duckdb.connect(str(j), read_only=True)
    sig = con.execute(
        "SELECT symbol, side, status, notes, fill_qty FROM futures_signals"
    ).fetchone()
    prot = con.execute("SELECT signal_id, status, notes FROM futures_protection_orders").fetchone()
    con.close()
    assert sig == ("DOGE/USDT", "short", "filled", "resolved_by_retry", 2327.0)
    assert prot[0] == res["sig_id"]
    assert prot[1] == "placed"
    assert "resolved_by_retry" in prot[2]


def test_finalize_marks_idempotency(tmp_path):
    from price_action.execution.idempotency import IdempotencyStore

    j = tmp_path / "j.duckdb"
    _init_journal(j)
    idem_db = tmp_path / "idem.duckdb"
    IdempotencyStore(db_path=idem_db)  # şema kur (mark_filled upsert eder)
    ex = FakeExchange()
    order = {"id": "mkt1", "filled": 2327.0, "average": 0.1551}
    res = ppe._finalize_fill(_entry(), order, ex, str(j), str(idem_db))
    assert res["idempotency"] is True


def test_check_existing_fill_returns_prior_fill():
    """Attempt-1'in -1007-sonrası aslında DOLMUŞ emri bulunur → yeni emir YOK."""
    existing = {
        "PA_abc123-r1": {"id": "old1", "status": "closed", "filled": 2327.0, "average": 0.155}
    }
    ex = FakeExchange(existing_orders=existing)
    found = ppe._check_existing_fill(ex, _entry(attempts=1))
    assert found is not None and found["id"] == "old1"
    assert ex.orders_created == []  # yeni emir atılmadı


def test_check_existing_fill_none_when_no_orders():
    ex = FakeExchange()
    assert ppe._check_existing_fill(ex, _entry()) is None


def test_check_existing_open_gets_cancelled():
    existing = {"PA_abc123": {"id": "open1", "status": "open", "filled": 0}}
    ex = FakeExchange(existing_orders=existing)
    found = ppe._check_existing_fill(ex, _entry(attempts=0))
    assert found is None  # açık emir fill değil → cancel + yeni retry yolu
    assert "open1" in ex.cancelled


def test_finalize_journal_failure_does_not_raise(tmp_path):
    """Journal yazılamasa bile raise YOK (koruma zaten kondu) + missed-audit düşer."""
    ex = FakeExchange()
    order = {"id": "mkt1", "filled": 10.0, "average": 1.0}
    res = ppe._finalize_fill(
        _entry(), order, ex, str(tmp_path / "yok" / "j.duckdb"), str(tmp_path / "i.duckdb")
    )
    assert res["journal"] is False
    assert res["protection"] == "placed"  # koruma yine de kondu


def test_side_mapping_and_source_pins():
    assert ppe._SIDE_TO_ORDER["long"] == "buy"
    assert ppe._SIDE_TO_ORDER["short"] == "sell"
    src = (ROOT / "scripts" / "process_pending_entries.py").read_text(encoding="utf-8")
    assert "get_futures_exchange" in src
    assert 'os.environ.get("PA_BINANCE_API_KEY"' not in src  # hayalet env gitti
    daemon_src = (ROOT / "scripts" / "futures_daemon.py").read_text(encoding="utf-8")
    assert '"journal_db": str(JOURNAL)' in daemon_src  # kuyruk kendini-tarifler
