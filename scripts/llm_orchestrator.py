"""Faz 5 — LLM Orchestrator.

Günlük brief, haftalık özet, post-mortem, kriz alarmı ve watchdog modu.

Usage
-----
    # Günlük brief (manuel / cron)
    PYTHONPATH=src python scripts/llm_orchestrator.py --mode daily-brief

    # Dry-run (gerçek LLM/Telegram çağrısı yapılmaz)
    PYTHONPATH=src PA_LLM_DRY_RUN=true python scripts/llm_orchestrator.py --mode daily-brief --dry-run

    # Haftalık özet
    PYTHONPATH=src python scripts/llm_orchestrator.py --mode weekly-summary

    # Post-mortem (trade_id ile)
    PYTHONPATH=src python scripts/llm_orchestrator.py --mode post-mortem --trade-id paper-faz6-abc123

    # Kriz alarmı
    PYTHONPATH=src python scripts/llm_orchestrator.py --mode crit-alarm --reason "daily DD %5 aşıldı"

    # Watchdog (APScheduler ile sürekli mod)
    PYTHONPATH=src python scripts/llm_orchestrator.py --watchdog

Env vars
--------
PA_LLM_DRY_RUN=true        — LLM ve Telegram çağrıları atlanır
PA_LLM_BRIEF_TIME=09:00    — daily-brief UTC saati (varsayılan 09:00)
PA_LLM_WEEKLY_DAY=Sunday   — weekly-summary günü (varsayılan Sunday)
TELEGRAM_BOT_TOKEN          — Telegram bot token
TELEGRAM_CHAT_ID            — Telegram chat ID
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# Ensure src is on path
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from price_action.logging_config import logger
from price_action.notifications.telegram import send_critical, send_telegram

# =====================================================================
# Constants
# =====================================================================

JOURNAL_PATH = _ROOT / "data" / "paper_journal.duckdb"
REPORTS_CEO_DIR = _ROOT / "reports" / "ceo"
REPORTS_CEO_DIR.mkdir(parents=True, exist_ok=True)


def _is_dry_run(args: argparse.Namespace | None = None) -> bool:
    """dry-run modu: --dry-run argümanı VEYA PA_LLM_DRY_RUN env var."""
    if args is not None and getattr(args, "dry_run", False):
        return True
    return os.environ.get("PA_LLM_DRY_RUN", "").lower() in ("1", "true", "yes")


# =====================================================================
# Journal reader (DuckDB, defansif)
# =====================================================================

def _read_journal_summary() -> dict[str, Any]:
    """paper_journal.duckdb'den günlük özet çek. DB yoksa boş döner."""
    result: dict[str, Any] = {
        "available": False,
        "open_trades": 0,
        "closed_today": 0,
        "total_pnl": 0.0,
        "equity": None,
    }
    if not JOURNAL_PATH.exists():
        return result
    try:
        import duckdb  # type: ignore[import-not-found]

        today = date.today().isoformat()
        conn = duckdb.connect(str(JOURNAL_PATH), read_only=True)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE status='open'"
            ).fetchone()
            result["open_trades"] = row[0] if row else 0

            row2 = conn.execute(
                "SELECT COUNT(*), SUM(realized_pnl) FROM paper_trades "
                "WHERE status='closed' AND CAST(exit_ts AS VARCHAR) LIKE ?",
                [f"{today}%"],
            ).fetchone()
            result["closed_today"] = row2[0] if row2 else 0
            result["total_pnl"] = float(row2[1] or 0.0) if row2 else 0.0

            eq_row = conn.execute(
                "SELECT equity FROM paper_equity_snapshots ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            result["equity"] = float(eq_row[0]) if eq_row else None
            result["available"] = True
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("orchestrator.journal_read_fail", extra={"err": str(exc)[:200]})
    return result


def _get_closed_trade(trade_id: str) -> dict[str, Any] | None:
    """Belirli bir trade'i journal'dan çek."""
    if not JOURNAL_PATH.exists():
        return None
    try:
        import duckdb  # type: ignore[import-not-found]

        conn = duckdb.connect(str(JOURNAL_PATH), read_only=True)
        try:
            row = conn.execute(
                "SELECT trade_id, symbol, side, entry_ts, exit_ts, "
                "entry_price, exit_price, realized_pnl, r_multiple, "
                "pattern_id, confluence_score, strategy_id, exit_reason "
                "FROM paper_trades WHERE trade_id=?",
                [trade_id],
            ).fetchone()
            if row is None:
                return None
            cols = [
                "trade_id", "symbol", "side", "entry_ts", "exit_ts",
                "entry_price", "exit_price", "realized_pnl", "r_multiple",
                "pattern_id", "confluence_score", "strategy_id", "exit_reason",
            ]
            return dict(zip(cols, row))
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("orchestrator.trade_read_fail", extra={"err": str(exc)[:200]})
        return None


# =====================================================================
# Idempotency helpers
# =====================================================================

def _report_already_exists(mode: str, label: str) -> bool:
    """Aynı gün/hafta için rapor zaten yazıldıysa True döner."""
    if mode == "daily-brief":
        path = REPORTS_CEO_DIR / f"{label}-brief.md"
        return path.exists()
    if mode == "weekly-summary":
        path = REPORTS_CEO_DIR / f"{label}-weekly.md"
        return path.exists()
    return False


# =====================================================================
# Mode: daily-brief
# =====================================================================

async def run_daily_brief(dry_run: bool = False) -> dict[str, Any]:
    """CEO günlük morning brief — idempotent (aynı gün 2x çalışmaz)."""
    today = date.today()
    label = today.isoformat()

    if not dry_run and _report_already_exists("daily-brief", label):
        logger.info(
            "orchestrator.daily_brief.already_done",
            extra={"date": label},
        )
        send_telegram(
            f"Daily brief {label} zaten mevcut — atlandı.",
            level="INFO",
        )
        return {"status": "skipped", "reason": "already_exists", "date": label}

    journal = _read_journal_summary()
    journal_context = (
        f"Journal özeti ({label}): "
        f"Açık pozisyon={journal['open_trades']}, "
        f"Bugün kapandı={journal['closed_today']}, "
        f"Bugün PnL={journal['total_pnl']:.2f} USDT"
        + (f", Equity={journal['equity']:.2f} USDT" if journal["equity"] else "")
        if journal["available"]
        else "Journal verisi mevcut değil (DuckDB bağlantı yok veya ilk çalıştırma)."
    )

    if dry_run:
        logger.info(
            "orchestrator.daily_brief.dry_run",
            extra={"date": label, "journal_context": journal_context},
        )
        dry_report = (
            f"# CEO Morning Brief — {label}\n\n"
            f"[DRY RUN — gerçek LLM çağrısı yapılmadı]\n\n"
            f"## Journal Özeti\n{journal_context}\n\n"
            f"## Beklenen İçerik\n"
            "- Dünkü Analytics raporu özeti\n"
            "- Açık pozisyon snapshot\n"
            "- Günün öne çıkan watch-item'ları\n"
            "- Risk breaker durumu\n"
        )
        out_path = REPORTS_CEO_DIR / f"{label}-brief.md"
        out_path.write_text(dry_report, encoding="utf-8")
        return {
            "status": "dry_run",
            "date": label,
            "report_path": str(out_path),
            "journal": journal,
        }

    # Gerçek LLM çağrısı
    from price_action.agents import CEOAgent

    try:
        ceo = CEOAgent()
        report_path = await ceo.daily_brief(when=today)
        report_text = report_path.read_text(encoding="utf-8")

        # Telegram'a gönder (ilk 3000 karakter — Telegram limiti 4096)
        telegram_msg = (
            f"*CEO Morning Brief — {label}*\n\n"
            + report_text[:2800]
            + ("\n\n_(truncated)_" if len(report_text) > 2800 else "")
        )
        send_telegram(telegram_msg, level="INFO", parse_mode="Markdown")

        logger.info(
            "orchestrator.daily_brief.done",
            extra={"date": label, "path": str(report_path)},
        )
        return {
            "status": "ok",
            "date": label,
            "report_path": str(report_path),
            "journal": journal,
        }
    except Exception as exc:
        err_msg = f"Daily brief hatası: {exc}"
        logger.error("orchestrator.daily_brief.fail", extra={"err": str(exc)[:300]})
        send_telegram(err_msg, level="ERROR")
        return {"status": "error", "error": str(exc), "date": label}


# =====================================================================
# Mode: weekly-summary
# =====================================================================

async def run_weekly_summary(dry_run: bool = False) -> dict[str, Any]:
    """CEO haftalık özet + Researcher hipotez taraması + Lab tournament özeti."""
    iso = datetime.now(timezone.utc).isocalendar()
    week_label = f"{iso.year}-W{iso.week:02d}"

    if not dry_run and _report_already_exists("weekly-summary", week_label):
        logger.info(
            "orchestrator.weekly_summary.already_done",
            extra={"week": week_label},
        )
        return {"status": "skipped", "reason": "already_exists", "week": week_label}

    if dry_run:
        logger.info("orchestrator.weekly_summary.dry_run", extra={"week": week_label})
        dry_report = (
            f"# CEO Weekly Summary — {week_label}\n\n"
            "[DRY RUN — gerçek LLM çağrısı yapılmadı]\n\n"
            "## Beklenen İçerik\n"
            "- Net P&L, Sharpe, MaxDD, profit factor\n"
            "- Researcher hipotez tarama özeti\n"
            "- Lab tournament sonuçları\n"
            "- Drift uyarıları\n"
            "- Önümüzdeki hafta 3 watch-item\n"
        )
        out_path = REPORTS_CEO_DIR / f"{week_label}-weekly.md"
        out_path.write_text(dry_report, encoding="utf-8")
        return {"status": "dry_run", "week": week_label, "report_path": str(out_path)}

    from price_action.agents import CEOAgent, ResearcherAgent

    results: dict[str, Any] = {"status": "ok", "week": week_label, "steps": {}}

    # 1) Researcher hipotez taraması
    try:
        researcher = ResearcherAgent()
        hyp = await researcher.propose_hypothesis(
            f"Haftalık tarama {week_label}: geçen hafta paper trading sonuçları "
            "ışığında engulfing_continuation için yeni veya iyileştirilmiş edge sinyalleri"
        )
        results["steps"]["researcher"] = "ok"
        logger.info("orchestrator.weekly_summary.researcher_done")
    except Exception as exc:
        logger.warning("orchestrator.weekly_summary.researcher_fail", extra={"err": str(exc)[:200]})
        results["steps"]["researcher"] = f"error: {exc}"

    # 2) CEO haftalık özet
    try:
        ceo = CEOAgent()
        report_path = await ceo.weekly_summary(week_label=week_label)
        results["steps"]["ceo"] = "ok"
        results["report_path"] = str(report_path)
        report_text = report_path.read_text(encoding="utf-8")

        telegram_msg = (
            f"*CEO Weekly Summary — {week_label}*\n\n"
            + report_text[:2800]
            + ("\n\n_(truncated)_" if len(report_text) > 2800 else "")
        )
        send_telegram(telegram_msg, level="INFO", parse_mode="Markdown")
    except Exception as exc:
        logger.warning("orchestrator.weekly_summary.ceo_fail", extra={"err": str(exc)[:200]})
        results["steps"]["ceo"] = f"error: {exc}"
        results["status"] = "partial"

    return results


# =====================================================================
# Mode: post-mortem
# =====================================================================

async def run_post_mortem(trade_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Belirli bir trade için Analyst post-mortem raporu."""
    if dry_run:
        logger.info("orchestrator.post_mortem.dry_run", extra={"trade_id": trade_id})
        return {
            "status": "dry_run",
            "trade_id": trade_id,
            "message": "Gerçek post-mortem için --dry-run olmadan çalıştır",
        }

    trade = _get_closed_trade(trade_id)
    if trade is None:
        logger.warning("orchestrator.post_mortem.trade_not_found", extra={"trade_id": trade_id})
        send_telegram(f"Post-mortem: trade_id={trade_id} journal'da bulunamadı.", level="WARNING")
        return {"status": "error", "reason": "trade_not_found", "trade_id": trade_id}

    from price_action.agents import AnalystAgent

    try:
        analyst = AnalystAgent()
        report_path = await analyst.postmortem(trade)
        report_text = report_path.read_text(encoding="utf-8")

        symbol = trade.get("symbol", "?")
        pnl = trade.get("realized_pnl", 0.0)
        telegram_msg = (
            f"*Trade Post-Mortem — {symbol}*\n"
            f"trade_id: `{trade_id}`\n"
            f"P&L: {pnl:.2f} USDT\n\n"
            + report_text[:2200]
            + ("\n\n_(truncated)_" if len(report_text) > 2200 else "")
        )
        send_telegram(telegram_msg, level="INFO", parse_mode="Markdown")
        logger.info("orchestrator.post_mortem.done", extra={"trade_id": trade_id, "path": str(report_path)})
        return {"status": "ok", "trade_id": trade_id, "report_path": str(report_path)}
    except Exception as exc:
        logger.error("orchestrator.post_mortem.fail", extra={"err": str(exc)[:300]})
        return {"status": "error", "error": str(exc), "trade_id": trade_id}


# =====================================================================
# Mode: crit-alarm
# =====================================================================

async def run_crit_alarm(reason: str, dry_run: bool = False) -> dict[str, Any]:
    """Kriz protokolü — CEO crisis_protocol çağırır + Telegram CRIT gönderir."""
    logger.warning("orchestrator.crit_alarm.triggered", extra={"reason": reason[:300]})

    if dry_run:
        logger.info("orchestrator.crit_alarm.dry_run", extra={"reason": reason})
        return {"status": "dry_run", "reason": reason}

    # Önce Telegram CRIT gönder (LLM'den önce — hızlı uyarı)
    send_critical(f"KRİZ ALARMI TETIKLENDI\n\nSebep: {reason}\n\nCEO kriz protokolü başlatıldı...")

    from price_action.agents import CEOAgent

    try:
        ceo = CEOAgent()
        report_path = await ceo.crisis_protocol(reason=reason)
        report_text = report_path.read_text(encoding="utf-8")

        # CEO'nun önerisini de Telegram'a gönder
        send_critical(
            f"CEO KRİZ ÖNERİSİ:\n\n"
            + report_text[:2500]
            + ("\n\n_(truncated — tam rapor dosyada)_" if len(report_text) > 2500 else "")
        )
        logger.info("orchestrator.crit_alarm.done", extra={"path": str(report_path)})
        return {"status": "ok", "reason": reason, "report_path": str(report_path)}
    except Exception as exc:
        err_msg = f"CEO kriz protokolü başarısız: {exc}"
        logger.error("orchestrator.crit_alarm.fail", extra={"err": str(exc)[:300]})
        send_critical(err_msg)
        return {"status": "error", "error": str(exc), "reason": reason}


# =====================================================================
# Watchdog — APScheduler tabanlı sürekli mod
# =====================================================================

def _parse_brief_time() -> tuple[int, int]:
    """PA_LLM_BRIEF_TIME=HH:MM → (hour, minute)."""
    raw = os.environ.get("PA_LLM_BRIEF_TIME", "09:00")
    try:
        parts = raw.strip().split(":")
        return int(parts[0]), int(parts[1])
    except Exception:
        logger.warning("orchestrator.watchdog.invalid_brief_time", extra={"raw": raw})
        return 9, 0


def _parse_weekly_day() -> str:
    """PA_LLM_WEEKLY_DAY=Sunday → APScheduler day_of_week string."""
    raw = os.environ.get("PA_LLM_WEEKLY_DAY", "Sunday").strip().lower()
    mapping = {
        "monday": "mon", "tuesday": "tue", "wednesday": "wed",
        "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
        "mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu",
        "fri": "fri", "sat": "sat", "sun": "sun",
    }
    return mapping.get(raw, "sun")


def _build_apscheduler() -> Any:
    """APScheduler AsyncIOScheduler oluştur."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-not-found]
        return AsyncIOScheduler(timezone="UTC")
    except ImportError as exc:
        raise RuntimeError(
            "apscheduler yüklü değil — `pip install apscheduler` veya `uv add apscheduler`"
        ) from exc


async def _watchdog_daily_brief_job(dry_run: bool) -> None:
    try:
        result = await run_daily_brief(dry_run=dry_run)
        logger.info("orchestrator.watchdog.daily_brief", extra={"result_status": result.get("status")})
    except Exception as exc:
        logger.error("orchestrator.watchdog.daily_brief_fail", extra={"err": str(exc)[:200]})
        send_critical(f"Watchdog daily-brief hatası: {exc}")


async def _watchdog_weekly_summary_job(dry_run: bool) -> None:
    try:
        result = await run_weekly_summary(dry_run=dry_run)
        logger.info("orchestrator.watchdog.weekly_summary", extra={"result_status": result.get("status")})
    except Exception as exc:
        logger.error("orchestrator.watchdog.weekly_summary_fail", extra={"err": str(exc)[:200]})
        send_critical(f"Watchdog weekly-summary hatası: {exc}")


def run_watchdog(dry_run: bool = False) -> None:
    """APScheduler ile sürekli modu başlat."""
    import functools

    scheduler = _build_apscheduler()
    brief_hour, brief_minute = _parse_brief_time()
    weekly_dow = _parse_weekly_day()

    # Daily brief: her gün PA_LLM_BRIEF_TIME UTC'de
    scheduler.add_job(
        functools.partial(_watchdog_daily_brief_job, dry_run),
        "cron",
        hour=brief_hour,
        minute=brief_minute,
        id="llm_daily_brief",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Weekly summary: PA_LLM_WEEKLY_DAY 18:00 UTC
    scheduler.add_job(
        functools.partial(_watchdog_weekly_summary_job, dry_run),
        "cron",
        day_of_week=weekly_dow,
        hour=18,
        minute=0,
        id="llm_weekly_summary",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    logger.info(
        "orchestrator.watchdog.started",
        extra={
            "daily_brief_utc": f"{brief_hour:02d}:{brief_minute:02d}",
            "weekly_summary_day": weekly_dow,
            "dry_run": dry_run,
        },
    )
    send_telegram(
        f"LLM Orchestrator watchdog başlatıldı.\n"
        f"Daily brief: {brief_hour:02d}:{brief_minute:02d} UTC\n"
        f"Weekly summary: {weekly_dow} 18:00 UTC",
        level="INFO",
    )

    # Event loop — scheduler asyncio ile çalışır
    try:
        loop = asyncio.get_event_loop()
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("orchestrator.watchdog.stopping")
        scheduler.shutdown()
        send_telegram("LLM Orchestrator watchdog durduruldu.", level="WARNING")


# =====================================================================
# Entry point
# =====================================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Faz 5 LLM Orchestrator — daily brief, weekly summary, post-mortem, crit-alarm"
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--mode",
        choices=["daily-brief", "weekly-summary", "post-mortem", "crit-alarm"],
        help="Çalıştırılacak mod",
    )
    mode_group.add_argument(
        "--watchdog",
        action="store_true",
        help="APScheduler ile sürekli mod",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="LLM ve Telegram çağrıları yapılmaz (test/CI modu)",
    )
    parser.add_argument(
        "--trade-id",
        dest="trade_id",
        default=None,
        help="post-mortem modu için trade ID",
    )
    parser.add_argument(
        "--reason",
        default=None,
        help="crit-alarm modu için tetikleyici sebep",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    dry_run = _is_dry_run(args)

    if args.watchdog:
        run_watchdog(dry_run=dry_run)
        return

    if args.mode is None:
        parser.print_help()
        sys.exit(1)

    result: dict[str, Any] = {}

    if args.mode == "daily-brief":
        result = asyncio.run(run_daily_brief(dry_run=dry_run))
    elif args.mode == "weekly-summary":
        result = asyncio.run(run_weekly_summary(dry_run=dry_run))
    elif args.mode == "post-mortem":
        if not args.trade_id:
            parser.error("--mode post-mortem için --trade-id gerekli")
        result = asyncio.run(run_post_mortem(args.trade_id, dry_run=dry_run))
    elif args.mode == "crit-alarm":
        reason = args.reason or "Manuel kriz alarmı tetiklendi"
        result = asyncio.run(run_crit_alarm(reason=reason, dry_run=dry_run))

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
