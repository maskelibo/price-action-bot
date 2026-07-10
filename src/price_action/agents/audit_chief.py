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

from .audit_base import SKIP, AuditAgentBase, Finding

_OWNER = "ceo"  # kapsama açığı sahibi (süreç sahipliği atanana dek)

# ---------------------------------------------------------------------------
# T5-01 (2026-07-10) — ÇALIŞABILIR ajan kümesi (CT-CHF-02 phantom-owner girdisi)
#
# src/price_action/agents/*.py içindeki GERÇEK Agent sınıflarının
# ``name: ClassVar[str]`` değerleri. Persona-only ajanlar (.claude/agents/*.md
# dosyası var ama Python sınıfı YOK — örn. execution_chief, portfolio_manager,
# signal_chief) bu kümede DEĞİLDİR: onlara atanan bulgu remediation dead-end
# olur (kimse koşmaz, SLA sessizce dolar — CT-OPS-03/05/06'da yaşandı).
#
# Açık liste (dinamik import yerine) bilinçli tercih: denetim koşusu importable
# olmayan tek bir ajan modülünde patlamasın. Kaynak-pin testi
# tests/audit/test_ct_chf_02_phantom_owner.py — küme kod tabanından regex ile
# türetilip bu frozenset ile karşılaştırılır; drift = kırmızı test.
# ---------------------------------------------------------------------------
RUNNABLE_AGENT_NAMES: frozenset[str] = frozenset(
    {
        "adversary_engineer",
        "analyst",
        "audit_chief",
        "audit_data",
        "audit_execution",
        "audit_ops",
        "audit_research",
        "audit_risk",
        "bot_monitor",
        "ceo",
        "data_engineer",
        "lab_scientist",
        "market_scout",
        "ops_engineer",
        "researcher",
        "risk_officer",
        "strategy_curator",
    }
)


