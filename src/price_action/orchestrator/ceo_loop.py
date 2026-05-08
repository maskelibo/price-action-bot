"""CEO main loop — pa-ceo CLI giriş noktası.

`pa-ceo --mode daily|weekly|once` ile çalıştırılır.
- `daily`: APScheduler başlatır, günlük döngü.
- `weekly`: Haftalık özet üretip çıkar.
- `once`: Sadece bir morning brief üret, çıkar (test/CI için).

SIGINT/SIGTERM yakalanır → graceful shutdown.
"""
from __future__ import annotations

import asyncio
import signal
from typing import Any

import typer

from price_action.logging_config import logger
from price_action.settings import ensure_dirs

from .scheduler import build_scheduler, register_jobs

app = typer.Typer(add_completion=False, help="CEO orchestrator — APScheduler.")


async def _run_daemon() -> None:
    ensure_dirs()
    scheduler = build_scheduler()
    register_jobs(scheduler)
    scheduler.start()
    logger.info("ceo_loop.started")
    stop = asyncio.Event()

    def _signal(*_a: Any) -> None:
        logger.info("ceo_loop.signal_received")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal)
        except (NotImplementedError, RuntimeError):
            # Windows / non-main-thread loop
            signal.signal(sig, lambda *_: _signal())
    try:
        await stop.wait()
    finally:
        scheduler.shutdown(wait=False)
        logger.info("ceo_loop.stopped")


async def _run_weekly() -> None:
    from price_action.agents import CEOAgent

    ensure_dirs()
    path = await CEOAgent().weekly_summary()
    typer.echo(str(path))


async def _run_once() -> None:
    from price_action.agents import CEOAgent

    ensure_dirs()
    path = await CEOAgent().daily_brief()
    typer.echo(str(path))


@app.command()
def run(
    mode: str = typer.Option(
        "daily", help="daily | weekly | once", case_sensitive=False
    ),
) -> None:
    """CEO döngüsünü başlatır."""
    mode = mode.lower()
    if mode == "daily":
        asyncio.run(_run_daemon())
    elif mode == "weekly":
        asyncio.run(_run_weekly())
    elif mode == "once":
        asyncio.run(_run_once())
    else:
        raise typer.BadParameter(f"Bilinmeyen mode: {mode}")


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
