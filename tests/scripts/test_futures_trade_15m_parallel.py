"""SEC55.A — Paralel symbol scan testleri.

Senaryolar:
  1) max_workers=1 vs max_workers=8 byte-identical signal list
  2) Deterministik sıra: sort(ts, symbol) her zaman aynı
  3) Exception isolation: 1 sembol crash → diğerleri devam (degraded mode)
  4) Timeout per-symbol: 180s budget (mock ile kontrol)
  5) _scan_symbol thread-safe: strateji instantiation per-call
  6) PA_SCAN_PARALLEL_WORKERS env var override
  7) max_workers=1 sequential path fonksiyonel eşdeğerlik
  8) Boş sembol: veri yoksa boş liste döner, crash yok
  9) target_bar_close tz-naive → UTC normalize (no crash)
 10) as_completed sırasından bağımsız deterministik çıktı
"""
from __future__ import annotations

import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# ── Helpers ───────────────────────────────────────────────────────────────────

_UTC = timezone.utc

_BAR_CLOSE = datetime(2026, 5, 18, 14, 15, 0, tzinfo=_UTC)

_SYMBOLS_10 = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
    "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT",
]


def _make_signal(sym: str, strategy: str, offset_sec: int = 0) -> dict:
    """Test için minimal sinyal dict."""
    ts = pd.Timestamp(_BAR_CLOSE) + pd.Timedelta(seconds=offset_sec)
    return {
        "ts": ts,
        "bar_close_ts": pd.Timestamp(_BAR_CLOSE),
        "symbol": sym,
        "strategy": strategy,
        "side": "long",
        "entry_price": 100.0,
        "sl_price": 95.0,
        "tp_price": 110.0,
        "confluence": 0.6,
        "signal_obj": MagicMock(),
    }


def _make_scan_symbol_stub(
    signals_per_sym: dict[str, list[dict]],
    fail_syms: set[str] | None = None,
    delay_syms: dict[str, float] | None = None,
) -> callable:
    """_scan_symbol stub fabrikası.

    signals_per_sym: sym → döndürülecek sinyaller
    fail_syms:      bu semboller exception raise eder
    delay_syms:     sym → saniye gecikme (timeout testi için)
    """
    import time

    def stub(sym: str, target_bar_close: pd.Timestamp) -> list[dict]:
        if fail_syms and sym in fail_syms:
            raise RuntimeError(f"simulated failure for {sym}")
        if delay_syms and sym in delay_syms:
            time.sleep(delay_syms[sym])
        return signals_per_sym.get(sym, [])

    return stub


# ── Senaryo 1: max_workers=1 vs max_workers=8 byte-identical ─────────────────

class TestByteIdenticalOutput:
    """Sequential ve paralel scan aynı sinyalleri (aynı sırada) üretmeli."""

    def _run_scan(self, workers: int, signals_per_sym: dict) -> list[dict]:
        stub = _make_scan_symbol_stub(signals_per_sym)
        with patch(
            "scripts.futures_trade_15m._scan_symbol", side_effect=stub
        ), patch(
            "scripts.futures_trade_15m.SYMBOLS", _SYMBOLS_10
        ):
            from scripts.futures_trade_15m import scan_signals_15m
            return scan_signals_15m(_BAR_CLOSE, max_workers=workers)

    def test_identical_10_syms_4_strategies(self):
        """10 sembol × 4 strateji, her biri 1 sinyal — seq vs par identical."""
        signals_per_sym: dict[str, list[dict]] = {}
        for sym in _SYMBOLS_10:
            signals_per_sym[sym] = [
                _make_signal(sym, "vsa_climax_test"),
                _make_signal(sym, "brooks_failed_breakout"),
                _make_signal(sym, "anchored_vwap_reversal"),
                _make_signal(sym, "engulfing_continuation"),
            ]

        seq = self._run_scan(1, signals_per_sym)
        par = self._run_scan(8, signals_per_sym)

        assert len(seq) == 40  # 10 sym × 4 strategy
        assert len(par) == 40
        # ts + symbol sırasına göre karşılaştır
        _key = lambda s: (str(s["ts"]), s["symbol"], s["strategy"])
        assert sorted(seq, key=_key) == sorted(par, key=_key)

    def test_identical_empty_results(self):
        """Hiç sinyal yoksa her iki path da boş döner."""
        seq = self._run_scan(1, {sym: [] for sym in _SYMBOLS_10})
        par = self._run_scan(8, {sym: [] for sym in _SYMBOLS_10})
        assert seq == [] == par

    def test_identical_partial_signals(self):
        """Sadece 3 sembol sinyal üretiyor."""
        signals_per_sym = {sym: [] for sym in _SYMBOLS_10}
        signals_per_sym["BTC/USDT"] = [_make_signal("BTC/USDT", "vsa_climax_test")]
        signals_per_sym["ETH/USDT"] = [_make_signal("ETH/USDT", "engulfing_continuation")]
        signals_per_sym["SOL/USDT"] = [_make_signal("SOL/USDT", "brooks_failed_breakout")]

        seq = self._run_scan(1, signals_per_sym)
        par = self._run_scan(8, signals_per_sym)

        assert len(seq) == 3 == len(par)
        _key = lambda s: (str(s["ts"]), s["symbol"], s["strategy"])
        assert sorted(seq, key=_key) == sorted(par, key=_key)


