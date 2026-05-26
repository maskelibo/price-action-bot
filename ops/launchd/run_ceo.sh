#!/bin/bash
# pa-ceo launchd wrapper — .env source eder, doğru python'la başlatır.
#
# Faz 4.1 hardening:
# - .env'den TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID + ANTHROPIC_API_KEY okur
# - PATH'i node/python tooling'ini bulacak şekilde set eder
# - PA_CLAUDE_CLI'ı `which claude` ile dinamik bulur (nvm path değişimine resilient)
# - Tüm critical env vars'ı çocuk process'e aktarır
# - Çocuk process exit kodu wrapper exit kodu olarak yansır
#
# Çağrılan: launchd com.priceaction.ceo plist
# Log: launchd StandardOutPath/StandardErrorPath'e gider

set -uo pipefail

ROOT="/Users/peyman/price-action-bot"
cd "${ROOT}"

# 1) PATH set et (launchd minimal PATH miras alır)
#    nvm + homebrew + system standartları
export PATH="/Users/peyman/.nvm/versions/node/v24.16.0/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

# 2) .env source — secret'lar buradan gelir (TELEGRAM_*, ANTHROPIC_API_KEY)
if [[ -f "${ROOT}/.env" ]]; then
    set -a  # tüm değişkenleri auto-export et
    # shellcheck disable=SC1091
    source "${ROOT}/.env"
    set +a
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: ${ROOT}/.env yok — Telegram + LLM creds eksik kalabilir" >&2
fi

# 3) PA_CLAUDE_CLI dinamik bulma (nvm version değişimine dayanıklı)
CLAUDE_PATH=$(command -v claude 2>/dev/null || true)
if [[ -n "${CLAUDE_PATH}" ]]; then
    export PA_CLAUDE_CLI="${CLAUDE_PATH}"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: claude binary PATH'te bulunamadı — LLM çağrıları fail edecek" >&2
fi

# 4) Orchestrator için zorunlu env
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export PA_LLM_USE_CLI="true"
export PA_RUN_MODE="${PA_RUN_MODE:-paper}"
export PA_CEO_PUSH_TELEGRAM="true"
export TZ="UTC"
# CEO morning brief büyük context (~25k token) → Opus call 3-4dk sürebilir.
# Default 180sn timeout retry zincirine girer → 9dk boşa. 300sn (5dk) güvenli.
export PA_CLI_TIMEOUT_S="${PA_CLI_TIMEOUT_S:-300}"

# 4b) PA_LLM_USE_CLI=true iken Claude CLI subscription auth kullanmalı.
# Eğer ANTHROPIC_API_KEY set ise CLI onu kullanmaya çalışır; invalid/expired
# olursa "Invalid API key" hatası alırız. UNSET — CLI OAuth/subscription'a düşsün.
if [[ -n "${ANTHROPIC_API_KEY:-}" ]] && [[ "${PA_LLM_USE_CLI}" == "true" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: PA_LLM_USE_CLI=true — ANTHROPIC_API_KEY unset edildi (CLI subscription auth)"
    unset ANTHROPIC_API_KEY
fi

# 4c) FIX 2026-05-26 (Faz 14.7): pycache auto-clean.
# Önceki bug: kod değişiklikten sonra `launchctl kickstart -k` daemon'u
# yeniden başlatıyor ama __pycache__/*.pyc eski bytecode'u tutuyor → yeni
# daemon ESKI kodu okuyor (3 saat sistem dondu 2026-05-26 H2 bug'ında).
# Çözüm: her launch'da pycache temizle (~100ms iş).
find "${ROOT}/src" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "${ROOT}/src" -name "*.pyc" -delete 2>/dev/null || true
echo "[$(date '+%Y-%m-%d %H:%M:%S')] pycache cleaned"

# 5) Pre-flight check (loga yazılır)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ceo_loop starting"
echo "  PYTHONPATH=${PYTHONPATH}"
echo "  PA_CLAUDE_CLI=${PA_CLAUDE_CLI:-MISSING}"
echo "  TELEGRAM_BOT_TOKEN=$([[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && echo "SET" || echo "MISSING")"
echo "  TELEGRAM_CHAT_ID=$([[ -n "${TELEGRAM_CHAT_ID:-}" ]] && echo "SET" || echo "MISSING")"
echo "  ANTHROPIC_API_KEY=$([[ -n "${ANTHROPIC_API_KEY:-}" ]] && echo "SET" || echo "MISSING")"
echo "  PA_RUN_MODE=${PA_RUN_MODE}"

# 6) Exec — wrapper süreci python ile yer değiştirir (launchd PID python'ı gözler)
exec "${ROOT}/.venv/bin/python" -m price_action.orchestrator.ceo_loop --mode daily --telegram
