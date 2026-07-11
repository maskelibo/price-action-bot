"""SlippageTracker TF-bucket testleri — SEC31.

Yeni ozellikler:
  - record_fill(..., tf="15m") → TF bucket
  - daily_summary(tf="15m") → TF-spesifik threshold'lar
  - tf_histogram("15m") → histogram/budget raporu

Senaryolar:
  1) test_record_fill_tf_stored         — tf kolonu fills tablosuna yaziliyor
  2) test_daily_summary_tf_filter       — tf filtresi dogru calistiyor
  3) test_tf_budget_thresholds_15m      — 15m: warning=15bps, critical=30bps
  4) test_tf_budget_thresholds_1m       — 1m: warning=10bps, critical=20bps
  5) test_tf_histogram_empty            — bos histogram (no fills)
  6) test_tf_histogram_with_fills       — histogram pct_over_warning dogrulama
  7) test_single_fill_alarm_tf_scaled   — 1m single_max=15bps (15m=22bps)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from price_action.execution.slippage_tracker import (
    TF_SLIPPAGE_BUDGET,
    DeterministicFillConflictError,
    SlippageTracker,
)


def _tracker(tmp_path: Path) -> SlippageTracker:
    db = tmp_path / "test_fills.duckdb"
    return SlippageTracker(db_path=db)


def _fill(
    tracker: SlippageTracker,
    fill_id: str,
    slippage_bps_target: float,
    tf: str = "1d",
    side: str = "long",
    *,
    is_maker: bool = True,
    fill_type: str = "entry",
    fill_role: str | None = None,
    fee_usdt: float | None = 0.08,
    fee_source: str | None = None,
    maker_quantity: float | None = None,
    maker_notional_usdt: float | None = None,
) -> float:
    """Belirli slippage olusturacak sekilde fill kaydet."""
    expected = 1000.0
    if side == "long":
        realized = expected + slippage_bps_target / 10_000 * expected
    else:
        realized = expected - slippage_bps_target / 10_000 * expected

    ts = datetime.now(UTC)
    kwargs = {}
    if fill_role is not None:
        kwargs["fill_role"] = fill_role
    if fee_source is not None:
        kwargs["fee_source"] = fee_source
    if maker_quantity is not None:
        kwargs["maker_quantity"] = maker_quantity
    if maker_notional_usdt is not None:
        kwargs["maker_notional_usdt"] = maker_notional_usdt
    return tracker.record_fill(
        fill_id=fill_id,
        ts=ts,
        symbol="BTC/USDT",
        strategy="test",
        side=side,
        expected_price=expected,
        realized_price=realized,
        quantity=0.01,
        fee_usdt=fee_usdt,
        is_maker=is_maker,
        order_type="limit",
        mode="paper",
        tf=tf,
        fill_type=fill_type,
        **kwargs,
    )


# ===== Testler =====


def test_record_fill_tf_stored(tmp_path):
    """Senaryo 1: tf degeri fills tablosuna yaziliyor."""
    import duckdb

    t = _tracker(tmp_path)
    _fill(t, "f1", slippage_bps_target=5.0, tf="15m")

    con = duckdb.connect(str(tmp_path / "test_fills.duckdb"))
    tf_val = con.execute("SELECT tf FROM fills WHERE fill_id = 'f1'").fetchone()[0]
    con.close()
    assert tf_val == "15m"


def test_record_fill_stores_aware_timestamp_as_utc_naive(tmp_path):
    """Europe/Istanbul-aware input must not be persisted three hours ahead."""
    import duckdb

    t = _tracker(tmp_path)
    local_ts = datetime(2026, 7, 11, 2, 12, tzinfo=timezone(timedelta(hours=3)))
    t.record_fill(
        fill_id="utc_ts",
        ts=local_ts,
        symbol="BTC/USDT",
        strategy="test",
        side="long",
        expected_price=100.0,
        realized_price=100.0,
        quantity=1.0,
        fee_usdt=0.0,
        is_maker=False,
        order_type="market",
        mode="paper",
        tf="15m",
    )
    con = duckdb.connect(str(tmp_path / "test_fills.duckdb"))
    stored = con.execute("SELECT ts FROM fills WHERE fill_id='utc_ts'").fetchone()[0]
    con.close()
    assert stored == datetime(2026, 7, 10, 23, 12)


def test_record_fill_default_tf_is_1d(tmp_path):
    """Default tf '1d' olarak kaydedilmeli."""
    import duckdb

    t = _tracker(tmp_path)
    # tf vermeden cagir
    ts = datetime.now(UTC)
    t.record_fill(
        fill_id="f_default",
        ts=ts,
        symbol="ETH/USDT",
        strategy="test",
        side="long",
        expected_price=2000.0,
        realized_price=2002.0,
        quantity=0.1,
        fee_usdt=0.16,
        is_maker=False,
        order_type="market",
        mode="paper",
    )
    con = duckdb.connect(str(tmp_path / "test_fills.duckdb"))
    tf_val = con.execute("SELECT tf FROM fills WHERE fill_id = 'f_default'").fetchone()[0]
    con.close()
    assert tf_val == "1d"


def test_daily_summary_tf_filter(tmp_path):
    """Senaryo 2: tf filtresi ile sadece ilgili tf fill'leri sayiliyor."""
    t = _tracker(tmp_path)
    _fill(t, "a1", slippage_bps_target=5.0, tf="15m")
    _fill(t, "a2", slippage_bps_target=5.0, tf="15m")
    _fill(t, "a3", slippage_bps_target=8.0, tf="1m")

    summary_15m = t.daily_summary(tf="15m")
    summary_1m = t.daily_summary(tf="1m")

    assert summary_15m["n_fills"] == 2
    assert summary_1m["n_fills"] == 1
    assert summary_15m["tf"] == "15m"
    assert summary_1m["tf"] == "1m"


