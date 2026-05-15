"""APScheduler entegrasyonu.

Tüm günlük/haftalık LLM job'larını kayıt eder. Job fonksiyonları async;
APScheduler ``AsyncIOScheduler`` üstünde döner.

Job listesi:
- ingest_data (saatlik)            — Data dept (placeholder hook)
- daily_research (02:00 UTC)       — Researcher
- signal_scan (1d kapanış sonrası) — Signal Chief (placeholder)
- execute_orders                   — Execution (placeholder)
- daily_kpi (23:00 UTC)            — Analyst + CEO daily_brief
- weekly_lab_tournament (Paz 03:00) — Lab Scientist
- weekly_drift (Paz 03:30)         — Lab
- weekly_rag_refresh (Paz 04:00)   — Lab
- monthly_review (ay sonu)         — CEO weekly_summary genelleştirilmiş
"""
from __future__ import annotations

from typing import Any

from price_action.logging_config import logger


def build_scheduler() -> Any:
    """``AsyncIOScheduler`` instance'ı döndürür."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "apscheduler yüklü değil — `pip install apscheduler`"
        ) from exc
    return AsyncIOScheduler(timezone="UTC")


# ----------------------------------------------------------------------
# Job fonksiyonları (async)
# ----------------------------------------------------------------------

async def _job_ingest_data() -> None:
    """Saatlik OHLCV ingest. Deterministik ingest_ccxt modülünü çağırır.

    Hata olursa logla; scheduler'ı düşürme.
    """
    try:
        from price_action.data import ingest_ccxt  # type: ignore[import-untyped]

        if hasattr(ingest_ccxt, "run_hourly"):
            await ingest_ccxt.run_hourly()  # type: ignore[attr-defined]
            return
    except Exception as exc:
        logger.warning("scheduler.ingest_skip", extra={"err": str(exc)[:200]})


async def _job_daily_research() -> None:
    """Researcher: günlük hipotez taraması."""
    try:
        from price_action.agents import ResearcherAgent

        await ResearcherAgent().propose_hypothesis(
            "Günlük tarama: yeni RAG ekleri ışığında price action edge sinyalleri"
        )
    except Exception as exc:
        logger.warning("scheduler.daily_research_fail", extra={"err": str(exc)[:200]})


async def _job_signal_scan() -> None:
    """Signal Chief deterministik tarama (placeholder)."""
    try:
        from price_action import signals  # type: ignore[import-untyped]

        if hasattr(signals, "run_daily_scan"):
            await signals.run_daily_scan()  # type: ignore[attr-defined]
    except Exception as exc:
        logger.warning("scheduler.signal_scan_skip", extra={"err": str(exc)[:200]})


async def _job_execute_orders() -> None:
    """Execution emir akışı — futures testnet/live daily_run çağrısı.

    PA_RUN_MODE=paper  → futures_daemon.py testnet'e gönderir
    PA_RUN_MODE=live   → PA_LIVE_CONFIRM=YES_I_KNOW + live_mode_enabled=true zorunlu
    PA_RUN_MODE=backtest → hiçbir şey gönderilmez (log only)

    Scheduler'dan ayrı olarak futures_daemon.py da kendi döngüsünde çalışır;
    bu job scheduler wiring'ini kapatır (SEC20 show-stopper fix).
    """
    import asyncio
    from datetime import datetime, timedelta, timezone

    from price_action.settings import get_settings

    s = get_settings()
    logger.info(
        "scheduler.execute_orders_tick",
        extra={"mode": s.pa_run_mode, "is_live": s.is_live},
    )

    if s.pa_run_mode == "backtest":
        logger.info("scheduler.execute_orders_skip_backtest")
        return

    try:
        from scripts.futures_trade_daily import daily_run  # type: ignore[import-not-found]

        target = datetime.now(timezone.utc) - timedelta(days=1)
        dry = not s.is_live  # live değilse dry_run=True (paper/testnet)

        logger.info(
            "scheduler.execute_orders_run",
            extra={"target": str(target.date()), "dry_run": dry},
        )
        await asyncio.to_thread(daily_run, target, dry)
        logger.info("scheduler.execute_orders_done", extra={"date": str(target.date())})
    except ImportError:
        logger.warning("scheduler.execute_orders_import_fail",
                       extra={"hint": "scripts/futures_trade_daily.py bulunamadı"})
    except Exception as exc:
        logger.error("scheduler.execute_orders_fail", extra={"err": str(exc)[:300]})


async def _job_daily_kpi() -> None:
    """Analyst günlük KPI brief + CEO morning brief."""
    try:
        from price_action.agents import AnalystAgent, CEOAgent

        await AnalystAgent().daily_kpi_brief()
        await CEOAgent().daily_brief()
    except Exception as exc:
        logger.warning("scheduler.daily_kpi_fail", extra={"err": str(exc)[:200]})


async def _job_weekly_tournament() -> None:
    """Lab haftalık tournament — gerçek strateji listesi placeholder."""
    try:
        from price_action.agents import LabScientistAgent

        # Gerçek champion/challenger Lab tarafından yüklenir; burada hook.
        await LabScientistAgent().weekly_tournament(
            champion={"id": "noop", "oos_returns": [], "oos_sharpe": 0, "oos_maxdd": 0},
            challengers=[],
        )
    except Exception as exc:
        logger.warning("scheduler.tournament_fail", extra={"err": str(exc)[:200]})


async def _job_weekly_drift() -> None:
    try:
        from price_action.agents import LabScientistAgent

        lab = LabScientistAgent()
        # Gerçek seriler journal'dan gelir; placeholder boş seriler.
        result = lab.drift_detect([], [])
        if result.get("alert"):
            lab.append_learning(
                f"Drift alert: {result}", slug="drift-alert", confidence="high"
            )
    except Exception as exc:
        logger.warning("scheduler.drift_fail", extra={"err": str(exc)[:200]})


async def _job_weekly_rag_refresh() -> None:
    try:
        from price_action.agents import LabScientistAgent

        await LabScientistAgent().rag_refresh(since_days=7)
    except Exception as exc:
        logger.warning("scheduler.rag_refresh_fail", extra={"err": str(exc)[:200]})


async def _job_monthly_review() -> None:
    try:
        from price_action.agents import CEOAgent

        await CEOAgent().weekly_summary()
    except Exception as exc:
        logger.warning("scheduler.monthly_review_fail", extra={"err": str(exc)[:200]})


# ----------------------------------------------------------------------
# Kayıt
# ----------------------------------------------------------------------

JOB_TABLE: tuple[tuple[str, str, str, Any], ...] = (
    # (id, kind, expr, func)
    ("ingest_data", "cron", "0 * * * *", _job_ingest_data),  # saatlik :00
    ("daily_research", "cron", "0 2 * * *", _job_daily_research),
    ("signal_scan", "cron", "5 0 * * *", _job_signal_scan),
    ("execute_orders", "cron", "10 0 * * *", _job_execute_orders),
    ("daily_kpi", "cron", "0 23 * * *", _job_daily_kpi),
    ("weekly_lab_tournament", "cron", "0 3 * * sun", _job_weekly_tournament),
    ("weekly_drift", "cron", "30 3 * * sun", _job_weekly_drift),
    ("weekly_rag_refresh", "cron", "0 4 * * sun", _job_weekly_rag_refresh),
    ("monthly_review", "cron", "0 6 28-31 * *", _job_monthly_review),
)


def _add_cron(scheduler: Any, expr: str, func: Any, job_id: str) -> None:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"Geçersiz cron expr: {expr}")
    minute, hour, day, month, dow = parts
    scheduler.add_job(
        func,
        "cron",
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=dow,
        id=job_id,
        replace_existing=True,
        misfire_grace_time=3600,
    )


def register_jobs(scheduler: Any) -> list[str]:
    """Tüm job'ları kayıt eder. Geri dönüş: kayıtlanan job id listesi."""
    registered: list[str] = []
    for job_id, kind, expr, func in JOB_TABLE:
        if kind != "cron":
            continue
        _add_cron(scheduler, expr, func, job_id)
        registered.append(job_id)
    logger.info("scheduler.jobs_registered", extra={"jobs": registered})
    return registered
