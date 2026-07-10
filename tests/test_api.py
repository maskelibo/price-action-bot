"""FastAPI smoke testleri — TestClient ile."""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("PA_ADMIN_TOKEN", "test-token-secret")
    # Settings cache'i temizle
    from price_action.settings import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    from price_action.analytics import journal as journal_module
    from price_action.api import server

    class _EmptyJournal:
        def query_trades(self, *args, **kwargs):
            return pd.DataFrame()

        def query_open_positions(self):
            return pd.DataFrame()

        def query_pending_signals(self, *args, **kwargs):
            return pd.DataFrame()

    monkeypatch.setattr(server, "_state_file", lambda: tmp_path / "kill_switch.json")
    monkeypatch.setattr(journal_module, "Journal", _EmptyJournal)

    app = server.create_app()
    return TestClient(app)


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_metrics_exposes_prometheus(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    text = r.text
    # Bizim tanımlı metric'ler dump'ta görünmeli
    assert "pa_orders_total" in text or "# HELP" in text


def test_trades_smoke(client):
    r = client.get("/trades?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert "trades" in body


def test_positions_smoke(client):
    r = client.get("/positions")
    assert r.status_code == 200
    assert "positions" in r.json()


def test_signals_smoke(client):
    r = client.get("/signals/pending")
    assert r.status_code == 200
    assert "signals" in r.json()


def test_admin_halt_requires_token(client):
    r = client.post("/admin/halt")
    assert r.status_code == 401


def test_admin_halt_with_valid_token(client):
    r = client.post(
        "/admin/halt",
        headers={"X-Admin-Token": "test-token-secret"},
        params={"reason": "unit-test"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["halted"] is True
    # resume
    r2 = client.post(
        "/admin/resume",
        headers={"X-Admin-Token": "test-token-secret"},
    )
    assert r2.status_code == 200
    assert r2.json()["halted"] is False


def test_admin_halt_bad_token(client):
    r = client.post(
        "/admin/halt",
        headers={"X-Admin-Token": "wrong-token-aa"},
    )
    assert r.status_code == 403


def test_dashboard_renders(client):
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Price Action" in r.text
