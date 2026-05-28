"""data/pool_manifest.json'a göre süresi dolan pool backup'larını sil.

FIX 2026-05-28 (audit-Y10): pool manifest (Y4) backup'lar için
`retention_until` ISO timestamp tutar. Bu script o tarihten geçenleri siler.
Manuel veya weekly cron olarak çalıştırılır.

Usage:
    python scripts/cleanup_pool_backups.py                    # ger silsin
    python scripts/cleanup_pool_backups.py --dry-run          # sadece liste
    python scripts/cleanup_pool_backups.py --manifest <path>  # özel manifest

Çıkış kodu: 0 = OK; 1 = manifest hatası; 2 = silme fail.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "data" / "pool_manifest.json"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str) -> datetime | None:
    """ISO 8601 timestamp parse; tz-aware UTC döner. Hata olursa None."""
    try:
        # "2026-06-22T00:00:00Z" stilini destekle
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Pool manifest yolu (default: {DEFAULT_MANIFEST})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Silme yapma, sadece liste göster",
    )
    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"[ERR] manifest yok: {args.manifest}", file=sys.stderr)
        return 1

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERR] manifest parse fail: {e}", file=sys.stderr)
        return 1

    backups = manifest.get("backups", []) or []
    if not backups:
        print("[INFO] manifest'te backup yok, yapacak iş yok")
        return 0

    now = _now_utc()
    print(f"[INFO] now (UTC) = {now.isoformat()}, backup count = {len(backups)}")

    to_remove: list[tuple[Path, dict]] = []
    keep: list[dict] = []
    for entry in backups:
        path_str = entry.get("path")
        ret_str = entry.get("retention_until")
        if not path_str or not ret_str:
            print(f"[WARN] eksik path/retention_until: {entry}")
            keep.append(entry)
            continue
        ret_dt = _parse_iso(ret_str)
        if ret_dt is None:
            print(f"[WARN] retention_until parse fail: {ret_str}")
            keep.append(entry)
            continue
        full_path = REPO_ROOT / path_str if not Path(path_str).is_absolute() else Path(path_str)
        if now > ret_dt:
            to_remove.append((full_path, entry))
        else:
            keep.append(entry)
            print(f"[KEEP] {path_str} (kalan {(ret_dt - now).days} gün)")

    if not to_remove:
        print(f"[INFO] silinecek backup yok ({len(keep)} korunuyor)")
        return 0

    print(f"[ACTION] {len(to_remove)} backup süresi dolmuş:")
    removed_count = 0
    for path, entry in to_remove:
        ret_str = entry["retention_until"]
        if not path.exists():
            print(f"  [SKIP] {path} (dosya yok)")
            continue
        size_mb = path.stat().st_size / 1024 / 1024
        if args.dry_run:
            print(f"  [DRY-RUN] silinecek: {path} ({size_mb:.1f}MB, expired {ret_str})")
            continue
        try:
            path.unlink()
            print(f"  [REMOVED] {path} ({size_mb:.1f}MB, expired {ret_str})")
            removed_count += 1
        except OSError as e:
            print(f"  [ERR] silme fail {path}: {e}", file=sys.stderr)
            return 2

    if not args.dry_run and removed_count > 0:
        # Manifest'ten silinen entry'leri çıkar
        new_backups = [e for e in backups if e not in [t[1] for t in to_remove]]
        manifest["backups"] = new_backups
        manifest["generated_at"] = now.isoformat()
        try:
            args.manifest.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"[INFO] manifest güncellendi ({len(new_backups)} backup kaldı)")
        except OSError as e:
            print(f"[ERR] manifest yaz fail: {e}", file=sys.stderr)
            return 2

    print(f"[DONE] removed={removed_count}, kept={len(keep)}, dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
