"""TradeJournal — kapanan futures trade kayıt + bugünkü realized PnL aggregation.

SEC26.B-4: `realized_pnl_today_futures()` artık equity_snapshot delta yerine
gerçek kapanmış trade'lerin SUM(realized_pnl_usdt) toplamından okusun.
Açık pozisyon unrealized değişimi daily_pnl'i kirletmesin → DD breaker doğru.

PARTIAL-CLOSE UPDATE (2026-05-31):
Winner-let-run tasarımında 3 protection emri var (TP1 %25, TP2 %25, SL %50
runner). TP1 kısmi dolup trailing SL cancel-replace olduğu yarış anında
"ikisi de yok" görünüp TÜM kaydı 'tp' ile kapatıyordu → runner borsada AÇIK
kalırken journal'da kapalı → reconciler PHANTOM + realized PnL şişmesi.

Çözüm:
- `futures_partial_closes` yeni tablosu: kısmi TP dilimleri buraya.
- `record_partial_close()`: idempotent partial kayıt.
- `get_remaining_qty()`: fill_qty − SUM(partials) = açık kalan qty.
- `get_realized_pnl_today()` / `get_realized_pnl_window()`: partial + final
  toplamını döner (çift sayım yok: partial'lar partial tablosunda, final dilim
  trades_closed'de — ayrık).
- `record_close()` semantiği değişmedi: TAMAMEN kapandı → bu tabloya.
  qty = kalan (runner) qty, entry→exit sadece o dilim.

Schema (mevcut `futures_trades_closed` DEĞİŞMEDİ):

    CREATE TABLE IF NOT EXISTS futures_partial_closes (
        close_id TEXT PRIMARY KEY,
        trade_id TEXT NOT NULL,
        ts_close TIMESTAMP,
        sym TEXT,
        side TEXT,
        strategy TEXT,
        qty_closed DOUBLE,
        exit_price DOUBLE,
        realized_pnl_usdt DOUBLE,
        realized_r DOUBLE,
        close_reason TEXT   -- 'tp1' | 'tp2' | 'tp' | 'sl' | 'partial_close'
    )

Public API:
    journal = TradeJournal()                           # default data/futures_journal.duckdb
    journal.record_close(trade_id, ts_open, ts_close,
                         sym, side, strategy,
                         entry_price, exit_price, qty,
                         sl_price, close_reason)       # → True/False (idempotent)
    journal.record_partial_close(close_id, trade_id, ts_close,
                                 sym, side, strategy,
                                 entry_price, exit_price,
                                 qty_closed, sl_price,
                                 close_reason)         # → True/False (idempotent)
    rem = journal.get_remaining_qty(trade_id, fill_qty)  # fill_qty − SUM(partials)
    pnl_today = journal.get_realized_pnl_today()       # USD bugün (partial + final)
    pnl_window = journal.get_realized_pnl_window(s, e) # arbitrary window
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Literal

import duckdb

# Module-level lock — concurrent record_close/record_partial_close threads aynı
# trade_id için DuckDB constraint violation race'i önle (DuckDB PRIMARY KEY
# tablosu lock tutmuyor, pre-check + insert iki ayrı işlem). Bu lock
# process-içi yeterli.
_WRITE_LOCK = threading.Lock()


def _compute_realized_pnl(entry_price: float, exit_price: float, qty: float, side: str) -> float:
    """Realized PnL (USDT). Linear futures (USDT-margined) for both sides.

    long:  (exit - entry) * qty
    short: (entry - exit) * qty
    """
    if side == "long":
        return (exit_price - entry_price) * qty
    elif side == "short":
        return (entry_price - exit_price) * qty
    else:
        raise ValueError(f"side must be 'long' or 'short', got {side!r}")


def _compute_realized_r(entry_price: float, exit_price: float, side: str, sl_price: float) -> float:
    """Realized R = pnl_per_unit / risk_per_unit.

    Edge case: sl_price == entry_price → risk=0 → R=0 (clamp, no crash).
    Bu durum normalde olmamalı (signal builder sl_price'i entry'den uzakta
    set eder) ama defensive.
    """
    risk_per_unit = abs(entry_price - sl_price)
    if risk_per_unit <= 0.0:
        return 0.0
    if side == "long":
        pnl_per_unit = exit_price - entry_price
    elif side == "short":
        pnl_per_unit = entry_price - exit_price
    else:
        raise ValueError(f"side must be 'long' or 'short', got {side!r}")
    return pnl_per_unit / risk_per_unit


def _strip_tz(dt: datetime) -> datetime:
    """tz-aware datetime'ı UTC'ye çevir + tzinfo strip. naive ise dokunma."""
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


class TradeJournal:
    """Kapanan trade kayıt + bugünkü realized PnL aggregation.

    Idempotent (PRIMARY KEY trade_id, duplicate insert sessizce reddedilir).
    UTC consistent (tüm timestamp UTC olarak yorumlanır).
    """

    def __init__(self, db_path: str | Path = "data/futures_journal.duckdb") -> None:
        self.db_path = str(db_path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """CREATE IF NOT EXISTS — SEC26.B-3 schema parity + partial_closes."""
        con = duckdb.connect(self.db_path)
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS futures_trades_closed (
                    trade_id TEXT PRIMARY KEY,
                    ts_open TIMESTAMP,
                    ts_close TIMESTAMP,
                    sym TEXT,
                    side TEXT,
                    strategy TEXT,
                    entry_price DOUBLE,
                    exit_price DOUBLE,
                    qty DOUBLE,
                    realized_pnl_usdt DOUBLE,
                    realized_r DOUBLE,
                    win BOOLEAN,
                    close_reason TEXT
                )
            """)
            # NEW: partial closes table (2026-05-31)
            # Semantik: her ara TP dilimi buraya. Sadece bu tablodan okunarak
            # çift sayım olmaz (final dilim trades_closed'de, partial'lar burada).
            con.execute("""
                CREATE TABLE IF NOT EXISTS futures_partial_closes (
                    close_id TEXT PRIMARY KEY,
                    trade_id TEXT NOT NULL,
                    ts_close TIMESTAMP,
                    sym TEXT,
                    side TEXT,
                    strategy TEXT,
                    qty_closed DOUBLE,
                    exit_price DOUBLE,
                    realized_pnl_usdt DOUBLE,
                    realized_r DOUBLE,
                    close_reason TEXT
                )
            """)
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_fpc_trade_id "
                "ON futures_partial_closes (trade_id)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_fpc_ts_close "
                "ON futures_partial_closes (ts_close)"
            )
            con.commit()
        finally:
            con.close()

    def record_close(
        self,
        *,
        trade_id: str,
        ts_open: datetime,
        ts_close: datetime,
        sym: str,
        side: Literal["long", "short"],
        strategy: str,
        entry_price: float,
        exit_price: float,
        qty: float,
        sl_price: float,
        close_reason: Literal["tp", "sl", "time", "force", "reconcile_orphan"] = "tp",
        realized_pnl_override: float | None = None,
    ) -> bool:
        # G8 fix (hard review 2026-05-21): _ensure_schema her record_close çağrısında
        # da garanti edilir. Daemon farklı DB path ile (phoenix/atlas bot JOURNAL)
        # ilk kez TradeJournal(db_path=JOURNAL) yaptığında __init__ schema'yı kurar;
        # ama JOURNAL başka bağlantıyla açık/boş ise (örn. equity_snapshot DuckDB
        # exclusive lock alırsa) schema kaçabilir. __init__ + record_close çift güvence.
        # _ensure_schema CREATE TABLE IF NOT EXISTS → idempotent, perf yükü minimax.
        self._ensure_schema()
        """Kapanan trade'i kaydet. Idempotent — aynı trade_id 2. kez çağrılırsa False.

        SEMANTIK: Pozisyon BORSADA TAM KAPANDI anlamına gelir. qty = kalan
        (runner) qty, bu son dilimin realized PnL'ini kapsar. Kısmi kapanışlar
        için record_partial_close() kullan.

        Returns:
            True  → yeni kayıt eklendi
            False → trade_id zaten mevcut (idempotent no-op)

        No-clip: realized_pnl çok büyük olsa bile clip etmiyoruz.
        """
        # UTC normalize — G7 fix (hard review 2026-05-21):
        # futures_trades_closed.ts_* kolonları tz-NAIVE TIMESTAMP. tz-aware
        # datetime insert edilince DuckDB connector yerel saate (UTC+3) çevirip
        # naive yazıyordu → +3h kayma. Çözüm: aware ise UTC'ye çevir + tzinfo
        # strip; naive ise UTC varsay (caller sözleşmesi), dokunma.
        ts_open = _strip_tz(ts_open)
        ts_close = _strip_tz(ts_close)

        side = side.lower()  # type: ignore[assignment]
        # CT-EXE-02 (2026-06-15): realized_pnl_override verilirse (borsa income'ından
        # gerçek REALIZED_PNL+COMMISSION+FUNDING) onu yaz — lokal (exit-entry)*qty
        # fee/funding'i atlıyor + heal yolu hiç yazmıyordu. None ise eski lokal hesap.
        # realized_r fiyat-bazlı kalır (R = fiyat-hareketi oranı, fee'den bağımsız).
        if realized_pnl_override is not None:
            realized_pnl = float(realized_pnl_override)
        else:
            realized_pnl = _compute_realized_pnl(entry_price, exit_price, qty, side)
        realized_r = _compute_realized_r(entry_price, exit_price, side, sl_price)
        win = realized_pnl > 0.0

        with _WRITE_LOCK:
            con = duckdb.connect(self.db_path)
            try:
                # Idempotent: pre-check + insert. PRIMARY KEY constraint extra safety.
                existing = con.execute(
                    "SELECT 1 FROM futures_trades_closed WHERE trade_id = ?",
                    [trade_id],
                ).fetchone()
                if existing:
                    return False
                try:
                    con.execute(
                        """
                        INSERT INTO futures_trades_closed VALUES
                        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            trade_id,
                            ts_open,
                            ts_close,
                            sym,
                            side,
                            strategy,
                            float(entry_price),
                            float(exit_price),
                            float(qty),
                            float(realized_pnl),
                            float(realized_r),
                            bool(win),
                            close_reason,
                        ],
                    )
                    con.commit()
                    return True
                except duckdb.ConstraintException:
                    # Race: başka thread/process aynı trade_id'yi insert etti.
                    return False
            finally:
                con.close()

    def record_partial_close(
        self,
        *,
        close_id: str,
        trade_id: str,
        ts_close: datetime,
        sym: str,
        side: Literal["long", "short"],
        strategy: str,
        entry_price: float,
        exit_price: float,
        qty_closed: float,
        sl_price: float,
        close_reason: str = "tp1",
    ) -> bool:
        """Kısmi TP dilimini kaydet. Idempotent — aynı close_id 2. kez çağrılırsa False.

        close_id deterministik olmalı: örn. f"{trade_id}_{tp_order_id}".
        Böylece aynı TP1 fill ikinci kez kontrol edildiğinde tekrar yazılmaz.

        SEMANTIK: Pozisyon borsada AÇIK kalmaya devam eder. Sadece bu dilim
        kapatıldı. trade_id asla trades_closed'e bu çağrıyla girmez.

        Returns:
            True  → yeni partial kayıt eklendi
            False → close_id zaten mevcut (idempotent no-op)
        """
        self._ensure_schema()
        ts_close = _strip_tz(ts_close)
        side = side.lower()  # type: ignore[assignment]
        realized_pnl = _compute_realized_pnl(entry_price, exit_price, qty_closed, side)
        realized_r = _compute_realized_r(entry_price, exit_price, side, sl_price)

        with _WRITE_LOCK:
            con = duckdb.connect(self.db_path)
            try:
                existing = con.execute(
                    "SELECT 1 FROM futures_partial_closes WHERE close_id = ?",
                    [close_id],
                ).fetchone()
                if existing:
                    return False
                try:
                    con.execute(
                        """
                        INSERT INTO futures_partial_closes VALUES
                        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            close_id,
                            trade_id,
                            ts_close,
                            sym,
                            side,
                            strategy,
                            float(qty_closed),
                            float(exit_price),
                            float(realized_pnl),
                            float(realized_r),
                            close_reason,
                        ],
                    )
                    con.commit()
                    return True
                except duckdb.ConstraintException:
                    return False
            finally:
                con.close()

    def get_remaining_qty(self, trade_id: str, fill_qty: float) -> float:
        """Açık kalan qty = fill_qty − SUM(futures_partial_closes.qty_closed).

        Pozisyon tamamen kapanmışsa (trades_closed'de varsa) 0.0 döner.
        Partial'lar yoksa fill_qty'nin tamamı döner.
        """
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            # Önce tam kapandı mı kontrol et
            closed = con.execute(
                "SELECT 1 FROM futures_trades_closed WHERE trade_id = ?",
                [trade_id],
            ).fetchone()
            if closed:
                return 0.0
            # Partial kapananları topla
            row = con.execute(
                "SELECT COALESCE(SUM(qty_closed), 0.0) FROM futures_partial_closes "
                "WHERE trade_id = ?",
                [trade_id],
            ).fetchone()
            partial_sum = float(row[0]) if row and row[0] is not None else 0.0
            remaining = float(fill_qty) - partial_sum
            return max(0.0, remaining)
        except duckdb.CatalogException:
            return float(fill_qty)
        finally:
            con.close()

    def get_partial_pnl_sum(self, trade_id: str) -> float:
        """Bu trade için daha önce kaydedilmiş partial realized PnL toplamı (USDT).

        CT-EXE-02: borsa income penceresi ([ts_open, ts_close]) trade'in TÜM
        realized'ını (partial TP'ler dahil) kapsar. record_close'a override olarak
        FULL income − bu toplam (= runner dilimi) geçilmeli; yoksa partial'lar hem
        futures_partial_closes'ta hem trades_closed'da çift sayılır. Partial yoksa 0.0.
        """
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            row = con.execute(
                "SELECT COALESCE(SUM(realized_pnl_usdt), 0.0) FROM futures_partial_closes "
                "WHERE trade_id = ?",
                [trade_id],
            ).fetchone()
            return float(row[0]) if row and row[0] is not None else 0.0
        except duckdb.CatalogException:
            return 0.0
        finally:
            con.close()

    def get_realized_pnl_today(self, *, now: datetime | None = None) -> float:
        """Bugünkü (UTC) realized PnL toplamı (USDT).

        trades_closed + futures_partial_closes TOPLAMINI döner (çift sayım yok:
        partial'lar partial tablosunda, final dilim trades_closed'de — ayrık).

        UTC günü 00:00:00'da reset olur (kalan zaman dilimleri irrelevant
        — DD breaker UTC daily anchor ile tutarlı).
        """
        if now is None:
            now = datetime.now(UTC)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        day_start = datetime.combine(now.date(), time.min, tzinfo=UTC)
        day_end = datetime.combine(now.date(), time.max, tzinfo=UTC)
        return self.get_realized_pnl_window(day_start, day_end)

    def get_realized_pnl_window(self, start_utc: datetime, end_utc: datetime) -> float:
        """[start_utc, end_utc] kapalı aralık için SUM(realized_pnl_usdt).

        trades_closed + futures_partial_closes TOPLAMINI döner.
        Çift sayım yok: partial'lar partial tablosunda, final dilim
        trades_closed'de (ayrık tablolar, ayrık dilimleri kaydeder).

        Boş aralık veya tablo yokken 0.0.
        """
        # G7 fix (hard review 2026-05-21): ts_close kolonu naive-UTC; sorgu
        # parametreleri de naive-UTC olmalı — tz-aware ise yerel saate kayar.
        start_utc = _strip_tz(start_utc)
        end_utc = _strip_tz(end_utc)
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            # trades_closed PnL
            row_closed = con.execute(
                """
                SELECT COALESCE(SUM(realized_pnl_usdt), 0.0)
                FROM futures_trades_closed
                WHERE ts_close >= ? AND ts_close <= ?
                """,
                [start_utc, end_utc],
            ).fetchone()
            pnl_closed = float(row_closed[0]) if row_closed and row_closed[0] is not None else 0.0

            # futures_partial_closes PnL
            try:
                row_partial = con.execute(
                    """
                    SELECT COALESCE(SUM(realized_pnl_usdt), 0.0)
                    FROM futures_partial_closes
                    WHERE ts_close >= ? AND ts_close <= ?
                    """,
                    [start_utc, end_utc],
                ).fetchone()
                pnl_partial = (
                    float(row_partial[0]) if row_partial and row_partial[0] is not None else 0.0
                )
            except duckdb.CatalogException:
                # Tablo henüz yok (yeni DB, eski deployment)
                pnl_partial = 0.0

            return pnl_closed + pnl_partial
        except duckdb.CatalogException:
            # futures_trades_closed tablo yok (yeni DB, schema henüz yaratılmadı)
            return 0.0
        finally:
            con.close()


__all__ = [
    "TradeJournal",
    "_compute_realized_pnl",
    "_compute_realized_r",
]