def test_tf_budget_thresholds_15m(tmp_path):
    """Senaryo 3: 15m budget — warning=15bps, critical=30bps."""
    budget = TF_SLIPPAGE_BUDGET["15m"]
    assert budget["warning"] == pytest.approx(15.0)
    assert budget["critical"] == pytest.approx(30.0)
    assert budget["single_max"] == pytest.approx(22.0)


def test_tf_budget_thresholds_1m(tmp_path):
    """Senaryo 4: 1m budget — warning=10bps, critical=20bps."""
    budget = TF_SLIPPAGE_BUDGET["1m"]
    assert budget["warning"] == pytest.approx(10.0)
    assert budget["critical"] == pytest.approx(20.0)
    assert budget["single_max"] == pytest.approx(15.0)


def test_tf_budget_thresholds_5m():
    """5m budget — warning=12bps, critical=24bps."""
    budget = TF_SLIPPAGE_BUDGET["5m"]
    assert budget["warning"] == pytest.approx(12.0)
    assert budget["critical"] == pytest.approx(24.0)


def test_tf_histogram_empty(tmp_path):
    """Senaryo 5: bos histogram (fill yok)."""
    t = _tracker(tmp_path)
    hist = t.tf_histogram("1m")

    assert hist["tf"] == "1m"
    assert hist["n_fills"] == 0
    assert hist["mean_bps"] == pytest.approx(0.0)
    assert hist["budget_warning_bps"] == pytest.approx(10.0)
    assert hist["budget_critical_bps"] == pytest.approx(20.0)


