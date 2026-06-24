from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd
import pytest
from price_action.contracts import Reject, RiskedOrder, Signal
from price_action.risk.breaker import DDBreaker
from price_action.risk.regime_filter import CacheFreshnessConfig, RegimeCacheStatus
from price_action.risk.sizing import AccountState, RiskOfficer

def _make_parquet(tmp_path, age_hours, ts_date=None):
    # canlı now() — modül-seviyesi sabit (frozen _NOW) suite içinde 42s kayma
    # yaratıp grace-boundary testlerini flaky yapıyordu.
    _now = datetime.now(timezone.utc)
    fetched_at = _now - timedelta(hours=age_hours)
    ts_date = ts_date or ((_now - timedelta(days=1)).date())
    df = pd.DataFrame([{
        "ts": ts_date, "fetched_at": fetched_at,
        "atr_pct_30d": 4.0, "return_30d": 5.0, "return_30d_abs_pct": 5.0,
        "ema200_distance_pct": 2.0, "above_ema200": True,
        "fng_value": 50.0, "realized_vol_7d_annualized": 60.0,
    }])
    p = tmp_path / "regime_features_latest.parquet"
    df.to_parquet(p)
    return p

def _base_risk_cfg(parquet_path=None, strict=True, grace_minutes=30.0):
    return {
        "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01, "min_quantity_usdt": 20},
        "stop_loss": {"method": "atr", "atr_period": 14, "atr_multiplier": 2.0},
        "take_profit": {"primary_R": 2.0, "partial_close_at_R": 1.0},
        "leverage": {"enabled": True, "max_leverage_per_symbol": 3, "max_portfolio_notional_x_equity": 4, "margin_safety_ratio": 0.5},
        "drawdown_breakers": {"daily_loss_pct": 0.05, "weekly_loss_pct": 0.10, "monthly_loss_pct": 0.99, "consecutive_losses": 99},
        "correlation_gate": {"enabled": False},
        "concentration_limits": {"max_open_positions": 8, "max_per_category_pct": 0.40, "max_per_symbol_pct": 0.20},
        "liquidity_gate": {"max_order_to_minute_volume": 0.01, "min_book_depth_usdt": 100_000},
        "regime_filter_per_strategy": {
            "enabled": True,
            "features_path": parquet_path or "data/regime_features_latest.parquet",
            "cache_freshness": {
                "warn_hours": 24.0, "reject_hours": 48.0,
                "hard_reject_hours": 168.0, "grace_minutes": grace_minutes,
                "strict_mode": strict,
            },
        },
    }

def _make_signal(direction="long"):
    return Signal(
        ts=datetime(2024, 6, 2, 9, 0, tzinfo=timezone.utc),
        venue="binance", symbol="BTC/USDT", timeframe="1d",
        direction=direction, pattern_id="engulfing_continuation",
        confluence_score=2.0, sl_price=92.0, tp_price=116.0,
        suggested_size_atr=4.0, metadata={"atr14": 2.0},
    )

def _make_ro(cfg, tmp_path):
    breaker = DDBreaker(cfg["drawdown_breakers"], state_path=tmp_path / "br.json")
    return RiskOfficer(cfg, breaker=breaker)

def _make_acct():
    return AccountState(equity_usdt=10_000, free_margin_usdt=10_000)



# ==============================================================
# 1. CacheFreshnessConfig.classify
# ==============================================================

