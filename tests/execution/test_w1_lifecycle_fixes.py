"""W1 daemon yaşam-döngüsü paketi — dalga-3 denetim fix'leri (2026-07-08).

Kapsam (DERIN_DENETIM_2026-07-07 §W1, "yarın-1" paketi):
  S1) Watchdog SL cancel-replace → journal futures_protection_orders.sl_order_id
      GÜNCELLENMELİ (eski bug: ilk trail'den sonra heal/orphan bayat ID'ye bakar).
  S2) Journal self-heal false-close: 2 bayat tick yetmez → HEAL_CONFIRM_TICKS=3
      ardışık tick teyidi (orphan-cancel deseniyle aynı disiplin).
  S3) Runner time-stop çıpası TRADE-scoped: yalnız aynı sembol+yönün EN YENİ
      'filled' sinyalinin TP1 partial'ı çıpa olabilir (zombi sinyal çıpası
      yeni kazananı kapattıramaz).
  S4) Koruma satırı çok-atış: futures_protection_orders yalnız pozisyon
      borsada FLAT iken 'filled'e çekilir (TP1 partial satırı öldürmez —
      final kapanışı heal değil daemon yazar).
  S5) DMS flatten: -2022 reduceOnly reddi → taze qty ile plain-market fallback;
      flatten başarısızsa tek-atış DEĞİL → sonraki watchdog tick'te retry
      (FLATTEN_MAX_ATTEMPTS tavanlı).

S1/S3/S4 gerçek daemon fonksiyonlarını import edip test eder (modül import'u
yan-etkisiz, ~0.05s). S2 repo geleneğiyle logic-mirror + source-pin.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import duckdb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.futures_daemon as fd  # noqa: E402

from price_action.execution.dead_mans_switch import DeadMansSwitch  # noqa: E402

_DAEMON_SRC = (ROOT / "scripts" / "futures_daemon.py").read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────────────────────────────────────


def _make_prot_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE futures_protection_orders (
            prot_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            signal_id VARCHAR,
            symbol VARCHAR,
            side VARCHAR,
            qty DOUBLE,
            tp_price DOUBLE,
            sl_price DOUBLE,
            tp_order_id VARCHAR,
            sl_order_id VARCHAR,
            status VARCHAR,
            notes VARCHAR
        )
    """)


def _insert_prot(con, prot_id, symbol, side, sl_oid, status) -> None:
    con.execute(
        "INSERT INTO futures_protection_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            prot_id,
            datetime.now(UTC),
            f"sig_{prot_id}",
            symbol,
            side,
            1.0,
            110.0,
            90.0,
            f"tp_{prot_id}",
            sl_oid,
            status,
            None,
        ),
    )


def _naive_utc(dt: datetime) -> datetime:
    """Journal konvansiyonu (TradeJournal._strip_tz): naive-UTC olarak sakla.

    Aware datetime'ı doğrudan bind etmek DuckDB'de LOKAL duvar saatine
    çevrilir (test artefaktı) — üretim yolu her zaman naive-UTC yazar.
    """
    return dt.astimezone(UTC).replace(tzinfo=None)


