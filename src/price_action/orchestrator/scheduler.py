"""APScheduler entegrasyonu.

Tüm günlük/haftalık LLM job'larını kayıt eder. Job fonksiyonları async;
APScheduler ``AsyncIOScheduler`` üstünde döner.

Job listesi:
- ingest_data (saatlik)            — Data dept (placeholder hook)
- daily_research (02:00 UTC)       — Researcher
- signal_scan (1d kapanış sonrası) — Signal Chief (placeholder)
- execute_orders                   — Execution (placeholder)
- daily_kpi (23:00 UTC)            — Analyst + CEO daily_brief
- daily_whatif (23:30 UTC)         — Analyst what-if counterfactual (Faz 2.3)
- review_inbox (HH:15 saatlik)     — Risk Officer inbox review (Faz 2.3)
- weekly_lab_tournament (Paz 03:00) — Lab Scientist
- weekly_drift (Paz 03:30)         — Lab
- weekly_rag_refresh (Paz 04:00)   — Lab
- monthly_review (ay sonu)         — CEO weekly_summary genelleştirilmiş
"""
from __future__ import annotations

from pathlib import Path
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
    """Analyst günlük KPI brief + CEO morning brief + Telegram push."""
    try:
        from price_action.agents import AnalystAgent, CEOAgent

        await AnalystAgent().daily_kpi_brief()
        brief_path = await CEOAgent().daily_brief()
        _push_report_safe(brief_path, level="INFO", caption="CEO Morning Brief")
    except Exception as exc:
        logger.warning("scheduler.daily_kpi_fail", extra={"err": str(exc)[:200]})


async def _job_weekly_tournament() -> None:
    """Lab haftalık tournament — gerçek strateji listesi placeholder.

    Faz 1.2: terfi adayı bulunursa Telegram push (latest tournament dosyası).
    """
    try:
        from price_action.agents import LabScientistAgent

        # Gerçek champion/challenger Lab tarafından yüklenir; burada hook.
        result = await LabScientistAgent().weekly_tournament(
            champion={"id": "noop", "oos_returns": [], "oos_sharpe": 0, "oos_maxdd": 0},
            challengers=[],
        )
        # Tournament dosyası yazılıyorsa push (reports/lab/ son rapor)
        _push_latest_safe("lab", "tournament-*.md", level="INFO",
                          caption="Lab Tournament Result")
        return result  # silenced unused var lint
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
            # Faz 1.2: drift alarmı → Telegram WARN
            _push_critical_safe(
                f"DRIFT detected: {result}",
                source="lab_scientist",
            )
    except Exception as exc:
        logger.warning("scheduler.drift_fail", extra={"err": str(exc)[:200]})


async def _job_weekly_rag_refresh() -> None:
    try:
        from price_action.agents import LabScientistAgent

        await LabScientistAgent().rag_refresh(since_days=7)
        # Faz 1.2: RAG refresh raporu — sessiz başarı, sadece hata push
    except Exception as exc:
        logger.warning("scheduler.rag_refresh_fail", extra={"err": str(exc)[:200]})


async def _job_monthly_review() -> None:
    try:
        from price_action.agents import CEOAgent

        path = await CEOAgent().weekly_summary()
        _push_report_safe(path, level="INFO", caption="CEO Monthly Review")
    except Exception as exc:
        logger.warning("scheduler.monthly_review_fail", extra={"err": str(exc)[:200]})


# ----------------------------------------------------------------------
# Faz 2.3 — what-if + inbox review job'ları
# ----------------------------------------------------------------------

async def _job_daily_whatif() -> None:
    """Analyst what-if counterfactual — günlük (23:30 UTC).

    Son 7 gün rejected sinyallerinin 'filtre olmasaydı' PnL'ini hesaplar.
    Çıktı protokol-uyumlu doc; Risk Officer review queue'sine girer.
    Telegram push sadece filter_loss önemli (>%5) ise.
    """
    try:
        from price_action.agents import AnalystAgent

        path = await AnalystAgent().whatif_analysis(window_days=7)
        if not isinstance(path, Path):
            # write_doc=False döndü → dict
            logger.info("scheduler.whatif_no_doc", extra={"stats": str(path)[:200]})
            return
        # Filter cost büyükse push et (notifications.yaml condition: filter_loss_pct >= 5)
        # Şu an için her zaman push; Faz 4'te conditional logic eklenir
        _push_report_safe(path, level="INFO", caption="Analyst What-If Analysis")
    except Exception as exc:
        logger.warning("scheduler.whatif_fail", extra={"err": str(exc)[:200]})


