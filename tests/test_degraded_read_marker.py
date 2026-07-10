"""KALAN_ISLER #8 — borsa okumalarında "başarı-şekilli boş dönüş" görünürlüğü testleri.

Sözleşme (Principal tasarım kısıtı): sarmalayıcılar mock'lanmış hata ile
çağrıldığında dönüş ESKİYLE BİREBİR AYNI (boş liste / sıfır-equity) kalmalı,
AMA _DEGRADED_READS sayacı artmalı + DEGRADED_READ log işareti üretilmeli.
Temiz çağrıda sayaç ARTMAMALI, marker üretilmemeli.

Kaynak-pin: canlı-yol dosyalarındaki instrumente sahaların kaynak adları
(kod grep'i) — saha silinir/yeniden adlandırılırsa bu test kırılır.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.lib.degraded_reads import (  # noqa: E402
    degraded_reads_snapshot,
    record_degraded_read,
    reset_degraded_reads,
    total_degraded_reads,
)


@pytest.fixture(autouse=True)
def _clean_counter():
    """Her test izole sayaçla başlar/biter (modül state global)."""
    reset_degraded_reads()
    yield
    reset_degraded_reads()


# =====================================================================
# 1. Sayaç modülü birim davranışı
# =====================================================================


class TestDegradedReadsModule:
    def test_record_increments_counter_and_snapshot(self):
        assert total_degraded_reads() == 0
        record_degraded_read("kaynak.a", ValueError("boom"), emit_log=False)
        record_degraded_read("kaynak.a", ValueError("boom2"), emit_log=False)
        record_degraded_read("kaynak.b", emit_log=False)
        assert total_degraded_reads() == 3
        snap = degraded_reads_snapshot()
        assert snap["kaynak.a"]["count"] == 2
        assert snap["kaynak.b"]["count"] == 1
        assert snap["kaynak.a"]["last_error_ts"] > 0

    def test_marker_line_on_stderr(self, capsys):
        record_degraded_read("kaynak.stderr", RuntimeError("api down"))
        err = capsys.readouterr().err
        assert "DEGRADED_READ: kaynak.stderr" in err
        assert "boş dönüş HATA kaynaklı" in err
        assert "RuntimeError" in err

    def test_marker_via_log_fn(self):
        lines: list[str] = []
        record_degraded_read("kaynak.logfn", OSError("x"), log_fn=lines.append)
        assert len(lines) == 1
        assert lines[0].startswith("DEGRADED_READ: kaynak.logfn")

    def test_emit_log_false_counts_but_silent(self, capsys):
        record_degraded_read("kaynak.sessiz", ValueError("v"), emit_log=False)
        assert total_degraded_reads() == 1
        assert "DEGRADED_READ" not in capsys.readouterr().err

    def test_never_raises_even_with_hostile_log_fn(self):
        def _bomb(_msg: str) -> None:
            raise RuntimeError("logger patladı")

        # Sözleşme: gözlemlenebilirlik yolu canlı akışı asla bozamaz.
        record_degraded_read("kaynak.bomba", ValueError("v"), log_fn=_bomb)
        assert total_degraded_reads() == 1

    def test_reset(self):
        record_degraded_read("kaynak.r", emit_log=False)
        reset_degraded_reads()
        assert total_degraded_reads() == 0
        assert degraded_reads_snapshot() == {}


# =====================================================================
# 2. fetch_futures_state — mock hata: dönüş AYNI (boş) + sayaç + marker
# =====================================================================


class _FailingReadsExchange:
    """Account raw OK; positions/open-orders/algo-orders okumaları patlar."""

    def fapiPrivateV2GetAccount(self):  # noqa: N802 — ccxt API adı
        return {
            "totalWalletBalance": "5000.0",
            "totalUnrealizedProfit": "0.0",
            "totalMarginBalance": "5000.0",
            "availableBalance": "4900.0",
            "totalInitialMargin": "0.0",
        }

    def fetch_positions(self):
        raise RuntimeError("418 rate-limit ban")

    def fapiPrivateGetOpenOrders(self):  # noqa: N802 — ccxt API adı
        raise RuntimeError("timeout")

    def fapiPrivateGetOpenAlgoOrders(self):  # noqa: N802 — ccxt API adı
        raise RuntimeError("HTTP 503")


class _CleanExchange:
    def fapiPrivateV2GetAccount(self):  # noqa: N802 — ccxt API adı
        return {
            "totalWalletBalance": "5000.0",
            "totalUnrealizedProfit": "0.0",
            "totalMarginBalance": "5000.0",
            "availableBalance": "4900.0",
            "totalInitialMargin": "0.0",
        }

    def fetch_positions(self):
        return []

    def fapiPrivateGetOpenOrders(self):  # noqa: N802 — ccxt API adı
        return []

    def fapiPrivateGetOpenAlgoOrders(self):  # noqa: N802 — ccxt API adı
        return []


class TestFetchFuturesStateDegradedVisibility:
    def test_failing_reads_return_same_empty_shape_but_counted(self, capsys):
        from scripts.futures_trade_daily import fetch_futures_state

        state = fetch_futures_state(_FailingReadsExchange())

        # Dönüş ESKİYLE BİREBİR AYNI (davranış-parite kutsal)
        assert state["positions"] == []
        assert state["algo_orders"] == []
        assert state["n_positions"] == 0
        assert state["n_open_orders"] == 0
        assert state["n_regular_orders"] == 0
        assert state["n_algo_orders"] == 0
        assert state["positions_ok"] is False
        assert state["regular_orders_ok"] is False
        assert state["algo_orders_ok"] is False
        assert state["wallet_balance"] == 5000.0

        # AMA artık ayırt edilebilir: sayaç 3 kaynak için arttı
        assert total_degraded_reads() == 3
        snap = degraded_reads_snapshot()
        assert snap["fetch_futures_state.fetch_positions"]["count"] == 1
        assert snap["fetch_futures_state.open_orders"]["count"] == 1
        assert snap["fetch_futures_state.open_algo_orders"]["count"] == 1

        # ve log işareti üretildi (stderr → launchd log kanalı)
        err = capsys.readouterr().err
        assert "DEGRADED_READ: fetch_futures_state.fetch_positions" in err
        assert "DEGRADED_READ: fetch_futures_state.open_orders" in err
        assert "DEGRADED_READ: fetch_futures_state.open_algo_orders" in err

    def test_clean_reads_do_not_count_or_mark(self, capsys):
        from scripts.futures_trade_daily import fetch_futures_state

        state = fetch_futures_state(_CleanExchange())
        assert state["positions"] == []
        assert state["positions_ok"] is True
        assert state["regular_orders_ok"] is True
        assert state["algo_orders_ok"] is True
        assert total_degraded_reads() == 0
        assert "DEGRADED_READ" not in capsys.readouterr().err


# =====================================================================
# 3. build_spot_account_state — fetch_balance hatası: dönüş AYNI + sayaç
# =====================================================================


class TestSpotAccountDegradedVisibility:
    def test_balance_fail_same_zero_state_but_counted(self, capsys, tmp_path):
        from scripts.lib.risk_integration import build_spot_account_state

        class _Ex:
            def fetch_balance(self):
                raise RuntimeError("api key invalid")

        acct = build_spot_account_state(_Ex(), journal_path=tmp_path / "yok.duckdb")
        # Dönüş ESKİYLE AYNI: sıfır-equity AccountState
        assert acct.equity_usdt == 0.0
        assert acct.free_margin_usdt == 0.0
        assert acct.open_positions == []
        # Sayaç + marker
        assert degraded_reads_snapshot()["spot_account.fetch_balance"]["count"] == 1
        assert "DEGRADED_READ: spot_account.fetch_balance" in capsys.readouterr().err

    def test_clean_balance_no_count(self, capsys, tmp_path):
        from scripts.lib.risk_integration import build_spot_account_state

        class _Ex:
            def fetch_balance(self):
                return {"USDT": {"total": 1000.0}, "total": {"USDT": 1000.0}}

        acct = build_spot_account_state(_Ex(), journal_path=tmp_path / "yok.duckdb")
        assert acct.equity_usdt == 1000.0
        assert total_degraded_reads() == 0
        assert "DEGRADED_READ" not in capsys.readouterr().err


# =====================================================================
# 4. Kaynak-pin: instrumente sahalar kodda mevcut (silinirse test kırılır)
# =====================================================================


class TestSourcePins:
    """DEGRADED_READ marker'ı sahalarda — dosya bazlı kaynak-adı pinleri."""

    def _src(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_futures_trade_daily_sites(self):
        src = self._src("scripts/futures_trade_daily.py")
        for source in (
            "fetch_futures_state.fetch_positions",
            "fetch_futures_state.open_orders",
            "fetch_futures_state.open_algo_orders",
        ):
            assert f'record_degraded_read("{source}"' in src, source

    def test_futures_daemon_sites(self):
        src = self._src("scripts/futures_daemon.py")
        for source in (
            "rebuild_tracking.fetch_positions",
            "rebuild_tracking.open_algo_orders",
            "pos_check.position_risk_confirm",
            "prot_check.algo_history",
            "prot_watchdog.fetch_positions_fresh",
            "entry_submit.fetch_order",
        ):
            assert "record_degraded_read(" in src and f'"{source}"' in src, source
        # POS_CHECK özet satırı [DEGRADED:n] ekini taşıyabilmeli
        assert "_POS_CHECK_DEG_SNAPSHOT" in src
        assert "[DEGRADED:" in src
        assert "degraded_suffix" in src

    def test_futures_trade_15m_site(self):
        src = self._src("scripts/futures_trade_15m.py")
        assert 'record_degraded_read("scan15m.fresh_fetch_ohlcv"' in src

    def test_risk_integration_sites(self):
        src = self._src("scripts/lib/risk_integration.py")
        assert 'record_degraded_read("spot_account.fetch_balance"' in src
        assert 'record_degraded_read("spot_account.fetch_ticker"' in src


# =====================================================================
# 5. POS_CHECK delta semantiği (total sayaç üzerinden)
# =====================================================================


class TestPosCheckDeltaSemantics:
    def test_delta_between_snapshots(self):
        """position_check'in kullandığı delta deseni: önceki-toplam → yeni-toplam."""
        snapshot = total_degraded_reads()
        assert snapshot == 0
        record_degraded_read("tick.icinde.a", emit_log=False)
        record_degraded_read("tick.icinde.b", emit_log=False)
        delta = total_degraded_reads() - snapshot
        assert delta == 2  # → " [DEGRADED:2]" eki
        snapshot = total_degraded_reads()
        # Temiz tick: delta 0 → ek yok
        assert total_degraded_reads() - snapshot == 0
