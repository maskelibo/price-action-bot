"""Komuta Merkezi Dashboard — FastAPI sunucu (always-on).

Arka plan thread'i collect_all()'ı ~120s'de bir çalıştırır → in-memory cache +
data/dashboard/snapshot.json. Sayfa cache'ten ANINDA yüklenir (income API yavaş;
asla sayfa-yükünde çağrılmaz). Manuel "Yenile" → /api/refresh.

Çalıştır:  .venv/bin/python scripts/dashboard/server.py   → http://127.0.0.1:8787
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

os.environ.setdefault("PA_LOG_QUIET", "1")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# NOT: 'scripts/dashboard.py' (eski Streamlit) ile 'scripts/dashboard/' dizini isim
# çakışıyor → paket import'u yerine collect.py'yi doğrudan dosyadan yükle.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("pa_dash_collect", HERE / "collect.py")
_collect_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_collect_mod)
collect_all = _collect_mod.collect_all

from datetime import UTC  # noqa: E402

import uvicorn  # noqa: E402
from fastapi import Body, FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402

SNAP_PATH = ROOT / "data" / "dashboard" / "snapshot.json"
REFRESH_SEC = 120
PORT = int(os.getenv("PA_DASHBOARD_PORT", "8787"))

# DASHBOARD-FIX 2026-07-08 (DERIN_DENETIM W6-HIGH): canlı acil-durdurma yüzeyi.
# Bulgu netleştirmesi: /admin/halt api/server.py'de vardı ama o API (0.0.0.0:8000)
# HİÇ çalışmıyor; çalışan dashboard'da (8787) halt endpoint'i yoktu → kağıt üstünde
# zincir. Daemon KILL_SWITCH_PATH = logs/kill_switch.json'ı okur (fail-closed);
# aynı dosyaya buradan yazınca gerçek durdurma olur.
# GÜVENLİK (T6): dashboard 127.0.0.1 auth'suz + 2. lokal kullanıcı erişebilir.
# Halt güvenli-taraf (yalnız durdurur) AMA auth'suz = DoS yüzeyi. Bu yüzden
# TOKEN-GUARD fail-closed: PA_DASHBOARD_ADMIN_TOKEN set DEĞİLSE endpoint 403 —
# yeni saldırı yüzeyi AÇMAZ, Principal token verince gerçek durdurma yolu olur.
KILL_SWITCH_PATH = ROOT / "logs" / "kill_switch.json"
_ADMIN_TOKEN = os.getenv("PA_DASHBOARD_ADMIN_TOKEN", "").strip()
_BODY_OPT = Body(default=None)  # B008: modül-seviyesi singleton (arg-default çağrısı yasak)

_cache: dict = {"snapshot": None}
_refreshing = threading.Event()


def _load_initial() -> None:
    if SNAP_PATH.exists():
        try:
            _cache["snapshot"] = json.loads(SNAP_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass


def _refresh() -> None:
    if _refreshing.is_set():
        return
    _refreshing.set()
    try:
        snap = collect_all()
        _cache["snapshot"] = snap
        SNAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAP_PATH.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    except Exception:
        traceback.print_exc()
    finally:
        _refreshing.clear()


def _bg_loop() -> None:
    while True:
        _refresh()
        time.sleep(REFRESH_SEC)


app = FastAPI(title="PA Komuta Merkezi", docs_url=None, redoc_url=None)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (HERE / "index.html").read_text(encoding="utf-8")


@app.get("/api/snapshot")
def snapshot() -> JSONResponse:
    return JSONResponse(_cache["snapshot"] or {"loading": True})


@app.get("/api/refresh")
def refresh() -> dict:
    threading.Thread(target=_refresh, daemon=True).start()
    return {"ok": True}


def _read_halt_state() -> dict:
    if not KILL_SWITCH_PATH.exists():
        return {"halted": False, "reason": None, "ts": None, "by": None}
    try:
        return json.loads(KILL_SWITCH_PATH.read_text(encoding="utf-8"))
    except Exception:
        # Torn-write / parse hatası: daemon fail-closed HALT sayar; burada da öyle raporla.
        return {"halted": True, "reason": "kill_switch parse fail", "ts": None, "by": None}


@app.get("/api/halt_state")
def halt_state() -> dict:
    return _read_halt_state()


@app.post("/admin/halt")
def admin_halt(payload: dict = _BODY_OPT) -> dict:
    """Acil durdurma: logs/kill_switch.json'a halted=true yaz (daemon okur, fail-closed).

    Token-guard fail-closed: PA_DASHBOARD_ADMIN_TOKEN set değilse 403.
    Body: {"token": "...", "reason": "..."}.
    """
    if not _ADMIN_TOKEN:
        raise HTTPException(
            status_code=403,
            detail="admin halt devre dışı — PA_DASHBOARD_ADMIN_TOKEN set edilmemiş (fail-closed)",
        )
    body = payload or {}
    if str(body.get("token", "")) != _ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="geçersiz token")
    reason = str(body.get("reason", "manual dashboard halt"))
    from datetime import datetime

    state = {
        "halted": True,
        "reason": reason,
        "ts": datetime.now(UTC).isoformat(),
        "by": "dashboard_admin",
    }
    KILL_SWITCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    KILL_SWITCH_PATH.write_text(json.dumps(state), encoding="utf-8")
    return {"ok": True, "halted": True, "reason": reason}


@app.post("/admin/resume")
def admin_resume(payload: dict = _BODY_OPT) -> dict:
    """Halt'ı kaldır (halted=false). Aynı token-guard. Daemon restart AYRICA gerekir."""
    if not _ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="admin devre dışı (fail-closed)")
    body = payload or {}
    if str(body.get("token", "")) != _ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="geçersiz token")
    state = {"halted": False, "reason": None, "ts": None, "by": "dashboard_admin"}
    KILL_SWITCH_PATH.write_text(json.dumps(state), encoding="utf-8")
    return {"ok": True, "halted": False}


def main() -> None:
    _load_initial()
    threading.Thread(target=_bg_loop, daemon=True).start()
    print(f"[dashboard] http://127.0.0.1:{PORT}  (refresh {REFRESH_SEC}s)")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
