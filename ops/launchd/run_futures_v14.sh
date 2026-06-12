#!/bin/bash
# v14 launchd wrapper — v14p3 FINAL config (5 strateji + ağırlık + throttle).
#
# 2026-06-12: Principal 2 gün erişimsiz kalacağı için unmanaged → KeepAlive.
# DURDURMA: kill YETMEZ (launchd ~60s'de respawn eder). Doğru prosedür:
#   launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.priceaction.futures_v14.plist
# Tekrar başlatma:
#   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.priceaction.futures_v14.plist

set -uo pipefail

ROOT="/Users/peyman/price-action-bot"
cd "${ROOT}"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

# .env source — exchange API key + diğer env
if [[ -f "${ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/.env"
    set +a
fi

# ÇİFT-DAEMON KORUMASI: unmanaged bir v14 hâlâ yaşıyorsa başlama (launchd
# ThrottleInterval ile tekrar dener; operatör eskiyi öldürünce devralır).
if pgrep -f "futures_daemon_v14.py" >/dev/null; then
    echo "[run_v14] başka bir v14 daemon zaten çalışıyor — çift-daemon engellendi, çıkılıyor"
    sleep 30
    exit 1
fi

export PA_V14_PHASE=3
exec "${ROOT}/.venv/bin/python" -u scripts/futures_daemon_v14.py --timeframe 15m
