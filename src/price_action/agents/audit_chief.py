"""AuditChiefAgent — Baş Denetçi (Chief Audit Officer, 3. hat).

Bağımsız iç denetimin başı. Saha bulgusu ÜRETMEZ (objektiflik — plan/onay/sentez
yapar); domain denetçileri saha denetimini yapar. Görevleri:
  - Denetim evreni (audit_universe.yaml) sahibi + risk-bazlı plan.
  - KAPSAMA-BOŞLUĞU haritası: her süreç 1./2./3. hat kontrolüne sahip mi
    ("açıkta kalan var mı?" — kullanıcı şartı #1).
  - Findings register sentezi: açık/overdue/recurrence → sistemik açık.
  - Aylık güvence raporu + ÖNGÖRÜ beyin-fırtınası (kullanıcı şartı #2) → Principal.

Archetype: IIA Three Lines Model + COSO Internal Control + risk-bazlı audit
(audit_risk = inherent × control × detection).
"""

from __future__ import annotations

from datetime import UTC
from typing import Any, ClassVar

from price_action.logging_config import logger

from .audit_base import AuditAgentBase, Finding

_OWNER = "ceo"  # kapsama açığı sahibi (süreç sahipliği atanana dek)


def coverage_gap(universe_processes: dict[str, dict[str, Any]]) -> list[Finding]:
    """DETERMİNİSTİK ÇEKİRDEK — audit_universe.yaml'da her sürecin 1./2./3. hat
    kontrol kapsamasını denetle. Eksik olan = uncovered_process bulgusu.

    Beklenen her process şeması:
      owner_agent (1. hat), auditor (3. hat), controls (kontrol-test listesi).
    """
    findings: list[Finding] = []
    for proc, spec in (universe_processes or {}).items():
        missing = []
        if not spec.get("owner_agent"):
            missing.append("1. hat sahibi (owner_agent) YOK")
        if not spec.get("auditor"):
            missing.append("3. hat denetçisi (auditor) YOK")
        if not (spec.get("controls") or []):
            missing.append("kontrol-testi (controls) YOK")
        if not missing:
            continue
        findings.append(
            Finding(
                control_id="CT-CHF-01",
                severity="high" if "3. hat denetçisi (auditor) YOK" in missing else "med",
                owner=spec.get("owner_agent") or _OWNER,
                title=f"kapsama açığı — {proc}",
                condition=f"Süreç '{proc}' eksik kontrol kapsamı: " + "; ".join(missing),
                criteria="Her süreç 1. hat (sahip) + 2. hat (izleme) + 3. hat (denetim) "
                "kapsamasına sahip olmalı (three-lines tam kapsama).",
                cause="audit_universe.yaml eksik/güncellenmemiş veya süreç hiç atanmamış.",
                effect="Denetlenmeyen süreçte kontrol açığı sessizce büyür (kör nokta).",
                recommendation=f"'{proc}' için sahip+denetçi+kontrol-testi ata.",
                evidence={"process": proc, "missing": ", ".join(missing)},
                due_days=14,
            )
        )
    return findings


class AuditChiefAgent(AuditAgentBase):
    name: ClassVar[str] = "audit_chief"
    domain: ClassVar[str] = "chf"

    def _load_universe(self) -> dict[str, dict[str, Any]]:
        try:
            import yaml

            p = self._repo_root() / "configs" / "audit_universe.yaml"
            if not p.exists():
                return {}
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            return data.get("processes", {}) or {}
        except Exception as exc:
            logger.warning("audit_chief.universe_load_fail", extra={"err": str(exc)[:160]})
            return {}

    def run_coverage_gap(self) -> list[Finding]:
        return coverage_gap(self._load_universe())

    def register_summary(self) -> dict[str, Any]:
        """Açık/overdue/recurrence özeti (deterministik — güvence raporu girdisi)."""
        from datetime import datetime

        now = datetime.now(UTC)
        latest = self._latest_state()
        open_f = [r for r in latest.values() if r.get("status") in ("OPEN", "REOPENED")]
        overdue = []
        for r in open_f:
            try:
                due = datetime.fromisoformat(str(r.get("due_at", "")).replace("Z", "+00:00"))
                if now > due:
                    overdue.append(r)
            except Exception:
                pass
        recurring = [r for r in latest.values() if int(r.get("recurrence_count", 0) or 0) > 0]
        by_sev: dict[str, int] = {}
        for r in open_f:
            s = r.get("severity", "?")
            by_sev[s] = by_sev.get(s, 0) + 1
        return {
            "total": len(latest),
            "open": len(open_f),
            "overdue": len(overdue),
            "recurring": len(recurring),
            "by_severity": by_sev,
            "overdue_ids": [r.get("finding_id") for r in overdue],
            "recurring_ids": [r.get("finding_id") for r in recurring],
        }

    async def monthly_assurance(self) -> Any:
        """Aylık güvence raporu + kapsama açığı bulgularını emit + sistemik özet."""
        emitted = []
        for f in self.run_coverage_gap():
            try:
                emitted.append(self.emit_finding(f))
            except Exception as exc:
                logger.warning("audit_chief.coverage_emit_fail", extra={"err": str(exc)[:160]})

        summ = self.register_summary()
        body = (
            "# İç Denetim — Aylık Güvence Raporu\n\n"
            f"## Findings register durumu\n"
            f"- Toplam bulgu: {summ['total']}\n"
            f"- Açık (OPEN/REOPENED): {summ['open']}\n"
            f"- Süresi geçmiş (overdue): {summ['overdue']} → {summ['overdue_ids']}\n"
            f"- Tekrar eden (sistemik): {summ['recurring']} → {summ['recurring_ids']}\n"
            f"- Severity dağılımı (açık): {summ['by_severity']}\n\n"
            f"## Kapsama açığı taraması\n"
            f"- Bu koşuda {len(emitted)} uncovered_process bulgusu açıldı.\n\n"
            "## Öngörü / beyin-fırtınası (ileriye dönük)\n"
            "Tekrar eden bulgular sistemik kontrol-tasarım açığıdır; domain "
            "denetçileri 'henüz yaşanmamış ama yaşanabilecek' arızaları (örn. DuckDB "
            "bozulması, yedek başarısızlığı) öngörü-taramasıyla aramalı.\n"
        )
        path = self.write_protocol_doc(
            doc_type="audit_assurance",
            body=body,
            slug="monthly-assurance",
            target_dir=self._audit_reports_dir(),
            status="PROPOSED",
            confidence="high",
            requested_review_from=["human_principal", "ceo"],
            tags=["audit", "assurance", "principal_escalation"],
        )
        return path
