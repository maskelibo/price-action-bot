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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from price_action.logging_config import logger

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

        ts_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
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
            body = content[m.end() :]
            return fm, body
        except Exception as exc:
            logger.warning(
                "risk_officer.parse_fail", extra={"path": str(path), "err": str(exc)[:200]}
            )
            return {}, ""

    def _deterministic_gate_check(self, fm: dict[str, Any], body: str) -> dict[str, Any]:
        """12-madde risk gate'i (özet) — deterministik ön-kontrol.

        H1 FIX (Faz 4 hardening): keyword mention'lar artık `info_flags`
        (sadece bilgi). `risk_flags` SADECE **somut sayısal aşımlarda** set
        edilir. Eskiden her trading doc'unun "risk" geçtiği için
        is_high_risk=True flag'leniyordu → auto-critique seli. Şimdi:
        - Leverage > 5x → flag
        - risk_pct > 0.02 → flag
        - concentration_pct > 0.20 → flag
        - daily_dd > 0.05 → flag
        - max_concurrent > 3 → flag

        Auto-critique yolu KAPATILDI — her zaman LLM-driven review.
        LLM tail analysis yokluğunu da değerlendirsin.
        """
        info_flags: list[str] = []  # Sadece bilgi, alarm değil
        risk_flags: list[str] = []  # Somut numerical violation

        body_lower = body.lower()

        # 1. INFO: hangi risk parametreleri menzilde (alarm değil)
        info_keywords = (
            "risk_pct",
            "leverage",
            "concentration",
            "max_position",
            "drawdown",
            "stop_loss",
            "tp_r",
            "kelly",
            "correlation",
        )
        for kw in info_keywords:
            if kw in body_lower:
                info_flags.append(f"references_{kw}")

        # 2. RISK: yalnızca somut numerical aşımlar
        # 2a. Leverage > 5x
        leverage_matches = re.findall(r"leverage[:\s=]+(\d+(?:\.\d+)?)\s*x?", body, re.IGNORECASE)
        if leverage_matches:
            try:
                max_lev = max(float(x) for x in leverage_matches)
                if max_lev > 5:
                    risk_flags.append(f"high_leverage_{max_lev}x")
            except ValueError:
                pass

        # 2b. risk_pct > 0.02 (single trade %2'den yüksek)
        risk_pct_matches = re.findall(r"risk_pct[:\s=]+(\d+\.\d+)", body, re.IGNORECASE)
        if risk_pct_matches:
            try:
                max_risk = max(float(x) for x in risk_pct_matches)
                if max_risk > 0.02:
                    risk_flags.append(f"high_risk_pct_{max_risk}")
            except ValueError:
                pass

        # 2c. concentration > 20% (single symbol cap absolute)
        conc_matches = re.findall(r"concentration[a-z_]*[:\s=]+(\d+\.\d+)", body, re.IGNORECASE)
        if conc_matches:
            try:
                max_conc = max(float(x) for x in conc_matches)
                if max_conc > 0.20:
                    risk_flags.append(f"concentration_breach_{max_conc}")
            except ValueError:
                pass

        # 2d. daily_dd / weekly_dd >5% (deploy parametre değişikliği önerisinde)
        dd_matches = re.findall(r"(?:daily|weekly)_dd[:\s=]+(\d+\.\d+)", body, re.IGNORECASE)
        if dd_matches:
            try:
                max_dd = max(float(x) for x in dd_matches)
                if max_dd > 0.05:
                    risk_flags.append(f"dd_relaxation_{max_dd}")
            except ValueError:
                pass

        # 2e. max_concurrent_positions > 3 (current cap)
        mc_matches = re.findall(r"max_concurrent[a-z_]*[:\s=]+(\d+)", body, re.IGNORECASE)
        if mc_matches:
            try:
                max_mc = max(int(x) for x in mc_matches)
                if max_mc > 3:
                    risk_flags.append(f"concurrent_relaxation_{max_mc}")
            except ValueError:
                pass

        # 3. Tail event ve stress test referansı VAR mı?
        tail_keywords = (
            "stress",
            "tail",
            "worst-month",
            "worst_month",
            "fat-tail",
            "fat_tail",
            "black swan",
            "2022-05",
            "2022-11",
            "flash crash",
            "luna",
            "ftx",
        )
        has_tail_analysis = any(kw in body_lower for kw in tail_keywords)

        # 4. Status başka birinin onayını isteyip istemediği
        review_required = bool(fm.get("requested_review_from"))

        return {
            "info_flags": info_flags,  # bilgi — alarm değil
            "risk_flags": risk_flags,  # somut numerical aşım
            "has_tail_analysis": has_tail_analysis,
            "review_required": review_required,
            "doc_type": fm.get("doc_type"),
            # is_high_risk SADECE somut numerical violation varsa.
            # Eski "references_X" flag'lerine bakmıyor (H1 false-positive fix).
            "is_high_risk": len(risk_flags) > 0,
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

        # H1 FIX: Auto-critique yolu KALDIRILDI. Eskiden her "risk" kelime geçen
        # doc'a auto-critique basılıyordu (false positive seli). Şimdi LLM her
        # zaman karar verir; deterministic gate bulguları LLM prompt'una input.
        # Sadece **somut numerical aşım** + tail analysis yokluğu durumunda
        # auto-critique tetiklenir (gerçekten tehlikeli durum).
        if gate["risk_flags"] and not gate["has_tail_analysis"]:
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
                tags=["critique", "auto_reject", "numerical_breach"],
            )
            self._ack_in_inbox(original_doc_id)
            logger.warning(
                "risk_officer.auto_critique_numerical_breach",
                extra={
                    "original": original_doc_id,
                    "risk_flags": gate["risk_flags"],
                    "critique": str(critique_path),
                },
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
        # FIX 2026-07-07 (denetim CRIT): gate dict'inde "flags" anahtarı YOK —
        # H1 fix'i info_flags/risk_flags'e böldü ama burası güncellenmedi →
        # her deterministik vetoda KeyError: critique yazılmıyor, mesaj
        # ack'lenmeyip sonsuza dek yeniden deneniyordu. Veto yolu fiilen ölüydü.
        flags = gate.get("risk_flags") or gate.get("flags") or []
        flags_md = "\n".join(f"- `{f}`" for f in flags)
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

    async def review_all_pending(
        self,
        *,
        max_items: int = 5,
        max_input_tokens: int = 25_000,
    ) -> list[Path]:
        """Inbox'taki bekleyen tüm doc'ları sıralı review et.

        Cleanup 2: per-job token cap eklendi. Batch size 5 (Sonnet, hafif)
        ama input token toplamı ``max_input_tokens`` aşarsa kalanları
        sıradaki saate ertele. Telegram CRIT push: token cap reached.

        Sonnet pricing ~3.0/15.0 USD per 1M token → 25K input ≈ $0.075/saat.
        24 saat = $1.80/gün → aylık ~$54 worst-case. Kabul edilebilir.

        max_items + max_input_tokens conjunction: ikisinden hangisi önce
        gelirse o keser.
        """
        pending = self._scan_inbox(max_items=max_items)
        if not pending:
            logger.info("risk_officer.inbox_empty")
            return []

        logger.info(
            "risk_officer.batch_review_start",
            extra={"n": len(pending), "max_input_tokens": max_input_tokens},
        )
        results: list[Path] = []
        cumulative_input_chars = 0  # rough proxy: 1 token ≈ 4 char
        capped = False
        for msg in pending:
            # Cleanup 2: cap check ÖNCE — doc okuyup tokenize etmeden önce
            est_tokens = cumulative_input_chars // 4
            if est_tokens >= max_input_tokens:
                capped = True
                logger.warning(
                    "risk_officer.token_cap_reached",
                    extra={
                        "processed": len(results),
                        "skipped": len(pending) - len(results),
                        "est_tokens": est_tokens,
                        "cap": max_input_tokens,
                    },
                )
                break

            ref_path = msg.get("ref_path", "")
            if not ref_path:
                continue
            full = self.settings.reports_dir.parent / ref_path

            # Doc boyutunu ölç (LLM call'dan önce)
            try:
                doc_size = full.stat().st_size if full.exists() else 0
                cumulative_input_chars += doc_size
            except OSError:
                pass

            try:
                out = await self.review_doc(full)
                if out:
                    results.append(out)
            except Exception as exc:
                logger.warning(
                    "risk_officer.review_fail",
                    extra={"doc_id": msg.get("doc_id"), "err": str(exc)[:200]},
                )

        logger.info(
            "risk_officer.batch_review_done",
            extra={
                "n_processed": len(results),
                "est_input_tokens": cumulative_input_chars // 4,
                "capped": capped,
            },
        )
        return results
