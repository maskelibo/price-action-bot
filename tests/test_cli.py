"""CLI smoke testleri — typer's CliRunner ile."""

from __future__ import annotations

from types import SimpleNamespace

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


def test_status_command(monkeypatch):
    monkeypatch.setattr(
        "price_action.analytics.journal.Journal",
        lambda: SimpleNamespace(query_open_positions=lambda: []),
    )
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 0
    assert "version" in r.stdout.lower() or "mode" in r.stdout.lower()


def test_ops_halt_then_resume(tmp_path, monkeypatch):
    state_file = tmp_path / "kill_switch.json"
    monkeypatch.setattr("price_action.api.server._state_file", lambda: state_file)
    r1 = runner.invoke(app, ["ops", "halt", "--reason", "unit"])
    assert r1.exit_code == 0
    assert state_file.exists()
    r2 = runner.invoke(app, ["ops", "resume"])
    assert r2.exit_code == 0
    assert '"halted": false' in state_file.read_text(encoding="utf-8")


def test_ingest_missing_module_clean_error(monkeypatch):
    """data.ingest_ccxt henüz mevcut değilse renkli mesaj + exit-2."""

    def _missing_module(name: str):
        assert name == "price_action.data.ingest_ccxt"
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("price_action.cli.importlib.import_module", _missing_module)
    r = runner.invoke(app, ["ingest", "--venue", "binance", "--tf", "1d", "--years", "1"])
    assert r.exit_code == 2


def test_subapp_help_universe():
    r = runner.invoke(app, ["universe", "--help"])
    assert r.exit_code == 0
