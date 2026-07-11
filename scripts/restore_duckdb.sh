#!/usr/bin/env bash
# DuckDB restore procedure (fail-closed, staged, rollback-capable).
#
# Usage:
#   scripts/restore_duckdb.sh <db-name> [<backup-date>]
#   scripts/restore_duckdb.sh --list <db-name>
#
# Safety boundary:
#   - The current v15p2 fleet and every known DB user must be booted out first.
#   - lsof must confirm that neither the DB nor its WAL has an open holder.
#   - The backup is copied to a same-filesystem staging path, its WAL is
#     checkpointed, and every table is counted before the atomic replacement.
#   - The previous DB/WAL is retained as .before_restore.<timestamp> for rollback.

set -euo pipefail

ROOT="${PA_PROJECT_ROOT:-$HOME/price-action-bot}"
DATA_DIR="$ROOT/data"
BACKUP_ROOT="$DATA_DIR/backups"
LOG_FILE="$ROOT/logs/restore_duckdb.log"
PYTHON_BIN="${PA_PYTHON_BIN:-$ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi

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
  $0 market.duckdb 20260711     # specific date
  $0 --list market.duckdb       # show available backups
EOF
  exit 1
}

_validate_db_name() {
  local name="$1"
  if [[ ! "$name" =~ ^[A-Za-z0-9._-]+\.duckdb$ ]] || [[ "$name" != "$(basename "$name")" ]]; then
    echo "Geçersiz DB adı: $name (yalnız basename + .duckdb kabul edilir)" >&2
    exit 2
  fi
}

_verify_db() {
  local db_path="$1"
  local mode="$2"
  "$PYTHON_BIN" - "$db_path" "$mode" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

path = Path(sys.argv[1])
mode = sys.argv[2]
if not path.is_file() or path.stat().st_size == 0:
    raise SystemExit(f"DB_VERIFY_FAIL missing_or_empty={path}")

read_only = mode == "read-only"
con = duckdb.connect(str(path), read_only=read_only)
try:
    if not read_only:
        # Replays a copied <db>.wal, then materializes one self-contained DB file.
        con.execute("CHECKPOINT")
    catalog = str(con.execute("SELECT current_database()").fetchone()[0])
    tables = [
        (row[0], row[1])
        for row in con.execute(
            """SELECT table_schema, table_name
               FROM information_schema.tables
               WHERE table_catalog = ? AND table_type = 'BASE TABLE'
               ORDER BY table_schema, table_name""",
            [catalog],
        ).fetchall()
    ]
    total_rows = 0
    for schema, table in tables:
        quoted_schema = '"' + schema.replace('"', '""') + '"'
        quoted_table = '"' + table.replace('"', '""') + '"'
        qualified = f"{quoted_schema}.{quoted_table}"
        # COUNT(*) forces storage-page reads; LIMIT 0 validates the table schema.
        total_rows += int(con.execute(f"SELECT COUNT(*) FROM {qualified}").fetchone()[0])
        con.execute(f"SELECT * FROM {qualified} LIMIT 0")
    print(f"INTEGRITY_OK tables={len(tables)} rows_total={total_rows} mode={mode}")
finally:
    con.close()
PY
}

LIST_MODE=0
if [[ "${1:-}" == "--list" ]]; then
  LIST_MODE=1
  shift
