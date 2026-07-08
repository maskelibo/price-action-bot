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

import math
import os
from datetime import UTC
from pathlib import Path
from typing import Any

from price_action.logging_config import logger


def build_scheduler() -> Any:
    """``AsyncIOScheduler`` instance'ı döndürür.

    FIX 2026-05-26 (H2): Async job desteği için AsyncIOExecutor (default).
    Önceki versiyon ThreadPoolExecutor kullanıyordu → async coroutine'ler
    "never awaited" hatasıyla 3 saatir hiç çalışmadı. Düzeltme:
    AsyncIOExecutor (built-in pool 100 default — sub-second job'lar için
    yeterli). Subprocess uzun süren job'lar asyncio.to_thread içinde
    zaten yer alıyor → blocking yok.
    """
    try:
        from apscheduler.executors.asyncio import AsyncIOExecutor  # type: ignore[import-not-found]
        from apscheduler.schedulers.asyncio import (
            AsyncIOScheduler,  # type: ignore[import-not-found]
        )
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("apscheduler yüklü değil — `pip install apscheduler`") from exc
    executors = {
        "default": AsyncIOExecutor(),
    }
    job_defaults = {
        "coalesce": True,  # Aynı job için birikmiş misfire'lar tek run
        "max_instances": 1,  # Aynı job ID concurrent yasak (kendiyle race yok)
        "misfire_grace_time": 600,  # 10 dk geç çalışmaya izin
    }
    return AsyncIOScheduler(
        timezone="UTC",
        executors=executors,
        job_defaults=job_defaults,
    )


# ----------------------------------------------------------------------
# Job fonksiyonları (async)
# ----------------------------------------------------------------------


async def _job_ingest_data() -> None:
    """Saatlik OHLCV ingest. Deterministik ingest_ccxt modülünü çağırır.

    FIX 2026-05-28 (Faz 14.27): Önceden `run_hourly` fonksiyonu YOKTU,
    `hasattr` False olunca SILENT SKIP → market.duckdb 6 GÜN güncellenmedi.
    Şimdi: run_hourly eklendi + missing durumunda CRIT log + Telegram alert.

    Hata olursa logla + alert; scheduler'ı düşürme.
    """
    try:
        from price_action.data import ingest_ccxt  # type: ignore[import-untyped]

        if hasattr(ingest_ccxt, "run_hourly"):
            stats = await ingest_ccxt.run_hourly()  # type: ignore[attr-defined]
            logger.info("scheduler.ingest_data_done", extra={"extra": stats})
            return
        # Defensive: function missing → CRITICAL (Faz 14.27 fix)
        logger.error("scheduler.ingest_data_missing_func", extra={"extra": {"func": "run_hourly"}})
        try:
            from price_action.orchestrator.notifications import push_critical

            push_critical(
                "ingest_data SILENT FAIL: run_hourly() yok — market.duckdb stale "
                "olabilir. Bot karar verirken eski veri kullanır.",
                source="scheduler_ingest",
            )
        except Exception:
            pass
    except Exception as exc:
        logger.warning("scheduler.ingest_skip", extra={"err": str(exc)[:200]})


async def _job_market_snapshot() -> None:
    """SNAPSHOT 2026-05-29: market_ingest.duckdb → market.duckdb (atomik file-copy).

    Ayrı job çünkü run_hourly tüm sembolleri tarayıp uzun/cancelled olabiliyor →
    sondaki snapshot'a ulaşamıyor → market.duckdb donuyor. Bu hafif job ingest'ten
    BAĞIMSIZ her saat :05'te snapshot'lar (market_ingest'te ne varsa consumer'a
    taşır). run_hourly sonundaki snapshot da backstop olarak kalır.
    """
    try:
        import asyncio

        from price_action.data.ingest_ccxt import _snapshot_ingest_to_consumer
        from price_action.settings import get_settings

        s = get_settings()
        res = await asyncio.to_thread(
            _snapshot_ingest_to_consumer, s.ingest_duckdb_path, s.duckdb_path
        )
        logger.info("scheduler.market_snapshot_done", extra={"extra": res})
    except Exception as exc:
        logger.warning("scheduler.market_snapshot_fail", extra={"err": str(exc)[:200]})


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
    from datetime import datetime, timedelta

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

        target = datetime.now(UTC) - timedelta(days=1)
        dry = not s.is_live  # live değilse dry_run=True (paper/testnet)

        logger.info(
            "scheduler.execute_orders_run",
            extra={"target": str(target.date()), "dry_run": dry},
        )
        await asyncio.to_thread(daily_run, target, dry)
        logger.info("scheduler.execute_orders_done", extra={"date": str(target.date())})
    except ImportError:
        logger.warning(
            "scheduler.execute_orders_import_fail",
            extra={"hint": "scripts/futures_trade_daily.py bulunamadı"},
        )
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


async def _job_auto_iterate_orchestrator() -> None:
    """FIX 2026-05-27 (Faz 14.24): OTONOM iterate orchestrator.

    User talebi: 'İşte böyle geliştirilir bot. Otonom hale getir.
    Israrcı olsun umut vaad edenlere. Yarın sorduğumda bug çıkmasın.'

    Çalışma:
      1. data/state/iterate_state.json — per-target progress (idempotent)
      2. memory/researcher/iterate_targets.json — pending queue
      3. Her koşumda 2 target × 5 variant (~10 dk compute)
      4. 7 round bitince target completed
      5. BEATS_LIVE / SUPER_ELITE bulununca Telegram CRIT push
      6. Crash-safe — her variant try/except, state korunur

    Cron: her 2 saatte 1 (24h'da 12 koşum × 2 target × 5 variant = 120 trade)
    Tam yetenek: tüm 4 pending target 7 round × 5 variant = 140 variant /
    2 target per run = 70 koşum / 2h = 6 gün (worst case).
    Daha sık (saat başı) = 3 gün. Şimdilik 2 saat.
    """
    try:
        import asyncio

        from price_action.lab.iterate_orchestrator import run_orchestrator

        result = await asyncio.to_thread(
            run_orchestrator,
            max_targets_per_run=2,
            max_variants_per_round=5,
        )
        logger.info(
            "scheduler.auto_iterate_done",
            extra={
                "targets_processed": result["targets_processed"],
                "rounds_run": result["rounds_run"],
                "promotes_found": len(result["promotes_found"]),
                "errors": len(result["errors"]),
            },
        )
        if result["promotes_found"]:
            logger.warning(
                "scheduler.auto_iterate_promote_found",
                extra={"promotes": result["promotes_found"]},
            )
    except Exception as exc:
        logger.warning(
            "scheduler.auto_iterate_exc",
            extra={"err": str(exc)[:200]},
        )


async def _job_find_promising_to_iterate() -> None:
    """FIX 2026-05-27 (Faz 14.22): Pozitif edge'li ama riskli stratejileri
    tespit et + Researcher'a iterate talebi yaz.

    User direktifi: 'Researcher rsi2 gibi botlardan vazgeçmesin — sonuçları
    iyi DD düşürmeye, ROI artırmaya çalışsın, çöpe atmasın.'

    Output: reports/researcher_iterate_queue/iterate-queue-<date>.md
    Researcher persona SOP-4b'ye göre bu queue'yu okur ve v2/v3 hipotezler
    yazar (REDDETMEK YASAK politika).
    """
    try:
        import asyncio
        import subprocess
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        cmd = [
            str(repo_root / ".venv" / "bin" / "python"),
            "scripts/find_promising_to_iterate.py",
        ]
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info(
                "scheduler.iterate_queue_done",
                extra={"stdout_tail": result.stdout[-500:]},
            )
        else:
            logger.warning(
                "scheduler.iterate_queue_fail",
                extra={"rc": result.returncode, "stderr": result.stderr[-300:]},
            )
    except Exception as exc:
        logger.warning("scheduler.iterate_queue_exc", extra={"err": str(exc)[:200]})


async def _job_hypothesis_backtest_runner() -> None:
    """FIX 2026-05-27 (Faz 14.15): Researcher hipotezleri için backtest köprüsü.

    Researcher 36 saatte 1.8M token yakıp 14 hipotez yazıyor, hiçbiri
    BACKTEST edilmiyordu → tournament'a oos_returns=[] olarak girip
    otomatik reject ediliyordu. Bu job:

      1. memory/researcher/hypotheses/ son N gün
      2. backtest_results/ ENVET (result yok)
      3. LLM extract → param_sweep|analysis|new_strategy classify
      4. Tipine göre runner çağır
      5. memory/researcher/backtest_results/<hyp_id>.json yaz

    Her job çağrısı max 3 hipotez (LLM extract her hipotez ~5K token).
    """
    try:
        from price_action.lab.hypothesis_runner import HypothesisRunner

        runner = HypothesisRunner()
        results = await runner.run_all_pending(since_days=30, max_runs=3)
        ok = sum(1 for r in results if r.get("result", {}).get("status") == "OK")
        logger.info(
            "scheduler.hyp_backtest_done",
            extra={
                "n_attempted": len(results),
                "n_ok": ok,
                "results": [
                    {"id": r.get("hypothesis_id"), "status": r.get("result", {}).get("status")}
                    for r in results
                ],
            },
        )
    except Exception as exc:
        logger.warning(
            "scheduler.hyp_backtest_fail",
            extra={"err": str(exc)[:200]},
        )