def test_tf_histogram_with_fills(tmp_path):
    """Senaryo 6: histogram pct_over_warning dogrulama."""
    t = _tracker(tmp_path)
    # 3 fill: 5bps, 12bps, 25bps (15m budget warning=15, critical=30)
    _fill(t, "h1", 5.0, tf="15m")
    _fill(t, "h2", 12.0, tf="15m")
    _fill(t, "h3", 25.0, tf="15m")

    hist = t.tf_histogram("15m")

    assert hist["n_fills"] == 3
    assert hist["mean_bps"] == pytest.approx((5 + 12 + 25) / 3, abs=0.5)
    # 1/3 over warning (15bps): 25bps
    assert hist["pct_over_warning"] == pytest.approx(33.3, abs=1.0)
    # 0/3 over critical (30bps)
    assert hist["pct_over_critical"] == pytest.approx(0.0, abs=0.1)
    assert hist["budget_warning_bps"] == pytest.approx(15.0)


def test_alarm_fires_on_tf_critical(tmp_path, capsys):
    """daily_summary TF-threshold ile alarm tetikleniyor mu?"""
    t = _tracker(tmp_path)
    # 1m critical = 20bps, 25bps fill ekle
    _fill(t, "alarm1", 25.0, tf="1m")

    summary = t.daily_summary(tf="1m")
    # 25bps > 20bps → CRITICAL
    assert summary["alarm_level"] == "CRITICAL"
    assert summary["alarm_triggered"] is True


# ── G14 fix: fill_type parametresi + notes alanı ─────────────────────────────


def test_fill_type_stored_in_notes(tmp_path):
    """G14 fix (hard review 2026-05-21): fill_type=entry/tp/sl notes alanına yazılır.

    Batch D daemon çağrısı: entry fill → fill_type='entry',
    TP fill → fill_type='tp', SL fill → fill_type='sl'.
    notes kolonu 'fill_type=<type>' prefix ile başlar.
    """
    import duckdb

    t = _tracker(tmp_path)
    ts = datetime.now(UTC)

    t.record_fill(
        fill_id="ft_entry",
        ts=ts,
        symbol="BTC/USDT",
        strategy="engulfing",
        side="long",
        expected_price=1000.0,
        realized_price=1001.0,
        quantity=0.01,
        fee_usdt=0.08,
        is_maker=False,
        order_type="market",
        mode="paper",
        tf="15m",
        fill_type="entry",
    )
    t.record_fill(
        fill_id="ft_tp",
        ts=ts,
        symbol="BTC/USDT",
        strategy="engulfing",
        side="long",
        expected_price=1020.0,
        realized_price=1019.5,
        quantity=0.005,
        fee_usdt=0.04,
        is_maker=True,
        order_type="limit",
        mode="paper",
        tf="15m",
        fill_type="tp",
    )
    t.record_fill(
        fill_id="ft_sl",
        ts=ts,
        symbol="BTC/USDT",
        strategy="engulfing",
        side="long",
        expected_price=980.0,
        realized_price=979.0,
        quantity=0.005,
        fee_usdt=0.04,
        is_maker=False,
        order_type="stop_market",
        mode="paper",
        tf="15m",
        fill_type="sl",
    )

    con = duckdb.connect(str(tmp_path / "test_fills.duckdb"))
    rows = {
        row[0]: row[1]
        for row in con.execute("SELECT fill_id, notes FROM fills ORDER BY fill_id").fetchall()
    }
    con.close()

    assert rows["ft_entry"].startswith("fill_type=entry"), f"entry notes: {rows['ft_entry']}"
    assert rows["ft_tp"].startswith("fill_type=tp"), f"tp notes: {rows['ft_tp']}"
    assert rows["ft_sl"].startswith("fill_type=sl"), f"sl notes: {rows['ft_sl']}"


def test_fill_type_default_is_entry(tmp_path):
    """fill_type verilmezse default 'entry' notes'a yazılır (backward compat)."""
    import duckdb

    t = _tracker(tmp_path)
    ts = datetime.now(UTC)
    t.record_fill(
        fill_id="ft_default",
        ts=ts,
        symbol="ETH/USDT",
        strategy="test",
        side="short",
        expected_price=500.0,
        realized_price=499.5,
        quantity=0.1,
        fee_usdt=0.02,
        is_maker=False,
        order_type="market",
        mode="paper",
        # fill_type yok → default "entry"
    )
    con = duckdb.connect(str(tmp_path / "test_fills.duckdb"))
    notes = con.execute("SELECT notes FROM fills WHERE fill_id='ft_default'").fetchone()[0]
    con.close()
    assert notes == "fill_type=entry", f"default notes: {notes}"


