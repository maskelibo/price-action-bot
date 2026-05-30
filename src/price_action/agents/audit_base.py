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
        due_days: int = 7,
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
        for fid, row in self._latest_state().items():
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

        due_at = (ts + timedelta(days=f.due_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
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
