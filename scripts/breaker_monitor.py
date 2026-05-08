"""Faz 5 — Breaker Monitor.

paper_journal.duckdb'i her PA_BREAKER_POLL_INTERVAL saniyede (varsayılan 300)
poll eder. Günlük/haftalık/aylık DD breaker eşikleri aşılırsa:
  1. logs/kill_switch.json'a yazar
  2. llm_orchestrator.py --mode crit-alarm ile CEO kriz protokolü tetikler
  3. Telegram CRIT alert gönderir

Idempotent: breaker aktifken tekrar tetiklenmez (spam yok).

Usage
-----
    PYTHONPATH=src python scripts/breaker_monitor.py
    PYTHONPATH=src PA_LLM_DRY_RUN=true python scripts/breaker_monitor.py --once

Env vars
--------
PA_BREAKER_POLL_INTERVAL=300   — Poll sıklığı (saniye, varsayılan 300)
PA_LLM_DRY_RUN=true            — LLM ve Telegram çağrıları atlanır
TELEGRAM_BOT_TOKEN              — Telegram bot token
TELEGRAM_CHAT_ID                — Telegram chat ID

Breaker thresholds (paper_trading_loop.py ile uyumlu):
    Daily loss  >= 5%   → daily_dd
    Weekly loss >= 10%  → weekly_dd
    Monthly loss>= 15%  → monthly_dd
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Ensure src is on path
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from price_action.logging_config import logger
from price_action.notifications.telegram import send_critical, send_telegram

# =====================================================================
# Constants
# =====================================================================

JOURNAL_PATH = _ROOT / "data" / "paper_journal.duckdb"
KILL_SWITCH_PATH = _ROOT / "logs" / "kill_switch.json"
KILL_SWITCH_PATH.parent.mkdir(parents=True, exist_ok=True)

DAILY_DD_PCT = float(os.environ.get("PA_DAILY_DD_BREAKER", "0.05"))
WEEKLY_DD_PCT = float(os.environ.get("PA_WEEKLY_DD_BREAKER", "0.10"))
MONTHLY_DD_PCT = float(os.environ.get("PA_MONTHLY_DD_BREAKER", "0.15"))
POLL_INTERVAL = int(os.environ.get("PA_BREAKER_POLL_INTERVAL", "300"))

INITIAL_CAPITAL = float(os.environ.get("PA_PAPER_INITIAL_CAPITAL", "10000"))


def _is_dry_run() -> bool:
    return os.environ.get("PA_LLM_DRY_RUN", "").lower() in ("1", "true", "yes")


# =====================================================================
# Kill-switch state
# =====================================================================

def _load_kill_switch() -> dict[str, Any]:
    """Kill switch durumunu oku."""
    if not KILL_SWITCH_PATH.exists():
        return {"active": False, "breakers": {}, "triggered_at": None, "reason": None}
    try:
        return json.loads(KILL_SWITCH_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("breaker_monitor.kill_switch_read_fail", extra={"err": str(exc)[:200]})
        return {"active": False, "breakers": {}, "triggered_at": None, "reason": None}


def _save_kill_switch(state: dict[str, Any]) -> None:
    """Kill switch durumunu kaydet."""
    try:
        KILL_SWITCH_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        logger.info("breaker_monitor.kill_switch_saved", extra={"state": state})
    except Exception as exc:
        logger.error("breaker_monitor.kill_switch_save_fail", extra={"err": str(exc)[:200]})


def _reset_kill_switch() -> None:
    """Kill switch'i sıfırla (insan onayı sonrası)."""
    state = {
        "active": False,
        "breakers": {},
        "triggered_at": None,
        "reason": None,
        "reset_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_kill_switch(state)
    logger.info("breaker_monitor.kill_switch_reset")


# =====================================================================
# DD computation from journal
# =====================================================================

def _compute_drawdowns() -> dict[str, Any]:
    """Journal'dan DD hesapla.

    Returns dict ile:
        daily_pnl, weekly_pnl, monthly_pnl,
        daily_dd_pct, weekly_dd_pct, monthly_dd_pct,
        current_equity, initial_equity
    """
    result: dict[str, Any] = {
        "available": False,
        "daily_pnl": 0.0,
        "weekly_pnl": 0.0,
        "monthly_pnl": 0.0,
        "daily_dd_pct": 0.0,
        "weekly_dd_pct": 0.0,
        "monthly_dd_pct": 0.0,
        "current_equity": INITIAL_CAPITAL,
        "error": None,
    }

    if not JOURNAL_PATH.exists():
        result["error"] = "journal_not_found"
        return result

    try:
        import duckdb  # type: ignore[import-not-found]

        conn = duckdb.connect(str(JOURNAL_PATH), read_only=True)
        now_utc = datetime.now(timezone.utc)
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)

        try:
            # Latest equity from snapshots
            eq_row = conn.execute(
                "SELECT equity FROM paper_equity_snapshots ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            current_equity = float(eq_row[0]) if eq_row else INITIAL_CAPITAL
            result["current_equity"] = current_equity

            def _sum_pnl(since_date: date) -> float:
                row = conn.execute(
                    "SELECT SUM(realized_pnl) FROM paper_trades "
                    "WHERE status='closed' AND exit_ts >= ?",
                    [since_date.isoformat()],
                ).fetchone()
                return float(row[0] or 0.0) if row else 0.0

            daily_pnl = _sum_pnl(today)
            weekly_pnl = _sum_pnl(week_start)
            monthly_pnl = _sum_pnl(month_start)

            result["daily_pnl"] = daily_pnl
            result["weekly_pnl"] = weekly_pnl
            result["monthly_pnl"] = monthly_pnl

            # DD as percentage of current equity (or INITIAL_CAPITAL as base)
            base = max(current_equity, INITIAL_CAPITAL * 0.5)  # don't div by tiny number
            result["daily_dd_pct"] = max(-daily_pnl / base, 0.0)
            result["weekly_dd_pct"] = max(-weekly_pnl / base, 0.0)
            result["monthly_dd_pct"] = max(-monthly_pnl / base, 0.0)
            result["available"] = True
        finally:
            conn.close()

    except ImportError:
        result["error"] = "duckdb_not_installed"
        logger.warning("breaker_monitor.duckdb_missing")
    except Exception as exc:
        result["error"] = str(exc)[:200]
        logger.warning("breaker_monitor.dd_compute_fail", extra={"err": str(exc)[:200]})

    return result


# =====================================================================
# Breaker evaluation
# =====================================================================

def _evaluate_breakers(dd: dict[str, Any]) -> dict[str, bool]:
    """DD'yi eşiklerle karşılaştır, tetiklenen breaker'ları döndür."""
    return {
        "daily_dd": dd["daily_dd_pct"] >= DAILY_DD_PCT,
        "weekly_dd": dd["weekly_dd_pct"] >= WEEKLY_DD_PCT,
        "monthly_dd": dd["monthly_dd_pct"] >= MONTHLY_DD_PCT,
    }


def _format_reason(breakers: dict[str, bool], dd: dict[str, Any]) -> str:
    """Tetiklenen breaker'lar için açıklama metni üret."""
    parts = []
    if breakers.get("daily_dd"):
        parts.append(
            f"GÜNLÜK DD: {dd['daily_dd_pct']*100:.2f}% >= {DAILY_DD_PCT*100:.0f}% limit"
        )
    if breakers.get("weekly_dd"):
        parts.append(
            f"HAFTALIK DD: {dd['weekly_dd_pct']*100:.2f}% >= {WEEKLY_DD_PCT*100:.0f}% limit"
        )
    if breakers.get("monthly_dd"):
        parts.append(
            f"AYLIK DD: {dd['monthly_dd_pct']*100:.2f}% >= {MONTHLY_DD_PCT*100:.0f}% limit"
        )
    return " | ".join(parts) if parts else "Bilinmeyen breaker"


# =====================================================================
# Trigger logic
# =====================================================================

def _trigger_orchestrator(reason: str) -> None:
    """llm_orchestrator.py --mode crit-alarm subprocess çağrısı."""
    script = _ROOT / "scripts" / "llm_orchestrator.py"
    cmd = [sys.executable, str(script), "--mode", "crit-alarm", "--reason", reason]

    if _is_dry_run():
        cmd.append("--dry-run")

    logger.info("breaker_monitor.triggering_orchestrator", extra={"cmd": " ".join(cmd[:4])})
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        # Non-blocking: orchestrator kendi logger'ına yazar, biz beklemiyor
        logger.info(
            "breaker_monitor.orchestrator_spawned",
            extra={"pid": proc.pid},
        )
    except Exception as exc:
        logger.error(
            "breaker_monitor.orchestrator_spawn_fail",
            extra={"err": str(exc)[:200]},
        )


def handle_breaker_trigger(
    breakers: dict[str, bool],
    dd: dict[str, Any],
) -> None:
    """Breaker tetiklendiğinde tüm aksiyonları uygula."""
    reason = _format_reason(breakers, dd)
    now = datetime.now(timezone.utc).isoformat()

    # 1. Kill switch kaydet
    state: dict[str, Any] = {
        "active": True,
        "breakers": breakers,
        "triggered_at": now,
        "reason": reason,
        "dd_snapshot": {
            "daily_pnl": dd.get("daily_pnl"),
            "weekly_pnl": dd.get("weekly_pnl"),
            "monthly_pnl": dd.get("monthly_pnl"),
            "daily_dd_pct": dd.get("daily_dd_pct"),
            "weekly_dd_pct": dd.get("weekly_dd_pct"),
            "monthly_dd_pct": dd.get("monthly_dd_pct"),
            "equity": dd.get("current_equity"),
        },
    }
    _save_kill_switch(state)

    # 2. Telegram CRIT (önce — hızlı uyarı)
    send_critical(
        f"BREAKER TETİKLENDİ\n\n"
        f"{reason}\n\n"
        f"Equity: {dd.get('current_equity', 0):.2f} USDT\n"
        f"Yeni pozisyon açılmıyor. Kill-switch: logs/kill_switch.json\n"
        f"Manuel reset: breaker_monitor.py --reset"
    )

    # 3. LLM orchestrator kriz protokolü (async subprocess)
    _trigger_orchestrator(reason)

    logger.warning(
        "breaker_monitor.breaker_triggered",
        extra={"reason": reason, "breakers": breakers},
    )


# =====================================================================
# Poll cycle
# =====================================================================

def poll_once() -> dict[str, Any]:
    """Tek bir poll döngüsü — breaker tetiklenirse handle_breaker_trigger çağırır."""
    ks = _load_kill_switch()

    dd = _compute_drawdowns()
    if not dd["available"]:
        logger.info(
            "breaker_monitor.journal_unavailable",
            extra={"reason": dd.get("error", "unknown")},
        )
        return {"status": "no_data", "dd": dd, "kill_switch": ks}

    breakers = _evaluate_breakers(dd)
    any_triggered = any(breakers.values())

    if any_triggered:
        if ks.get("active"):
            # Idempotent: breaker zaten aktif — tekrar tetikleme
            logger.info(
                "breaker_monitor.already_active",
                extra={"triggered_since": ks.get("triggered_at")},
            )
            return {
                "status": "already_active",
                "dd": dd,
                "breakers": breakers,
                "kill_switch": ks,
            }

        # Yeni tetiklenme
        handle_breaker_trigger(breakers, dd)
        return {
            "status": "triggered",
            "dd": dd,
            "breakers": breakers,
        }

    # Breaker aktifken DD normale döndüyse logla (ama otomatik reset yapma)
    if ks.get("active") and not any_triggered:
        logger.info(
            "breaker_monitor.dd_recovered",
            extra={"note": "Kill-switch hala aktif — manuel reset gerekli"},
        )
        return {
            "status": "recovered_but_locked",
            "dd": dd,
            "breakers": breakers,
            "kill_switch": ks,
        }

    # Normal durum
    logger.info(
        "breaker_monitor.ok",
        extra={
            "daily_dd_pct": f"{dd['daily_dd_pct']*100:.2f}%",
            "weekly_dd_pct": f"{dd['weekly_dd_pct']*100:.2f}%",
            "monthly_dd_pct": f"{dd['monthly_dd_pct']*100:.2f}%",
            "equity": dd.get("current_equity"),
        },
    )
    return {"status": "ok", "dd": dd, "breakers": breakers}


# =====================================================================
# Entry point
# =====================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Faz 5 Breaker Monitor — DD breaker poll + Telegram CRIT alert"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Bir kez poll et ve çık (watchdog modu yerine)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Kill-switch'i manuel sıfırla (insan onayı gerekli)",
    )
    args = parser.parse_args()

    if args.reset:
        confirm = input(
            "Kill-switch'i sıfırlamak istediğini onayla — 'YES' yaz: "
        ).strip()
        if confirm == "YES":
            _reset_kill_switch()
            send_telegram("Kill-switch manuel olarak sıfırlandı.", level="WARNING")
            print("Kill-switch sıfırlandı.")
        else:
            print("İptal edildi.")
        return

    if args.once:
        result = poll_once()
        import json
        print(json.dumps(result, indent=2, default=str))
        return

    # Sürekli watchdog
    logger.info(
        "breaker_monitor.watchdog_start",
        extra={"poll_interval_s": POLL_INTERVAL, "dry_run": _is_dry_run()},
    )
    send_telegram(
        f"Breaker Monitor başlatıldı. Poll aralığı: {POLL_INTERVAL}s",
        level="INFO",
    )

    iteration = 0
    while True:
        iteration += 1
        try:
            poll_once()
        except Exception as exc:
            logger.error(
                "breaker_monitor.poll_error",
                extra={"iteration": iteration, "err": str(exc)[:300]},
            )
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
