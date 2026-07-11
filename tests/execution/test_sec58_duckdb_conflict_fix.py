"""SEC58 CRIT-2 — DuckDB connection conflict fix testleri.

Root cause: build_returns_df() her çağrıda duckdb.connect(read_only=True) açıyordu.
Windows DuckDB 1.5.2: aynı DB dosyasına farklı config (R/W vs read_only) ile
ikinci connection → "Connection Error: Can't open a connection to same database
file with a different configuration than existing connections".

Fix: OHLCVStore singleton pool (R/W, RLock-guarded) üzerinden oku.

Test senaryoları:
  T1: OHLCVStore pool singleton: aynı path için tek connection
  T2: build_returns_df() R/W singleton açıkken conflict yok
  T3: 8 sembol paralel build_returns_df() → 0 connection error
  T4: Parity — fix sonrası returns_df eski sonuçla aynı
  T5: Boş sembol listesi → boş DataFrame (backward compat)
  T6: Bilinmeyen sembol → boş DataFrame (konservatif, crash yok)
  T7: OHLCVStore pool R/W → read_only=False, conflict undefined
  T8: market_db parametresi injection (test fixture için)
"""

from __future__ import annotations

import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.lib.risk_integration as risk_integration  # noqa: E402
from price_action.data.store import OHLCVStore, reset_store_pool  # noqa: E402
from scripts.lib.risk_integration import (  # noqa: E402
    build_returns_df,
    reset_returns_df_cache,
)

# =====================================================================
# Fixture: geçici market.duckdb (veri dolu)
# =====================================================================

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "DOT/USDT",
]
VENUE = "binance"
TF = "1d"
N_DAYS = 100  # 90+5 buffer aşacak kadar


def _make_test_db(tmp_path: Path) -> Path:
    """tmp_path içinde ohlcv verisi dolu geçici market.duckdb yarat.

    Veri güncel tarihlerden geriye doğru oluşturulur (now() - INTERVAL X DAY
    sorgusunun fixture verisiyle eşleşmesi için).
    """
    db = tmp_path / "market.duckdb"
    store = OHLCVStore(duckdb_path=db)
    rows = []
    # Bugünden geriye N_DAYS gün: now() - 95 gün sorgusuna girsin
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    rng = np.random.default_rng(42)
    for sym in SYMBOLS:
        price = 1000.0
        for i in range(N_DAYS, 0, -1):
            ts = today - timedelta(days=i)
            price *= 1 + rng.normal(0, 0.02)
            rows.append(
                {
                    "venue": VENUE,
                    "symbol": sym,
                    "timeframe": TF,
                    "ts": ts,
                    "open": price * 0.99,
                    "high": price * 1.01,
                    "low": price * 0.98,
                    "close": price,
                    "volume": rng.uniform(1e6, 1e7),
                }
            )
    df = pd.DataFrame(rows)
    store.upsert(df, also_parquet=False)
    reset_store_pool()  # cleanup fixture connection, tests açar
    return db


@pytest.fixture
def market_db(tmp_path):
    """Veri dolu geçici market.duckdb fixture."""
    reset_store_pool()
    db = _make_test_db(tmp_path)
    yield db
    reset_store_pool()


@pytest.fixture(autouse=True)
def _clean_returns_cache():
    reset_returns_df_cache()
    yield
    reset_returns_df_cache()


# =====================================================================
# T1: OHLCVStore pool singleton — aynı path = tek connection
# =====================================================================


class TestOHLCVStorePoolSingleton:
    """OHLCVStore._CONN_POOL path başına tek connection tutar."""

    def test_same_path_returns_same_connection(self, market_db):
        from price_action.data.store import _get_pooled_connection

        reset_store_pool()
        path = str(market_db)
        con1, _ = _get_pooled_connection(path)
        con2, _ = _get_pooled_connection(path)
        assert con1 is con2, "Aynı path için pool farklı connection döndürdü"
        reset_store_pool()

    def test_different_paths_different_connections(self, tmp_path):
        from price_action.data.store import _get_pooled_connection

        reset_store_pool()
        db_a = tmp_path / "a.duckdb"
        db_b = tmp_path / "b.duckdb"
        # İkisi de yoksa duckdb.connect create eder
        con_a, _ = _get_pooled_connection(str(db_a))
        con_b, _ = _get_pooled_connection(str(db_b))
        assert con_a is not con_b
        reset_store_pool()


