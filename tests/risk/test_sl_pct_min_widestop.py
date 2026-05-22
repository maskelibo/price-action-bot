"""WIRE-widestop (2026-05-22): sl_pct_min causal filter — unit + parity tests.

DEPLOY_widestop_15m.md WIRE step 4. Verifies the wide-stop deploy filter
wired into the backtest engine (lab.ProductionConfig.sl_pct_min +
production_replay):

  1. Default OFF (sl_pct_min=0.0) → no trade dropped (byte-identical).
  2. sl_pct_min=0.025 → narrow-stop trades dropped, n decreases.
  3. Boundary: a trade with sl_pct exactly == threshold is KEPT (>=).
  4. PARITY: the engine's internal filter is byte-identical to an external
     pre-filter — this is the property that makes production_replay reproduce
     scripts/lab_15m_widestop_dd_opt.py (which pre-filters the pool itself).
  5. All-narrow pool → production_replay returns None.
  6. YAML wiring: risk_phoenix_scalp_15m_widestop.yaml → 0.025; c2v5 → 0.0.

sl_pct = |entry_price - initial_sl| / entry_price, known at entry from ATR
→ causal, no look-ahead.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from price_action.backtest.lab import ProductionConfig, production_replay

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Synthetic trade pool — deterministic, varying sl_pct
# ---------------------------------------------------------------------------


def _make_trades(n: int, sl_pcts: list[float], entry_price: float = 100.0):
    """n long trades; trade i gets sl_pct = sl_pcts[i % len(sl_pcts)].

    lab.production_replay needs entry_price + initial_sl on each trade.
    sl_pct = |entry - sl| / entry; long → sl = entry * (1 - sl_pct).
    """
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        sl_pct = sl_pcts[i % len(sl_pcts)]
        sl_price = entry_price * (1.0 - sl_pct)
        is_win = (i % 2 == 0)
        out.append({
            "entry_ts": base + timedelta(hours=i * 6),
            "exit_ts": base + timedelta(hours=i * 6 + 2),
            "symbol": "BTC/USDT",
            "side": "long",
            "strategy": "test_strat",
            "R": 2.0 if is_win else -1.0,
            "conf": 0.5,
            "conf_pct": 0.5,
            "entry_price": entry_price,
            "initial_sl": sl_price,
        })
    return out


def _base_cfg(**overrides) -> ProductionConfig:
    """Deterministic replay — breakers/cooldown OFF so the sl_pct filter is the
    only variable. sl_pct_min defaults to 0.0 unless overridden."""
    cfg = ProductionConfig(
        risk_pct=0.005,
        conf_min=0.0,
        max_concurrent=50,
        same_symbol_side_cooldown_days=0.0,
        initial_capital=10_000.0,
        consecutive_loss_n=None,
        daily_dd=0.99, weekly_dd=0.99, monthly_dd=0.99,
    )
    return cfg.with_overrides(**overrides) if overrides else cfg


def _sl_pct(t: dict) -> float:
    return abs(t["initial_sl"] - t["entry_price"]) / t["entry_price"]


# ---------------------------------------------------------------------------
# 1) Default OFF — sl_pct_min=0.0 drops nothing
# ---------------------------------------------------------------------------


def test_default_off_keeps_all_trades():
    """sl_pct_min=0.0 (default) → filter block skipped → every trade replayed."""
    pool = _make_trades(80, sl_pcts=[0.015, 0.035])
    cfg = _base_cfg()  # sl_pct_min defaults 0.0
    assert cfg.sl_pct_min == 0.0

    r = production_replay(pool, cfg)
    assert r is not None
    # cooldown/breakers OFF, conf_min 0 → all 80 trades replay
    assert r.trades == 80, f"sl_pct_min=0.0 must drop nothing, got {r.trades}"


# ---------------------------------------------------------------------------
# 2) sl_pct_min=0.025 → narrow-stop trades dropped
# ---------------------------------------------------------------------------


def test_widestop_threshold_drops_narrow_trades():
    """sl_pct_min=0.025 → only sl_pct >= 0.025 trades survive."""
    pool = _make_trades(80, sl_pcts=[0.015, 0.035])  # 40 narrow / 40 wide
    r_off = production_replay(pool, _base_cfg())
    r_ws = production_replay(pool, _base_cfg(sl_pct_min=0.025))
    assert r_off is not None and r_ws is not None

    n_wide = sum(1 for t in pool if _sl_pct(t) >= 0.025)
    assert n_wide == 40
    assert r_ws.trades == n_wide, (
        f"sl_pct_min=0.025 should keep {n_wide} wide trades, got {r_ws.trades}"
    )
    assert r_ws.trades < r_off.trades, "wide-stop filter must reduce trade count"


# ---------------------------------------------------------------------------
# 3) Boundary — sl_pct exactly == threshold is KEPT (>= comparison)
# ---------------------------------------------------------------------------


def test_threshold_boundary_is_inclusive():
    """A trade with sl_pct exactly == sl_pct_min is kept (filter uses >=)."""
    pool = _make_trades(20, sl_pcts=[0.025])  # every trade exactly at threshold
    r = production_replay(pool, _base_cfg(sl_pct_min=0.025))
    assert r is not None
    assert r.trades == 20, "sl_pct == threshold must be KEPT (>=), not dropped"

    # just below threshold → all dropped
    pool_below = _make_trades(20, sl_pcts=[0.0249])
    r_below = production_replay(pool_below, _base_cfg(sl_pct_min=0.025))
    assert r_below is None, "sl_pct just below threshold → all dropped → None"


# ---------------------------------------------------------------------------
# 4) PARITY — engine internal filter == external pre-filter
# ---------------------------------------------------------------------------


def test_engine_filter_equals_external_prefilter():
    """The engine's internal sl_pct_min filter is byte-identical to an external
    pre-filter feeding an unfiltered config.

    This is the WIRE-4 parity property: scripts/lab_15m_widestop_dd_opt.py
    pre-filters the pool (`sub = [t for t in pool if sl_pct >= thr]`) then calls
    production_replay; the live engine instead carries cfg.sl_pct_min. Both
    paths MUST produce identical replays.
    """
    pool = _make_trades(150, sl_pcts=[0.012, 0.020, 0.028, 0.040, 0.060])
    thr = 0.025

    # Path A — external pre-filter (the lab script's method), no sl_pct_min
    sub = [t for t in pool if _sl_pct(t) >= thr]
    r_external = production_replay(sub, _base_cfg())

    # Path B — engine internal filter on the full pool
    r_engine = production_replay(pool, _base_cfg(sl_pct_min=thr))

    assert r_external is not None and r_engine is not None
    assert r_engine.trades == r_external.trades
    assert r_engine.final_equity == r_external.final_equity, (
        f"parity break: engine {r_engine.final_equity} "
        f"vs external {r_external.final_equity}"
    )
    assert r_engine.max_drawdown == r_external.max_drawdown
    assert r_engine.sum_r == r_external.sum_r
    assert r_engine.win_rate == r_external.win_rate


def test_parity_holds_across_thresholds():
    """Parity must hold at every threshold in the lab script's sweep."""
    pool = _make_trades(200, sl_pcts=[0.010, 0.018, 0.022, 0.025, 0.030, 0.050])
    for thr in (0.018, 0.020, 0.022, 0.025, 0.030):
        sub = [t for t in pool if _sl_pct(t) >= thr]
        r_external = production_replay(sub, _base_cfg())
        r_engine = production_replay(pool, _base_cfg(sl_pct_min=thr))
        if r_external is None:
            assert r_engine is None, f"thr={thr}: external None but engine not"
            continue
        assert r_engine is not None
        assert r_engine.final_equity == r_external.final_equity, f"thr={thr}"
        assert r_engine.trades == r_external.trades, f"thr={thr}"
        assert r_engine.max_drawdown == r_external.max_drawdown, f"thr={thr}"


