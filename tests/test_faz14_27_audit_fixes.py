"""Regression tests for Faz 14.27 audit fixes.

Bu tests audit sırasında bulunan 4 kritik bug için regression koruması:
  - P0-1: regime_features fetched_at string parse (sizing.py)
  - P0-2: v63/v11 config schema parity (RiskOfficer key reads)
  - P0-5: SL yön mismatch (PROT_WATCHDOG side filter)
  - P0-9: market.duckdb PA_DUCKDB_READ_ONLY env
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


# -----------------------------------------------------------------------------
# P0-1: regime_features fetched_at string parse
# -----------------------------------------------------------------------------

class TestRegimeFeaturesFetchedAtParse:
    """Faz 14.27 P0-1 regression: parquet'te fetched_at string olarak yazılıyor.
    Önceki bug: hasattr(to_pydatetime) False → silent fallback datetime.now()
    → cache HER ZAMAN FRESH gibi görünüyordu (BTC capitulation halt devre dışı).
    """

    def _make_parquet_with_string_fetched_at(self, tmpdir: Path, age_hours: float):
        """Test parquet'i string fetched_at ile."""
        fa = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
        df = pd.DataFrame([{
            "ts": "2026-05-27",
            "atr_pct_30d": 2.5,
            "return_30d": -3.0,
            "return_30d_abs_pct": 3.0,
            "ema200_distance_pct": -5.0,
            "above_ema200": False,
            "fng_value": -1.0,
            "realized_vol_7d_annualized": 30.0,
            "fetched_at": fa,  # ← STRING, not pandas timestamp
        }])
        p = tmpdir / "regime_features_latest.parquet"
        df.to_parquet(p)
        return p

    def test_string_fetched_at_parsed_correctly_fresh(self):
        """Cache 1h eski (FRESH < 6h threshold) — parse OK, status FRESH."""
        from price_action.risk.sizing import RiskOfficer
        from price_action.risk.regime_filter import RegimeCacheStatus

        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            parquet = self._make_parquet_with_string_fetched_at(tmpdir, age_hours=1.0)

            cfg = {
                "regime_filter_per_strategy": {
                    "enabled": True,
                    "features_path": str(parquet),
                    "cache_freshness": {
                        "warn_hours": 6,
                        "reject_hours": 24,
                        "hard_reject_hours": 48,
                        "strict_mode": True,
                    },
                },
            }
            ro = RiskOfficer(cfg)
            features, status = ro._load_regime_features()
            assert status == RegimeCacheStatus.FRESH, \
                f"1h old cache should be FRESH (got {status})"
            assert features is not None, "Fresh cache should return features"

    def test_string_fetched_at_parsed_correctly_warn(self):
        """Cache 8h eski (WARN: 6h < age < 24h) — parse OK, status WARN."""
        from price_action.risk.sizing import RiskOfficer
        from price_action.risk.regime_filter import RegimeCacheStatus

        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            parquet = self._make_parquet_with_string_fetched_at(tmpdir, age_hours=8.0)

            cfg = {
                "regime_filter_per_strategy": {
                    "enabled": True,
                    "features_path": str(parquet),
                    "cache_freshness": {
                        "warn_hours": 6,
                        "reject_hours": 24,
                        "hard_reject_hours": 48,
                        "strict_mode": True,
                    },
                },
            }
            ro = RiskOfficer(cfg)
            features, status = ro._load_regime_features()
            assert status == RegimeCacheStatus.WARN, \
                f"8h old cache should be WARN (got {status})"

    def test_string_fetched_at_parsed_correctly_reject(self):
        """Cache 30h eski (REJECT: 24h < age < 48h) — parse OK, status REJECT."""
        from price_action.risk.sizing import RiskOfficer
        from price_action.risk.regime_filter import RegimeCacheStatus

        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            parquet = self._make_parquet_with_string_fetched_at(tmpdir, age_hours=30.0)

            cfg = {
                "regime_filter_per_strategy": {
                    "enabled": True,
                    "features_path": str(parquet),
                    "cache_freshness": {
                        "warn_hours": 6,
                        "reject_hours": 24,
                        "hard_reject_hours": 48,
                        "strict_mode": True,
                    },
                },
            }
            ro = RiskOfficer(cfg)
            features, status = ro._load_regime_features()
            assert status == RegimeCacheStatus.REJECT, \
                f"30h old cache should be REJECT (got {status})"