class TestCacheFreshnessClassify:

    def _cfg(self, grace_minutes=30.0):
        return CacheFreshnessConfig(warn_hours=24.0, reject_hours=48.0, hard_reject_hours=168.0, grace_minutes=grace_minutes)

    def test_fresh_zero_age(self):
        assert self._cfg().classify(0.0) == RegimeCacheStatus.FRESH

    def test_fresh_just_below_warn_threshold(self):
        assert self._cfg(30.0).classify(24.4) == RegimeCacheStatus.FRESH

    def test_warn_just_above_warn_threshold(self):
        assert self._cfg(30.0).classify(24.6) == RegimeCacheStatus.WARN

    def test_warn_below_reject_threshold(self):
        assert self._cfg().classify(40.0) == RegimeCacheStatus.WARN

    def test_reject_just_above_reject_threshold(self):
        assert self._cfg(30.0).classify(49.0) == RegimeCacheStatus.REJECT

    def test_reject_below_hard_threshold(self):
        assert self._cfg().classify(100.0) == RegimeCacheStatus.REJECT

    def test_hard_reject_above_hard_threshold(self):
        assert self._cfg(30.0).classify(169.0) == RegimeCacheStatus.HARD_REJECT

    def test_grace_absorbs_5min_late_cron(self):
        age = 24.0 + 5 / 60.0
        assert self._cfg(30.0).classify(age) == RegimeCacheStatus.FRESH

    def test_grace_zero_exactly_at_warn_triggers_warn(self):
        cfg = CacheFreshnessConfig(warn_hours=24.0, reject_hours=48.0, hard_reject_hours=168.0, grace_minutes=0.0)
        assert cfg.classify(24.0) == RegimeCacheStatus.WARN

    def test_from_cfg_defaults(self):
        cfg = CacheFreshnessConfig.from_cfg({})
        assert cfg.warn_hours == 24.0 and cfg.reject_hours == 48.0
        assert cfg.hard_reject_hours == 168.0 and cfg.grace_minutes == 30.0

    def test_from_cfg_custom(self):
        d = dict(warn_hours=12.0, reject_hours=36.0, hard_reject_hours=72.0, grace_minutes=15.0)
        cfg = CacheFreshnessConfig.from_cfg(d)
        assert cfg.warn_hours == 12.0 and cfg.reject_hours == 36.0
        assert cfg.hard_reject_hours == 72.0 and cfg.grace_minutes == 15.0


# ==============================================================
# 2. _load_regime_features -- staleness tiers
# ==============================================================

class TestLoadRegimeFeaturesTiers:

    def test_fresh_returns_fresh(self, tmp_path):
        p = _make_parquet(tmp_path, age_hours=1.0)
        ro = _make_ro(_base_risk_cfg(str(p)), tmp_path)
        features, status = ro._load_regime_features()
        assert status == RegimeCacheStatus.FRESH and features is not None

    def test_warn_age_returns_warn_with_features(self, tmp_path):
        p = _make_parquet(tmp_path, age_hours=25.0)
        ro = _make_ro(_base_risk_cfg(str(p), grace_minutes=0.0), tmp_path)
        features, status = ro._load_regime_features()
        assert status == RegimeCacheStatus.WARN
        assert features is not None

    def test_reject_age_returns_reject_no_features(self, tmp_path):
        p = _make_parquet(tmp_path, age_hours=50.0)
        ro = _make_ro(_base_risk_cfg(str(p), grace_minutes=0.0), tmp_path)
        features, status = ro._load_regime_features()
        assert status == RegimeCacheStatus.REJECT and features is None

    def test_hard_reject_age_returns_hard_reject(self, tmp_path):
        p = _make_parquet(tmp_path, age_hours=200.0)
        ro = _make_ro(_base_risk_cfg(str(p), grace_minutes=0.0), tmp_path)
        features, status = ro._load_regime_features()
        assert status == RegimeCacheStatus.HARD_REJECT and features is None

    def test_missing_file_strict_returns_reject(self, tmp_path):
        path = str(tmp_path / "nonexistent.parquet")
        ro = _make_ro(_base_risk_cfg(path, strict=True), tmp_path)
        features, status = ro._load_regime_features()
        assert status == RegimeCacheStatus.REJECT and features is None

    def test_missing_file_non_strict_returns_missing(self, tmp_path):
        path = str(tmp_path / "nonexistent.parquet")
        ro = _make_ro(_base_risk_cfg(path, strict=False), tmp_path)
        features, status = ro._load_regime_features()
        assert status == RegimeCacheStatus.MISSING and features is None


# ==============================================================
# 3 and 4. RiskOfficer.evaluate() -- cache status driven
# ==============================================================