# =====================================================================
# T2: build_returns_df() R/W singleton açıkken conflict yok
# =====================================================================


class TestBuildReturnsDfNoConflict:
    """Mevcut R/W connection varken build_returns_df() patlamamalı."""

    def test_no_exception_with_rw_singleton_open(self, market_db):
        """R/W pool açıkken build_returns_df() aynı DB'yi okuyabilmeli."""
        # R/W singleton pool'u aç (OHLCVStore init eder)
        OHLCVStore(duckdb_path=market_db)
        # Şimdi build_returns_df() aynı path'e okuma yapsın
        result = build_returns_df(
            ["BTC/USDT", "ETH/USDT"],
            days=90,
            market_db=market_db,
        )
        # Çakışma olmadı; sonuç DataFrame (boş değil)
        assert isinstance(result, pd.DataFrame)
        assert not result.empty, "Veri dolu DB'den boş returns_df geldi"
        reset_store_pool()

    def test_old_read_only_would_conflict(self, market_db):
        """Windows DuckDB: R/W açıkken read_only=True → conflict (referans test)."""
        # Pool'u R/W ile aç
        con_rw = duckdb.connect(str(market_db))
        try:
            try:
                con_ro = duckdb.connect(str(market_db), read_only=True)
                con_ro.close()
                # Bazı platformlarda (Linux) conflict olmayabilir — test skip
                pytest.skip("Bu platformda DuckDB R/W + read_only conflict üretmiyor")
            except Exception as e:
                assert "different configuration" in str(e) or "Can't open" in str(
                    e
                ), f"Beklenmedik hata: {e}"
        finally:
            con_rw.close()


# =====================================================================
# T3: 8 sembol paralel build_returns_df() → 0 connection error
# =====================================================================


class TestParallelBuildReturnsDF:
    """8 thread paralel build_returns_df() — Windows lock conflict yok."""

    def test_8_symbols_parallel_no_conflict(self, market_db):
        errors: list[str] = []
        results: list[pd.DataFrame] = []
        lock = threading.Lock()

        def _call(sym: str):
            try:
                df = build_returns_df(
                    [sym],
                    days=90,
                    market_db=market_db,
                )
                with lock:
                    results.append(df)
            except Exception as exc:
                with lock:
                    errors.append(f"{sym}: {exc}")

        threads = [threading.Thread(target=_call, args=(s,)) for s in SYMBOLS]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert errors == [], f"Connection error(lar): {errors}"
        assert len(results) == len(SYMBOLS), f"Beklenen {len(SYMBOLS)} sonuç, gelen {len(results)}"
        assert all(isinstance(r, pd.DataFrame) for r in results)
        reset_store_pool()

    def test_all_symbols_single_call_no_conflict(self, market_db):
        """Tüm semboller tek çağrıda — no conflict."""
        result = build_returns_df(
            SYMBOLS,
            days=90,
            market_db=market_db,
        )
        assert isinstance(result, pd.DataFrame)
        assert not result.empty
        # Dönen columns semboller
        for sym in SYMBOLS:
            assert sym in result.columns, f"{sym} returns_df'de yok"
        reset_store_pool()


# =====================================================================
# T4: Parity — fix sonrası returns_df doğru değerleri üretir
# =====================================================================


