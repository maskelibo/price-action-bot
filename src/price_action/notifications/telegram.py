"""Telegram notification module — Faz 5 LLM Orchestration.

Public API
----------
send_telegram(message, level="INFO")  — genel mesaj gönder
send_critical(message)                — 🚨 prefix ile CRIT mesaj

Defensive design:
- TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID env var'ları eksikse,
  WARNING loglanır ve fonksiyon sessizce çıkar (crash yok).
- requests kütüphanesi mevcut değilse aynı davranış.
- PA_LLM_DRY_RUN=true ise gerçek HTTP isteği yapılmaz.
- Markdown parse_mode desteklenir (MarkdownV2).

Env vars
--------
TELEGRAM_BOT_TOKEN   — BotFather'dan alınan bot token
TELEGRAM_CHAT_ID     — Mesaj gönderilecek chat/channel ID
PA_LLM_DRY_RUN       — "true" ise no-op (test/CI modu)
"""

from __future__ import annotations

import os
from typing import Any

from price_action.logging_config import logger

_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"

# Level → emoji prefix mapping
_LEVEL_PREFIX: dict[str, str] = {
    "DEBUG": "🔍",
    "INFO": "ℹ️",
    "WARNING": "⚠️",
    "WARN": "⚠️",
    "ERROR": "❌",
    "CRIT": "🚨",
    "CRITICAL": "🚨",
}


def _get_credentials() -> tuple[str, str] | None:
    """Bot token ve chat_id'yi env'den çek. Eksikse None döner."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token:
        logger.warning(
            "telegram.missing_token",
            extra={"hint": "TELEGRAM_BOT_TOKEN env var set edilmeli"},
        )
        return None
    if not chat_id:
        logger.warning(
            "telegram.missing_chat_id",
            extra={"hint": "TELEGRAM_CHAT_ID env var set edilmeli"},
        )
        return None
    return token, chat_id


def _is_dry_run() -> bool:
    return os.environ.get("PA_LLM_DRY_RUN", "").lower() in ("1", "true", "yes")


def _escape_markdown_v2(text: str) -> str:
    """Telegram MarkdownV2 özel karakterlerini escape et.

    Telegram MarkdownV2'de şu karakterler escape edilmeli:
    _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    special = r"\_*[]()~`>#+-=|{}.!"
    result = []
    for ch in text:
        if ch in special:
            result.append(f"\\{ch}")
        else:
            result.append(ch)
    return "".join(result)


def send_telegram(
    message: str,
    level: str = "INFO",
    *,
    parse_mode: str | None = None,
    disable_web_page_preview: bool = True,
) -> bool:
    """Telegram'a mesaj gönder.

    Parameters
    ----------
    message:
        Gönderilecek metin (Markdown veya düz metin).
    level:
        "INFO" | "WARNING" | "ERROR" | "CRIT" — emoji prefix için kullanılır.
    parse_mode:
        None (düz metin), "Markdown", "MarkdownV2", "HTML".
        None ise mesajı olduğu gibi gönderir.
    disable_web_page_preview:
        Link önizlemesini kapat (varsayılan True).

    Returns
    -------
    bool
        True: başarılı gönderim. False: no-op (eksik config, dry-run, hata).
    """
    level_upper = level.upper()
    prefix = _LEVEL_PREFIX.get(level_upper, "ℹ️")
    full_message = f"{prefix} [{level_upper}] {message}"

    # Dry-run: log et, gerçek istek yapma
    if _is_dry_run():
        logger.info(
            "telegram.dry_run",
            extra={"level": level_upper, "message_preview": full_message[:200]},
        )
        return False

    creds = _get_credentials()
    if creds is None:
        return False

    token, chat_id = creds

    try:
        import requests  # type: ignore[import-untyped]
    except ImportError:
        logger.warning(
            "telegram.requests_missing",
            extra={"hint": "`pip install requests` veya `uv add requests`"},
        )
        return False

    url = _TELEGRAM_API_BASE.format(token=token)

    # FIX 2026-07-08 (bildirim paketi N5): Telegram hard limit 4096 karakter.
    # Eski kod bölmüyordu → uzun mesaj (uzun CRIT dahil) 400 Bad Request ile
    # KOMPLE kaybolurdu. Satır sınırından bölerek sırayla gönder.
    tg_limit = 4096
    parts: list[str] = []
    remaining = full_message
    while len(remaining) > tg_limit:
        cut = remaining.rfind("\n", 1, tg_limit)
        if cut < 1:
            cut = tg_limit
        parts.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    parts.append(remaining)

    any_sent = False
    for part in parts:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": part,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info(
                    "telegram.sent",
                    extra={"level": level_upper, "chat_id": chat_id},
                )
                any_sent = True
            else:
                logger.warning(
                    "telegram.api_error",
                    extra={
                        "status_code": response.status_code,
                        "body": response.text[:300],
                    },
                )
        except Exception as exc:
            # GÜVENLİK FIX 2026-07-07: requests exception metni tam URL'i (yani
            # bot TOKEN'ını) içerir — 21 Haz ağ kesintisinde token log'a sızdı.
            # Token'ı maskele; asla ham exception'ı loglama.
            err_text = str(exc)[:300].replace(token, "***TOKEN***")
            logger.warning(
                "telegram.send_fail",
                extra={"err": err_text[:200]},
            )
    return any_sent


def send_critical(message: str, *, parse_mode: str | None = None) -> bool:
    """Kritik alarm gönder — 🚨 prefix otomatik eklenir.

    Parameters
    ----------
    message:
        Alarm metni.
    parse_mode:
        Telegram parse modu (None, "Markdown", "MarkdownV2", "HTML").

    Returns
    -------
    bool
        True: başarılı. False: no-op.
    """
    return send_telegram(message, level="CRIT", parse_mode=parse_mode)
