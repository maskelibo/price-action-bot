"""MemoryStore — agent başına markdown bellek katmanı.

Bu modül agent'ların dosya tabanlı kalıcı belleğine okuma/yazma API'si sağlar.
Yapı `memory/README.md` ile uyumludur.

Önemli kurallar:
- Identity dışındaki dosyalar **append-only** kabul edilir; silme yok.
- Her append entry bir tarih başlığı + slug + confidence ile yazılır.
- Decisions ADR formatında ayrı dosyaya yazılır (`decisions/YYYY-MM-DD-<slug>.md`).
- Shared facts (`memory/shared/facts/*.md`) ve shared lessons
  (`memory/shared/lessons/*.md`) tüm agent'lar tarafından okunur.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from price_action.contracts import MemoryEntry
from price_action.logging_config import logger
from price_action.settings import get_settings

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    """Tarih/dosya isimleri için güvenli slug üretir."""
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:60] or "entry"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


class MemoryStore:
    """Agent başına markdown bellek API'si.

    Markdown dosyaları append-only. Yazımlar tarihli başlıklarla altta birikir.
    Decisions her büyük karar için ayrı bir ADR dosyasına yazılır.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        s = get_settings()
        self.base_dir: Path = (base_dir or s.memory_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "shared" / "facts").mkdir(parents=True, exist_ok=True)
        (self.base_dir / "shared" / "lessons").mkdir(parents=True, exist_ok=True)
        (self.base_dir / "shared" / "decisions").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Yol yardımcıları
    # ------------------------------------------------------------------

    def _agent_dir(self, agent: str) -> Path:
        path = self.base_dir / agent
        path.mkdir(parents=True, exist_ok=True)
        (path / "decisions").mkdir(parents=True, exist_ok=True)
        (path / "runtime").mkdir(parents=True, exist_ok=True)
        return path

    def identity_path(self, agent: str) -> Path:
        return self._agent_dir(agent) / "identity.md"

    def know_how_path(self, agent: str) -> Path:
        return self._agent_dir(agent) / "know_how.md"

    def learning_path(self, agent: str) -> Path:
        return self._agent_dir(agent) / "learning.md"

    def decisions_dir(self, agent: str) -> Path:
        return self._agent_dir(agent) / "decisions"

    # ------------------------------------------------------------------
    # Okuma API'si
    # ------------------------------------------------------------------

    def read_identity(self, agent: str) -> str:
        return _read_text(self.identity_path(agent))

    def read_know_how(self, agent: str) -> str:
        return _read_text(self.know_how_path(agent))

    def read_learning(self, agent: str) -> str:
        return _read_text(self.learning_path(agent))

    def read_decisions(self, agent: str, limit: int | None = None) -> list[tuple[str, str]]:
        """`(filename, content)` listesi — yeni ADR'ler önce."""
        out: list[tuple[str, str]] = []
        for p in sorted(self.decisions_dir(agent).glob("*.md"), reverse=True):
            out.append((p.name, p.read_text(encoding="utf-8")))
            if limit and len(out) >= limit:
                break
        return out

    def read_shared_facts(self) -> dict[str, str]:
        """`memory/shared/facts/*.md` -> dict[stem, content]."""
        facts_dir = self.base_dir / "shared" / "facts"
        out: dict[str, str] = {}
        for p in sorted(facts_dir.glob("*.md")):
            out[p.stem] = p.read_text(encoding="utf-8")
        return out

    def read_shared_lessons(self, limit: int = 20) -> list[str]:
        """En yeni ``limit`` adet shared lesson içeriği (mtime'a göre azalan)."""
        lessons_dir = self.base_dir / "shared" / "lessons"
        files = sorted(lessons_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [f.read_text(encoding="utf-8") for f in files[:limit]]

    # ------------------------------------------------------------------
    # Yazma API'si (append-only)
    # ------------------------------------------------------------------

    def _append_markdown(self, path: Path, entry: MemoryEntry) -> None:
        """Markdown dosyasına bir entry alta append eder.

        Format:
            ### YYYY-MM-DD — <slug> (confidence)
            tags: [...]
            <body>
            ---
        """
        _ensure_parent(path)
        date_str = entry.ts.strftime("%Y-%m-%d")
        tags = ", ".join(entry.tags) if entry.tags else "—"
        block = (
            f"\n### {date_str} — {entry.slug} ({entry.confidence})\n"
            f"- tags: {tags}\n\n"
            f"{entry.body.rstrip()}\n\n---\n"
        )
        # Dosya yoksa minimal başlık ekle
        if not path.exists():
            path.write_text(
                f"---\nagent: {entry.agent}\ntype: {entry.type}\n---\n\n"
                f"# {entry.agent.title()} — {entry.type.replace('_', ' ').title()}\n",
                encoding="utf-8",
            )
        with path.open("a", encoding="utf-8") as fh:
            fh.write(block)
        logger.debug(
            "memory.append",
            extra={"agent": entry.agent, "type": entry.type, "slug": entry.slug},
        )

    def append_learning(self, agent: str, entry: MemoryEntry) -> Path:
        if entry.type != "learning":
            entry = entry.model_copy(update={"type": "learning", "agent": agent})
        path = self.learning_path(agent)
        self._append_markdown(path, entry)
        return path

    def append_know_how(self, agent: str, entry: MemoryEntry) -> Path:
        if entry.type != "know_how":
            entry = entry.model_copy(update={"type": "know_how", "agent": agent})
        path = self.know_how_path(agent)
        self._append_markdown(path, entry)
        return path

    def write_decision(
        self,
        agent: str,
        adr: dict[str, Any],
        slug: str | None = None,
        when: date | None = None,
    ) -> Path:
        """ADR yazar: `decisions/YYYY-MM-DD-<slug>.md`.

        ``adr`` sözlüğü beklenen alanlar: ``title``, ``context``, ``options``,
        ``decision``, ``consequences``, ``status`` (default 'proposed'). Eksik
        alanlar boş olarak yazılır; hiçbiri zorunlu değil ama en az ``title``
        verilmeli.
        """
        when = when or date.today()
        title = str(adr.get("title", "decision"))
        slug_final = _slugify(slug or title)
        path = self.decisions_dir(agent) / f"{when.isoformat()}-{slug_final}.md"
        _ensure_parent(path)

        status = adr.get("status", "proposed")
        body = (
            f"---\n"
            f"agent: {agent}\n"
            f"type: decision\n"
            f"date: {when.isoformat()}\n"
            f"status: {status}\n"
            f"---\n\n"
            f"# ADR: {title}\n\n"
            f"## Context\n{adr.get('context', '')}\n\n"
            f"## Options\n{adr.get('options', '')}\n\n"
            f"## Decision\n{adr.get('decision', '')}\n\n"
            f"## Consequences\n{adr.get('consequences', '')}\n\n"
            f"## Notes\n{adr.get('notes', '')}\n"
        )
        path.write_text(body, encoding="utf-8")
        logger.info("memory.decision_written", extra={"agent": agent, "path": str(path)})
        return path

    # ------------------------------------------------------------------
    # Boot context
    # ------------------------------------------------------------------

    def boot_context(self, agent: str) -> str:
        """Her LLM çağrısı öncesi system prompt'a girecek özet.

        Identity + know_how + son 5 learning entry + son 5 shared lesson +
        shared facts başlık özetlerini içerir.
        """
        identity = self.read_identity(agent).strip()
        know_how = self.read_know_how(agent).strip()
        learning_full = self.read_learning(agent).strip()
        last_learning = _last_n_blocks(learning_full, n=5)
        last_lessons = self.read_shared_lessons(limit=5)
        facts = self.read_shared_facts()

        parts: list[str] = []
        parts.append(f"## IDENTITY\n{identity or '(empty)'}\n")
        parts.append(f"## KNOW-HOW\n{know_how or '(empty)'}\n")
        parts.append(
            f"## RECENT LEARNINGS (last 5)\n{last_learning or '(no recent learnings)'}\n"
        )
        if last_lessons:
            parts.append(
                "## RECENT SHARED LESSONS (last 5)\n"
                + "\n\n---\n\n".join(s.strip() for s in last_lessons)
                + "\n"
            )
        if facts:
            fact_titles = ", ".join(sorted(facts.keys()))
            parts.append(f"## SHARED FACTS AVAILABLE\n{fact_titles}\n")
        return "\n".join(parts)


def _last_n_blocks(markdown: str, n: int = 5) -> str:
    """Markdown içinde `### ` ile başlayan son n bloku döndür."""
    if not markdown:
        return ""
    blocks: list[str] = []
    current: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("### "):
            if current:
                blocks.append("\n".join(current).strip())
                current = []
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    # Filter to those that actually look like entries (start with `### `)
    entry_blocks = [b for b in blocks if b.startswith("### ")]
    return "\n\n".join(entry_blocks[-n:])


# ----------------------------------------------------------------------
# Yardımcılar — public
# ----------------------------------------------------------------------

def make_entry(
    agent: str,
    body: str,
    *,
    entry_type: str = "learning",
    slug: str | None = None,
    confidence: str = "med",
    tags: list[str] | None = None,
    ts: datetime | None = None,
) -> MemoryEntry:
    """``MemoryEntry`` üretmek için convenience helper."""
    return MemoryEntry(
        agent=agent,
        type=entry_type,  # type: ignore[arg-type]
        slug=_slugify(slug or body[:40]),
        body=body,
        ts=ts or datetime.now(timezone.utc),
        confidence=confidence,  # type: ignore[arg-type]
        tags=list(tags or []),
    )