class TestReturnsDfParity:
    """build_returns_df() matematiksel parity kontrolü."""

    def test_log_returns_shape(self, market_db):
        """91 exact close, 8 sembol → exact (90, 8) return matrix."""
        result = build_returns_df(
            SYMBOLS,
            days=90,
            market_db=market_db,
        )
        assert result.shape[1] == len(SYMBOLS), "Kolon sayısı sembol sayısına eşit olmalı"
        assert result.shape[0] == 90, "Tam 90 UTC günlük return zorunlu"

    def test_log_returns_finite(self, market_db):
        """Tüm değerler finite (NaN/Inf yok)."""
        result = build_returns_df(
            SYMBOLS,
            days=90,
            market_db=market_db,
        )
        assert np.isfinite(result.values).all(), "NaN veya Inf değer var"

    def test_parity_manual_log_returns(self, market_db):
        """Manuel hesap ile uyuşmalı (rounding toleransı ± 1e-10)."""
        # OHLCVStore ile ham close'ları çek
        store = OHLCVStore(duckdb_path=market_db)
        with store._conn() as con:
            rows = con.execute(
                """
                SELECT symbol, ts, close FROM ohlcv
                WHERE venue='binance' AND timeframe='1d'
                  AND symbol IN ('BTC/USDT', 'ETH/USDT')
                ORDER BY symbol, ts
                """
            ).fetchall()
        reset_store_pool()

        df_raw = pd.DataFrame(rows, columns=["symbol", "ts", "close"])
        pivot = df_raw.pivot(index="ts", columns="symbol", values="close").sort_index()
        expected = np.log(pivot / pivot.shift(1)).dropna(how="all").tail(90)

        result = build_returns_df(
            ["BTC/USDT", "ETH/USDT"],
            days=90,
            market_db=market_db,
        )

        # Index ve değer parity
        pd.testing.assert_frame_equal(
            result[["BTC/USDT", "ETH/USDT"]].reset_index(drop=True),
            expected[["BTC/USDT", "ETH/USDT"]].reset_index(drop=True),
            check_like=True,
            atol=1e-10,
        )
        reset_store_pool()


# =====================================================================
# T5: Boş sembol listesi → boş DataFrame
# =====================================================================