def _champion_live_oos() -> dict[str, Any] | None:
    """Canlı v14'ün borsa-truth kapanış R-serisinden champion dict'i üret.

    FIX 2026-07-02 (fabrika RW P0-3): önceki champion `oos_returns=[]`
    hardcoded → welch_p daima NaN, champion karşılaştırması ölüydü (1 Tem
    W27 turnuvasında tüm satırlar NaN). Şimdi:
      - TEMİZ dönem (eski champion emekliliği 2026-06-14T21:53Z sonrası)
        REALIZED_PNL income kayıtları → per-close R = pnl / (5000×0.0075).
      - oos_sharpe = per-obs SR × √(yıllık kapanış sayısı) — sweep
        aggregator'ın annualized konvansiyonuyla aynı birim.
      - KONSERVATİF taban: canlı-annualized, backtest tabanı 1.5'in altına
        düşerse 1.5 kullanılır → champion'ın kötü haftasında bar düşüp
        zayıf aday terfi etmesin (slump-promotion koruması).
      - oos_maxdd 0.193 sabit (backtest 5y compound DD) — challenger
        DD'leri de 5y compound; 17 günlük canlı DD ile kıyas elma-armut.
    Borsaya ulaşılamazsa None → çağıran statik fallback kullanır.
    """
    try:
        import statistics
        import sys
        from datetime import datetime as _dt

        repo_root = Path(__file__).resolve().parents[3]
        if str(repo_root / "scripts") not in sys.path:
            sys.path.insert(0, str(repo_root / "scripts"))
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from scripts.futures_trade_daily import get_futures_exchange  # type: ignore

        ex = get_futures_exchange()
        # FIX 2026-07-07 (denetim D4): baseline v14'te kalmıştı — cutoff 14 Haz
        # + risk_usd 37.5 → post-2Tem R'ler ~%32 şişik ve seri v14/v15p2 karışık.
        # v15p2 deploy anı (2 Tem 13:07 UTC) + temiz anchor $4963 × risk %1.
        clean_ms = int(_dt(2026, 7, 2, 13, 7, tzinfo=UTC).timestamp() * 1000)
        now_ms = int(_dt.now(UTC).timestamp() * 1000)
        risk_usd = 4963.0 * 0.01  # v15p2 risk_per_trade — R normalizasyonu

        rows: list[dict[str, Any]] = []
        cur = clean_ms
        while cur < now_ms:
            batch = ex.fapiPrivateGetIncome({"startTime": cur, "endTime": now_ms, "limit": 1000})
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < 1000:
                break
            cur = int(batch[-1]["time"]) + 1

        seen: set[tuple] = set()
        rr: list[float] = []
        for r in rows:
            if r.get("incomeType") != "REALIZED_PNL":
                continue
            k = (r.get("tranId"), r.get("time"), r.get("income"))
            if k in seen:
                continue
            seen.add(k)
            v = float(r.get("income") or 0.0)
            if v != 0.0:
                rr.append(v / risk_usd)

        if len(rr) < 30:  # örneklem çok küçük → güvenilir değil
            return None
        sd = statistics.stdev(rr)
        if sd <= 1e-12:
            return None
        sr_obs = statistics.mean(rr) / sd
        days = max(1e-9, (now_ms - clean_ms) / 86_400_000)
        ann = sr_obs * math.sqrt(len(rr) * 365.0 / days)
        # NOT (kalibrasyon, 2026-07-02): effect-gate BARI = 1.5 (backtest-bazlı,
        # challenger'ların 5y-backtest annualized birimiyle elma-elma). Canlı
        # 17g annualized (~4.8) kısa-örneklem + frekans şişmesiyle KIYAS DIŞI —
        # bar yapılsaydı yeni bir geçilmez duvar olurdu (aday ≥5.5 gerekirdi).
        # Canlı R-serisi Welch dağılım testinde kullanılır (P0-3'ün asıl amacı);
        # ham canlı-annualized diagnostik olarak raporda taşınır.
        return {
            "id": "live_v15p2_champion_income",
            "oos_returns": rr,
            "oos_sharpe": 1.5,  # backtest-bazlı bar (birim paritesi)
            "oos_maxdd": 0.193,  # backtest 5y compound DD (birim paritesi)
            "n_trials": 1,
            "live_ann_sharpe_raw": float(ann),
            "n_closes": len(rr),
        }
    except Exception as exc:
        logger.warning("scheduler.champion_live_fail", extra={"err": str(exc)[:200]})
        return None


async def _job_weekly_tournament() -> None:
    """Lab tournament — sweep chunk'larından gerçek challenger ile.

    FIX 2026-05-27 (Faz 14.10): önceki versiyon `champion={"noop"...}`
    + `challengers=[]` ile çağırıyordu → tournament rows hep boş.
    Şimdi: LabScientist.weekly_tournament(challengers=None) çağrılır
    → `_collect_active_challengers()` sweep aggregator + hipotez
    placeholder'ı birleştirir → gerçek rows üretir.

    FIX 2026-07-02 (fabrika RW P0-3): champion artık canlı borsa-truth
    R-serisiyle besleniyor (_champion_live_oos) — Welch testi ilk kez
    gerçek veriyle çalışır. Borsa erişilemezse eski statik proxy fallback.
    """
    try:
        import asyncio

        from price_action.agents import LabScientistAgent

        # OTONOMI-1 (2026-07-07, PROGRAM_V2 4b): challenger-yoksa-skip ön-kontrolü.
        # Yeni challenger materyali yokken Opus'la turnuva koşmak boş törendi
        # (lab 443 çağrıyla 2. en büyük token kalemi). Deterministik kontrol:
        # son 24h'te yeni sweep chunk VEYA status=OK backtest sonucu var mı?
        # PA_TOURNAMENT_FORCE=1 ile bypass (haftalık tam tur / manuel).
        if os.environ.get("PA_TOURNAMENT_FORCE", "0") != "1":
            import json as _json
            import time as _time
            from pathlib import Path as _Path

            cutoff = _time.time() - 24 * 3600
            fresh = any(
                p.stat().st_mtime > cutoff
                for p in _Path("reports/param_sweep/chunks").glob("*.jsonl")
            )
            if not fresh:
                for p in _Path("memory/researcher/backtest_results").glob("*.json"):
                    if p.stat().st_mtime > cutoff:
                        try:
                            if _json.loads(p.read_text()).get("result", {}).get("status") == "OK":
                                fresh = True
                                break
                        except Exception:
                            continue
            if not fresh:
                logger.info(
                    "scheduler.tournament_skipped_no_challenger",
                    extra={"reason": "son 24h'te yeni chunk/OK-backtest yok"},
                )
                return

        champion = await asyncio.to_thread(_champion_live_oos)
        if champion is None:
            # Fallback: statik proxy (backtest header: DD -17%, sharpe ~1.5)
            champion = {
                "id": "live_vsa_climax_widestop_15m",
                "oos_returns": [],
                "oos_sharpe": 1.5,
                "oos_maxdd": 0.17,
                "n_trials": 30,
            }
        logger.info(
            "scheduler.tournament_champion",
            extra={
                "extra": {
                    "id": champion.get("id"),
                    "n_returns": len(champion.get("oos_returns", [])),
                    "oos_sharpe": champion.get("oos_sharpe"),
                    "live_ann_raw": champion.get("live_ann_sharpe_raw"),
                }
            },
        )
        result = await LabScientistAgent().weekly_tournament(
            champion=champion,
            challengers=None,  # auto-collect: sweep cells + hyp placeholders
        )
        # Tournament dosyası yazılıyorsa push (reports/lab/ son rapor)
        _push_latest_safe("lab", "*tournament*.md", level="INFO", caption="Lab Tournament Result")
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
            lab.append_learning(f"Drift alert: {result}", slug="drift-alert", confidence="high")
            # Faz 1.2: drift alarmı → Telegram WARN
            _push_critical_safe(
                f"DRIFT detected: {result}",
                source="lab_scientist",
            )
    except Exception as exc:
        logger.warning("scheduler.drift_fail", extra={"err": str(exc)[:200]})


async def _job_weekly_rag_refresh() -> None:
    try:
        import asyncio

        from price_action.agents import LabScientistAgent

        # EMPTY-CORPUS GUARD 2026-05-29 (Ops): haftalık rag_refresh incremental
        # (since_days=7) — boş corpus'u ASLA backfill edemez ("0 yeni doc" deyip
        # geçer). Corpus boşsa (hiç gerçek ingest çalışmadıysa) önce tam ingest
        # yap; yoksa Researcher RAG=0 ile her hipotezi self-abort eder (SOP-5).
        from price_action.rag.ingest import gather_items, ingest_items, load_seeds
        from price_action.rag.store import RAGStore

        _RAG_EMPTY_THRESHOLD = 50
        _n = RAGStore().count()
        if _n < _RAG_EMPTY_THRESHOLD:
            logger.warning(
                "scheduler.rag_corpus_empty_backfill",
                extra={"count": _n, "threshold": _RAG_EMPTY_THRESHOLD},
            )
            _seeds = load_seeds()
            _items = await asyncio.to_thread(gather_items, _seeds)
            _stats = await asyncio.to_thread(ingest_items, _items, _seeds)
            logger.info("scheduler.rag_backfill_done", extra={"stats": _stats})

        await LabScientistAgent().rag_refresh(since_days=7)
        # Faz 1.2: RAG refresh raporu — sessiz başarı, sadece hata push
    except Exception as exc:
        logger.warning("scheduler.rag_refresh_fail", extra={"err": str(exc)[:200]})


def _is_last_day_of_month() -> bool:
    """FIX 2026-07-07 (denetim D12): '28-31' cron'u ayda 2-4 kez ateşliyordu —
    aylık job'lar sadece ayın SON günü koşmalı (yarın ayın 1'i ise bugün son gün)."""
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    return (_dt.now(UTC) + _td(days=1)).day == 1


async def _job_monthly_review() -> None:
    if not _is_last_day_of_month():
        return
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
                from price_action.notifications.telegram import send_telegram

                from .notifications import should_push

                if should_push():
                    send_telegram(
                        f"⚠️ Token budget %80+ — {agents_warn}",
                        level="WARNING",
                    )
            except Exception as _push_exc:
                # FIX 2026-05-26 (H1): silent pass → log; Telegram fail görünür olsun
                logger.warning(
                    "scheduler.token_warn_push_fail",
                    extra={"err": str(_push_exc)[:200], "agents_warn": agents_warn},
                )
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
        import subprocess
        from datetime import datetime as _dt

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
        except Exception as _pgrep_exc:
            # FIX 2026-05-26 (H1)
            logger.warning("scheduler.pgrep_fail", extra={"err": str(_pgrep_exc)[:200]})

        # 2. Canlı daemon log freshness — EN TAZE futures_daemon*.log'u izle.
        # FIX 2026-06-04: hardcoded futures_daemon.log champion'a aitti; champion
        # emekli edilince (launchctl bootout) o log donuyor → sahte "1800dk eski"
        # alarmı. v13 futures_daemon_v13.log, 5m futures_daemon_5m.log yazıyor.
        # En taze olanın yaşına bak → hangi daemon canlıysa onu izler, emekli
        # olanın ölü logu false-alarm üretmez.
        _logs_dir = s.reports_dir.parent / "logs"
        _daemon_logs = list(_logs_dir.glob("futures_daemon*.log"))
        if _daemon_logs:
            _newest = max(_daemon_logs, key=lambda p: p.stat().st_mtime)
            age_min = (_dt.now().timestamp() - _newest.stat().st_mtime) / 60
            if age_min > 30:
                issues.append(f"{_newest.name} {int(age_min)}dk eski (>30dk)")

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
                out = subprocess.run(
                    ["du", "-sm", str(logs_dir)], capture_output=True, text=True, timeout=10
                )
                if out.stdout:
                    mb = int(out.stdout.split()[0])
                    if mb > 1024:
                        issues.append(f"logs/ {mb}MB (>1GB) — rotation gecikmiş")
            except Exception as _du_exc:
                # FIX 2026-05-26 (H1)
                logger.warning("scheduler.du_fail", extra={"err": str(_du_exc)[:200]})

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
        from datetime import datetime as _dt

        iso = _dt.now(UTC).isocalendar()
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


async def _job_reconcile_journal() -> None:
    """FIX 2026-05-26 (Faz 14.6): Journal/Exchange state reconciler.

    Her 15dk: borsa açık pozisyonlarını journal ile karşılaştır.
    - Journal "açık" ama borsada yok → orphan, otomatik close (reconcile_orphan)
    - Borsada var, journal'da yok → phantom, Telegram alert (manuel inceleme)
    """
    try:
        import asyncio
        import subprocess
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        cmd = [
            str(repo_root / ".venv" / "bin" / "python"),
            "scripts/reconcile_journal.py",
        ]
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            # Anlamlı çıktıyı logla
            if (
                "orphans_closed" in result.stdout
                and "0" not in result.stdout.split("orphans_closed")[1][:20]
            ):
                logger.info("scheduler.reconcile_done", extra={"stdout_tail": result.stdout[-300:]})
        else:
            logger.warning(
                "scheduler.reconcile_fail",
                extra={"rc": result.returncode, "stderr": result.stderr[-300:]},
            )
    except Exception as exc:
        logger.warning("scheduler.reconcile_exc", extra={"err": str(exc)[:200]})


