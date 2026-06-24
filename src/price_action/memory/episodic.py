"""EpisodicLog — JSONL kısa vadeli runtime hafızası.

Lab her hafta `consolidate(...)` çağrısıyla bu logu okuyup tekrar eden
desenleri ``learning.md`` / ``know_how.md`` / ``shared/lessons``'a transfer
eder. Burada karar verilmez; sadece veri toplanır + özetlenir.

Format: her satır bir JSON object.
    {"agent": "ceo", "ts": "2026-05-08T12:00:00", "tags": [...],
     "body": "...", "kind": "episodic" }
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from price_action.contracts import MemoryEntry
from price_action.logging_config import logger
from price_action.settings import get_settings


def _runtime_dir(agent: str, base: Path | None = None) -> Path:
    base = base or get_settings().memory_dir
    p = (base / agent / "runtime").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


class EpisodicLog:
    """Append-only JSONL log per agent."""

    def __init__(self, agent: str, base_dir: Path | None = None) -> None:
        self.agent = agent
        self.base_dir = base_dir
        self.path: Path = _runtime_dir(agent, base_dir) / "episodic.jsonl"

    # ------------------------------------------------------------------
    # Yazma
    # ------------------------------------------------------------------

    def append(
        self,
        body: str,
        *,
        tags: list[str] | None = None,
        kind: str = "episodic",
        extra: dict[str, Any] | None = None,
        ts: datetime | None = None,
    ) -> None:
        record = {
            "agent": self.agent,
            "ts": (ts or datetime.now(timezone.utc)).isoformat(),
            "kind": kind,
            "tags": list(tags or []),
            "body": body,
        }
        if extra:
            record["extra"] = extra
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def append_entry(self, entry: MemoryEntry) -> None:
        self.append(
            body=entry.body,
            tags=entry.tags,
            kind=entry.type,
            extra={"slug": entry.slug, "confidence": entry.confidence},
            ts=entry.ts,
        )

    # ------------------------------------------------------------------
    # Okuma
    # ------------------------------------------------------------------

    def iter_records(self) -> Iterable[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "episodic.bad_line",
                        extra={"agent": self.agent, "err": str(exc)},
                    )

    # ------------------------------------------------------------------
    # Konsolidasyon
    # ------------------------------------------------------------------

    def consolidate(self, last_n_days: int = 7) -> dict[str, Any]:
        """Son N günün özetini döndürür — Lab haftalık çağırır.

        Output şeması:
        {
            "agent": ...,
            "window_days": 7,
            "total": int,
            "by_kind": {kind: count},
            "top_tags": [(tag, count), ...],
            "samples": [latest few records],
            "frequent_bodies": [(body_prefix, count), ...]
        }
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=last_n_days)
        kinds: Counter[str] = Counter()
        tags: Counter[str] = Counter()
        body_counts: Counter[str] = Counter()
        per_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
        samples: list[dict[str, Any]] = []
        total = 0

        for rec in self.iter_records():
            try:
                ts = datetime.fromisoformat(rec.get("ts", ""))
            except ValueError:
                continue
            # Geriye uyumluluk: eski kayıtlar tz-naive olabilir → UTC varsay.
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
            total += 1
            kind = rec.get("kind", "episodic")
            kinds[kind] += 1
            for t in rec.get("tags", []) or []:
                tags[t] += 1
            body_prefix = (rec.get("body", "") or "")[:80]
            body_counts[body_prefix] += 1
            per_kind[kind].append(rec)
            samples.append(rec)

        samples = samples[-10:]
        return {
            "agent": self.agent,
            "window_days": last_n_days,
            "total": total,
            "by_kind": dict(kinds),
            "top_tags": tags.most_common(10),
            "frequent_bodies": [bc for bc in body_counts.most_common(5) if bc[1] > 1],
            "samples": samples,
        }

    def archive(self, week_label: str) -> Path | None:
        """Mevcut episodic dosyasını `runtime/archive/<week>/` altına taşır."""
        if not self.path.exists():
            return None
        archive_dir = self.path.parent / "archive" / week_label
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / self.path.name
        # Mevcut içeriği kopyala (rename değil; aynı süreçte log devam edebilir)
        target.write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")
        # Aktif logu sıfırla
        self.path.write_text("", encoding="utf-8")
        logger.info(
            "episodic.archived",
            extra={"agent": self.agent, "to": str(target), "week": week_label},
        )
        return target
