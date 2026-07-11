#!/usr/bin/env bash
# FIX 2026-05-28 (audit-A9): otomatik DuckDB backup — daily rolling 3 capture.
#
# Bu script tüm data/*.duckdb dosyalarını kaynak DB+WAL'i gizli bir stage'e
# kopyalayıp orada CHECKPOINT + tam tablo okumasıyla doğrular. Açık kaynaklar
# normaldir (ingest DB sürekli açıktır); tutarsız kopya en fazla 3 kez yeniden
# denenir ve hiçbiri geçmezse mevcut yayımlanmış backup korunarak fail-closed
# durur. Sonuç data/backups/YYYYMMDD/ altında tek dosyalı, WAL'siz snapshot'tır.
# En yeni 3 backup dizinini tutar. launchd plist ile gece 00:00 TR'de çalışır.
#
# Önceki durum: 814M market.duckdb + 9 diğer .duckdb dosyası HİÇ yedeklenmiyordu.
# Tek nokta hata — corrupt → tüm geçmiş kayıp. Şimdi newest-3 güvence.
#
# Disk maliyeti kaynak DB toplamının yaklaşık 3 katıdır.
#
# Manual usage:
#   bash scripts/backup_duckdb.sh
#   bash scripts/backup_duckdb.sh --dry-run   # Sadece ne yapacağını listele
#
# launchd usage (plist: yerel saatle gece 00:00 TR):
#   launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.priceaction.dbbackup.plist

set -euo pipefail

ROOT="${PA_PROJECT_ROOT:-$HOME/price-action-bot}"
DATA_DIR="$ROOT/data"
BACKUP_ROOT="$DATA_DIR/backups"
# Retention = "tarih adina gore en yeni N backup'i tut" anlaminda. mtime'a
# bakilmaz: find -mtime tam gunleri asagi yuvarladigi icin N=3 iken 4 klasor
# kalabiliyordu. Env: plist PA_BACKUP_RETENTION_DAYS=3.
RETENTION_DAYS="${PA_BACKUP_RETENTION_DAYS:-3}"
SNAPSHOT_RETRIES="${PA_BACKUP_SNAPSHOT_RETRIES:-3}"
DATESTAMP="$(date +%Y%m%d)"
DST_DIR="$BACKUP_ROOT/$DATESTAMP"
LOG_FILE="$ROOT/logs/backup_duckdb.log"
PYTHON_BIN="${PA_PYTHON_BIN:-$ROOT/.venv/bin/python}"
STAGE_DIR="$BACKUP_ROOT/.${DATESTAMP}.stage.$$"
PUBLISH_ROLLBACK_DIR=""
LOCK_DIR="$BACKUP_ROOT/.backup_duckdb.lock"
LOCK_OWNED=0
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

if ! [[ "$RETENTION_DAYS" =~ ^[1-9][0-9]*$ ]]; then
  echo "PA_BACKUP_RETENTION_DAYS pozitif tam sayi olmali: $RETENTION_DAYS" >&2
  exit 2
fi
if ! [[ "$SNAPSHOT_RETRIES" =~ ^[1-9][0-9]*$ ]]; then
  echo "PA_BACKUP_SNAPSHOT_RETRIES pozitif tam sayi olmali: $SNAPSHOT_RETRIES" >&2
  exit 2
fi

mkdir -p "$BACKUP_ROOT"
mkdir -p "$(dirname "$LOG_FILE")"

_log() {
  local msg="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
  echo "$msg" | tee -a "$LOG_FILE"
}

_cleanup_stage() {
  rm -rf "$STAGE_DIR"
  if [[ -n "$PUBLISH_ROLLBACK_DIR" ]] \
    && [[ -d "$PUBLISH_ROLLBACK_DIR" ]] \
    && [[ ! -e "$DST_DIR" ]]; then
    mv "$PUBLISH_ROLLBACK_DIR" "$DST_DIR" 2>/dev/null || true
  fi
  if [[ "$LOCK_OWNED" -eq 1 ]] \
    && [[ -f "$LOCK_DIR/pid" ]] \
    && [[ "$(cat "$LOCK_DIR/pid" 2>/dev/null || true)" == "$$" ]]; then
    rm -rf "$LOCK_DIR"
  fi
}
trap _cleanup_stage EXIT
# Exit through the EXIT trap so a signal can never clean the mutex and then let
# the backup transaction continue without single-writer ownership.
trap 'exit 130' INT
trap 'exit 143' TERM

