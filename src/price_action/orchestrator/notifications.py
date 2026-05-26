"""Telegram push helper — orchestrator merkezi notification katmanı.

Faz 1.2 unification: tüm push noktaları (CEO daily/weekly brief, Lab tournament,
Drift alert, crisis) bu modülden geçer. `llm_orchestrator.py`'deki dağınık
``send_telegram`` çağrıları buraya konsolide edilir.

Public API
----------
push_report(path, level, caption=None, max_chars=2800) -> bool
    Markdown raporu Telegram'a gönderir; uzun ise chunk'lara böler.

push_critical(message, source=None) -> bool
    🚨 CRIT prefix ile send; episodic kayıt + Prometheus counter.

should_push(env_var="PA_CEO_PUSH_TELEGRAM") -> bool
    Env + dry-run kontrolü tek noktada.

Hiçbir fonksiyon hata fırlatmaz — sessiz fail + WARN log (Telegram down
production'ı durdurmamalı).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from price_action.logging_config import logger
from price_action.notifications.telegram import send_critical, send_telegram

# 2800 char Telegram limit'in altında, 4096 hard limit'in çok altında —
# Markdown escape'ten sonra biraz şişer.
_DEFAULT_MAX_CHARS = 2800


def should_push(env_var: str = "PA_CEO_PUSH_TELEGRAM") -> bool:
    """Telegram push'un aktif olup olmadığını kontrol et.

    Üç koşul birden:
    1. ``env_var`` "true" set edilmiş (default: PA_CEO_PUSH_TELEGRAM)
    2. PA_LLM_DRY_RUN aktif değil (test/CI'da sessiz)
    3. TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID env'de mevcut

    Returns
    -------
    bool
        True ise push yapılır; False ise sessizce skip.
    """
    if os.environ.get(env_var, "").lower() not in ("1", "true", "yes"):
        return False
    if os.environ.get("PA_LLM_DRY_RUN", "").lower() in ("1", "true", "yes"):
        return False
    if not os.environ.get("TELEGRAM_BOT_TOKEN", "").strip():
        return False
    if not os.environ.get("TELEGRAM_CHAT_ID", "").strip():
        return False
    return True


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Markdown'ı kelime sınırında chunk'lara böl.

    Telegram tek mesajda max 4096 char; biz 2800 limit ile güvenli kalırız.
    Chunk'lar arasına `_(continued)_` header eklenir.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    remaining = text
    chunk_idx = 0
    while remaining:
        if len(remaining) <= max_chars:
            header = f"_(continued — part {chunk_idx + 1})_\n\n" if chunk_idx > 0 else ""
            chunks.append(header + remaining)
            break

        # Çift satırda kes (paragraph boundary)
        cut = remaining.rfind("\n\n", 0, max_chars)
        if cut < max_chars // 2:
            # Yeterince geriye gidemiyoruz → tek satırda kes
            cut = remaining.rfind("\n", 0, max_chars)
        if cut < max_chars // 2:
            # Hâlâ kötü → hard cut
            cut = max_chars - 100
        # FIX 2026-05-26 (L2): Emoji/Unicode surrogate safety.
        # UTF-8 multi-byte char ortasında cut yapmaktan kaçın.
        # cut'a yakın geçerli char boundary'sini bul.
        try:
            # encode/decode round-trip ile char safety
            test = remaining[:cut].encode("utf-8", errors="strict")
            # Eğer encode başarılı, cut güvenli. Sorun yok.
        except UnicodeError:
            # Geriye doğru git, geçerli boundary bul
            for backstep in range(1, 10):
                try:
                    remaining[: cut - backstep].encode("utf-8", errors="strict")
                    cut = cut - backstep
                    break
                except UnicodeError:
                    continue

        header = f"_(continued — part {chunk_idx + 1})_\n\n" if chunk_idx > 0 else ""
        chunks.append(header + remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
        chunk_idx += 1

    return chunks


def push_report(
    path: Path | str,
    *,
    level: str = "INFO",
    caption: str | None = None,
    max_chars: int = _DEFAULT_MAX_CHARS,
    env_var: str = "PA_CEO_PUSH_TELEGRAM",
    parse_mode: str | None = None,  # FIX 2026-05-25: None safer — file names with _ or *
    alert_type: str | None = None,
) -> bool:
    """Markdown raporu Telegram'a gönder; uzun ise chunk'lara böl.

    Parameters
    ----------
    path:
        Gönderilecek markdown dosyasının yolu (Path veya str).
    level:
        "INFO" | "WARNING" | "ERROR" | "CRIT" — emoji prefix.
    caption:
        Opsiyonel başlık (rapor body'sinin önüne eklenir).
    max_chars:
        Chunk başı maksimum karakter (Telegram 4096 hard limit).
    env_var:
        Push'un aktif olup olmadığını kontrol eden env değişkeni.
    parse_mode:
        Telegram parse mode ("Markdown", "MarkdownV2", "HTML", None).

    Returns
    -------
    bool
        True: en az 1 chunk gönderildi. False: skip veya tüm chunk'lar fail.
    """
    if not should_push(env_var):
        logger.info(
            "notifications.push_skip",
            extra={"reason": "should_push=False", "path": str(path)},
        )
        return False

    p = Path(path)
    if not p.exists():
        logger.warning(
            "notifications.push_path_missing",
            extra={"path": str(path)},
        )
        return False

    try:
        body = p.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning(
            "notifications.push_read_fail",
            extra={"path": str(path), "err": str(exc)[:200]},
        )
        return False

    full = body if not caption else f"**{caption}**\n\n{body}"
    chunks = _chunk_text(full, max_chars)
    sent_any = False

    # H5 FIX: TelegramThrottle entegrasyonu — spam koruma (5dk window default)
    # alert_type belirtilirse throttle key olarak kullan; yoksa path-stem.
    use_throttle = alert_type is not None or (caption is not None)
    throttle = None
    if use_throttle:
        try:
            from price_action.ops.telegram_throttle import get_telegram_throttle
            throttle = get_telegram_throttle()
        except Exception as exc:
            logger.warning(
                "notifications.throttle_init_fail",
                extra={"err": str(exc)[:200]},
            )
            throttle = None

    effective_alert = alert_type or (caption or Path(path).stem)[:40]

    for chunk in chunks:
        if throttle:
            ok = throttle.send_throttled(effective_alert, chunk, level=level)
        else:
            ok = send_telegram(chunk, level=level, parse_mode=parse_mode)
        sent_any = sent_any or ok
    logger.info(
        "notifications.push_done",
        extra={
            "path": str(path),
            "chunks": len(chunks),
            "sent_any": sent_any,
            "total_chars": len(full),
            "throttled": use_throttle,
            "alert_type": effective_alert,
        },
    )
    return sent_any


def push_critical(
    message: str,
    *,
    source: str | None = None,
    env_var: str = "PA_CEO_PUSH_TELEGRAM",
) -> bool:
    """🚨 CRIT alarm gönder.

    Kritik alarmlar her zaman gönderilmeye **çalışılır** (env_var'a bakılmaz —
    crisis durumunda env unutulsa bile alarm gitmeli). Tek bypass:
    PA_LLM_DRY_RUN aktifse skip + log.

    Parameters
    ----------
    message:
        Alarm mesajı (kısa, < 2800 char).
    source:
        Hangi agent/component üretti (örn. "risk_officer", "ops_engineer").
    env_var:
        Çoğu zaman göz ardı edilir (CRIT için always-on), ama opsiyonel kill switch.

    Returns
    -------
    bool
        True: gönderildi. False: skip veya fail.
    """
    if os.environ.get("PA_LLM_DRY_RUN", "").lower() in ("1", "true", "yes"):
        logger.warning(
            "notifications.crit_dry_run",
            extra={"source": source, "preview": message[:200]},
        )
        return False
    if not os.environ.get("TELEGRAM_BOT_TOKEN", "").strip():
        logger.error(
            "notifications.crit_no_token",
            extra={"source": source, "preview": message[:200]},
        )
        return False

    full = f"[{source or 'system'}] {message}" if source else message
    # FIX 2026-05-25: parse_mode=None — source often contains _ (e.g. risk_officer)
    # which breaks Markdown parser. CRIT alerts must always deliver.
    return send_critical(full, parse_mode=None)


# ----------------------------------------------------------------------
# Convenience: scheduler/agent çağrı kalıpları
# ----------------------------------------------------------------------

def push_report_if_recent(
    dir_path: Path | str,
    pattern: str,
    *,
    level: str = "INFO",
    caption: str | None = None,
    **kwargs: Any,
) -> bool:
    """En son matching raporu bul ve push et.

    Örn. ``push_report_if_recent(reports_dir/"ceo", "*-brief.md")`` —
    son üretilen brief'i bulur, push eder.
    """
    d = Path(dir_path)
    if not d.exists():
        return False
    matches = sorted(d.glob(pattern), reverse=True)
    if not matches:
        logger.info(
            "notifications.no_match",
            extra={"dir": str(d), "pattern": pattern},
        )
        return False
    return push_report(matches[0], level=level, caption=caption, **kwargs)
