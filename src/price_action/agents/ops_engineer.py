"""Ops Engineer — hybrid agent.

Tek LLM görevi: incident summary üretmek (Haiku model, kısa).
Geri kalan tüm SRE işleri deterministik kodda kalır.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from .base import LLMAgentBase


class OpsAgent(LLMAgentBase):
    name: ClassVar[str] = "ops_engineer"
    default_model: ClassVar[str] = ""  # settings.claude_model_light (Haiku)
    allowed_tools: ClassVar[tuple[str, ...]] = (
        "read_log",
        "read_metric",
        "write_report",
    )

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        if not self.model:
            self.model = self.settings.claude_model_light

    async def incident_summary(
        self,
        logs: list[str],
        metrics: dict[str, Any] | None = None,
    ) -> str:
        """Incident postmortem'in ilk taslağı.

        Maks 200 kelime; structured: trigger, kapsam, etki, kök neden hipotezi,
        takip aksiyonu.
        """
        log_block = "\n".join(logs[-200:])  # son 200 satır yeter
        metric_block = ""
        if metrics:
            metric_block = "\nMetrics: " + ", ".join(f"{k}={v}" for k, v in metrics.items())
        prompt = (
            "Incident summary üret. Maks 200 kelime. Bölümler: "
            "trigger, kapsam, etki, kök neden hipotezi, takip aksiyonu. "
            "Hiçbir API anahtarı, IP, kullanıcı verisi sızdırma.\n\n"
            f"--- LOGS (son 200 satır) ---\n{log_block}{metric_block}"
        )
        text = await self.run(prompt, max_tokens=1024, temperature=0.1)
        # Diske de yaz (insan revizyonu için)
        path = self._write_incident_file(text)
        self.record_episodic(
            f"incident_summary written: {path.name}",
            tags=["incident"],
        )
        return text

    def _write_incident_file(self, text: str) -> Path:
        s = self.settings
        d = s.reports_dir / "ops" / "incidents"
        d.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        path = d / f"{ts}.md"
        path.write_text(text, encoding="utf-8")
        return path
