"""Memory layer — agent persona, know-how, learning, decisions, runtime episodic.

Bu paket dosya tabanlı bir bellek katmanı sağlar. Markdown ve JSONL üzerinde
çalışır; çoklu süreç güvenli olması zorunlu değildir (her agent kendi LLM
çağrısında okur/yazar; orchestrator yazımları seri sıraya koyar).

İçerik dağılımı:
- ``store.MemoryStore`` — markdown identity / know_how / learning / decisions
  okuma ve append-only yazma API'si.
- ``episodic.EpisodicLog`` — JSONL kısa vadeli episodic log; Lab haftalık
  konsolide eder.

Memory dosyaları **append-only**. Silme yok. Revize gerekirse "(revised: ...)"
notu ile satır eklenir.
"""
from __future__ import annotations

from .episodic import EpisodicLog
from .store import MemoryStore

__all__ = ["EpisodicLog", "MemoryStore"]