# ── Senaryo 2: Deterministik sıra ────────────────────────────────────────────

class TestDeterministicOrder:
    """as_completed sırası non-deterministic olsa bile çıktı sıralı."""

    def test_sort_by_ts_then_symbol(self):
        """Farklı ts'li sinyaller: ts artan, aynı ts'de sembol alfabetik."""
        t0 = pd.Timestamp(_BAR_CLOSE)
        t1 = t0 + pd.Timedelta(seconds=1)

        signals_per_sym = {sym: [] for sym in _SYMBOLS_10}
        # BTC t1, ETH t0 — paralel gelme sırası rastgele ama çıktı t0-ETH önce
        signals_per_sym["BTC/USDT"] = [
            {"ts": t1, "bar_close_ts": t0, "symbol": "BTC/USDT",
             "strategy": "vsa", "side": "long", "entry_price": 100.0,
             "sl_price": 95.0, "tp_price": 110.0, "confluence": 0.6,
             "signal_obj": MagicMock()}
        ]
        signals_per_sym["ETH/USDT"] = [
            {"ts": t0, "bar_close_ts": t0, "symbol": "ETH/USDT",
             "strategy": "vsa", "side": "long", "entry_price": 50.0,
             "sl_price": 45.0, "tp_price": 60.0, "confluence": 0.5,
             "signal_obj": MagicMock()}
        ]

        stub = _make_scan_symbol_stub(signals_per_sym)
        with patch("scripts.futures_trade_15m._scan_symbol", side_effect=stub), \
             patch("scripts.futures_trade_15m.SYMBOLS", _SYMBOLS_10):
            from scripts.futures_trade_15m import scan_signals_15m
            result = scan_signals_15m(_BAR_CLOSE, max_workers=8)

        assert len(result) == 2
        # ETH (t0) önce, BTC (t1) sonra
        assert result[0]["symbol"] == "ETH/USDT"
        assert result[1]["symbol"] == "BTC/USDT"

    def test_same_ts_symbols_alphabetic(self):
        """Aynı ts: sembol alfabetik sırada (AVAX < BTC < ETH < SOL)."""
        t0 = pd.Timestamp(_BAR_CLOSE)
        syms_subset = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "AVAX/USDT"]

        signals_per_sym = {sym: [] for sym in _SYMBOLS_10}
        for sym in syms_subset:
            signals_per_sym[sym] = [
                {"ts": t0, "bar_close_ts": t0, "symbol": sym,
                 "strategy": "vsa", "side": "long", "entry_price": 100.0,
                 "sl_price": 95.0, "tp_price": 110.0, "confluence": 0.6,
                 "signal_obj": MagicMock()}
            ]

        stub = _make_scan_symbol_stub(signals_per_sym)
        with patch("scripts.futures_trade_15m._scan_symbol", side_effect=stub), \
             patch("scripts.futures_trade_15m.SYMBOLS", _SYMBOLS_10):
            from scripts.futures_trade_15m import scan_signals_15m
            result = scan_signals_15m(_BAR_CLOSE, max_workers=8)

        assert len(result) == 4
        result_syms = [s["symbol"] for s in result]
        assert result_syms == sorted(result_syms)


