#!/bin/bash
# Price Action log rotation — cron'dan günde 1 kez (03:00).
#
# newsyslog'un ötesinde: 30g+ gzip, 180g+ delete (newsyslog count-based, age-based değil)
# Crontab entry: 0 3 * * * /Users/peyman/price-action-bot/ops/logrotate/rotate_logs.sh

set -euo pipefail

LOGS_DIR="/Users/peyman/price-action-bot/logs"
ARCHIVE_DIR="${LOGS_DIR}/archive"
RETENTION_DAYS_GZIP=30   # 30g üstü gzip
RETENTION_DAYS_DELETE=180  # 180g üstü sil

mkdir -p "${ARCHIVE_DIR}"

# 1. 30+ gün eski .log dosyalarını gzip'le ve archive'a taşı
find "${LOGS_DIR}" -maxdepth 2 -type f -name "*.log" -mtime "+${RETENTION_DAYS_GZIP}" | while read -r logfile; do
    [ -f "$logfile" ] || continue
    base=$(basename "$logfile" .log)
    year_month=$(date -r "$logfile" "+%Y/%m")
    target_dir="${ARCHIVE_DIR}/${year_month}"
    mkdir -p "$target_dir"
    gzip -c "$logfile" > "${target_dir}/${base}-$(date -r "$logfile" "+%Y%m%d").log.gz"
    # Orijinal log'u truncate et (servis yazmaya devam etsin)
    : > "$logfile"
    echo "[$(date "+%Y-%m-%d %H:%M:%S")] rotated: ${logfile} → ${target_dir}/${base}-*.log.gz"
done

# 2. 180+ gün eski archive dosyalarını sil
find "${ARCHIVE_DIR}" -type f -name "*.log.gz" -mtime "+${RETENTION_DAYS_DELETE}" -delete -print | while read -r deleted; do
    echo "[$(date "+%Y-%m-%d %H:%M:%S")] deleted (>180d): ${deleted}"
done

# 3. Disk usage report
du_total=$(du -sh "${LOGS_DIR}" | awk '{print $1}')
echo "[$(date "+%Y-%m-%d %H:%M:%S")] logs/ disk usage: ${du_total}"

# 4. Alert eğer 500MB üstüne çıkmışsa (manuel inceleme şart)
du_bytes=$(du -sb "${LOGS_DIR}" 2>/dev/null | awk '{print $1}' || du -sk "${LOGS_DIR}" | awk '{print $1*1024}')
if [ "${du_bytes}" -gt 524288000 ]; then  # 500MB
    echo "[$(date "+%Y-%m-%d %H:%M:%S")] ⚠️ WARNING: logs/ > 500MB — manuel inceleme gerekli"
fi
