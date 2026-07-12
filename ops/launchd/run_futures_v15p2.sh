#!/usr/bin/env bash
# v15p2 "KONSANTRE FILO" testnet daemon wrapper (2026-07-02, Principal onayı).
# grimes+vsa eşit-ağırlık, risk %1.0, PYRAMID OFF (validasyonla birebir).
# Aynı script'i (futures_daemon_v14.py) PA_V14_PHASE=v15p2 ile koşar.
# DURDURMA: launchctl bootout gui/501/com.priceaction.futures_v15p2
set -uo pipefail
ROOT="/Users/peyman/price-action-bot"
cd "${ROOT}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
if [[ -f "${ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/.env"
    set +a
fi

# ── DR9 fail-boot devre-kesici alarmı (2026-07-10) ─────────────────────────
# KeepAlive+ThrottleInterval=60 → bozuk .env/config'te SONSUZ sessiz relaunch
# churn'ü (T8 DR9). Tespit: ardışık HIZLI relaunch'lar (<120s ara) = crash-loop
# şüphesi; 5.'de TEK Telegram CRIT (spam yok — sayaç 5'i aşınca susar, yavaş
# relaunch sayacı sıfırlar). exec/sinyal semantiğine DOKUNULMAZ (graceful
# SIGTERM + REBUILD canlı-para-kritik). Normal kickstart'lar arası > 120s
# olduğundan asla tetiklenmez.
_DR9_STATE="${ROOT}/logs/launchd/v15p2_boot_state"
_now=$(date +%s)
_last=0; _fails=0
if [[ -f "${_DR9_STATE}" ]]; then
    read -r _last _fails < "${_DR9_STATE}" 2>/dev/null || { _last=0; _fails=0; }
fi
if (( _now - _last < 120 )); then
    _fails=$(( _fails + 1 ))
else
    _fails=0
fi
echo "${_now} ${_fails}" > "${_DR9_STATE}" 2>/dev/null || true
if (( _fails == 5 )) && [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
    curl -s -m 5 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="${TELEGRAM_CHAT_ID}" \
        -d text="🚨 [CRIT] v15p2 daemon CRASH-LOOP: 5 ardışık hızlı relaunch (<120s ara). Muhtemel bozuk .env/config — bot fiilen KAPALI, launchd sessizce döngüde. Elle bak: logs/launchd/futures_v15p2.stderr.log" \
        >/dev/null 2>&1 || true
    echo "[run_v15p2] DR9: crash-loop alarmı gönderildi (5 ardışık hızlı relaunch)"
fi
# ── DR9 sonu ────────────────────────────────────────────────────────────────

# Çift-daemon koruması: yalnız gerçek Python daemon executable+argv kimliğini
# kabul et. Geniş `pgrep -f` orkestrasyon/diagnostic shell komut satırındaki
# `futures_daemon_v14.py` metnini de proses sanıyordu ve güvenli kickstart'ı
# false-positive ile bir KeepAlive gecikmesine sokabiliyordu.
_process_table="$(ps -axo pid=,ucomm=,args= 2>/dev/null)" || {
    echo "[run_v15p2] CRIT: process inventory okunamadı — çift-daemon güvenliği fail-closed"
    exit 1
}
_existing_pid="$(
    printf '%s\n' "${_process_table}" |
        awk -f "${ROOT}/ops/launchd/select_futures_v15p2_pid.awk"
)" || {
    echo "[run_v15p2] CRIT: daemon identity selector çalışmadı — fail-closed"
    exit 1
}
if [[ -n "${_existing_pid}" ]]; then
    echo "[run_v15p2] futures daemon PID ${_existing_pid} zaten çalışıyor — çift-daemon engellendi, çıkılıyor"
    sleep 30
    exit 1
fi
# SAFETY: testnet wrapper — live ASLA. (daemon içinde de PA_LIVE_CONFIRM reddi var.)
export PA_V14_PHASE=v15p2
exec "${ROOT}/.venv/bin/python" -u scripts/futures_daemon_v14.py --timeframe 15m