def test_fill_type_with_existing_notes(tmp_path):
    """fill_type + mevcut notes → 'fill_type=X <eski_notes>' formatı."""
    import duckdb

    t = _tracker(tmp_path)
    ts = datetime.now(UTC)
    t.record_fill(
        fill_id="ft_combined",
        ts=ts,
        symbol="SOL/USDT",
        strategy="pin_bar",
        side="long",
        expected_price=50.0,
        realized_price=50.05,
        quantity=1.0,
        fee_usdt=0.02,
        is_maker=False,
        order_type="market",
        mode="paper",
        tf="15m",
        fill_type="pyramid",
        notes="leg=2 trigger=1.0R",
    )
    con = duckdb.connect(str(tmp_path / "test_fills.duckdb"))
    notes = con.execute("SELECT notes FROM fills WHERE fill_id='ft_combined'").fetchone()[0]
    con.close()
    assert notes.startswith("fill_type=pyramid"), f"notes: {notes}"
    assert "leg=2" in notes, f"existing notes lost: {notes}"


def test_init_db_idempotent_on_record_fill(tmp_path):
    """G14 fix: record_fill her çağrıda _init_db çağırır → tablo garantisi.

    Senaryo: DB başka bir yerden açılmış, fills tablosu yok.
    SlippageTracker başlatılmadan (init atlanmış gibi) direkt record_fill
    çağrılsa bile tablo oluşur. (Test: _init_db doğrudan çağrılabilir idempotent.)
    """
    t = _tracker(tmp_path)
    # Mevcut tabloyu sil (en kötü senaryo simülasyonu)
    import duckdb

    con = duckdb.connect(str(tmp_path / "test_fills.duckdb"))
    con.execute("DROP TABLE IF EXISTS fills")
    con.commit()
    con.close()

    # record_fill → _init_db → fills tablosu yeniden yaratılır
    ts = datetime.now(UTC)
    slip = t.record_fill(
        fill_id="rebuild_test",
        ts=ts,
        symbol="ADA/USDT",
        strategy="test",
        side="long",
        expected_price=0.5,
        realized_price=0.5005,
        quantity=100.0,
        fee_usdt=0.01,
        is_maker=False,
        order_type="market",
        mode="paper",
        tf="15m",
        fill_type="entry",
    )
    assert slip >= 0.0  # slippage hesaplandı (tablo rebuild oldu)

    con2 = duckdb.connect(str(tmp_path / "test_fills.duckdb"))
    cnt = con2.execute("SELECT COUNT(*) FROM fills WHERE fill_id='rebuild_test'").fetchone()[0]
    con2.close()
    assert cnt == 1, f"rebuild sonrası satır yok (cnt={cnt})"


# ── Maker KPI role ayrımı + geriye uyumlu migration ──────────────────────────


def test_daily_maker_kpi_is_entry_only_and_invalid_role_fails_closed(tmp_path):
    """Exit/unknown fill maker KPI paydasına giremez.

    Eski hata şekli: iki taker entry + maker diye işaretlenmiş bir protection
    fill, global oranı %33.3 gösteriyordu. Entry-only gerçek oran %0'dır.
    """
    t = _tracker(tmp_path)
    _fill(t, "entry_1", 2.0, tf="15m", is_maker=False, fill_role="entry")
    _fill(t, "entry_2", 3.0, tf="15m", is_maker=False, fill_role="entry")
    _fill(
        t,
        "exit_1",
        4.0,
        tf="15m",
        is_maker=True,
        fill_type="sl",
        fill_role="exit",
    )
    _fill(
        t,
        "unknown_1",
        5.0,
        tf="15m",
        is_maker=True,
        fill_role="not-a-real-role",
    )

    summary = t.daily_summary(tf="15m")
    assert summary["n_fills"] == 4
    assert summary["entry_fill_count"] == 2
    assert summary["exit_fill_count"] == 1
    assert summary["unknown_fill_count"] == 1
    assert summary["maker_fill_pct"] == 0.0
    assert summary["entry_maker_fill_pct"] == 0.0


