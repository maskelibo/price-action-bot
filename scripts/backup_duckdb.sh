#!/usr/bin/env bash
# FIX 2026-05-28 (audit-A9): otomatik DuckDB backup — daily rolling 7 gün.
#
# Bu script tüm data/*.duckdb dosyalarını data/backups/YYYYMMDD/ altına kopyalar.
# 7 günden eski backup dizinlerini siler. launchd plist ile gece 03:00 TR'de
# çalıştırılması öngörülüyor (ops/launchd/com.priceaction.dbbackup.plist).
#
# Önceki durum: 814M market.duckdb + 9 diğer .duckdb dosyası HİÇ yedeklenmiyordu.
# Tek nokta hata — corrupt → tüm geçmiş kayıp. Şimdi 7-day rolling güvence.
#
# Disk maliyeti: ~9 GB rolling (1.3 GB × 7 gün).
#
# Manual usage:
#   bash scripts/backup_duckdb.sh
#   bash scripts/backup_duckdb.sh --dry-run   # Sadece ne yapacağını listele
#
# launchd usage:
#   launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.priceaction.dbbackup.plist

set -euo pipefail

ROOT="${PA_PROJECT_ROOT:-$HOME/price-action-bot}"
DATA_DIR="$ROOT/data"
BACKUP_ROOT="$DATA_DIR/backups"
RETENTION_DAYS="${PA_BACKUP_RETENTION_DAYS:-7}"
DATESTAMP="$(date +%Y%m%d)"
DST_DIR="$BACKUP_ROOT/$DATESTAMP"
LOG_FILE="$ROOT/logs/backup_duckdb.log"
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$BACKUP_ROOT"
mkdir -p "$(dirname "$LOG_FILE")"

_log() {
  local msg="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
  echo "$msg" | tee -a "$LOG_FILE"
}

_log "BACKUP_START: src=$DATA_DIR dst=$DST_DIR retention=${RETENTION_DAYS}d dry_run=$DRY_RUN"

# Disk space check — minimum 5GB free required
FREE_MB=$(df -m "$DATA_DIR" | tail -1 | awk '{print $4}')
if [[ "$FREE_MB" -lt 5000 ]]; then
  _log "BACKUP_ABORT: free disk ${FREE_MB}MB < 5000MB threshold"
  exit 1
fi

# Yedek dizinini oluştur
if [[ "$DRY_RUN" -eq 0 ]]; then
  mkdir -p "$DST_DIR"
fi

# Tüm .duckdb dosyalarını kopyala (WAL dosyalarını dahil et — replay için gerekli)
COPIED=0
for db in "$DATA_DIR"/*.duckdb; do
  [[ -f "$db" ]] || continue
  base=$(basename "$db")
  size_mb=$(du -m "$db" | awk '{print $1}')
  _log "BACKUP_COPY: $base (${size_mb}MB)"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    cp -p "$db" "$DST_DIR/$base"
    # WAL dosyası varsa kopyala (durability için)
    if [[ -f "${db}.wal" ]]; then
      cp -p "${db}.wal" "$DST_DIR/${base}.wal"
    fi
    COPIED=$((COPIED + 1))
  fi
done

_log "BACKUP_DONE: $COPIED dosya kopyalandı → $DST_DIR"

# Retention cleanup: N günden eski backup dizinlerini sil
if [[ "$DRY_RUN" -eq 0 ]]; then
  REMOVED=0
  while IFS= read -r old_dir; do
    _log "BACKUP_PRUNE: silinen $old_dir"
    rm -rf "$old_dir"
    REMOVED=$((REMOVED + 1))
  done < <(find "$BACKUP_ROOT" -maxdepth 1 -mindepth 1 -type d -mtime "+${RETENTION_DAYS}" 2>/dev/null || true)
  _log "BACKUP_PRUNE_DONE: $REMOVED eski backup silindi (retention=${RETENTION_DAYS}d)"
fi

# Toplam backup boyutu raporu
TOTAL_MB=$(du -ms "$BACKUP_ROOT" 2>/dev/null | awk '{print $1}' || echo "?")
_log "BACKUP_SUMMARY: backups total=${TOTAL_MB}MB at $BACKUP_ROOT"