# macOS ships without flock(1). mkdir is atomic on the local filesystem and
# therefore provides a portable single-writer lease for the complete capture,
# publish and retention transaction. A stale lock is deliberately not removed
# automatically: an operator must first prove that the recorded PID is gone.
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  LOCK_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || echo unknown)"
  _log "BACKUP_ABORT: başka backup çalışıyor veya stale lock var lock=$LOCK_DIR pid=$LOCK_PID"
  exit 3
fi
LOCK_OWNED=1
if ! printf '%s\n' "$$" > "$LOCK_DIR/pid"; then
  _log "BACKUP_ABORT: backup lock sahibi kaydedilemedi lock=$LOCK_DIR"
  exit 3
fi
_log "BACKUP_LOCK_ACQUIRED: lock=$LOCK_DIR pid=$$"

_observe_open_source() {
  local target="$1"
  local holders=""
  local rc=0
  [[ -e "$target" ]] || return 0
  if ! command -v lsof >/dev/null 2>&1; then
    _log "BACKUP_SOURCE_HOLDERS_UNKNOWN: lsof bulunamadı target=$target"
    return 0
  fi
  set +e
  holders=$(lsof -t -- "$target" 2>/dev/null)
  rc=$?
  set -e
  if [[ "$rc" -eq 0 ]]; then
    _log "BACKUP_SOURCE_OPEN: staged copy+verify uygulanacak target=$target pids=${holders//$'\n'/,}"
    return 0
  fi
  if [[ "$rc" -ne 1 ]]; then
    _log "BACKUP_SOURCE_HOLDERS_UNKNOWN: lsof hata rc=$rc target=$target"
  fi
}

_source_pair_fingerprint() {
  local source_db="$1"
  "$PYTHON_BIN" - "$source_db" <<'PY'
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

source = Path(os.path.abspath(sys.argv[1]))


def fingerprint(path: Path) -> dict[str, int | bool]:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return {
            "exists": False,
            "inode": 0,
            "is_regular": False,
            "is_symlink": False,
            "mtime_ns": 0,
            "size": 0,
        }
    return {
        "exists": True,
        "inode": int(info.st_ino),
        "is_regular": stat.S_ISREG(info.st_mode),
        "is_symlink": stat.S_ISLNK(info.st_mode),
        "mtime_ns": int(info.st_mtime_ns),
        "size": int(info.st_size),
    }


pair = {
    "db": fingerprint(source),
    "wal": fingerprint(Path(f"{source}.wal")),
}
db = pair["db"]
wal = pair["wal"]
if not db["exists"] or not db["is_regular"] or db["is_symlink"] or db["size"] <= 0:
    raise SystemExit(f"SOURCE_PAIR_INVALID db={json.dumps(db, sort_keys=True)}")
if wal["exists"] and (not wal["is_regular"] or wal["is_symlink"]):
    raise SystemExit(f"SOURCE_PAIR_INVALID wal={json.dumps(wal, sort_keys=True)}")
print(json.dumps(pair, sort_keys=True, separators=(",", ":")))
PY
}

