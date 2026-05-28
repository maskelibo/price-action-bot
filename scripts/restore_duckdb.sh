#!/usr/bin/env bash
# FIX 2026-05-28 (audit-F4): DuckDB restore-from-backup procedure.
#
# Kullanım:
#   scripts/restore_duckdb.sh <db-name> [<backup-date>]
#
# Örnekler:
#   scripts/restore_duckdb.sh market.duckdb
#       # En son backup'tan market.duckdb'yi restore et
#   scripts/restore_duckdb.sh market.duckdb 20260527
#       # Belirli tarihteki backup'tan restore
#   scripts/restore_duckdb.sh --list market.duckdb
#       # Mevcut backup'ları listele
#
# Akış:
#   1) Aktif bot'ları kontrol et (futures15m, ceo, futures5m varsa STOP gerekiyor)
#   2) Mevcut DB'yi `.before_restore.<ts>` olarak yedekle (geri dönüş için)
#   3) Backup'tan kopyala
#   4) DuckDB integrity check (tabloları listele, count(*) bir tabloya)
#   5) Bot'ları restart et (manuel — script önerir, kendi yapmaz)
#
# Önceki durum: Backup vardı (A9 daily cron), restore prosedürü YOKTU.
# Tek nokta hata: DB corrupt → ne yapacağı kafadalardı.

set -euo pipefail

ROOT="${PA_PROJECT_ROOT:-$HOME/price-action-bot}"
DATA_DIR="$ROOT/data"
BACKUP_ROOT="$DATA_DIR/backups"
LOG_FILE="$ROOT/logs/restore_duckdb.log"

mkdir -p "$(dirname "$LOG_FILE")"

_log() {
  local msg="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
  echo "$msg" | tee -a "$LOG_FILE"
}

_usage() {
  cat <<EOF
Usage: $0 <db-name> [<backup-date>]
       $0 --list <db-name>

Examples:
  $0 market.duckdb              # latest backup
  $0 market.duckdb 20260527     # specific date
  $0 --list market.duckdb       # show available backups

DB names: market.duckdb, futures_journal.duckdb, idempotency.duckdb, ...
EOF
  exit 1
}

[[ $# -ge 1 ]] || _usage

LIST_MODE=0
if [[ "$1" == "--list" ]]; then
  LIST_MODE=1
  shift
  [[ $# -ge 1 ]] || _usage
fi

DB_NAME="$1"
BACKUP_DATE="${2:-}"

# List mode — sadece mevcut backup'ları göster
if [[ "$LIST_MODE" -eq 1 ]]; then
  echo "Available backups for $DB_NAME:"
  find "$BACKUP_ROOT" -maxdepth 2 -name "$DB_NAME" -type f 2>/dev/null | sort -r | while read -r f; do
    parent=$(basename "$(dirname "$f")")
    size=$(du -h "$f" | awk '{print $1}')
    mtime=$(stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$f" 2>/dev/null || stat -c '%y' "$f" 2>/dev/null)
    echo "  $parent: $size ($mtime)"
  done
  exit 0
fi

ACTIVE_DB="$DATA_DIR/$DB_NAME"

# Backup seç
if [[ -n "$BACKUP_DATE" ]]; then
  SRC="$BACKUP_ROOT/$BACKUP_DATE/$DB_NAME"
else
  # En son backup
  SRC=$(find "$BACKUP_ROOT" -maxdepth 2 -name "$DB_NAME" -type f 2>/dev/null | sort -r | head -1)
fi

if [[ -z "$SRC" ]] || [[ ! -f "$SRC" ]]; then
  _log "ERR: backup bulunamadı: $DB_NAME (date=$BACKUP_DATE)"
  echo "Use: $0 --list $DB_NAME" >&2
  exit 2
fi

_log "RESTORE_START: src=$SRC dst=$ACTIVE_DB"

# 1) Aktif bot'ları kontrol et
echo ""
echo "⚠️  UYARI: market.duckdb / idempotency.duckdb / pyramid_store gibi DB'leri"
echo "    aktif bot okurken/yazarken restore etmek ÇOK TEHLİKELİ."
echo ""
echo "Aktif bot'lar (launchctl):"
launchctl list 2>&1 | grep priceaction || echo "  (boş)"
echo ""
read -p "Bot'ları DURDURDUN mu? (yes/no): " confirm
if [[ "$confirm" != "yes" ]]; then
  _log "ABORT: kullanıcı bot stop onayı vermedi"
  echo "İptal. Önce bot'ları durdurun:"
  echo "  launchctl bootout gui/\$(id -u)/com.priceaction.futures15m"
  echo "  launchctl bootout gui/\$(id -u)/com.priceaction.ceo"
  exit 3
fi

# 2) Mevcut DB'yi yedekle (geri dönüş için)
if [[ -f "$ACTIVE_DB" ]]; then
  STAMP=$(date -u +%Y%m%d-%H%M%S)
  BACKUP_OLD="$ACTIVE_DB.before_restore.$STAMP"
  cp "$ACTIVE_DB" "$BACKUP_OLD"
  # WAL dosyası varsa onu da
  [[ -f "$ACTIVE_DB.wal" ]] && cp "$ACTIVE_DB.wal" "$BACKUP_OLD.wal"
  _log "SAFETY_COPY: mevcut DB → $BACKUP_OLD"
fi

# 3) Backup'tan kopyala
cp "$SRC" "$ACTIVE_DB"
# WAL dosyası backup'ta varsa onu da
[[ -f "$SRC.wal" ]] && cp "$SRC.wal" "$ACTIVE_DB.wal"
_log "RESTORE_COPY: $SRC → $ACTIVE_DB"

# 4) Integrity check
if command -v duckdb &> /dev/null; then
  echo ""
  _log "INTEGRITY_CHECK: tablolar listeleniyor..."
  TABLES=$(duckdb "$ACTIVE_DB" -c ".tables" 2>&1 | head -20)
  echo "$TABLES" | tee -a "$LOG_FILE"
else
  # Python ile fallback
  PYTHONPATH="$ROOT/src" python3 -c "
import duckdb
con = duckdb.connect('$ACTIVE_DB', read_only=True)
tables = con.execute('SELECT table_name FROM information_schema.tables WHERE table_schema=\\'main\\'').fetchall()
print(f'Tables: {len(tables)}')
for t in tables[:10]:
    print(f'  - {t[0]}')
con.close()
" 2>&1 | tee -a "$LOG_FILE"
fi

_log "RESTORE_DONE"

# 5) Bot restart önerisi
cat <<EOF

✅ Restore tamamlandı.

Şimdi bot'ları geri al:
  launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/com.priceaction.futures15m.plist
  launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/com.priceaction.ceo.plist

Geri dönüş gerekirse (restore yanlış gittiyse):
  cp $BACKUP_OLD $ACTIVE_DB
EOF