def test_legacy_fill_schema_migration_backfills_only_unambiguous_roles(tmp_path):
    """Eski DB açılışı güvenli: notes kanıtı olanlar ayrılır, belirsiz satır UNKNOWN kalır."""
    import duckdb

    db = tmp_path / "legacy_fills.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        """
        CREATE TABLE fills (
            fill_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP NOT NULL,
            symbol VARCHAR,
            strategy VARCHAR,
            side VARCHAR,
            tf VARCHAR DEFAULT '1d',
            expected_price DOUBLE,
            realized_price DOUBLE,
            quantity DOUBLE,
            notional_usdt DOUBLE,
            slippage_bps DOUBLE,
            fee_usdt DOUBLE,
            fee_bps DOUBLE,
            total_cost_bps DOUBLE,
            is_maker BOOLEAN,
            order_type VARCHAR,
            mode VARCHAR,
            exchange_order_id VARCHAR,
            client_order_id VARCHAR,
            notes VARCHAR
        )
        """
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    con.executemany(
        """INSERT INTO fills
           (fill_id, ts, tf, slippage_bps, fee_usdt, is_maker, notes)
           VALUES (?, ?, '15m', 1.0, 0.1, ?, ?)""",
        [
            ("legacy_entry", now, False, "fill_type=entry"),
            ("legacy_exit", now, True, "fill_type=sl"),
            ("legacy_ambiguous", now, True, None),
        ],
    )
    con.close()

    t = SlippageTracker(db_path=db)
    con = duckdb.connect(str(db))
    roles = dict(con.execute("SELECT fill_id, fill_role FROM fills").fetchall())
    columns = {row[0] for row in con.execute("DESCRIBE fills").fetchall()}
    con.close()

    assert {"fill_role", "fee_source", "maker_quantity", "maker_notional_usdt"} <= columns
    assert roles == {
        "legacy_entry": "entry",
        "legacy_exit": "exit",
        "legacy_ambiguous": "unknown",
    }
    summary = t.daily_summary(d=datetime.now(UTC).date(), tf="15m")
    assert summary["maker_fill_pct"] == 0.0
    assert summary["entry_fill_count"] == 1
    assert summary["exit_fill_count"] == 1
    assert summary["unknown_fill_count"] == 1


def test_entry_maker_qty_and_notional_kpis_preserve_mixed_fallback_leg(tmp_path):
    """Binary taker order içindeki kısmi maker leg ağırlıklı KPI'da kaybolmaz."""
    t = _tracker(tmp_path)
    total_qty = 3845.0
    maker_qty = 538.0
    maker_notional = 104.14604  # oid=543048866 userTrades quote toplamı
    taker_notional = 642.31906  # oid=543051193 userTrades quote toplamı
    total_notional = maker_notional + taker_notional
    realized = total_notional / total_qty

    t.record_fill(
        fill_id="mixed_entry_xlm",
        ts=datetime.now(UTC),
        symbol="XLM/USDT",
        strategy="vsa",
        side="long",
        expected_price=realized,
        realized_price=realized,
        quantity=total_qty,
        fee_usdt=0.02082915 + 0.2569276,
        is_maker=False,  # order bütünü binary olarak maker değil
        order_type="mixed_limit_market",
        mode="paper",
        tf="15m",
        fill_type="entry",
        fill_role="entry",
        fee_source="exchange_user_trades",
        maker_quantity=maker_qty,
        maker_notional_usdt=maker_notional,
    )

    summary = t.daily_summary(tf="15m")
    assert summary["maker_fill_pct"] == 0.0
    assert summary["entry_maker_order_pct"] == 0.0
    assert summary["entry_maker_qty_pct"] == 14.0
    assert summary["entry_maker_notional_pct"] == 14.0


