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
from datetime import UTC, date, datetime
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

    # ------------------------------------------------------------------
    # Faz 2.5 — protokol-uyumlu doc listeleme
    # ------------------------------------------------------------------

    def list_recent_docs(
        self,
        agent: str | None = None,
        doc_type: str | None = None,
        *,
        since_days: int = 7,
        reports_root: Path | None = None,
    ) -> list[Path]:
        """Recent protocol-compliant doc'ları listele.

        ``reports/<agent>/`` veya genel `reports/`'u tarar, frontmatter'a
        bakarak filtre uygular.

        Parameters
        ----------
        agent:
            Belirli bir agent'ın çıktıları (örn. "ceo", "researcher").
            None ise tüm agent'lar.
        doc_type:
            Belirli doc_type (örn. "brief", "hypothesis", "tournament").
            None ise tüm tipler.
        since_days:
            Son N gün (mtime bazlı, frontmatter parse'ı pahalı olduğu için).
        reports_root:
            Override (default: ``settings.reports_dir``).

        Returns
        -------
        list[Path]
            En yeni doc'lar başta, sıralı.
        """
        if reports_root is None:
            s = get_settings()
            reports_root = s.reports_dir
        if not reports_root.exists():
            return []

        from datetime import datetime as _dt

        cutoff = _dt.now(UTC).timestamp() - since_days * 86400

        # Hangi dizinleri tara
        if agent:
            search_dirs = [reports_root / agent]
        else:
            search_dirs = [d for d in reports_root.iterdir() if d.is_dir()]

        candidates: list[tuple[float, Path]] = []
        for d in search_dirs:
            if not d.exists():
                continue
            for p in d.rglob("*.md"):
                try:
                    mtime = p.stat().st_mtime
                    if mtime < cutoff:
                        continue
                    # doc_type filtre — frontmatter peek (sadece ilk 20 satır)
                    if doc_type:
                        try:
                            head = p.read_text(encoding="utf-8")[:1024]
                            if f"doc_type: {doc_type}" not in head:
                                continue
                        except Exception:
                            continue
                    candidates.append((mtime, p))
                except OSError:
                    continue

        # Sort: en yeni başta
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in candidates]

    def boot_context(self, agent: str) -> str:
        """Her LLM çağrısı öncesi system prompt'a girecek özet.

        Identity + know_how + son N learning entry + sidecar learning özetleri
        + son 5 shared lesson + shared facts başlık özetlerini içerir.

        FIX 2026-07-02 (hafıza RW): "sistem biriktirdiğinin %5'ini hatırlıyor"
        bulgusuna cevap — (1) learning son-5-blok hapsi → son 25 blok +
        char-cap 24K (researcher 278KB / 115 blok biriktirmişti, %96'sı hiç
        yüklenmiyordu); (2) sidecar `learning_*.md` dosyaları (20 dosya,
        ~120KB forensik içerik, SIFIR okuyucu) artık başlık+ilk-paragraf
        özetiyle boot'a giriyor; (3) shared facts sadece başlık değil kısa
        içerik önizlemesiyle yüklenir.
        """
        identity = self.read_identity(agent).strip()
        know_how = self.read_know_how(agent).strip()
        learning_full = self.read_learning(agent).strip()
        # Son 25 blok, toplam 24K char tavanı (prompt şişme emniyeti)
        last_learning = _last_n_blocks(learning_full, n=25)
        if len(last_learning) > 24_000:
            last_learning = last_learning[-24_000:]
        last_lessons = self.read_shared_lessons(limit=5)
        facts = self.read_shared_facts()

        parts: list[str] = []
        parts.append(f"## IDENTITY\n{identity or '(empty)'}\n")
        parts.append(f"## KNOW-HOW\n{know_how or '(empty)'}\n")
        parts.append(f"## RECENT LEARNINGS (last 25)\n{last_learning or '(no recent learnings)'}\n")
        # Sidecar learning dosyaları — başlık + ilk anlamlı satırlar (özet)
        try:
            agent_dir = self.base_dir / agent
            sidecars = sorted(
                agent_dir.glob("learning_*.md"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:8]
            if sidecars:
                sc_parts: list[str] = []
                for p in sidecars:
                    try:
                        txt = p.read_text(encoding="utf-8").strip()
                    except OSError:
                        continue
                    head = "\n".join(txt.splitlines()[:12])[:1200]
                    sc_parts.append(f"[{p.name}]\n{head}")
                if sc_parts:
                    parts.append(
                        "## SIDECAR LEARNING DIGESTS (en yeni 8 dosya, özet)\n"
                        + "\n\n---\n\n".join(sc_parts)
                        + "\n"
                    )
        except Exception:
            pass  # sidecar özetleme asla boot'u kırmasın
        if last_lessons:
            parts.append(
                "## RECENT SHARED LESSONS (last 5)\n"
                + "\n\n---\n\n".join(s.strip() for s in last_lessons)
                + "\n"
            )
        if facts:
            fact_lines: list[str] = []
            for k in sorted(facts.keys()):
                v = str(facts.get(k, "")).strip().replace("\n", " ")
                fact_lines.append(f"- {k}: {v[:280]}")
            parts.append("## SHARED FACTS\n" + "\n".join(fact_lines) + "\n")
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
        ts=ts or datetime.now(UTC),
        confidence=confidence,  # type: ignore[arg-type]
        tags=list(tags or []),
    )
