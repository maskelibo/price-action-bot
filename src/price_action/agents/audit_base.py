"""AuditAgentBase — 3. savunma hattı (bağımsız iç denetim) ortak tabanı.

Bu sınıf TÜM denetçi-agentların (audit_chief/execution/risk/data/research/ops)
ortak temelidir. Mevcut ``LLMAgentBase`` altyapısını YENİDEN KULLANIR
(``write_protocol_doc`` + ``_inbox_publish`` + DRY_RUN), yeni altyapı icat etmez.

Bağımsızlık (independence by construction):
  - allowed_tools READ-ONLY (Write/Edit yok). Trading config yazamaz, deploy
    edemez, emir veremez, başka ajan kod/doc'unu değiştiremez.
  - Yalnız ``reports/audit/`` (bulgu doc'ları) + ``memory/audit/`` (findings
    register) yazar — bu, write_protocol_doc'un target_dir parametresiyle
    sağlanır.
  - audit_* doc'ları ``principal_escalation`` tag'i taşır → CEO bastıramaz.

Bulgu yaşam döngüsü:
  DETECT (CT-XXX deterministik test) → EMIT (emit_finding) → register OPEN
  → owner ack/remediate → VERIFY (verify_remediation) → CLOSED / REOPENED
  (recurrence_count++ + severity escalate).

Tasarım kuralı: her CT-XXX kontrol-testinin DETERMİNİSTİK ÇEKİRDEĞİ saf
fonksiyondur (LLM'siz, girdi→bulgu|None) → ``PA_LLM_DRY_RUN=true`` ile bile
test edilebilir. LLM yalnız bulgu gerekçesini (Condition/Cause/Effect) zenginleştirir.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

from price_action.logging_config import logger

from .base import LLMAgentBase

# Severity sıralaması (escalation için)
_SEVERITY_ORDER = ("low", "med", "high", "critical")

# SLA politikası (kullanıcı şartı 2026-06-02): açık bulgular ilgili 1. hat tarafından
# 1 GÜN içinde remediate + closure raporu ile kapatılmalı; geçerse Principal'a escalate.
# Tek kaynak — emit_finding bunu uygular (per-control due_days hint'i override eder).
SLA_DAYS = 1

# Kontrol-testi "denetlenemedi" sentinel'i (örn borsaya ulaşılamadı).
# None = TEMİZ (problem yok → auto-verify CLOSE), SKIP = bilgi yok (dokunma).
# Bu ayrım kritik: skip'i "temiz" sanıp açık bulguyu yanlışlıkla kapatmayalım.
SKIP = object()


def severity_escalate(sev: str) -> str:
    """Bir kademe yukarı (recurrence için). critical zaten tavan."""
    sev = (sev or "low").lower()
    try:
        i = _SEVERITY_ORDER.index(sev)
    except ValueError:
        return "med"
    return _SEVERITY_ORDER[min(i + 1, len(_SEVERITY_ORDER) - 1)]


class Finding:
    """Bir kontrol-testinin (CT-XXX) ürettiği bulgu — saf veri taşıyıcı.

    Deterministik çekirdek bunu döndürür; ``emit_finding`` bunu doc+register'a
    çevirir. ``None`` yerine "bulgu yok" anlamı için çağıran ``if finding:``
    kontrolü yapar.
    """

    def __init__(
        self,
        *,
        control_id: str,
        severity: str,
        owner: str,
        title: str,
        condition: str,
        criteria: str,
        cause: str,
        effect: str,
        recommendation: str,
        evidence: dict[str, Any] | None = None,
        due_days: int = 1,
    ) -> None:
        self.control_id = control_id
        self.severity = severity.lower()
        self.owner = owner
        self.title = title
        self.condition = condition  # COSO: gözlemlenen durum
        self.criteria = criteria  # olması gereken / standart
        self.cause = cause  # kök neden
        self.effect = effect  # risk/etki
        self.recommendation = recommendation
        self.evidence = evidence or {}
        self.due_days = due_days

    def __repr__(self) -> str:  # pragma: no cover (debug)
        return f"Finding({self.control_id}, {self.severity}, {self.title!r})"


class AuditAgentBase(LLMAgentBase):
    """3. hat denetçi tabanı. READ-ONLY + findings register + finding lifecycle."""

    # NOT (C17): agents/audit_base.md YOK — bu base doğrudan instantiate edilmemeli
    # (alt sınıf name override eder); edilirse rules_missing warning + boş persona ile koşar.
    name: ClassVar[str] = "audit_base"
    default_model: ClassVar[str] = ""  # boşsa settings.claude_model_default (Opus)
    # READ-ONLY tool seti — independence by construction. write_report YOK;
    # bulgu yazımı write_protocol_doc(target_dir=reports/audit) ile kısıtlı.
    allowed_tools: ClassVar[tuple[str, ...]] = ("read_file", "search_files", "list_files")

    # Hangi domain'i denetler (register finding_id öneki + universe filtresi).
    domain: ClassVar[str] = "base"

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        if not self.model:
            self.model = self.settings.claude_model_default

    # ------------------------------------------------------------------
    # Yollar
    # ------------------------------------------------------------------
    def _audit_reports_dir(self) -> Path:
        p = self.settings.reports_dir / "audit"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _register_path(self) -> Path:
        p = self.settings.memory_dir / "audit" / "findings_register.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _repo_root(self) -> Path:
        return self.settings.reports_dir.parent

    # ------------------------------------------------------------------
    # Findings register (append-only; son satır = güncel durum)
    # ------------------------------------------------------------------
    def _register_rows(self) -> list[dict[str, Any]]:
        path = self._register_path()
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def _latest_state(self) -> dict[str, dict[str, Any]]:
        """finding_id → en son durum (append-only'de son satır kazanır)."""
        latest: dict[str, dict[str, Any]] = {}
        for row in self._register_rows():
            fid = row.get("finding_id")
            if fid:
                latest[fid] = row
        return latest

    def _append_register(self, row: dict[str, Any]) -> None:
        with self._register_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _next_finding_id(self, control_id: str, ts: datetime) -> str:
        """AF-<DOMAIN>-<YYYYMMDD>-NNN — gün+control bazında artan sıra."""
        dom = control_id.split("-")[1] if "-" in control_id else self.domain.upper()
        day = ts.strftime("%Y%m%d")
        prefix = f"AF-{dom}-{day}-"
        existing = [
            r.get("finding_id", "")
            for r in self._register_rows()
            if str(r.get("finding_id", "")).startswith(prefix)
        ]
        seq = len({e for e in existing}) + 1
        return f"{prefix}{seq:03d}"

    def _recurrence_for(self, control_id: str) -> int:
        """Bu control_id için daha önce CLOSED olmuş bulgu sayısı (sistemik sinyal)."""
        n = 0
        for _fid, row in self._latest_state().items():
            if row.get("control_id") == control_id and row.get("status") == "CLOSED":
                n += 1
        return n

    # ------------------------------------------------------------------
    # Bulgu gövdesi (COSO formatı)
    # ------------------------------------------------------------------
    @staticmethod
    def _render_finding_body(f: Finding, finding_id: str, recurrence: int) -> str:
        ev_lines = "\n".join(f"- **{k}:** {v}" for k, v in f.evidence.items()) or "- (yok)"
        rec_note = (
            f"\n\n> ⚠️ **TEKRAR EDEN BULGU** (recurrence={recurrence}) — bu kontrol-açığı "
            f"daha önce kapatılmıştı ve YİNE açıldı. Sistemik kontrol-tasarım açığı "
            f"olarak audit_chief beyin-fırtınasına alınmalı."
            if recurrence > 0
            else ""
        )
        return (
            f"# Audit Finding {finding_id} — {f.title}\n\n"
            f"- **Control:** {f.control_id}\n"
            f"- **Severity:** {f.severity.upper()}\n"
            f"- **Owner (1. hat):** {f.owner}\n"
            f"{rec_note}\n\n"
            f"## Condition (gözlemlenen)\n{f.condition}\n\n"
            f"## Criteria (olması gereken)\n{f.criteria}\n\n"
            f"## Cause (kök neden)\n{f.cause}\n\n"
            f"## Effect (risk / etki)\n{f.effect}\n\n"
            f"## Evidence\n{ev_lines}\n\n"
            f"## Recommendation\n{f.recommendation}\n\n"
            f"## What would close this finding\n"
            f"Owner remediation + denetçinin {f.control_id} kontrol-testini YENİDEN "
            f"koşup PASS alması (verify_remediation).\n"
        )

    # ------------------------------------------------------------------
    # EMIT — bulgu doc + register OPEN + owner inbox
    # ------------------------------------------------------------------
    def emit_finding(self, f: Finding) -> Path:
        """Finding → audit_finding doc (reports/audit/) + register OPEN + inbox.

        Recurrence varsa severity bir kademe yükseltilir.
        """
        ts = datetime.now(UTC)
        recurrence = self._recurrence_for(f.control_id)
        if recurrence > 0:
            f.severity = severity_escalate(f.severity)
        finding_id = self._next_finding_id(f.control_id, ts)
        body = self._render_finding_body(f, finding_id, recurrence)

        tags = ["audit", f.control_id, f.severity]
        if f.severity in ("high", "critical"):
            tags.append("principal_escalation")

        path = self.write_protocol_doc(
            doc_type="audit_finding",
            body=body,
            slug=finding_id,
            target_dir=self._audit_reports_dir(),
            status="PROPOSED",
            confidence="high",
            requested_review_from=[f.owner, "audit_chief"],
            tags=tags,
        )

        # SLA politikası: per-control due_days hint'i değil, tek-kaynak SLA_DAYS.
        due_at = (ts + timedelta(days=SLA_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._append_register(
            {
                "finding_id": finding_id,
                "control_id": f.control_id,
                "severity": f.severity,
                "owner": f.owner,
                "auditor": self.name,
                "title": f.title,
                "status": "OPEN",
                "opened_at": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "due_at": due_at,
                "doc_path": str(path.relative_to(self._repo_root())),
                "remediation_doc": None,
                "verified_at": None,
                "escalated_at": None,
                "recurrence_count": recurrence,
            }
        )
        logger.info(
            "audit.finding_emitted",
            extra={
                "finding_id": finding_id,
                "control_id": f.control_id,
                "severity": f.severity,
                "owner": f.owner,
            },
        )
        return path

    # ------------------------------------------------------------------
    # VERIFY — remediation doğrula → CLOSED veya REOPENED
    # ------------------------------------------------------------------
    def verify_remediation(
        self, finding_id: str, passed: bool, remediation_doc: str | None = None
    ) -> Path:
        """Kontrol-testi yeniden koşulduktan sonra çağrılır.

        passed=True  → audit_followup(VERIFIED) + register CLOSED.
        passed=False → register REOPENED + recurrence_count++ + severity escalate.
        """
        ts = datetime.now(UTC)
        state = self._latest_state().get(finding_id)
        if state is None:
            raise ValueError(f"finding_id bulunamadı: {finding_id}")

        if passed:
            new_status = "CLOSED"
            verdict = "VERIFIED — kontrol-testi yeniden koşuldu, PASS."
        else:
            new_status = "REOPENED"
            verdict = "REOPENED — remediation kontrol-testini geçemedi."

        body = (
            f"# Audit Follow-up {finding_id} — {new_status}\n\n"
            f"- **Control:** {state.get('control_id')}\n"
            f"- **Sonuç:** {verdict}\n"
            f"- **Remediation doc:** {remediation_doc or '(yok)'}\n"
        )
        path = self.write_protocol_doc(
            doc_type="audit_followup",
            body=body,
            slug=f"{finding_id}-{new_status.lower()}",
            target_dir=self._audit_reports_dir(),
            status="REVIEWED" if passed else "PROPOSED",
            confidence="high",
            requested_review_from=[state.get("owner", "ceo"), "audit_chief"],
            tags=["audit", "followup", new_status.lower()],
        )

        new_row = dict(state)
        new_row["status"] = new_status
        new_row["remediation_doc"] = remediation_doc
        if passed:
            new_row["verified_at"] = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            new_row["recurrence_count"] = int(state.get("recurrence_count", 0)) + 1
            new_row["severity"] = severity_escalate(state.get("severity", "med"))
        self._append_register(new_row)
        logger.info(
            "audit.remediation_verified", extra={"finding_id": finding_id, "status": new_status}
        )
        return path

    # ------------------------------------------------------------------
    # REMEDIATION — owner (1. hat) "kapatıldı raporu" (closure report)
    # ------------------------------------------------------------------
    def record_remediation(
        self, finding_id: str, *, remediation_doc: str, by: str
    ) -> dict[str, Any]:
        """Owner 1. hat ajanı düzeltmeyi yapınca "kapatıldı raporu" kaydeder.

        Bu bulguyu KAPATMAZ — yalnız ``REMEDIATION_FILED``'a taşır. Kapatma yetkisi
        denetçide kalır: sonraki ``run_controls``'ta CT-XXX yeniden koşulur →
        PASS ise CLOSED (owner raporu referanslı), FAIL ise REOPENED (owner
        "düzelttim" dedi ama kontrol hâlâ kırık → severity escalate + recurrence++).
        Bağımsızlık: owner kendi işini "kapandı" ilan EDEMEZ, denetçi doğrular.
        """
        state = self._latest_state().get(finding_id)
        if state is None:
            raise ValueError(f"finding_id bulunamadı: {finding_id}")
        new_row = dict(state)
        new_row["status"] = "REMEDIATION_FILED"
        new_row["remediation_doc"] = remediation_doc
        new_row["remediated_by"] = by
        new_row["remediated_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._append_register(new_row)
        logger.info("audit.remediation_filed", extra={"finding_id": finding_id, "by": by})
        return new_row

    # ------------------------------------------------------------------
    # OVERDUE — 1-gün SLA aşımı → Principal'a escalate (idempotent)
    # ------------------------------------------------------------------
    def escalate_overdue(self) -> list[str]:
        """SLA (``SLA_DAYS``) aşan, henüz kapanmamış bulguları Principal'a yükselt.

        OPEN/REOPENED/REMEDIATION_FILED + due_at geçmiş + henüz escalate edilmemiş.
        Idempotent: ``escalated_at`` set'liyse tekrar yükseltmez (alarm-spam yok).
        """
        now = datetime.now(UTC)
        escalated: list[str] = []
        for fid, row in self._latest_state().items():
            if row.get("status") not in self._OPEN_STATES:
                continue
            if row.get("escalated_at"):
                continue
            due = row.get("due_at")
            if not due:
                continue
            try:
                due_dt = datetime.strptime(due, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            except ValueError:
                continue
            if now <= due_dt:
                continue
            overdue_h = (now - due_dt).total_seconds() / 3600.0
            body = (
                f"# Audit SLA İHLALİ {fid} — {row.get('title')}\n\n"
                f"- **Control:** {row.get('control_id')}\n"
                f"- **Severity:** {str(row.get('severity', '')).upper()}\n"
                f"- **Owner (1. hat):** {row.get('owner')}\n"
                f"- **Açıldı:** {row.get('opened_at')} · **Vade:** {due} "
                f"(**{overdue_h:.0f}s gecikme**)\n"
                f"- **Durum:** {row.get('status')} · remediation_doc: "
                f"{row.get('remediation_doc') or '(YOK — owner düzeltme yapmadı)'}\n\n"
                f"{SLA_DAYS}-gün SLA aşıldı; owner bulguyu süresinde kapatmadı. "
                f"Principal müdahalesi gerekli.\n"
            )
            path = self.write_protocol_doc(
                doc_type="audit_followup",
                body=body,
                slug=f"{fid}-overdue",
                target_dir=self._audit_reports_dir(),
                status="PROPOSED",
                confidence="high",
                requested_review_from=[row.get("owner", "ceo"), "audit_chief"],
                tags=["audit", "sla_breach", "principal_escalation", str(row.get("severity", ""))],
            )
            new_row = dict(row)
            new_row["escalated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            new_row["escalation_doc"] = str(path.relative_to(self._repo_root()))
            self._append_register(new_row)
            escalated.append(fid)
            try:
                from price_action.orchestrator.notifications import push_critical

                push_critical(
                    f"AUDIT SLA İHLALİ: {fid} ({row.get('control_id')}, "
                    f"{str(row.get('severity', '')).upper()}) — owner={row.get('owner')} "
                    f"{SLA_DAYS}-gün SLA'da kapatmadı ({overdue_h:.0f}s gecikme).",
                    source="audit_sla",
                )
            except Exception:
                pass
        if escalated:
            logger.info(
                "audit.overdue_escalated", extra={"auditor": self.name, "escalated": escalated}
            )
        return escalated

    # ------------------------------------------------------------------
    # Kontrol-testi registry + emit/AUTO-VERIFY/dedup döngüsü (Faz 4)
    # ------------------------------------------------------------------
    def controls(self) -> dict[str, Any]:
        """{control_id: runner} — alt sınıf override eder.

        runner() → Finding (problem) | None (TEMİZ) | SKIP (denetlenemedi).
        SKIP ile None FARKI kritik: None = problem yok (açık bulgu auto-CLOSE),
        SKIP = bilgi yok (dokunma, yanlışlıkla kapatma).
        """
        return {}

    _OPEN_STATES = ("OPEN", "REOPENED", "REMEDIATION_FILED")

    def _open_findings_for(self, control_id: str) -> list[dict[str, Any]]:
        return [
            r
            for r in self._latest_state().values()
            if r.get("control_id") == control_id and r.get("status") in self._OPEN_STATES
        ]

    async def run_controls(self) -> dict[str, Any]:
        """Her kontrol-testini koş:
        - Finding + açık-bulgu YOK  → emit (yeni problem)
        - Finding + açık-bulgu VAR  → dedup (tekrar emit etme)
        - None (TEMİZ) + açık-bulgu VAR → AUTO-VERIFY → CLOSED
        - SKIP → dokunma (denetlenemedi)
        """
        emitted: list[str] = []
        closed: list[str] = []
        reopened: list[str] = []
        for cid, runner in self.controls().items():
            try:
                f = runner()
            except Exception as exc:
                logger.warning("audit.control_run_fail", extra={"cid": cid, "err": str(exc)[:160]})
                continue
            if f is SKIP:
                continue  # denetlenemedi — durumu değiştirme
            open_f = self._open_findings_for(cid)
            if f is not None:
                # Problem HÂLÂ var. Owner "düzelttim" (REMEDIATION_FILED) dediyse ama
                # kontrol hâlâ kırıksa → REOPENED (boş kapatma iddiası yakalanır).
                filed = [r for r in open_f if r.get("status") == "REMEDIATION_FILED"]
                if filed:
                    for r in filed:
                        self.verify_remediation(
                            r["finding_id"],
                            passed=False,
                            remediation_doc=r.get("remediation_doc"),
                        )
                        reopened.append(r["finding_id"])
                elif not open_f:
                    emitted.append(str(self.emit_finding(f)))  # yeni problem
                # else: zaten OPEN/REOPENED → dedup (günlük tekrar emit etme)
            else:
                # TEMİZ → açık bulgu varsa doğrula+kapat (owner closure raporu referanslı).
                for r in open_f:
                    self.verify_remediation(
                        r["finding_id"],
                        passed=True,
                        remediation_doc=r.get("remediation_doc")
                        or "auto-verify: kontrol-testi artık TEMİZ (owner raporu yok)",
                    )
                    closed.append(r["finding_id"])
        # Her koşuda SLA aşımı taraması (1-gün geçen açık bulgu → Principal).
        overdue = self.escalate_overdue()
        if closed or reopened:
            logger.info(
                "audit.lifecycle_done",
                extra={"auditor": self.name, "closed": closed, "reopened": reopened},
            )
        return {"emitted": emitted, "closed": closed, "reopened": reopened, "overdue": overdue}

    async def daily_control_review(self) -> list[Any]:
        """Geriye uyumlu giriş: run_controls çağırır, emit edilen path'leri döner.
        (scheduler + run_audit bunu çağırır; artık auto-verify de yapar.)"""
        res = await self.run_controls()
        return res["emitted"]
