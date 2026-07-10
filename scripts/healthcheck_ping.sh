#!/usr/bin/env bash
# DR1 dış dead-man bekçisi — healthchecks.io ping (2026-07-10).
#
# NEDEN (T8 DR1 CRIT): FileVault + auto-login-yok → reboot'ta TÜM stack manuel
# login'e kadar OFFLINE (kanıt: 8 Tem 96dk kör pencere). Yazılımla çözülemez;
# tek meşru fix Mac-DIŞI alarm: ping'ler kesilirse healthchecks.io Principal'e
# mail/push atar → "reboot oldu, git login yap" bilinir.
#
# TASARIM:
#  - HEALTHCHECKS_PING_URL .env'de YOKSA sessiz çık (inert — kurulum güvenli).
#  - Sağlık = v15p2 daemon prosesi CANLI + log taze (<20dk; bar 15dk+buffer).
#  - Sağlıklı → ping. SAĞLIKSIZ → ping YOK (/fail DEĞİL): daemon restart'ının
#    ~2-3dk boşluğu anlık false-alarm üretmesin; gerçek ölümde ping'ler kesilir,
#    healthchecks grace (öneri: 15dk) sonrası alarm verir. Reboot'ta bu script
#    de ölür (gui LaunchAgent) → ping kesilir → alarm. İstenen davranış bu.
#
# launchd: com.priceaction.healthping (StartInterval 300 = 5dk).
set -u
ROOT="/Users/peyman/price-action-bot"
URL="$(grep -E '^HEALTHCHECKS_PING_URL=' "$ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2-)"
[ -z "${URL:-}" ] && exit 0  # kurulmamış — inert

LOG="$ROOT/logs/futures_daemon_v15p2.log"
now=$(date +%s)

# Sağlık 1: daemon prosesi canlı mı
if ! pgrep -f "futures_daemon_v14.py" >/dev/null 2>&1; then
    echo "[$(date -u '+%H:%M:%SZ')] UNHEALTHY: daemon prosesi yok — ping atlanıyor (grace alarmı devrede)"
    exit 0
fi

# Sağlık 2: log taze mi (<20dk — bar 15dk + tarama payı)
if [ -f "$LOG" ]; then
    mtime=$(stat -f %m "$LOG" 2>/dev/null || echo 0)
    age=$(( now - mtime ))
    if [ "$age" -gt 1200 ]; then
        echo "[$(date -u '+%H:%M:%SZ')] UNHEALTHY: log ${age}s bayat (>1200s) — ping atlanıyor"
        exit 0
    fi
else
    echo "[$(date -u '+%H:%M:%SZ')] UNHEALTHY: log dosyası yok — ping atlanıyor"
    exit 0
fi

# Sağlıklı → ping (sessiz; curl hatası ölümcül değil, sonraki 5dk'da tekrar)
curl -fsS -m 10 --retry 2 -o /dev/null "$URL" 2>/dev/null || \
    echo "[$(date -u '+%H:%M:%SZ')] PING_FAIL: healthchecks erişilemedi (ağ?)"
exit 0