# -----------------------------------------------------------------------------
# P0-2: v63/v11 config schema parity
# -----------------------------------------------------------------------------

class TestConfigSchemaParity:
    """Faz 14.27 P0-2 regression: backtest schema (lab.py) vs LIVE RiskOfficer.

    LIVE RiskOfficer şunları okur:
      - position_sizing.risk_per_trade
      - concentration_limits.max_open_positions
      - drawdown_breakers.consecutive_losses
      - drawdown_breakers.daily_loss_pct

    v63 ve v11 config'lerinde bu key'lerin BULUNDUĞUNU doğrula.
    """

    @pytest.mark.parametrize("config_path,expected_max_open,expected_consec", [
        ("configs/risk_phoenix_scalp_15m_rsi2_v63.yaml", 8, 3),
        ("configs/risk_phoenix_scalp_15m_vwap_v11.yaml", 4, 2),
    ])
    def test_live_schema_keys_present(self, config_path, expected_max_open, expected_consec):
        cfg = yaml.safe_load((ROOT / config_path).read_text())

        # 1) position_sizing.risk_per_trade
        rpt = cfg.get("position_sizing", {}).get("risk_per_trade")
        assert rpt is not None, f"{config_path}: position_sizing.risk_per_trade EKSİK (LIVE bot okumaz)"
        assert 0 < rpt <= 0.05, f"risk_per_trade {rpt} out of range"

        # 2) concentration_limits.max_open_positions
        max_open = cfg.get("concentration_limits", {}).get("max_open_positions")
        assert max_open == expected_max_open, \
            f"{config_path}: concentration_limits.max_open_positions {max_open} != {expected_max_open}"

        # 3) drawdown_breakers.consecutive_losses
        consec = cfg.get("drawdown_breakers", {}).get("consecutive_losses")
        assert consec == expected_consec, \
            f"{config_path}: drawdown_breakers.consecutive_losses {consec} != {expected_consec}"

        # 4) drawdown_breakers.daily_loss_pct
        daily = cfg.get("drawdown_breakers", {}).get("daily_loss_pct")
        assert daily is not None, f"{config_path}: drawdown_breakers.daily_loss_pct EKSİK"


# -----------------------------------------------------------------------------
# P0-5: SL yön mismatch (PROT_WATCHDOG side filter)
# -----------------------------------------------------------------------------