class TestEvaluateCacheStatus:

    def test_fresh_cache_allows_signal(self, tmp_path):
        p = _make_parquet(tmp_path, age_hours=1.0)
        ro = _make_ro(_base_risk_cfg(str(p)), tmp_path)
        result = ro.evaluate(_make_signal(), _make_acct(), market_price=100.0, atr=2.0)
        assert isinstance(result, RiskedOrder)

    def test_warn_cache_allows_signal(self, tmp_path):
        p = _make_parquet(tmp_path, age_hours=25.0)
        ro = _make_ro(_base_risk_cfg(str(p), grace_minutes=0.0), tmp_path)
        result = ro.evaluate(_make_signal(), _make_acct(), market_price=100.0, atr=2.0)
        assert isinstance(result, RiskedOrder)

    def test_reject_cache_rejects_signal(self, tmp_path):
        p = _make_parquet(tmp_path, age_hours=50.0)
        ro = _make_ro(_base_risk_cfg(str(p), grace_minutes=0.0), tmp_path)
        result = ro.evaluate(_make_signal(), _make_acct(), market_price=100.0, atr=2.0)
        assert isinstance(result, Reject)
        assert result.reason == "regime_cache_stale"
        assert result.detail["cache_status"] == "reject"

    def test_hard_reject_cache_rejects_signal(self, tmp_path):
        p = _make_parquet(tmp_path, age_hours=200.0)
        ro = _make_ro(_base_risk_cfg(str(p), grace_minutes=0.0), tmp_path)
        result = ro.evaluate(_make_signal(), _make_acct(), market_price=100.0, atr=2.0)
        assert isinstance(result, Reject)
        assert result.reason == "regime_cache_stale"
        assert result.detail["cache_status"] == "hard_reject"

    def test_missing_strict_rejects_signal(self, tmp_path):
        # file missing + strict=True: _load_regime_features returns (None, REJECT)
        # -> evaluate() rejects with regime_cache_stale (covers both REJECT paths)
        path = str(tmp_path / "nonexistent.parquet")
        ro = _make_ro(_base_risk_cfg(path, strict=True), tmp_path)
        result = ro.evaluate(_make_signal(), _make_acct(), market_price=100.0, atr=2.0)
        assert isinstance(result, Reject)
        assert result.reason in ("regime_cache_stale", "regime_cache_missing")

    def test_reject_blocks_both_sides(self, tmp_path):
        p = _make_parquet(tmp_path, age_hours=50.0)
        ro = _make_ro(_base_risk_cfg(str(p), grace_minutes=0.0), tmp_path)
        acct = _make_acct()
        r_long = ro.evaluate(_make_signal("long"), acct, market_price=100.0, atr=2.0)
        r_short = ro.evaluate(_make_signal("short"), acct, market_price=100.0, atr=2.0)
        assert isinstance(r_long, Reject) and r_long.reason == "regime_cache_stale"
        assert isinstance(r_short, Reject) and r_short.reason == "regime_cache_stale"


# ==============================================================
# 5. PA_REGIME_CACHE_STRICT=0
# ==============================================================