async def _job_truth_report() -> None:
    """FIX 2026-05-26 (Faz 14.4): Daily Truth Report.

    Her sabah 03:00 UTC (06:00 TR). Sistemin gerçek durumunu aggregate
    eder ve Telegram'a tek mesaj olarak gönderir. Provenance + drift +
    promises + pozisyonlar + alert'ler + commit'ler.

    Bu rapor bir gün sen okumadan giderse — sistem yalan söylüyor demektir.
    """
    try:
        import asyncio
        import subprocess
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        cmd = [
            str(repo_root / ".venv" / "bin" / "python"),
            "scripts/truth_report.py",
        ]
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info("scheduler.truth_report_done", extra={"stdout_tail": result.stdout[-300:]})
        else:
            logger.warning(
                "scheduler.truth_report_fail",
                extra={"rc": result.returncode, "stderr": result.stderr[-300:]},
            )
    except Exception as exc:
        logger.warning("scheduler.truth_report_exc", extra={"err": str(exc)[:200]})


async def _job_quiet_failure_audit() -> None:
    """FIX 2026-05-26 (Faz 14.3): Adversary quiet failure hunt.

    Promise/Reality detector eksiklikleri yakaladığı için bu job
    DAHA DERIN sorular sorar: config drift, silent agents, never-written
    files, atrophied output directories. Haftada bir Pazar gecesi.
    """
    try:
        from price_action.agents import AdversaryEngineerAgent

        ae = AdversaryEngineerAgent()
        path = await ae.quiet_failure_audit()
        logger.info(
            "scheduler.quiet_failure_audit_done",
            extra={"path": str(path) if path else None},
        )
    except Exception as exc:
        logger.warning("scheduler.quiet_failure_audit_fail", extra={"err": str(exc)[:200]})


def _register_event_handlers_once() -> None:
    """FIX 2026-05-28 (Faz 14.27 FINAL): Event bus handler wire-up.

    Scheduler startup'ta tek seferlik register: configs/event_subscribers.yaml
    okunmaz, doğrudan code-level mapping kullanılır (deklaratif YAML deps eklenebilir
    sonra). Bu fonksiyon main() veya register_jobs() içinden çağrılır.
    """
    try:
        from price_action.events import EventTopic, register_handler
    except Exception:
        return

    async def _handle_pause_alert(env):
        """Bot Monitor PAUSE → Adversary daily_stress_test."""
        try:
            from price_action.agents import AdversaryEngineerAgent

            ae = AdversaryEngineerAgent()
            bot_id = env.payload.get("bot_id", "futures15m")
            await ae.daily_stress_test(
                bot_id
            )  # FIX 2026-07-07: str bekler, liste config-miss yaratıyordu
            logger.info(
                "event_handler.pause_alert_done",
                extra={"extra": {"bot_id": bot_id, "event_id": env.event_id}},
            )
        except Exception as exc:
            logger.warning("event_handler.pause_alert_fail", extra={"err": str(exc)[:200]})

    async def _handle_phantom(env):
        """Reconciler phantom → Bot Monitor anomaly + Risk Officer audit."""
        try:
            from price_action.agents import BotMonitorAgent

            bm = BotMonitorAgent()
            # Anomaly log (placeholder — gerçek method bot_monitor.py'de)
            logger.info(
                "event_handler.phantom_logged",
                extra={"extra": {"symbol": env.payload.get("symbol"), "event_id": env.event_id}},
            )
        except Exception as exc:
            logger.warning("event_handler.phantom_fail", extra={"err": str(exc)[:200]})

    async def _handle_drift(env):
        """WR/R drift → Researcher hypothesis."""
        try:
            from price_action.agents import ResearcherAgent

            r = ResearcherAgent()
            drift_type = env.payload.get("drift_type", "unknown")
            await r.propose_hypothesis(f"Drift detected ({drift_type}): {env.payload}")
            logger.info(
                "event_handler.drift_response_done",
                extra={"extra": {"drift_type": drift_type, "event_id": env.event_id}},
            )
        except Exception as exc:
            logger.warning("event_handler.drift_fail", extra={"err": str(exc)[:200]})

    register_handler(EventTopic.BOT_MONITOR_PAUSE, _handle_pause_alert)
    register_handler(EventTopic.RECONCILER_PHANTOM, _handle_phantom)
    register_handler(EventTopic.RECONCILER_QTY_DRIFT, _handle_phantom)
    register_handler(EventTopic.DRIFT_WR_DROP, _handle_drift)
    register_handler(EventTopic.DRIFT_R_DROP, _handle_drift)
    register_handler(EventTopic.DRIFT_REGIME_CHANGE, _handle_drift)
    logger.info("scheduler.event_handlers_registered", extra={"extra": {"n": 6}})


async def _job_event_bus_dispatch() -> None:
    """FIX 2026-05-28 (Faz 14.27 KRITIK-1): Event bus dispatcher.

    Son 1h içinde publish edilmiş ack edilmemiş event'leri configs/
    event_subscribers.yaml'a göre uygun consumer'a route eder.

    Cron: */15 * * * * (her 15dk, hızlı tepki)
    """
    try:
        import yaml as _yaml

        from price_action.events import replay_recent

        # Subscriber registry yükle
        config_path = Path("configs/event_subscribers.yaml")
        if not config_path.exists():
            return
        subs = _yaml.safe_load(config_path.read_text()).get("subscribers", {}) or {}

        events = replay_recent(hours_back=1)
        n_dispatched = 0
        # Dedup state — sub başına işlenmiş event_id'leri tut
        dedup_path = Path("logs/state/event_bus_dispatched.json")
        dedup_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            already = __import__("json").loads(dedup_path.read_text())
        except Exception:
            already = {}

        for env in events:
            topic = env.topic
            consumers = subs.get(topic, [])
            for sub in consumers:
                key = f"{env.event_id}:{sub['consumer']}:{sub['action']}"
                if already.get(key):
                    continue
                # Dispatch — basit log + dedup
                logger.info(
                    "scheduler.event_bus_dispatch",
                    extra={
                        "extra": {
                            "event_id": env.event_id,
                            "topic": topic,
                            "consumer": sub["consumer"],
                            "action": sub["action"],
                        }
                    },
                )
                already[key] = True
                n_dispatched += 1

        try:
            dedup_path.write_text(__import__("json").dumps(already))
        except Exception:
            pass

        if n_dispatched > 0:
            logger.info("scheduler.event_bus_done", extra={"extra": {"n_dispatched": n_dispatched}})
    except Exception as exc:
        logger.warning("scheduler.event_bus_fail", extra={"err": str(exc)[:200]})


async def _job_bot_monitor_adversary_hook() -> None:
    """FIX 2026-05-28 (Faz 14.27 C8): Bot Monitor PAUSE alert → Adversary tetik.

    Önceki bug: Bot Monitor kill_criteria_alert (PAUSE) yazıyordu ama
    Adversary engineer'a otomatik tetik yoktu. Şimdi: inbox tarama,
    son 6h içinde kill_criteria_alert + ack_at=null var ise Adversary
    stress test çalıştır (alert'in işaret ettiği bot için).
    """
    try:
        import json
        from datetime import datetime as _dt
        from datetime import timedelta as _td
        from pathlib import Path

        inbox = Path("memory/protocol/inbox.jsonl")
        if not inbox.exists():
            return
        now = _dt.now(UTC)
        cutoff = now - _td(hours=6)
        pause_alerts = []
        for line in inbox.read_text(encoding="utf-8").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("topic") != "kill_criteria_alert":
                continue
            if msg.get("ack_at"):
                continue
            try:
                created = _dt.fromisoformat(msg.get("created_at", "").replace("Z", "+00:00"))
                if created < cutoff:
                    continue
            except Exception:
                continue
            pause_alerts.append(msg)

        if not pause_alerts:
            return

        # Hangi bot için PAUSE alert var? Genelde doc_id'de bot_name ipucu var.
        from price_action.agents import AdversaryEngineerAgent

        ae = AdversaryEngineerAgent()
        # PAUSE alert için stress test tetikle
        for alert in pause_alerts[:3]:
            bot_id = "futures15m"  # default (v15p2 pool'u yok; en yakın vekil)
            doc_id = alert.get("doc_id", "")
            if "futures5m" in doc_id:
                bot_id = "futures5m"
            elif "v63" in doc_id or "rsi2" in doc_id:
                bot_id = "futures15m_v63"
            elif "v11" in doc_id or "vwap" in doc_id:
                bot_id = "futures15m_v11"
            try:
                path = await ae.daily_stress_test(
                    bot_id
                )  # FIX 2026-07-07: str bekler, liste config-miss yaratıyordu
                logger.info(
                    "scheduler.bot_monitor_adversary_hook_done",
                    extra={
                        "extra": {
                            "bot_id": bot_id,
                            "trigger_doc": doc_id,
                            "report": str(path) if path else None,
                        }
                    },
                )
            except Exception as exc:
                logger.warning(
                    "scheduler.bot_monitor_adversary_hook_fail",
                    extra={"err": str(exc)[:200], "bot_id": bot_id},
                )
    except Exception as exc:
        logger.warning(
            "scheduler.bot_monitor_adversary_hook_outer_fail", extra={"err": str(exc)[:200]}
        )


async def _job_slippage_daily_summary() -> None:
    """FIX 2026-05-28 (Faz 14.27 C4): SlippageTracker günlük özet — 23:30 UTC.

    Önceki bug: daily_summary metodu vardı ama hiç tetiklenmiyordu →
    daily_slippage_summary tablosu BOŞ → outlier detection inaktif.
    """
    try:
        from price_action.execution.slippage_tracker import SlippageTracker

        st = SlippageTracker()
        summary = st.daily_summary()
        logger.info("scheduler.slippage_daily_done", extra={"extra": summary})
    except Exception as exc:
        logger.warning("scheduler.slippage_daily_fail", extra={"err": str(exc)[:200]})


async def _job_slippage_weekly_summary() -> None:
    """FIX 2026-05-28 (Faz 14.27 C4): Haftalık slippage trend — Pazar 05:30 UTC.

    Önceki bug: weekly raporlama hiç yoktu → slippage trend görünmez.
    """
    try:
        from price_action.execution.slippage_tracker import SlippageTracker

        st = SlippageTracker()
        summary = st.weekly_summary()
        # Telegram WARN if avg_slippage > prev week +20% veya outlier var
        try:
            change = summary["vs_previous_week"]["avg_slippage_change_pct"]
            n_out = len(summary["outlier_fills_top10"])
            if (change is not None and change > 20) or n_out > 5:
                from price_action.orchestrator.notifications import push_critical

                push_critical(
                    f"⚠️ Weekly slippage drift — avg change={change}%, outliers={n_out}",
                    source="scheduler_slippage_weekly",
                )
        except Exception:
            pass
        logger.info(
            "scheduler.slippage_weekly_done",
            extra={
                "extra": {
                    "week_end": summary.get("week_end"),
                    "current_avg_bps": summary.get("current_week", {}).get("avg_slippage_bps"),
                    "outliers_n": len(summary.get("outlier_fills_top10", [])),
                }
            },
        )
    except Exception as exc:
        logger.warning("scheduler.slippage_weekly_fail", extra={"err": str(exc)[:200]})


