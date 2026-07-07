"""Perpetual orderbook snapshot logger — microstructure research module.

Hypothesis: perp-orderbook-imbalance (2026-05-09)
  Engulfing sinyal anında top-N orderbook derinliğini loglar ve
  bid/ask imbalance'ı hesaplar. Forward validation için 4 hafta veri biriktirir.

Tasarım ilkeleri:
  1. SAVUNMACI: Tüm ağ hataları sessizce yutulur — crash olmaz.
  2. LOOKAHEAD YOK: Snapshot her zaman sinyal anında çekilir (prospektif).
  3. GERİ UYUMLU: Tarihsel backtest için aynı compute_imbalance() fonksiyonu kullanılabilir.
  4. BAĞIMSIZ: Engulfing strategy'ye dokunmaz, paper_trading_loop.py'da opsiyonel hook.

Kullanım (paper_trading_loop.py'da defansif hook):
    try:
        from price_action.data.orderbook_logger import OrderbookLogger
        ob_logger = OrderbookLogger()
        ob_logger.log_signal_orderbook(
            signal_info=signal_info,
            exchange=exchange,
            top_n=5,
        )
    except Exception:
        pass  # orderbook logging opsiyonel — crash olmaz

CLI sorgu:
    python -c "
    from price_action.data.orderbook_logger import OrderbookLogger
    l = OrderbookLogger()
    print(l.query_recent(limit=10))
    "
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from price_action.logging_config import logger

# ---------------------------------------------------------------------------
# Pydantic model (optional import — graceful fallback if pydantic unavailable)
# ---------------------------------------------------------------------------
try:
    from pydantic import BaseModel, ConfigDict

    class OrderbookSnapshot(BaseModel):
        """Tek bir orderbook snapshot — forward validation + eventual backtest için."""

        model_config = ConfigDict(frozen=True)

        snapshot_id: str
        ts: datetime  # snapshot çekildiği zaman (UTC)
        signal_ts: datetime | None  # engulfing bar kapanış ts'i
        venue: str
        symbol: str
        direction: str | None  # sinyal yönü: 'long' | 'short'
        top_n: int  # kaç seviye kullanıldı
        bid_volume: float  # top_n seviyenin toplam bid hacmi
        ask_volume: float  # top_n seviyenin toplam ask hacmi
        imbalance: float  # (bid - ask) / (bid + ask), [-1, +1]
        raw_bids: list[list[float]]  # [[price, size], ...]
        raw_asks: list[list[float]]
        signal_id: str | None  # paper trade fingerprint
        pattern_id: str | None
        confidence: float | None
        fetch_latency_ms: float  # REST round-trip ms

    _PYDANTIC_AVAILABLE = True

except ImportError:  # pragma: no cover
    OrderbookSnapshot = None  # type: ignore[misc,assignment]
    _PYDANTIC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Pure computation — no I/O, testable without exchange
# ---------------------------------------------------------------------------


def compute_imbalance(
    bids: list[list[float]],
    asks: list[list[float]],
    top_n: int = 5,
) -> float:
    """Orderbook imbalance hesapla.

    Harris (2003) microstructure formülü:
        imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)

    Değer aralığı: [-1.0, +1.0]
        +1.0 → tüm likidite bid tarafında (güçlü alım baskısı)
        -1.0 → tüm likidite ask tarafında (güçlü satım baskısı)
         0.0 → dengeli orderbook

    Args:
        bids: [[price, size], ...] — fiyata göre azalan sıra (en iyi bid başta)
        asks: [[price, size], ...] — fiyata göre artan sıra (en iyi ask başta)
        top_n: kaç seviye kullanılacak (default 5)

    Returns:
        float in [-1.0, +1.0]. Kitap boşsa veya toplam sıfırsa 0.0 döner.

    Edge cases:
        - Boş kitap ([] bids veya asks) → 0.0
        - top_n > mevcut seviyeleri → mevcut seviyeleri kullan
        - Sıfır hacim → 0.0 (div-by-zero koruması)
    """
    bid_levels = bids[:top_n] if bids else []
    ask_levels = asks[:top_n] if asks else []

    bid_vol = sum(float(lvl[1]) for lvl in bid_levels if len(lvl) >= 2)
    ask_vol = sum(float(lvl[1]) for lvl in ask_levels if len(lvl) >= 2)

    total = bid_vol + ask_vol
    if total <= 0.0:
        return 0.0

    return (bid_vol - ask_vol) / total


def is_imbalance_aligned(imbalance: float, direction: str, threshold: float = 0.6) -> bool:
    """Imbalance sinyalin yönüyle uyumlu mu?

    Args:
        imbalance: compute_imbalance() çıktısı, [-1, +1]
        direction: 'long' veya 'short'
        threshold: |imbalance| için minimum eşik (default 0.6)

    Returns:
        True → yüksek conviction (imbalance aynı yönde ve eşiği aşıyor)
        False → düşük conviction veya karşı yönde
    """
    if direction == "long":
        return imbalance >= threshold
    elif direction == "short":
        return imbalance <= -threshold
    return False


# ---------------------------------------------------------------------------
# Fetch — live REST, defensive
# ---------------------------------------------------------------------------


def fetch_orderbook_snapshot(
    symbol: str,
    venue: str = "binance",
    limit: int = 20,
    exchange: Any = None,
) -> dict[str, Any] | None:
    """Orderbook snapshot çek (ccxt REST).

    Args:
        symbol: CCXT unified symbol, örn 'BTC/USDT' veya 'BTC/USDT:USDT'
        venue: ccxt exchange adı (default 'binance')
        limit: kaç seviye isteniyor (ücretsiz, 20 Binance default)
        exchange: mevcut ccxt exchange nesnesi (None ise yeni oluşturulur)

    Returns:
        {'bids': [[price, size], ...], 'asks': [[price, size], ...], 'latency_ms': float}
        veya None (herhangi bir hata durumunda)
    """
    _log = logger.bind(component="orderbook_logger", symbol=symbol, venue=venue)

    ex = exchange
    if ex is None:
        try:
            import ccxt  # type: ignore

            kls = getattr(ccxt, venue, None)
            if kls is None:
                _log.warning("orderbook_logger.venue_not_found")
                return None
            ex = kls({"enableRateLimit": True})
        except ImportError:
            _log.warning("orderbook_logger.ccxt_not_installed")
            return None
        except Exception as exc:
            _log.bind(err=str(exc)).warning("orderbook_logger.exchange_init_fail")
            return None

    t0 = time.monotonic()
    try:
        raw = ex.fetch_order_book(symbol, limit=limit)
        latency_ms = (time.monotonic() - t0) * 1000.0
        return {
            "bids": raw.get("bids", []),
            "asks": raw.get("asks", []),
            "latency_ms": round(latency_ms, 2),
        }
    except Exception as exc:
        _log.bind(err=str(exc)).warning("orderbook_logger.fetch_fail")
        return None


# ---------------------------------------------------------------------------
# DuckDB storage
# ---------------------------------------------------------------------------

_ORDERBOOK_DDL = """
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    snapshot_id       TEXT PRIMARY KEY,
    ts                TIMESTAMP WITH TIME ZONE NOT NULL,
    signal_ts         TIMESTAMP WITH TIME ZONE,
    venue             TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    direction         TEXT,
    top_n             INTEGER,
    bid_volume        DOUBLE,
    ask_volume        DOUBLE,
    imbalance         DOUBLE,
    raw_bids          TEXT,
    raw_asks          TEXT,
    signal_id         TEXT,
    pattern_id        TEXT,
    confidence        DOUBLE,
    fetch_latency_ms  DOUBLE
);
"""


class OrderbookLogger:
    """Orderbook snapshot loglayıcı — DuckDB kalıcı depo.

    Paper trading loop'una defansif olarak takılır. Her engulfing sinyali
    tetiklendiğinde çağrılır. Herhangi bir hata durumunda sessizce geçer.

    Örnek kullanım:
        ob_logger = OrderbookLogger()
        ob_logger.log_signal_orderbook(
            signal_info={"symbol": "BTC/USDT", "direction": "long", ...},
            exchange=ccxt_exchange_object,
            top_n=5,
        )
    """

    def __init__(
        self,
        db_path: Path | None = None,
        top_n_default: int = 5,
    ) -> None:
        if db_path is None:
            _root = (
                Path(__file__).resolve().parents[3]
            )  # G24-fix 2026-07-07: parents[4] repo dışıydı
            db_path = _root / "data" / "orderbook_snapshots.duckdb"
        self.db_path = db_path
        self.top_n_default = top_n_default
        self._log = logger.bind(component="orderbook_logger")
        self._init_db()

    # ----- DB setup -----

    def _get_conn(self) -> Any | None:
        """DuckDB bağlantısı — her çağrıda yeni bağlantı (Windows DuckDB safety)."""
        try:
            import duckdb  # type: ignore

            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            return duckdb.connect(str(self.db_path))
        except ImportError:
            self._log.warning("orderbook_logger.duckdb_not_installed")
            return None
        except Exception as exc:
            self._log.bind(err=str(exc)).warning("orderbook_logger.db_connect_fail")
            return None

    def _init_db(self) -> None:
        conn = self._get_conn()
        if conn is None:
            return
        try:
            conn.execute(_ORDERBOOK_DDL)
            conn.close()
        except Exception as exc:
            self._log.bind(err=str(exc)).warning("orderbook_logger.db_init_fail")

    # ----- Core public API -----

    def log_signal_orderbook(
        self,
        signal_info: dict[str, Any],
        exchange: Any = None,
        top_n: int | None = None,
    ) -> OrderbookSnapshot | None:
        """Sinyal anında orderbook snapshot çek ve logla.

        Args:
            signal_info: paper_trading_loop'tan gelen sinyal dict'i. Beklenen anahtarlar:
                - symbol (str)
                - direction ('long' | 'short')
                - bar_ts (str ISO veya datetime)
                - pattern_id (str, opsiyonel)
                - confidence (float, opsiyonel)
                - trade_id (str, opsiyonel — sinyal fingerprint olarak kullanılır)
            exchange: mevcut ccxt exchange nesnesi (None → yeni oluşturulur)
            top_n: kaç seviye imbalance hesabında kullanılacak (None → self.top_n_default)

        Returns:
            OrderbookSnapshot nesnesi (loglandı), veya None (herhangi bir hata)
        """
        if top_n is None:
            top_n = self.top_n_default

        symbol = signal_info.get("symbol", "")
        direction = signal_info.get("direction")
        pattern_id = signal_info.get("pattern_id")
        confidence = signal_info.get("confidence")
        signal_id = signal_info.get("trade_id")

        # bar_ts → datetime
        signal_ts = None
        bar_ts_raw = signal_info.get("bar_ts")
        if bar_ts_raw:
            try:
                if isinstance(bar_ts_raw, str):
                    from datetime import datetime

                    signal_ts = datetime.fromisoformat(bar_ts_raw.replace("Z", "+00:00"))
                elif isinstance(bar_ts_raw, datetime):
                    signal_ts = bar_ts_raw
            except Exception:
                pass

        # Fetch
        venue = signal_info.get("venue", "binance")
        raw = fetch_orderbook_snapshot(
            symbol=symbol,
            venue=venue,
            limit=max(top_n * 2, 20),
            exchange=exchange,
        )

        if raw is None:
            self._log.bind(symbol=symbol).warning("orderbook_logger.snapshot_fetch_failed — skip")
            return None

        bids = raw["bids"]
        asks = raw["asks"]
        latency_ms = raw["latency_ms"]

        # Compute
        bid_vol = sum(float(lvl[1]) for lvl in bids[:top_n] if len(lvl) >= 2)
        ask_vol = sum(float(lvl[1]) for lvl in asks[:top_n] if len(lvl) >= 2)
        imbalance = compute_imbalance(bids, asks, top_n=top_n)
        aligned = (
            is_imbalance_aligned(imbalance, direction or "", threshold=0.6) if direction else False
        )

        snapshot_id = uuid.uuid4().hex[:20]
        now_utc = datetime.now(UTC)

        self._log.bind(
            symbol=symbol,
            direction=direction,
            imbalance=round(imbalance, 4),
            aligned=aligned,
            latency_ms=latency_ms,
        ).info("orderbook_logger.snapshot_captured")

        # Persist
        conn = self._get_conn()
        if conn is not None:
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO orderbook_snapshots
                       (snapshot_id, ts, signal_ts, venue, symbol, direction,
                        top_n, bid_volume, ask_volume, imbalance,
                        raw_bids, raw_asks, signal_id, pattern_id, confidence,
                        fetch_latency_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        snapshot_id,
                        now_utc,
                        signal_ts,
                        venue,
                        symbol,
                        direction,
                        top_n,
                        bid_vol,
                        ask_vol,
                        imbalance,
                        json.dumps(bids[:top_n]),
                        json.dumps(asks[:top_n]),
                        signal_id,
                        pattern_id,
                        confidence,
                        latency_ms,
                    ],
                )
                conn.close()
            except Exception as exc:
                self._log.bind(err=str(exc)).warning("orderbook_logger.db_write_fail")

        # Build snapshot object (if pydantic available)
        if _PYDANTIC_AVAILABLE:
            try:
                return OrderbookSnapshot(
                    snapshot_id=snapshot_id,
                    ts=now_utc,
                    signal_ts=signal_ts,
                    venue=venue,
                    symbol=symbol,
                    direction=direction,
                    top_n=top_n,
                    bid_volume=bid_vol,
                    ask_volume=ask_vol,
                    imbalance=imbalance,
                    raw_bids=bids[:top_n],
                    raw_asks=asks[:top_n],
                    signal_id=signal_id,
                    pattern_id=pattern_id,
                    confidence=confidence,
                    fetch_latency_ms=latency_ms,
                )
            except Exception:
                pass

        return None

    def query_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Son N snapshot'ı döndür (analiz için)."""
        conn = self._get_conn()
        if conn is None:
            return []
        try:
            rows = conn.execute(
                """SELECT snapshot_id, ts, symbol, direction, imbalance,
                          bid_volume, ask_volume, confidence, pattern_id,
                          fetch_latency_ms
                   FROM orderbook_snapshots
                   ORDER BY ts DESC
                   LIMIT ?""",
                [limit],
            ).fetchall()
            conn.close()
            cols = [
                "snapshot_id",
                "ts",
                "symbol",
                "direction",
                "imbalance",
                "bid_volume",
                "ask_volume",
                "confidence",
                "pattern_id",
                "fetch_latency_ms",
            ]
            return [dict(zip(cols, row, strict=False)) for row in rows]
        except Exception as exc:
            self._log.bind(err=str(exc)).warning("orderbook_logger.query_fail")
            return []

    def correlation_summary(self) -> dict[str, Any]:
        """İmbalance alignment ile trade count özeti — forward validation analizi.

        Returns:
            {
                "total_snapshots": int,
                "aligned_count": int,       # |imbalance| > 0.6 AND same direction
                "misaligned_count": int,    # |imbalance| > 0.6 AND opposite direction
                "neutral_count": int,       # |imbalance| <= 0.6
                "avg_imbalance_aligned": float,
                "avg_imbalance_all": float,
            }
        """
        conn = self._get_conn()
        if conn is None:
            return {}
        try:
            row = conn.execute(
                """SELECT
                       COUNT(*) AS total,
                       SUM(CASE
                           WHEN (direction='long'  AND imbalance >= 0.6) OR
                                (direction='short' AND imbalance <= -0.6)
                           THEN 1 ELSE 0 END) AS aligned,
                       SUM(CASE
                           WHEN (direction='long'  AND imbalance <= -0.6) OR
                                (direction='short' AND imbalance >= 0.6)
                           THEN 1 ELSE 0 END) AS misaligned,
                       SUM(CASE
                           WHEN ABS(imbalance) <= 0.6
                           THEN 1 ELSE 0 END) AS neutral,
                       AVG(CASE
                           WHEN (direction='long'  AND imbalance >= 0.6) OR
                                (direction='short' AND imbalance <= -0.6)
                           THEN ABS(imbalance) END) AS avg_imbalance_aligned,
                       AVG(ABS(imbalance)) AS avg_imbalance_all
                   FROM orderbook_snapshots
                   WHERE direction IS NOT NULL"""
            ).fetchone()
            conn.close()
            if row is None:
                return {}
            return {
                "total_snapshots": row[0] or 0,
                "aligned_count": row[1] or 0,
                "misaligned_count": row[2] or 0,
                "neutral_count": row[3] or 0,
                "avg_imbalance_aligned": round(float(row[4] or 0.0), 4),
                "avg_imbalance_all": round(float(row[5] or 0.0), 4),
            }
        except Exception as exc:
            self._log.bind(err=str(exc)).warning("orderbook_logger.summary_fail")
            return {}