_verify_source_pair_and_copy_sizes() {
  local source_db="$1"
  local snapshot_db="$2"
  local pre_fingerprint="$3"
  "$PYTHON_BIN" - "$source_db" "$snapshot_db" "$pre_fingerprint" <<'PY'
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

source = Path(os.path.abspath(sys.argv[1]))
snapshot = Path(os.path.abspath(sys.argv[2]))
before = json.loads(sys.argv[3])


def fingerprint(path: Path) -> dict[str, int | bool]:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return {
            "exists": False,
            "inode": 0,
            "is_regular": False,
            "is_symlink": False,
            "mtime_ns": 0,
            "size": 0,
        }
    return {
        "exists": True,
        "inode": int(info.st_ino),
        "is_regular": stat.S_ISREG(info.st_mode),
        "is_symlink": stat.S_ISLNK(info.st_mode),
        "mtime_ns": int(info.st_mtime_ns),
        "size": int(info.st_size),
    }


after = {
    "db": fingerprint(source),
    "wal": fingerprint(Path(f"{source}.wal")),
}
if after != before:
    raise SystemExit(
        "SOURCE_PAIR_CHANGED "
        f"before={json.dumps(before, sort_keys=True)} "
        f"after={json.dumps(after, sort_keys=True)}"
    )

snapshot_db = fingerprint(snapshot)
snapshot_wal = fingerprint(Path(f"{snapshot}.wal"))
if (
    not snapshot_db["exists"]
    or not snapshot_db["is_regular"]
    or snapshot_db["is_symlink"]
    or snapshot_db["size"] != before["db"]["size"]
):
    raise SystemExit(
        "SNAPSHOT_COPY_SIZE_MISMATCH "
        f"artifact=db expected={before['db']['size']} actual={snapshot_db['size']}"
    )
if before["wal"]["exists"]:
    if (
        not snapshot_wal["exists"]
        or not snapshot_wal["is_regular"]
        or snapshot_wal["is_symlink"]
        or snapshot_wal["size"] != before["wal"]["size"]
    ):
        raise SystemExit(
            "SNAPSHOT_COPY_SIZE_MISMATCH "
            f"artifact=wal expected={before['wal']['size']} actual={snapshot_wal['size']}"
        )
elif snapshot_wal["exists"]:
    raise SystemExit(
        "SNAPSHOT_COPY_SIZE_MISMATCH artifact=wal expected=absent actual=present"
    )
PY
}

_snapshot_db() {
  local source_db="$1"
  local snapshot_db="$2"
  local pre_fingerprint=""
  rm -f "$snapshot_db" "$snapshot_db.wal"
  if ! pre_fingerprint=$(_source_pair_fingerprint "$source_db"); then
    return 1
  fi
  cp -p "$source_db" "$snapshot_db"
  if [[ -f "$source_db.wal" ]]; then
    cp -p "$source_db.wal" "$snapshot_db.wal"
  fi
  if ! _verify_source_pair_and_copy_sizes \
    "$source_db" "$snapshot_db" "$pre_fingerprint"; then
    return 1
  fi
  "$PYTHON_BIN" - "$snapshot_db" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

snapshot = Path(sys.argv[1]).resolve()
if not snapshot.is_file() or snapshot.stat().st_size == 0:
    raise SystemExit(f"SNAPSHOT_FAIL missing_or_empty={snapshot}")


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


# The source DB may be held by another process. Never connect to or checkpoint
# it here: DuckDB's cross-process writer lock would make the scheduled backup
# permanently fail for market_ingest.duckdb. Replay only the copied WAL in the
# isolated stage. A torn DB/WAL pair fails here and the shell retries a fresh
# copy; no incomplete stage is ever published.
snapshot_con = duckdb.connect(str(snapshot))
try:
    snapshot_con.execute("CHECKPOINT")
finally:
    snapshot_con.close()

snapshot_wal = Path(f"{snapshot}.wal")
if snapshot_wal.exists() and snapshot_wal.stat().st_size:
    raise SystemExit(f"SNAPSHOT_FAIL non_empty_wal={snapshot_wal}")
snapshot_wal.unlink(missing_ok=True)

# Reopen the result independently and force a read of every base table. This
# proves the published artifact does not depend on the source WAL/connection.
verify = duckdb.connect(str(snapshot), read_only=True)
try:
    catalog = str(verify.execute("SELECT current_database()").fetchone()[0])
    tables = verify.execute(
        """SELECT table_schema, table_name
           FROM information_schema.tables
           WHERE table_catalog = ? AND table_type = 'BASE TABLE'
           ORDER BY table_schema, table_name""",
        [catalog],
    ).fetchall()
    total_rows = 0
    for schema, table in tables:
        qualified = f"{quote_identifier(schema)}.{quote_identifier(table)}"
        total_rows += int(verify.execute(f"SELECT COUNT(*) FROM {qualified}").fetchone()[0])
        verify.execute(f"SELECT * FROM {qualified} LIMIT 0")
finally:
    verify.close()

print(
    f"BACKUP_SNAPSHOT_OK: db={snapshot.name} tables={len(tables)} "
    f"rows_total={total_rows} mode=staged-copy-checkpoint wal=none"
)
PY
}

