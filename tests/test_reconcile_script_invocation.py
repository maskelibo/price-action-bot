"""reconcile script-direct koşum import fix — dalga-5 A1-03 (2026-07-09).

e957f0c fix'i kod-doğru ama üretimde ETKİSİZDİ: `python scripts/reconcile_
journal.py` (scheduler'ın çağrısı) sys.path[0]=scripts/ koyar, repo kökü path'te
OLMAZ → `from scripts.futures_trade_daily import ...` ModuleNotFoundError →
try/except yutar → log-fallback → SAFE_MODE → güvenlik ağı kapalı kalır.
Testler geçiyordu çünkü test harness ROOT'u sys.path'e ekliyor — klasik
"test-yeşil, üretim-ölü". Bu test ÜRETİM-BİREBİR semantikle doğrular.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"


def test_script_direct_invocation_resolves_scripts_package():
    """Script-direct sys.path semantiğinde (repo kökü YOK) header fix'i
    scripts paketini çözülebilir yapmalı. importlib ile __file__ doğru,
    main KOŞMAZ (canlıya temas yok)."""
    code = f"""
import importlib.util, sys
ROOT = {str(ROOT)!r}
sys.path = [p for p in sys.path if p not in ("", ROOT)]
sys.path.insert(0, ROOT + "/scripts")
spec = importlib.util.spec_from_file_location("rj_probe", ROOT + "/scripts/reconcile_journal.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
from scripts.futures_trade_daily import get_futures_exchange
print("IMPORT_OK")
"""
    out = subprocess.run(
        [str(PY), "-c", code], capture_output=True, text=True, cwd=str(ROOT), timeout=60
    )
    assert "IMPORT_OK" in out.stdout, f"stdout={out.stdout[-300:]} stderr={out.stderr[-300:]}"


def test_module_header_inserts_repo_root():
    """Kaynak-pin: header _REPO'yu sys.path'e ekliyor (regresyon önleme)."""
    src = (ROOT / "scripts" / "reconcile_journal.py").read_text(encoding="utf-8")
    assert "sys.path.insert(0, str(_REPO))" in src


def test_scheduler_surfaces_fetch_fail():
    """A1-03 görünürlük: scheduler, exchange_fetch_ok=false koşusunu WARNING
    loglamalı — sessiz SAFE_MODE bir daha haftalarca görünmez kalamaz."""
    src = (ROOT / "src/price_action/orchestrator/scheduler.py").read_text(encoding="utf-8")
    fn = src[
        src.find("async def _job_reconcile_journal") : src.find("\nasync def _job_truth_report")
    ]
    assert '"exchange_fetch_ok": false' in fn, "scheduler fetch-fail görünürlüğü yok"
    assert "reconcile_safe_mode" in fn or "reconcile_fetch_fail" in fn


"""Not: sys.executable yerine .venv python kullanılır — üretim yorumlayıcısı."""
