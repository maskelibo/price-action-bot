"""Risk Officer Agent — Chief Risk Officer.

Faz 2.2: deterministik runbook (gerçek runtime risk gate'leri konfigde
deterministik kod tarafından uygulanır) + ince LLM wrapper (inbox doc'ları
critique/endorse eder).

HARD LIMIT (`agents/risk_officer.md` §How to Disagree):
- ❌ `configs/risk*.yaml`'a YAZMAZ
- ❌ Hiçbir runtime parametreyi DEĞİŞTİRMEZ
- ❌ Trading kararına müdahale etmez
- ✅ Sadece dosya yazar (critique veya endorse doc)
- ✅ Inbox'taki `recipient: risk_officer` mesajlarını işler

ADR-002 koruma — Risk Officer hâlâ "deterministic + read-only over configs"
sınırlı; bu modül sadece **review** katmanını ekler.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from price_action.logging_config import logger
from price_action.settings import get_settings

from .base import LLMAgentBase


class RiskOfficerAgent(LLMAgentBase):
    name: ClassVar[str] = "risk_officer"
    default_model: ClassVar[str] = "claude-sonnet-4-6"  # Sonnet — light reasoning
    allowed_tools: ClassVar[tuple[str, ...]] = (
        "read_file",  # config + doc okuma
        "write_report",  # critique/endorse yazma
    )

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        if not self.model:
            self.model = "claude-sonnet-4-6"

    # ------------------------------------------------------------------
    # Inbox processing
    # ------------------------------------------------------------------

    def _inbox_path(self) -> Path:
        return self.settings.memory_dir / "protocol" / "inbox.jsonl"

    def _scan_inbox(self, *, max_items: int = 20) -> list[dict[str, Any]]:
        """Inbox'tan recipient=risk_officer ve ack_at=null olanları topla.

        Append-only — eski satırlar değişmez. Son N satıra bak.
        """
        inbox = self._inbox_path()
        if not inbox.exists():
            return []
        try:
            lines = inbox.read_text(encoding="utf-8").strip().split("\n")
        except Exception as exc:
            logger.warning("risk_officer.inbox_read_fail", extra={"err": str(exc)[:200]})
            return []

        pending: list[dict[str, Any]] = []
        # Son 200 satıra bak (queue size limit)
        for line in lines[-200:]:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("recipient") == self.name and not msg.get("ack_at"):
                pending.append(msg)
                if len(pending) >= max_items:
                    break
        return pending

    def _ack_in_inbox(self, doc_id: str) -> bool:
        """`doc_id`'ye ait inbox satırının `ack_at`'ini doldur (idempotent).

        Inbox append-only, ama line-by-line YENİDEN YAZMA güvenli (atomik rename).
        """
        inbox = self._inbox_path()
        if not inbox.exists():
            return False
        try:
            lines = inbox.read_text(encoding="utf-8").split("\n")
        except Exception:
            return False

        ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        modified = False
        new_lines: list[str] = []
        for line in lines:
            line = line.strip()
            if not line:
                new_lines.append(line)
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                new_lines.append(line)
                continue
            if (
                msg.get("doc_id") == doc_id
                and msg.get("recipient") == self.name
                and not msg.get("ack_at")
            ):
                msg["ack_at"] = ts_iso
                modified = True
            new_lines.append(json.dumps(msg, ensure_ascii=False))

        if modified:
            tmp = inbox.with_suffix(inbox.suffix + ".tmp")
            tmp.write_text("\n".join(new_lines), encoding="utf-8")
            tmp.replace(inbox)
        return modified

    # ------------------------------------------------------------------
    # Faz 2.2 — Review
    # ------------------------------------------------------------------

    _FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

    def _parse_doc(self, path: Path) -> tuple[dict[str, Any], str]:
        """Frontmatter + body parse."""
        if not path.exists():
            return {}, ""
        try:
            import yaml
            content = path.read_text(encoding="utf-8")
            m = self._FRONTMATTER_RE.match(content)
            if not m:
                return {}, content
            fm = yaml.safe_load(m.group(1)) or {}
            body = content[m.end():]
            return fm, body
        except Exception as exc:
            logger.warning("risk_officer.parse_fail", extra={"path": str(path), "err": str(exc)[:200]})
            return {}, ""

    def _deterministic_gate_check(self, fm: dict[str, Any], body: str) -> dict[str, Any]:
        """12-madde risk gate'i (özet) — deterministik ön-kontrol.

        Bu LLM çağrısından ÖNCE çalışır; gate violation varsa LLM atlanır
        ve direkt REJECT critique yazılır.
        """
        flags: list[str] = []

        # 1. Body içinde risk parameter referansı arıyoruz
        risk_keywords = (
            "risk_pct", "leverage", "concentration", "max_position", "drawdown",
            "stop_loss", "tp_r", "kelly", "correlation",
        )
        for kw in risk_keywords:
            if kw in body.lower():
                flags.append(f"references_{kw}")

        # 2. Yüksek risk göstergeleri (sayısal)
        # %X risk veya leverage Nx pattern arama
        leverage_matches = re.findall(r"leverage[:\s]+(\d+)x?", body, re.IGNORECASE)
        if leverage_matches:
            max_lev = max(int(x) for x in leverage_matches)
            if max_lev > 5:
                flags.append(f"high_leverage_{max_lev}x")

        risk_pct_matches = re.findall(r"risk_pct[:\s]+([\d.]+)", body, re.IGNORECASE)
        if risk_pct_matches:
            max_risk = max(float(x) for x in risk_pct_matches)
            if max_risk > 0.02:  # %2 tek trade
                flags.append(f"high_risk_pct_{max_risk}")

        # 3. Tail event ve stress test referansı VAR mı?
        tail_keywords = ("stress", "tail", "worst-month", "fat-tail", "black swan", "2022-05", "2022-11", "flash crash")
        has_tail_analysis = any(kw in body.lower() for kw in tail_keywords)

        # 4. Status başka birinin onayını isteyip istemediği
        review_required = bool(fm.get("requested_review_from"))

        return {
            "flags": flags,
            "has_tail_analysis": has_tail_analysis,
            "review_required": review_required,
            "doc_type": fm.get("doc_type"),
            "is_high_risk": any(f.startswith("high_") for f in flags),
        }

    async def review_doc(self, doc_path: Path | str) -> Path | None:
        """Bir doc'u critique veya endorse et.

        Akış:
        1. Doc'u parse et (frontmatter + body)
        2. Deterministik 12-madde gate kontrolü
        3. Eğer gate violation → REJECT critique (LLM bypass)
        4. Yoksa → LLM ile critique/endorse karar ver
        5. Doc yaz (write_protocol_doc), inbox'a ACK koy

        Returns
        -------
        Path | None
            Üretilen critique/endorse doc path, veya None (doc okunamadıysa)
        """
        path = Path(doc_path)
        fm, body = self._parse_doc(path)
        if not fm:
            logger.warning("risk_officer.no_frontmatter", extra={"path": str(path)})
            return None

        original_doc_id = fm.get("doc_id", path.stem)

        # Deterministik gate
        gate = self._deterministic_gate_check(fm, body)
        logger.info(
            "risk_officer.gate_check",
            extra={"doc_id": original_doc_id, "gate": gate},
        )

        # Yüksek risk + tail analysis yoksa → direkt critique (LLM atla)
        if gate["is_high_risk"] and not gate["has_tail_analysis"]:
            crit_body = self._build_auto_critique(original_doc_id, gate)
            critique_path = self.write_protocol_doc(
                doc_type="critique",
                body=crit_body,
                slug=f"critique-{original_doc_id[:50]}",
                target_dir=self.settings.reports_dir / "risk",
                status="PROPOSED",
                confidence="high",
                depends_on=[original_doc_id],
                requested_review_from=["ceo"],
                tags=["critique", "auto_reject", "high_risk"],
            )
            self._ack_in_inbox(original_doc_id)
            logger.info(
                "risk_officer.auto_critique",
                extra={"original": original_doc_id, "critique": str(critique_path)},
            )
            return critique_path

        # LLM-driven critique veya endorse
        prompt = (
            "Sen Risk Officer'sın. Aşağıdaki dokümanı critique veya endorse etmen gerek.\n\n"
            "DOC FRONTMATTER:\n"
            f"{json.dumps({k: v for k, v in fm.items() if k in ('doc_id', 'doc_type', 'agent_id', 'tags', 'confidence')}, default=str, indent=2)}\n\n"
            "DOC BODY (ilk 3000 char):\n"
            f"{body[:3000]}\n\n"
            "DETERMINISTIC GATE OUTPUT:\n"
            f"{json.dumps(gate, indent=2)}\n\n"
            "Karar:\n"
            "1. Eğer doc risk-aware (tail analysis yapmış, conservative bias var) → ENDORSE\n"
            "2. Eğer risk eksiklik var (stress test yok, leverage yüksek, concentration ihmal) → CRITIQUE\n\n"
            "Çıktı zorunlu format — `memory/shared/templates/critique.md.tmpl` 5 alan:\n"
            "## Claim\n## Disagreement (CRITIQUE ise) VEYA ## Why I Endorse (ENDORSE ise)\n"
            "## Evidence\n## Alternative (CRITIQUE) VEYA ## Strengths I Want to Highlight (ENDORSE)\n"
            "## What would change my mind\n\n"
            "İlk satırda 'CRITIQUE' veya 'ENDORSE' yaz."
        )

        text = await self.run(prompt)

        # Decide critique vs endorse from LLM output
        is_critique = text.strip().upper().startswith("CRITIQUE")
        doc_type = "critique" if is_critique else "endorse"

        review_path = self.write_protocol_doc(
            doc_type=doc_type,
            body=text,
            slug=f"{doc_type}-{original_doc_id[:50]}",
            target_dir=self.settings.reports_dir / "risk",
            status="PROPOSED",
            confidence="high" if is_critique else "med",
            depends_on=[original_doc_id],
            requested_review_from=["ceo"] if is_critique else [],
            tags=[doc_type, "llm_reviewed", gate.get("doc_type", "unknown")],
        )
        self._ack_in_inbox(original_doc_id)
        return review_path

    def _build_auto_critique(self, original_doc_id: str, gate: dict[str, Any]) -> str:
        """Deterministik fail durumunda hızlı critique body."""
        flags_md = "\n".join(f"- `{f}`" for f in gate["flags"])
        return (
            f"## Claim\n"
            f"Original doc {original_doc_id} risk-relevant parametre içeriyor.\n\n"
            "## Disagreement\n"
            "Deterministik 12-madde risk gate'i fail. Yüksek-risk flag(ler) tespit edildi "
            "ama tail event analizi yok.\n\n"
            "## Evidence\n"
            f"Triggered flags:\n{flags_md}\n\n"
            f"Tail analysis present: {gate['has_tail_analysis']}\n\n"
            "## Alternative\n"
            "1. Stress test bölümü ekle (2022-05 LUNA, 2022-11 FTX, 2024-03 BTC ATH, 2024-08 Yen carry)\n"
            "2. Worst-month MaxDD analizi (mean değil)\n"
            "3. Joint distribution korelasyon stresli rejim hesabı\n"
            "4. Kelly fraction (full değil half/fractional)\n\n"
            "## What would change my mind\n"
            "Yukarıdaki 4 maddenin **sayısal kanıtla** raporda görünmesi. Stress periodlarında "
            "kayıp bütçesi %15'in altında kalıyorsa critique geri çekilir."
        )

    async def review_all_pending(self, *, max_items: int = 5) -> list[Path]:
        """Inbox'taki bekleyen tüm doc'ları sıralı review et.

        Batch size: 5 (Sonnet, hafif). Token aşımına karşı koruma.
        """
        pending = self._scan_inbox(max_items=max_items)
        if not pending:
            logger.info("risk_officer.inbox_empty")
            return []

        logger.info("risk_officer.batch_review_start", extra={"n": len(pending)})
        results: list[Path] = []
        for msg in pending:
            ref_path = msg.get("ref_path", "")
            if not ref_path:
                continue
            full = self.settings.reports_dir.parent / ref_path
            try:
                out = await self.review_doc(full)
                if out:
                    results.append(out)
            except Exception as exc:
                logger.warning(
                    "risk_officer.review_fail",
                    extra={"doc_id": msg.get("doc_id"), "err": str(exc)[:200]},
                )
        logger.info("risk_officer.batch_review_done", extra={"n_processed": len(results)})
        return results