# ---------------------------------------------------------------------------
# 5) All-narrow pool → None
# ---------------------------------------------------------------------------


def test_all_narrow_pool_returns_none():
    """If every trade is below sl_pct_min → no trade survives → None."""
    pool = _make_trades(40, sl_pcts=[0.010, 0.015, 0.020])  # all < 0.025
    r = production_replay(pool, _base_cfg(sl_pct_min=0.025))
    assert r is None


# ---------------------------------------------------------------------------
# 6) YAML wiring — widestop config carries 0.025, c2v5 stays 0.0
# ---------------------------------------------------------------------------


def test_yaml_widestop_config_sets_threshold():
    """risk_phoenix_scalp_15m_widestop.yaml → sl_pct_min=0.025 + DD-opt values."""
    cfg = ProductionConfig.from_yaml(
        str(REPO_ROOT / "configs" / "risk_phoenix_scalp_15m_widestop.yaml")
    )
    assert cfg.sl_pct_min == 0.025
    assert cfg.risk_pct == 0.005
    assert cfg.daily_dd == 0.02
    assert cfg.weekly_dd == 0.05
    assert cfg.pyramid_enabled is False


def test_yaml_c2v5_config_keeps_filter_off():
    """c2v5 final YAML must stay sl_pct_min=0.0 — live bot behavior unchanged."""
    cfg = ProductionConfig.from_yaml(
        str(REPO_ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml")
    )
    assert cfg.sl_pct_min == 0.0, (
        "c2v5 config must NOT carry sl_pct_min — WIRE keeps live bot byte-identical"
    )
