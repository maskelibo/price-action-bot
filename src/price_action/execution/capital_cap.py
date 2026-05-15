"""Capital Cap Loader — live_capital_cap YAML bloğundan cap değeri türetir.

Kurallar:
  - PA_RUN_MODE != 'live' ise her zaman None (paper/backtest safe)
  - enabled: false ise None
  - cap_expires_at geçmiş tarih ise None + WARNING log
  - Aksi hâlde max_equity_usdt döner

Callerlar:
    from price_action.execution.capital_cap import load_capital_cap
    cap = load_capital_cap(yaml_config_dict)   # -> float | None
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def load_capital_cap(config: dict[str, Any]) -> float | None:
    """YAML config dict'inden capital cap değeri türet.

    Args:
        config: risk_balanced.yaml'ın tam parse edilmiş dict'i
                (live_capital_cap alanı beklenir).

    Returns:
        float  — aktif cap (max_equity_usdt)
        None   — cap devre dışı (paper/backtest/expired/disabled)
    """
    # Gate 1: sadece live modda aktif
    run_mode = os.environ.get("PA_RUN_MODE", "paper").lower()
    if run_mode != "live":
        logger.debug("[CAPITAL_CAP] PA_RUN_MODE=%s — cap devre dışı (paper/backtest)", run_mode)
        return None

    # Gate 2: YAML bloğu var mı?
    cap_cfg = config.get("live_capital_cap")
    if not cap_cfg:
        logger.debug("[CAPITAL_CAP] live_capital_cap bloğu YAML'da yok — cap None")
        return None

    # Gate 3: enabled kontrolü
    if not cap_cfg.get("enabled", False):
        logger.info("[CAPITAL_CAP] enabled=False — cap devre dışı")
        return None

    # Gate 4: cap_expires_at geçmiş mi?
    expires_raw = cap_cfg.get("cap_expires_at")
    if expires_raw:
        try:
            if isinstance(expires_raw, datetime):
                exp_date = expires_raw.date()
            elif isinstance(expires_raw, date):
                exp_date = expires_raw
            else:
                exp_date = date.fromisoformat(str(expires_raw))

            today = datetime.now(timezone.utc).date()
            if today > exp_date:
                logger.warning(
                    "[CAPITAL_CAP] cap_expires_at=%s GECMiS (bugun=%s) — cap inactive, None donuyor. "
                    "YAML'da cap_expires_at guncelle veya enabled=false yap.",
                    exp_date, today,
                )
                return None
        except (ValueError, TypeError) as exc:
            logger.warning("[CAPITAL_CAP] cap_expires_at parse hatası: %s — cap None", exc)
            return None

    # Gate 5: max_equity_usdt
    max_usdt = cap_cfg.get("max_equity_usdt")
    if max_usdt is None:
        logger.warning("[CAPITAL_CAP] max_equity_usdt YAML'da yok — cap None")
        return None

    cap_value = float(max_usdt)

    # Warn threshold log (bilgi amaçlı — caller equity bilmeyebilir,
    # bu yüzden threshold'u da döndürmek için tuple yerine basit float tercih edildi;
    # warn threshold kontrolü caller tarafında yapılır — burada sadece değeri döndür)
    warn_pct = float(cap_cfg.get("warn_threshold_pct", 0.80))
    expires_str = str(expires_raw) if expires_raw else "none"
    logger.info(
        "[CAPITAL_CAP] enabled=True max=%.1f USDT expires=%s warn_pct=%.0f%%",
        cap_value, expires_str, warn_pct * 100,
    )

    return cap_value


def check_warn_threshold(
    cap_value: float,
    current_equity_usdt: float,
    config: dict[str, Any],
) -> None:
    """Mevcut equity cap'in warn_threshold_pct'ine ulaştıysa WARNING yaz.

    futures_trade_daily.py'de equity snapshot sonrası çağrılır.
    """
    if cap_value <= 0:
        return
    cap_cfg = config.get("live_capital_cap") or {}
    warn_pct = float(cap_cfg.get("warn_threshold_pct", 0.80))
    ratio = current_equity_usdt / cap_value
    if ratio >= warn_pct:
        logger.warning(
            "[CAPITAL_CAP] WARN — equity $%.2f / cap $%.2f = %.0f%% (esik %%%.0f). "
            "Cap'e yaklasiliyor, izle.",
            current_equity_usdt, cap_value, ratio * 100, warn_pct * 100,
        )
