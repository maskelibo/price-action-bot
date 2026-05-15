"""Capital Cap Wiring Testleri — Phase1.B1 pre-live checklist.

3 senaryo:
  1. YAML yüklendiğinde cap değeri doğru gelmeli (1000.0 USDT)
  2. cap_expires_at geçmiş tarih ise None dönmeli
  3. enabled: false ise None dönmeli

PA_RUN_MODE=live mock'lanarak test edilir (gerçek borsa çağrısı yok).
"""
from __future__ import annotations

import os
from datetime import date, timedelta, timezone, datetime
from unittest.mock import patch

import pytest

from price_action.execution.capital_cap import load_capital_cap


# ----- yardımcı: minimal config dict'leri -----

def _cfg(
    enabled: bool = True,
    max_usdt: float = 1000.0,
    expires_at: str | None = None,
    warn_pct: float = 0.80,
) -> dict:
    """risk_balanced.yaml'ın live_capital_cap bloğunu taklit eden dict."""
    cap_block: dict = {
        "enabled": enabled,
        "max_equity_usdt": max_usdt,
        "warn_threshold_pct": warn_pct,
    }
    if expires_at is not None:
        cap_block["cap_expires_at"] = expires_at
    return {"live_capital_cap": cap_block}


def _future_date(days: int = 30) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


def _past_date(days: int = 1) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()


# ===== Test 1: YAML'dan cap değeri doğru yüklenmeli =====

def test_capital_cap_loaded_from_yaml():
    """PA_RUN_MODE=live + enabled + gelecek tarih → 1000.0 dönmeli."""
    config = _cfg(enabled=True, max_usdt=1000.0, expires_at=_future_date(30))

    with patch.dict(os.environ, {"PA_RUN_MODE": "live"}):
        cap = load_capital_cap(config)

    assert cap == 1000.0, f"Beklenen 1000.0, gelen {cap}"


# ===== Test 2: cap_expires_at geçmişse None =====

def test_capital_cap_expired_returns_none():
    """cap_expires_at dün ise, live modda dahi None dönmeli."""
    config = _cfg(enabled=True, max_usdt=1000.0, expires_at=_past_date(1))

    with patch.dict(os.environ, {"PA_RUN_MODE": "live"}):
        cap = load_capital_cap(config)

    assert cap is None, f"Süresi dolmuş cap None olmalı, gelen {cap}"


# ===== Test 3: enabled: false ise None =====

def test_capital_cap_disabled():
    """enabled: false ise PA_RUN_MODE=live dahi olsa None dönmeli."""
    config = _cfg(enabled=False, max_usdt=1000.0, expires_at=_future_date(30))

    with patch.dict(os.environ, {"PA_RUN_MODE": "live"}):
        cap = load_capital_cap(config)

    assert cap is None, f"Disabled cap None olmalı, gelen {cap}"


# ===== Ek güvenlik testleri =====

def test_capital_cap_paper_mode_always_none():
    """PA_RUN_MODE=paper → her zaman None (backward compat)."""
    config = _cfg(enabled=True, max_usdt=1000.0, expires_at=_future_date(30))

    with patch.dict(os.environ, {"PA_RUN_MODE": "paper"}):
        cap = load_capital_cap(config)

    assert cap is None, "Paper modda cap None olmalı"


def test_capital_cap_backtest_mode_always_none():
    """PA_RUN_MODE=backtest → her zaman None."""
    config = _cfg(enabled=True, max_usdt=1000.0, expires_at=_future_date(30))

    with patch.dict(os.environ, {"PA_RUN_MODE": "backtest"}):
        cap = load_capital_cap(config)

    assert cap is None, "Backtest modda cap None olmalı"


def test_capital_cap_missing_block_returns_none():
    """live_capital_cap bloğu hiç yoksa None."""
    config: dict = {}  # boş config

    with patch.dict(os.environ, {"PA_RUN_MODE": "live"}):
        cap = load_capital_cap(config)

    assert cap is None


def test_capital_cap_exact_expiry_day_still_active():
    """cap_expires_at bugünün tarihi ise hâlâ aktif (> değil >= değil, sadece >)."""
    today = datetime.now(timezone.utc).date().isoformat()
    config = _cfg(enabled=True, max_usdt=500.0, expires_at=today)

    with patch.dict(os.environ, {"PA_RUN_MODE": "live"}):
        cap = load_capital_cap(config)

    # Bugün == expires_at → aktif (sadece yarından itibaren expire)
    assert cap == 500.0, f"Bugün == expiry günü hâlâ aktif olmalı, gelen {cap}"