async def _job_review_inbox() -> None:
    """Risk Officer inbox review — saatlik (HH:15).

    inbox.jsonl'i tara, recipient=risk_officer + ack_at=null doc'ları batch
    işle. Batch size 5 (Sonnet, light reasoning, hourly).
    """
    try:
        from price_action.agents import RiskOfficerAgent

        ro = RiskOfficerAgent()
        results = await ro.review_all_pending(max_items=5)
        if results:
            logger.info("scheduler.inbox_reviewed", extra={"n": len(results)})
    except Exception as exc:
        logger.warning("scheduler.inbox_review_fail", extra={"err": str(exc)[:200]})


async def _job_scan_drift_alerts() -> None:
    """Researcher drift response — her 30dk (HH:45).

    inbox.jsonl'i tara, recipient=researcher + topic=drift_alert + ack_at=null
    olanları işle. Cooldown logic ResearcherAgent içinde (max 3 hipotez/drift,
    7g reject sonrası bekleme).
    """
    try:
        from price_action.agents import ResearcherAgent

        r = ResearcherAgent()
        results = await r.respond_to_pending_drifts(max_items=3)
        if results:
            logger.info("scheduler.drift_responses_written", extra={"n": len(results)})
    except Exception as exc:
        logger.warning("scheduler.drift_scan_fail", extra={"err": str(exc)[:200]})


# ----------------------------------------------------------------------
# Faz 4.2 — Token budget report
# ----------------------------------------------------------------------

async def _job_hourly_token_check() -> None:
    """Saatlik token budget kontrol — H3 FIX.

    Eskiden token kontrolü Pazar haftalık — bir agent Pazartesi blow up etse
    6 gün sessizlik. Şimdi her saat kontrol; daily limit aşımı CRIT push.
    """
    try:
        from price_action.ops.token_budget import (
            check_budget,
            get_token_stats,
            load_budget_config,
        )

        stats = get_token_stats(window_hours=24)
        config = load_budget_config()
        alerts = check_budget(stats, config)
        if not alerts:
            return

        crit_alerts = [a for a in alerts if a.get("level") == "CRIT"]
        warn_alerts = [a for a in alerts if a.get("level") == "WARN"]

        if crit_alerts:
            agents_over = ", ".join(f"{a['agent']} ({a['pct']}%)" for a in crit_alerts)
            _push_critical_safe(
                f"🚨 Daily token budget AŞILDI: {agents_over}",
                source="ops_engineer",
            )
            logger.error(
                "scheduler.token_crit",
                extra={"alerts": crit_alerts},
            )
        elif warn_alerts:
            # WARN: kısa Telegram mesaj, throttle ile
            agents_warn = ", ".join(f"{a['agent']} ({a['pct']}%)" for a in warn_alerts)
            try:
                from .notifications import should_push
                from price_action.notifications.telegram import send_telegram
                if should_push():
                    send_telegram(
                        f"⚠️ Token budget %80+ — {agents_warn}",
                        level="WARNING",
                    )
            except Exception:
                pass
            logger.warning(
                "scheduler.token_warn",
                extra={"alerts": warn_alerts},
            )
    except Exception as exc:
        logger.warning("scheduler.hourly_token_fail", extra={"err": str(exc)[:200]})


