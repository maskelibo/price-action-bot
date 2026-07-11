"""Slippage Tracker — Fill-level journal + günlük aggregat + alarmlar.

Her fill kayıt altına alınır:
  - expected_price (signal anındaki ref fiyat)
  - realized_price (exchange fill average)
  - slippage_bps, fee_bps, total_cost_bps
  - is_maker (post-only rebate)
  - fill_role (entry | exit | unknown; maker KPI yalnız entry)
  - fee_source (exchange_user_trades | estimated | provided | unavailable)
  - tf (timeframe bucket: "1m", "5m", "15m", "1h", "1d")

Günlük aggregat:
  - Ortalama slippage, max, p95 — hem global hem TF-bucket bazlı
  - Entry-only maker fill rate
  - Thresholds TF-bazlı (15m: 15bps, 5m: 12bps, 1m: 10bps)
  - >threshold WARNING; >threshold*2 CRITICAL

TF Slippage Budgets (master plan §4.5):
  1d:  25 bps single-fill cap (legacy)
  15m: 15 bps WARNING, 30 bps CRITICAL
  5m:  12 bps WARNING, 24 bps CRITICAL
  1m:  10 bps WARNING, 20 bps CRITICAL

Usage:
    tracker = SlippageTracker()
    tracker.record_fill(..., tf="15m")
    summary = tracker.daily_summary()
    tf_hist  = tracker.tf_histogram("15m")
"""

from __future__ import annotations

import json
import logging
import math
import threading
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb

from price_action.runtime_paths import RuntimePaths

ROOT = (
    Path(__file__).resolve().parents[3]
)  # G24 fix: Price Action kökü (eskiden parents[4]=projeler — proje dışı)
_RUNTIME_PATHS = RuntimePaths.from_env(ROOT)
DEFAULT_DB = _RUNTIME_PATHS.data / "execution_fills.duckdb"
LOG_DIR = _RUNTIME_PATHS.logs / "execution"

# Legacy (1d) defaults
ALARM_WARNING_BPS = 10.0
ALARM_CRITICAL_BPS = 20.0
SINGLE_FILL_MAX_BPS = 25.0

# TF-spesifik slippage budget (bps)
TF_SLIPPAGE_BUDGET: dict[str, dict[str, float]] = {
    "1m": {"warning": 10.0, "critical": 20.0, "single_max": 15.0},
    "5m": {"warning": 12.0, "critical": 24.0, "single_max": 18.0},
    "15m": {"warning": 15.0, "critical": 30.0, "single_max": 22.0},
    "1h": {"warning": 20.0, "critical": 40.0, "single_max": 25.0},
    "4h": {"warning": 20.0, "critical": 40.0, "single_max": 25.0},
    "1d": {"warning": 10.0, "critical": 20.0, "single_max": 25.0},
}

_ENTRY_FILL_TYPES = frozenset({"entry", "pyramid"})
_EXIT_FILL_TYPES = frozenset({"exit", "protection", "tp", "tp1", "tp2", "sl"})
_VALID_FILL_ROLES = frozenset({"entry", "exit", "unknown"})
_LOG = logging.getLogger(__name__)

# Router ACK aggregate'leri (cumQuote / executedQty) ile matching-engine
# userTrades toplamları aynı fill'i farklı decimal toplama sırasıyla temsil
# edebilir.  Ownership doğrulaması exact binary-float eşitliği istememeli;
# buna karşılık yalnız pozitif, sonlu ve birbirine çok yakın değerleri kabul
# etmelidir.  Daemon ve deferred processor aynı sözleşmeyi kullanır.
EXECUTION_EVIDENCE_REL_TOL = 1e-8
EXECUTION_EVIDENCE_ABS_TOL = 1e-10


def execution_evidence_values_match(left: object, right: object) -> bool:
    """Return whether two positive execution values are exchange-equivalent."""
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    try:
        left_value = float(left)
        right_value = float(right)
    except (TypeError, ValueError):
        return False
    if not (
        math.isfinite(left_value)
        and math.isfinite(right_value)
        and left_value > 0
        and right_value > 0
    ):
        return False
    return math.isclose(
        left_value,
        right_value,
        rel_tol=EXECUTION_EVIDENCE_REL_TOL,
        abs_tol=EXECUTION_EVIDENCE_ABS_TOL,
    )


class DeterministicFillConflictError(RuntimeError):
    """A stable fill id was replayed with different execution evidence."""


def _stored_fill_value_matches(left: object, right: object) -> bool:
    """Compare nullable/zero/negative stored numerics with exchange tolerance."""
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    try:
        left_value = float(left)
        right_value = float(right)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(left_value) and math.isfinite(right_value)):
        return False
    return math.isclose(
        left_value,
        right_value,
        rel_tol=EXECUTION_EVIDENCE_REL_TOL,
        abs_tol=EXECUTION_EVIDENCE_ABS_TOL,
    )


def _resolve_fill_role(fill_role: str | None, fill_type: str) -> str:
    """KPI rolünü güvenli çöz; belirsiz/geçersiz değer entry sayılmaz."""
    if fill_role is not None:
        explicit = str(fill_role).strip().lower()
        return explicit if explicit in _VALID_FILL_ROLES else "unknown"
    normalized_type = str(fill_type).strip().lower()
    if normalized_type in _ENTRY_FILL_TYPES:
        return "entry"
    if normalized_type in _EXIT_FILL_TYPES:
        return "exit"
    return "unknown"


