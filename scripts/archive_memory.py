#!/usr/bin/env python3
"""archive_memory — quarterly memory archive (M4 FIX).

`memory/researcher/hypotheses/` ve diğer growing dirs zamanla şişer:
- 66 dosya now → ~150/yıl → 3 yıl sonra 400+ single dir
- Filesystem performance degrades, glob() yavaş

Bu script üç aydan eski dosyaları `memory/archive/YYYY-QN/<agent>/<subdir>/`'a
taşır. Idempotent — zaten archive'da olan dosya yeniden taşınmaz.

Cron'a eklenebilir (her ay 1'i, 04:00):
    0 4 1 * * /Users/peyman/price-action-bot/.venv/bin/python \
        /Users/peyman/price-action-bot/scripts/archive_memory.py

Usage
-----
    cd ~/price-action-bot
    .venv/bin/python scripts/archive_memory.py [--dry-run] [--days N]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MEMORY = ROOT / "memory"
ARCHIVE_ROOT = MEMORY / "archive"

# Bu dizinler taranır
GROWING_DIRS = [
    "researcher/hypotheses",
    # Geleceğe yönelik (Faz 5+ eklenebilir):
    # "researcher/runtime",
    # "lab_scientist/runtime",
]


def _quarter_label(dt: datetime) -> str:
    """2026-Q2 gibi label üret."""
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


def archive_dir(rel_dir: str, *, days: int, dry_run: bool) -> dict:
    """`memory/<rel_dir>/` altındaki days+ eski dosyaları archive et."""
    src_dir = MEMORY / rel_dir
    if not src_dir.exists():
        return {"status": "no_dir", "n_archived": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ts = cutoff.timestamp()

    n_archived = 0
    for f in src_dir.iterdir():
        if not f.is_file():
            continue
        try:
            mtime = f.stat().st_mtime
            if mtime >= cutoff_ts:
                continue  # taze, atla

            file_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
            quarter = _quarter_label(file_dt)
            target_dir = ARCHIVE_ROOT / quarter / rel_dir
            target = target_dir / f.name

            if dry_run:
                print(f"  [DRY] {f.relative_to(ROOT)} → {target.relative_to(ROOT)}")
            else:
                target_dir.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    # Idempotent — zaten taşınmış, kaynağı sadece sil
                    f.unlink()
                else:
                    shutil.move(str(f), str(target))
                print(f"  archived: {f.name} → {quarter}/{rel_dir}/")
            n_archived += 1
        except Exception as e:
            print(f"  ✗ {f.name} — ERROR: {e}")

    return {"status": "ok", "n_archived": n_archived}


def main() -> int:
    parser = argparse.ArgumentParser(description="Memory quarterly archive")
    parser.add_argument("--days", type=int, default=90, help="Eski sayılan gün eşiği (default 90)")
    parser.add_argument("--dry-run", action="store_true", help="Sadece raporla")
    args = parser.parse_args()

    print(f"=== archive_memory ===")
    print(f"  cutoff_days: {args.days}")
    print(f"  mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print()

    total_archived = 0
    for rel_dir in GROWING_DIRS:
        print(f"-- {rel_dir} --")
        result = archive_dir(rel_dir, days=args.days, dry_run=args.dry_run)
        total_archived += result["n_archived"]
        print(f"  → {result['n_archived']} dosya")

    print()
    print(f"=== ÖZET: {total_archived} dosya archived ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