fi
[[ $# -ge 1 ]] || _usage

DB_NAME="$1"
BACKUP_DATE="${2:-}"
_validate_db_name "$DB_NAME"
if [[ -n "$BACKUP_DATE" ]] && [[ ! "$BACKUP_DATE" =~ ^[0-9]{8}$ ]]; then
  echo "Geçersiz backup tarihi: $BACKUP_DATE (YYYYMMDD bekleniyor)" >&2
  exit 2
fi

if [[ "$LIST_MODE" -eq 1 ]]; then
  echo "Available backups for $DB_NAME:"
  find "$BACKUP_ROOT" -mindepth 2 -maxdepth 2 -type f -name "$DB_NAME" 2>/dev/null \
    | LC_ALL=C sort -r \
    | while IFS= read -r file; do
        parent=$(basename "$(dirname "$file")")
        size=$(du -h "$file" | awk '{print $1}')
        manifest="no"
        [[ -f "$(dirname "$file")/backup_manifest.sha256" ]] && manifest="yes"
        echo "  $parent: $size (capture=$parent, checksum_manifest=$manifest)"
      done
  exit 0
fi

ACTIVE_DB="$DATA_DIR/$DB_NAME"
if [[ -n "$BACKUP_DATE" ]]; then
  SRC="$BACKUP_ROOT/$BACKUP_DATE/$DB_NAME"
else
  SRC=$(
    find "$BACKUP_ROOT" -mindepth 2 -maxdepth 2 -type f -name "$DB_NAME" 2>/dev/null \
      | LC_ALL=C sort -r \
      | awk 'NR == 1 { first = $0 } END { print first }'
  )
fi
if [[ -z "${SRC:-}" ]] || [[ ! -f "$SRC" ]]; then
  _log "RESTORE_ABORT: backup bulunamadı db=$DB_NAME date=$BACKUP_DATE"
  echo "Use: $0 --list $DB_NAME" >&2
  exit 2
fi

SRC_DIR=$(dirname "$SRC")
CHECKSUM_MANIFEST="$SRC_DIR/backup_manifest.sha256"
if [[ -f "$CHECKSUM_MANIFEST" ]]; then
  if ! command -v shasum >/dev/null 2>&1; then
    _log "RESTORE_ABORT: checksum manifest var ama shasum bulunamadı"
    exit 5
  fi
  DB_MANIFEST_HASH=$(awk -v name="$DB_NAME" '$2 == name {print $1; exit}' "$CHECKSUM_MANIFEST")
  if [[ -z "$DB_MANIFEST_HASH" ]]; then
    _log "RESTORE_ABORT: manifest artifact içermiyor artifact=$DB_NAME"
    exit 5
  fi
  WAL_NAME="$DB_NAME.wal"
  WAL_MANIFEST_HASH=$(awk -v name="$WAL_NAME" '$2 == name {print $1; exit}' "$CHECKSUM_MANIFEST")
  if [[ -n "$WAL_MANIFEST_HASH" ]] && [[ ! -f "$SRC.wal" ]]; then
    _log "RESTORE_ABORT: manifestte listelenen WAL eksik artifact=$WAL_NAME"
    exit 5
  fi
  if [[ -f "$SRC.wal" ]] && [[ -z "$WAL_MANIFEST_HASH" ]]; then
    _log "RESTORE_ABORT: backup WAL manifestte listelenmemiş artifact=$WAL_NAME"
    exit 5
  fi
  for artifact in "$SRC" ${WAL_MANIFEST_HASH:+"$SRC.wal"}; do
    artifact_name=$(basename "$artifact")
    expected_hash=$(awk -v name="$artifact_name" '$2 == name {print $1; exit}' "$CHECKSUM_MANIFEST")
    actual_hash=$(shasum -a 256 "$artifact" | awk '{print $1}')
    if [[ "$actual_hash" != "$expected_hash" ]]; then
      _log "RESTORE_ABORT: checksum mismatch artifact=$artifact_name"
      exit 5
    fi
  done
  _log "RESTORE_CHECKSUM_OK: db=$DB_NAME manifest=$CHECKSUM_MANIFEST"
else
  _log "RESTORE_WARN: legacy backup checksum manifest yok; staged tam-okuma zorunlu"
fi

# Capture every currently loaded, supported DB user before changing launchd
# state. The restore transaction boots out exactly that set and bootstraps
# exactly the same label/plist pairs afterwards. Retired/v14 jobs are never
# restarted; finding one loaded aborts the restore before any active DB change.
ALLOWED_RESTART_LABELS=(
  com.priceaction.ceo
  com.priceaction.ingest15m
  com.priceaction.liqcollector
  com.priceaction.dashboard
  com.priceaction.dbbackup
  com.priceaction.forward_sim
  com.priceaction.multitf_paper
  com.priceaction.e13_shadow_tick
  com.priceaction.futures_v15p2
)
PROHIBITED_LABELS=(
  com.priceaction.futures_v14
  com.priceaction.futures15m
  com.priceaction.futures15m_v11
  com.priceaction.futures15m_v63
  com.priceaction.futures5m
)
REQUIRED_STOP_LABELS=("${ALLOWED_RESTART_LABELS[@]}" "${PROHIBITED_LABELS[@]}")
PRE_ACTIVE_LABELS=()
PRE_ACTIVE_PLISTS=()
STOPPED_LABELS=()
STOPPED_PLISTS=()
RESTART_ATTEMPTED=0
STAGE=""

if ! command -v launchctl >/dev/null 2>&1; then
  _log "RESTORE_ABORT: launchctl bulunamadı; servis durumu doğrulanamıyor"
  exit 4
fi

if ! command -v lsof >/dev/null 2>&1; then
  _log "RESTORE_ABORT: lsof bulunamadı; açık dosya sahipliği doğrulanamıyor"
  exit 4
fi

_assert_required_jobs_stopped() {
  local label=""
  local loaded_labels=()
  for label in "${REQUIRED_STOP_LABELS[@]}"; do
    if launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
      loaded_labels+=("$label")
    fi
  done
  if [[ "${#loaded_labels[@]}" -gt 0 ]]; then
    _log "RESTORE_ABORT: bootout edilmemiş servisler=${loaded_labels[*]}"
    echo "Restore öncesi aşağıdaki job'ları bootout et:" >&2
    for label in "${loaded_labels[@]}"; do
      echo "  launchctl bootout gui/$(id -u)/$label" >&2
    done
    return 1
  fi
}

_capture_pre_active_jobs() {
  local label=""
  local launch_state=""
  local plist_path=""
  for label in "${PROHIBITED_LABELS[@]}"; do
    if launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
      _log "RESTORE_ABORT: emekli/v14 servis loaded; otomatik restart yasak label=$label"
      echo "Önce manuel bootout et ve neden loaded olduğunu incele: $label" >&2
      return 1
    fi
  done
  for label in "${ALLOWED_RESTART_LABELS[@]}"; do
    if ! launch_state=$(launchctl print "gui/$(id -u)/$label" 2>/dev/null); then
      continue
    fi
    plist_path=$(
      printf '%s\n' "$launch_state" \
        | awk '/^[[:space:]]*path = / {sub(/^[[:space:]]*path = /, ""); print; exit}'
    )
    if [[ -z "$plist_path" ]] || [[ ! -f "$plist_path" ]]; then
      _log "RESTORE_ABORT: loaded servisin plist yolu eksik/geçersiz label=$label path=${plist_path:-missing}"
      return 1
    fi
    PRE_ACTIVE_LABELS+=("$label")
    PRE_ACTIVE_PLISTS+=("$plist_path")
  done
  if [[ "${#PRE_ACTIVE_LABELS[@]}" -eq 0 ]]; then
    _log "RESTORE_PRE_ACTIVE_NONE: restart edilecek loaded DB kullanıcısı yok"
  else
    _log "RESTORE_PRE_ACTIVE_CAPTURED: labels=${PRE_ACTIVE_LABELS[*]}"
  fi
}

_restart_stopped_jobs() {
  local index=0
  local label=""
  local plist_path=""
  local failures=0
  RESTART_ATTEMPTED=1
  if [[ "${#STOPPED_LABELS[@]}" -eq 0 ]]; then
    _log "RESTORE_RESTART_NONE: restore tarafından bootout edilen servis yok"
    return 0
  fi
  for index in "${!STOPPED_LABELS[@]}"; do
    label="${STOPPED_LABELS[$index]}"
    plist_path="${STOPPED_PLISTS[$index]}"
    if [[ ! -f "$plist_path" ]]; then
      _log "RESTORE_RESTART_FAIL: plist kayıp label=$label path=$plist_path"
      failures=$((failures + 1))
      continue
    fi
    if ! launchctl bootstrap "gui/$(id -u)" "$plist_path"; then
      _log "RESTORE_RESTART_FAIL: bootstrap başarısız label=$label path=$plist_path"
      failures=$((failures + 1))
      continue
    fi
    if ! launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
      _log "RESTORE_RESTART_FAIL: bootstrap sonrası label doğrulanamadı label=$label"
      failures=$((failures + 1))
      continue
    fi
    _log "RESTORE_RESTART_OK: label=$label path=$plist_path"
  done
  [[ "$failures" -eq 0 ]]
}

_restore_exit_trap() {
  local original_rc=$?
  local restart_rc=0
  trap - EXIT INT TERM
  if [[ -n "$STAGE" ]]; then
    rm -f "$STAGE" "$STAGE.wal"
  fi
  if [[ "$RESTART_ATTEMPTED" -eq 0 ]] && [[ "${#STOPPED_LABELS[@]}" -gt 0 ]]; then
    _restart_stopped_jobs || restart_rc=$?
    if [[ "$restart_rc" -ne 0 ]]; then
      _log "RESTORE_RESTART_INCOMPLETE: original_rc=$original_rc"
      if [[ "$original_rc" -eq 0 ]]; then
        original_rc=8
      fi
    fi
  fi
  exit "$original_rc"
}
trap _restore_exit_trap EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

_assert_no_open_holders() {
  local target=""
  local holders=""
  local lsof_rc=0
  for target in "$ACTIVE_DB" "$ACTIVE_DB.wal"; do
    [[ -e "$target" ]] || continue
    set +e
    holders=$(lsof -t -- "$target" 2>/dev/null)
    lsof_rc=$?
    set -e
    if [[ "$lsof_rc" -eq 0 ]]; then
      _log "RESTORE_ABORT: açık dosya target=$target pids=${holders//$'\n'/,}"
      echo "DB/WAL hâlâ bir proses tarafından açık. Restore yapılmadı." >&2
      return 1
    fi
    if [[ "$lsof_rc" -ne 1 ]]; then
      _log "RESTORE_ABORT: lsof hata rc=$lsof_rc target=$target"
      return 1
    fi
  done
}

if ! _capture_pre_active_jobs; then
  exit 4
fi

echo ""
echo "⚠️  $DB_NAME restore edilecek. Captured DB kullanıcıları exact set olarak bootout/restart edilecek."
if [[ "${#PRE_ACTIVE_LABELS[@]}" -gt 0 ]]; then
  printf 'Captured loaded labels:\n'
  printf '  %s\n' "${PRE_ACTIVE_LABELS[@]}"
else
  echo "Captured loaded labels: none"
fi
read -r -p "Devam etmek için exact 'yes' yaz: " confirm
if [[ "$confirm" != "yes" ]]; then
  _log "RESTORE_ABORT: kullanıcı exact yes vermedi"
  exit 3
fi

# Exact captured set is stopped only after explicit confirmation. If a partial
# bootout fails, the EXIT trap restores only the labels already stopped.
for index in "${!PRE_ACTIVE_LABELS[@]}"; do
  label="${PRE_ACTIVE_LABELS[$index]}"
  plist_path="${PRE_ACTIVE_PLISTS[$index]}"
  if ! launchctl bootout "gui/$(id -u)/$label"; then
    _log "RESTORE_ABORT: bootout başarısız label=$label"
    exit 4
  fi
  STOPPED_LABELS+=("$label")
  STOPPED_PLISTS+=("$plist_path")
  _log "RESTORE_BOOTOUT_OK: label=$label"
done

# Prompt açıkken yeni/retired bir job yüklenmiş veya ad-hoc proses DB'yi açmış
# olabilir. Bootout sonrası ve replace sınırında aynı fail-closed kapılar çalışır.
if ! _assert_required_jobs_stopped; then
  exit 4
fi
if ! _assert_no_open_holders; then
  exit 4
fi

STAMP=$(date -u +%Y%m%d-%H%M%S)
STAGE="$DATA_DIR/.${DB_NAME}.restore.${STAMP}.$$.tmp"
BACKUP_OLD=""

_rollback() {
  local reason="$1"
  _log "RESTORE_ROLLBACK_START: reason=$reason"
  if [[ -n "$BACKUP_OLD" ]] && [[ -f "$BACKUP_OLD" ]]; then
    cp -p "$BACKUP_OLD" "$ACTIVE_DB"
    rm -f "$ACTIVE_DB.wal"
    [[ -f "$BACKUP_OLD.wal" ]] && cp -p "$BACKUP_OLD.wal" "$ACTIVE_DB.wal"
    _log "RESTORE_ROLLBACK_DONE: restored=$BACKUP_OLD"
  else
    rm -f "$ACTIVE_DB" "$ACTIVE_DB.wal"
    _log "RESTORE_ROLLBACK_DONE: active DB restore öncesinde yoktu; yeni dosya kaldırıldı"
  fi
}

_log "RESTORE_STAGE_START: src=$SRC stage=$STAGE"
cp -p "$SRC" "$STAGE"
[[ -f "$SRC.wal" ]] && cp -p "$SRC.wal" "$STAGE.wal"

set +e
STAGE_VERIFY=$(_verify_db "$STAGE" "checkpoint" 2>&1)
VERIFY_RC=$?
set -e
if [[ "$VERIFY_RC" -ne 0 ]]; then
  _log "RESTORE_ABORT: staged integrity fail rc=$VERIFY_RC detail=${STAGE_VERIFY//$'\n'/ }"
  exit 5
fi
rm -f "$STAGE.wal"
_log "$STAGE_VERIFY"

# Staged tam-okuma uzun sürebilir. Aktif DB'nin safety-copy/replace sınırında
# servis ve gerçek file-holder kontrollerini son kez yaparak TOCTOU penceresini
# daralt. Bilinmeyen bir DB kullanıcısı da lsof tarafından yakalanır.
if ! _assert_required_jobs_stopped; then
  exit 4
fi
if ! _assert_no_open_holders; then
  exit 4
fi

if [[ -f "$ACTIVE_DB" ]]; then
  BACKUP_OLD="$ACTIVE_DB.before_restore.$STAMP"
  cp -p "$ACTIVE_DB" "$BACKUP_OLD"
  [[ -f "$ACTIVE_DB.wal" ]] && cp -p "$ACTIVE_DB.wal" "$BACKUP_OLD.wal"
  _log "RESTORE_SAFETY_COPY: active=$ACTIVE_DB rollback=$BACKUP_OLD"
fi

# The staged DB is on DATA_DIR, so rename is an atomic same-filesystem replace.
# Remove any old active WAL first; the staged WAL was already checkpointed.
rm -f "$ACTIVE_DB.wal"
if ! mv -f "$STAGE" "$ACTIVE_DB"; then
  _rollback "atomic replace failed"
  exit 6
fi

set +e
FINAL_VERIFY=$(_verify_db "$ACTIVE_DB" "read-only" 2>&1)
FINAL_RC=$?
set -e
if [[ "$FINAL_RC" -ne 0 ]]; then
  _log "RESTORE_POSTCHECK_FAIL: rc=$FINAL_RC detail=${FINAL_VERIFY//$'\n'/ }"
  _rollback "post-replace integrity failed"
  exit 7
fi
_log "$FINAL_VERIFY"
_log "RESTORE_DONE: src=$SRC dst=$ACTIVE_DB"

# Restore exactly the supported labels captured as loaded before the
# transaction. Inactive helpers (notably E13/forward/multitf) are never started
# merely because a plist happens to exist on disk.
if ! _restart_stopped_jobs; then
  _log "RESTORE_ABORT: DB restore tamamlandı fakat pre-active servis seti eksik restart edildi"
  exit 8
fi

if [[ -n "$BACKUP_OLD" ]]; then
  ROLLBACK_NOTE="cp '$BACKUP_OLD' '$ACTIVE_DB' (job'lar bootout iken)"
else
  ROLLBACK_NOTE="Aktif DB restore öncesinde yoktu; geri dönüş için '$ACTIVE_DB' kaldırılır."
fi

cat <<EOF

✅ Restore ve tam tablo okuma doğrulaması tamamlandı.

Restore öncesinde loaded olarak yakalanan destekli label'ların exact seti,
capture edilen plist yollarıyla yeniden bootstrap edildi. İnaktif helper'lar
başlatılmadı; emekli/v14 label'lar hiçbir koşulda restart edilmedi.

Rollback notu:
  $ROLLBACK_NOTE
EOF