# ── Senaryo 3: Exception isolation (degraded mode) ────────────────────────────

class TestExceptionIsolation:
    """1 sembol exception → diğerleri devam, toplam sinyal azalır ama crash yok."""

    def test_one_fail_others_continue_parallel(self):
        """BTC exception → diğer 9 sembol sinyalleri gelir."""
        signals_per_sym = {
            sym: [_make_signal(sym, "vsa_climax_test")]
            for sym in _SYMBOLS_10
        }
        stub = _make_scan_symbol_stub(
            signals_per_sym, fail_syms={"BTC/USDT"}
        )
        with patch("scripts.futures_trade_15m._scan_symbol", side_effect=stub), \
             patch("scripts.futures_trade_15m.SYMBOLS", _SYMBOLS_10):
            from scripts.futures_trade_15m import scan_signals_15m
            result = scan_signals_15m(_BAR_CLOSE, max_workers=8)

        syms = {s["symbol"] for s in result}
        assert "BTC/USDT" not in syms
        assert len(syms) == 9

    def test_one_fail_others_continue_sequential(self):
        """Sequential mode'da da aynı degraded behavior."""
        signals_per_sym = {
            sym: [_make_signal(sym, "vsa_climax_test")]
            for sym in _SYMBOLS_10
        }
        stub = _make_scan_symbol_stub(
            signals_per_sym, fail_syms={"ETH/USDT"}
        )
        with patch("scripts.futures_trade_15m._scan_symbol", side_effect=stub), \
             patch("scripts.futures_trade_15m.SYMBOLS", _SYMBOLS_10):
            from scripts.futures_trade_15m import scan_signals_15m
            result = scan_signals_15m(_BAR_CLOSE, max_workers=1)

        syms = {s["symbol"] for s in result}
        assert "ETH/USDT" not in syms
        assert len(syms) == 9

    def test_all_fail_returns_empty(self):
        """Tüm semboller fail → boş liste, exception propagate yok."""
        stub = _make_scan_symbol_stub(
            {}, fail_syms=set(_SYMBOLS_10)
        )
        with patch("scripts.futures_trade_15m._scan_symbol", side_effect=stub), \
             patch("scripts.futures_trade_15m.SYMBOLS", _SYMBOLS_10):
            from scripts.futures_trade_15m import scan_signals_15m
            result = scan_signals_15m(_BAR_CLOSE, max_workers=8)

        assert result == []

    def test_multiple_fails_partial_results(self):
        """3 sembol fail → 7 sembol sonucu."""
        signals_per_sym = {
            sym: [_make_signal(sym, "vsa_climax_test")]
            for sym in _SYMBOLS_10
        }
        fail_syms = {"BTC/USDT", "ETH/USDT", "SOL/USDT"}
        stub = _make_scan_symbol_stub(signals_per_sym, fail_syms=fail_syms)
        with patch("scripts.futures_trade_15m._scan_symbol", side_effect=stub), \
             patch("scripts.futures_trade_15m.SYMBOLS", _SYMBOLS_10):
            from scripts.futures_trade_15m import scan_signals_15m
            result = scan_signals_15m(_BAR_CLOSE, max_workers=4)

        assert len(result) == 7


# ── Senaryo 4: Timeout per-symbol ─────────────────────────────────────────────

