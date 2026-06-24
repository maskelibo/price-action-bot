"""Researcher Agent — Head of Quantitative Research.

Hipotez üretimi → pre-registration → backtest yorumu → terfi/red kararı.
RAG'i çağırır; backtest tetikleyebilir (deterministik kod).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
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