class TestEdgeCases:
    """Backward compat edge case'ler."""

    def test_empty_symbols_returns_empty_df(self, market_db):
        result = build_returns_df([], days=90, market_db=market_db)
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_unknown_symbol_returns_empty_df(self, market_db):
        """DB'de olmayan sembol → boş DataFrame (crash yok)."""
        result = build_returns_df(
            ["UNKNOWN/USDT"],
            days=90,
            market_db=market_db,
        )
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_nonexistent_db_returns_empty_df(self, tmp_path):
        """DB dosyası yoksa boş DataFrame — OHLCVStore yaratır ama veri yok."""
        fake_db = tmp_path / "nonexistent.duckdb"
        result = build_returns_df(
            ["BTC/USDT"],
            days=90,
            market_db=fake_db,
        )
        assert isinstance(result, pd.DataFrame)
        assert result.empty
        reset_store_pool()

    def test_days_param_truncates_result(self, market_db):
        """days=30 → exact 30 row döner."""
        result = build_returns_df(
            SYMBOLS,
            days=30,
            market_db=market_db,
        )
        assert result.shape[0] == 30
        reset_store_pool()

    def test_missing_required_calendar_day_fails_closed(self, market_db):
        """90 finite satırı daha eski günden tamamlamak yasaktır."""
        store = OHLCVStore(duckdb_path=market_db)
        missing_ts = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=10)
        with store._conn() as con:
            con.execute(
                "DELETE FROM ohlcv WHERE symbol = ? AND timeframe = ? AND ts::DATE = ?",
                ["ETH/USDT", TF, missing_ts.date()],
            )
        reset_store_pool()

        result = build_returns_df(
            ["BTC/USDT", "ETH/USDT"],
            days=90,
            market_db=market_db,
        )
        assert result.empty
        reset_store_pool()

    def test_forming_current_utc_day_is_excluded(self, market_db):
        """Bugünün henüz tamamlanmamış 1d barı 90 return'e sızamaz."""
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        store = OHLCVStore(duckdb_path=market_db)
        store.upsert(
            pd.DataFrame(
                [
                    {
                        "venue": VENUE,
                        "symbol": "BTC/USDT",
                        "timeframe": TF,
                        "ts": today,
                        "open": 1.0,
                        "high": 1.0,
                        "low": 1.0,
                        "close": np.nan,
                        "volume": 1.0,
                    }
                ]
            ),
            also_parquet=False,
        )
        reset_store_pool()

        result = build_returns_df(["BTC/USDT"], days=90, market_db=market_db)

        assert result.shape == (90, 1)
        assert result.index[-1] == pd.Timestamp(today - timedelta(days=1))
        assert pd.Timestamp(today) not in result.index

    def test_fresh_ttl_cache_is_invalidated_at_utc_day_rollover(self, market_db, monkeypatch):
        """TTL dolmasa bile UTC midnight eski 90-gün matrisini geçersiz kılar."""
        symbols = ["BTC/USDT"]
        first = build_returns_df(symbols, days=90, market_db=market_db)
        key = (("BTC/USDT",), 90, str(market_db), "1d", "binance")
        assert first.shape == (90, 1)
        assert key in risk_integration._RETURNS_DF_CACHE

        tomorrow = pd.Timestamp.now(tz="UTC").floor("D") + pd.Timedelta(days=1)
        monkeypatch.setattr(risk_integration, "_utc_day_cutoff", lambda: tomorrow)

        second = build_returns_df(symbols, days=90, market_db=market_db)

        assert second.empty  # yeni tamamlanmış gün henüz DB'de yok
        assert key not in risk_integration._RETURNS_DF_CACHE

    @pytest.mark.parametrize("invalid_close", [0.0, -1.0, np.nan, np.inf, -np.inf])
    def test_invalid_required_close_fails_closed(self, market_db, invalid_close):
        """Nonpositive ve nonfinite tamamlanmış close kabul edilmez."""
        target = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=5
        )
        store = OHLCVStore(duckdb_path=market_db)
        with store._conn() as con:
            con.execute(
                "UPDATE ohlcv SET close = ? WHERE symbol = ? AND timeframe = ? AND ts = ?",
                [invalid_close, "BTC/USDT", TF, target],
            )
        reset_store_pool()

        result = build_returns_df(["BTC/USDT"], days=90, market_db=market_db)

        assert result.empty

    @pytest.mark.parametrize("duplicate_offset", [timedelta(0), timedelta(hours=12)])
    def test_duplicate_or_off_grid_daily_close_fails_closed(self, tmp_path, duplicate_offset):
        """Aynı exact ts ya da aynı UTC günde ikinci 1d bar kabul edilmez."""
        db = tmp_path / "malformed_market.duckdb"
        con = duckdb.connect(str(db))
        con.execute(
            """
            CREATE TABLE ohlcv (
                venue VARCHAR, symbol VARCHAR, timeframe VARCHAR,
                ts TIMESTAMP WITH TIME ZONE, open DOUBLE, high DOUBLE,
                low DOUBLE, close DOUBLE, volume DOUBLE
            )
            """
        )
        cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        rows = []
        for age in range(91, 0, -1):
            ts = cutoff - timedelta(days=age)
            rows.append((VENUE, "BTC/USDT", TF, ts, 100.0, 101.0, 99.0, 100.0 + age, 1.0))
        duplicate = list(rows[-1])
        duplicate[3] = duplicate[3] + duplicate_offset
        rows.append(tuple(duplicate))
        con.executemany("INSERT INTO ohlcv VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        con.close()

        result = build_returns_df(["BTC/USDT"], days=90, market_db=db)

        assert result.empty
        reset_store_pool()


# =====================================================================
# T7: OHLCVStore pool R/W config
# =====================================================================


class TestOHLCVStorePoolConfig:
    """Pool'un R/W (read_only=False) açtığını doğrula."""

    def test_pool_opens_rw_not_readonly(self, market_db):
        """Pool'daki connection R/W (write yapabilmeli)."""
        from price_action.data.store import _get_pooled_connection

        reset_store_pool()
        con, lock = _get_pooled_connection(str(market_db))
        with lock:
            # R/W ise schema oluşturabilmeli
            con.execute("CREATE TABLE IF NOT EXISTS _sec58_test_rw (x INT)")
            rows = con.execute("SELECT COUNT(*) FROM _sec58_test_rw").fetchone()
            assert rows is not None
        reset_store_pool()


# =====================================================================
# T8: market_db injection backward compat
# =====================================================================


class TestMarketDbParamBackwardCompat:
    """market_db parametresi str veya Path olarak kabul edilmeli."""

    def test_market_db_as_str(self, market_db):
        result = build_returns_df(
            ["BTC/USDT"],
            days=90,
            market_db=str(market_db),
        )
        assert isinstance(result, pd.DataFrame)
        reset_store_pool()

    def test_market_db_as_path(self, market_db):
        result = build_returns_df(
            ["BTC/USDT"],
            days=90,
            market_db=Path(market_db),
        )
        assert isinstance(result, pd.DataFrame)
        reset_store_pool()