async def _job_active_state_refresh() -> None:
    """FIX 2026-05-28 (Faz 14.27 — B2): active_state.md saatlik update.

    Önceki bug: active_state.md sadece daily_brief'te (günde 1 kez) update
    ediliyordu → 9h+ stale olabiliyordu (Faz D audit bulgusu).

    Bu cron 25 * * * * (her saat HH:25) tetiklenir, CEO.update_active_state
    çağırır. Inbox + decisions + breaker state yenilenir.
    """
    try:
        from price_action.agents import CEOAgent

        ceo = CEOAgent()
        path = ceo.update_active_state()
        logger.info(
            "scheduler.active_state_refresh_done",
            extra={"extra": {"path": str(path) if path else None}},
        )
    except Exception as exc:
        logger.warning("scheduler.active_state_refresh_fail", extra={"err": str(exc)[:200]})


async def _job_data_health_daily() -> None:
    """FIX 2026-05-28 (Faz 14.27 — B1): DataEngineer günlük health check.

    Önceki bug: data_engineer.py agent class HİÇ YOKTU → cron tetikleyemez,
    memory/data_engineer/ klasörü 6+ gün boyunca güncellenmedi (Faz D audit
    bulgusu).

    Bu cron 06:30 UTC günlük (09:30 TR) tetiklenir:
      - market.duckdb tazeligi check
      - regime_features parquet doğruluğu
      - reconcile trend (phantom/orphan)
      - anomali varsa Ops Engineer'a review request
    """
    try:
        from price_action.agents import DataEngineerAgent

        de = DataEngineerAgent()
        path = await de.daily_health_summary()
        logger.info(
            "scheduler.data_health_daily_done",
            extra={"extra": {"path": str(path) if path else None}},
        )
    except Exception as exc:
        logger.warning("scheduler.data_health_daily_fail", extra={"err": str(exc)[:200]})


async def _job_stuck_doc_check() -> None:
    """FIX 2026-05-28 (Faz 14.27): Stuck inbox doc detector.

    Bot Monitor 27 Mayıs 23:45'te PAUSE alert yazdı (DD %43), 13+ saat ack
    edilmedi (Risk Officer review_fail çünkü ANTHROPIC_API_KEY=placeholder
    → Claude CLI 401). Principal'a HİÇ ulaşmadı.

    Bu job her saat inbox.jsonl tarar:
      - kill_criteria_alert + ack_at=null + age > 6h → CRIT push
      - critique + ack_at=null + age > 12h → CRIT push
      - başka doc + ack_at=null + age > 48h → WARN push

    Tek doc başına 1 push (idempotency: doc_id hash kayıtlı, tekrar push yok).
    """
    try:
        import json
        from datetime import datetime, timedelta
        from pathlib import Path

        inbox = Path("memory/protocol/inbox.jsonl")
        if not inbox.exists():
            return

        now = datetime.now(UTC)
        # FIX 2026-05-30: SADECE gerçekten aksiyon/principal gerektiren topic'ler
        # page eder. Önceki "default 48h" tüm bilgilendirme/danışma akışını
        # (bot_daily_card, bot_health_report, endorse, tournament, whatif,
        # market_feasibility, strategy_correlation/lifecycle, adversarial_test,
        # new_hypothesis) "stuck" sayıp yanlış-pozitif CRIT basıyordu — bunlar
        # agent-to-agent otonom akış, tüketilmese de operatör eylemi gerekmez.
        # Aksiyon-gerektiren: kill_criteria_alert (güvenlik) + critique (CEO
        # review gate). Sadece bunlar alarm verir.
        thresholds = {
            "kill_criteria_alert": timedelta(hours=6),
            "critique": timedelta(hours=12),
        }
        actionable_topics = set(thresholds.keys())
        # Per-doc dedup (saatlik tetik → her doc 1 push)
        stuck_state_path = Path("logs/state/stuck_docs_pushed.json")
        stuck_state_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            pushed_already = json.loads(stuck_state_path.read_text())
        except Exception:
            pushed_already = {}

        stuck = []
        for line in inbox.read_text(encoding="utf-8").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("ack_at"):
                continue
            # FIX 2026-05-30: yalnızca aksiyon-gerektiren topic'ler alarm verir.
            if msg.get("topic") not in actionable_topics:
                continue
            created = msg.get("created_at", "")
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except Exception:
                continue
            age = now - created_dt
            doc_id = msg.get("doc_id", "")
            topic = msg.get("topic", "")
            # Eşik (sadece actionable_topics buraya ulaşır)
            thr = thresholds[topic]
            if age < thr:
                continue
            # Dedup — bu doc bu süre içinde push edildi mi?
            dedup_key = f"{doc_id}:{topic}"
            if pushed_already.get(dedup_key, 0) > 1:
                continue  # 2+ kez push edildi, susalım
            stuck.append((doc_id, topic, age, msg, dedup_key))

        if not stuck:
            return

        try:
            from price_action.orchestrator.notifications import push_critical

            lines = [f"⚠️ STUCK INBOX DOCS — {len(stuck)} doc ack-timeout aştı:"]
            for doc_id, topic, age, msg, _ in stuck[:5]:
                lines.append(
                    f"  - [{topic}] {doc_id} (recipient={msg.get('recipient')}, "
                    f"age={age.total_seconds()/3600:.1f}h)"
                )
            lines.append(
                "Sebep: LLM agent fail (API key, circuit breaker) veya "
                "Principal eylem bekliyor. Inbox: memory/protocol/inbox.jsonl"
            )
            push_critical("\n".join(lines), source="scheduler_stuck_doc")
        except Exception as exc:
            logger.warning("scheduler.stuck_doc_push_fail", extra={"err": str(exc)[:200]})

        # Push counter güncelle
        for _, _, _, _, dedup_key in stuck:
            pushed_already[dedup_key] = pushed_already.get(dedup_key, 0) + 1
        try:
            stuck_state_path.write_text(json.dumps(pushed_already))
        except Exception:
            pass

        logger.info("scheduler.stuck_doc_check_done", extra={"extra": {"n_stuck": len(stuck)}})

    except Exception as exc:
        logger.warning("scheduler.stuck_doc_check_fail", extra={"err": str(exc)[:200]})


async def _job_check_promises() -> None:
    """FIX 2026-05-26 (Faz 14.2): Promise/Reality detector.

    configs/promises.yaml'daki SLA beyanlarını her saat kontrol eder.
    CRIT ihlal varsa push_critical Telegram alert.
    """
    try:
        import asyncio
        import subprocess
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        cmd = [
            str(repo_root / ".venv" / "bin" / "python"),
            "scripts/check_promises.py",
        ]
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            logger.info(
                "scheduler.promises_check_done", extra={"stdout_tail": result.stdout[-300:]}
            )
        else:
            logger.warning(
                "scheduler.promises_check_fail",
                extra={"rc": result.returncode, "stderr": result.stderr[-300:]},
            )
    except Exception as exc:
        logger.warning("scheduler.promises_check_exc", extra={"err": str(exc)[:200]})


async def _job_dms_heartbeat_check() -> None:
    """FIX 2026-05-26 (M5): DMS heartbeat staleness automated check.

    Önceden DMS dosyaları sadece Bot Monitor saatlik snapshot içinde
    kontrol ediliyordu, Telegram'a push olmuyordu. Bu job her 5dk
    heartbeat dosyalarını kontrol eder; stale (>5dk) ise CRIT alert.
    """
    try:
        from datetime import datetime as _dt

        from price_action.settings import get_settings

        s = get_settings()
        data_dir = s.reports_dir.parent / "data"
        if not data_dir.exists():
            return
        now = _dt.now(UTC)
        stale_threshold_min = 5
        abandoned_threshold_min = 60 * 24  # FIX 2026-05-26 (Faz 14.8): 24h+ phantom
        # FIX 2026-05-30: paper/backtest modunda CANLI execution döngüsü yok →
        # dms_heartbeat_execution.txt güncellenmiyor (phantom). Koruduğu canlı
        # emir olmadığı için staleness alarmı yanlış-pozitif. Yalnızca live
        # modda execution heartbeat anlamlı. Trading daemon heartbeat'leri
        # (futures_daemon_15m/5m) her modda kontrol edilir — onlar her zaman canlı.
        run_mode = str(getattr(s, "pa_run_mode", "paper")).lower()
        for hb in data_dir.glob("dms_heartbeat_*.txt"):
            # Skip test heartbeat dosyaları
            if "test" in hb.name.lower():
                continue
            # Skip execution-layer heartbeat when not live (paper phantom)
            if "execution" in hb.name.lower() and run_mode != "live":
                # 1 kez sessizce temizle (yeniden birikmesin), alarm verme
                try:
                    age_min_exec = (
                        now - _dt.fromtimestamp(hb.stat().st_mtime, tz=UTC)
                    ).total_seconds() / 60
                    if age_min_exec > stale_threshold_min:
                        hb.unlink()
                        logger.info(
                            "scheduler.dms_execution_phantom_removed",
                            extra={"file": hb.name, "run_mode": run_mode},
                        )
                except Exception:
                    pass
                continue
            try:
                mtime = _dt.fromtimestamp(hb.stat().st_mtime, tz=UTC)
                age_min = (now - mtime).total_seconds() / 60
                # FIX 2026-05-26: 24h+ eski → abandoned phantom, sessizce sil
                if age_min > abandoned_threshold_min:
                    try:
                        hb.unlink()
                        logger.info(
                            "scheduler.dms_phantom_removed",
                            extra={"file": hb.name, "age_min": round(age_min, 1)},
                        )
                    except Exception:
                        pass
                    continue
                if age_min > stale_threshold_min:
                    # FIX 2026-05-26: throttle 1h, aynı dosya için tekrarlanmasın
                    try:
                        from price_action.ops.telegram_throttle import get_telegram_throttle

                        get_telegram_throttle().send_throttled(
                            alert_type=f"dms_stale_{hb.name}",
                            message=(
                                f"⚠️ DMS heartbeat eski — {hb.name}\n"
                                f"Son güncelleme: {age_min:.0f}dk önce (eşik {stale_threshold_min}dk).\n"
                                f"Olası sebep: daemon dondu/kapandı. futures15m/5m POS_CHECK log'una bak."
                            ),
                            level="WARNING",
                        )
                    except Exception:
                        _push_critical_safe(
                            f"DMS heartbeat STALE: {hb.name} {age_min:.1f}dk eski",
                            source="dms_monitor",
                        )
                    logger.error(
                        "scheduler.dms_stale",
                        extra={"file": hb.name, "age_min": round(age_min, 1)},
                    )
            except Exception as exc:
                logger.warning(
                    "scheduler.dms_check_file_fail",
                    extra={"file": hb.name, "err": str(exc)[:200]},
                )
    except Exception as exc:
        logger.warning("scheduler.dms_check_fail", extra={"err": str(exc)[:200]})


# FIX 2026-05-28 (depo-ayirma + freshness): kritik feed staleness watchdog.
# Throttle state'i process-ömründe module-level dict'te tutulur (her cron run'da
# yeni instance yaratıp last_sent sıfırlamak yanlış olurdu). feed başına son
# alarm zamanı.
_FRESHNESS_LAST_ALERT: dict[str, float] = {}