_log "BACKUP_START: src=$DATA_DIR dst=$DST_DIR retention=${RETENTION_DAYS}d dry_run=$DRY_RUN"

# Disk space check — minimum 5GB free required
FREE_MB=$(df -m "$DATA_DIR" | tail -1 | awk '{print $4}')
if [[ "$FREE_MB" -lt 5000 ]]; then
  _log "BACKUP_ABORT: free disk ${FREE_MB}MB < 5000MB threshold"
  exit 1
fi

# Snapshot'lar önce gizli bir stage dizininde tamamlanır. Sayısal tarih dizini
# yalnız bütün DB'ler ve manifest hazır olduktan sonra yayınlanır.
if [[ "$DRY_RUN" -eq 0 ]]; then
  if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3 || true)"
  fi
  if [[ -z "$PYTHON_BIN" ]] || [[ ! -x "$PYTHON_BIN" ]]; then
    _log "BACKUP_ABORT: çalışabilir Python bulunamadı"
    exit 1
  fi
  rm -rf "$STAGE_DIR"
  mkdir -p "$STAGE_DIR"
fi

COPIED=0
DISCOVERED=0
for db in "$DATA_DIR"/*.duckdb; do
  [[ -f "$db" ]] || continue
  DISCOVERED=$((DISCOVERED + 1))
  base=$(basename "$db")
  size_mb=$(du -m "$db" | awk '{print $1}')
  _log "BACKUP_SNAPSHOT: $base (${size_mb}MB)"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    _observe_open_source "$db"
    _observe_open_source "${db}.wal"
    SNAPSHOT_OK=0
    ATTEMPT=1
    while [[ "$ATTEMPT" -le "$SNAPSHOT_RETRIES" ]]; do
      set +e
      SNAPSHOT_RESULT=$(_snapshot_db "$db" "$STAGE_DIR/$base" 2>&1)
      SNAPSHOT_RC=$?
      set -e
      if [[ "$SNAPSHOT_RC" -eq 0 ]]; then
        SNAPSHOT_OK=1
        break
      fi
      _log "BACKUP_SNAPSHOT_RETRY: db=$base attempt=$ATTEMPT/$SNAPSHOT_RETRIES rc=$SNAPSHOT_RC detail=${SNAPSHOT_RESULT//$'\n'/ }"
      rm -f "$STAGE_DIR/$base" "$STAGE_DIR/$base.wal"
      ATTEMPT=$((ATTEMPT + 1))
      if [[ "$ATTEMPT" -le "$SNAPSHOT_RETRIES" ]]; then
        sleep 1
      fi
    done
    if [[ "$SNAPSHOT_OK" -ne 1 ]]; then
      _log "BACKUP_ABORT: snapshot $SNAPSHOT_RETRIES denemede doğrulanamadı db=$base"
      exit 1
    fi
    _log "$SNAPSHOT_RESULT"
    COPIED=$((COPIED + 1))
  fi
done

if [[ "$DISCOVERED" -eq 0 ]]; then
  _log "BACKUP_ABORT: kaynakta hiç .duckdb bulunamadı; boş backup başarı sayılmaz"
  exit 1
fi

# Destination-side checksum manifest: a later verify/restore drill can prove
# that the bytes have not changed since capture. This is deliberately created
# only after every copy succeeds and is atomically renamed into place.
if [[ "$DRY_RUN" -eq 0 ]]; then
  if ! command -v shasum >/dev/null 2>&1; then
    _log "BACKUP_ABORT: shasum bulunamadı; checksum manifest üretilemedi"
    exit 1
  fi
  MANIFEST="$STAGE_DIR/backup_manifest.sha256"
  MANIFEST_TMP="$STAGE_DIR/.backup_manifest.sha256.$$"
  : > "$MANIFEST_TMP"
  MANIFEST_FILES=0
  for artifact in "$STAGE_DIR"/*.duckdb; do
    [[ -f "$artifact" ]] || continue
    base=$(basename "$artifact")
    (cd "$STAGE_DIR" && shasum -a 256 "$base") >> "$MANIFEST_TMP"
    MANIFEST_FILES=$((MANIFEST_FILES + 1))
  done
  mv -f "$MANIFEST_TMP" "$MANIFEST"
  if [[ "$MANIFEST_FILES" -ne "$COPIED" ]]; then
    _log "BACKUP_ABORT: manifest/snapshot sayısı uyuşmuyor manifest=$MANIFEST_FILES copied=$COPIED"
    exit 1
  fi

  if [[ -e "$DST_DIR" ]] && [[ ! -d "$DST_DIR" ]]; then
    _log "BACKUP_ABORT: hedef bir dizin değil path=$DST_DIR"
    exit 1
  fi
  if [[ -d "$DST_DIR" ]]; then
    PUBLISH_ROLLBACK_DIR="$BACKUP_ROOT/.${DATESTAMP}.previous.$$"
    mv "$DST_DIR" "$PUBLISH_ROLLBACK_DIR"
  fi
  if ! mv "$STAGE_DIR" "$DST_DIR"; then
    _log "BACKUP_ABORT: tamamlanmış stage yayınlanamadı path=$DST_DIR"
    exit 1
  fi
  if [[ -n "$PUBLISH_ROLLBACK_DIR" ]]; then
    rm -rf "$PUBLISH_ROLLBACK_DIR"
    PUBLISH_ROLLBACK_DIR=""
  fi
  _log "BACKUP_MANIFEST: files=$MANIFEST_FILES path=$DST_DIR/backup_manifest.sha256"
  _log "BACKUP_DONE: $COPIED tutarlı snapshot yayınlandı → $DST_DIR"
else
  _log "BACKUP_DRY_RUN_DONE: $DISCOVERED kaynak DB bulundu; dosya yazılmadı"
fi

# Retention cleanup: YYYYMMDD adina gore en yeni N backup dizinini tut.
# LC_ALL=C + ters leksikografik siralama bu ad formatinda kronolojik siradir;
# mtime, saat dilimi ve find'in tam-gun yuvarlamasi sonucu etkilemez.
if [[ "$DRY_RUN" -eq 0 ]]; then
  REMOVED=0
  SEEN=0
  while IFS= read -r backup_name; do
    [[ -n "$backup_name" ]] || continue
    SEEN=$((SEEN + 1))
    if [[ "$SEEN" -le "$RETENTION_DAYS" ]]; then
      continue
    fi
    old_dir="$BACKUP_ROOT/$backup_name"
    _log "BACKUP_PRUNE: silinen $old_dir"
    rm -rf "$old_dir"
    REMOVED=$((REMOVED + 1))
  done < <(
    find "$BACKUP_ROOT" -maxdepth 1 -mindepth 1 -type d -exec basename {} \; 2>/dev/null \
      | LC_ALL=C grep -E '^[0-9]{8}$' \
      | LC_ALL=C sort -r \
      || true
  )
  _log "BACKUP_PRUNE_DONE: $REMOVED eski backup silindi (retention=${RETENTION_DAYS}, policy=newest-N)"
fi

# Toplam backup boyutu raporu
TOTAL_MB=$(du -ms "$BACKUP_ROOT" 2>/dev/null | awk '{print $1}' || echo "?")
_log "BACKUP_SUMMARY: backups total=${TOTAL_MB}MB at $BACKUP_ROOT"
