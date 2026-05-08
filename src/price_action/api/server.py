"""FastAPI uygulaması — health, metrics, equity, trades, positions, admin.

LLM emir vermez; admin endpoint'ler deterministik kill-switch state'ini değiştirir.
Bu modül uygulamayı oluşturur ve uvicorn ile servis eder.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from price_action import __version__
from price_action.api.auth import verify_token
from price_action.api.dashboard import render_dashboard
from price_action.logging_config import logger
from price_action.settings import ensure_dirs, get_settings

# Global "halt" state — file-based, restart-safe
_STATE_FILE_NAME = "kill_switch.json"


# =====================================================================
# Kill-switch state (basit dosya bazlı)
# =====================================================================

def _state_file() -> Path:
    s = get_settings()
    return s.logs_dir / _STATE_FILE_NAME


def _read_halt_state() -> dict[str, Any]:
    p = _state_file()
    if not p.exists():
        return {"halted": False, "reason": None, "ts": None, "by": None}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"halted": False, "reason": None, "ts": None, "by": None}


def _write_halt_state(payload: dict[str, Any]) -> None:
    p = _state_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, default=str), encoding="utf-8")


def is_halted() -> bool:
    return bool(_read_halt_state().get("halted"))


# =====================================================================
# App factory
# =====================================================================

def create_app() -> FastAPI:
    ensure_dirs()
    app = FastAPI(
        title="Price Action API",
        version=__version__,
        description="Otonom price action trading şirketi — operasyon ve gözlem API'si.",
    )

    # ----- /health -----
    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "halted": is_halted(),
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    # ----- /metrics -----
    @app.get("/metrics")
    def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # ----- /equity -----
    @app.get("/equity")
    def equity(days: int = Query(30, ge=1, le=3650)) -> JSONResponse:
        try:
            from price_action.analytics.journal import Journal

            j = Journal()
            df = j.query_trades(start=datetime.now(timezone.utc) - timedelta(days=days))
        except Exception as exc:
            logger.warning("api.equity_failed", extra={"err": str(exc)[:200]})
            return JSONResponse({"points": [], "error": str(exc)[:200]})
        if df.empty:
            return JSONResponse({"points": []})
        df = df.sort_values("exit_ts")
        # synthetic equity from realized pnl
        eq = 10_000.0
        points = []
        for _, row in df.iterrows():
            eq += float(row.get("realized_pnl_usdt", 0.0) or 0.0)
            points.append({"ts": str(row["exit_ts"]), "equity": eq})
        return JSONResponse({"points": points})

    # ----- /trades -----
    @app.get("/trades")
    def trades(limit: int = Query(50, ge=1, le=1000)) -> JSONResponse:
        try:
            from price_action.analytics.journal import Journal

            j = Journal()
            df = j.query_trades(limit=limit)
            return JSONResponse({"trades": json.loads(df.to_json(orient="records", date_format="iso"))})
        except Exception as exc:
            logger.warning("api.trades_failed", extra={"err": str(exc)[:200]})
            return JSONResponse({"trades": [], "error": str(exc)[:200]})

    # ----- /positions -----
    @app.get("/positions")
    def positions() -> JSONResponse:
        try:
            from price_action.analytics.journal import Journal

            j = Journal()
            df = j.query_open_positions()
            return JSONResponse({"positions": json.loads(df.to_json(orient="records", date_format="iso"))})
        except Exception as exc:
            return JSONResponse({"positions": [], "error": str(exc)[:200]})

    # ----- /signals/pending -----
    @app.get("/signals/pending")
    def signals_pending(limit: int = Query(50, ge=1, le=500)) -> JSONResponse:
        try:
            from price_action.analytics.journal import Journal

            j = Journal()
            df = j.query_pending_signals(limit=limit)
            return JSONResponse({"signals": json.loads(df.to_json(orient="records", date_format="iso"))})
        except Exception as exc:
            return JSONResponse({"signals": [], "error": str(exc)[:200]})

    # ----- /admin/halt -----
    @app.post("/admin/halt")
    def admin_halt(
        reason: str = Query("manual"),
        _token: str = Depends(verify_token),
    ) -> dict[str, Any]:
        payload = {
            "halted": True,
            "reason": reason,
            "ts": datetime.now(timezone.utc).isoformat(),
            "by": "admin_api",
        }
        _write_halt_state(payload)
        logger.warning("admin.halt", extra={"reason": reason})
        return payload

    # ----- /admin/resume -----
    @app.post("/admin/resume")
    def admin_resume(_token: str = Depends(verify_token)) -> dict[str, Any]:
        payload = {
            "halted": False,
            "reason": None,
            "ts": datetime.now(timezone.utc).isoformat(),
            "by": "admin_api",
        }
        _write_halt_state(payload)
        logger.info("admin.resume")
        return payload

    # ----- /reports/ceo/latest -----
    @app.get("/reports/ceo/latest", response_class=PlainTextResponse)
    def latest_ceo() -> str:
        return _latest_report("ceo")

    # ----- /reports/analytics/latest -----
    @app.get("/reports/analytics/latest", response_class=PlainTextResponse)
    def latest_analytics() -> str:
        return _latest_report("analytics")

    # ----- /dashboard -----
    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard() -> str:
        try:
            from price_action.analytics.journal import Journal

            j = Journal()
            trades_df = j.query_trades(limit=200)
        except Exception:
            trades_df = None
        return render_dashboard(trades_df=trades_df)

    return app


def _latest_report(folder: str) -> str:
    s = get_settings()
    folder_path = s.reports_dir / folder
    if not folder_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{folder} reports yok")
    files = sorted(folder_path.glob("*.md"), reverse=True)
    if not files:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{folder} dosyası yok")
    return files[0].read_text(encoding="utf-8")


# Module-level app — uvicorn için
app = create_app()


def main() -> None:
    """`python -m price_action.api.server` ya da `pa-api` ile çağrı."""
    import uvicorn

    uvicorn.run(
        "price_action.api.server:app",
        host="0.0.0.0",
        port=8000,
        log_level=get_settings().log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