def _freshness_should_alert(key: str, throttle_s: float) -> bool:
    """feed başına throttle. True → şimdi alarm gönder (ve zaman damgala)."""
    import time as _t

    now = _t.time()
    last = _FRESHNESS_LAST_ALERT.get(key, 0.0)
    if now - last >= throttle_s:
        _FRESHNESS_LAST_ALERT[key] = now
        return True
    return False


def _check_freshness(now=None) -> list[dict[str, Any]]:
    """Saf, side-effect-free kontrol — test edilebilir.

    Her kritik feed için (kaynak, yaş, SLA, ihlal mi) hesaplar. Alarm GÖNDERMEZ;
    sadece ihlal listesini döner. _job_freshness_watchdog bunu çağırıp throttle'lı
    alarm üretir. SLA'lar:
      - market.duckdb newest bar  > 2h  → freshness_market_stale
      - RAG corpus count          < 50  → freshness_rag_empty
      - regime_features_latest    > 6h  → freshness_regime_stale
      - futures daemon heartbeat  > 20m → freshness_futures_hb_stale

    Returns: ihlal dict listesi. Her dict: {alert_type, level, message, key}.
    """
    from datetime import datetime as _dt
    from pathlib import Path as _Path

    if now is None:
        now = _dt.now(UTC)
    violations: list[dict[str, Any]] = []

    try:
        from price_action.settings import get_settings as _gs

        s = _gs()
        data_dir = _Path(s.duckdb_path).parent
    except Exception:
        from pathlib import Path as _P

        data_dir = _P(__file__).resolve().parents[3] / "data"
        s = None

    # --- 1) market.duckdb newest bar > 2h --------------------------------
    try:
        market_db = _Path(s.duckdb_path) if s is not None else data_dir / "market.duckdb"
        if not market_db.exists():
            violations.append(
                {
                    "alert_type": "freshness_market_stale",
                    "level": "CRITICAL",
                    "key": "market_stale",
                    "message": f"market.duckdb YOK: {market_db}",
                }
            )
        else:
            import duckdb as _ddb

            _c = _ddb.connect(str(market_db), read_only=True)
            try:
                _row = _c.execute("SELECT MAX(ts) FROM ohlcv").fetchone()
            finally:
                _c.close()
            newest = _row[0] if _row else None
            if newest is None:
                violations.append(
                    {
                        "alert_type": "freshness_market_stale",
                        "level": "CRITICAL",
                        "key": "market_stale",
                        "message": "market.duckdb ohlcv boş (MAX(ts)=NULL)",
                    }
                )
            else:
                if getattr(newest, "tzinfo", None) is None:
                    newest = newest.replace(tzinfo=UTC)
                age_h = (now - newest).total_seconds() / 3600
                if age_h > 2.0:
                    violations.append(
                        {
                            "alert_type": "freshness_market_stale",
                            "level": "CRITICAL",
                            "key": "market_stale",
                            "message": (
                                f"market.duckdb BAYAT: newest bar {newest} "
                                f"({age_h:.1f}h önce, SLA 2h). Ingest/snapshot durmuş olabilir → "
                                f"tüm downstream (regime/lab/backtest/drift) eski veri okuyor."
                            ),
                        }
                    )
    except Exception as exc:
        violations.append(
            {
                "alert_type": "freshness_market_stale",
                "level": "CRITICAL",
                "key": "market_stale",
                "message": f"market.duckdb kontrol hatası: {str(exc)[:200]}",
            }
        )

    # --- 2) RAG corpus count < 50 ----------------------------------------
    try:
        from price_action.rag.store import RAGStore

        n = RAGStore().count()
        if n < 50:
            violations.append(
                {
                    "alert_type": "freshness_rag_empty",
                    "level": "CRITICAL",
                    "key": "rag_empty",
                    "message": (
                        f"RAG corpus DÜŞÜK: {n} doküman (<50). Researcher/Lab boş RAG ile "
                        f"hipotez üretiyorsa kalite çöker — embedding/index kayıp olabilir."
                    ),
                }
            )
    except Exception as exc:
        violations.append(
            {
                "alert_type": "freshness_rag_empty",
                "level": "WARNING",
                "key": "rag_empty",
                "message": f"RAG corpus kontrol hatası: {str(exc)[:200]}",
            }
        )

    # --- 3) regime_features_latest.parquet > 6h --------------------------
    try:
        rp = data_dir / "regime_features_latest.parquet"
        if not rp.exists():
            violations.append(
                {
                    "alert_type": "freshness_regime_stale",
                    "level": "WARNING",
                    "key": "regime_stale",
                    "message": "regime_features_latest.parquet YOK",
                }
            )
        else:
            mtime = _dt.fromtimestamp(rp.stat().st_mtime, tz=UTC)
            age_h = (now - mtime).total_seconds() / 3600
            if age_h > 6.0:
                violations.append(
                    {
                        "alert_type": "freshness_regime_stale",
                        "level": "WARNING",
                        "key": "regime_stale",
                        "message": (
                            f"regime_features_latest.parquet BAYAT: {age_h:.1f}h "
                            f"(SLA 6h). regime_features_refresh cron'u çalışmıyor olabilir."
                        ),
                    }
                )
    except Exception as exc:
        violations.append(
            {
                "alert_type": "freshness_regime_stale",
                "level": "WARNING",
                "key": "regime_stale",
                "message": f"regime parquet kontrol hatası: {str(exc)[:200]}",
            }
        )

    # --- 4) futures daemon heartbeat > 20dk ------------------------------
    # FIX 2026-07-02 (ops RW B1): 5m daemon 30 Haz'da KALICI emekli edildi
    # (com.priceaction.futures5m bootout+disable+plist→disabled/). Hardcoded
    # 5m heartbeat beklentisi saatlik false-CRIT üretiyordu ("heartbeat YOK")
    # → alarm yorgunluğu. Emeklilikle senkron: sadece canlı daemon'lar listede.
    try:
        for hb_name in ("dms_heartbeat_futures_daemon_15m.txt",):
            hb = data_dir / hb_name
            if not hb.exists():
                violations.append(
                    {
                        "alert_type": "freshness_futures_hb_stale",
                        "level": "CRITICAL",
                        "key": f"futures_hb_{hb_name}",
                        "message": f"futures daemon heartbeat YOK: {hb_name}",
                    }
                )
                continue
            mtime = _dt.fromtimestamp(hb.stat().st_mtime, tz=UTC)
            age_m = (now - mtime).total_seconds() / 60
            if age_m > 20.0:
                violations.append(
                    {
                        "alert_type": "freshness_futures_hb_stale",
                        "level": "CRITICAL",
                        "key": f"futures_hb_{hb_name}",
                        "message": (
                            f"futures daemon DONMUŞ olabilir: {hb_name} heartbeat "
                            f"{age_m:.0f}dk eski (SLA 20dk)."
                        ),
                    }
                )
    except Exception as exc:
        violations.append(
            {
                "alert_type": "freshness_futures_hb_stale",
                "level": "WARNING",
                "key": "futures_hb_err",
                "message": f"futures hb kontrol hatası: {str(exc)[:200]}",
            }
        )

    return violations


async def _job_freshness_watchdog() -> None:
    """FIX 2026-05-28 (depo-ayirma + freshness): kritik feed staleness watchdog.

    Her saat (:12) tüm kritik feed'lerin tazeligini SLA'ya göre kontrol eder.
    İhlalde GÜRÜLTÜLÜ alarm (yeni alert_type'lar — mevcut muted tiplerle
    çakışmaz). Throttle feed başına 4h (spam önle, ama gerçek incident kaçmaz).

    YENİ alert_type'lar (mute listesinde DEĞİL):
      freshness_market_stale, freshness_rag_empty,
      freshness_regime_stale, freshness_futures_hb_stale

    Mevcut muted/ayrı tipler (dms_stale_, regime_cache_stale_warn,
    scheduler_stuck_doc, promise_detector) DOKUNULMAZ — onları yeniden açmaz.
    """
    try:
        violations = await __import__("asyncio").to_thread(_check_freshness)
        if not violations:
            logger.info("scheduler.freshness_ok")
            return
        _THROTTLE_S = 4 * 3600  # feed başına 4h
        for v in violations:
            key = v.get("key", v["alert_type"])
            if not _freshness_should_alert(key, _THROTTLE_S):
                continue
            try:
                from price_action.ops.telegram_throttle import get_telegram_throttle

                get_telegram_throttle().send_throttled(
                    alert_type=v["alert_type"],
                    message="🚨 FRESHNESS: " + v["message"],
                    level=v.get("level", "CRITICAL"),
                )
            except Exception:
                _push_critical_safe("FRESHNESS: " + v["message"], source="freshness_watchdog")
            logger.error(
                "scheduler.freshness_violation",
                extra={"alert_type": v["alert_type"], "msg": v["message"][:200]},
            )
    except Exception as exc:
        logger.warning("scheduler.freshness_watchdog_fail", extra={"err": str(exc)[:200]})


async def _job_rotate_launchd_logs() -> None:
    """FIX 2026-05-26 (M1): launchd log rotation (size + retention)."""
    try:
        import asyncio
        import subprocess
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        cmd = [
            str(repo_root / ".venv" / "bin" / "python"),
            "scripts/rotate_launchd_logs.py",
        ]
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and "rotated=0" not in result.stdout:
            logger.info(
                "scheduler.log_rotate_done",
                extra={"stdout_tail": result.stdout[-300:]},
            )
    except Exception as exc:
        logger.warning("scheduler.log_rotate_fail", extra={"err": str(exc)[:200]})


