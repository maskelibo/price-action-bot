"""AuditOpsAgent — Ops & Control-Environment denetçisi (3. hat).

"Auditor of the 2nd line": gözetim katmanının KENDİSİNİ denetler — scheduler cron
sağlığı, notifications/mute durumu, token_budget, freshness/promise/stuck guard'ları,
ve 2. hat ajanlarının (risk_officer/adversary/bot_monitor) gerçekten koşup koşmadığı.

Archetype: SRE error-budget / alert-fatigue (SNR + mute drift) + James Reason
"Swiss-cheese" (hizalanan delikler) + IIA control self-assessment (kontrolün varlığı
≠ çalışması).

Kontrol-testleri:
  CT-OPS-01  alarm mute drift / kör-nokta (bu seansın mute bug'ı): paper için
             susturulan alarmlar canlıya geçişte / kök-neden çözüldükten sonra
             hâlâ mute mu?
  CT-OPS-02  silent cron — beklenen pencerede koşmamış job (öngörü).
"""

from __future__ import annotations

from typing import Any, ClassVar

from price_action.logging_config import logger

from .audit_base import AuditAgentBase, Finding

_OWNER = "ops_engineer"


def ct_ops_01_mute_drift(
    muted_alert_prefixes: list[str],
    muted_crit_sources: list[str],
    *,
    run_mode: str = "paper",
) -> Finding | None:
    """DETERMİNİSTİK ÇEKİRDEK — aktif mute kuralları kör-nokta yaratıyor mu?

    Herhangi bir alarm mute'luysa bu bir kör-noktadır; canlı (live) modda KRİTİK,
    paper modda dahi kök-neden çözüldüyse kaldırılmalı. Boş mute listeleri = temiz
    (bu seansta unmute edildi).
    """
    muted = [m for m in (muted_alert_prefixes or []) if m] + [
        m for m in (muted_crit_sources or []) if m
    ]
    if not muted:
        return None
    sev = "critical" if str(run_mode).lower() == "live" else "med"
    return Finding(
        control_id="CT-OPS-01",
        severity=sev,
        owner=_OWNER,
        title="alarm mute kör-noktası",
        condition=f"Aktif mute kuralları ({run_mode} mod): {', '.join(muted)}. "
        "Bu alarmlar bastırılmış → gerçek olay sessiz kalabilir.",
        criteria="Mute geçici bir yara bandıdır; kök-neden çözülünce kaldırılmalı. "
        "Canlı modda alarm bastırma yasak.",
        cause="Paper/araştırma modu false-positive'leri için konulan mute kalıcı "
        "drift'e döndü; kaldırma unutuldu.",
        effect="Gerçek bir daemon çöküşü / DD breach / stuck doc sessizce yutulur "
        "(Swiss-cheese: izleme deliği hizalanır).",
        recommendation="Kök-neden çözüldüyse mute listelerini boşalt; canlı geçişte "
        "tüm mute'ları kaldır; mute'a TTL/expiry ekle.",
        evidence={"muted": ", ".join(muted), "run_mode": run_mode},
        due_days=5,
    )


def ct_ops_02_silent_cron(
    job_ages_hours: dict[str, float],
    expected_max_age_hours: dict[str, float],
) -> Finding | None:
    """DETERMİNİSTİK ÇEKİRDEK (öngörü) — bir cron job beklenen penceresinde koşmuş mu?

    job_ages_hours: {job_name: son_koşmadan_bu_yana_saat}.
    expected_max_age_hours: {job_name: izin_verilen_max_saat}.
    """
    stale = []
    for job, max_age in expected_max_age_hours.items():
        age = job_ages_hours.get(job)
        if age is None:
            stale.append(f"{job}: hiç koşmamış")
        elif age > max_age:
            stale.append(f"{job}: {age:.1f}h (eşik {max_age:.0f}h)")
    if not stale:
        return None
    return Finding(
        control_id="CT-OPS-02",
        severity="high",
        owner=_OWNER,
        title="sessiz cron — beklenen pencerede koşmamış job",
        condition="Şu job'lar beklenen aralıkta çalışmamış: " + "; ".join(stale),
        criteria="Her cron job beklenen cadence'inde başarılı koşu izi bırakmalı.",
        cause="launchd/scheduler job düşmüş, exception ile sessiz fail, veya göç "
        "kalıntısı (Windows→Mac taşınmamış cron).",
        effect="İzleme/ingest/denetim sessizce durur — kör nokta büyür.",
        recommendation="job'u yeniden etkinleştir; fail-loud + heartbeat ekle.",
        evidence={"stale_jobs": "; ".join(stale)},
        due_days=3,
    )


class AuditOpsAgent(AuditAgentBase):
    name: ClassVar[str] = "audit_ops"
    domain: ClassVar[str] = "ops"

    def run_ct_ops_01(self) -> Finding | None:
        """Canlı mute durumunu kod'dan oku (telegram_throttle + notifications)."""
        try:
            from price_action.ops.telegram_throttle import TelegramThrottle
            from price_action.orchestrator.notifications import _MUTED_CRIT_SOURCES
            from price_action.settings import get_settings

            run_mode = str(getattr(get_settings(), "pa_run_mode", "paper"))
            return ct_ops_01_mute_drift(
                list(TelegramThrottle._MUTED_ALERT_PREFIXES),
                list(_MUTED_CRIT_SOURCES),
                run_mode=run_mode,
            )
        except Exception as exc:
            logger.warning("audit_ops.ct_ops_01_fail", extra={"err": str(exc)[:160]})
            return None

    async def daily_control_review(self) -> list[Any]:
        emitted = []
        for runner in (self.run_ct_ops_01,):
            try:
                f = runner()
                if f is not None:
                    emitted.append(self.emit_finding(f))
            except Exception as exc:
                logger.warning(
                    "audit_ops.ct_fail", extra={"runner": runner.__name__, "err": str(exc)[:160]}
                )
        return emitted
