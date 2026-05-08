"""knowledge/books/ klasorundeki kitap ozetlerini RAG corpus'a ingest et.

Bu script `gather_items` tarafindan okunmayan `books/*.md` dosyalarini
direkt IngestItem'a cevirip `ingest_items()` pipeline'indan gecirir.

Calistirma:
    PYTHONPATH=src python scripts/ingest_books.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """`---\n...\n---\n` YAML bloku varsa cikar; (meta, body) dondur."""
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    try:
        import yaml
        meta = yaml.safe_load(m.group(1)) or {}
    except Exception:
        meta = {}
    return meta, m.group(2)


def main() -> int:
    from price_action.rag.ingest import IngestItem, ingest_items, load_seeds

    books_dir = ROOT / "knowledge" / "books"
    files = sorted(books_dir.glob("*.md"))
    if not files:
        print(f"[ingest_books] {books_dir} bos.", file=sys.stderr)
        return 1

    seeds = load_seeds()
    items: list[IngestItem] = []
    for fp in files:
        text = fp.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        wc = len(body.split())
        if wc < 500:
            print(f"  SKIP {fp.name}: yalnizca {wc} kelime (min 500)")
            continue
        sid = meta.get("source_id") or fp.stem
        items.append(
            IngestItem(
                source_id=sid,
                source_type="book",
                url=f"file://{fp.as_posix()}",
                title=str(meta.get("title") or fp.stem),
                text=body,
                author=str(meta.get("author") or ""),
                published_date=str(meta.get("ingested_date") or ""),
                quality=int(meta.get("quality") or 5),
                extra_tags=list(meta.get("topic_tags") or []),
            )
        )
        print(f"  OK   {fp.name}: {wc} kelime")

    if not items:
        print("[ingest_books] Hicbir kitap eklenmedi.", file=sys.stderr)
        return 1

    stats = ingest_items(items, seeds)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