def phantom_owner(
    universe_processes: dict[str, dict[str, Any]],
    runnable_agents: frozenset[str] = RUNNABLE_AGENT_NAMES,
) -> Finding | None:
    """DETERMİNİSTİK ÇEKİRDEK (CT-CHF-02) — phantom-owner kontrolü (T5-01).

    audit_universe.yaml'daki her ``owner_agent`` ÇALIŞABILIR ajan kümesinde mi?
    Değilse o sürece açılan bulgular remediation dead-end'dir (owner'ı koşacak
    Python sınıfı yok → kimse düzeltmez, SLA sessizce dolar).

    Düşük-gürültü tasarımı: süreç başına değil, TEK toplu bulgu (phantom owner →
    süreç listesi haritasıyla). ``owner_agent`` hiç yoksa saymaz — o zaten
    CT-CHF-01'in (kapsama açığı) işi; çift bulgu üretmeyelim.
    """
    phantoms: dict[str, list[str]] = {}
    for proc, spec in (universe_processes or {}).items():
        owner = str((spec or {}).get("owner_agent") or "").strip()
        if not owner:
            continue  # owner YOK → CT-CHF-01 kapsama açığı olarak raporlar
        if owner not in runnable_agents:
            phantoms.setdefault(owner, []).append(proc)
    if not phantoms:
        return None
    detail = "; ".join(
        f"{owner} → [{', '.join(sorted(procs))}]" for owner, procs in sorted(phantoms.items())
    )
    n_procs = sum(len(v) for v in phantoms.values())
    return Finding(
        control_id="CT-CHF-02",
        severity="med",
        owner="ops_engineer",
        title=f"phantom owner — {len(phantoms)} çalıştırılamaz owner_agent ({n_procs} süreç)",
        condition=(
            "audit_universe.yaml'da çalışabilir Python ajanı OLMAYAN "
            f"owner_agent atamaları var: {detail}"
        ),
        criteria=(
            "Her sürecin owner_agent'ı src/price_action/agents/ altındaki gerçek "
            "Agent sınıflarından biri olmalı (RUNNABLE_AGENT_NAMES); aksi hâlde o "
            "sürece açılan bulgu remediation dead-end olur."
        ),
        cause=(
            "Persona-only ajan (.claude/agents/*.md var, Python sınıfı yok) "
            "owner olarak atanmış veya ajan adı yanlış yazılmış."
        ),
        effect=(
            "Phantom owner'a route edilen bulgular sahipsiz kalır; SLA sessizce "
            "dolar, kontrol açığı görünmez büyür (CT-OPS-03/05/06 vakası)."
        ),
        recommendation=(
            "audit_universe.yaml'daki phantom owner'ları çalışabilir bir ajanla "
            "değiştir (örn. ops_engineer) veya eksik ajan sınıfını implemente et."
        ),
        evidence={
            "phantom_owners": detail,
            "n_phantom_owners": len(phantoms),
            "n_affected_processes": n_procs,
        },
    )


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
        # NOT: boş `controls` tek başına bulgu DEĞİL (Faz 3) — bu bir backlog
        # metriğidir (dashboard 'controls coverage %'). Sadece sahip/denetçi
        # eksikliği gerçek kapsama açığıdır (uncovered_process).
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

    # ------------------------------------------------------------------
    # T5-01 — CT-CHF-02 phantom-owner (controls() kaydı → run_controls
    # yaşam döngüsü: emit + dedup + auto-verify)
    # ------------------------------------------------------------------
    def run_ct_chf_02_phantom_owner(self) -> Any:
        """CT-CHF-02 runner — universe okunamıyorsa SKIP (yanlışlıkla kapatma)."""
        procs = self._load_universe()
        if not procs:
            return SKIP  # dosya yok/parse hatası/boş — bilgi yok, dokunma
        return phantom_owner(procs)

    def controls(self) -> dict[str, Any]:
        return {"CT-CHF-02": self.run_ct_chf_02_phantom_owner}

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
            except Exception as _du_err:
                # log-only: due_at parse fail → bulgu overdue listesinden sessizce
                # düşerdi (SLA ihlali görünmez olurdu) — artık görünür.
                logger.warning(
                    "audit_chief.due_at_parse_fail",
                    extra={"finding": str(r.get("finding_id", "?")), "err": str(_du_err)[:80]},
                )
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

    # ------------------------------------------------------------------
    # Faz 3 — controls coverage metriği + dashboard + tam-koşu orkestrasyon
    # ------------------------------------------------------------------
    def controls_coverage(self) -> dict[str, Any]:
        """Kaç sürecin kontrol-testi var (backlog metriği — boş controls bulgu değil)."""
        procs = self._load_universe()
        total = len(procs)
        with_controls = sum(1 for p in procs.values() if (p.get("controls") or []))
        by_domain: dict[str, dict[str, int]] = {}
        for p in procs.values():
            d = p.get("domain", "?")
            slot = by_domain.setdefault(d, {"total": 0, "covered": 0})
            slot["total"] += 1
            if p.get("controls") or []:
                slot["covered"] += 1
        return {
            "total": total,
            "with_controls": with_controls,
            "pct": round(100.0 * with_controls / total, 1) if total else 0.0,
            "by_domain": by_domain,
        }

    def build_dashboard(self) -> Any:
        """reports/audit/dashboard.md — açık/kapalı/overdue/recurrence + kapsama + controls %."""
        summ = self.register_summary()
        cov = self.controls_coverage()
        gaps = self.run_coverage_gap()  # gerçek kapsama açığı (sahip/denetçi yok)
        latest = self._latest_state()
        # severity'ye göre açık bulgular
        open_rows = [r for r in latest.values() if r.get("status") in ("OPEN", "REOPENED")]
        open_rows.sort(key=lambda r: r.get("severity", ""), reverse=True)

        dom_lines = "\n".join(
            f"  - {d}: {s['covered']}/{s['total']} süreç kontrol-testli"
            for d, s in sorted(cov["by_domain"].items())
        )
        open_lines = (
            "\n".join(
                f"  - [{r.get('severity', '?').upper()}] {r.get('finding_id')} "
                f"({r.get('control_id')}, owner={r.get('owner')}, status={r.get('status')})"
                for r in open_rows[:20]
            )
            or "  - (açık bulgu yok)"
        )

        body = (
            "# İç Denetim — Dashboard\n\n"
            "## Findings register\n"
            f"- Toplam: {summ['total']} | Açık: {summ['open']} | "
            f"Overdue: {summ['overdue']} | Tekrar eden (sistemik): {summ['recurring']}\n"
            f"- Severity (açık): {summ['by_severity']}\n\n"
            "## Açık bulgular\n"
            f"{open_lines}\n\n"
            "## Üç-hat kapsama\n"
            f"- Gerçek kapsama açığı (sahip/denetçi yok): {len(gaps)}\n"
            f"- Kontrol-testi kapsamı (backlog): {cov['with_controls']}/{cov['total']} "
            f"süreç (%{cov['pct']})\n"
            f"{dom_lines}\n\n"
            "## Notlar\n"
            "- 'Kontrol-testi kapsamı' boş-controls süreçleri backlog'dur (Faz 3'te "
            "kontrol-testi kazanacak) — bulgu değil.\n"
            "- Tekrar eden (recurrence>0) bulgular sistemik kontrol-tasarım açığıdır.\n"
        )
        path = self.write_protocol_doc(
            doc_type="audit_report",
            body=body,
            slug="dashboard",
            target_dir=self._audit_reports_dir(),
            status="FINAL",
            confidence="high",
            requested_review_from=[],
            tags=["audit", "dashboard"],
        )
        return path

    async def run_full_audit(self) -> dict[str, Any]:
        """On-demand TAM denetim turu: 5 domain denetçisi + kapsama + dashboard.

        Her domain denetçisini koşturup bulguları emit eder, sonra dashboard'u günceller.
        Döner: {domain: emitted_count, ...} + dashboard path.
        """
        from price_action.agents import (
            AuditDataAgent,
            AuditExecutionAgent,
            AuditOpsAgent,
            AuditResearchAgent,
            AuditRiskAgent,
        )

        results: dict[str, Any] = {}
        domain_agents = [
            ("execution", AuditExecutionAgent),
            ("risk", AuditRiskAgent),
            ("data", AuditDataAgent),
            ("research", AuditResearchAgent),
            ("ops", AuditOpsAgent),
        ]
        for label, cls in domain_agents:
            try:
                emitted = await cls().daily_control_review()
                results[label] = len(emitted)
            except Exception as exc:
                logger.warning(
                    "audit_chief.full_audit_domain_fail",
                    extra={"label": label, "err": str(exc)[:160]},
                )
                results[label] = -1
        # kapsama açığı bulguları (sahip/denetçi yok)
        try:
            results["coverage_gaps"] = len([self.emit_finding(f) for f in self.run_coverage_gap()])
        except Exception:
            results["coverage_gaps"] = 0
        # T5-01: chief'in kendi kontrol-testleri (CT-CHF-02 phantom-owner) —
        # run_controls yaşam döngüsüyle (emit + dedup + auto-verify).
        try:
            own = await self.run_controls()
            results["chief_controls"] = {k: len(v) for k, v in own.items()}
        except Exception as exc:
            logger.warning("audit_chief.own_controls_fail", extra={"err": str(exc)[:160]})
            results["chief_controls"] = {}
        results["dashboard"] = str(self.build_dashboard())
        return results