def test_unknown_commission_stays_null_and_summary_marks_incomplete(tmp_path):
    """Borsa komisyonu bulunamazsa 4/8bps tahmini gerçekmiş gibi yazılmaz."""
    import duckdb

    t = _tracker(tmp_path)
    _fill(
        t,
        "exit_fee_unknown",
        4.0,
        tf="15m",
        is_maker=False,
        fill_type="sl",
        fill_role="exit",
        fee_usdt=None,
        fee_source="unavailable",
    )

    con = duckdb.connect(str(tmp_path / "test_fills.duckdb"))
    fee_usdt, fee_bps, total_cost_bps, fee_source = con.execute(
        """SELECT fee_usdt, fee_bps, total_cost_bps, fee_source
           FROM fills WHERE fill_id='exit_fee_unknown'"""
    ).fetchone()
    con.close()
    assert fee_usdt is None
    assert fee_bps is None
    assert total_cost_bps is None
    assert fee_source == "unavailable"

    summary = t.daily_summary(tf="15m")
    assert summary["fee_known_fill_count"] == 0
    assert summary["fee_unknown_fill_count"] == 1
    assert summary["total_fee_complete"] is False


def test_deterministic_fill_exact_replay_is_noop(tmp_path, monkeypatch):
    tracker = _tracker(tmp_path)
    jsonl_writes = []
    monkeypatch.setattr(
        tracker,
        "_write_jsonl",
        lambda *args, **kwargs: jsonl_writes.append((args, kwargs)),
    )
    kwargs = {
        "fill_id": "stable-exit-1",
        "ts": datetime(2026, 7, 11, tzinfo=UTC),
        "symbol": "BTC/USDT",
        "strategy": "vsa_tp1",
        "side": "long",
        "expected_price": 100.0,
        "realized_price": 100.05,
        "quantity": 0.25,
        "fee_usdt": 0.01,
        "is_maker": False,
        "order_type": "algo_take_profit_market",
        "mode": "paper",
        "exchange_order_id": "777",
        "fill_type": "tp1",
        "fill_role": "exit",
        "fee_source": "exchange_user_trades",
        "tf": "15m",
    }
    first = tracker.record_fill(**kwargs, notes="first writer")
    second = tracker.record_fill(
        **{**kwargs, "ts": datetime(2026, 7, 11, 0, 1, tzinfo=UTC)},
        notes="replay writer may use different audit notes",
    )

    assert second == pytest.approx(first)
    assert len(jsonl_writes) == 1


def test_deterministic_fill_rounding_dust_is_tolerated_but_payload_drift_raises(
    tmp_path, caplog
):
    tracker = _tracker(tmp_path)
    kwargs = {
        "fill_id": "stable-entry-1",
        "ts": datetime(2026, 7, 11, tzinfo=UTC),
        "symbol": "BTC/USDT",
        "strategy": "vsa",
        "side": "long",
        "expected_price": 100.0,
        "realized_price": 100.0,
        "quantity": 1.0,
        "fee_usdt": None,
        "is_maker": False,
        "order_type": "market",
        "mode": "paper",
        "fill_type": "entry",
        "fill_role": "entry",
        "fee_source": "unavailable",
        "tf": "15m",
    }
    tracker.record_fill(**kwargs)
    tracker.record_fill(**{**kwargs, "quantity": 1.0 + 5e-9})

    with caplog.at_level("CRITICAL"), pytest.raises(
        DeterministicFillConflictError, match="payload mismatch"
    ):
        tracker.record_fill(**{**kwargs, "quantity": 1.01})
    assert "deterministic_fill_conflict" in caplog.text
