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
# Çift-daemon koruması: aynı script (v14 veya v15p2) zaten koşuyorsa çık.
if pgrep -f "futures_daemon_v14.py" >/dev/null; then
    echo "[run_v15p2] futures_daemon_v14.py zaten çalışıyor (v14 veya v15p2) — çift-daemon engellendi, çıkılıyor"
    sleep 30
    exit 1
fi
# SAFETY: testnet wrapper — live ASLA. (daemon içinde de PA_LIVE_CONFIRM reddi var.)
export PA_V14_PHASE=v15p2
exec "${ROOT}/.venv/bin/python" -u scripts/futures_daemon_v14.py --timeframe 15m
