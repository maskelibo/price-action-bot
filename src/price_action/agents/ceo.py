"""CEO Agent — Trading Desk Head.

CEO'nun mandate'i:
- Günlük morning brief
- Haftalık executive summary
- Kriz protokolü tetikleme önerisi
- Departmanlar arası çatışma çözme

CEO emir VEREMEZ — sadece **öneri** üretir. Çıktı `reports/ceo/` altında
markdown olarak diskte kalır.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from price_action.logging_config import logger
from price_action.settings import get_settings

from .base import LLMAgentBase


class CEOAgent(LLMAgentBase):
    name: ClassVar[str] = "ceo"
    default_model: ClassVar[str] = ""  # settings.claude_model_default
    # CEO sadece okuma + dosya yazma yapabilir (rapor)
    allowed_tools: ClassVar[tuple[str, ...]] = (
        "read_file",
        "list_dir",
        "write_report",
    )

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        if not self.model:
            self.model = self.settings.claude_model_default

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------

    def _reports_dir(self) -> Path:
        p = self.settings.reports_dir / "ceo"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _write_report(self, filename: str, content: str) -> Path:
        path = self._reports_dir() / filename
        path.write_text(content, encoding="utf-8")
        logger.info("ceo.report_written", extra={"path": str(path)})
        return path

    # ------------------------------------------------------------------
    # SOP
    # ------------------------------------------------------------------

    async def daily_brief(self, when: date | None = None) -> Path:
        """Sabah brief'ini üretir. Çıktı: `reports/ceo/YYYY-MM-DD-brief.md`."""
        when = when or date.today()
        prompt = (
            "SOP-1 Günlük Morning Brief üret. Önce dünkü Analytics raporlarını "
            "ve açık pozisyon snapshot'ını oku (varsa). 'CEO Morning Brief' "
            "başlık formatında çıktı ver. Sayısal gerekçe olmayan satır yazma."
        )
        ctx = self._collect_daily_context(when)
        text = await self.run(prompt, context_files=ctx)
        path = self._write_report(f"{when.isoformat()}-brief.md", text)
        self.record_episodic(
            f"daily_brief produced for {when.isoformat()}", tags=["brief", "daily"]
        )
        return path

    async def weekly_summary(self, week_label: str | None = None) -> Path:
        """Haftalık executive summary."""
        if week_label is None:
            iso = datetime.now(timezone.utc).isocalendar()
            week_label = f"{iso.year}-W{iso.week:02d}"
        prompt = (
            "SOP-2 Haftalık Executive Summary üret. Net P&L, Sharpe, MaxDD, "
            "profit factor; Researcher hipotez özeti; Lab tournament sonucu; "
            "drift uyarısı; aday parametre değişiklikleri (insan onayına); "
            "önümüzdeki haftaya 3 watch-item."
        )
        ctx = self._collect_weekly_context()
        text = await self.run(prompt, context_files=ctx)
        return self._write_report(f"{week_label}-weekly.md", text)

    async def crisis_protocol(self, reason: str) -> Path:
        """Kriz protokolü — önerileri üretir; aksiyon almaz."""
        prompt = (
            f"SOP-3 Kriz Protokolü tetiklendi. Tetikleyici: {reason}. "
            "Sadece **öneri** üret: Telegram CRIT alert metni, açık pozisyon "
            "için partial-close veya SL sıkıştırma önerisi, sebep analizi. "
            "Hiçbir komut çağrısı yapma; insan onayı zorunlu olduğunu yinele."
        )
        text = await self.run(prompt)
        slug = "crisis-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = self._write_report(f"{slug}.md", text)
        self.record_episodic(
            f"crisis_protocol triggered: {reason}", tags=["crisis"], kind="learning"
        )
        return path

    async def arbitrate(self, conflict: dict[str, Any]) -> str:
        """SOP-4: Departmanlar arası çatışma çözümü. ADR yazar + cevap döner.

        ``conflict`` örneği::
            {
              "topic": "promotion_vs_drift",
              "researcher_view": "...",
              "lab_view": "...",
              "metrics": {...}
            }
        """
        prompt = (
            "SOP-4 Departmanlar Arası Çatışma. Aşağıdaki çatışmayı sayısal "
            "gerekçelerle değerlendirip karar öner. Conservative bias: "
            "şüphedeyken Risk/Lab tarafına yaslan.\n\n"
            f"CONFLICT: {conflict}"
        )
        text = await self.run(prompt)
        adr = {
            "title": f"Arbitration: {conflict.get('topic', 'untitled')}",
            "context": str(conflict),
            "options": "Promote / Reject / Wait",
            "decision": text,
            "consequences": "Re-evaluate in 4 weeks.",
            "status": "proposed",
        }
        self.write_decision(adr, slug=f"arbitration-{conflict.get('topic', 'untitled')}")
        return text

    # ------------------------------------------------------------------
    # Context toplama
    # ------------------------------------------------------------------

    def _collect_daily_context(self, when: date) -> list[Path]:
        s = get_settings()
        candidates = [
            s.reports_dir / "analytics" / f"{when.isoformat()}.md",
            s.reports_dir / "analytics" / "yesterday.md",
            s.reports_dir / "lab" / "latest.md",
        ]
        return [p for p in candidates if p.exists()]

    def _collect_weekly_context(self) -> list[Path]:
        s = get_settings()
        candidates: list[Path] = []
        for sub in ("analytics", "research", "lab"):
            d = s.reports_dir / sub
            if d.exists():
                latest = sorted(d.glob("*.md"), reverse=True)[:3]
                candidates.extend(latest)
        return candidates