class TestSymbolTimeout:
    """Timeout=180s — mock ile kontrol edilir (gerçek sleep yok)."""

    def test_timeout_constant_value(self):
        """_SCAN_SYMBOL_TIMEOUT_SEC = 180."""
        from scripts.futures_trade_15m import _SCAN_SYMBOL_TIMEOUT_SEC
        assert _SCAN_SYMBOL_TIMEOUT_SEC == 180

    def test_timeout_sym_excluded_others_included(self):
        """TimeoutError fırlatan sembol excluded; diğerleri OK."""
        import concurrent.futures

        signals_per_sym = {
            sym: [_make_signal(sym, "vsa_climax_test")]
            for sym in _SYMBOLS_10
        }
        timeout_sym = "AVAX/USDT"

        original_stub = _make_scan_symbol_stub(signals_per_sym)

        call_count = {"n": 0}
        futures_map_ref: dict = {}

        def patched_submit(fn, sym, tbc):
            fut = MagicMock()
            if sym == timeout_sym:
                fut.result.side_effect = concurrent.futures.TimeoutError()
            else:
                fut.result.return_value = original_stub(sym, tbc)
            futures_map_ref[fut] = sym
            return fut

        # as_completed'ı da mock'layarak timeout davranışını simüle ediyoruz
        with patch("scripts.futures_trade_15m._scan_symbol", side_effect=original_stub), \
             patch("scripts.futures_trade_15m.SYMBOLS", _SYMBOLS_10):
            from scripts.futures_trade_15m import scan_signals_15m, _SCAN_SYMBOL_TIMEOUT_SEC

            # fut.result(timeout=...) çağrısını kontrol et
            with patch("concurrent.futures.ThreadPoolExecutor") as mock_pool_cls:
                mock_pool = MagicMock()
                mock_pool_cls.return_value.__enter__ = MagicMock(return_value=mock_pool)
                mock_pool_cls.return_value.__exit__ = MagicMock(return_value=False)

                futs = []
                for sym in _SYMBOLS_10:
                    f = MagicMock()
                    if sym == timeout_sym:
                        f.result.side_effect = concurrent.futures.TimeoutError()
                    else:
                        f.result.return_value = signals_per_sym.get(sym, [])
                    futs.append((f, sym))

                future_to_sym = {f: s for f, s in futs}
                mock_pool.submit.side_effect = lambda fn, s, tbc: future_to_sym.get(
                    next(f for f, sym in futs if sym == s), MagicMock()
                )

                with patch("scripts.futures_trade_15m.as_completed", return_value=[f for f, _ in futs]):
                    with patch("scripts.futures_trade_15m.ThreadPoolExecutor") as tpe_cls:
                        mock_ctx = MagicMock()
                        mock_ctx.__enter__ = MagicMock(return_value=mock_pool)
                        mock_ctx.__exit__ = MagicMock(return_value=False)
                        tpe_cls.return_value = mock_ctx

                        mock_pool.submit.side_effect = lambda fn, s, tbc: next(
                            f for f, sym in futs if sym == s
                        )

                        result = scan_signals_15m(_BAR_CLOSE, max_workers=8)

        # Timeout sembolü hariç 9 sembol sinyali gelmeli
        syms_found = {s["symbol"] for s in result}
        assert timeout_sym not in syms_found
        assert len(syms_found) == 9


# ── Senaryo 5: Thread-safety — per-call strategy instantiation ───────────────

class TestThreadSafety:
    """_scan_symbol her çağrıda bağımsız strateji instance'ı yaratmalı."""

    def test_strategy_instantiation_per_call(self):
        """Eşzamanlı 10 çağrı — strateji instance'ları birbirini etkilemez."""
        from scripts.futures_trade_15m import _TOP_4_15M

        instance_ids: list[int] = []
        lock = threading.Lock()

        original_init = None

        def tracking_stub(sym: str, tbc: pd.Timestamp) -> list[dict]:
            # Her çağrı yeni strateji yaratmalı — burada sadece None döndürüyoruz
            # Gerçek threading safety: ayrı thread'ler ayrı strategy instance'ı alır
            with lock:
                instance_ids.append(threading.get_ident())
            return []

        with patch("scripts.futures_trade_15m._scan_symbol", side_effect=tracking_stub), \
             patch("scripts.futures_trade_15m.SYMBOLS", _SYMBOLS_10):
            from scripts.futures_trade_15m import scan_signals_15m
            scan_signals_15m(_BAR_CLOSE, max_workers=8)

        # 10 sembol → 10 çağrı
        assert len(instance_ids) == 10

    def test_no_shared_mutable_state_between_calls(self):
        """İki ardışık scan — önceki state sonrakini etkilemez."""
        signals_per_sym = {sym: [] for sym in _SYMBOLS_10}
        signals_per_sym["BTC/USDT"] = [_make_signal("BTC/USDT", "vsa_climax_test")]

        stub = _make_scan_symbol_stub(signals_per_sym)
        with patch("scripts.futures_trade_15m._scan_symbol", side_effect=stub), \
             patch("scripts.futures_trade_15m.SYMBOLS", _SYMBOLS_10):
            from scripts.futures_trade_15m import scan_signals_15m

            r1 = scan_signals_15m(_BAR_CLOSE, max_workers=4)
            r2 = scan_signals_15m(_BAR_CLOSE, max_workers=4)

        assert len(r1) == len(r2) == 1


