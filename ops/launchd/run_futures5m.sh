#!/bin/bash
# futures5m launchd wrapper — 5m P1c daemon başlatıcı.
#
# Paralel olarak com.priceaction.futures15m ile yan yana çalışır.
# Ayrı journal, ayrı log, ayrı state. PnL track tamamen izole.
#
# Faz 5 (2026-05-25): ilk deploy
# Çağrılan: launchd com.priceaction.futures5m plist

set -uo pipefail

ROOT="/Users/peyman/price-action-bot"
cd "${ROOT}"

# 1) PATH (launchd minimal PATH miras alır)
export PATH="/Users/peyman/.nvm/versions/node/v24.16.0/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

# 2) .env source — exchange API key + diğer env
if [[ -f "${ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/.env"
    set +a
fi

# 3) Orchestrator için zorunlu env
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export PA_RUN_MODE="${PA_RUN_MODE:-paper}"
export PA_5M_CONFIG="${PA_5M_CONFIG:-configs/risk_phoenix_scalp_5m_p1c.yaml}"
export TZ="UTC"

# 4) Pre-flight check (loga yazılır)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] futures5m starting"
echo "  PYTHONPATH=${PYTHONPATH}"
echo "  PA_5M_CONFIG=${PA_5M_CONFIG}"
echo "  PA_RUN_MODE=${PA_RUN_MODE}"
echo "  TELEGRAM_BOT_TOKEN=$([[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && echo "SET" || echo "MISSING")"

# 5) Exec — wrapper süreci python ile yer değiştirir
exec "${ROOT}/.venv/bin/python" -u scripts/futures_daemon.py --timeframe 5m
