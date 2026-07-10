"""Dashboard halt zinciri — kapanış sprinti 2026-07-08 (DERIN_DENETIM W6-HIGH).

Canlı dashboard'a (8787, çalışan servis) fail-closed token-guard'lı /admin/halt
eklendi. Daemon KILL_SWITCH_PATH = logs/kill_switch.json'ı okur → aynı dosyaya
yazınca gerçek durdurma. Token yoksa 403 (yeni DoS yüzeyi açmaz).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def _load_server(monkeypatch, tmp_path, token: str | None):
    """server.py'yi izole kill_switch yolu + token ile taze yükle."""
    if token is None:
        monkeypatch.delenv("PA_DASHBOARD_ADMIN_TOKEN", raising=False)
    else:
        monkeypatch.setenv("PA_DASHBOARD_ADMIN_TOKEN", token)
    spec = importlib.util.spec_from_file_location(
        "pa_dash_server_test", ROOT / "scripts" / "dashboard" / "server.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "KILL_SWITCH_PATH", tmp_path / "kill_switch.json")
    return mod


def test_halt_disabled_without_token(monkeypatch, tmp_path):
    mod = _load_server(monkeypatch, tmp_path, token=None)
    client = TestClient(mod.app)
    r = client.post("/admin/halt", json={"reason": "test"})
    assert r.status_code == 403
    assert not (tmp_path / "kill_switch.json").exists()  # dosya YAZILMADI


def test_halt_rejects_wrong_token(monkeypatch, tmp_path):
    mod = _load_server(monkeypatch, tmp_path, token="secret")
    client = TestClient(mod.app)
    r = client.post("/admin/halt", json={"token": "yanlis", "reason": "x"})
    assert r.status_code == 403
    assert not (tmp_path / "kill_switch.json").exists()


def test_halt_writes_kill_switch_with_valid_token(monkeypatch, tmp_path):
    mod = _load_server(monkeypatch, tmp_path, token="secret")
    client = TestClient(mod.app)
    r = client.post("/admin/halt", json={"token": "secret", "reason": "acil"})
    assert r.status_code == 200
    ks = json.loads((tmp_path / "kill_switch.json").read_text())
    assert ks["halted"] is True
    assert ks["reason"] == "acil"
    assert ks["by"] == "dashboard_admin"


def test_daemon_reads_same_path_as_dashboard_writes(monkeypatch, tmp_path):
    """Zincir bütünlüğü: dashboard'ın yazdığı yol = daemon'ın okuduğu yol.

    Daemon ve dashboard aynı PA_RUNTIME_ROOT/logs/kill_switch.json yolunu kullanır.
    Source-pin ile iki tarafın da aynı override sözleşmesine bağlı kaldığını doğrula.
    """
    daemon_src = (ROOT / "scripts" / "futures_daemon.py").read_text(encoding="utf-8")
    dash_src = (ROOT / "scripts" / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert 'KILL_SWITCH_PATH = LOGS_DIR / "kill_switch.json"' in daemon_src
    assert 'KILL_SWITCH_PATH = RUNTIME_ROOT / "logs" / "kill_switch.json"' in dash_src


def test_resume_clears_halt(monkeypatch, tmp_path):
    mod = _load_server(monkeypatch, tmp_path, token="secret")
    client = TestClient(mod.app)
    client.post("/admin/halt", json={"token": "secret", "reason": "x"})
    r = client.post("/admin/resume", json={"token": "secret"})
    assert r.status_code == 200
    ks = json.loads((tmp_path / "kill_switch.json").read_text())
    assert ks["halted"] is False


def test_halt_state_reports_parse_fail_as_halted(monkeypatch, tmp_path):
    """Torn-write parse hatası → fail-closed HALT raporu (daemon davranışıyla hizalı)."""
    mod = _load_server(monkeypatch, tmp_path, token="secret")
    (tmp_path / "kill_switch.json").write_text("{bozuk json", encoding="utf-8")
    client = TestClient(mod.app)
    r = client.get("/api/halt_state")
    assert r.status_code == 200
    assert r.json()["halted"] is True


def test_dashboard_monitors_v15p2_not_retired_daemons(monkeypatch, tmp_path):
    """collect.py izleme hedefi v15p2 (emekli v14/5m kalıcı-down yalanı bitti)."""
    src = (ROOT / "scripts" / "dashboard" / "collect.py").read_text(encoding="utf-8")
    assert "com.priceaction.futures_v15p2" in src
    assert "futures_daemon_v15p2.log" in src
    assert "com.priceaction.futures_v14" not in src
    assert "com.priceaction.futures5m" not in src
