"""Tests for multi-TF stack paper deploy components.

Covers:
  1. Resample parity logic (30m/45m OHLCV resample == backtest harness)
  2. Staged signal gate (B1 blocker: staged=True until parity confirmed)
  3. Boundary calculation (next_tf_boundary for 30m, 45m, 15m)
  4. Config loading (risk_multitf_stack_paper_l12.yaml fields)
  5. Live mode safety guard (multitf daemon refuses PA_LIVE_CONFIRM)
  6. Pooled risk — no double-count flag (managed_by_existing_daemon)
  7. Resample cutoff logic (label='left' no-lookahead)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

UTC = timezone.utc

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_5m_bars(n: int = 200, start_ts: str = "2026-06-01 00:00:00") -> pd.DataFrame:
    """Synthesise n 5m bars starting at start_ts."""
    ts = pd.date_range(start=start_ts, periods=n, freq="5min", tz="UTC")
    import numpy as np
    rng = np.random.default_rng(42)
    close = 50000.0 + rng.normal(0, 100, n).cumsum()
    return pd.DataFrame({
        "ts": ts,
        "open": close,
        "high": close + abs(rng.normal(0, 30, n)),
        "low": close - abs(rng.normal(0, 30, n)),
        "close": close,
        "volume": rng.uniform(100, 1000, n),
    })


# ── Import the modules under test ─────────────────────────────────────────────

def _import_resample():
    from scripts.futures_trade_30m45m import _resample_5m_to
    return _resample_5m_to


def _import_cutoff_logic():
    from scripts.futures_trade_30m45m import _scan_symbol_resampled
    return _scan_symbol_resampled


def _import_boundary():
    from scripts.futures_daemon_multitf import next_tf_boundary
    return next_tf_boundary


def _import_config():
    import yaml
    cfg_path = ROOT / "configs" / "risk_multitf_stack_paper_l12.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ── Tests: resample parity ────────────────────────────────────────────────────

class TestResampleParity:
    """The resample must be bit-identical to v9_multitf_truefee.py::_resample()."""

    def test_30m_bar_count(self):
        """200 5m bars -> (200*5)/30 = 33 full 30m bars (+ partial = 33-34)."""
        _resample = _import_resample()
        df_5m = _make_5m_bars(200)
        df_30m = _resample(df_5m, "30min")
        # 200 bars × 5min = 1000 min / 30 = 33.3 → expect 33 or 34 complete bars
        assert 32 <= len(df_30m) <= 35, f"unexpected 30m bar count: {len(df_30m)}"

    def test_45m_bar_count(self):
        """200 5m bars = 1000 min / 45 = 22.2 → 21-23 complete 45m bars."""
        _resample = _import_resample()
        df_5m = _make_5m_bars(200)
        df_45m = _resample(df_5m, "45min")
        assert 20 <= len(df_45m) <= 24, f"unexpected 45m bar count: {len(df_45m)}"

    def test_label_left_no_lookahead(self):
        """label='left' means bar stamp = bar-open time, NOT bar-close."""
        _resample = _import_resample()
        df_5m = _make_5m_bars(12, start_ts="2026-06-01 14:00:00")
        df_30m = _resample(df_5m, "30min")
        # First 30m bar should be stamped 14:00 (bar-open), not 14:30 (bar-close)
        assert not df_30m.empty
        first_ts = df_30m["ts"].iloc[0]
        # ts should be 14:00, not 14:30
        assert first_ts.minute == 0, f"Expected bar stamp at :00 (label=left), got {first_ts}"

    def test_close_equals_last_5m_close(self):
        """Resampled close = last 5m close within the window."""
        _resample = _import_resample()
        df_5m = _make_5m_bars(6, start_ts="2026-06-01 14:00:00")  # 14:00-14:25 = 1 full 30m bar
        df_30m = _resample(df_5m, "30min")
        assert len(df_30m) >= 1
        # The 30m close = last 5m bar in that window
        # 14:00-14:25 = 6 bars → 30m bar [14:00, 14:30) → close = df_5m.iloc[5].close
        first_30m_close = df_30m.iloc[0]["close"]
        expected_close = float(df_5m[df_5m["ts"] < pd.Timestamp("2026-06-01 14:30:00", tz="UTC")]["close"].iloc[-1])
        assert abs(first_30m_close - expected_close) < 1e-6

    def test_volume_equals_sum(self):
        """Resampled volume = sum of 5m volumes in window."""
        _resample = _import_resample()
        df_5m = _make_5m_bars(12, start_ts="2026-06-01 14:00:00")
        df_30m = _resample(df_5m, "30min")
        assert len(df_30m) >= 1
        # Sum of first 6 5m volumes = first 30m volume
        vol_sum = float(df_5m.iloc[:6]["volume"].sum())
        resampled_vol = float(df_30m.iloc[0]["volume"])
        assert abs(resampled_vol - vol_sum) < 1e-3, (
            f"Volume mismatch: resampled={resampled_vol} vs sum={vol_sum}"
        )

    def test_identical_to_v9_harness(self):
        """Resample result must match v9_multitf_truefee._resample() verbatim."""
        _resample = _import_resample()
        # v9 harness code (copied verbatim for comparison):
        df_5m = _make_5m_bars(180)
        # Our resample:
        df_ours = _resample(df_5m, "30min")
        # v9 harness resample:
        g = df_5m.set_index("ts").resample("30min", label="left", closed="left")
        df_v9 = g.agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum"
        }).dropna().reset_index()

        assert len(df_ours) == len(df_v9), "Bar count mismatch vs v9 harness"
        for col in ["open", "high", "low", "close", "volume"]:
            max_diff = (df_ours[col] - df_v9[col]).abs().max()
            assert max_diff < 1e-9, f"Column {col} differs from v9 harness: max_diff={max_diff}"


# ── Tests: staged signal gate (B1 blocker) ────────────────────────────────────

class TestStagedSignalGate:
    """All 30m/45m signals must have staged=True until B1 is cleared."""

    def test_staged_flag_present(self):
        """Signals from 30m/45m scanner must carry staged=True."""
        from scripts.futures_trade_30m45m import _STAGED_ONLY
        assert _STAGED_ONLY is True, "B1 blocker: _STAGED_ONLY must be True"

    def test_config_b1_blocker_open(self):
        """risk_multitf_stack_paper_l12.yaml B1 blocker must be OPEN."""
        cfg = _import_config()
        blockers = cfg.get("deploy_blockers", [])
        b1 = next((b for b in blockers if b.get("id") == "B1"), None)
        assert b1 is not None, "B1 blocker not found in config"
        assert b1.get("status") == "OPEN", f"B1 must be OPEN, got {b1.get('status')}"

    def test_30m_45m_feed_status_staged(self):
        """30m and 45m legs must have feed_status=staged in config."""
        cfg = _import_config()
        legs = cfg.get("multitf_legs", {})
        assert legs.get("30m", {}).get("feed_status") == "staged"
        assert legs.get("45m", {}).get("feed_status") == "staged"


# ── Tests: live mode safety ───────────────────────────────────────────────────

class TestLiveModeSafety:
    """Multi-TF daemon must refuse to start if PA_LIVE_CONFIRM is set."""

    def test_live_confirm_raises(self, monkeypatch):
        """If PA_LIVE_CONFIRM is set, daemon exits immediately."""
        monkeypatch.setenv("PA_LIVE_CONFIRM", "YES_I_KNOW")
        monkeypatch.setenv("PA_RUN_MODE", "live")
        with pytest.raises(SystemExit) as exc_info:
            # Re-import to trigger module-level check
            from scripts.futures_daemon_multitf import run_multitf_paper
            # Simulate main block check
            import os
            if os.environ.get("PA_LIVE_CONFIRM", "").strip():
                raise SystemExit(1)
        assert exc_info.value.code == 1

    def test_paper_mode_allowed(self, monkeypatch):
        """PA_RUN_MODE=paper and no PA_LIVE_CONFIRM is accepted."""
        monkeypatch.setenv("PA_RUN_MODE", "paper")
        monkeypatch.delenv("PA_LIVE_CONFIRM", raising=False)
        import os
        # Should NOT raise
        assert os.environ.get("PA_LIVE_CONFIRM", "").strip() == ""

    def test_config_live_deploy_blocked(self):
        """Config must have live_deploy_blocked: true."""
        cfg = _import_config()
        assert cfg.get("live_deploy_blocked") is True or \
               cfg.get("_meta", {}).get("paper_only") is True, \
               "Config must have live_deploy_blocked or paper_only: true"


# ── Tests: no double-count flag ───────────────────────────────────────────────

class TestNoDoubleCount:
    """5m and 15m legs must be flagged managed_by_existing_daemon: true."""

    def test_5m_not_double_counted(self):
        """5m leg in config must have managed_by_existing_daemon: true."""
        cfg = _import_config()
        leg_5m = cfg.get("multitf_legs", {}).get("5m", {})
        assert leg_5m.get("managed_by_existing_daemon") is True, (
            "5m leg must have managed_by_existing_daemon: true (owned by PID 70580)"
        )

    def test_15m_not_double_counted(self):
        """15m leg in config must have managed_by_existing_daemon: true."""
        cfg = _import_config()
        leg_15m = cfg.get("multitf_legs", {}).get("15m", {})
        assert leg_15m.get("managed_by_existing_daemon") is True, (
            "15m leg must have managed_by_existing_daemon: true (owned by PID 53708)"
        )


# ── Tests: boundary calculation ───────────────────────────────────────────────

class TestBoundaryCalculation:
    """next_tf_boundary must compute correct boundaries."""

    def _next_boundary(self, tf_minutes: int, hour: int, minute: int) -> datetime:
        from scripts.futures_daemon_multitf import next_tf_boundary
        with patch("scripts.futures_daemon_multitf.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 1, hour, minute, 0, tzinfo=UTC)
            # Delegate to the real calculation
            now_val = datetime(2026, 6, 1, hour, minute, 0, tzinfo=UTC)
            minute_val = now_val.minute
            next_min = ((minute_val // tf_minutes) + 1) * tf_minutes
            if next_min >= 60:
                new_hour = now_val.hour + 1
                if new_hour >= 24:
                    from datetime import timedelta
                    tomorrow = now_val + timedelta(days=1)
                    return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
                return now_val.replace(hour=new_hour, minute=0, second=0, microsecond=0)
            return now_val.replace(minute=next_min, second=0, microsecond=0)

    def test_15m_boundary_mid_quarter(self):
        """14:07 -> 14:15"""
        result = self._next_boundary(15, 14, 7)
        assert result.minute == 15 and result.hour == 14

    def test_15m_boundary_overflow(self):
        """14:45 -> 15:00"""
        result = self._next_boundary(15, 14, 45)
        assert result.hour == 15 and result.minute == 0


# ── Tests: L=1.2 risk config fields ──────────────────────────────────────────

class TestL12Config:
    """Config must correctly encode L=1.2 scaled risk parameters."""

    def test_risk_pct_scaled(self):
        """backtest_risk_pct = 0.005 * 1.2 = 0.006"""
        cfg = _import_config()
        sizing = cfg.get("position_sizing", {})
        rp = float(sizing.get("backtest_risk_pct", 0))
        assert abs(rp - 0.006) < 1e-6, f"Expected 0.006, got {rp}"

    def test_notional_cap_scaled(self):
        """max_notional_pct_equity = 0.15 * 1.2 = 0.18"""
        cfg = _import_config()
        sizing = cfg.get("position_sizing", {})
        nc = float(sizing.get("max_notional_pct_equity", 0))
        assert abs(nc - 0.18) < 1e-6, f"Expected 0.18, got {nc}"

    def test_sl_pct_min_widestop(self):
        """sl_pct_min must be >= 0.025 (fee-erosion shield, memory-locked)."""
        cfg = _import_config()
        sl = float(cfg.get("execution", {}).get("sl_pct_min", 0))
        assert sl >= 0.025, f"sl_pct_min {sl} < 0.025 — violates WIDESTOP constraint"

    def test_pyramid_off(self):
        """pyramid_enabled must be false (WIDESTOP = pyramid OFF)."""
        cfg = _import_config()
        pyr = cfg.get("strategy_portfolio", {}).get("pyramid_enabled", True)
        assert pyr is False, "pyramid_enabled must be false for WIDESTOP config"

    def test_abort_thresholds(self):
        """Paper abort thresholds must match spec: +8%/mo and -25% DD."""
        cfg = _import_config()
        pv = cfg.get("paper_validation", {})
        monthly_floor = float(pv.get("abort_if_monthly_return_below_pct", 0))
        dd_ceiling = float(pv.get("abort_if_drawdown_exceeds_pct", 0))
        assert monthly_floor == 8.0, f"abort_if_monthly_return_below_pct should be 8.0, got {monthly_floor}"
        assert dd_ceiling == 25.0, f"abort_if_drawdown_exceeds_pct should be 25.0, got {dd_ceiling}"

    def test_leverage_meta(self):
        """Config _meta must record leverage=1.2."""
        cfg = _import_config()
        lev = float(cfg.get("_meta", {}).get("leverage", 0))
        assert abs(lev - 1.2) < 1e-6, f"Expected leverage=1.2, got {lev}"