async def _job_process_pending_entries() -> None:
    """FIX 2026-05-26 (H6): Pending retry queue processor.

    futures_daemon entry timeout durumunda sinyali pending_retries.jsonl'e
    yazıyor (daemon bloke olmasın diye). Bu cron her 60s queue'yu işler:
    fresh ticker fetch → slip kontrol → market order retry. Başarılı ise
    Telegram 'RESOLVED' alert. 2dk içinde başarısız ise 'MISSED' alert.
    """
    try:
        import asyncio
        import subprocess
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        cmd = [
            str(repo_root / ".venv" / "bin" / "python"),
            "scripts/process_pending_entries.py",
        ]
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            # Sadece "anlamlı" çıktıyı logla (read>0 olduğunda)
            if 'read": 0' not in result.stdout:
                logger.info(
                    "scheduler.pending_retry_done",
                    extra={"stdout_tail": result.stdout[-300:]},
                )
        else:
            logger.warning(
                "scheduler.pending_retry_fail",
                extra={"rc": result.returncode, "stderr": result.stderr[-300:]},
            )
    except Exception as exc:
        logger.warning("scheduler.pending_retry_exc", extra={"err": str(exc)[:200]})


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
            subprocess.run,
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info("scheduler.regime_refresh_ok", extra={"stdout_tail": result.stdout[-300:]})
        else:
            logger.error(
                "scheduler.regime_refresh_fail",
                extra={"rc": result.returncode, "stderr_tail": result.stderr[-300:]},
            )
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
        from pathlib import Path

        import yaml

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

    FIX 2026-05-26: önceden gün modulo ile 1 bot/gün rotation vardı.
    Yeni: her gece HER iki bot için stress test (paralel).

    FIX 2026-05-27 (Faz 14.14): pool parametresi her zaman None geçiyordu
    → adversary "no_pool_data" döndürüyor → DD=nan, equity gate fail.
    Şimdi: bot_id'ye göre R-multiple pool yüklenir + pnl_pct'e çevrilir.
    Adversary _replay_stress_period() pnl_pct toplamından equity curve
    + DD + recovery hesabını yapar.
    """
    try:
        import asyncio
        import pickle
        from pathlib import Path

        from price_action.agents import AdversaryEngineerAgent

        ae = AdversaryEngineerAgent()
        # FIX 2026-07-07 (denetim D5): futures5m 30 Haz'da kalıcı emekli —
        # ölü botun günlük stres raporu promise'ı yapay geçiriyordu, çıkarıldı.
        # NOT: vsa2 pool'u canlı v15p2'nin vsa koluna en yakın vekil; gerçek
        # v15p2 pool'u üretilene dek (açık iş P10) proxy olarak kalır.
        bots = ["futures15m"]
        BOT_POOL_MAP = {
            "futures15m": ("data/sec53_15m_pool_v11_vsa2_top4.pkl", 0.005),
        }

        def _load_pool_for_adversary(pool_path: str, risk_pct: float) -> list[dict]:
            """R-multiple pool → adversary format (ts iso + pnl_pct float)."""
            p = Path(pool_path)
            if not p.exists():
                logger.warning("scheduler.adversary_pool_missing", extra={"path": pool_path})
                return []
            try:
                with p.open("rb") as f:
                    raw = pickle.load(f)
            except Exception as _exc:
                logger.warning(
                    "scheduler.adversary_pool_load_fail",
                    extra={"path": pool_path, "err": str(_exc)[:200]},
                )
                return []
            converted: list[dict] = []
            for tr in raw:
                try:
                    ts = tr.get("entry_ts") or tr.get("exit_ts")
                    if ts is None:
                        continue
                    ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
                    # R → pnl_pct (yüzde, ör. 1R × %0.5 risk = %0.5)
                    R = float(tr.get("R", 0.0))
                    pnl_pct = R * float(risk_pct) * 100.0
                    converted.append(
                        {
                            "ts": ts_str,
                            "pnl_pct": pnl_pct,
                            "symbol": tr.get("symbol"),
                            "strategy": tr.get("strategy"),
                        }
                    )
                except Exception:
                    continue
            logger.info(
                "scheduler.adversary_pool_loaded",
                extra={"path": pool_path, "n_trades": len(converted), "risk_pct": risk_pct},
            )
            return converted

        # Her bot için pool yükle + adversary'ye geçir
        bot_pools: dict[str, list[dict]] = {}
        for bot_id in bots:
            if bot_id in BOT_POOL_MAP:
                pool_path, risk_pct = BOT_POOL_MAP[bot_id]
                bot_pools[bot_id] = _load_pool_for_adversary(pool_path, risk_pct)
            else:
                bot_pools[bot_id] = []

        # Paralel çalıştır (bağımsız işler, agent re-entrant)
        results = await asyncio.gather(
            *[ae.daily_stress_test(b, pool=bot_pools[b]) for b in bots],
            return_exceptions=True,
        )
        for bot_id, result in zip(bots, results, strict=False):
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
            except Exception as _crit_exc:
                # FIX 2026-05-26 (H1)
                logger.warning(
                    "scheduler.adversary_crit_check_fail",
                    extra={"bot": bot_id, "err": str(_crit_exc)[:200]},
                )
    except Exception as exc:
        logger.warning("scheduler.adversary_daily_fail", extra={"err": str(exc)[:200]})


async def _job_adversary_weekly_red_team() -> None:
    """Faz 9: Adversary Engineer haftalık red team raporu (tüm bot'lar)."""
    try:
        from price_action.agents import AdversaryEngineerAgent

        ae = AdversaryEngineerAgent()
        # FIX 2026-07-07 (denetim D5): emekli futures5m listeden çıkarıldı.
        path = await ae.weekly_red_team_report(["futures15m"])
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
            path,
            level="INFO",
            caption=f"Weekly Market Scout — {market_name}",
        )
    except Exception as exc:
        logger.warning("scheduler.weekly_market_scout_fail", extra={"err": str(exc)[:200]})


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


