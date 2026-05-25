"""Researcher Agent — Head of Quantitative Research.

Hipotez üretimi → pre-registration → backtest yorumu → terfi/red kararı.
RAG'i çağırır; backtest tetikleyebilir (deterministik kod).

Faz 3.1: respond_to_drift(drift_doc_path) — drift_alert dokümanını okur,
RAG'den ilgili literatür çeker, hipotez kartı (DRAFT) üretir. Cooldown:
aynı drift_alert için max 3 hipotez yanıtı; reject sonrası 7g bekleme.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar

from price_action.logging_config import logger
from price_action.rag import retrieve_for_hypothesis
from price_action.settings import get_settings

from .base import LLMAgentBase

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG.sub("-", s.lower()).strip("-")[:60] or "hypothesis"


class ResearcherAgent(LLMAgentBase):
    name: ClassVar[str] = "researcher"
    default_model: ClassVar[str] = ""
    allowed_tools: ClassVar[tuple[str, ...]] = (
        "rag_retrieve",
        "backtest_run",
        "walk_forward_run",
        "read_file",
        "write_report",
    )

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        if not self.model:
            self.model = self.settings.claude_model_default

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------

    def _hypotheses_dir(self) -> Path:
        s = get_settings()
        p = s.memory_dir / self.name / "hypotheses"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _reports_dir(self) -> Path:
        s = get_settings()
        p = s.reports_dir / "research"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ------------------------------------------------------------------
    # SOP
    # ------------------------------------------------------------------

    async def propose_hypothesis(self, seed_topic: str) -> str:
        """SOP-1: Hipotez üretim. RAG'den 8-10 kaynak çekip hipotez yazar."""
        hits = retrieve_for_hypothesis(seed_topic, k=10)
        rag_block = "\n\n".join(
            f"[#{i+1} score={h.score:.3f} src={h.metadata.get('source_id', '?')} "
            f"author={h.metadata.get('author', '?')}]\n{h.text[:600]}"
            for i, h in enumerate(hits)
        ) or "(RAG corpus boş veya hit yok)"

        prompt = (
            f"SOP-1 Hipotez Üretim. Seed konu: '{seed_topic}'.\n"
            "Aşağıdaki RAG referanslarını kullan. Pre-registration formatına "
            "uygun, ölçülebilir bir hipotez yaz: iddia, gerekçe (RAG ref), "
            "dependent vars, independent vars, beklenen p-value, stop criteria. "
            "Sayı olmayan iddia yazma. Curve-fit şüphesi yarat.\n\n"
            f"--- RAG REFERENCES ---\n{rag_block}"
        )
        text = await self.run(prompt)
        self.record_episodic(
            f"propose_hypothesis seed={seed_topic[:80]}", tags=["hypothesis"]
        )
        return text

    def pre_register(self, hypothesis_md: str, slug: str | None = None) -> Path:
        """Hipotezi `memory/researcher/hypotheses/YYYY-MM-DD-<slug>.md`'ye yaz.

        Bu fonksiyon LLM çağırmaz — sadece dosya yazımı + commit metadata.
        """
        when = date.today()
        if not slug:
            # İlk H1/H2 başlığı slug olarak al
            for line in hypothesis_md.splitlines():
                line = line.strip()
                if line.startswith("#"):
                    slug = _slug(line.lstrip("#").strip())
                    break
        slug = slug or _slug(hypothesis_md[:60])
        path = self._hypotheses_dir() / f"{when.isoformat()}-{slug}.md"
        header = (
            f"---\n"
            f"agent: researcher\n"
            f"type: hypothesis\n"
            f"date: {when.isoformat()}\n"
            f"slug: {slug}\n"
            f"status: pre_registered\n"
            f"---\n\n"
        )
        path.write_text(header + hypothesis_md.strip() + "\n", encoding="utf-8")
        logger.info(
            "researcher.pre_registered", extra={"path": str(path), "slug": slug}
        )
        self.record_episodic(
            f"pre_registered hypothesis {slug}",
            tags=["hypothesis", "pre_register"],
        )
        return path

    async def interpret_backtest(self, result: dict[str, Any]) -> str:
        """Backtest sonucu üzerinden yorum yazar (overfit / regime / drift)."""
        prompt = (
            "SOP-3 Robustness Suite ışığında bu backtest sonucunu yorumla. "
            "Gate'leri tek tek geç (Sharpe, MaxDD, walk-forward dilimleri, "
            "regime split, shuffle baseline, Bonferroni). Numerik tabloyla cevap.\n\n"
            f"BACKTEST RESULT JSON: {result}"
        )
        return await self.run(prompt)

    # ------------------------------------------------------------------
    # Faz 3.1 — drift response
    # ------------------------------------------------------------------

    _FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

    def _parse_doc(self, path: Path) -> tuple[dict[str, Any], str]:
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
            logger.warning("researcher.parse_fail", extra={"path": str(path), "err": str(exc)[:200]})
            return {}, ""

    def _drift_response_count(self, drift_doc_id: str) -> int:
        """Bu drift_doc_id için kaç hipotez kartı üretildi (cooldown)."""
        hdir = self._hypotheses_dir()
        if not hdir.exists():
            return 0
        count = 0
        for h in hdir.glob("*.md"):
            try:
                content = h.read_text(encoding="utf-8")[:2000]
                if drift_doc_id in content:
                    count += 1
            except Exception:
                continue
        return count

    def _drift_in_cooldown(self, drift_doc_id: str, symbol: str, strategy: str) -> tuple[bool, str]:
        """Cooldown kontrolü.

        - Aynı drift_doc_id için max 3 hipotez
        - Aynı (symbol, strategy) Lab REJECT sonrası 7 gün cooldown
        """
        # Rule 1: drift_doc_id sayım
        n = self._drift_response_count(drift_doc_id)
        if n >= 3:
            return True, f"max_3_responses_reached (current={n})"

        # Rule 2: 7g cooldown — son rejected hypothesis var mı?
        hdir = self._hypotheses_dir()
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        for h in hdir.glob("*.md"):
            try:
                mtime = datetime.fromtimestamp(h.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    continue
                content = h.read_text(encoding="utf-8")[:3000]
                if symbol in content and strategy in content and "REJECTED" in content.upper():
                    days_ago = (datetime.now(timezone.utc) - mtime).days
                    return True, f"recent_reject_within_7d (symbol={symbol}, strategy={strategy}, days_ago={days_ago})"
            except Exception:
                continue

        return False, "ok"

    async def respond_to_drift(self, drift_doc_path: Path | str) -> Path | None:
        """Drift alert dokümanını oku, hipotez kartı taslağı üret.

        Cooldown kontrolünden geçerse RAG (rejim-spesifik literatür) çekip
        pre-registration formatında DRAFT hypothesis yazar.

        Returns
        -------
        Path | None
            Üretilen hipotez kartı, veya None (cooldown reddetti veya doc okunamadı).
        """
        drift_path = Path(drift_doc_path)
        fm, body = self._parse_doc(drift_path)
        if not fm or fm.get("doc_type") != "drift_alert":
            logger.warning(
                "researcher.invalid_drift_doc",
                extra={"path": str(drift_path), "doc_type": fm.get("doc_type")},
            )
            return None

        drift_doc_id = fm.get("doc_id", drift_path.stem)
        tags = fm.get("tags", [])
        # drift_alert tags: ["drift", strategy, symbol]
        symbol = tags[2] if len(tags) >= 3 else "unknown"
        strategy = tags[1] if len(tags) >= 2 else "unknown"

        # Cooldown
        in_cooldown, reason = self._drift_in_cooldown(drift_doc_id, symbol, strategy)
        if in_cooldown:
            logger.info(
                "researcher.drift_cooldown",
                extra={"drift_doc_id": drift_doc_id, "reason": reason},
            )
            return None

        # RAG çek — rejim-spesifik literatür
        try:
            seed = f"drift detection in {strategy} for {symbol} — regime shift adaptation"
            hits = retrieve_for_hypothesis(seed, k=8)
        except Exception as exc:
            logger.warning("researcher.rag_fail", extra={"err": str(exc)[:200]})
            hits = []

        rag_block = "\n\n".join(
            f"[#{i+1} score={h.score:.3f} src={h.metadata.get('source_id', '?')}]\n{h.text[:500]}"
            for i, h in enumerate(hits)
        ) or "(RAG corpus boş veya hit yok)"

        prompt = (
            "Drift alert geldi. Yanıt olarak pre-registration formatında DRAFT "
            "hipotez kartı üret. Falsifiable, sayısal, OOS testable.\n\n"
            "DRIFT DOC FRONTMATTER:\n"
            f"{json.dumps({k: v for k, v in fm.items() if k in ('doc_id', 'tags', 'created_at')}, default=str, indent=2)}\n\n"
            "DRIFT DOC BODY (ilk 2000 char):\n"
            f"{body[:2000]}\n\n"
            "RAG REFERENCES (rejim shift literatür):\n"
            f"{rag_block}\n\n"
            "Görev: `memory/shared/templates/hypothesis.md.tmpl` body yapısında:\n"
            "1. İddia (H1) — falsifiable\n"
            "2. Null hipotez (H0)\n"
            "3. Gerekçe (RAG ref)\n"
            "4. Bağımsız değişkenler (grid)\n"
            "5. Bağımlı değişkenler (metrikler)\n"
            "6. Anti-overfit protokolü (8 madde)\n"
            "7. Kabul kriteri (HARD gates)\n"
            "8. Stop criteria\n"
            "9. Önsel tahmin (Tetlock calibration)\n\n"
            f"BİLGİ: Bu hipotez {drift_doc_id} drift'ine yanıttır. depends_on'a koy."
        )
        body_text = await self.run(prompt)

        # write_protocol_doc kullan (Faz 1.5 helper)
        hyp_path = self.write_protocol_doc(
            doc_type="hypothesis",
            body=body_text,
            slug=f"drift-response-{symbol}-{strategy}",
            target_dir=self._hypotheses_dir(),
            status="DRAFT",
            confidence="med",
            depends_on=[drift_doc_id],
            requested_review_from=["lab_scientist", "risk_officer"],
            tags=["hypothesis", "drift_response", strategy, symbol],
        )
        logger.info(
            "researcher.drift_response_written",
            extra={"drift_doc_id": drift_doc_id, "hyp_path": str(hyp_path)},
        )
        return hyp_path

    async def respond_to_pending_drifts(self, *, max_items: int = 3) -> list[Path]:
        """Inbox'taki recipient=researcher, doc_type=drift_alert mesajları işle.

        Scheduler `_job_scan_drift_alerts` her 30dk çağırır.
        """
        inbox = self.settings.memory_dir / "protocol" / "inbox.jsonl"
        if not inbox.exists():
            return []

        results: list[Path] = []
        try:
            lines = inbox.read_text(encoding="utf-8").strip().split("\n")
        except Exception as exc:
            logger.warning("researcher.inbox_read_fail", extra={"err": str(exc)[:200]})
            return []

        for line in lines[-200:]:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("recipient") != self.name:
                continue
            if msg.get("ack_at"):
                continue
            if msg.get("topic") != "drift_alert":
                continue
            ref_path = msg.get("ref_path", "")
            if not ref_path:
                continue
            full = self.settings.reports_dir.parent / ref_path
            try:
                out = await self.respond_to_drift(full)
                if out:
                    results.append(out)
                    # ack inbox
                    self._ack_in_inbox(msg.get("doc_id", ""))
            except Exception as exc:
                logger.warning(
                    "researcher.drift_response_fail",
                    extra={"drift_doc_id": msg.get("doc_id"), "err": str(exc)[:200]},
                )
            if len(results) >= max_items:
                break

        return results

    def _ack_in_inbox(self, doc_id: str) -> bool:
        """Inbox satırına ack_at koy (atomik)."""
        inbox = self.settings.memory_dir / "protocol" / "inbox.jsonl"
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

    async def decide_promotion(self, result: dict[str, Any]) -> dict[str, Any]:
        """SOP-4: terfi adayı / red kararı. Karar + ADR yazımı."""
        commentary = await self.interpret_backtest(result)
        # Basit deterministik gate kontrolü; LLM commentary'i destek olarak.
        passed = (
            float(result.get("oos_sharpe", 0)) >= 1.0
            and float(result.get("oos_maxdd", 1)) <= 0.25
            and float(result.get("walk_forward_pos_ratio", 0)) >= 0.66
            and float(result.get("shuffle_p_value", 1)) < 0.05
        )
        decision = "promote_candidate" if passed else "reject"
        adr = {
            "title": f"Strategy decision: {result.get('strategy_id', 'unknown')}",
            "context": f"Backtest result: {result}",
            "options": "Promote candidate / Reject / Wait for more data",
            "decision": decision,
            "consequences": commentary,
            "status": "proposed",
        }
        self.write_decision(adr, slug=f"strategy-{result.get('strategy_id', 'x')}")
        # Rapor da yaz
        report_path = self._reports_dir() / (
            f"{result.get('strategy_id', 'unknown')}-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.md"
        )
        report_path.write_text(
            f"# Research Report — {result.get('strategy_id', 'unknown')}\n\n"
            f"## Decision\n{decision}\n\n"
            f"## Backtest Result\n```json\n{result}\n```\n\n"
            f"## LLM Commentary\n{commentary}\n",
            encoding="utf-8",
        )
        return {
            "decision": decision,
            "commentary": commentary,
            "report_path": str(report_path),
        }
