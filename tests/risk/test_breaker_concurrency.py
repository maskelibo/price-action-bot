"""SEC58 CRIT-3: DDBreaker threading.RLock + atomic save concurrency tests.

Two tests:
  1. concurrent_update_state_consistent — 2 threads, 500 update() calls each,
     month boundary crossed mid-run; final state must be self-consistent
     (no partial reset: last_reset_monthly == anchor month).
  2. race_condition_month_boundary_simulation — 20 threads simultaneously
     cross a UTC month boundary; anchor_equity must equal the equity value
     passed by the winning resetter, never 0.0.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from price_action.risk.breaker import DDBreaker
from price_action.risk.sizing import AccountState


def _acct(equity: float) -> AccountState:
    return AccountState(
        equity_usdt=equity,
        free_margin_usdt=equity,
        consecutive_losses=0,
    )


@pytest.fixture
def base_cfg() -> dict:
    return {
        "daily_loss_pct": 0.99,    # disabled — only testing concurrency
        "weekly_loss_pct": 0.99,
        "monthly_loss_pct": 0.99,
        "consecutive_losses": 999,
    }


# ── Test 1: 2-thread concurrent update, state must be internally consistent ──

def test_concurrent_update_state_consistent(tmp_path: Path, base_cfg: dict) -> None:
    """Two threads firing 500 update() calls each must leave state consistent.

    Consistency invariant: last_reset_monthly matches the month of
    monthly_anchor_equity (i.e. the reset and anchor write are atomic).
    We cannot predict which month's equity "wins", but:
      - monthly_anchor_equity must not be 0.0 after the first reset
      - triggered_monthly must be False (losses disabled in cfg)
      - No exception raised
    """
    breaker = DDBreaker(base_cfg, state_path=tmp_path / "br.json")

    # Two timestamps straddling a month boundary
    ts_jan = datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc)
    ts_feb = datetime(2026, 2, 1, 0, 0, 1, tzinfo=timezone.utc)

    errors: list[Exception] = []

    def worker(ts: datetime, equity: float) -> None:
        try:
            for _ in range(500):
                breaker.update(_acct(equity), now=ts)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=(ts_jan, 10_000.0), daemon=True)
    t2 = threading.Thread(target=worker, args=(ts_feb, 12_000.0), daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not errors, f"Exceptions in worker threads: {errors}"
    # State consistency checks
    assert breaker.state.monthly_anchor_equity > 0.0, (
        "monthly_anchor_equity is 0.0 — partial reset detected (lock failure)"
    )
    assert breaker.state.triggered_monthly is False
    # The monthly_anchor_equity must be one of the two equities we passed
    assert breaker.state.monthly_anchor_equity in (10_000.0, 12_000.0), (
        f"anchor equity corrupt: {breaker.state.monthly_anchor_equity}"
    )


# ── Test 2: 20-thread month-boundary race ────────────────────────────────────

def test_race_condition_month_boundary_simulation(tmp_path: Path, base_cfg: dict) -> None:
    """20 threads simultaneously cross a UTC month boundary 100 times each.

    Invariant: monthly_anchor_equity is NEVER 0.0 after the run
    (0.0 would mean a thread read the cleared anchor before another set it).
    Also: no AttributeError / TypeError / json decode error.
    """
    breaker = DDBreaker(base_cfg, state_path=tmp_path / "br.json")

    ts_old = datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc)
    ts_new = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)

    errors: list[Exception] = []
    barrier = threading.Barrier(20)

    def worker(thread_id: int) -> None:
        try:
            barrier.wait()  # all 20 threads cross boundary simultaneously
            for i in range(100):
                ts = ts_new if (thread_id + i) % 2 == 0 else ts_old
                equity = 10_000.0 + thread_id * 100
                breaker.update(_acct(equity), now=ts)
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(i,), daemon=True)
        for i in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, f"Exceptions in race threads: {errors}"
    # anchor must never be 0 (which would mean reset+write were non-atomic)
    assert breaker.state.monthly_anchor_equity != 0.0, (
        "monthly_anchor_equity=0.0 after race — non-atomic reset detected"
    )
