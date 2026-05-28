#!/usr/bin/env bash
# FIX 2026-05-28 (audit-F2): launchd log rotation.
#
# logs/launchd/*.log dosyaları launchd tarafından yazılır ama launchd'nin
# kendi rotation mekanizması YOKTUR — unbounded büyür. Bu script:
#   - 50MB+ dosyaları gzip'leyip logs/launchd/archive/ altına taşır
#   - Aktif log'u truncate eder (process devam edebilir, fd hâlâ açık)
#   - 30 günden eski arşivleri siler
#
# logs/app.log ve logs/futures_daemon.log için ZATEN kendi rotation'ları var
# (loguru 200MB, daemon 20MB). Bu script SADECE launchd log'ları için.
#
# Plist: com.priceaction.logrotate (gece 04:00 UTC = 07:00 TR).

set -euo pipefail

ROOT="${PA_PROJECT_ROOT:-$HOME/price-action-bot}"
LAUNCHD_DIR="$ROOT/logs/launchd"
ARCHIVE_DIR="$LAUNCHD_DIR/archive"
THRESHOLD_MB="${PA_LOG_ROTATE_MB:-50}"
RETENTION_DAYS="${PA_LOG_RETENTION_DAYS:-30}"
LOG_FILE="$ROOT/logs/log_rotate.log"

mkdir -p "$ARCHIVE_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

_log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"
}

_log "ROTATE_START: threshold=${THRESHOLD_MB}MB retention=${RETENTION_DAYS}d"

ROTATED=0
for f in "$LAUNCHD_DIR"/*.log; do
  [[ -f "$f" ]] || continue
  base=$(basename "$f")
  size_mb=$(du -m "$f" | awk '{print $1}')
  if [[ "$size_mb" -ge "$THRESHOLD_MB" ]]; then
    stamp=$(date -u +%Y%m%d-%H%M%S)
    target="$ARCHIVE_DIR/${base%.log}.${stamp}.log"
    _log "ROTATE: $base (${size_mb}MB) → ${base%.log}.${stamp}.log.gz"
    # Önce kopyala (fd kopyalanıyor, process etkilenmiyor)
    cp "$f" "$target"
    gzip "$target"
    # Aktif log'u truncate et (process'in fd'sini bozma; >/dev/null with truncate)
    : > "$f"
    ROTATED=$((ROTATED + 1))
  fi
done

_log "ROTATE_DONE: $ROTATED dosya rotate edildi"

# Retention cleanup — N günden eski .gz arşivler
REMOVED=0
while IFS= read -r old; do
  _log "PRUNE: $(basename "$old")"
  rm -f "$old"
  REMOVED=$((REMOVED + 1))
done < <(find "$ARCHIVE_DIR" -maxdepth 1 -name "*.log.gz" -mtime "+${RETENTION_DAYS}" 2>/dev/null || true)

_log "PRUNE_DONE: $REMOVED eski arşiv silindi"

TOTAL_MB=$(du -ms "$ARCHIVE_DIR" 2>/dev/null | awk '{print $1}' || echo "?")
_log "SUMMARY: archive total=${TOTAL_MB}MB"