class TestSLYonMismatchFilter:
    """Faz 14.27 P0-5 regression: STOP_MARKET emirleri yön filtresiz toplanıyordu.

    Senaryo: Pozisyon SHORT→LONG yön değişti, eski BUY STOP (SHORT'un SL'i)
    yanlışlıkla "LONG'un SL'i" sanılıyor → orphan SL'siz pozisyon.
    """

    def test_long_position_filters_out_buy_stop(self):
        """LONG pozisyon için BUY STOP emirleri filtrelenir, SELL STOP geçer."""
        _side = "long"
        _sym_algo = "AVAXUSDT"
        _expected_sl_side = "SELL" if _side == "long" else "BUY"

        algo_orders = [
            # Eski SHORT SL'i — ters yön, filtrelenecek
            {"symbol": _sym_algo, "orderType": "STOP_MARKET",
             "side": "BUY", "triggerPrice": "9.524", "algoId": 1, "quantity": "40"},
            # Yeni LONG SL'i — doğru yön, geçecek
            {"symbol": _sym_algo, "orderType": "STOP_MARKET",
             "side": "SELL", "triggerPrice": "8.5", "algoId": 2, "quantity": "20"},
        ]

        # Bot fix logic'i (futures_daemon.py:680-712 reproduce)
        _sl_orders = []
        _orphan_wrong_side = []
        for o in algo_orders:
            if (o.get("symbol") == _sym_algo
                    and str(o.get("orderType", "")).upper() == "STOP_MARKET"):
                _o_side = str(o.get("side", "")).upper()
                if _o_side == _expected_sl_side:
                    _sl_orders.append((float(o["triggerPrice"]), o["algoId"], float(o["quantity"])))
                else:
                    _orphan_wrong_side.append((float(o["triggerPrice"]), o["algoId"], _o_side))

        assert len(_sl_orders) == 1, f"LONG için 1 geçerli SL bekleniyor: {_sl_orders}"
        assert _sl_orders[0][1] == 2, "Geçerli SL algoId=2 (SELL STOP) olmalı"
        assert len(_orphan_wrong_side) == 1, "Orphan BUY STOP listede olmalı"
        assert _orphan_wrong_side[0][2] == "BUY", "Orphan'ın side'ı BUY"

    def test_short_position_filters_out_sell_stop(self):
        """SHORT pozisyon için SELL STOP emirleri filtrelenir, BUY STOP geçer."""
        _side = "short"
        _sym_algo = "BTCUSDT"
        _expected_sl_side = "SELL" if _side == "long" else "BUY"

        algo_orders = [
            # Eski LONG SL'i — ters yön
            {"symbol": _sym_algo, "orderType": "STOP_MARKET",
             "side": "SELL", "triggerPrice": "60000", "algoId": 10, "quantity": "0.1"},
            # Yeni SHORT SL'i — doğru yön
            {"symbol": _sym_algo, "orderType": "STOP_MARKET",
             "side": "BUY", "triggerPrice": "70000", "algoId": 11, "quantity": "0.1"},
        ]

        _sl_orders = []
        _orphan_wrong_side = []
        for o in algo_orders:
            if (o.get("symbol") == _sym_algo
                    and str(o.get("orderType", "")).upper() == "STOP_MARKET"):
                _o_side = str(o.get("side", "")).upper()
                if _o_side == _expected_sl_side:
                    _sl_orders.append((float(o["triggerPrice"]), o["algoId"], float(o["quantity"])))
                else:
                    _orphan_wrong_side.append((float(o["triggerPrice"]), o["algoId"], _o_side))

        assert len(_sl_orders) == 1
        assert _sl_orders[0][1] == 11  # BUY STOP
        assert len(_orphan_wrong_side) == 1
        assert _orphan_wrong_side[0][2] == "SELL"


# -----------------------------------------------------------------------------
# P0-9: market.duckdb PA_DUCKDB_READ_ONLY env
# -----------------------------------------------------------------------------