async def _job_health_check() -> None:
    """H4 FIX: Saatlik sistem sağlık kontrolü.

    - futures_daemon process var mı? (PID kontrolü)
    - logs/futures_daemon.log son 30dk'da update edildi mi?
    - Inbox.jsonl > 1MB mı? (rotation gerekebilir)
    - logs/ disk > 1GB mı?

    Bir sorun varsa Telegram WARN push.
    """
    try:
        import os
        import subprocess
        from datetime import datetime as _dt, timezone as _tz

        from price_action.settings import get_settings as _gs

        s = _gs()
        issues: list[str] = []

        # 1. futures_daemon process check (ps aux | grep)
        try:
            out = subprocess.run(
                ["pgrep", "-f", "futures_daemon"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.returncode != 0:
                issues.append("futures_daemon process YOK")
        except Exception:
            pass

        # 2. futures_daemon.log freshness
        flog = s.reports_dir.parent / "logs" / "futures_daemon.log"
        if flog.exists():
            age_min = (_dt.now().timestamp() - flog.stat().st_mtime) / 60
            if age_min > 30:
                issues.append(f"futures_daemon.log {int(age_min)}dk eski (>30dk)")

        # 3. Inbox boyut
        inbox = s.memory_dir / "protocol" / "inbox.jsonl"
        if inbox.exists():
            size_mb = inbox.stat().st_size / 1024 / 1024
            if size_mb > 1.0:
                issues.append(f"inbox.jsonl {size_mb:.1f}MB (>1MB) — consolidation yaklaşıyor")

        # 4. logs disk
        logs_dir = s.reports_dir.parent / "logs"
        if logs_dir.exists():
            try:
                out = subprocess.run(["du", "-sm", str(logs_dir)], capture_output=True, text=True, timeout=10)
                if out.stdout:
                    mb = int(out.stdout.split()[0])
                    if mb > 1024:
                        issues.append(f"logs/ {mb}MB (>1GB) — rotation gecikmiş")
            except Exception:
                pass

        if issues:
            _push_critical_safe(
                "🏥 Health check uyarısı: " + "; ".join(issues),
                source="ops_engineer",
            )
            logger.warning("scheduler.health_issues", extra={"issues": issues})
        else:
            logger.info("scheduler.health_ok")
    except Exception as exc:
        logger.warning("scheduler.health_check_fail", extra={"err": str(exc)[:200]})


async def _job_weekly_token_report() -> None:
    """OpsAgent haftalık token usage raporu (Pazar 05:00 UTC).

    Prometheus pa_llm_tokens_total → per-agent breakdown + bütçe kontrolü.
    Limit aşımı varsa Telegram CRIT push.
    """
    try:
        from price_action.agents import OpsAgent
        from price_action.ops.token_budget import (
            build_weekly_report,
            check_budget,
            get_token_stats,
            load_budget_config,
        )

        stats = get_token_stats(window_hours=24 * 7)
        config = load_budget_config()
        alerts = check_budget(stats, config)
        body = build_weekly_report(stats, config, alerts)

        ops = OpsAgent()
        # OpsAgent write_protocol_doc helper'ı kullansın
        from datetime import datetime as _dt, timezone as _tz
        iso = _dt.now(_tz.utc).isocalendar()
        week_label = f"{iso.year}-W{iso.week:02d}"
        path = ops.write_protocol_doc(
            doc_type="incident" if alerts else "postmortem",
            body=body,
            slug=f"token-report-{week_label}",
            target_dir=ops.settings.reports_dir / "ops",
            status="ACTIVE",
            confidence="high",
            requested_review_from=["ceo"] if alerts else [],
            tags=["token_budget", "weekly", week_label],
        )

        # Limit aşımı varsa CRIT push
        crit_alerts = [a for a in alerts if a.get("level") == "CRIT"]
        if crit_alerts:
            _push_critical_safe(
                f"Token budget aşıldı: {[a['agent'] for a in crit_alerts]}",
                source="ops_engineer",
            )
        elif alerts:
            _push_report_safe(path, level="WARNING", caption="Token Budget WARN")
        logger.info(
            "scheduler.token_report_done",
            extra={"path": str(path), "n_alerts": len(alerts)},
        )
    except Exception as exc:
        logger.warning("scheduler.token_report_fail", extra={"err": str(exc)[:200]})


# ----------------------------------------------------------------------
# Faz 4.4 — Weekly consolidation
# ----------------------------------------------------------------------

async def _job_bot_health_check() -> None:
    """Faz 6: Bot Monitor saatlik snapshot — her bot için equity + DD + halt."""
    try:
        from price_action.agents import BotMonitorAgent
        bm = BotMonitorAgent()
        await bm.hourly_snapshot()
    except Exception as exc:
        logger.warning("scheduler.bot_health_fail", extra={"err": str(exc)[:200]})


async def _job_bot_daily_cards() -> None:
    """Faz 6: Bot Monitor günlük report cards — per-bot performance brief."""
    try:
        from price_action.agents import BotMonitorAgent
        bm = BotMonitorAgent()
        path = await bm.daily_report_cards()
        _push_report_safe(path, level="INFO", caption="Bot Daily Cards")
    except Exception as exc:
        logger.warning("scheduler.bot_cards_fail", extra={"err": str(exc)[:200]})


async def _job_kill_criteria_eval() -> None:
    """Faz 6: Bot Monitor kill criteria — 7g/14g loss eşik kontrolü."""
    try:
        from price_action.agents import BotMonitorAgent
        bm = BotMonitorAgent()
        await bm.evaluate_kill_criteria()
    except Exception as exc:
        logger.warning("scheduler.kill_criteria_fail", extra={"err": str(exc)[:200]})


async def _job_param_sweep_chunk() -> None:
    """Faz 7: Param sweep saatlik chunk processor (5 cell/saat)."""
    try:
        import asyncio
        await asyncio.to_thread(_run_param_sweep_chunk_sync)
    except Exception as exc:
        logger.warning("scheduler.param_sweep_chunk_fail", extra={"err": str(exc)[:200]})


async def _job_regime_features_refresh() -> None:
    """FIX 2026-05-25: Daily BTC regime features refresh.

    Was missing from JOB_TABLE — caused 15m bot to reject signals with
    regime_cache_stale when running long enough for cache to expire.
    Runs 00:01 UTC daily; ccxt-direct fetch bypasses DuckDB lock conflicts.
    """
    try:
        import asyncio
        import subprocess
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[3]
        cmd = [
            str(repo_root / ".venv" / "bin" / "python"),
            "scripts/regime_features_refresh.py",
        ]
        result = await asyncio.to_thread(
            subprocess.run, cmd, cwd=str(repo_root),
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            logger.info("scheduler.regime_refresh_ok",
                        extra={"stdout_tail": result.stdout[-300:]})
        else:
            logger.error("scheduler.regime_refresh_fail",
                         extra={"rc": result.returncode,
                                "stderr_tail": result.stderr[-300:]})
            _push_critical_safe(
                f"Regime features refresh FAILED rc={result.returncode}. "
                f"15m bot will start rejecting signals once cache expires.",
                source="scheduler",
            )
    except Exception as exc:
        logger.error("scheduler.regime_refresh_exc", extra={"err": str(exc)[:200]})
        _push_critical_safe(
            f"Regime features refresh CRASHED: {str(exc)[:200]}",
            source="scheduler",
        )


def _run_param_sweep_chunk_sync() -> None:
    """Sync helper — scripts/param_sweep_chunk_processor.py'i import et.

    FIX 2026-05-26: önceki versiyon `process_next_chunk` çağırıyordu, oysa
    fonksiyon adı `process_chunk(chunks_cfg, grids_cfg, chunks_dir)`.
    Configleri main()'in yaptığı gibi yükle ve doğru imzayla çağır.
    """
    try:
        import yaml
        from pathlib import Path
        from scripts.param_sweep_chunk_processor import process_chunk
        chunks_yaml = Path("configs/param_sweep_chunks.yaml")
        grids_yaml = Path("configs/param_sweep_grids.yaml")
        if not chunks_yaml.exists() or not grids_yaml.exists():
            logger.warning(
                "scheduler.param_sweep_config_missing",
                extra={"chunks": str(chunks_yaml), "grids": str(grids_yaml)},
            )
            return
        chunks_cfg = yaml.safe_load(chunks_yaml.read_text()) or {}
        grids_cfg = yaml.safe_load(grids_yaml.read_text()) or {}
        chunks_dir = Path(chunks_cfg.get("chunks_dir", "reports/param_sweep/chunks"))
        chunks_dir.mkdir(parents=True, exist_ok=True)
        result = process_chunk(chunks_cfg, grids_cfg, chunks_dir)
        logger.info(
            "scheduler.param_sweep_chunk_done",
            extra={
                "strategy": result.get("strategy"),
                "cells_processed": result.get("cells_processed"),
                "offset_after": result.get("offset_after"),
            },
        )
    except ImportError as exc:
        logger.warning("scheduler.param_sweep_import_fail", extra={"err": str(exc)[:200]})
    except Exception as exc:
        logger.warning("scheduler.param_sweep_run_fail", extra={"err": str(exc)[:200]})


async def _job_adversary_daily_stress() -> None:
    """Faz 9: Adversary Engineer günlük stress test.

    FIX 2026-05-26: önceden gün modulo ile 1 bot/gün rotation vardı
    (day%2==0 → futures15m, day%2==1 → futures5m). Bu Principal'in
    "futures15m hiç test edilmiyor" şikayetine sebep oldu çünkü
    aktif gün rotation'a denk gelmediğinde günlerce sıra atlıyordu.
    Yeni davranış: her gece HER iki bot için stress test (paralel).
    Token bütçesi artırıldı (Faz 4.2 revize 2026-05-25), karşılayabilir.
    """
    try:
        import asyncio
        from price_action.agents import AdversaryEngineerAgent
        ae = AdversaryEngineerAgent()
        bots = ["futures15m", "futures5m"]
        # Paralel çalıştır (bağımsız işler, agent re-entrant)
        results = await asyncio.gather(
            *[ae.daily_stress_test(b) for b in bots],
            return_exceptions=True,
        )
        for bot_id, result in zip(bots, results):
            if isinstance(result, Exception):
                logger.warning(
                    "scheduler.adversary_per_bot_fail",
                    extra={"bot": bot_id, "err": str(result)[:200]},
                )
                continue
            # CRIT verdict varsa push
            try:
                content = result.read_text(encoding="utf-8")[:3000]
                if "CRIT" in content or "FAILED" in content:
                    _push_critical_safe(
                        f"Adversary stress test CRIT — bot={bot_id}",
                        source="adversary_engineer",
                    )
            except Exception:
                pass
    except Exception as exc:
        logger.warning("scheduler.adversary_daily_fail", extra={"err": str(exc)[:200]})


async def _job_adversary_weekly_red_team() -> None:
    """Faz 9: Adversary Engineer haftalık red team raporu (tüm bot'lar)."""
    try:
        from price_action.agents import AdversaryEngineerAgent
        ae = AdversaryEngineerAgent()
        path = await ae.weekly_red_team_report(["futures15m", "futures5m"])
        _push_report_safe(path, level="INFO", caption="Weekly Red Team Report")
    except Exception as exc:
        logger.warning("scheduler.adversary_weekly_fail", extra={"err": str(exc)[:200]})


async def _job_monthly_market_scout() -> None:
    """Faz 11: Market Scout aylık feasibility study (ayın 5'i).

    Aylık tetik korundu — derin bir 5-boyutlu çalışma.
    Haftalık hızlı tarama için ``_job_weekly_market_scout`` ayrı.
    """
    try:
        from price_action.agents import MarketScoutAgent
        ms = MarketScoutAgent()
        path = await ms.monthly_feasibility_study(target_market=None)  # auto-rotation
        _push_report_safe(path, level="INFO", caption="Market Scout Feasibility")
    except Exception as exc:
        logger.warning("scheduler.market_scout_fail", extra={"err": str(exc)[:200]})


async def _job_weekly_market_scout() -> None:
    """FIX 2026-05-26: Haftalık market scout (5 haftada tüm rotation).

    Aylık tetik 5 ayda 1 tam tur dönüyor (yavaş kapsama). Bu haftalık
    iş ISO hafta modulo ile her hafta sıradaki pazara bakar — 5 haftada
    tüm rotation taranır. select_market_for_week() kullanır.
    """
    try:
        from price_action.agents import MarketScoutAgent
        ms = MarketScoutAgent()
        cal = ms.load_calendar()
        slot = ms.select_market_for_week(calendar=cal)
        if slot is None:
            logger.warning("scheduler.weekly_market_scout_no_slot")
            return
        market_name = str(slot.get("market", "unknown"))
        path = await ms.monthly_feasibility_study(target_market=market_name)
        _push_report_safe(
            path, level="INFO",
            caption=f"Weekly Market Scout — {market_name}",
        )
    except Exception as exc:
        logger.warning(
            "scheduler.weekly_market_scout_fail", extra={"err": str(exc)[:200]}
        )


async def _job_curator_daily_correlation() -> None:
    """Faz 8: Strategy Curator günlük correlation update."""
    try:
        from price_action.agents import StrategyCuratorAgent
        sc = StrategyCuratorAgent()
        await sc.daily_correlation_update()
    except Exception as exc:
        logger.warning("scheduler.curator_correlation_fail", extra={"err": str(exc)[:200]})


async def _job_curator_weekly_lifecycle() -> None:
    """Faz 8: Strategy Curator haftalık lifecycle review."""
    try:
        from price_action.agents import StrategyCuratorAgent
        sc = StrategyCuratorAgent()
        path = await sc.weekly_lifecycle_review()
        _push_report_safe(path, level="INFO", caption="Weekly Strategy Lifecycle")
    except Exception as exc:
        logger.warning("scheduler.curator_lifecycle_fail", extra={"err": str(exc)[:200]})


async def _job_researcher_5batch() -> None:
    """Faz 12: Researcher 5-paralel hipotez üretimi (her gece 02:30)."""
    try:
        from price_action.agents import ResearcherAgent
        r = ResearcherAgent()
        results = await r.propose_5_batch()
        logger.info(
            "scheduler.researcher_5batch_done",
            extra={"n_hypotheses": len(results)},
        )
    except Exception as exc:
        logger.warning("scheduler.researcher_5batch_fail", extra={"err": str(exc)[:200]})


async def _job_researcher_improvement_pulse() -> None:
    """FIX 2026-05-26: Gün içi Researcher pulse'ları.

    Önceden Researcher sadece gece 02:00 (deep) + 02:30 (5-batch) çalışıyordu.
    Principal "gün içinde de üretsin, mevcut botu iyileştirsin" istedi.
    Bu job 4 saatte 1 çalışır, dönüşümlü temalar:
      0: futures15m bot iyileştirme
      1: futures5m bot iyileştirme
      2: yeni edge / çapraz strateji
      3: portföy çeşitlilik

    Her çağrı ~30-50K Opus token (kalan günlük 500K bütçe karşılar).
    """
    try:
        from datetime import datetime as _dt, timezone as _tz
        from price_action.agents import ResearcherAgent
        hour = _dt.now(_tz.utc).hour
        themes = [
            "futures15m wide-stop bot: bugünkü gözlemlerden yola çıkarak bir iyileştirme önerisi (SL/TP/regime filter/vol_z tier).",
            "futures5m P1c bot: bugünkü reject pattern'larından yola çıkarak bir iyileştirme önerisi (widestop threshold/strateji ekleme).",
            "Cross-strategy edge keşfi: aktif vsa_climax_test ile düşük korelasyonlu ek bir strateji (raftaki 66'dan adaylar).",
            "Portföy çeşitlilik: mevcut tek-strateji riski azaltacak bir TF/strateji kombinasyonu.",
        ]
        theme = themes[hour % len(themes)]
        r = ResearcherAgent()
        result = await r.propose_hypothesis(theme)
        logger.info(
            "scheduler.researcher_pulse_done",
            extra={"hour_utc": hour, "theme_idx": hour % len(themes),
                   "result_preview": (result or "")[:120]},
        )
    except Exception as exc:
        logger.warning(
            "scheduler.researcher_pulse_fail", extra={"err": str(exc)[:200]}
        )


async def _job_lab_quick_scan() -> None:
    """FIX 2026-05-26: Gün içi Lab Scientist hızlı tarama.

    Her 2 saatte 1: drift detection (deterministic) + bekleyen hipotez varsa
    Researcher inbox'tan birini yorumlat (interpret_backtest). Hafif iş,
    ~5-15K Sonnet token / çağrı.
    """
    try:
        from price_action.agents import LabScientistAgent
        lab = LabScientistAgent()

        # 1. Drift detect — recent series placeholder (Faz 5+ Walker'dan beslenir)
        try:
            result = lab.drift_detect([], [])
            if result.get("alert"):
                lab.append_learning(
                    f"Quick scan drift alert: {result}",
                    slug="drift-alert-quick", confidence="med",
                )
        except Exception:
            pass

        # 2. Param sweep ek hücre — her quick scan +1 cell
        try:
            import asyncio
            await asyncio.to_thread(_run_param_sweep_chunk_sync)
        except Exception:
            pass

        logger.info("scheduler.lab_quick_scan_done")
    except Exception as exc:
        logger.warning("scheduler.lab_quick_scan_fail", extra={"err": str(exc)[:200]})


async def _job_weekly_bot_attribution() -> None:
    """Faz 12: Haftalık per-bot attribution (Analyst + Bot Monitor sentez)."""
    try:
        from price_action.agents import AnalystAgent, BotMonitorAgent
        # Bot Monitor günlük cards'larını topla, Analyst sentez yapsın
        bm = BotMonitorAgent()
        cards_path = await bm.daily_report_cards()
        # Şimdilik basit: bot_monitor weekly summary
        # Faz 12.x: Analyst.weekly_attribution metodu ekle, çapraz-sentez
        logger.info(
            "scheduler.weekly_bot_attribution_done",
            extra={"path": str(cards_path)},
        )
        _push_report_safe(cards_path, level="INFO", caption="Weekly Bot Attribution")
    except Exception as exc:
        logger.warning("scheduler.weekly_bot_attribution_fail", extra={"err": str(exc)[:200]})


async def _job_weekly_principal_queue() -> None:
    """Faz 12: Pazar 08:30 — CEO Q&A digest, Principal action queue."""
    try:
        from price_action.agents import CEOAgent
        ceo = CEOAgent()
        # CEO weekly_summary'i Principal action queue olarak push
        path = await ceo.weekly_summary()
        _push_report_safe(path, level="INFO", caption="Principal Action Queue (Weekly)")
    except Exception as exc:
        logger.warning("scheduler.weekly_principal_queue_fail", extra={"err": str(exc)[:200]})


async def _job_monthly_strategy_portfolio_review() -> None:
    """Faz 12: Aybaşı 09:00 — Curator + CEO monthly portfolio review."""
    try:
        from price_action.agents import CEOAgent, StrategyCuratorAgent
        sc = StrategyCuratorAgent()
        await sc.weekly_lifecycle_review()  # Monthly = ek detaylı weekly variant
        ceo = CEOAgent()
        path = await ceo.weekly_summary()
        _push_report_safe(path, level="INFO", caption="Monthly Strategy Portfolio Review")
    except Exception as exc:
        logger.warning("scheduler.monthly_portfolio_review_fail", extra={"err": str(exc)[:200]})


async def _job_tf_exploration_chunk() -> None:
    """Faz 10: TF exploration günlük chunk (1 strateji × 1 TF/gün)."""
    try:
        import asyncio
        await asyncio.to_thread(_run_tf_exploration_chunk_sync)
    except Exception as exc:
        logger.warning("scheduler.tf_exploration_chunk_fail", extra={"err": str(exc)[:200]})


def _run_tf_exploration_chunk_sync() -> None:
    """Sync wrapper — scripts/tf_exploration_runner.py."""
    try:
        from scripts.tf_exploration_runner import explore_tf
        from price_action.settings import get_settings as _gs
        from datetime import datetime as _dt, timezone as _tz
        from pathlib import Path

        s = _gs()
        # Basit rotation: gün × strateji index
        strategies = ["vsa_climax_test", "brooks_failed_breakout", "anchored_vwap_reversal"]
        idx = _dt.now(_tz.utc).day % len(strategies)
        strategy = strategies[idx]

        # Pool paths
        pool_paths = {
            "5m": s.reports_dir.parent / "data" / "sec53_5m_pool_v11_vm20.pkl",
            "15m": s.reports_dir.parent / "data" / "sec53_15m_pool_v11.pkl",
        }
        out_dir = s.reports_dir / "tf_exploration"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{strategy}-{_dt.now(_tz.utc).date()}.md"

        result = explore_tf(
            strategy=strategy,
            tf_list=["5m", "15m"],
            pool_paths=pool_paths,
        )
        # render report — basit dump (full markdown rapor explore_tf'in kendisi yazar)
        logger.info(
            "scheduler.tf_exploration_done",
            extra={"strategy": strategy, "best_tf": result.get("best_tf")},
        )
    except ImportError:
        logger.warning("scheduler.tf_exploration_import_fail")
    except Exception as exc:
        logger.warning("scheduler.tf_exploration_inner_fail", extra={"err": str(exc)[:200]})


async def _job_weekly_consolidation() -> None:
    """Tüm agent'ların weekly_consolidation çağrısı + inbox archive (Pazar 05:30 UTC)."""
    try:
        from price_action.agents import (
            AnalystAgent,
            CEOAgent,
            LabScientistAgent,
            OpsAgent,
            ResearcherAgent,
            RiskOfficerAgent,
        )
        from price_action.settings import get_settings as _gs

        agents = [
            CEOAgent(), ResearcherAgent(), LabScientistAgent(),
            AnalystAgent(), RiskOfficerAgent(), OpsAgent(),
        ]
        consolidated = 0
        for a in agents:
            try:
                a.consolidate_weekly(last_n_days=7)
                consolidated += 1
            except Exception as exc:
                logger.warning(
                    "scheduler.consolidate_fail",
                    extra={"agent": a.name, "err": str(exc)[:200]},
                )

        # Inbox archive: önceki haftanın inbox.jsonl'ini archive/'a taşı
        s = _gs()
        inbox = s.memory_dir / "protocol" / "inbox.jsonl"
        if inbox.exists():
            from datetime import datetime as _dt, timezone as _tz
            iso = _dt.now(_tz.utc).isocalendar()
            archive_path = s.memory_dir / "protocol" / "archive" / f"{iso.year}-W{iso.week:02d}.jsonl"
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            # Move (rename)
            inbox.rename(archive_path)
            # Yeni boş inbox başlat
            inbox.touch()
            logger.info(
                "scheduler.inbox_archived",
                extra={"archive": str(archive_path)},
            )

        logger.info("scheduler.consolidation_done", extra={"n_agents": consolidated})
    except Exception as exc:
        logger.warning("scheduler.consolidation_fail", extra={"err": str(exc)[:200]})


# ----------------------------------------------------------------------
# Faz 1.2 — Push helper'ları (sessiz fail; scheduler düşmesin)
# ----------------------------------------------------------------------

def _push_report_safe(path: Any, *, level: str = "INFO", caption: str | None = None) -> None:
    """Path'i Telegram'a gönder; hata varsa sessizce logla."""
    try:
        from .notifications import push_report, should_push

        if not should_push():
            return
        # FIX 2026-05-25: parse_mode=None — file paths/captions often contain _
        # which breaks Markdown parser. Plain text is safer for system reports.
        push_report(path, level=level, caption=caption, parse_mode=None)
    except Exception as exc:
        logger.warning("scheduler.push_fail", extra={"path": str(path), "err": str(exc)[:200]})


def _push_critical_safe(message: str, *, source: str | None = None) -> None:
    """CRIT mesajını gönder; hata varsa sessizce logla."""
    try:
        from .notifications import push_critical

        push_critical(message, source=source)
    except Exception as exc:
        logger.warning("scheduler.push_crit_fail", extra={"source": source, "err": str(exc)[:200]})


def _push_latest_safe(
    subdir: str, pattern: str, *, level: str = "INFO", caption: str | None = None
) -> None:
    """`reports/<subdir>/` altında en son matching dosyayı bul ve push."""
    try:
        from price_action.settings import get_settings

        from .notifications import push_report_if_recent, should_push

        if not should_push():
            return
        s = get_settings()
        d = s.reports_dir / subdir
        push_report_if_recent(d, pattern, level=level, caption=caption, parse_mode=None)
    except Exception as exc:
        logger.warning(
            "scheduler.push_latest_fail",
            extra={"subdir": subdir, "pattern": pattern, "err": str(exc)[:200]},
        )


# ----------------------------------------------------------------------
# Kayıt
# ----------------------------------------------------------------------

JOB_TABLE: tuple[tuple[str, str, str, Any], ...] = (
    # (id, kind, expr, func)
    ("ingest_data", "cron", "0 * * * *", _job_ingest_data),  # saatlik :00
    # FIX 2026-05-25: regime features daily refresh (was missing — caused regime_cache_stale)
    ("regime_features_refresh", "cron", "1 0 * * *", _job_regime_features_refresh),  # 00:01 UTC
    ("hourly_token_check", "cron", "7 * * * *", _job_hourly_token_check),  # H3 :07
    ("review_inbox", "cron", "15 * * * *", _job_review_inbox),  # Faz 2.3 :15
    ("bot_health_check", "cron", "20 * * * *", _job_bot_health_check),  # Faz 6 :20
    ("health_check", "cron", "30 * * * *", _job_health_check),  # H4 :30
    ("param_sweep_chunk", "cron", "35 * * * *", _job_param_sweep_chunk),  # Faz 7 :35
    ("scan_drift_alerts", "cron", "45 * * * *", _job_scan_drift_alerts),  # Faz 3.1 :45
    # Günlük
    ("daily_research", "cron", "0 2 * * *", _job_daily_research),
    ("researcher_5batch", "cron", "30 2 * * *", _job_researcher_5batch),  # Faz 12
    # FIX 2026-05-26: gün içi Researcher pulse (her 4 saatte 1, gece 02:00 main hariç)
    ("researcher_pulse", "cron", "0 6,10,14,18,22 * * *", _job_researcher_improvement_pulse),
    # FIX 2026-05-26: gün içi Lab Scientist hızlı tarama (her 2 saatte 1)
    ("lab_quick_scan", "cron", "25 0,2,4,6,8,10,12,14,16,18,20,22 * * *", _job_lab_quick_scan),
    ("adversary_daily_stress", "cron", "0 4 * * *", _job_adversary_daily_stress),  # Faz 9
    ("tf_exploration_chunk", "cron", "30 4 * * *", _job_tf_exploration_chunk),  # Faz 10
    ("signal_scan", "cron", "5 0 * * *", _job_signal_scan),
    ("execute_orders", "cron", "10 0 * * *", _job_execute_orders),
    ("curator_daily_correlation", "cron", "0 19 * * *", _job_curator_daily_correlation),  # Faz 8
    ("bot_daily_cards", "cron", "0 22 * * *", _job_bot_daily_cards),  # Faz 6
    ("daily_kpi", "cron", "0 23 * * *", _job_daily_kpi),
    ("daily_whatif", "cron", "30 23 * * *", _job_daily_whatif),  # Faz 2.3
    ("kill_criteria_eval", "cron", "45 23 * * *", _job_kill_criteria_eval),  # Faz 6
    # Haftalık
    ("weekly_lab_tournament", "cron", "0 3 * * sun", _job_weekly_tournament),
    ("weekly_drift", "cron", "30 3 * * sun", _job_weekly_drift),
    ("adversary_weekly_red_team", "cron", "30 4 * * sun", _job_adversary_weekly_red_team),  # Faz 9
    ("weekly_rag_refresh", "cron", "0 4 * * sun", _job_weekly_rag_refresh),
    ("weekly_token_report", "cron", "0 5 * * sun", _job_weekly_token_report),  # Faz 4.2
    ("weekly_consolidation", "cron", "30 5 * * sun", _job_weekly_consolidation),  # Faz 4.4
    ("curator_weekly_lifecycle", "cron", "30 6 * * sun", _job_curator_weekly_lifecycle),  # Faz 8
    ("weekly_bot_attribution", "cron", "30 7 * * sun", _job_weekly_bot_attribution),  # Faz 12
    ("weekly_principal_queue", "cron", "30 8 * * sun", _job_weekly_principal_queue),  # Faz 12
    # Aylık
    ("monthly_market_scout", "cron", "0 8 5 * *", _job_monthly_market_scout),  # Faz 11
    # FIX 2026-05-26: haftalık market scout (5 haftada full rotation kapsama)
    ("weekly_market_scout", "cron", "0 9 * * mon", _job_weekly_market_scout),  # Pzt 09:00 UTC
    ("monthly_review", "cron", "0 6 28-31 * *", _job_monthly_review),
    ("monthly_strategy_portfolio", "cron", "0 9 28-31 * *", _job_monthly_strategy_portfolio_review),  # Faz 12
)


def _add_cron(scheduler: Any, expr: str, func: Any, job_id: str) -> None:
    """Cron job ekle.

    M7 FIX: explicit `max_instances=1` (varsayılan zaten 1 ama dokümante et)
    + `coalesce=True` — birden fazla misfire varsa tek run'da birleştir
    (kuyruğu önle).

    Job-spesifik karakteristikler:
    - daily_research: ~40s (RAG embedding load) — uzun olsa da single
    - daily_kpi + daily_brief: ~3s
    - weekly_tournament: değişken (challenger count'a göre)
    """
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
        max_instances=1,   # M7: explicit — overlap engelle
        coalesce=True,     # M7: birden fazla misfire → tek run
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