async def _job_feature_sweep() -> None:
    """OTONOMI-1 (2026-07-07): feature × forward-return korelasyon taraması.

    scripts/feature_sweep.py subprocess olarak koşar (deterministik, LLM yok).
    Spearman IC + BH-FDR + OOS onayı; adaylar sweep_candidates.jsonl'e.
    """
    try:
        import asyncio
        import subprocess
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        result = await asyncio.to_thread(
            subprocess.run,
            [str(repo_root / ".venv" / "bin" / "python"), "scripts/feature_sweep.py"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=1800,
        )
        tail = (result.stdout or "").strip().splitlines()[-1:] or [""]
        logger.info(
            "scheduler.feature_sweep_done",
            extra={"rc": result.returncode, "tail": tail[0][:200]},
        )
        if result.returncode != 0:
            logger.warning(
                "scheduler.feature_sweep_fail",
                extra={"stderr": (result.stderr or "")[-300:]},
            )
    except Exception as exc:
        logger.warning("scheduler.feature_sweep_fail", extra={"err": str(exc)[:200]})


async def _job_funding_refresh() -> None:
    """FIX 2026-07-07 (denetim V2): funding.duckdb 35 gün bayattı — hiçbir job
    yenilemiyordu; XS-carry (kalan tek araştırma kaldıracı) + AILE-2 girdisi
    donuktu. scripts/backfill_funding_rates.py idempotent upsert (funding + OI
    snapshot), günlük koşum güvenli.
    """
    try:
        import asyncio
        import subprocess
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        result = await asyncio.to_thread(
            subprocess.run,
            [
                str(repo_root / ".venv" / "bin" / "python"),
                "scripts/backfill_funding_rates.py",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=1800,
        )
        logger.info(
            "scheduler.funding_refresh_done",
            extra={"rc": result.returncode},
        )
        if result.returncode != 0:
            logger.warning(
                "scheduler.funding_refresh_fail",
                extra={"stderr": (result.stderr or "")[-300:]},
            )
    except Exception as exc:
        logger.warning("scheduler.funding_refresh_fail", extra={"err": str(exc)[:200]})


async def _job_researcher_improvement_pulse() -> None:
    """FIX 2026-05-26: Gün içi Researcher pulse'ları.

    Önceden Researcher sadece gece 02:00 (deep) + 02:30 (5-batch) çalışıyordu.
    Principal "gün içinde de üretsin, mevcut botu iyileştirsin" istedi.
    OTONOMI-1 (2026-07-07): temalar kanıt-temelli AILE-* rotasyonuna bağlandı
    (aşağıdaki `themes` listesi); eski futures5m/bayat tema listesi öldü.

    Her çağrı ~30-50K Opus token (kalan günlük 500K bütçe karşılar).
    """
    try:
        from datetime import datetime as _dt

        from price_action.agents import ResearcherAgent

        hour = _dt.now(UTC).hour
        # OTONOMI-1 (2026-07-07, PROGRAM_V2): temalar kanıt-temelli ailelere
        # bağlandı. Eski temalar bayattı (emekli futures5m'i refere ediyordu)
        # ve kanıtsızdı — 195 abort'luk seed-spin bunun sonucuydu. Tema-0 artık
        # feature_sweep'in İSTATİSTİKSEL adaylarını (FDR+OOS onaylı) hammadde
        # olarak prompt'a gömer: önce piyasayı ölç, sonra hipotez yaz.
        sweep_context = ""
        try:
            import json as _json
            from pathlib import Path as _Path

            cand_path = _Path("memory/researcher/sweep_candidates.jsonl")
            if cand_path.exists():
                cands = [
                    _json.loads(ln)
                    for ln in cand_path.read_text().splitlines()[-200:]
                    if ln.strip()
                ]
                cands.sort(key=lambda c: -abs(c.get("ic_oos", 0)))
                top = cands[:12]
                if top:
                    rows = "\n".join(
                        f"- {c['symbol']} | {c['feature']} -> {c['target']} | "
                        f"IC_is={c['ic_is']:+.3f} IC_oos={c['ic_oos']:+.3f}"
                        for c in top
                    )
                    sweep_context = (
                        "\n\nFEATURE-SWEEP ADAYLARI (FDR+OOS onaylı, feature_sweep.py):\n"
                        + rows
                        + "\nBu istatistiksel ilişkilerden EKONOMİK RASYONELİ olan birini "
                        "seç ve test edilebilir hipoteze dönüştür (pre-registration)."
                    )
        except Exception:  # pragma: no cover — sweep yoksa tema yine çalışır
            pass
        themes = [
            "AILE-SWEEP: Feature-sweep adaylarından TEK hipotez üret."
            + (
                sweep_context
                or " (Aday dosyası boş — mevcut 4 detektörün en zayıf rejimine odaklan.)"
            ),
            "AILE-TF: Mevcut 4 base stratejinin (vsa_climax/brooks_fb/avwap/engulfing) "
            "1h veya 4h TF varyantı — 15m parametrelerini TF'ye ölçekleyerek TEK somut, "
            "hypothesis_runner'ın KOŞABİLECEĞİ (base_strategy + param sweep) hipotez yaz.",
            "AILE-FUNDING: funding-ekstrem + OI-rejim koşullu mevcut detektör sinyali "
            "(PROGRAM_V2 AİLE-2; frontier'ın RED ettiği 2 hücreye prior-art atıfı ZORUNLU).",
            "AILE-MIKRO: likidite süpürme (swing high/low sweep) + likidasyon-proxy "
            "teyidi (PROGRAM_V2 AİLE-3; SMC-RED prior-art atıfı ZORUNLU).",
        ]
        theme = themes[hour % len(themes)]
        r = ResearcherAgent()
        result = await r.propose_hypothesis(theme)
        logger.info(
            "scheduler.researcher_pulse_done",
            extra={
                "hour_utc": hour,
                "theme_idx": hour % len(themes),
                "result_preview": (result or "")[:120],
            },
        )
    except Exception as exc:
        logger.warning("scheduler.researcher_pulse_fail", extra={"err": str(exc)[:200]})


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
                    slug="drift-alert-quick",
                    confidence="med",
                )
        except Exception as _drift_exc:
            # FIX 2026-05-26 (H1)
            logger.warning(
                "scheduler.lab_drift_detect_fail",
                extra={"err": str(_drift_exc)[:200]},
            )

        # 2. Param sweep ek hücre — her quick scan +1 cell
        try:
            import asyncio

            await asyncio.to_thread(_run_param_sweep_chunk_sync)
        except Exception as _sweep_exc:
            # FIX 2026-05-26 (H1)
            logger.warning(
                "scheduler.lab_quick_sweep_fail",
                extra={"err": str(_sweep_exc)[:200]},
            )

        logger.info("scheduler.lab_quick_scan_done")
    except Exception as exc:
        logger.warning("scheduler.lab_quick_scan_fail", extra={"err": str(exc)[:200]})


async def _job_weekly_bot_attribution() -> None:
    """Faz 12: Haftalık per-bot attribution (Analyst + Bot Monitor sentez)."""
    try:
        from price_action.agents import BotMonitorAgent

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
    """Faz 12: Ay sonu 09:00 — Curator + CEO monthly portfolio review."""
    if not _is_last_day_of_month():
        return
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
        from datetime import datetime as _dt
        from datetime import timezone as _tz
        from pathlib import Path

        from price_action.settings import get_settings as _gs
        from scripts.tf_exploration_runner import explore_tf

        s = _gs()
        # Basit rotation: gün × strateji index
        strategies = ["vsa_climax_test", "brooks_failed_breakout", "anchored_vwap_reversal"]
        idx = _dt.now(UTC).day % len(strategies)
        strategy = strategies[idx]

        # Pool paths
        pool_paths = {
            "5m": s.reports_dir.parent / "data" / "sec53_5m_pool_v11_vm20.pkl",
            "15m": s.reports_dir.parent / "data" / "sec53_15m_pool_v11.pkl",
        }
        out_dir = s.reports_dir / "tf_exploration"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{strategy}-{_dt.now(UTC).date()}.md"

        result = explore_tf(
            strategy=strategy,
            tf_list=["5m", "15m"],
            pool_paths=pool_paths,
        )
        # FIX 2026-06-22: result önceden hesaplanıp atılıyordu — out_path hiç
        # kullanılmıyordu, rapor dosyası yazılmıyordu ("atrophied output" bug'ı,
        # tf_exploration/ 2026-05-25'ten beri boştu). Runner'ın test edilmiş
        # render_markdown()'ı ile out_path'e yaz.
        from scripts.tf_exploration_runner import render_markdown

        out_path.write_text(render_markdown(result), encoding="utf-8")
        logger.info(
            "scheduler.tf_exploration_done",
            extra={
                "strategy": strategy,
                "best_tf": result.get("best_tf"),
                "out": str(out_path),
            },
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
            CEOAgent(),
            ResearcherAgent(),
            LabScientistAgent(),
            AnalystAgent(),
            RiskOfficerAgent(),
            OpsAgent(),
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
        # FIX 2026-05-26 (M7): atomic rename + lockfile pattern.
        # Önceden review_inbox (:15 her saat) ile race vardı — Pazar 05:30
        # consolidation rename ederken :15 review okuyorsa file descriptor
        # dangling olabilirdi. Lockfile ile review okuma sırasında archive
        # bekler, vice versa.
        s = _gs()
        inbox = s.memory_dir / "protocol" / "inbox.jsonl"
        if inbox.exists():
            import fcntl
            from datetime import datetime as _dt

            lock_path = s.memory_dir / "protocol" / ".inbox.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = None
            try:
                lock_file = open(lock_path, "w")
                # Exclusive lock — block if review_inbox holds it
                fcntl.flock(lock_file, fcntl.LOCK_EX)
                iso = _dt.now(UTC).isocalendar()
                archive_path = (
                    s.memory_dir / "protocol" / "archive" / f"{iso.year}-W{iso.week:02d}.jsonl"
                )
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                # Atomic rename within same filesystem
                inbox.rename(archive_path)
                # Yeni boş inbox başlat
                inbox.touch()
                logger.info(
                    "scheduler.inbox_archived",
                    extra={"archive": str(archive_path)},
                )
            finally:
                if lock_file is not None:
                    try:
                        fcntl.flock(lock_file, fcntl.LOCK_UN)
                        lock_file.close()
                    except Exception:
                        pass

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
# İç Denetim (3. savunma hattı) — Faz 2 cron job'ları
# Üretim cron'larından SONRA (05:30+) → denetçi BİTMİŞ çıktıyı okur.
# Denetçiler read-only; bulgu → reports/audit/ + findings_register.jsonl.
# ----------------------------------------------------------------------
async def _run_audit_domain(agent_cls: Any, label: str) -> None:
    """Bir domain denetçisini koş, bulguları emit et, high/critical'ı Principal'a push."""
    try:
        agent = agent_cls()
        emitted = await agent.daily_control_review()
        if emitted:
            _push_critical_safe(
                f"🔎 İç Denetim [{label}]: {len(emitted)} yeni bulgu. "
                f"reports/audit/ + memory/audit/findings_register.jsonl",
                source=f"audit_{label}",
            )
        logger.info("scheduler.audit_done", extra={"label": label, "n_findings": len(emitted)})
    except Exception as exc:
        logger.warning("scheduler.audit_fail", extra={"label": label, "err": str(exc)[:200]})


async def _job_audit_execution() -> None:
    from price_action.agents import AuditExecutionAgent

    await _run_audit_domain(AuditExecutionAgent, "execution")


async def _job_audit_risk() -> None:
    from price_action.agents import AuditRiskAgent

    await _run_audit_domain(AuditRiskAgent, "risk")


async def _job_audit_data() -> None:
    from price_action.agents import AuditDataAgent

    await _run_audit_domain(AuditDataAgent, "data")


async def _job_audit_research() -> None:
    from price_action.agents import AuditResearchAgent

    await _run_audit_domain(AuditResearchAgent, "research")


async def _job_audit_ops() -> None:
    from price_action.agents import AuditOpsAgent

    await _run_audit_domain(AuditOpsAgent, "ops")


async def _job_audit_chief_weekly() -> None:
    """Haftalık kapsama-boşluğu taraması (uncovered_process bulguları)."""
    try:
        from price_action.agents import AuditChiefAgent

        agent = AuditChiefAgent()
        emitted = [agent.emit_finding(f) for f in agent.run_coverage_gap()]
        logger.info("scheduler.audit_chief_weekly", extra={"n_gaps": len(emitted)})
    except Exception as exc:
        logger.warning("scheduler.audit_chief_weekly_fail", extra={"err": str(exc)[:200]})


async def _job_audit_chief_monthly() -> None:
    """Aylık güvence raporu + öngörü beyin-fırtınası → Principal."""
    try:
        from price_action.agents import AuditChiefAgent

        path = await AuditChiefAgent().monthly_assurance()
        _push_report_safe(path, level="INFO", caption="İç Denetim — Aylık Güvence")
    except Exception as exc:
        logger.warning("scheduler.audit_chief_monthly_fail", extra={"err": str(exc)[:200]})


async def _job_telegram_digest_flush() -> None:
    """Saatlik: throttle buffer'ındaki alarmları digest olarak boşalt.

    FIX 2026-07-08 (bildirim paketi N4, DERIN_DENETIM W5-HIGH): flush_digest()
    tasarımda "cron'dan çağrılmalı" yazıyordu ama HİÇBİR job çağırmıyordu —
    buffer'lanan her alarm süreç ömrüyle sınırlı bellekte ölüyordu. N2 drain
    fix'i ana kaybı kapatır; bu job scheduler sürecinin kendi buffer'ı için
    kemer-askı (tipine bir daha alarm gelmezse bile en geç 1 saatte teslim).
    """
    try:
        from price_action.ops.telegram_throttle import get_telegram_throttle

        n = get_telegram_throttle().flush_digest()
        if n:
            logger.info("scheduler.telegram_digest_flush", extra={"digests": n})
    except Exception as exc:
        logger.warning("scheduler.telegram_digest_flush_fail", extra={"err": str(exc)[:200]})


# ----------------------------------------------------------------------
# Kayıt
# ----------------------------------------------------------------------

JOB_TABLE: tuple[tuple[str, str, str, Any], ...] = (
    # (id, kind, expr, func)
    ("ingest_data", "cron", "0 * * * *", _job_ingest_data),  # saatlik :00
    # SNAPSHOT 2026-05-29: market_ingest → market.duckdb, :05 (ingest sonrası, decouple)
    ("market_snapshot", "cron", "5 * * * *", _job_market_snapshot),
    # FIX 2026-05-25: regime features daily refresh (was missing — caused regime_cache_stale)
    # FIX 2026-05-29 (deploy): daily (00:01) → every 4h (00:01,04:01,...). Daily refresh
    # left cache >6h stale by afternoon → regime_cache_stale HARD_REJECT (48 occurrences
    # observed in live log). 4h cadence keeps fetched_at age < 4h, under reject gate.
    (
        "regime_features_refresh",
        "cron",
        "1 */4 * * *",
        _job_regime_features_refresh,
    ),  # :01 her 4h UTC
    # FIX 2026-05-26 (H6): pending entry retry processor (her 60s)
    ("process_pending_entries", "cron", "* * * * *", _job_process_pending_entries),
    # FIX 2026-05-26 (M1): launchd log rotation (saatlik :50)
    ("rotate_launchd_logs", "cron", "50 * * * *", _job_rotate_launchd_logs),
    # FIX 2026-05-26 (M5): DMS heartbeat staleness check (her 5dk)
    ("dms_heartbeat_check", "cron", "*/5 * * * *", _job_dms_heartbeat_check),
    # FIX 2026-05-28 (depo-ayirma + freshness): kritik feed staleness watchdog.
    # Saatlik :12 (ingest :00 + snapshot bittikten sonra çalışsın). Yeni
    # alert_type'lar (freshness_*) — mevcut muted tiplerle çakışmaz.
    # NOT (cutover): bu cron daemon reload edilince AKTİF olur — Principal onayı.
    ("freshness_watchdog", "cron", "12 * * * *", _job_freshness_watchdog),
    # FIX 2026-05-26 (Faz 14.2): Promise/Reality check (saatlik :55)
    ("check_promises", "cron", "55 * * * *", _job_check_promises),
    # FIX 2026-07-08 (bildirim paketi N4): throttle buffer'ını saatlik boşalt (:58)
    ("telegram_digest_flush", "cron", "58 * * * *", _job_telegram_digest_flush),
    # FIX 2026-05-28 (Faz 14.27): stuck inbox doc detector — 6h+ ack timeout → CRIT push
    ("stuck_doc_check", "cron", "50 * * * *", _job_stuck_doc_check),
    # FIX 2026-05-28 (Faz 14.27 — B1): DataEngineer günlük health
    ("data_health_daily", "cron", "30 6 * * *", _job_data_health_daily),
    # FIX 2026-05-28 (Faz 14.27 — B2): active_state.md saatlik refresh
    ("active_state_refresh", "cron", "25 * * * *", _job_active_state_refresh),
    # FIX 2026-05-28 (Faz 14.27 C4): slippage daily + weekly
    ("slippage_daily", "cron", "30 23 * * *", _job_slippage_daily_summary),
    ("slippage_weekly", "cron", "30 5 * * sun", _job_slippage_weekly_summary),
    # FIX 2026-05-28 (Faz 14.27 C8): Bot Monitor PAUSE → Adversary stress test
    ("bot_monitor_adversary_hook", "cron", "40 * * * *", _job_bot_monitor_adversary_hook),
    # FIX 2026-05-28 (Faz 14.27 KRITIK-1): formal event bus dispatcher
    ("event_bus_dispatch", "cron", "*/15 * * * *", _job_event_bus_dispatch),
    # FIX 2026-05-26 (Faz 14.3): Adversary quiet failure audit (Pzr 22:30 UTC)
    ("quiet_failure_audit", "cron", "30 22 * * sun", _job_quiet_failure_audit),
    # FIX 2026-05-26 (Faz 14.4): Daily Truth Report (03:00 UTC = 06:00 TR)
    ("truth_report", "cron", "0 3 * * *", _job_truth_report),
    # FIX 2026-05-26 (Faz 14.6): Journal/Exchange reconciler (her 15dk :07)
    ("reconcile_journal", "cron", "7,22,37,52 * * * *", _job_reconcile_journal),
    ("hourly_token_check", "cron", "7 * * * *", _job_hourly_token_check),  # H3 :07
    ("review_inbox", "cron", "15 * * * *", _job_review_inbox),  # Faz 2.3 :15
    ("bot_health_check", "cron", "20 * * * *", _job_bot_health_check),  # Faz 6 :20
    ("health_check", "cron", "30 * * * *", _job_health_check),  # H4 :30
    ("param_sweep_chunk", "cron", "35 * * * *", _job_param_sweep_chunk),  # Faz 7 :35
    ("scan_drift_alerts", "cron", "45 * * * *", _job_scan_drift_alerts),  # Faz 3.1 :45
    # Günlük
    ("daily_research", "cron", "0 2 * * *", _job_daily_research),
    # OTONOMI-1 (2026-07-07, PROGRAM_V2 4b): researcher_5batch DURAKLATILDI —
    # 41 günde 195 abort / 0 terfi, 35 seed'lik spin-loop kanıtı (seed_abort_log).
    # Yerine feature_sweep (deterministik kanıt üretimi) + kanıt-temelli pulse
    # temaları geldi. Geri açma: satırı aç + PROGRAM_V2 aile-hedefli prompt şart.
    # ("researcher_5batch", "cron", "30 2 * * *", _job_researcher_5batch),  # Faz 12
    # OTONOMI-1: feature × forward-return sweep (deterministik, LLM YOK).
    # FDR+OOS onaylı adaylar memory/researcher/sweep_candidates.jsonl'e düşer;
    # researcher_pulse tema-0 bunları hipoteze çevirir. Günlük 01:10 UTC.
    ("feature_sweep", "cron", "10 1 * * *", _job_feature_sweep),
    # FIX 2026-07-07 (V2): funding günlük tazeleme (35 gün bayattı, job yoktu)
    ("funding_refresh", "cron", "40 2 * * *", _job_funding_refresh),
    # FIX 2026-07-02 (fabrika yeniden-açılış, token disiplini): pulse 5×→2×/gün,
    # quick_scan 12×→4×/gün. Gerekçe: researcher 7 günde 27.7M token yaktı
    # (çağrı başı ~733K input) ve çıktı 0 terfiydi; kalite kapıları düzeldi,
    # hacim değil İSABET istiyoruz. Cooldown-guard + SOP-5 + dar grid'lerle
    # birlikte bu cadence yeterli sinyal üretir.
    ("researcher_pulse", "cron", "0 6,18 * * *", _job_researcher_improvement_pulse),
    ("lab_quick_scan", "cron", "25 0,6,12,18 * * *", _job_lab_quick_scan),
    ("adversary_daily_stress", "cron", "0 4 * * *", _job_adversary_daily_stress),  # Faz 9
    ("tf_exploration_chunk", "cron", "30 4 * * *", _job_tf_exploration_chunk),  # Faz 10
    # FIX 2026-07-07 (denetim D8/D9): signal_scan doğuştan ölüydü (hedef
    # run_daily_scan hiç var olmadı, sessiz no-op); execute_orders emekli 1d
    # pipeline zombisiydi (tüketicisiz dry-run, her gece). İkisi de kayıttan
    # çıkarıldı — script'ler manuel kullanım için duruyor.
    # ("signal_scan", "cron", "5 0 * * *", _job_signal_scan),
    # ("execute_orders", "cron", "10 0 * * *", _job_execute_orders),
    ("curator_daily_correlation", "cron", "0 19 * * *", _job_curator_daily_correlation),  # Faz 8
    ("bot_daily_cards", "cron", "0 22 * * *", _job_bot_daily_cards),  # Faz 6
    ("daily_kpi", "cron", "0 23 * * *", _job_daily_kpi),
    ("daily_whatif", "cron", "30 23 * * *", _job_daily_whatif),  # Faz 2.3
    ("kill_criteria_eval", "cron", "45 23 * * *", _job_kill_criteria_eval),  # Faz 6
    # FIX 2026-05-27 (Faz 14.10): günlük tournament — sweep chunk her saat
    # büyüyor, haftalık çok seyrek. Günlük 04:00 UTC (07:00 TR) bilgilendirici.
    ("daily_lab_tournament", "cron", "0 4 * * *", _job_weekly_tournament),
    # FIX 2026-05-27 (Faz 14.15): hipotez backtest runner.
    # REVIZE 2026-05-27 02:45 UTC: 6h → 30dk. Backlog 48 hipotez, 6h'da
    # 3 koşum = 96 saat (4 gün) çok yavaş. 30dk'da 3 koşum = 144/gün
    # → tüm backlog ~8h temizlenir. Token budget: 144 × 5K = 720K LLM
    # extract, Lab daily 1.5M içinde rahatça.
    ("hypothesis_backtest_runner", "cron", "*/30 * * * *", _job_hypothesis_backtest_runner),
    # FIX 2026-05-27 (Faz 14.22): pozitif edge'li ama riskli stratejileri tespit
    # → Researcher iterate queue. Günde 1 kez 03:05 UTC (06:05 TR).
    ("find_promising_to_iterate", "cron", "5 3 * * *", _job_find_promising_to_iterate),
    # FIX 2026-05-27 (Faz 14.24): OTONOM iterate orchestrator. Queue'daki her
    # umut verici stratejiye 7 round disiplin ile iterate yap. 2 saatte 1 koşar
    # (12/gün × 2 target × 5 variant = 120 variant/gün).
    ("auto_iterate_orchestrator", "cron", "15 */2 * * *", _job_auto_iterate_orchestrator),
    # Haftalık
    ("weekly_lab_tournament", "cron", "0 3 * * sun", _job_weekly_tournament),
    ("weekly_drift", "cron", "30 3 * * sun", _job_weekly_drift),
    ("adversary_weekly_red_team", "cron", "30 4 * * sun", _job_adversary_weekly_red_team),  # Faz 9
    ("weekly_rag_refresh", "cron", "0 4 * * sun", _job_weekly_rag_refresh),
    ("weekly_token_report", "cron", "0 5 * * sun", _job_weekly_token_report),  # Faz 4.2
    ("weekly_consolidation", "cron", "30 5 * * sun", _job_weekly_consolidation),  # Faz 4.4
    ("curator_weekly_lifecycle", "cron", "30 6 * * sun", _job_curator_weekly_lifecycle),  # Faz 8
    # FIX 2026-07-07 (denetim D21): bot_daily_cards duplikasıydı (aynı fonksiyon,
    # farklı başlıkla ikinci Telegram push; Analyst sentezi hiç yazılmadı) — kapatıldı.
    # ("weekly_bot_attribution", "cron", "30 7 * * sun", _job_weekly_bot_attribution),
    ("weekly_principal_queue", "cron", "30 8 * * sun", _job_weekly_principal_queue),  # Faz 12
    # Aylık
    ("monthly_market_scout", "cron", "0 8 5 * *", _job_monthly_market_scout),  # Faz 11
    # FIX 2026-05-26: haftalık market scout (5 haftada full rotation kapsama)
    ("weekly_market_scout", "cron", "0 9 * * mon", _job_weekly_market_scout),  # Pzt 09:00 UTC
    ("monthly_review", "cron", "0 6 28-31 * *", _job_monthly_review),
    (
        "monthly_strategy_portfolio",
        "cron",
        "0 9 28-31 * *",
        _job_monthly_strategy_portfolio_review,
    ),  # Faz 12
    # İç Denetim (3. savunma hattı) — Faz 2 otonom.
    # Principal şartı (2026-06-18): günlük sweep SABAH 06:00 TR (= 03:00 UTC) penceresinde
    # koşar; bulgu owner'a route + 1-gün SLA (audit_base.SLA_DAYS). audit_ops artık daemon
    # ERROR loglarını da tarar (CT-OPS-03..07 log-pattern) — "audit körlüğü" kapatıldı.
    ("audit_execution", "cron", "0 3 * * *", _job_audit_execution),  # günlük 06:00 TR
    ("audit_risk", "cron", "5 3 * * *", _job_audit_risk),  # günlük 06:05 TR
    ("audit_data", "cron", "10 3 * * *", _job_audit_data),  # günlük 06:10 TR
    ("audit_ops", "cron", "15 3 * * *", _job_audit_ops),  # günlük 06:15 TR (log-pattern tarama)
    ("audit_research", "cron", "20 3 * * mon", _job_audit_research),  # haftalık Pzt 06:20 TR
    ("audit_chief_weekly", "cron", "30 3 * * mon", _job_audit_chief_weekly),  # Pzt 06:30 TR
    ("audit_chief_monthly", "cron", "0 4 1 * *", _job_audit_chief_monthly),  # ayın 1'i 07:00 TR
)


# FIX 2026-06-30 (Principal "israfı kes"): araştırma-otopilotu job kümesi.
# Kanıt: researcher/iterate mill 28 May→29 Haz arası 195 seed_abort kaydı üretti —
# 193'ü REJECTED_PRE_TEST, 0 backtest, 0 promote. Aynı tükenmiş kripto-15m seed'lerini
# self-throttle döngüsünde tekrar tekrar reddedip token+CPU yakıyordu (boşa churn).
# Bu yüksek-frekanslı job'lar artık SADECE PA_RESEARCH_AUTOPILOT=1 iken kayıt edilir.
# Geri açmak / forex-4H'ye yönlendirmek: env flag set + ceo_loop restart. Diğer tüm
# job'lar (reconcile/health/token/bot-monitor/DMS/truth-report/audit) ETKİLENMEZ.
_RESEARCH_AUTOPILOT_JOBS = frozenset(
    {
        "daily_research",
        "researcher_5batch",
        "researcher_pulse",
        "scan_drift_alerts",
        "lab_quick_scan",
        "hypothesis_backtest_runner",
        "find_promising_to_iterate",
        "auto_iterate_orchestrator",
        "tf_exploration_chunk",
    }
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
        max_instances=1,  # M7: explicit — overlap engelle
        coalesce=True,  # M7: birden fazla misfire → tek run
    )


def register_jobs(scheduler: Any) -> list[str]:
    """Tüm job'ları kayıt eder. Geri dönüş: kayıtlanan job id listesi.

    FIX 2026-05-28 (Faz 14.27 FINAL): Event handlers da burada wire ediliyor.
    """
    import os

    # Event bus handlers — tek seferlik (idempotent)
    _register_event_handlers_once()

    # Araştırma-otopilotu default KAPALI (boşa churn'ı kes). Açmak için
    # PA_RESEARCH_AUTOPILOT=1 + ceo_loop restart. Bkz _RESEARCH_AUTOPILOT_JOBS.
    autopilot_on = os.getenv("PA_RESEARCH_AUTOPILOT", "0") == "1"

    registered: list[str] = []
    skipped: list[str] = []
    for job_id, kind, expr, func in JOB_TABLE:
        if kind != "cron":
            continue
        if job_id in _RESEARCH_AUTOPILOT_JOBS and not autopilot_on:
            skipped.append(job_id)
            continue
        _add_cron(scheduler, expr, func, job_id)
        registered.append(job_id)
    if skipped:
        logger.info("scheduler.research_autopilot_skipped", extra={"jobs": skipped})
    logger.info("scheduler.jobs_registered", extra={"jobs": registered})
    return registered