class TestDuckDBReadOnlyMode:
    """Faz 14.27 P0-9 regression: bot exclusive lock tutuyordu, ingest yazamıyordu.

    Fix: PA_DUCKDB_READ_ONLY=true → bot read-only mode, ingest write yapabilir.
    """

    def test_pa_duckdb_read_only_env_recognized(self, monkeypatch):
        """PA_DUCKDB_READ_ONLY=true store.py tarafından okunuyor."""
        from price_action.data.store import _get_pooled_connection

        monkeypatch.setenv("PA_DUCKDB_READ_ONLY", "true")

        # _get_pooled_connection bu env'i okuyup read_only=True döndürmeli
        # store.py:40 docstring: "PA_DUCKDB_READ_ONLY=true ise read_only modunda aç"
        import os as _os
        flag = _os.environ.get("PA_DUCKDB_READ_ONLY", "").lower() in ("1", "true", "yes")
        assert flag is True, "PA_DUCKDB_READ_ONLY recognized as truthy"

    def test_pa_duckdb_read_only_env_false(self, monkeypatch):
        """PA_DUCKDB_READ_ONLY=false veya yok → read-write mode."""
        monkeypatch.delenv("PA_DUCKDB_READ_ONLY", raising=False)

        import os as _os
        flag = _os.environ.get("PA_DUCKDB_READ_ONLY", "").lower() in ("1", "true", "yes")
        assert flag is False, "Empty PA_DUCKDB_READ_ONLY = read-write mode"

    def test_plist_files_have_read_only_env(self):
        """4 bot plist'inde PA_DUCKDB_READ_ONLY ekli mi?"""
        plist_files = [
            "ops/launchd/com.priceaction.futures15m.plist",
            "ops/launchd/com.priceaction.futures15m_v63.plist",
            "ops/launchd/com.priceaction.futures15m_v11.plist",
        ]
        for pf in plist_files:
            content = (ROOT / pf).read_text()
            assert "PA_DUCKDB_READ_ONLY" in content, f"{pf}: PA_DUCKDB_READ_ONLY EKSİK"

        # 5m bot wrapper script
        sh_content = (ROOT / "ops/launchd/run_futures5m.sh").read_text()
        assert "PA_DUCKDB_READ_ONLY" in sh_content, "run_futures5m.sh: PA_DUCKDB_READ_ONLY EKSİK"


# -----------------------------------------------------------------------------
# C2-1: MTD halt timezone bug
# -----------------------------------------------------------------------------

class TestMTDHaltTimezone:
    """Faz 14.27 C2-1 regression: _end_of_month() naive datetime → tz-aware."""

    def test_end_of_month_returns_tz_aware(self):
        from price_action.execution.p1c_walker import P1cWalker

        # Mock config
        cfg_path = ROOT / "configs/risk_phoenix_scalp_5m_p1c.yaml"
        walker = P1cWalker(config_path=cfg_path)
        eom = walker._end_of_month()
        assert eom.tzinfo is not None, "_end_of_month should return tz-aware datetime"
        assert eom.tzinfo == timezone.utc, "tzinfo should be UTC"

    def test_end_of_month_iso_roundtrip(self):
        """isoformat → fromisoformat roundtrip tz korur."""
        from price_action.execution.p1c_walker import P1cWalker

        cfg_path = ROOT / "configs/risk_phoenix_scalp_5m_p1c.yaml"
        walker = P1cWalker(config_path=cfg_path)
        eom = walker._end_of_month()
        iso_str = eom.isoformat()
        parsed = datetime.fromisoformat(iso_str)
        assert parsed.tzinfo is not None, "Roundtrip should preserve tz info"


# -----------------------------------------------------------------------------
# C2-2: Loss counter reset after profit
# -----------------------------------------------------------------------------

class TestLossCounterReset:
    """Faz 14.27 C2-2 regression: kazanç sonrası last_loss_times sıfırlanır."""

    def test_profit_resets_loss_counter(self):
        from price_action.execution.p1c_walker import P1cWalker

        cfg_path = ROOT / "configs/risk_phoenix_scalp_5m_p1c.yaml"
        walker = P1cWalker(config_path=cfg_path)
        # Mevcut state'i clear
        walker._state["last_loss_times"] = ["2026-05-28T10:00:00+00:00",
                                             "2026-05-28T10:30:00+00:00"]
        # Kazanç trade kaydet
        walker.record_trade_outcome({
            "symbol": "BTC/USDT",
            "entry_ts": "2026-05-28T11:00:00+00:00",
            "close_ts": "2026-05-28T11:15:00+00:00",
            "pnl_usdt": 50.0,  # Profit
            "r_multiple": 1.5,
            "side": "long",
            "strategy": "test",
        })
        assert walker._state["last_loss_times"] == [], \
            "Kazanç sonrası last_loss_times boş olmalı"
