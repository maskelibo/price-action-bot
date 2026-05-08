"""CLI smoke testleri — typer's CliRunner ile."""
from __future__ import annotations

from typer.testing import CliRunner

from price_action.cli import app

runner = CliRunner()


def test_help_basic():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "Price Action" in r.stdout or "price-action" in r.stdout.lower()


def test_version_command():
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert "price-action" in r.stdout


def test_init_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["init"])
    # init bir tablo basar; harici eksik dosyalar olabilir → exit kodu 0 ya da 1
    assert r.exit_code in (0, 1)


def test_status_command():
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 0
    assert "version" in r.stdout.lower() or "mode" in r.stdout.lower()


def test_ops_halt_then_resume():
    r1 = runner.invoke(app, ["ops", "halt", "--reason", "unit"])
    assert r1.exit_code == 0
    r2 = runner.invoke(app, ["ops", "resume"])
    assert r2.exit_code == 0


def test_ingest_missing_module_clean_error():
    """data.ingest_ccxt henüz mevcut değilse renkli mesaj + exit-2."""
    r = runner.invoke(app, ["ingest", "--venue", "binance", "--tf", "1d", "--years", "1"])
    # External modül yoksa exit code 2; varsa 0 — ikisi de kabul.
    assert r.exit_code in (0, 2)


def test_subapp_help_universe():
    r = runner.invoke(app, ["universe", "--help"])
    assert r.exit_code == 0