def _make_timestop_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE futures_signals (
            signal_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            symbol VARCHAR,
            side VARCHAR,
            status VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE futures_partial_closes (
            close_id VARCHAR PRIMARY KEY,
            trade_id VARCHAR,
            ts_close TIMESTAMP,
            close_reason VARCHAR
        )
    """)
    con.execute("CREATE TABLE futures_trades_closed (trade_id VARCHAR PRIMARY KEY)")


# ═════════════════════════════════════════════════════════════════════════════
# S1 — Watchdog SL cancel-replace → journal sl_order_id senkronu
# ═════════════════════════════════════════════════════════════════════════════


class TestWatchdogSlOrderIdSync:
    def _tmp_journal(self, tmp_path, monkeypatch) -> Path:
        db = tmp_path / "journal_s1.duckdb"
        con = duckdb.connect(str(db))
        _make_prot_table(con)
        con.commit()
        con.close()
        monkeypatch.setattr(fd, "JOURNAL", db)
        return db

    def test_updates_only_placed_row_of_symbol_side(self, tmp_path, monkeypatch):
        db = self._tmp_journal(tmp_path, monkeypatch)
        con = duckdb.connect(str(db))
        _insert_prot(con, "p_old", "ZEC/USDT", "short", "OLD_RETIRED", "filled")
        _insert_prot(con, "p_cur", "ZEC/USDT", "short", "ENTRY_SL_ID", "placed")
        _insert_prot(con, "p_oth", "SOL/USDT", "long", "SOL_SL_ID", "placed")
        con.commit()
        con.close()

        fd._update_journal_sl_order_id("ZEC/USDT", "short", "FRESH_SL_ID")

        con = duckdb.connect(str(db), read_only=True)
        rows = dict(
            con.execute("SELECT prot_id, sl_order_id FROM futures_protection_orders").fetchall()
        )
        con.close()
        assert rows["p_cur"] == "FRESH_SL_ID"  # placed satır güncellendi
        assert rows["p_old"] == "OLD_RETIRED"  # emekli satıra dokunulmadı
        assert rows["p_oth"] == "SOL_SL_ID"  # başka sembol dokunulmadı

    def test_side_is_case_insensitive(self, tmp_path, monkeypatch):
        db = self._tmp_journal(tmp_path, monkeypatch)
        con = duckdb.connect(str(db))
        _insert_prot(con, "p1", "AAVE/USDT", "SHORT", "OLD_ID", "placed")
        con.commit()
        con.close()

        fd._update_journal_sl_order_id("AAVE/USDT", "short", "NEW_ID")

        con = duckdb.connect(str(db), read_only=True)
        got = con.execute(
            "SELECT sl_order_id FROM futures_protection_orders WHERE prot_id='p1'"
        ).fetchone()[0]
        con.close()
        assert got == "NEW_ID"

    def test_empty_or_none_id_is_noop(self, tmp_path, monkeypatch):
        db = self._tmp_journal(tmp_path, monkeypatch)
        con = duckdb.connect(str(db))
        _insert_prot(con, "p1", "SOL/USDT", "long", "KEEP_ME", "placed")
        con.commit()
        con.close()

        fd._update_journal_sl_order_id("SOL/USDT", "long", "")
        fd._update_journal_sl_order_id("SOL/USDT", "long", None)

        con = duckdb.connect(str(db), read_only=True)
        got = con.execute(
            "SELECT sl_order_id FROM futures_protection_orders WHERE prot_id='p1'"
        ).fetchone()[0]
        con.close()
        assert got == "KEEP_ME"

    def test_db_error_does_not_raise(self, tmp_path, monkeypatch):
        """Watchdog tick'i journal hatasıyla ÖLMEMELİ (log + devam)."""
        monkeypatch.setattr(fd, "JOURNAL", tmp_path / "yok" / "boyle" / "db.duckdb")
        fd._update_journal_sl_order_id("ZEC/USDT", "short", "X")  # raise etmemeli

    def test_daemon_source_wires_all_three_replace_sites(self):
        """def + 3 çağrı (missing-SL kondu / qty-fix / ratchet taşındı)."""
        assert _DAEMON_SRC.count("_update_journal_sl_order_id(") >= 4


# ═════════════════════════════════════════════════════════════════════════════
# S2 — Heal N-tick teyit (2 bayat tick yetmez)
# ═════════════════════════════════════════════════════════════════════════════


class TestHealNTickConfirm:
    """Heal streak semantiği (daemon logic mirror — orphan deseniyle aynı)."""

    CONFIRM_TICKS = 3

    def _tick(self, ticks: dict, sid: str, looks_gone: bool) -> bool:
        """Tek heal tick simülasyonu. True dönerse kayıt 'closed' yapılır."""
        if not looks_gone:
            ticks.pop(sid, None)
            return False
        streak = ticks.get(sid, 0) + 1
        ticks[sid] = streak
        if streak < self.CONFIRM_TICKS:
            return False
        ticks.pop(sid, None)
        return True

    def test_two_stale_ticks_do_not_heal(self):
        """ESKİ bug: 2. tick'te heal ederdi → gerçek kapanış idempotency'ye
        takılır + SL orphan-iptal → çıplak kaskad."""
        ticks: dict = {}
        assert self._tick(ticks, "sig1", True) is False  # 1/3
        assert self._tick(ticks, "sig1", True) is False  # 2/3 (eski kod burada heal ederdi)

    def test_three_consecutive_ticks_heal(self):
        ticks: dict = {}
        self._tick(ticks, "sig1", True)
        self._tick(ticks, "sig1", True)
        assert self._tick(ticks, "sig1", True) is True  # 3/3
        assert "sig1" not in ticks

    def test_position_reappearing_resets_streak(self):
        ticks: dict = {}
        self._tick(ticks, "sig1", True)
        self._tick(ticks, "sig1", True)
        self._tick(ticks, "sig1", False)  # pozisyon/SL göründü → reset
        assert "sig1" not in ticks
        assert self._tick(ticks, "sig1", True) is False  # tekrar 1/3

    def test_daemon_source_has_heal_ntick(self):
        assert "HEAL_CONFIRM_TICKS = 3" in _DAEMON_SRC
        assert "JOURNAL_HEAL_PENDING" in _DAEMON_SRC
        # Aktif protection terminal eventleri kesin fill kaniti ile replay edilir;
        # legacy self-heal bu hatti sentetik reconcile_orphan ile preempt edemez.
        assert "AND NOT EXISTS (" in _DAEMON_SRC
        assert "AND ap.status = 'placed'" in _DAEMON_SRC
        # eski hard-coded eşik kalmamalı
        assert "if _streak < 2:" not in _DAEMON_SRC


# ═════════════════════════════════════════════════════════════════════════════
# S3 — Runner time-stop çıpası trade-scoped
# ═════════════════════════════════════════════════════════════════════════════


class TestRunnerTimestopTradeScope:
    SYM = "ZEC/USDT"

    def _con(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(":memory:")
        _make_timestop_tables(con)
        return con

    def test_zombie_signal_anchor_ignored(self):
        """Zombi 'filled' sinyalin eski TP1'i YENİ trade'e çıpa OLAMAZ.

        Eski bug: sembol+yön eşleşen EN ESKİ partial seçilirdi → 40 bar önceki
        zombi çıpası yeni +1R kazananı anında kapattırırdı.
        """
        con = self._con()
        t_old = datetime.now(UTC) - timedelta(hours=12)
        t_new = datetime.now(UTC) - timedelta(minutes=30)
        # Zombi: eski filled sinyal + eski TP1 partial (trades_closed'da YOK)
        con.execute(
            "INSERT INTO futures_signals VALUES ('sig_zombie', ?, ?, 'short', 'filled')",
            [_naive_utc(t_old), self.SYM],
        )
        con.execute(
            "INSERT INTO futures_partial_closes VALUES ('pc_zombie', 'sig_zombie', ?, 'tp1')",
            [_naive_utc(t_old + timedelta(minutes=15))],
        )
        # Güncel trade: yeni filled sinyal, HENÜZ TP1 partial'ı yok
        con.execute(
            "INSERT INTO futures_signals VALUES ('sig_new', ?, ?, 'short', 'filled')",
            [_naive_utc(t_new), self.SYM],
        )

        anchor = fd._runner_timestop_anchor_ts(con, self.SYM, "short")
        assert anchor is None  # yeni trade'in çıpası yok → timestop ATEŞLEMEZ

    def test_current_trade_own_anchor_returned(self):
        con = self._con()
        t_new = datetime.now(UTC) - timedelta(hours=2)
        t_tp1 = t_new + timedelta(minutes=45)
        con.execute(
            "INSERT INTO futures_signals VALUES ('sig_new', ?, ?, 'long', 'filled')",
            [_naive_utc(t_new), self.SYM],
        )
        con.execute(
            "INSERT INTO futures_partial_closes VALUES ('pc_new', 'sig_new', ?, 'tp1')",
            [_naive_utc(t_tp1)],
        )

        anchor = fd._runner_timestop_anchor_ts(con, self.SYM, "long")
        assert anchor is not None
        _a = anchor.replace(tzinfo=UTC) if anchor.tzinfo is None else anchor
        assert abs((_a - t_tp1).total_seconds()) < 2

    def test_zombie_present_but_current_trade_anchor_wins(self):
        """Zombi + güncel trade'in KENDİ TP1'i varken çıpa güncel olanınki."""
        con = self._con()
        t_old = datetime.now(UTC) - timedelta(hours=12)
        t_new = datetime.now(UTC) - timedelta(hours=1)
        t_tp1_new = t_new + timedelta(minutes=15)
        con.execute(
            "INSERT INTO futures_signals VALUES ('sig_zombie', ?, ?, 'short', 'filled')",
            [_naive_utc(t_old), self.SYM],
        )
        con.execute(
            "INSERT INTO futures_partial_closes VALUES ('pc_zombie', 'sig_zombie', ?, 'tp1')",
            [_naive_utc(t_old + timedelta(minutes=15))],
        )
        con.execute(
            "INSERT INTO futures_signals VALUES ('sig_new', ?, ?, 'short', 'filled')",
            [_naive_utc(t_new), self.SYM],
        )
        con.execute(
            "INSERT INTO futures_partial_closes VALUES ('pc_new', 'sig_new', ?, 'tp1')",
            [_naive_utc(t_tp1_new)],
        )

        anchor = fd._runner_timestop_anchor_ts(con, self.SYM, "short")
        assert anchor is not None
        _a = anchor.replace(tzinfo=UTC) if anchor.tzinfo is None else anchor
        assert abs((_a - t_tp1_new).total_seconds()) < 2

    def test_closed_trade_not_anchor(self):
        """trades_closed'daki sinyal çıpa olamaz (mevcut davranış korunur)."""
        con = self._con()
        t = datetime.now(UTC) - timedelta(hours=3)
        con.execute(
            "INSERT INTO futures_signals VALUES ('sig_done', ?, ?, 'long', 'filled')",
            [_naive_utc(t), self.SYM],
        )
        con.execute(
            "INSERT INTO futures_partial_closes VALUES ('pc_done', 'sig_done', ?, 'tp1')",
            [_naive_utc(t + timedelta(minutes=15))],
        )
        con.execute("INSERT INTO futures_trades_closed VALUES ('sig_done')")

        assert fd._runner_timestop_anchor_ts(con, self.SYM, "long") is None

    def test_side_mismatch_no_anchor(self):
        con = self._con()
        t = datetime.now(UTC) - timedelta(hours=2)
        con.execute(
            "INSERT INTO futures_signals VALUES ('sig_l', ?, ?, 'long', 'filled')",
            [_naive_utc(t), self.SYM],
        )
        con.execute(
            "INSERT INTO futures_partial_closes VALUES ('pc_l', 'sig_l', ?, 'tp1')",
            [_naive_utc(t + timedelta(minutes=15))],
        )

        assert fd._runner_timestop_anchor_ts(con, self.SYM, "short") is None

    def test_daemon_source_uses_scoped_helper(self):
        assert _DAEMON_SRC.count("_runner_timestop_anchor_ts(") >= 2  # def + çağrı


# ═════════════════════════════════════════════════════════════════════════════
# S4 — Koruma satırı çok-atış (partial'da 'placed' kalır)
# ═════════════════════════════════════════════════════════════════════════════


class TestProtectionRowMultiShot:
    def test_partial_keeps_row_alive(self):
        """TP1 partial (borsada qty kaldı) satırı EMEKLİ EDEMEZ — eski bug."""
        assert fd._should_retire_protection(True, 5.0) is False

    def test_full_close_retires_row(self):
        assert fd._should_retire_protection(True, 0.0) is True

    def test_dust_qty_counts_as_flat(self):
        assert fd._should_retire_protection(True, 1e-9) is True

    def test_no_terminal_event_never_retires(self):
        assert fd._should_retire_protection(False, 0.0) is False

    def test_daemon_source_guards_retirement(self):
        # Durable gate: def + production call; evidence/journal helper is wired.
        assert _DAEMON_SRC.count("_protection_retirement_ready(") >= 2
        assert _DAEMON_SRC.count("_process_protection_terminal_event(") >= 2
        assert "PROT_RETIRE_HELD" in _DAEMON_SRC


# ═════════════════════════════════════════════════════════════════════════════
# S5 — DMS flatten: -2022 fallback + retry
# ═════════════════════════════════════════════════════════════════════════════


def _mk_dms(tmp_path, mock_ex, **kw) -> DeadMansSwitch:
    return DeadMansSwitch(
        mock_ex,
        service_name="w1test",
        db_path=tmp_path / "dms_w1.duckdb",
        heartbeat_file=tmp_path / "hb_w1.txt",
        timeout_sec=kw.pop("timeout_sec", 5),
        **kw,
    )


class TestDMSFlattenHardened:
    def test_reduceonly_rejected_falls_back_to_plain_market(self, tmp_path, monkeypatch):
        """-2022 senaryosu: reduceOnly reddedilir → taze qty plain-market."""
        import price_action.execution.dead_mans_switch as dms_mod

        monkeypatch.setattr(dms_mod, "KILL_SWITCH_PATH", tmp_path / "ks.json")

        pos = {"symbol": "ZEC/USDT:USDT", "contracts": 1.05, "side": "short"}
        mock_ex = MagicMock()
        # 1. fetch: flatten listesi; 2. fetch: fallback taze qty; 3. fetch: doğrulama (flat)
        mock_ex.fetch_positions.side_effect = [[pos], [pos], []]
        mock_ex.create_market_order.side_effect = [
            Exception('binance {"code":-2022,"msg":"ReduceOnly Order is rejected."}'),
            {"id": "ok"},
        ]
        mock_ex.fapiPrivateGetOpenAlgoOrders.return_value = []

        dms = _mk_dms(tmp_path, mock_ex)
        ok = dms._emergency_flatten()

        assert ok is True
        assert mock_ex.create_market_order.call_count == 2
        first_kw = mock_ex.create_market_order.call_args_list[0].kwargs
        second_kw = mock_ex.create_market_order.call_args_list[1].kwargs
        assert first_kw.get("params", {}).get("reduceOnly") is True
        # fallback: reduceOnly YOK (plain market) — testnet -2022 reçetesi
        assert not (second_kw.get("params") or {}).get("reduceOnly")
        dms.stop()

    def test_flatten_returns_false_when_position_survives(self, tmp_path, monkeypatch):
        import price_action.execution.dead_mans_switch as dms_mod

        monkeypatch.setattr(dms_mod, "KILL_SWITCH_PATH", tmp_path / "ks.json")

        pos = {"symbol": "SOL/USDT:USDT", "contracts": 9.01, "side": "long"}
        mock_ex = MagicMock()
        mock_ex.fetch_positions.return_value = [pos]  # her fetch'te hâlâ açık
        mock_ex.create_market_order.side_effect = Exception("network down")
        mock_ex.fapiPrivateGetOpenAlgoOrders.return_value = []

        dms = _mk_dms(tmp_path, mock_ex)
        assert dms._emergency_flatten() is False
        dms.stop()

    def test_flatten_true_when_no_positions(self, tmp_path, monkeypatch):
        import price_action.execution.dead_mans_switch as dms_mod

        monkeypatch.setattr(dms_mod, "KILL_SWITCH_PATH", tmp_path / "ks.json")
        mock_ex = MagicMock()
        mock_ex.fetch_positions.return_value = []
        mock_ex.fapiPrivateGetOpenAlgoOrders.return_value = []

        dms = _mk_dms(tmp_path, mock_ex)
        assert dms._emergency_flatten() is True
        dms.stop()

    def test_watchdog_retries_failed_flatten(self, tmp_path, monkeypatch):
        """Tek-atış bug'ı: flatten başarısızsa sonraki tick'te TEKRAR denenmeli."""
        import price_action.execution.dead_mans_switch as dms_mod

        monkeypatch.setattr(dms_mod, "KILL_SWITCH_PATH", tmp_path / "ks.json")
        mock_ex = MagicMock()
        mock_ex.fetch_positions.return_value = []
        mock_ex.fapiPrivateGetOpenAlgoOrders.return_value = []

        dms = _mk_dms(tmp_path, mock_ex)
        dms._last_heartbeat_ts = 0.0  # çok eski → triggered
        import os as _os
        import time as _time

        hb = dms._watchdog.heartbeat_file
        _os.utime(hb, (_time.time() - 99999, _time.time() - 99999))

        dms._emergency_flatten = MagicMock(side_effect=[False, True])
        dms._watchdog_check()
        assert dms._flatten_done is False  # başarısız → done DEĞİL
        dms._watchdog_check()
        assert dms._flatten_done is True  # 2. deneme başarılı
        assert dms._emergency_flatten.call_count == 2
        dms.stop()

    def test_watchdog_gives_up_after_max_attempts(self, tmp_path, monkeypatch):
        """Sonsuz emir spam'i yok: FLATTEN_MAX_ATTEMPTS sonra durur (CRIT log)."""
        import price_action.execution.dead_mans_switch as dms_mod

        monkeypatch.setattr(dms_mod, "KILL_SWITCH_PATH", tmp_path / "ks.json")
        mock_ex = MagicMock()
        mock_ex.fetch_positions.return_value = []
        mock_ex.fapiPrivateGetOpenAlgoOrders.return_value = []

        dms = _mk_dms(tmp_path, mock_ex)
        dms._last_heartbeat_ts = 0.0
        import os as _os
        import time as _time

        hb = dms._watchdog.heartbeat_file
        _os.utime(hb, (_time.time() - 99999, _time.time() - 99999))

        dms._emergency_flatten = MagicMock(return_value=False)
        for _ in range(dms_mod.FLATTEN_MAX_ATTEMPTS + 2):
            dms._watchdog_check()
        assert dms._emergency_flatten.call_count == dms_mod.FLATTEN_MAX_ATTEMPTS
        assert dms._flatten_done is True  # tavana ulaşıldı → spam durdu
        dms.stop()

    def test_successful_flatten_not_repeated(self, tmp_path, monkeypatch):
        import price_action.execution.dead_mans_switch as dms_mod

        monkeypatch.setattr(dms_mod, "KILL_SWITCH_PATH", tmp_path / "ks.json")
        mock_ex = MagicMock()
        mock_ex.fetch_positions.return_value = []
        mock_ex.fapiPrivateGetOpenAlgoOrders.return_value = []

        dms = _mk_dms(tmp_path, mock_ex)
        dms._last_heartbeat_ts = 0.0
        import os as _os
        import time as _time

        hb = dms._watchdog.heartbeat_file
        _os.utime(hb, (_time.time() - 99999, _time.time() - 99999))

        dms._emergency_flatten = MagicMock(return_value=True)
        dms._watchdog_check()
        dms._watchdog_check()
        assert dms._emergency_flatten.call_count == 1
        dms.stop()
