#!/usr/bin/env python3
"""migrate_hypotheses — eski Faz pre-1.5 hipotez format → yeni protokol format.

M2 FIX (cosmic-cuddling-cocke.md): `memory/researcher/hypotheses/` altındaki
66 eski hipotez `type: hypothesis` field kullanıyor (Faz 1.5'ten önce).
Yeni `list_recent_docs(doc_type='hypothesis')` `doc_type:` field arıyor →
eski hipotezler görünmez.

Bu script eski hipotezlerin frontmatter'ına `doc_type: hypothesis` field
ekler (geriye dönük dual format — `type` + `doc_type` ikisi de bulunur,
hiçbir tooling kırılmaz).

Idempotent: zaten `doc_type` varsa atla.

Usage
-----
    cd ~/price-action-bot
    PYTHONPATH=src .venv/bin/python scripts/migrate_hypotheses.py [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
TYPE_HYPOTHESIS_RE = re.compile(r"^type:\s*hypothesis\s*$", re.MULTILINE)
DOC_TYPE_RE = re.compile(r"^doc_type:\s*\w+", re.MULTILINE)


def migrate_file(path: Path, *, dry_run: bool) -> str:
    """Tek dosyayı migrate et. Return: 'migrated' | 'skipped' | 'no_frontmatter'."""
    content = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(content)
    if not m:
        return "no_frontmatter"
    fm = m.group(1)

    # Zaten doc_type varsa atla
    if DOC_TYPE_RE.search(fm):
        return "skipped"

    # Sadece type: hypothesis olanları migrate et
    if not TYPE_HYPOTHESIS_RE.search(fm):
        return "skipped"

    # Frontmatter sonuna doc_type: hypothesis ekle
    new_fm = fm.rstrip() + "\ndoc_type: hypothesis\nagent_id: researcher"
    new_content = "---\n" + new_fm + "\n---\n" + content[m.end():]

    if not dry_run:
        path.write_text(new_content, encoding="utf-8")
    return "migrated"


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate old hypothesis frontmatter")
    parser.add_argument("--dry-run", action="store_true", help="Sadece raporla, yazma")
    args = parser.parse_args()

    hyp_dir = ROOT / "memory" / "researcher" / "hypotheses"
    if not hyp_dir.exists():
        print(f"ERROR: {hyp_dir} yok")
        return 1

    stats = {"migrated": 0, "skipped": 0, "no_frontmatter": 0, "error": 0}
    files = sorted(hyp_dir.glob("*.md"))
    print(f"Migration: {len(files)} dosya bulundu ({hyp_dir})")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print()

    for f in files:
        try:
            result = migrate_file(f, dry_run=args.dry_run)
            stats[result] += 1
            if result == "migrated":
                print(f"  + {f.name}")
            elif result == "no_frontmatter":
                print(f"  ! {f.name} — frontmatter yok")
        except Exception as e:
            stats["error"] += 1
            print(f"  ✗ {f.name} — ERROR: {e}")

    print()
    print(f"=== ÖZET ===")
    print(f"  Migrated: {stats['migrated']}")
    print(f"  Skipped (zaten doc_type var veya type!=hypothesis): {stats['skipped']}")
    print(f"  No frontmatter: {stats['no_frontmatter']}")
    print(f"  Errors: {stats['error']}")

    if args.dry_run:
        print()
        print("DRY-RUN — değişiklik yapılmadı. Production için: --no-dry-run ile çalıştır.")
    return 0 if stats["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
