"""Slippage Tracker — Fill-level journal + günlük aggregat + alarmlar.

Her fill kayıt altına alınır:
  - expected_price (signal anındaki ref fiyat)
  - realized_price (exchange fill average)
  - slippage_bps, fee_bps, total_cost_bps
  - is_maker (post-only rebate)
  - tf (timeframe bucket: "1m", "5m", "15m", "1h", "1d")

Günlük aggregat:
  - Ortalama slippage, max, p95 — hem global hem TF-bucket bazlı
  - Maker fill rate
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

import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[3]  # G24 fix: Price Action kökü (eskiden parents[4]=projeler — proje dışı)
DEFAULT_DB = ROOT / "data" / "execution_fills.duckdb"
LOG_DIR = ROOT / "logs" / "execution"

# Legacy (1d) defaults
ALARM_WARNING_BPS = 10.0
ALARM_CRITICAL_BPS = 20.0
SINGLE_FILL_MAX_BPS = 25.0

# TF-spesifik slippage budget (bps)
TF_SLIPPAGE_BUDGET: dict[str, dict[str, float]] = {
    "1m":  {"warning": 10.0, "critical": 20.0, "single_max": 15.0},
    "5m":  {"warning": 12.0, "critical": 24.0, "single_max": 18.0},
    "15m": {"warning": 15.0, "critical": 30.0, "single_max": 22.0},
    "1h":  {"warning": 20.0, "critical": 40.0, "single_max": 25.0},
    "4h":  {"warning": 20.0, "critical": 40.0, "single_max": 25.0},
    "1d":  {"warning": 10.0, "critical": 20.0, "single_max": 25.0},
}


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
        """)
        # Idempotent migration: tf column eski DB'lerde yoksa ekle.
        # Pyramid leg-2 slippage record FAIL (table fills has 19 columns but 20 values) → A1 fix.
        existing_cols = {row[0] for row in con.execute("DESCRIBE fills").fetchall()}
        if "tf" not in existing_cols:
            con.execute("ALTER TABLE fills ADD COLUMN tf VARCHAR DEFAULT '1d'")
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
                alarm_level VARCHAR
            )
        """)
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
        fee_usdt: float,
        is_maker: bool,
        order_type: str,
        mode: str,
        exchange_order_id: str = "",
        client_order_id: str = "",
        notes: str = "",
        tf: str = "1d",
        fill_type: str = "entry",
    ) -> float:
        """Fill'i kayıt altına al. Hesaplanan slippage_bps döndür.

        Yön düzeltmeli slippage:
          LONG: realized > expected = maliyet (pozitif)
          SHORT: realized < expected = maliyet (pozitif)

        Args:
            tf: Timeframe bucket ("1m", "5m", "15m", "1h", "4h", "1d").
                TF-bazlı slippage budget eşiklerini seçer.
            fill_type: Fill türü — "entry" | "tp" | "sl" | "tp1" | "tp2" | "pyramid".
                notes alanına eklenir; Batch D daemon fill noktasını etiketlemek için.
                Mevcut çağrılar etkilenmez (default "entry").

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
        if notes:
            notes = f"{_type_prefix} {notes}"
        else:
            notes = _type_prefix
        notional = quantity * realized_price
        if side == "long":
            slippage_bps = (realized_price - expected_price) / max(expected_price, 1e-10) * 10_000
        else:
            slippage_bps = (expected_price - realized_price) / max(expected_price, 1e-10) * 10_000

        fee_bps = fee_usdt / max(notional, 1e-10) * 10_000
        total_cost_bps = slippage_bps + fee_bps

        with self._lock:
            con = duckdb.connect(str(self._path))
            # Explicit column names: ALTER TABLE migration sonrası `tf` col tablonun
            # sonuna ekleniyor → positional INSERT yanlış kolona yazıyordu (A1 root cause).
            con.execute(
                """INSERT OR IGNORE INTO fills
                   (fill_id, ts, symbol, strategy, side, tf,
                    expected_price, realized_price, quantity, notional_usdt,
                    slippage_bps, fee_usdt, fee_bps, total_cost_bps,
                    is_maker, order_type, mode,
                    exchange_order_id, client_order_id, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    fill_id, ts, symbol, strategy, side, tf,
                    expected_price, realized_price, quantity, notional,
                    round(slippage_bps, 4), fee_usdt, round(fee_bps, 4),
                    round(total_cost_bps, 4), is_maker, order_type, mode,
                    exchange_order_id, client_order_id, notes,
                ],
            )
            con.commit()
            con.close()

        # JSONL log
        self._write_jsonl(ts, {
            "fill_id": fill_id, "symbol": symbol, "side": side, "tf": tf,
            "slippage_bps": round(slippage_bps, 4),
            "fee_bps": round(fee_bps, 4),
            "total_cost_bps": round(total_cost_bps, 4),
            "is_maker": is_maker, "mode": mode,
        })

        # TF-bazlı tek fill alarm
        budget = TF_SLIPPAGE_BUDGET.get(tf, TF_SLIPPAGE_BUDGET["1d"])
        single_max = budget["single_max"]
        if slippage_bps > single_max:
            self._alarm(
                level="CRITICAL",
                msg=(
                    f"SINGLE_FILL_SLIPPAGE_EXCEEDED [{tf}]: "
                    f"{symbol} {slippage_bps:.1f}bps > {single_max}bps"
                ),
            )

        return slippage_bps

    def daily_summary(self, d: date | None = None, tf: str | None = None) -> dict[str, Any]:
        """Günlük özet hesapla + alarm değerlendir.

        Args:
            d: Tarih (default: bugün).
            tf: Filtre TF (None = tüm TF'ler, global özet).
        """
        target = d or date.today()
        tf_filter = f"AND tf = '{tf}'" if tf else ""

        with self._lock:
            con = duckdb.connect(str(self._path))
            row = con.execute(
                f"""SELECT
                     COUNT(*),
                     AVG(slippage_bps),
                     MAX(slippage_bps),
                     PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY slippage_bps),
                     SUM(CASE WHEN is_maker THEN 1 ELSE 0 END) * 1.0 / NULLIF(COUNT(*), 0),
                     SUM(fee_usdt)
                   FROM fills
                   WHERE ts::DATE = ? {tf_filter}""",
                [target],
            ).fetchone()
            con.close()

        n, avg_slip, max_slip, p95_slip, maker_rate, total_fee = row or (0, 0, 0, 0, 0, 0)
        n = int(n or 0)
        avg_slip = float(avg_slip or 0)
        max_slip = float(max_slip or 0)
        p95_slip = float(p95_slip or 0)
        maker_rate = float(maker_rate or 0)
        total_fee = float(total_fee or 0)

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
            "total_fee_usdt": round(total_fee, 4),
            "alarm_triggered": alarm_triggered,
            "alarm_level": alarm_level,
        }

        if tf is None:
            # Global özet → DB'ye kaydet
            with self._lock:
                con = duckdb.connect(str(self._path))
                con.execute(
                    """INSERT OR REPLACE INTO daily_slippage_summary VALUES
                       (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        target, n, avg_slip, max_slip, p95_slip,
                        maker_rate * 100, total_fee, alarm_triggered, alarm_level,
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
                f"""SELECT slippage_bps, is_maker
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
                "tf": tf, "n_fills": 0,
                "mean_bps": 0.0, "p50_bps": 0.0, "p95_bps": 0.0, "max_bps": 0.0,
                "maker_fill_pct": 0.0,
                "budget_warning_bps": budget["warning"],
                "budget_critical_bps": budget["critical"],
                "pct_over_warning": 0.0, "pct_over_critical": 0.0,
            }

        import statistics
        slippages = [float(r[0]) for r in rows]
        is_maker_flags = [bool(r[1]) for r in rows]
        n = len(slippages)

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
            "maker_fill_pct": round(sum(is_maker_flags) / n * 100, 1),
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
                          slippage_bps, fee_bps, total_cost_bps, is_maker, mode
                    FROM fills
                    WHERE ts >= now() - INTERVAL {int(days)} DAY
                    ORDER BY ts DESC""",
            ).fetchall()
            con.close()
        cols = ["fill_id", "ts", "symbol", "strategy", "side",
                "slippage_bps", "fee_bps", "total_cost_bps", "is_maker", "mode"]
        return [dict(zip(cols, r)) for r in rows]

    def _write_jsonl(self, ts: datetime, data: dict) -> None:
        """logs/execution/YYYY-MM-DD.jsonl'e sat yaz."""
        import json
        log_file = LOG_DIR / f"{ts.date()}.jsonl"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": ts.isoformat(), **data}) + "\n")
        except Exception:
            pass

    def _alarm(self, level: str, msg: str) -> None:
        """Log + Telegram (varsa, throttled)."""
        import sys
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
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