class TestStrictModeEnvVar:

    def test_env_var_zero_overrides_strict(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PA_REGIME_CACHE_STRICT", "0")
        path = str(tmp_path / "nonexistent.parquet")
        ro = _make_ro(_base_risk_cfg(path, strict=True), tmp_path)
        assert ro._freshness_cfg.strict_mode is False

    def test_env_var_one_preserves_strict(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PA_REGIME_CACHE_STRICT", "1")
        path = str(tmp_path / "nonexistent.parquet")
        ro = _make_ro(_base_risk_cfg(path, strict=True), tmp_path)
        assert ro._freshness_cfg.strict_mode is True

    def test_env_var_zero_missing_returns_missing_not_reject(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PA_REGIME_CACHE_STRICT", "0")
        path = str(tmp_path / "nonexistent.parquet")
        ro = _make_ro(_base_risk_cfg(path, strict=True), tmp_path)
        _, status = ro._load_regime_features()
        assert status == RegimeCacheStatus.MISSING


# ==============================================================
# 6. Grace buffer false-positive prevention
# ==============================================================

class TestGraceBuffer:

    def test_5min_late_cron_stays_fresh(self, tmp_path):
        age = 24.0 + 5 / 60.0
        p = _make_parquet(tmp_path, age_hours=age)
        ro = _make_ro(_base_risk_cfg(str(p), grace_minutes=30.0), tmp_path)
        _, status = ro._load_regime_features()
        assert status == RegimeCacheStatus.FRESH

    def test_31min_late_cron_triggers_warn(self, tmp_path):
        age = 24.0 + 31 / 60.0
        p = _make_parquet(tmp_path, age_hours=age)
        ro = _make_ro(_base_risk_cfg(str(p), grace_minutes=30.0), tmp_path)
        _, status = ro._load_regime_features()
        assert status == RegimeCacheStatus.WARN

    def test_grace_boundary_exact_inside_fresh(self, tmp_path):
        grace_h = 30 / 60.0
        age = 24.0 + grace_h - 0.001
        p = _make_parquet(tmp_path, age_hours=age)
        ro = _make_ro(_base_risk_cfg(str(p), grace_minutes=30.0), tmp_path)
        _, status = ro._load_regime_features()
        assert status == RegimeCacheStatus.FRESH


# ==============================================================
# 7. Filter disabled -> no staleness check
# ==============================================================

class TestFilterDisabledNoStalenessCheck:

    def test_disabled_missing_cache_not_rejected(self, tmp_path):
        path = str(tmp_path / "nonexistent.parquet")
        cfg = _base_risk_cfg(path, strict=True)
        cfg["regime_filter_per_strategy"]["enabled"] = False
        ro = _make_ro(cfg, tmp_path)
        result = ro.evaluate(_make_signal(), _make_acct(), market_price=100.0, atr=2.0)
        if isinstance(result, Reject):
            assert result.reason not in ("regime_cache_missing", "regime_cache_stale")

    def test_disabled_stale_cache_not_rejected(self, tmp_path):
        p = _make_parquet(tmp_path, age_hours=200.0)
        cfg = _base_risk_cfg(str(p), grace_minutes=0.0)
        cfg["regime_filter_per_strategy"]["enabled"] = False
        ro = _make_ro(cfg, tmp_path)
        result = ro.evaluate(_make_signal(), _make_acct(), market_price=100.0, atr=2.0)
        if isinstance(result, Reject):
            assert result.reason not in ("regime_cache_stale", "regime_cache_missing")


# ==============================================================
# 8. Replay parity
# ==============================================================

class TestReplayParity:

    def _no_filter_cfg(self):
        return {
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01, "min_quantity_usdt": 20},
            "stop_loss": {"method": "atr", "atr_period": 14, "atr_multiplier": 2.0},
            "take_profit": {"primary_R": 2.0, "partial_close_at_R": 1.0},
            "leverage": {"enabled": True, "max_leverage_per_symbol": 3, "max_portfolio_notional_x_equity": 4, "margin_safety_ratio": 0.5},
            "drawdown_breakers": {"daily_loss_pct": 0.05, "weekly_loss_pct": 0.10, "monthly_loss_pct": 0.99, "consecutive_losses": 99},
            "correlation_gate": {"enabled": False},
            "concentration_limits": {"max_open_positions": 8, "max_per_category_pct": 0.40, "max_per_symbol_pct": 0.20},
            "liquidity_gate": {"max_order_to_minute_volume": 0.01, "min_book_depth_usdt": 100_000},
        }

    def test_disabled_filter_matches_no_filter(self, tmp_path):
        base_cfg = self._no_filter_cfg()
        cfg_disabled = dict(base_cfg)
        cfg_disabled["regime_filter_per_strategy"] = {"enabled": False, "features_path": str(tmp_path / "nonexistent.parquet")}
        ro_base = _make_ro(base_cfg, tmp_path)
        ro_disabled = _make_ro(cfg_disabled, tmp_path)
        sig = _make_signal()
        acct = _make_acct()
        r_base = ro_base.evaluate(sig, acct, market_price=100.0, atr=2.0)
        r_disabled = ro_disabled.evaluate(sig, acct, market_price=100.0, atr=2.0)
        assert type(r_base) is type(r_disabled)
        if isinstance(r_base, Reject) and isinstance(r_disabled, Reject):
            assert r_base.reason == r_disabled.reason
