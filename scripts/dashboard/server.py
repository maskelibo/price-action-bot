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

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402

SNAP_PATH = ROOT / "data" / "dashboard" / "snapshot.json"
REFRESH_SEC = 120
PORT = int(os.getenv("PA_DASHBOARD_PORT", "8787"))

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


def main() -> None:
    _load_initial()
    threading.Thread(target=_bg_loop, daemon=True).start()
    print(f"[dashboard] http://127.0.0.1:{PORT}  (refresh {REFRESH_SEC}s)")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
