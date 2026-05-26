"""CEO main loop — pa-ceo CLI giriş noktası.

`pa-ceo --mode daily|weekly|once [--telegram]` ile çalıştırılır.
- `daily`: APScheduler başlatır, günlük döngü.
- `weekly`: Haftalık özet üretip çıkar.
- `once`: Sadece bir morning brief üret, çıkar (test/CI için).

`--telegram` flag (veya `PA_CEO_PUSH_TELEGRAM=true` env) → üretilen rapor
otomatik Telegram'a push edilir. Faz 1.2 path unification — eski
``llm_orchestrator.py`` shim'ine dönüştü; bu modül tek doğru yer.

SIGINT/SIGTERM yakalanır → graceful shutdown.
"""
from __future__ import annotations

import asyncio
import os
import signal
from typing import Any

import typer

from price_action.logging_config import logger
from price_action.settings import ensure_dirs, get_settings

from .scheduler import build_scheduler, register_jobs

app = typer.Typer(add_completion=False, help="CEO orchestrator — APScheduler.")


def _apply_telegram_env(telegram: bool) -> None:
    """`--telegram` flag'i env'e yaz (push helper bunu okur).

    `notifications.should_push()` `PA_CEO_PUSH_TELEGRAM` env'ini kontrol eder.
    Flag tanımlanmışsa override eder; yoksa mevcut env değeri kalır.
    """
    if telegram:
        os.environ["PA_CEO_PUSH_TELEGRAM"] = "true"


async def _canary_check(scheduler: Any) -> None:
    """FIX 2026-05-26 (Faz 14.7): Canary — restart sonrası 120s içinde
    min 1 job tetiklenmiş mi kontrol et. Yoksa CRIT alert.

    Önceki bug (H2 ThreadPoolExecutor): scheduler register'di görünüyor
    ama hiç job çalışmıyor (3 saat sessiz felç). Bu canary aynı pattern
    tekrarlanırsa 2 dakika içinde yakalar.
    """
    await asyncio.sleep(120)  # 2 dk bekle
    try:
        # APScheduler jobs içinde herhangi birinin last_run_time'ı 2 dk içinde mi?
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=120)
        jobs = scheduler.get_jobs()
        # APScheduler private attr — next_run_time + son tetiği bilemiyoruz doğrudan.
        # Alternatif: app.log'da son 120s scheduler.* log var mı?
        from pathlib import Path
        log_path = Path("logs/app.log")
        recent_jobs_fired = 0
        if log_path.exists():
            try:
                with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()[-500:]
                import re as _re
                for line in lines:
                    if "scheduler." not in line:
                        continue
                    m = _re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                    if not m:
                        continue
                    try:
                        ts = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
                        if ts >= cutoff:
                            recent_jobs_fired += 1
                    except Exception:
                        continue
            except Exception:
                pass
        if recent_jobs_fired == 0:
            logger.error(
                "ceo_loop.canary_dead",
                extra={"n_jobs_registered": len(jobs), "fired_last_120s": 0},
            )
            try:
                from .notifications import push_critical
                push_critical(
                    f"🐦 CANARY DEAD: CEO daemon restart sonrası 120s'de "
                    f"HİÇBİR cron tetiklenmedi (registered jobs: {len(jobs)}). "
                    f"Scheduler felç olabilir (önceki H2 bug paterni). "
                    f"Debug: logs/launchd/ceo.stderr.log + verify_scheduler.py",
                    source="ceo_canary",
                )
            except Exception:
                pass
        else:
            logger.info(
                "ceo_loop.canary_ok",
                extra={"n_jobs_registered": len(jobs), "fired_last_120s": recent_jobs_fired},
            )
    except Exception as exc:
        logger.warning("ceo_loop.canary_check_fail", extra={"err": str(exc)[:200]})


async def _run_daemon() -> None:
    ensure_dirs()
    scheduler = build_scheduler()
    register_jobs(scheduler)
    scheduler.start()
    logger.info(
        "ceo_loop.started",
        extra={"telegram_push": os.environ.get("PA_CEO_PUSH_TELEGRAM", "false")},
    )
    # FIX 2026-05-26: canary background task — felç tespiti
    asyncio.create_task(_canary_check(scheduler))
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
    _push_if_enabled(path, caption="CEO Weekly Summary")


async def _run_once() -> None:
    from price_action.agents import CEOAgent

    ensure_dirs()
    path = await CEOAgent().daily_brief()
    typer.echo(str(path))
    _push_if_enabled(path, caption="CEO Morning Brief")


def _push_if_enabled(path: Any, *, caption: str | None = None) -> None:
    """Üretilen raporu Telegram'a gönder (env aktifse).

    Faz 1.2 unification — `llm_orchestrator.py`'deki dağınık çağrılar burada.
    `should_push()` üç koşulu (env_var + dry-run + credentials) tek noktada
    kontrol eder; biri eksikse sessizce skip.
    """
    try:
        from .notifications import push_report, should_push

        if not should_push():
            return
        # FIX 2026-05-25: parse_mode=None — Markdown breaks on _ in captions/paths
        push_report(path, level="INFO", caption=caption, parse_mode=None)
    except Exception as exc:
        # Telegram push'un hata vermesi rapor üretimini DURDURMAMALI.
        logger.warning(
            "ceo_loop.push_fail",
            extra={"path": str(path), "err": str(exc)[:200]},
        )


@app.command()
def run(
    mode: str = typer.Option(
        "daily", help="daily | weekly | once", case_sensitive=False
    ),
    telegram: bool = typer.Option(
        False,
        "--telegram/--no-telegram",
        help="Üretilen raporu Telegram'a push et (env PA_CEO_PUSH_TELEGRAM override).",
    ),
) -> None:
    """CEO döngüsünü başlatır."""
    _apply_telegram_env(telegram)
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
