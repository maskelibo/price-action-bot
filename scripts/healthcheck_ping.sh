#!/usr/bin/env bash
# DR1 dış dead-man bekçisi — healthchecks.io ping (2026-07-10).
#
# NEDEN (T8 DR1 CRIT): FileVault + auto-login-yok → reboot'ta TÜM stack manuel
# login'e kadar OFFLINE (kanıt: 8 Tem 96dk kör pencere). Yazılımla çözülemez;
# tek meşru fix Mac-DIŞI alarm: ping'ler kesilirse healthchecks.io Principal'e
# mail/push atar → "reboot oldu, git login yap" bilinir.
#
# TASARIM:
#  - HEALTHCHECKS_PING_URL yoksa emir/daemon davranışına dokunmadan INERT uyarısı
#    yaz; dashboard bunu WARN gösterir (dış bekçi varmış gibi false-green yok).
#  - Sağlık = v15p2 daemon prosesi CANLI + log taze (<20dk; bar 15dk+buffer).
#  - Sağlıklı → ping. SAĞLIKSIZ → ping YOK (/fail DEĞİL): daemon restart'ının
#    ~2-3dk boşluğu anlık false-alarm üretmesin; gerçek ölümde ping'ler kesilir,
#    healthchecks grace (öneri: 15dk) sonrası alarm verir. Reboot'ta bu script
#    de ölür (gui LaunchAgent) → ping kesilir → alarm. İstenen davranış bu.
#
# launchd: com.priceaction.healthping (StartInterval 300 = 5dk).
set -u
ROOT="${PA_PROJECT_ROOT:-/Users/peyman/price-action-bot}"
# Explicit process env wins; launchd deployment currently falls back to .env.
# Never print the URL itself — only configured/inert state is observable.
URL="${HEALTHCHECKS_PING_URL:-}"
if [ -z "$URL" ]; then
    URL="$(grep -E '^HEALTHCHECKS_PING_URL=' "$ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2-)"
fi
if [ -z "${URL:-}" ]; then
    echo "[$(date -u '+%H:%M:%SZ')] INERT: HEALTHCHECKS_PING_URL yapılandırılmamış — dış dead-man alarmı YOK"
    exit 0
fi

LOG="$ROOT/logs/futures_daemon_v15p2.log"
now=$(date +%s)
LAUNCH_LABEL="com.priceaction.futures_v15p2"
EXPECTED_PROGRAM="$ROOT/ops/launchd/run_futures_v15p2.sh"

# Sağlık 1: exact launchd label, exact configured program and its live PID.
# Broad pgrep is forbidden here: an editor/test process containing the same
# filename must never satisfy the production dead-man check.
if ! command -v launchctl >/dev/null 2>&1; then
    echo "[$(date -u '+%H:%M:%SZ')] UNHEALTHY: launchctl yok; exact daemon kimliği doğrulanamadı"
    exit 2
fi
if ! launch_state=$(launchctl print "gui/$(id -u)/$LAUNCH_LABEL" 2>/dev/null); then
    echo "[$(date -u '+%H:%M:%SZ')] UNHEALTHY: $LAUNCH_LABEL loaded değil — ping atlanıyor"
    exit 2
fi
daemon_pid=$(printf '%s\n' "$launch_state" | awk '/^[[:space:]]*pid = [0-9]+/ {print $3; exit}')
case "$daemon_pid" in
    ''|*[!0-9]*)
        echo "[$(date -u '+%H:%M:%SZ')] UNHEALTHY: $LAUNCH_LABEL running PID vermedi — ping atlanıyor"
        exit 2
        ;;
esac
configured_program=$(
    printf '%s\n' "$launch_state" \
        | awk '/^[[:space:]]*program = / {sub(/^[[:space:]]*program = /, ""); print; exit}'
)
if [ "$configured_program" != "$EXPECTED_PROGRAM" ]; then
    echo "[$(date -u '+%H:%M:%SZ')] UNHEALTHY: $LAUNCH_LABEL beklenen programı çalıştırmıyor — ping atlanıyor"
    exit 2
fi
if ! kill -0 "$daemon_pid" 2>/dev/null; then
    echo "[$(date -u '+%H:%M:%SZ')] UNHEALTHY: $LAUNCH_LABEL PID=$daemon_pid canlı değil — ping atlanıyor"
    exit 2
fi

# Sağlık 2: log taze mi (<20dk — bar 15dk + tarama payı)
if [ -f "$LOG" ]; then
    if [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
        mtime=$(stat -f %m "$LOG" 2>/dev/null || true)
    else
        mtime=$(stat -c %Y "$LOG" 2>/dev/null || true)
    fi
    case "$mtime" in
        ''|*[!0-9]*)
            echo "[$(date -u '+%H:%M:%SZ')] UNHEALTHY: log mtime okunamadı — ping atlanıyor"
            exit 2
            ;;
    esac
    if [ "$mtime" -gt "$now" ]; then
        echo "[$(date -u '+%H:%M:%SZ')] UNHEALTHY: log mtime gelecekte (mtime=$mtime now=$now) — ping atlanıyor"
        exit 2
    fi
    age=$(( now - mtime ))
    if [ "$age" -gt 1200 ]; then
        echo "[$(date -u '+%H:%M:%SZ')] UNHEALTHY: log ${age}s bayat (>1200s) — ping atlanıyor"
        exit 2
    fi
else
    echo "[$(date -u '+%H:%M:%SZ')] UNHEALTHY: log dosyası yok — ping atlanıyor"
    exit 2
fi

# Sağlıklı → ping. Teslim hatası non-zero döner ki launchd last-exit ve
# dashboard bunu başarı gibi göstermesin; StartInterval sonraki 5dk'da tekrarlar.
if ! curl -fsS -m 10 --retry 2 -o /dev/null "$URL" 2>/dev/null; then
    echo "[$(date -u '+%H:%M:%SZ')] PING_FAIL: healthchecks erişilemedi (ağ?)"
    exit 1
fi
echo "[$(date -u '+%H:%M:%SZ')] PING_OK: healthchecks endpoint isteği kabul etti"
exit 0