class SlippageTracker:
    """Thread-safe fill journal ve slippage izleme (TF-bucket destekli)."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path else DEFAULT_DB
        self._path.parent.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        con = duckdb.connect(str(self._path))
        con.execute("""
            CREATE TABLE IF NOT EXISTS fills (
                fill_id VARCHAR PRIMARY KEY,
                ts TIMESTAMP NOT NULL,
                symbol VARCHAR,
                strategy VARCHAR,
                side VARCHAR,
                fill_role VARCHAR DEFAULT 'unknown',
                tf VARCHAR DEFAULT '1d',
                expected_price DOUBLE,
                realized_price DOUBLE,
                quantity DOUBLE,
                maker_quantity DOUBLE,
                notional_usdt DOUBLE,
                maker_notional_usdt DOUBLE,
                slippage_bps DOUBLE,
                fee_usdt DOUBLE,
                fee_source VARCHAR DEFAULT 'legacy_unknown',
                fee_bps DOUBLE,
                total_cost_bps DOUBLE,
                is_maker BOOLEAN,
                order_type VARCHAR,
                mode VARCHAR,
                exchange_order_id VARCHAR,
                client_order_id VARCHAR,
                notes VARCHAR
            )
        """)
        # Idempotent migration: tf column eski DB'lerde yoksa ekle.
        # Pyramid leg-2 slippage record FAIL (table fills has 19 columns but 20 values) → A1 fix.
        existing_cols = {row[0] for row in con.execute("DESCRIBE fills").fetchall()}
        if "tf" not in existing_cols:
            con.execute("ALTER TABLE fills ADD COLUMN tf VARCHAR DEFAULT '1d'")
        # Maker KPI migration: yalnız notes'ta açık fill_type kanıtı olan eski
        # satırlar backfill edilir. Belirsiz legacy satırlar UNKNOWN kalır ve
        # entry maker paydasına girmez (fail-closed).
        if "fill_role" not in existing_cols:
            con.execute("ALTER TABLE fills ADD COLUMN fill_role VARCHAR DEFAULT 'unknown'")
            if "notes" in existing_cols:
                con.execute(
                    """UPDATE fills
                       SET fill_role = CASE
                           WHEN lower(coalesce(notes, '')) LIKE 'fill_type=entry%'
                             OR lower(coalesce(notes, '')) LIKE 'fill_type=pyramid%'
                               THEN 'entry'
                           WHEN lower(coalesce(notes, '')) LIKE 'fill_type=tp%'
                             OR lower(coalesce(notes, '')) LIKE 'fill_type=sl%'
                             OR lower(coalesce(notes, '')) LIKE 'fill_type=exit%'
                             OR lower(coalesce(notes, '')) LIKE 'fill_type=protection%'
                               THEN 'exit'
                           ELSE 'unknown'
                       END"""
                )
        if "fee_source" not in existing_cols:
            con.execute("ALTER TABLE fills ADD COLUMN fee_source VARCHAR DEFAULT 'legacy_unknown'")
        # Mixed post-only→market fallback kanıtı. Eski binary entry satırları
        # yalnız bildiğimiz kadar backfill edilir; UNKNOWN roller tahmin edilmez.
        if "maker_quantity" not in existing_cols:
            con.execute("ALTER TABLE fills ADD COLUMN maker_quantity DOUBLE")
            con.execute(
                """UPDATE fills SET maker_quantity = CASE
                     WHEN fill_role = 'entry' AND is_maker IS TRUE THEN quantity
                     WHEN fill_role = 'entry' THEN 0.0
                     ELSE NULL END"""
            )
        if "maker_notional_usdt" not in existing_cols:
            con.execute("ALTER TABLE fills ADD COLUMN maker_notional_usdt DOUBLE")
            con.execute(
                """UPDATE fills SET maker_notional_usdt = CASE
                     WHEN fill_role = 'entry' AND is_maker IS TRUE THEN notional_usdt
                     WHEN fill_role = 'entry' THEN 0.0
                     ELSE NULL END"""
            )
        con.execute("""
            CREATE TABLE IF NOT EXISTS daily_slippage_summary (
                summary_date DATE PRIMARY KEY,
                n_fills INTEGER,
                avg_slippage_bps DOUBLE,
                max_slippage_bps DOUBLE,
                p95_slippage_bps DOUBLE,
                maker_fill_pct DOUBLE,
                total_fee_usdt DOUBLE,
                alarm_triggered BOOLEAN,
                alarm_level VARCHAR,
                n_entry_fills INTEGER DEFAULT 0,
                n_exit_fills INTEGER DEFAULT 0,
                n_unknown_fills INTEGER DEFAULT 0,
                n_fee_unknown_fills INTEGER DEFAULT 0,
                total_fee_complete BOOLEAN DEFAULT TRUE,
                maker_qty_pct DOUBLE DEFAULT 0,
                maker_notional_pct DOUBLE DEFAULT 0
            )
        """)
        summary_cols = {row[0] for row in con.execute("DESCRIBE daily_slippage_summary").fetchall()}
        summary_migrations = {
            "n_entry_fills": "INTEGER DEFAULT 0",
            "n_exit_fills": "INTEGER DEFAULT 0",
            "n_unknown_fills": "INTEGER DEFAULT 0",
            "n_fee_unknown_fills": "INTEGER DEFAULT 0",
            "total_fee_complete": "BOOLEAN DEFAULT TRUE",
            "maker_qty_pct": "DOUBLE DEFAULT 0",
            "maker_notional_pct": "DOUBLE DEFAULT 0",
        }
        for col, ddl in summary_migrations.items():
            if col not in summary_cols:
                con.execute(f"ALTER TABLE daily_slippage_summary ADD COLUMN {col} {ddl}")
        con.commit()
        con.close()

    def record_fill(
        self,
        fill_id: str,
        ts: datetime,
        symbol: str,
        strategy: str,
        side: str,
        expected_price: float,
        realized_price: float,
        quantity: float,
        fee_usdt: float | None,
        is_maker: bool,
        order_type: str,
        mode: str,
        exchange_order_id: str = "",
        client_order_id: str = "",
        notes: str = "",
        tf: str = "1d",
        fill_type: str = "entry",
        fill_role: str | None = None,
        fee_source: str | None = None,
        maker_quantity: float | None = None,
        maker_notional_usdt: float | None = None,
    ) -> float:
        """Fill'i kayıt altına al. Hesaplanan slippage_bps döndür.

        Yön ve fill-rolü düzeltmeli slippage:
          LONG entry / SHORT exit (buy): realized > expected = maliyet (pozitif)
          SHORT entry / LONG exit (sell): realized < expected = maliyet (pozitif)

        Args:
            tf: Timeframe bucket ("1m", "5m", "15m", "1h", "4h", "1d").
                TF-bazlı slippage budget eşiklerini seçer.
            fill_type: Fill türü — "entry" | "tp" | "sl" | "tp1" | "tp2" | "pyramid".
                notes alanına eklenir; Batch D daemon fill noktasını etiketlemek için.
                Mevcut çağrılar etkilenmez (default "entry").
            fill_role: KPI rolü — "entry" | "exit" | "unknown". Verilmezse
                fill_type'tan güvenli biçimde türetilir; geçersiz değer UNKNOWN olur.
            fee_source: Ücretin kaynağı. fee_usdt None ise default "unavailable";
                aksi halde geriye uyum için "provided".
            maker_quantity: Entry içindeki maker dolan miktar. Mixed fallback'te
                partial limit leg; verilmezse binary is_maker'dan türetilir.
            maker_notional_usdt: Entry içindeki maker notional. Verilmezse
                maker_quantity oranından veya binary is_maker'dan türetilir.

        G14 fix (hard review 2026-05-21): fill_type parametresi eklendi. Daemon
        entry/TP/SL fill noktalarını etiketleyerek logs/execution JSONL + DB'ye
        yazar. Ayrıca _init_db çağrısı burada da garantilenir (koşullu DuckDB
        init race, farklı process'ten DB ilk açılışında schema kaçabilir).
        """
        # G14 fix: her record_fill çağrısında schema varlığını garantile.
        # PyramidRouter + daemon concurrent bağlantıda tablo eksik olabilir.
        self._init_db()
        # fill_type → notes alanına yaz (mevcut notes varsa önüne ekle)
        _type_prefix = f"fill_type={fill_type}"
        notes = f"{_type_prefix} {notes}" if notes else _type_prefix
        resolved_role = _resolve_fill_role(fill_role, fill_type)
        resolved_fee_source = (
            str(fee_source).strip().lower()
            if fee_source is not None and str(fee_source).strip()
            else ("unavailable" if fee_usdt is None else "provided")
        )
        fee_value = float(fee_usdt) if fee_usdt is not None else None
        # DuckDB TIMESTAMP offset saklamaz; aware datetime'ı doğrudan bind etmek
        # session timezone'a çevirip offset'i atar. DB sözleşmesi UTC-naive.
        db_ts = ts.astimezone(UTC).replace(tzinfo=None) if ts.tzinfo is not None else ts
        notional = quantity * realized_price
        if maker_quantity is None:
            resolved_maker_quantity = float(quantity if is_maker else 0.0)
        else:
            resolved_maker_quantity = min(max(float(maker_quantity), 0.0), float(quantity))
        if maker_notional_usdt is not None:
            resolved_maker_notional = min(max(float(maker_notional_usdt), 0.0), float(notional))
        elif maker_quantity is not None and quantity > 0:
            resolved_maker_notional = notional * resolved_maker_quantity / quantity
        else:
            resolved_maker_notional = float(notional if is_maker else 0.0)
        normalized_side = str(side).strip().lower()
        buy_execution = normalized_side in {"long", "buy"}
        if resolved_role == "exit":
            # ``side`` pozisyon yönüdür; exit emri bunun tersidir. Bu dönüşüm
            # stop/TP slippage işaretini gerçek execution-cost semantiğine taşır.
            buy_execution = not buy_execution
        if buy_execution:
            slippage_bps = (realized_price - expected_price) / max(expected_price, 1e-10) * 10_000
        else:
            slippage_bps = (expected_price - realized_price) / max(expected_price, 1e-10) * 10_000

        fee_bps = fee_value / max(notional, 1e-10) * 10_000 if fee_value is not None else None
        # Ücret bilinmiyorsa total cost de bilinmiyor; slippage'i tek başına
        # "toplam maliyet" diye göstermeyiz (fail-closed ölçüm semantiği).
        total_cost_bps = slippage_bps + fee_bps if fee_bps is not None else None

        stored_values = [
            str(symbol),
            str(strategy),
            str(side),
            str(tf),
            resolved_role,
            float(expected_price),
            float(realized_price),
            float(quantity),
            resolved_maker_quantity,
            float(notional),
            resolved_maker_notional,
            round(slippage_bps, 4),
            fee_value,
            resolved_fee_source,
            round(fee_bps, 4) if fee_bps is not None else None,
            round(total_cost_bps, 4) if total_cost_bps is not None else None,
            bool(is_maker),
            str(order_type),
            str(mode),
            str(exchange_order_id),
            str(client_order_id),
        ]
        with self._lock:
            con = duckdb.connect(str(self._path))
            try:
                # Explicit column names: ALTER TABLE migration sonrası `tf` col tablonun
                # sonuna ekleniyor → positional INSERT yanlış kolona yazıyordu (A1 root cause).
                inserted = con.execute(
                    """INSERT OR IGNORE INTO fills
                       (fill_id, ts, symbol, strategy, side, tf,
                        fill_role,
                        expected_price, realized_price, quantity, maker_quantity,
                        notional_usdt, maker_notional_usdt,
                        slippage_bps, fee_usdt, fee_source, fee_bps, total_cost_bps,
                        is_maker, order_type, mode,
                        exchange_order_id, client_order_id, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       RETURNING fill_id""",
                    [fill_id, db_ts, *stored_values[:5], *stored_values[5:], notes],
                ).fetchone()
                if inserted is None:
                    existing = con.execute(
                        """SELECT symbol, strategy, side, tf, fill_role,
                                  expected_price, realized_price, quantity, maker_quantity,
                                  notional_usdt, maker_notional_usdt, slippage_bps,
                                  fee_usdt, fee_source, fee_bps, total_cost_bps,
                                  is_maker, order_type, mode, exchange_order_id,
                                  client_order_id
                           FROM fills WHERE fill_id=?""",
                        [fill_id],
                    ).fetchone()
                    if existing is None:
                        raise DeterministicFillConflictError(
                            f"deterministic fill {fill_id!r} was ignored but cannot be read back"
                        )
                    numeric_indexes = {5, 6, 7, 8, 9, 10, 11, 12, 14, 15}
                    mismatches = [
                        index
                        for index, (stored, incoming) in enumerate(
                            zip(existing, stored_values, strict=True)
                        )
                        if (
                            not _stored_fill_value_matches(stored, incoming)
                            if index in numeric_indexes
                            else stored != incoming
                        )
                    ]
                    if mismatches:
                        _LOG.critical(
                            "deterministic_fill_conflict fill_id=%s field_indexes=%s",
                            fill_id,
                            mismatches,
                        )
                        raise DeterministicFillConflictError(
                            f"deterministic fill {fill_id!r} payload mismatch at fields "
                            f"{mismatches}"
                        )
                con.commit()
            finally:
                con.close()

        # The database primary key owns idempotency.  Replayed fill evidence
        # must not duplicate JSONL, outlier notifications or warning alarms.
        if inserted is None:
            return slippage_bps

        # FIX 2026-05-28 (Faz 14.27 ORTA C4): outlier auto-quarantine.
        # Slippage > 100bps = OUTLIER, ayrı alarm + log dosyası.
        # Önceden P95/P99 hesaplanıyordu ama explicit auto-action yoktu.
        OUTLIER_BPS_THRESHOLD = 100.0  # noqa: N806 (sabit-anlam, fonksiyon-yerel eşik)
        if slippage_bps > OUTLIER_BPS_THRESHOLD:
            try:
                from price_action.orchestrator.notifications import push_critical

                push_critical(
                    f"⚠️ SLIPPAGE OUTLIER — {symbol} {strategy} {side} "
                    f"{slippage_bps:.0f}bps > {OUTLIER_BPS_THRESHOLD}bps "
                    f"(fill_id={fill_id})",
                    source="slippage_tracker_outlier",
                )
            except Exception:
                pass
            try:
                outlier_path = _RUNTIME_PATHS.logs / "slippage_outliers.jsonl"
                outlier_path.parent.mkdir(parents=True, exist_ok=True)
                with open(outlier_path, "a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {
                                "ts": ts.isoformat(),
                                "fill_id": fill_id,
                                "symbol": symbol,
                                "strategy": strategy,
                                "side": side,
                                "slippage_bps": slippage_bps,
                                "notional": notional,
                            }
                        )
                        + "\n"
                    )
            except Exception:
                pass

        # JSONL log
        self._write_jsonl(
            ts,
            {
                "fill_id": fill_id,
                "symbol": symbol,
                "side": side,
                "tf": tf,
                "fill_type": fill_type,
                "fill_role": resolved_role,
                "maker_quantity": resolved_maker_quantity,
                "maker_notional_usdt": round(resolved_maker_notional, 8),
                "slippage_bps": round(slippage_bps, 4),
                "fee_bps": round(fee_bps, 4) if fee_bps is not None else None,
                "fee_source": resolved_fee_source,
                "total_cost_bps": (
                    round(total_cost_bps, 4) if total_cost_bps is not None else None
                ),
                "is_maker": is_maker,
                "mode": mode,
            },
        )

        # TF-bazlı tek fill alarm
        # FIX 2026-05-26 (Faz 14.5): insan-anlaşılır Türkçe mesaj
        budget = TF_SLIPPAGE_BUDGET.get(tf, TF_SLIPPAGE_BUDGET["1d"])
        single_max = budget["single_max"]
        if slippage_bps > single_max:
            slip_pct = slippage_bps / 100  # bps → percent
            limit_pct = single_max / 100
            self._alarm(
                level="WARNING",  # CRITICAL → WARNING (zarar yok, sadece bilgi)
                msg=(
                    f"⚠️ Yüksek slip — {symbol} [{tf}]\n"
                    f"Bot emrini verdi, fiyat %{slip_pct:.3f} kaydı "
                    f"(limit %{limit_pct:.3f}). Trade açıldı ama beklenenden "
                    f"%{(slip_pct - limit_pct):.3f} daha pahalı/ucuz doldu. "
                    f"Sıkça olursa execution stratejisini gözden geçir "
                    f"(post-only fail veya likidite az)."
                ),
            )

        return slippage_bps

    def daily_summary(self, d: date | None = None, tf: str | None = None) -> dict[str, Any]:
        """Günlük özet hesapla + alarm değerlendir.

        ``maker_fill_pct`` geriye uyum için korunur ama artık yalnız
        ``fill_role='entry'`` satırlarının maker oranıdır. Exit ve belirsiz
        legacy satırlar KPI paydasına girmez.

        Args:
            d: Tarih (default: bugün).
            tf: Filtre TF (None = tüm TF'ler, global özet).
        """
        target = d or datetime.now(UTC).date()
        where_sql = "WHERE ts::DATE = ?"
        params: list[Any] = [target]
        if tf:
            where_sql += " AND tf = ?"
            params.append(tf)

        with self._lock:
            con = duckdb.connect(str(self._path))
            row = con.execute(
                f"""SELECT
                     COUNT(*),
                     AVG(slippage_bps),
                     MAX(slippage_bps),
                     PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY slippage_bps),
                     SUM(CASE WHEN fill_role = 'entry' THEN 1 ELSE 0 END),
                     SUM(CASE WHEN fill_role = 'exit' THEN 1 ELSE 0 END),
                     SUM(CASE WHEN coalesce(fill_role, 'unknown') NOT IN ('entry', 'exit')
                              THEN 1 ELSE 0 END),
                     SUM(CASE WHEN fill_role = 'entry' AND is_maker IS TRUE
                              THEN 1 ELSE 0 END) * 1.0
                         / NULLIF(SUM(CASE WHEN fill_role = 'entry' THEN 1 ELSE 0 END), 0),
                     SUM(CASE WHEN fill_role = 'entry' THEN quantity ELSE 0 END),
                     SUM(CASE WHEN fill_role = 'entry' THEN maker_quantity ELSE 0 END),
                     SUM(CASE WHEN fill_role = 'entry' THEN notional_usdt ELSE 0 END),
                     SUM(CASE WHEN fill_role = 'entry' THEN maker_notional_usdt ELSE 0 END),
                     SUM(fee_usdt),
                     SUM(CASE WHEN fee_usdt IS NOT NULL THEN 1 ELSE 0 END),
                     SUM(CASE WHEN fee_usdt IS NULL THEN 1 ELSE 0 END)
                   FROM fills
                   {where_sql}""",
                params,
            ).fetchone()
            con.close()

        (
            n,
            avg_slip,
            max_slip,
            p95_slip,
            entry_count,
            exit_count,
            unknown_count,
            maker_rate,
            entry_quantity,
            entry_maker_quantity,
            entry_notional,
            entry_maker_notional,
            total_fee,
            fee_known_count,
            fee_unknown_count,
        ) = row or (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        n = int(n or 0)
        entry_count = int(entry_count or 0)
        exit_count = int(exit_count or 0)
        unknown_count = int(unknown_count or 0)
        fee_known_count = int(fee_known_count or 0)
        fee_unknown_count = int(fee_unknown_count or 0)
        avg_slip = float(avg_slip or 0)
        max_slip = float(max_slip or 0)
        p95_slip = float(p95_slip or 0)
        maker_rate = float(maker_rate or 0)
        entry_quantity = float(entry_quantity or 0)
        entry_maker_quantity = float(entry_maker_quantity or 0)
        entry_notional = float(entry_notional or 0)
        entry_maker_notional = float(entry_maker_notional or 0)
        total_fee = float(total_fee or 0)
        maker_qty_pct = entry_maker_quantity / entry_quantity * 100 if entry_quantity > 0 else 0.0
        maker_notional_pct = (
            entry_maker_notional / entry_notional * 100 if entry_notional > 0 else 0.0
        )

        # TF-bazlı threshold'lar
        budget = TF_SLIPPAGE_BUDGET.get(tf or "1d", TF_SLIPPAGE_BUDGET["1d"])
        warn_bps = budget["warning"]
        crit_bps = budget["critical"]

        alarm_level = "OK"
        alarm_triggered = False
        if avg_slip > crit_bps:
            alarm_level = "CRITICAL"
            alarm_triggered = True
            self._alarm(
                level="CRITICAL",
                msg=(
                    f"DAILY_SLIPPAGE_CRITICAL [{tf or 'all'}]: "
                    f"avg {avg_slip:.1f}bps > {crit_bps}bps ({n} fills)"
                ),
            )
        elif avg_slip > warn_bps:
            alarm_level = "WARNING"
            alarm_triggered = True
            self._alarm(
                level="WARNING",
                msg=(
                    f"DAILY_SLIPPAGE_WARNING [{tf or 'all'}]: "
                    f"avg {avg_slip:.1f}bps > {warn_bps}bps ({n} fills)"
                ),
            )

        summary = {
            "date": target.isoformat(),
            "tf": tf or "all",
            "n_fills": n,
            "avg_slippage_bps": round(avg_slip, 2),
            "max_slippage_bps": round(max_slip, 2),
            "p95_slippage_bps": round(p95_slip, 2),
            "maker_fill_pct": round(maker_rate * 100, 1),
            "entry_maker_fill_pct": round(maker_rate * 100, 1),
            "entry_maker_order_pct": round(maker_rate * 100, 1),
            "entry_maker_qty_pct": round(maker_qty_pct, 1),
            "entry_maker_notional_pct": round(maker_notional_pct, 1),
            "entry_fill_count": entry_count,
            "exit_fill_count": exit_count,
            "unknown_fill_count": unknown_count,
            "total_fee_usdt": round(total_fee, 4),
            "fee_known_fill_count": fee_known_count,
            "fee_unknown_fill_count": fee_unknown_count,
            "total_fee_complete": fee_unknown_count == 0,
            "alarm_triggered": alarm_triggered,
            "alarm_level": alarm_level,
        }

        if tf is None:
            # Global özet → DB'ye kaydet
            with self._lock:
                con = duckdb.connect(str(self._path))
                con.execute(
                    """INSERT OR REPLACE INTO daily_slippage_summary
                       (summary_date, n_fills, avg_slippage_bps, max_slippage_bps,
                        p95_slippage_bps, maker_fill_pct, total_fee_usdt,
                        alarm_triggered, alarm_level, n_entry_fills, n_exit_fills,
                        n_unknown_fills, n_fee_unknown_fills, total_fee_complete,
                        maker_qty_pct, maker_notional_pct)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        target,
                        n,
                        avg_slip,
                        max_slip,
                        p95_slip,
                        maker_rate * 100,
                        total_fee,
                        alarm_triggered,
                        alarm_level,
                        entry_count,
                        exit_count,
                        unknown_count,
                        fee_unknown_count,
                        fee_unknown_count == 0,
                        maker_qty_pct,
                        maker_notional_pct,
                    ],
                )
                con.commit()
                con.close()

        return summary

    def tf_histogram(self, tf: str, days: int = 30) -> dict[str, Any]:
        """Belirli TF icin slippage histogram (son N gun).

        Returns:
            dict: {tf, n_fills, mean_bps, p50_bps, p95_bps, max_bps,
                   maker_fill_pct, budget_warning_bps, budget_critical_bps,
                   pct_over_warning, pct_over_critical}
        """
        days_int = int(days)
        with self._lock:
            con = duckdb.connect(str(self._path))
            rows = con.execute(
                f"""SELECT slippage_bps, is_maker, fill_role, quantity,
                          maker_quantity, notional_usdt, maker_notional_usdt
                   FROM fills
                   WHERE tf = ?
                     AND ts >= now() - INTERVAL '{days_int} days'
                   ORDER BY slippage_bps""",
                [tf],
            ).fetchall()
            con.close()

        if not rows:
            budget = TF_SLIPPAGE_BUDGET.get(tf, TF_SLIPPAGE_BUDGET["1d"])
            return {
                "tf": tf,
                "n_fills": 0,
                "mean_bps": 0.0,
                "p50_bps": 0.0,
                "p95_bps": 0.0,
                "max_bps": 0.0,
                "maker_fill_pct": 0.0,
                "entry_maker_fill_pct": 0.0,
                "entry_maker_order_pct": 0.0,
                "entry_maker_qty_pct": 0.0,
                "entry_maker_notional_pct": 0.0,
                "entry_fill_count": 0,
                "exit_fill_count": 0,
                "unknown_fill_count": 0,
                "budget_warning_bps": budget["warning"],
                "budget_critical_bps": budget["critical"],
                "pct_over_warning": 0.0,
                "pct_over_critical": 0.0,
            }

        import statistics

        slippages = [float(r[0]) for r in rows]
        entry_maker_flags = [bool(r[1]) for r in rows if str(r[2]) == "entry"]
        entry_count = len(entry_maker_flags)
        exit_count = sum(str(r[2]) == "exit" for r in rows)
        unknown_count = len(rows) - entry_count - exit_count
        entry_quantity = sum(float(r[3] or 0.0) for r in rows if str(r[2]) == "entry")
        entry_maker_quantity = sum(float(r[4] or 0.0) for r in rows if str(r[2]) == "entry")
        entry_notional = sum(float(r[5] or 0.0) for r in rows if str(r[2]) == "entry")
        entry_maker_notional = sum(float(r[6] or 0.0) for r in rows if str(r[2]) == "entry")
        n = len(slippages)
        entry_maker_pct = (
            round(sum(entry_maker_flags) / entry_count * 100, 1) if entry_count else 0.0
        )

        budget = TF_SLIPPAGE_BUDGET.get(tf, TF_SLIPPAGE_BUDGET["1d"])
        warn = budget["warning"]
        crit = budget["critical"]

        sorted_sl = sorted(slippages)
        p50 = sorted_sl[int(n * 0.50)]
        p95 = sorted_sl[int(n * 0.95)]

        return {
            "tf": tf,
            "n_fills": n,
            "mean_bps": round(statistics.mean(slippages), 2),
            "p50_bps": round(p50, 2),
            "p95_bps": round(p95, 2),
            "max_bps": round(max(slippages), 2),
            "maker_fill_pct": entry_maker_pct,
            "entry_maker_fill_pct": entry_maker_pct,
            "entry_maker_order_pct": entry_maker_pct,
            "entry_maker_qty_pct": (
                round(entry_maker_quantity / entry_quantity * 100, 1) if entry_quantity > 0 else 0.0
            ),
            "entry_maker_notional_pct": (
                round(entry_maker_notional / entry_notional * 100, 1) if entry_notional > 0 else 0.0
            ),
            "entry_fill_count": entry_count,
            "exit_fill_count": exit_count,
            "unknown_fill_count": unknown_count,
            "budget_warning_bps": warn,
            "budget_critical_bps": crit,
            "pct_over_warning": round(sum(s > warn for s in slippages) / n * 100, 1),
            "pct_over_critical": round(sum(s > crit for s in slippages) / n * 100, 1),
        }

    def get_recent_fills(self, days: int = 30) -> list[dict[str, Any]]:
        """Son N günün fill kayıtları."""
        with self._lock:
            con = duckdb.connect(str(self._path))
            rows = con.execute(
                f"""SELECT fill_id, ts, symbol, strategy, side,
                          slippage_bps, quantity, maker_quantity, notional_usdt,
                          maker_notional_usdt, fee_usdt, fee_bps, fee_source,
                          total_cost_bps, is_maker, fill_role, mode
                    FROM fills
                    WHERE ts >= now() - INTERVAL {int(days)} DAY
                    ORDER BY ts DESC""",
            ).fetchall()
            con.close()
        cols = [
            "fill_id",
            "ts",
            "symbol",
            "strategy",
            "side",
            "slippage_bps",
            "quantity",
            "maker_quantity",
            "notional_usdt",
            "maker_notional_usdt",
            "fee_usdt",
            "fee_bps",
            "fee_source",
            "total_cost_bps",
            "is_maker",
            "fill_role",
            "mode",
        ]
        return [dict(zip(cols, r, strict=False)) for r in rows]

    def _write_jsonl(self, ts: datetime, data: dict) -> None:
        """logs/execution/YYYY-MM-DD.jsonl'e sat yaz."""
        log_file = LOG_DIR / f"{ts.date()}.jsonl"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": ts.isoformat(), **data}) + "\n")
        except Exception:
            pass

    def weekly_summary(self, end_date: date | None = None, tf: str | None = None) -> dict[str, Any]:
        """Haftalık özet (son 7 gün) — slippage trend + outlier detection.

        FIX 2026-05-28 (Faz 14.27 C4): Önceden weekly raporlama yoktu.
        Bu metod: trend (vs önceki hafta), outlier fills (>p99), maker rate drift.
        """
        from datetime import timedelta as _td

        end = end_date or datetime.now(UTC).date()
        start = end - _td(days=7)
        prev_start = start - _td(days=7)
        tf_filter = " AND tf = ?" if tf else ""
        curr_params: list[Any] = [start, end]
        prev_params: list[Any] = [prev_start, start]
        if tf:
            curr_params.append(tf)
            prev_params.append(tf)

        with self._lock:
            con = duckdb.connect(str(self._path))
            # Bu hafta
            curr = con.execute(
                f"""SELECT
                     COUNT(*),
                     AVG(slippage_bps),
                     PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY slippage_bps),
                     PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY slippage_bps),
                     SUM(CASE WHEN fill_role = 'entry' THEN 1 ELSE 0 END),
                     SUM(CASE WHEN fill_role = 'exit' THEN 1 ELSE 0 END),
                     SUM(CASE WHEN coalesce(fill_role, 'unknown') NOT IN ('entry', 'exit')
                              THEN 1 ELSE 0 END),
                     SUM(CASE WHEN fill_role = 'entry' AND is_maker IS TRUE
                              THEN 1 ELSE 0 END) * 1.0
                         / NULLIF(SUM(CASE WHEN fill_role = 'entry' THEN 1 ELSE 0 END), 0),
                     SUM(CASE WHEN fill_role = 'entry' THEN quantity ELSE 0 END),
                     SUM(CASE WHEN fill_role = 'entry' THEN maker_quantity ELSE 0 END),
                     SUM(CASE WHEN fill_role = 'entry' THEN notional_usdt ELSE 0 END),
                     SUM(CASE WHEN fill_role = 'entry' THEN maker_notional_usdt ELSE 0 END),
                     SUM(fee_usdt),
                     SUM(CASE WHEN fee_usdt IS NOT NULL THEN 1 ELSE 0 END),
                     SUM(CASE WHEN fee_usdt IS NULL THEN 1 ELSE 0 END)
                   FROM fills
                   WHERE ts::DATE >= ? AND ts::DATE < ? {tf_filter}""",
                curr_params,
            ).fetchone()
            # Geçen hafta (comparison)
            prev = con.execute(
                f"""SELECT
                     COUNT(*),
                     AVG(slippage_bps),
                     SUM(CASE WHEN fill_role = 'entry' AND is_maker IS TRUE
                              THEN 1 ELSE 0 END) * 1.0
                         / NULLIF(SUM(CASE WHEN fill_role = 'entry' THEN 1 ELSE 0 END), 0)
                   FROM fills
                   WHERE ts::DATE >= ? AND ts::DATE < ? {tf_filter}""",
                prev_params,
            ).fetchone()
            # Outlier fills (this week, >p99)
            p99_threshold = float(curr[3] or 0)
            outlier_params: list[Any] = [start, end, p99_threshold]
            if tf:
                outlier_params.append(tf)
            outliers = con.execute(
                f"""SELECT symbol, strategy, side, slippage_bps, ts
                   FROM fills
                   WHERE ts::DATE >= ? AND ts::DATE < ? AND slippage_bps > ? {tf_filter}
                   ORDER BY slippage_bps DESC LIMIT 10""",
                outlier_params,
            ).fetchall()
            con.close()

        (
            n,
            avg_slip,
            p95,
            _p99,
            entry_count,
            exit_count,
            unknown_count,
            maker_rate,
            entry_quantity,
            entry_maker_quantity,
            entry_notional,
            entry_maker_notional,
            total_fee,
            fee_known_count,
            fee_unknown_count,
        ) = curr or (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        n_prev, avg_prev, maker_prev = prev or (0, 0, 0)
        n = int(n or 0)
        n_prev = int(n_prev or 0)
        entry_count = int(entry_count or 0)
        exit_count = int(exit_count or 0)
        unknown_count = int(unknown_count or 0)
        fee_known_count = int(fee_known_count or 0)
        fee_unknown_count = int(fee_unknown_count or 0)
        avg_slip = float(avg_slip or 0)
        avg_prev = float(avg_prev or 0)
        entry_quantity = float(entry_quantity or 0)
        entry_maker_quantity = float(entry_maker_quantity or 0)
        entry_notional = float(entry_notional or 0)
        entry_maker_notional = float(entry_maker_notional or 0)
        maker_qty_pct = entry_maker_quantity / entry_quantity * 100 if entry_quantity > 0 else 0.0
        maker_notional_pct = (
            entry_maker_notional / entry_notional * 100 if entry_notional > 0 else 0.0
        )
        slip_delta_bps = avg_slip - avg_prev
        slip_change_pct = (slip_delta_bps / avg_prev * 100) if avg_prev else None

        return {
            "week_end": end.isoformat(),
            "week_start": start.isoformat(),
            "tf": tf or "all",
            "current_week": {
                "n_fills": n,
                "avg_slippage_bps": round(avg_slip, 2),
                "p95_slippage_bps": round(float(p95 or 0), 2),
                "p99_slippage_bps": round(p99_threshold, 2),
                "maker_rate_pct": round(float(maker_rate or 0) * 100, 1),
                "entry_maker_rate_pct": round(float(maker_rate or 0) * 100, 1),
                "entry_maker_order_pct": round(float(maker_rate or 0) * 100, 1),
                "entry_maker_qty_pct": round(maker_qty_pct, 1),
                "entry_maker_notional_pct": round(maker_notional_pct, 1),
                "entry_fill_count": entry_count,
                "exit_fill_count": exit_count,
                "unknown_fill_count": unknown_count,
                "total_fee_usdt": round(float(total_fee or 0), 4),
                "fee_known_fill_count": fee_known_count,
                "fee_unknown_fill_count": fee_unknown_count,
                "total_fee_complete": fee_unknown_count == 0,
            },
            "vs_previous_week": {
                "n_fills_delta": n - n_prev,
                "avg_slippage_delta_bps": round(slip_delta_bps, 2),
                "avg_slippage_change_pct": (
                    round(slip_change_pct, 1) if slip_change_pct is not None else None
                ),
                "maker_rate_delta_pct": round(
                    (float(maker_rate or 0) - float(maker_prev or 0)) * 100, 1
                ),
            },
            "outlier_fills_top10": [
                {
                    "symbol": o[0],
                    "strategy": o[1],
                    "side": o[2],
                    "slippage_bps": round(float(o[3]), 2),
                    "ts": str(o[4]),
                }
                for o in outliers
            ],
        }

    def _alarm(self, level: str, msg: str) -> None:
        """Log + Telegram (varsa, throttled)."""
        import sys

        ts = datetime.now(UTC).strftime("%H:%M:%S")
        line = f"[{ts}][SLIPPAGE_{level}] {msg}"
        print(line, file=sys.stderr)
        # Telegram (optional, fail-safe, throttled)
        try:
            from price_action.ops import get_telegram_throttle

            throttle = get_telegram_throttle()
            # Determine alert_type based on level
            alert_type = "slippage_critical" if level == "CRITICAL" else "slippage_warning"
            throttle.send_throttled(alert_type, msg, level=level)
        except Exception:
            pass