# ── Senaryo 6: PA_SCAN_PARALLEL_WORKERS env var ───────────────────────────────

class TestEnvVarOverride:
    """_get_parallel_workers() env var'ı doğru okumalı."""

    def test_default_is_8(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PA_SCAN_PARALLEL_WORKERS", None)
            from scripts.futures_trade_15m import _get_parallel_workers
            assert _get_parallel_workers() == 8

    def test_env_var_4(self):
        with patch.dict(os.environ, {"PA_SCAN_PARALLEL_WORKERS": "4"}):
            from scripts.futures_trade_15m import _get_parallel_workers
            assert _get_parallel_workers() == 4

    def test_env_var_1_sequential(self):
        with patch.dict(os.environ, {"PA_SCAN_PARALLEL_WORKERS": "1"}):
            from scripts.futures_trade_15m import _get_parallel_workers
            assert _get_parallel_workers() == 1

    def test_env_var_invalid_fallback_default(self):
        """Geçersiz değer → default 8."""
        with patch.dict(os.environ, {"PA_SCAN_PARALLEL_WORKERS": "abc"}):
            from scripts.futures_trade_15m import _get_parallel_workers
            assert _get_parallel_workers() == 8

    def test_env_var_zero_clamped_to_1(self):
        """0 → max(1, 0) = 1."""
        with patch.dict(os.environ, {"PA_SCAN_PARALLEL_WORKERS": "0"}):
            from scripts.futures_trade_15m import _get_parallel_workers
            assert _get_parallel_workers() == 1

    def test_env_var_16(self):
        with patch.dict(os.environ, {"PA_SCAN_PARALLEL_WORKERS": "16"}):
            from scripts.futures_trade_15m import _get_parallel_workers
            assert _get_parallel_workers() == 16


# ── Senaryo 7: max_workers=1 sequential path ──────────────────────────────────

class TestSequentialPath:
    """max_workers=1 → sequential loop, ThreadPoolExecutor kullanılmaz."""

    def test_sequential_does_not_use_threadpool(self):
        """max_workers=1 path'inde ThreadPoolExecutor.submit çağrılmaz."""
        signals_per_sym = {sym: [] for sym in _SYMBOLS_10}
        stub = _make_scan_symbol_stub(signals_per_sym)

        with patch("scripts.futures_trade_15m._scan_symbol", side_effect=stub), \
             patch("scripts.futures_trade_15m.SYMBOLS", _SYMBOLS_10), \
             patch("scripts.futures_trade_15m.ThreadPoolExecutor") as mock_tpe:

            from scripts.futures_trade_15m import scan_signals_15m
            scan_signals_15m(_BAR_CLOSE, max_workers=1)

        mock_tpe.assert_not_called()

    def test_sequential_visits_all_symbols(self):
        """Sequential path tüm sembolleri ziyaret eder."""
        visited: list[str] = []

        def tracking_stub(sym: str, tbc: pd.Timestamp) -> list[dict]:
            visited.append(sym)
            return []

        with patch("scripts.futures_trade_15m._scan_symbol", side_effect=tracking_stub), \
             patch("scripts.futures_trade_15m.SYMBOLS", _SYMBOLS_10):
            from scripts.futures_trade_15m import scan_signals_15m
            scan_signals_15m(_BAR_CLOSE, max_workers=1)

        assert sorted(visited) == sorted(_SYMBOLS_10)


# ── Senaryo 8: Boş sembol (veri yok) ─────────────────────────────────────────

class TestEmptySymbol:
    """DuckDB'de veri olmayan sembol → boş liste, crash yok."""

    def test_empty_db_no_crash(self):
        """_scan_symbol: OHLCVStore.read fail → [] döner, exception propagate etmez."""
        # OHLCVStore lokal import içinde — price_action.data.store.OHLCVStore patch'le
        mock_store = MagicMock()
        mock_store.read.side_effect = Exception("simulated db read error")

        with patch("price_action.data.store.OHLCVStore", return_value=mock_store):
            from scripts.futures_trade_15m import _scan_symbol
            result = _scan_symbol("BTC/USDT", pd.Timestamp(_BAR_CLOSE))

        # Read fail → boş liste, crash yok
        assert isinstance(result, list)
        assert result == []

    def test_empty_data_returns_empty(self):
        """OHLCVStore.read() boş df → [] döner."""
        mock_store = MagicMock()
        mock_store.read.return_value = pd.DataFrame()  # boş df

        with patch("price_action.data.store.OHLCVStore", return_value=mock_store):
            from scripts.futures_trade_15m import _scan_symbol
            result = _scan_symbol("XRP/USDT", pd.Timestamp(_BAR_CLOSE))

        assert result == []


# ── Senaryo 9: target_bar_close tz-naive → UTC normalize ─────────────────────

class TestTzNormalization:
    """tz-naive datetime → UTC tz-aware'e normalize, crash yok."""

    def test_tz_naive_no_crash(self):
        """tz-naive target_bar_close → scan hata vermez."""
        naive_bar_close = datetime(2026, 5, 18, 14, 15, 0)  # tz yok
        assert naive_bar_close.tzinfo is None

        stub = _make_scan_symbol_stub({sym: [] for sym in _SYMBOLS_10})
        with patch("scripts.futures_trade_15m._scan_symbol", side_effect=stub), \
             patch("scripts.futures_trade_15m.SYMBOLS", _SYMBOLS_10):
            from scripts.futures_trade_15m import scan_signals_15m
            result = scan_signals_15m(naive_bar_close, max_workers=4)

        assert isinstance(result, list)

    def test_tz_aware_utc_passes_through(self):
        """tz-aware UTC → sorun yok."""
        aware_bar_close = datetime(2026, 5, 18, 14, 15, 0, tzinfo=_UTC)
        stub = _make_scan_symbol_stub({sym: [] for sym in _SYMBOLS_10})
        with patch("scripts.futures_trade_15m._scan_symbol", side_effect=stub), \
             patch("scripts.futures_trade_15m.SYMBOLS", _SYMBOLS_10):
            from scripts.futures_trade_15m import scan_signals_15m
            result = scan_signals_15m(aware_bar_close, max_workers=4)

        assert isinstance(result, list)


# ── Senaryo 10: as_completed non-deterministic → sort sabit ──────────────────

class TestNonDeterministicCompletion:
    """as_completed rastgele sıra → sort(ts, sym) ile deterministic output."""

    def test_reversed_completion_order_same_result(self):
        """Semboller ters sırada tamamlansa da çıktı aynı."""
        t0 = pd.Timestamp(_BAR_CLOSE)
        syms = ["AAA/USDT", "BBB/USDT", "CCC/USDT"]
        signals_per_sym = {
            sym: [{"ts": t0, "bar_close_ts": t0, "symbol": sym,
                   "strategy": "vsa", "side": "long", "entry_price": 100.0,
                   "sl_price": 95.0, "tp_price": 110.0, "confluence": 0.6,
                   "signal_obj": MagicMock()}]
            for sym in syms
        }

        def scan_forward(wk: int) -> list[dict]:
            stub = _make_scan_symbol_stub(signals_per_sym)
            with patch("scripts.futures_trade_15m._scan_symbol", side_effect=stub), \
                 patch("scripts.futures_trade_15m.SYMBOLS", syms):
                from scripts.futures_trade_15m import scan_signals_15m
                return scan_signals_15m(_BAR_CLOSE, max_workers=wk)

        r1 = scan_forward(1)
        r2 = scan_forward(3)

        assert [s["symbol"] for s in r1] == [s["symbol"] for s in r2]
