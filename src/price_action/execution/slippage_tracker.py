"""Slippage Tracker — Fill-level journal + günlük aggregat + alarmlar.

Her fill kayıt altına alınır:
  - expected_price (signal anındaki ref fiyat)
  - realized_price (exchange fill average)
  - slippage_bps, fee_bps, total_cost_bps
  - is_maker (post-only rebate)

Günlük aggregat:
  - Ortalama slippage, max, p95
  - Maker fill rate
  - >10 bps → WARNING alarm (Telegram + log)
  - >20 bps → CRITICAL alarm

Usage:
    tracker = SlippageTracker()
    tracker.record_fill(fill, strategy="engulfing_continuation")
    summary = tracker.daily_summary()
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DB = ROOT / "data" / "execution_fills.duckdb"
LOG_DIR = ROOT / "logs" / "execution"

ALARM_WARNING_BPS = 10.0   # günlük ortalama > bu değer → WARNING
ALARM_CRITICAL_BPS = 20.0  # günlük ortalama > bu değer → CRITICAL
SINGLE_FILL_MAX_BPS = 25.0  # tek fill > bu → zaten iptal (ccxt_live'da), ama log


class SlippageTracker:
    """Thread-safe fill journal ve slippage izleme."""

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
    ) -> float:
        """Fill'i kayıt altına al. Hesaplanan slippage_bps döndür.

        Yön düzeltmeli slippage:
          LONG: realized > expected = maliyet (pozitif)
          SHORT: realized < expected = maliyet (pozitif)
        """
        notional = quantity * realized_price
        if side == "long":
            slippage_bps = (realized_price - expected_price) / max(expected_price, 1e-10) * 10_000
        else:
            slippage_bps = (expected_price - realized_price) / max(expected_price, 1e-10) * 10_000

        fee_bps = fee_usdt / max(notional, 1e-10) * 10_000
        total_cost_bps = slippage_bps + fee_bps

        with self._lock:
            con = duckdb.connect(str(self._path))
            con.execute(
                """INSERT OR IGNORE INTO fills VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    fill_id, ts, symbol, strategy, side,
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
            "fill_id": fill_id, "symbol": symbol, "side": side,
            "slippage_bps": round(slippage_bps, 4),
            "fee_bps": round(fee_bps, 4),
            "total_cost_bps": round(total_cost_bps, 4),
            "is_maker": is_maker, "mode": mode,
        })

        # Tek fill alarm
        if slippage_bps > SINGLE_FILL_MAX_BPS:
            self._alarm(
                level="CRITICAL",
                msg=f"SINGLE_FILL_SLIPPAGE_EXCEEDED: {symbol} {slippage_bps:.1f}bps > {SINGLE_FILL_MAX_BPS}bps",
            )

        return slippage_bps

    def daily_summary(self, d: date | None = None) -> dict[str, Any]:
        """Günlük özet hesapla + alarm değerlendir."""
        target = d or date.today()
        with self._lock:
            con = duckdb.connect(str(self._path))
            row = con.execute(
                """SELECT
                     COUNT(*),
                     AVG(slippage_bps),
                     MAX(slippage_bps),
                     PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY slippage_bps),
                     SUM(CASE WHEN is_maker THEN 1 ELSE 0 END) * 1.0 / NULLIF(COUNT(*), 0),
                     SUM(fee_usdt)
                   FROM fills
                   WHERE ts::DATE = ?""",
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

        alarm_level = "OK"
        alarm_triggered = False
        if avg_slip > ALARM_CRITICAL_BPS:
            alarm_level = "CRITICAL"
            alarm_triggered = True
            self._alarm(
                level="CRITICAL",
                msg=f"DAILY_SLIPPAGE_CRITICAL: avg {avg_slip:.1f}bps > {ALARM_CRITICAL_BPS}bps ({n} fills)",
            )
        elif avg_slip > ALARM_WARNING_BPS:
            alarm_level = "WARNING"
            alarm_triggered = True
            self._alarm(
                level="WARNING",
                msg=f"DAILY_SLIPPAGE_WARNING: avg {avg_slip:.1f}bps > {ALARM_WARNING_BPS}bps ({n} fills)",
            )

        summary = {
            "date": target.isoformat(),
            "n_fills": n,
            "avg_slippage_bps": round(avg_slip, 2),
            "max_slippage_bps": round(max_slip, 2),
            "p95_slippage_bps": round(p95_slip, 2),
            "maker_fill_pct": round(maker_rate * 100, 1),
            "total_fee_usdt": round(total_fee, 4),
            "alarm_triggered": alarm_triggered,
            "alarm_level": alarm_level,
        }

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
