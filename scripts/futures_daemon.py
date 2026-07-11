"""Futures Testnet REAL-TIME DAEMON — Binance USDM Futures Testnet sürekli paper trading.

Modes:
  --timeframe 1d  (default): Günlük 1d bar close bazlı tarama
  --timeframe 15m           : 15 dakikalık intraday bar-close loop

1d Loops:
  - SIGNAL SCAN: günde 1 (yeni 1d bar formed olduğunda)
  - POSITION CHECK: her 60 saniye (TP/SL fill detection + trailing)
  - EQUITY SNAPSHOT: her 5 dakika (dashboard live update)

15m Loops:
  - SIGNAL SCAN: her 15 dakikada bir (bar-close + 5s buffer)
  - POSITION MONITOR: her bar'da (pyramid trigger detection)
  - DMS HEARTBEAT: her tick (20s TF_DMS_PARAMS["15m"])

LONG + SHORT ikisi de calisir (futures'ta margin var).

Usage:
    python scripts/futures_daemon.py                       # 1d mode, arka planda
    python scripts/futures_daemon.py --once               # 1d, tek seferlik
    python scripts/futures_daemon.py --timeframe 15m      # 15m intraday mode
    python scripts/futures_daemon.py --timeframe 15m --once  # 15m, tek seferlik
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal as _signal
import sys
import time
import traceback as _traceback
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings

warnings.filterwarnings("ignore")

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from price_action.execution.slippage_tracker import execution_evidence_values_match
from price_action.runtime_paths import resolve_runtime_root

RUNTIME_ROOT = resolve_runtime_root(ROOT)
DATA_DIR = RUNTIME_ROOT / "data"
LOGS_DIR = RUNTIME_ROOT / "logs"
MARKET_DB = (
    Path(os.environ.get("DUCKDB_PATH", str(DATA_DIR / "market.duckdb"))).expanduser().resolve()
)

# KALAN_ISLER #8 (2026-07-10): borsa-okuma "başarı-şekilli boş dönüş" görünürlüğü.
# Saf-stdlib hafif sayaç modülü — kontrol akışına dokunmaz (bkz. degraded_reads.py).
from scripts.lib.degraded_reads import (
    record_degraded_read,
    total_degraded_reads,
)

# Multi-bot futures support
# FIX 2026-05-27 (Faz 14.25): generic — herhangi bir bot adına izin ver.
# FIX 2026-05-27 (Faz 14.26): idempotency + pyramid_store + DMS DB'leri de per-bot.
#   Önceki bug: PA_BOT_NAME sadece journal/log/state ayırıyordu, ama
#   idempotency.duckdb ve pyramid_store.duckdb shared kalmıştı → ikinci bot
#   startup'ta DuckDB lock conflict, DMS init fail (kritik güvenlik açığı).
_BOT_NAME = os.environ.get("PA_BOT_NAME", "").lower().strip()
if _BOT_NAME and _BOT_NAME not in ("default", ""):
    # Generic: PA_BOT_NAME=rsi2 → futures_journal_rsi2.duckdb
    JOURNAL = DATA_DIR / f"futures_journal_{_BOT_NAME}.duckdb"
    LOG_FILE = LOGS_DIR / f"futures_daemon_{_BOT_NAME}.log"
    LAST_SCAN_STATE = LOGS_DIR / "state" / f"futures_last_scan_{_BOT_NAME}.txt"
    IDEMPOTENCY_DB = DATA_DIR / f"idempotency_{_BOT_NAME}.duckdb"
    PYRAMID_STORE_DB = DATA_DIR / f"pyramid_store_{_BOT_NAME}.duckdb"
    # FIX 2026-06-10 (v14 audit BLOCKER-2): breaker state de bot-bazlı olmalı.
    # Önceden iki yerde hardcoded "futures_breaker_state_15m_phoenix.json" idi →
    # yeni bot (v14) eski botun daily_anchor/triggered watermark'larını miras
    # alıyordu (d04/w08 eşikleri d02/w05 anchor'ı üstünde yanlış hesap).
    BREAKER_STATE_15M = LOGS_DIR / "risk" / f"futures_breaker_state_15m_{_BOT_NAME}.json"
else:
    JOURNAL = DATA_DIR / "futures_journal.duckdb"
    LOG_FILE = LOGS_DIR / "futures_daemon.log"
    LAST_SCAN_STATE = LOGS_DIR / "state" / "futures_last_scan.txt"
    IDEMPOTENCY_DB = DATA_DIR / "idempotency.duckdb"
    PYRAMID_STORE_DB = DATA_DIR / "pyramid_store.duckdb"
    # Backward-compat: PA_BOT_NAME yokken eski path korunur (çalışan botlar etkilenmez)
    BREAKER_STATE_15M = LOGS_DIR / "risk" / "futures_breaker_state_15m_phoenix.json"
KILL_SWITCH_PATH = LOGS_DIR / "kill_switch.json"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
LAST_SCAN_STATE.parent.mkdir(parents=True, exist_ok=True)


# WIRE-widestop (2026-05-22): 15m risk config path — env-overridable.
# Default = c2v5 final (live behavior UNCHANGED). To run the wide-stop deploy
# candidate in paper/shadow without any code change:
#   PA_15M_CONFIG=configs/risk_phoenix_scalp_15m_widestop.yaml \
#       python scripts/futures_daemon.py --timeframe 15m
# Rollback = unset PA_15M_CONFIG. See DEPLOY_widestop_15m.md.
def _risk_config_15m() -> Path:
    """Resolve the active 15m risk config (PA_15M_CONFIG override or c2v5)."""
    _override = os.environ.get("PA_15M_CONFIG", "").strip()
    if _override:
        _p = Path(_override)
        return _p if _p.is_absolute() else (ROOT / _p)
    return ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"


def _risk_config_5m() -> Path:
    """Resolve the active 5m risk config (PA_5M_CONFIG override or P1c default).

    Default: configs/risk_phoenix_scalp_5m_p1c.yaml (Faz 5 P1c deploy candidate)
    Override: PA_5M_CONFIG env var
    """
    _override = os.environ.get("PA_5M_CONFIG", "").strip()
    if _override:
        _p = Path(_override)
        return _p if _p.is_absolute() else (ROOT / _p)
    return ROOT / "configs" / "risk_phoenix_scalp_5m_p1c.yaml"


# FIX 2026-05-26 (Faz 14.9): pyramid_enabled gate — cached.
# Önceki bug: widestop_vsa2 config'inde strategy_portfolio.pyramid_enabled=false
# olmasına rağmen daemon her POS_CHECK tick'inde pyramid_store'dan eski L2 PENDING
# leg'i yükleyip submit etmeye çalışıyordu → Binance -1007 timeout sonsuz retry.
# Kök neden: _get_pyramid_router() ve POS_CHECK loop bu flag'i hiç okumuyordu.
_PYRAMID_ENABLED_CACHE: dict[str, bool] = {}

# FIX 2026-06-10 (XRP 02:15Z): orphan-cancel N-ardışık-tick stateful teyit.
# Anahtar "SYMBOL|algoId" → ardışık orphan-görünüm tick sayısı. Pozisyon tek
# tick'te bile görünse sıfırlanır. ORPHAN_CONFIRM_TICKS tick (~45dk) üst üste
# orphan görünmeden iptal YAPILMAZ (double-stale-read deliği kapanışı).
_ORPHAN_SUSPECT_TICKS: dict[str, int] = {}
ORPHAN_CONFIRM_TICKS = 3

# FIX 2026-06-12 (INC5 devamı): journal self-heal sayacı — 'filled' kalmış
# kayıt, borsada pozisyon+SL yokken HEAL_CONFIRM_TICKS ardışık tick görülürse
# 'closed' yapılır.
# FIX 2026-07-08 (W1-CRIT, dalga-3): eşik 2→3 + adlandırılmış sabit. 2 bayat
# tick'te false-close → gerçek kapanış idempotency'ye takılır + SL orphan-iptal
# → çıplak kaskad. Orphan-cancel'daki 3-tick disipliniyle hizalandı.
_JOURNAL_HEAL_TICKS: dict[str, int] = {}
HEAL_CONFIRM_TICKS = 3

# T2-02 (2026-07-10): kaldıraç MUTLAK tavanı — son-savunma. Birincil kaynak
# RiskOfficer (yaml leverage.max_leverage_per_symbol); bu sabit yaml/karar ne
# derse desin aşılamayan hard-cap. yaml != cap ise startup LEV_CAP_MISMATCH loglar.
_LEV_HARD_CAP = 3

# Deferred-entry ile protection watchdog aynı pozisyonu ilk kez gördüğünde
# iki ayrı writer gibi davranmamalı. Queue kaydının sahibi retry processor'dür;
# watchdog bu lease boyunca entry-price heal/market-close/SL mutation yapmaz.
# Lease, queue metadata'sı bozuk veya aşırı büyük olsa bile sonludur: sonsuz
# stale satır gerçek bir çıplak pozisyonun watchdog'unu kalıcı susturamaz.
_PENDING_PROTECTION_LEASE_DEFAULT_SECONDS = 120.0
_PENDING_PROTECTION_LEASE_MAX_SECONDS = 300.0
_PENDING_PROTECTION_MAX_FUTURE_SKEW_SECONDS = 30.0
_PENDING_QUEUE_READ_FAIL_CLOSED_TICKS = 2
_pending_queue_read_fail_ticks = 0
PROTECTION_FINALIZE_QUEUE = DATA_DIR / "protection_finalizations.jsonl"


def _normalize_pending_symbol(value: object) -> str:
    """Normalize CCXT/journal/algo symbol spellings to e.g. ``BTCUSDT``."""
    symbol = str(value or "").strip().upper()
    if ":" in symbol:
        symbol = symbol.split(":", 1)[0]
    return symbol.replace("/", "").replace("-", "")


def _normalize_pending_side(value: object) -> str:
    side = str(value or "").strip().lower()
    return {"buy": "long", "sell": "short"}.get(side, side)


def _normalize_pending_bot(value: object) -> str:
    bot_name = str(value or "").strip().lower()
    return "" if bot_name in ("", "default") else bot_name


def _has_existing_symbol_position(positions: object, symbol: object) -> bool:
    """Return true when a nonzero net position already owns this symbol."""
    if not isinstance(positions, list):
        return False
    wanted = _normalize_pending_symbol(symbol)
    for position in positions:
        if not isinstance(position, dict):
            continue
        try:
            contracts = abs(float(position.get("contracts", 0) or 0))
        except (TypeError, ValueError):
            # Invalid quantity is not proof that ownership is zero.
            return True
        if _normalize_pending_symbol(position.get("symbol")) == wanted and contracts > 1e-9:
            return True
    return False


def _positive_pending_price(value: object) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if 0 < price < float("inf") else None


def _pending_retry_watchdog_intent(
    entry: dict,
    position_symbol: str,
    position_side: str,
    *,
    position_contracts: float | None = None,
    position_entry_price: float | None = None,
    position_update_time_ms: float | None = None,
    now: datetime | None = None,
) -> dict | None:
    """Return a bounded protection-ownership contract for one position.

    Old queue rows did not carry the explicit ``protection_owner`` fields, so a
    deterministic client/order id remains a valid ownership proof. A matching
    row without both original SL and TP is deliberately ignored: incomplete
    intent metadata must not suppress the last-resort watchdog.
    """
    if not isinstance(entry, dict):
        return None
    if str(entry.get("tf") or "15m").lower() != "15m":
        return None
    if _normalize_pending_symbol(entry.get("symbol")) != _normalize_pending_symbol(position_symbol):
        return None
    if _normalize_pending_side(entry.get("side")) != _normalize_pending_side(position_side):
        return None
    # New rows are bot-scoped. Missing field remains accepted solely for old
    # queue compatibility; an explicit different bot can never own our position.
    if "bot_name" in entry and _normalize_pending_bot(entry.get("bot_name")) != (
        _normalize_pending_bot(_BOT_NAME)
    ):
        return None
    owner = str(entry.get("protection_owner") or "pending_retry_processor").strip()
    if owner not in {"pending_retry_processor", "protection_finalize_processor"}:
        return None

    sl_price = _positive_pending_price(entry.get("sl_price"))
    tp_price = _positive_pending_price(entry.get("tp_price"))
    if sl_price is None or tp_price is None:
        return None
    entry_price = _positive_pending_price(entry.get("entry_px"))
    normalized_side = _normalize_pending_side(entry.get("side"))
    if entry_price is not None:
        levels_valid = (
            sl_price < entry_price < tp_price
            if normalized_side == "long"
            else tp_price < entry_price < sl_price
        )
        if not levels_valid:
            return None

    owner_id = str(
        entry.get("protection_intent_id")
        or entry.get("client_order_id")
        or entry.get("submitted_order_id")
        or ""
    ).strip()
    if not owner_id:
        known_ids = entry.get("known_order_ids")
        if isinstance(known_ids, list):
            owner_id = next(
                (
                    str(value).strip()
                    for value in known_ids
                    if value is not None and str(value).strip()
                ),
                "",
            )
    if not owner_id:
        return None

    generation_state = "not_applicable"
    generation = entry.get("position_generation")
    if owner == "protection_finalize_processor" and not isinstance(generation, dict):
        # A protection-finalize row is allowed to suppress the watchdog only
        # while its position generation can be proved.  Treat missing legacy
        # or malformed identity as uncertain ownership: hold during the short
        # processor lease, then ignore the stale intent instead of applying
        # its old SL/TP to a later same-symbol position.
        generation_state = "unverifiable"
    elif owner == "protection_finalize_processor":
        try:
            if generation.get("schema_version") != 1:
                raise ValueError("invalid generation schema")
            if _normalize_pending_symbol(generation.get("symbol")) != (
                _normalize_pending_symbol(entry.get("symbol"))
            ):
                raise ValueError("generation symbol mismatch")
            if _normalize_pending_side(generation.get("side")) != normalized_side:
                raise ValueError("generation side mismatch")
            for field in ("initial_quantity", "initial_entry_price", "verified_at_ms"):
                if isinstance(generation.get(field), bool):
                    raise ValueError(f"boolean generation {field}")
            generation_qty = float(generation["initial_quantity"])
            generation_entry = float(generation["initial_entry_price"])
            generation_verified_ms = float(generation["verified_at_ms"])
            current_qty = abs(float(position_contracts))
            current_entry = float(position_entry_price)
        except (KeyError, TypeError, ValueError):
            generation_state = "unverifiable"
        else:
            if not all(
                math.isfinite(value) and value > 0
                for value in (
                    generation_qty,
                    generation_entry,
                    generation_verified_ms,
                )
            ):
                generation_state = "unverifiable"
            elif not math.isfinite(current_qty) or current_qty <= 0:
                return None
            elif not math.isfinite(current_entry) or current_entry <= 0:
                generation_state = "unverifiable"
            elif current_qty > generation_qty * (1.0 + 1e-7) or not math.isclose(
                current_entry,
                generation_entry,
                rel_tol=1e-7,
                abs_tol=1e-10,
            ):
                return None
            else:
                try:
                    if isinstance(position_update_time_ms, bool):
                        raise ValueError("boolean position update time")
                    current_update_ms = float(position_update_time_ms)
                except (TypeError, ValueError):
                    current_update_ms = 0.0
                if not math.isfinite(current_update_ms) or current_update_ms <= 0:
                    generation_state = "unverifiable"
                elif current_update_ms > generation_verified_ms + 2_000:
                    return None
                else:
                    generation_state = "match"

    # When the enqueue path captured a pre-submit position baseline, require an
    # actual exchange-position delta in the intended direction. This prevents
    # a timed-out *unfilled* order from claiming an older same-symbol position.
    baseline_raw = entry.get("pre_submit_position_qty")
    if baseline_raw is not None and position_contracts is not None:
        try:
            baseline_qty = float(baseline_raw)
            contracts = abs(float(position_contracts))
        except (TypeError, ValueError):
            return None
        side_sign = 1.0 if _normalize_pending_side(position_side) == "long" else -1.0
        current_signed_qty = contracts * side_sign
        if (current_signed_qty - baseline_qty) * side_sign <= 1e-9:
            return None

    try:
        created_at = datetime.fromisoformat(str(entry["ts"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    else:
        created_at = created_at.astimezone(UTC)

    try:
        requested_lease = float(
            entry.get(
                "watchdog_protection_lease_seconds",
                entry.get("max_age_seconds", _PENDING_PROTECTION_LEASE_DEFAULT_SECONDS),
            )
        )
    except (TypeError, ValueError):
        requested_lease = _PENDING_PROTECTION_LEASE_DEFAULT_SECONDS
    if requested_lease <= 0 or requested_lease != requested_lease:  # NaN
        requested_lease = _PENDING_PROTECTION_LEASE_DEFAULT_SECONDS
    lease_seconds = min(requested_lease, _PENDING_PROTECTION_LEASE_MAX_SECONDS)
    now_utc = now or datetime.now(UTC)
    now_utc = now_utc.replace(tzinfo=UTC) if now_utc.tzinfo is None else now_utc.astimezone(UTC)
    # A far-future timestamp would renew the lease on every stateless read.
    # Reject it; small scheduler/host skew remains tolerated.
    if (created_at - now_utc).total_seconds() > _PENDING_PROTECTION_MAX_FUTURE_SKEW_SECONDS:
        return None
    lease_deadline = created_at + timedelta(seconds=lease_seconds)

    raw_known_ids = entry.get("known_order_ids")
    known_order_ids = list(raw_known_ids) if isinstance(raw_known_ids, list) else []

    return {
        "owner": owner,
        "owner_id": owner_id,
        "symbol": entry.get("symbol"),
        "side": normalized_side,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "created_at": created_at,
        "lease_deadline": lease_deadline,
        "lease_seconds": lease_seconds,
        "lease_active": now_utc <= lease_deadline,
        "known_order_ids": known_order_ids,
        "submitted_order_id": entry.get("submitted_order_id"),
        "reconcile_only": bool(entry.get("reconcile_only", False)),
        "generation_state": generation_state,
    }


def _read_pending_retry_entries(path: Path | None = None) -> tuple[list[dict], str | None]:
    """Read entry and protection ownership queues under their stable locks."""
    queue_paths = (
        [path]
        if path is not None
        else [DATA_DIR / "pending_retries.jsonl", PROTECTION_FINALIZE_QUEUE]
    )
    raw_lines: list[str] = []
    read_errors: list[str] = []
    from scripts.process_pending_entries import _read_queue_snapshot

    for queue_path in queue_paths:
        try:
            raw_lines.extend(_read_queue_snapshot(queue_path))
        except Exception as exc:
            read_errors.append(f"{queue_path.name}:{type(exc).__name__}: {str(exc)[:100]}")
    if read_errors:
        return [], "; ".join(read_errors)

    entries: list[dict] = []
    parse_failures = 0
    for raw in raw_lines:
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            parse_failures += 1
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
        else:
            parse_failures += 1
    if parse_failures:
        return entries, f"queue_parse_failures={parse_failures}"
    return entries, None


def _pending_retry_intent_for_position(
    entries: list[dict],
    position_symbol: str,
    position_side: str,
    *,
    position_contracts: float | None = None,
    position_entry_price: float | None = None,
    position_update_time_ms: float | None = None,
    now: datetime | None = None,
) -> dict | None:
    """Choose the newest matching queue owner deterministically."""
    matches = [
        intent
        for entry in entries
        if (
            intent := _pending_retry_watchdog_intent(
                entry,
                position_symbol,
                position_side,
                position_contracts=position_contracts,
                position_entry_price=position_entry_price,
                position_update_time_ms=position_update_time_ms,
                now=now,
            )
        )
        is not None
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: (item["created_at"], item["owner_id"]))


def _pending_retry_watchdog_action(
    intent: dict | None, *, queue_read_fail_closed: bool = False
) -> str:
    """Single ownership decision consumed by the mutation-heavy watchdog loop."""
    if queue_read_fail_closed:
        return "hold_queue_uncertain"
    if intent is not None and bool(intent.get("lease_active")):
        return "hold_processor_owned"
    if intent is not None and intent.get("generation_state") == "unverifiable":
        return "watchdog_normal_ignore_intent"
    if intent is not None:
        return "watchdog_takeover_original_levels"
    return "watchdog_normal"


def _known_order_ids_from_ack(order: dict | None) -> list[str]:
    """Collect every exchange order id carried by a direct or mixed-fill ACK."""
    if not isinstance(order, dict):
        return []
    order_ids: list[str] = []

    def _add(value) -> None:
        order_id = str(value or "").strip()
        if order_id and order_id not in order_ids:
            order_ids.append(order_id)

    for key in ("id", "partial_limit_order_id", "market_fallback_order_id"):
        _add(order.get(key))
    resolved = order.get("resolved_order_ids")
    if isinstance(resolved, list):
        for value in resolved:
            _add(value)
    legs = order.get("fill_legs")
    if isinstance(legs, list):
        for leg in legs:
            if isinstance(leg, dict):
                _add(leg.get("id"))
    return order_ids


def _build_pending_retry_entry(
    sig: dict,
    *,
    qty: float,
    entry_px: float,
    leverage: int,
    client_order_id: str,
    orig_error: str,
    pre_submit_position_qty: float | None,
    pre_submit_position_entry_price: float | None,
    order: dict | None = None,
    known_order_ids: list[str] | None = None,
    reconcile_only: bool = False,
) -> dict:
    """Build the durable hand-off shared by timeout and delayed-fill paths."""
    all_order_ids = _known_order_ids_from_ack(order)
    for value in known_order_ids or []:
        order_id = str(value or "").strip()
        if order_id and order_id not in all_order_ids:
            all_order_ids.append(order_id)

    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "tf": "15m",
        "symbol": sig["symbol"],
        "strategy": sig.get("strategy", ""),
        "side": sig["side"],
        "qty": qty,
        "entry_px": entry_px,
        "sl_price": sig.get("sl_price"),
        "tp_price": sig.get("tp_price"),
        "leverage": leverage,
        "client_order_id": client_order_id,
        "attempts": 0,
        "max_attempts": 2,
        # Two independent terminal-no-fill observations require two minute
        # ticks. 180s leaves one full cron interval of jitter/headroom without
        # permitting an indefinitely stale market entry.
        "max_age_seconds": 180,
        "orig_error": orig_error,
        "bot_name": os.environ.get("PA_BOT_NAME", ""),
        "journal_db": str(JOURNAL),
        "idempotency_db": str(IDEMPOTENCY_DB),
        "slippage_db": str(DATA_DIR / "execution_fills.duckdb"),
        "pre_submit_position_qty": pre_submit_position_qty,
        "pre_submit_position_entry_price": pre_submit_position_entry_price,
        # Explicit cross-process protection ownership. Older rows are inferred
        # from client/order ids by _pending_retry_watchdog_intent().
        "protection_owner": "pending_retry_processor",
        "protection_intent_id": client_order_id,
        "watchdog_protection_lease_seconds": (_PENDING_PROTECTION_LEASE_DEFAULT_SECONDS),
    }
    if all_order_ids:
        entry["known_order_ids"] = all_order_ids
        entry["submitted_order_id"] = all_order_ids[0]
    if reconcile_only:
        entry.update(
            {
                "reconcile_only": True,
                "terminal_no_fill_confirmations_required": 2,
                "uncertain_client_order_ids": [client_order_id],
                "submit_uncertainty": {
                    "stage": "immediate_submit_fill_unverified",
                    "main_client_order_id": client_order_id,
                    "fallback_client_order_id": None,
                    "partial_order_id": (
                        str((order or {}).get("partial_limit_order_id") or "") or None
                    ),
                    "partial_qty": float((order or {}).get("partial_limit_qty") or 0.0),
                    "remaining_qty": 0.0,
                },
            }
        )
    return entry


def _enqueue_pending_retry(entry: dict, path: Path | None = None) -> str:
    """Lock-safe queue append shared with the external retry processor."""
    from scripts.process_pending_entries import append_pending_entry

    return append_pending_entry(path or (DATA_DIR / "pending_retries.jsonl"), entry)


def _replace_pending_retry(entry: dict, exact_line: str, path: Path | None = None) -> str:
    """Persist an in-flight entry state transition on its existing WAL row."""
    from scripts.process_pending_entries import _persist_ack_transition

    return _persist_ack_transition(path or (DATA_DIR / "pending_retries.jsonl"), exact_line, entry)


def _remove_pending_retry(exact_line: str, path: Path | None = None) -> None:
    """Remove a handed-off entry WAL row without losing concurrent appends."""
    from scripts.process_pending_entries import remove_pending_entry

    remove_pending_entry(path or (DATA_DIR / "pending_retries.jsonl"), exact_line)


def _transition_pending_retry_to_no_submit(
    entry: dict,
    exact_line: str,
    *,
    reason: str,
    path: Path | None = None,
    updates: dict | None = None,
) -> str:
    """Persist the no-submit state before retirement or queue hand-off.

    Deletion is cleanup, not the safety transition.  If deletion later races or
    crashes, the surviving row can only reconcile the deterministic order IDs;
    it can never create a fresh market entry.
    """
    entry.update(updates or {})
    entry.update(
        {
            "reconcile_only": True,
            "entry_submit_allowed": False,
            "direct_submit_lease_until": datetime.now(UTC).isoformat(),
            "no_submit_reason": str(reason),
        }
    )
    return _replace_pending_retry(entry, exact_line, path)


def _build_protection_finalize_entry(
    sig: dict,
    *,
    exchange,
    client_order_id: str,
    order: dict,
    fill_method: str,
    entry_execution_evidence: dict,
    fill_qty: float,
    fill_price: float,
    fill_notional: float,
    fill_source: str,
    leverage: int,
    signal_id: str,
    protection_id: str,
    protection_plan: dict,
    known_order_ids: list[str] | None = None,
) -> dict:
    """Build the no-entry-submit WAL for one exchange-verified fill."""
    if not client_order_id or not signal_id or not protection_id:
        raise ValueError("protection finalize identity is incomplete")
    for field, value in {
        "fill_qty": fill_qty,
        "fill_price": fill_price,
        "fill_notional": fill_notional,
    }.items():
        parsed = float(value)
        if not (0 < parsed < float("inf")):
            raise ValueError(f"{field} must be finite and > 0")
    order_ids = _known_order_ids_from_ack(order)
    for value in known_order_ids or []:
        normalized = str(value or "").strip()
        if normalized and normalized not in order_ids:
            order_ids.append(normalized)
    journal_order_id = str(order.get("id") or ",".join(order_ids)).strip()
    verified_at = datetime.now(UTC)
    execution_outcome = order.get("slippage_breach")
    if not isinstance(entry_execution_evidence, dict):
        raise ValueError("entry execution evidence must be an object")
    try:
        evidence_qty = float(entry_execution_evidence["quantity"])
        evidence_notional = float(entry_execution_evidence["notional_usdt"])
        expected_price = float(entry_execution_evidence["expected_price"])
        realized_price = float(entry_execution_evidence["realized_price"])
        maker_qty = float(entry_execution_evidence["maker_quantity"])
        maker_notional = float(entry_execution_evidence["maker_notional_usdt"])
        fee_value = entry_execution_evidence.get("fee_usdt")
        fee_value = float(fee_value) if fee_value is not None else None
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("entry execution evidence numerics are invalid") from exc
    if (
        entry_execution_evidence.get("schema_version") != 1
        or not all(
            math.isfinite(value) and value > 0
            for value in (evidence_qty, evidence_notional, expected_price, realized_price)
        )
        or not math.isclose(evidence_qty, float(fill_qty), rel_tol=1e-12)
        or not math.isclose(evidence_notional, float(fill_notional), rel_tol=1e-12)
        or not (0 <= maker_qty <= evidence_qty)
        or not (0 <= maker_notional <= evidence_notional)
        or (fee_value is not None and not math.isfinite(fee_value))
        or str(entry_execution_evidence.get("fill_method")) != str(fill_method)
        or not str(entry_execution_evidence.get("fee_source") or "").strip()
        or not str(entry_execution_evidence.get("order_type") or "").strip()
        or not isinstance(entry_execution_evidence.get("is_maker"), bool)
    ):
        raise ValueError("entry execution evidence does not match verified fill")
    if execution_outcome is not None:
        if not isinstance(execution_outcome, dict):
            raise ValueError("entry execution outcome must be an object")
        expected_side = "buy" if str(sig["side"]).lower() == "long" else "sell"
        if (
            execution_outcome.get("schema_version") != 1
            or execution_outcome.get("outcome_type") != "slippage_breach"
            or execution_outcome.get("disposition") != "protect_position"
            or execution_outcome.get("position_owned") is not True
            or execution_outcome.get("protection_required") is not True
            or execution_outcome.get("unwind_attempted") is not False
            or execution_outcome.get("fill_evidence_verified") is not True
            or str(execution_outcome.get("symbol")) != str(sig["symbol"])
            or str(execution_outcome.get("entry_side")).lower() != expected_side
            or not math.isfinite(float(execution_outcome.get("slippage_bps")))
            or not math.isfinite(float(execution_outcome.get("limit_bps")))
            or float(execution_outcome.get("slippage_bps"))
            <= float(execution_outcome.get("limit_bps"))
            or not execution_evidence_values_match(
                execution_outcome.get("owned_quantity"), fill_qty
            )
            or not execution_evidence_values_match(
                execution_outcome.get("owned_average"), fill_price
            )
        ):
            raise ValueError("slippage breach ownership does not match verified fill")

    work = {
        "schema_version": 1,
        "work_type": "finalize_verified_fill_v1",
        "work_id": client_order_id,
        "ts": datetime.now(UTC).isoformat(),
        "signal_ts": str(sig.get("bar_close_ts") or sig.get("ts") or ""),
        "tf": "15m",
        "bot_name": os.environ.get("PA_BOT_NAME", ""),
        "symbol": sig["symbol"],
        "strategy": sig.get("strategy", ""),
        "side": sig["side"],
        "qty": float(fill_qty),
        "entry_px": float(fill_price),
        "sl_price": float(sig["sl_price"]),
        "tp_price": float(sig["tp_price"]),
        "leverage": int(leverage),
        "confluence": float(sig.get("confluence", 0.0)),
        "entry_fill_method": str(fill_method),
        "entry_execution_outcome": execution_outcome,
        "entry_execution_evidence": entry_execution_evidence,
        "client_order_id": client_order_id,
        "known_order_ids": order_ids,
        "journal_order_id": journal_order_id,
        "journal_db": str(JOURNAL),
        "idempotency_db": str(IDEMPOTENCY_DB),
        "slippage_db": str(DATA_DIR / "execution_fills.duckdb"),
        "journal_signal_id": signal_id,
        "journal_protection_id": protection_id,
        "entry_submit_allowed": False,
        "reconcile_only": True,
        "protection_owner": "protection_finalize_processor",
        "protection_intent_id": protection_plan["protection_key"],
        "protection_state": "intent_persisted",
        "watchdog_protection_lease_seconds": (_PENDING_PROTECTION_LEASE_DEFAULT_SECONDS),
        "protection_plan": protection_plan,
        "fill_evidence": {
            "verified": True,
            "verified_at": verified_at.isoformat(),
            "verified_at_ms": int(verified_at.timestamp() * 1000),
            "source": fill_source,
            "qty": float(fill_qty),
            "average": float(fill_price),
            "notional_usdt": float(fill_notional),
            "order_ids": order_ids,
        },
        "position_generation": {
            "schema_version": 1,
            "symbol": sig["symbol"],
            "side": sig["side"],
            "initial_quantity": float(fill_qty),
            "initial_entry_price": float(fill_price),
            "verified_at_ms": int(verified_at.timestamp() * 1000),
        },
        "finalize_attempts": 0,
    }
    _validate_protection_work_plan(exchange, work)
    work["protection_binding_sha256"] = _protection_work_binding_sha256(work)
    return work


def _validate_protection_work_plan(exchange, work: dict) -> dict:
    """Prove a WAL plan is canonical for its independently stored fill facts."""
    from scripts.futures_trade_daily import validate_protection_plan_for_intent

    return validate_protection_plan_for_intent(
        exchange,
        work["protection_plan"],
        symbol=str(work["symbol"]),
        side=str(work["side"]),
        qty=float(work["fill_evidence"]["qty"]),
        tp_price=float(work["tp_price"]),
        sl_price=float(work["sl_price"]),
        entry_price=float(work["fill_evidence"]["average"]),
        protection_key=str(work["client_order_id"]),
    )


def _protection_work_binding_sha256(work: dict) -> str:
    from scripts.futures_trade_daily import protection_plan_intent_binding_sha256

    fill = work["fill_evidence"]
    return protection_plan_intent_binding_sha256(
        work["protection_plan"],
        entry_client_order_id=str(work["client_order_id"]),
        symbol=str(work["symbol"]),
        side=str(work["side"]),
        qty=float(fill["qty"]),
        entry_price=float(fill["average"]),
        tp_price=float(work["tp_price"]),
        sl_price=float(work["sl_price"]),
    )


def _validate_protection_work_binding(work: dict) -> None:
    expected = _protection_work_binding_sha256(work)
    if str(work.get("protection_binding_sha256") or "") != expected:
        raise ValueError("protection work semantic binding mismatch")


def _execute_protection_with_wal(
    exchange,
    work: dict,
    *,
    queue_path: Path = PROTECTION_FINALIZE_QUEUE,
) -> tuple[dict, bool, str | None]:
    """Fsync the finalize intent before the first protection side effect."""
    from scripts.futures_trade_daily import (
        ensure_protection_plan_sl,
        execute_protection_plan,
    )
    from scripts.process_pending_entries import append_pending_entry

    _validate_protection_work_binding(work)
    try:
        append_pending_entry(queue_path, work)
    except Exception as exc:
        # Without a durable replay owner, only the canonical SL may be touched.
        # Creating TP legs here would re-open the original crash window.
        sl_result = ensure_protection_plan_sl(exchange, work["protection_plan"])
        return sl_result, False, f"{type(exc).__name__}: {str(exc)[:160]}"
    return execute_protection_plan(exchange, work["protection_plan"]), True, None


def _pyramid_enabled_15m() -> bool:
    """15m active config'de strategy_portfolio.pyramid_enabled değerini döner.

    Cache: process-lifetime; config değişirse daemon restart gerek.
    """
    cache_key = "15m"
    if cache_key in _PYRAMID_ENABLED_CACHE:
        return _PYRAMID_ENABLED_CACHE[cache_key]
    try:
        import yaml as _yaml_pe

        _path = _risk_config_15m()
        with open(_path, encoding="utf-8") as _pe_f:
            _cfg = _yaml_pe.safe_load(_pe_f) or {}
        _pe_raw = _cfg.get("strategy_portfolio", {}).get("pyramid_enabled")
        if _pe_raw is None:
            # FAIL-CLOSED (T2-05, 2026-07-10 Principal onayı): anahtar YOKSA
            # pyramid KAPALI varsay (eski default True = anahtar-eksik config'te
            # sessizce pyramid açılırdı). v15p2 anahtarı açıkça false → parite.
            log("PYRAMID_KEY_MISSING: pyramid_enabled anahtarı yok — FAIL-CLOSED (False)")
            _enabled = False
        else:
            _enabled = bool(_pe_raw)
    except Exception as _pe_err:
        # FAIL-CLOSED: config okunamıyorsa pyramid AÇMA (eski: True = fail-open).
        log(f"PYRAMID_CFG_FAIL: {str(_pe_err)[:80]} — FAIL-CLOSED (False)")
        _enabled = False
    if _enabled:
        # The shared post-only router now exposes typed uncertain/unverified
        # ownership.  Pyramid additions do not yet have the entry/protection
        # WAL used by normal 15m entries, so any enabled legacy config is held
        # before router construction or exchange I/O.  v15p2 is already OFF.
        log(
            "PYRAMID_EXECUTION_DISABLED: config ON ama crash-complete "
            "submit/protection WAL yok — FAIL-CLOSED (False)"
        )
        _enabled = False
    _PYRAMID_ENABLED_CACHE[cache_key] = _enabled
    return _enabled


def _load_last_scan_date() -> date | None:
    """Restart'a dayanıklı: son başarılı DAILY_SCAN tarihini oku."""
    if not LAST_SCAN_STATE.exists():
        return None
    try:
        text = LAST_SCAN_STATE.read_text(encoding="utf-8").strip()
        return date.fromisoformat(text) if text else None
    except Exception as exc:
        # FIX 2026-05-26 (H1): silent → stderr log (logger henüz init değil olabilir)
        sys.stderr.write(f"WARN _load_last_scan_date fail: {exc}\n")
        return None


def _save_last_scan_date(d: date) -> None:
    try:
        LAST_SCAN_STATE.write_text(d.isoformat(), encoding="utf-8")
    except Exception as exc:
        # FIX 2026-05-26 (H1): state save fail kritik — daemon restart'ta
        # tarama tekrar yapılır (idempotent değilse double scan)
        sys.stderr.write(f"WARN _save_last_scan_date fail: {exc}\n")


def _kill_switch_active() -> tuple[bool, str]:
    """logs/kill_switch.json oku — halted=true ise daemon durmalı."""
    if not KILL_SWITCH_PATH.exists():
        return False, ""
    try:
        import json as _json

        with open(KILL_SWITCH_PATH, encoding="utf-8") as f:
            ks = _json.load(f)
        if bool(ks.get("halted", False)):
            return True, str(ks.get("reason") or "no reason")
        return False, ""
    except FileNotFoundError:
        return False, ""  # dosya yok = halt yok (normal durum)
    except Exception as exc:
        # FIX 2026-07-07 (denetim MED-12): polarite DÜZELTİLDİ — bozuk/yarım
        # yazılmış kill_switch.json tam da acil-durdurma ANINDA oluşur (torn
        # write). Eski davranış "halted değil" sayıp halt'ın içinden trade
        # ediyordu. Acil fren fail-CLOSED olmalı: parse edilemeyen dosya = HALT.
        sys.stderr.write(f"CRIT _kill_switch_active parse fail (fail-closed → HALT): {exc}\n")
        return True, f"kill_switch.json parse fail (fail-closed): {str(exc)[:100]}"


_LOG_MAX_BYTES = 20 * 1024 * 1024  # 20 MB — yıllık ~250 MB cap


def _rotate_log_if_large(path) -> None:
    """FIX 2026-05-28 (Faz 14.27): basit log rotation.
    Log >20MB ise .1 → .2 → ... rotate. Maksimum 5 backup tutar (.5 silinir).

    FIX 2026-05-28 (audit-Y1): rotation fail SESSİZ değil → stderr'e warn.
    Önceden `except Exception: pass` ile permission/disk-full hatası gizliydi;
    log dosyası unbounded büyür, disk dolar, daemon ileride patlar. Şimdi
    en azından stderr'e (launchd log'una) düşüyor.
    """
    try:
        if not path.exists() or path.stat().st_size < _LOG_MAX_BYTES:
            return
        for i in range(5, 0, -1):
            old = path.with_suffix(path.suffix + f".{i}")
            new = path.with_suffix(path.suffix + f".{i + 1}")
            if i == 5 and old.exists():
                old.unlink()
            elif old.exists():
                old.rename(new)
        path.rename(path.with_suffix(path.suffix + ".1"))
    except Exception as _rot_err:
        # FIX audit-Y1: silent fail → stderr (launchd capture eder)
        try:
            sys.stderr.write(
                f"[WARN] log rotation fail ({path}): {type(_rot_err).__name__}: {_rot_err}\n"
            )
            sys.stderr.flush()
        except Exception:
            pass


def log(msg: str):
    # FIX 2026-05-28 (audit-D2): timestamp'e Z suffix — UTC olduğu net göster.
    # Önceden `[12:45:24]` yazıyordu; kullanıcı TR sanıp 3 saat shift hatası
    # yapabiliyordu (gerçekte 12:45 UTC = 15:45 TR). Şimdi `[12:45:24Z]`.
    ts = datetime.now(UTC).strftime("%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    # FIX 2026-05-26 (C1): flush + fsync — crash sonrası log kaybını önler.
    # Önceki versiyon Python buffer'da bırakıyordu; SIGKILL/OOM sonrası son
    # N satır disk'e yazılmamış kalıyordu (post-mortem yapılamıyordu).
    # FIX 2026-05-28 (Faz 14.27): log rotation — disk doldurma riski azalt.
    try:
        _rotate_log_if_large(LOG_FILE)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())  # kernel buffer → disk garantili
            except OSError:
                pass  # bazı dosya sistemleri fsync desteklemez
    except Exception:
        pass
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:
        pass


_last_signal_scan_date = _load_last_scan_date()  # restart-persistent (sadece günde 1 tarama)

# Dead Man's Switch instance (daemon başladığında set edilir)
_dms = None

# 15m main loop is single-threaded and keeps one CCXT client for its lifetime.
# The DMS intentionally receives a different instance, reserved for emergency
# flatten, so its watchdog thread never races the normal request limiter/state.
_DAEMON_PRIVATE_EXCHANGE = None

_RATE_BUDGET_RESPONSE_HEADERS: tuple[tuple[str, str], ...] = (
    ("x-mbx-used-weight-1m", "used_weight_1m"),
    ("x-mbx-order-count-10s", "order_count_10s"),
    ("x-mbx-order-count-1m", "order_count_1m"),
    ("x-mbx-order-count-1d", "order_count_1d"),
)


def _get_daemon_exchange():
    """Return the registered process-long main client, or a test/legacy fallback."""
    if _DAEMON_PRIVATE_EXCHANGE is not None:
        return _DAEMON_PRIVATE_EXCHANGE
    from scripts.futures_trade_daily import get_futures_exchange

    # Legacy 1d helpers and unit tests do not register a process client. Keep
    # their previous factory semantics; run_15m_mode performs registration.
    return get_futures_exchange()


def _rate_budget_log_line(exchange: object | None) -> str:
    """Format a non-secret, fail-safe snapshot of Binance rate headers."""
    raw_headers = getattr(exchange, "last_response_headers", None)
    headers = (
        {str(key).strip().lower(): value for key, value in raw_headers.items()}
        if isinstance(raw_headers, Mapping)
        else {}
    )
    values: list[str] = []
    for header_name, label in _RATE_BUDGET_RESPONSE_HEADERS:
        parsed = "UNKNOWN"
        raw_value = headers.get(header_name)
        if raw_value is not None and not isinstance(raw_value, bool):
            try:
                numeric = float(str(raw_value).strip())
            except (TypeError, ValueError):
                numeric = float("nan")
            if math.isfinite(numeric) and numeric >= 0 and numeric.is_integer():
                parsed = str(int(numeric))
        values.append(f"{label}={parsed}")
    return "RATE_BUDGET: " + " ".join(values)

# FIX 2026-05-28 (audit-A1): graceful shutdown bayrağı + signal handler.
# Önceki bug: PID 17267 12:45 TR'de sessiz öldü; son log "15M_WAIT", crash log yok.
# Kök neden: signal handler yoktu (SIGTERM/SIGHUP gelince Python cleanup yaptı,
# resource_tracker warning'i stderr'e yazıldı, ama "shutdown" log'u futures_daemon.log'a
# düşmedi) + sleep_until try/except dışındaydı (uyku içi exception görünmüyordu).
_stop_flag: bool = False


def _install_signal_handlers() -> None:
    """SIGTERM / SIGHUP için handler kur — sessiz ölümü engelle.

    SIGINT (Ctrl+C) Python tarafından KeyboardInterrupt'a çevriliyor zaten,
    main loop onu yakalıyor. Burada SIGTERM (kill, launchd unload) ve
    SIGHUP (terminal kapanması) için log + _stop_flag set ediyoruz.
    Main loop her tick başında _stop_flag'i kontrol edip break edecek.
    """

    def _shutdown_handler(signum: int, frame) -> None:  # type: ignore[no-untyped-def]
        global _stop_flag
        try:
            sig_name = _signal.Signals(signum).name
        except Exception:
            sig_name = f"SIG{signum}"
        log(f"SIGNAL_RECEIVED: {sig_name} ({signum}) — graceful shutdown başlıyor")
        _stop_flag = True

    try:
        _signal.signal(_signal.SIGTERM, _shutdown_handler)
    except (ValueError, OSError) as _e:
        sys.stderr.write(f"WARN SIGTERM handler kurulamadı: {_e}\n")
    try:
        # SIGHUP Unix-only; Windows'ta AttributeError olabilir
        _signal.signal(_signal.SIGHUP, _shutdown_handler)
    except (ValueError, OSError, AttributeError) as _e:
        sys.stderr.write(f"WARN SIGHUP handler kurulamadı (Windows normal): {_e}\n")


def _init_dead_mans_switch(exchange):
    """Dead Man's Switch'i exchange ile başlat."""
    global _dms
    try:
        from price_action.execution.dead_mans_switch import DeadMansSwitch

        _dms = DeadMansSwitch(exchange, service_name="futures_daemon", db_path=IDEMPOTENCY_DB)
        _dms.start()
        log("DEAD_MANS_SWITCH: başlatıldı (timeout=300s, heartbeat=60s)")
    except Exception as e:
        # FAIL-CLOSED (2026-07-10): 15m yoluyla tutarlı — DMS'siz koşma yok.
        log(f"DEAD_MANS_SWITCH_INIT_FATAL: {e} — fail-closed, çıkılıyor")
        raise SystemExit(f"DEAD_MANS_SWITCH_INIT_FATAL: {e}") from e


def _dms_ping(state: dict | None = None):
    """Dead Man's Switch heartbeat ping."""
    global _dms
    if _dms is None:
        return
    try:
        equity = float((state or {}).get("wallet_balance", 0))
        n_pos = int((state or {}).get("n_positions", 0))
        _dms.ping(equity_usdt=equity, n_open_positions=n_pos)
    except Exception as _e:
        log(f"DMS_PING_FAIL: {_e}")  # log-only: heartbeat best-effort, akış değişmez


def _utc_naive_timestamp(value):
    """Normalize an aware timestamp for DuckDB's timezone-less TIMESTAMP."""
    if value is not None and getattr(value, "tzinfo", None) is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _write_equity_snapshot(
    state: dict,
    *,
    journal_path: Path | str = JOURNAL,
    snapshot_id: str | None = None,
    snapshot_ts: datetime | None = None,
    notes: str | None = None,
) -> str:
    """Fetch edilmiş hesap durumunu explicit-column ve idempotent yaz."""
    snap_id = snapshot_id or uuid.uuid4().hex[:16]
    snap_ts = snapshot_ts or datetime.now(UTC)
    quality = state.get("positions_ok")
    exchange_complete = state.get("exchange_state_complete")
    if exchange_complete is False:
        quality_note = "exchange_state_complete=false API_STALE"
    elif quality is False:
        quality_note = "positions_ok=false API_STALE"
    elif quality is True:
        quality_note = "positions_ok=true"
    else:
        quality_note = "positions_ok=unknown API_STALE"
    notes = f"{notes} {quality_note}".strip() if notes else quality_note
    # DuckDB TIMESTAMP timezone taşımaz. Aware datetime doğrudan bind edilirse
    # session timezone'a (örn. Europe/Istanbul) çevrilip offset atılabilir.
    # Journal sözleşmesi UTC-naive'dir; önce explicit UTC'ye normalize et.
    snap_ts = _utc_naive_timestamp(snap_ts)
    con = duckdb.connect(str(journal_path))
    try:
        con.execute(
            """INSERT OR IGNORE INTO futures_equity_snapshots
               (snapshot_id, ts, wallet_balance, unrealized_pnl, margin_balance,
                available_balance, n_positions, n_open_orders, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snap_id,
                snap_ts,
                state["wallet_balance"],
                state["unrealized_pnl"],
                state["margin_balance"],
                state["available_balance"],
                state["n_positions"],
                state["n_open_orders"],
                notes,
            ),
        )
        con.commit()
    finally:
        con.close()
    return snap_id


def equity_snapshot():
    from scripts.futures_trade_daily import (
        fetch_futures_state,
        get_futures_exchange,
        init_futures_journal,
    )

    init_futures_journal()
    try:
        ex = get_futures_exchange()
        state = fetch_futures_state(ex)
        _write_equity_snapshot(state)
        log(
            f"SNAPSHOT: wallet=${state['wallet_balance']:.2f}, "
            f"unrealized={state['unrealized_pnl']:+.2f}, "
            f"pos={state['n_positions']}, orders={state['n_open_orders']}"
        )
        # Dead Man's Switch heartbeat ping
        _dms_ping(state)
        return state
    except Exception as e:
        log(f"SNAPSHOT ERROR: {e}")
        return None


# ── PyramidRouter singleton (SEC54.3) ─────────────────────────────────────
# Pyramid aktif pozisyonlar: parent_position_id → PyramidPosition
# SEC58-L2: in-memory cache + DuckDB persist (restart-safe).
_pyramid_positions: dict[str, object] = {}
_pyramid_router_instance = None

# FIX 2026-06-05: ORİJİNAL intended-SL cache. Key="SYMUSDT|side" → ilk SL fiyatı.
# Kök neden: v13'te pyramid KAPALI → entry'de _pyramid_positions kaydı oluşmuyor →
# watchdog G22 yolu hareketli borsa SL'ini intended_sl sanıyor → initial_r yanlış →
# TP1 sonrası trailing DONUYOR (kazanan pozisyon breakeven'a geri dönüp $0 kapanıyor;
# XRP +$64 → $0 olayı). Çözüm: girişte orijinal SL'i burada sakla, watchdog stabil bu
# değeri kullansın → BE-lock + trailing doğru çalışır. In-memory (restart'ta rebuild
# _pyramid_positions'ı journal'dan doldurur; bu cache running-açılan pozisyonları kapsar).
_ORIG_INTENDED_SL: dict[str, float] = {}

# SEC58-L2: PyramidStore singleton — startup'ta yüklenir, her upsert'te yazılır.
_pyramid_store = None


def _get_pyramid_store() -> object | None:
    """PyramidStore singleton (lazy init).

    FIX 2026-05-26 (M3): init fail → push_critical Telegram alert.
    Önceden in-memory mode silent fallback'e düşüyordu — restart'ta
    aktif pyramid pozisyonları kayboluyordu (bot duplicate layer-up
    açma riski). Şimdi: data/ permission check + alert.
    """
    global _pyramid_store
    if _pyramid_store is not None:
        return _pyramid_store

    # Önce data/ dizini yazılabilir mi kontrol et (defansif)
    try:
        data_dir = DATA_DIR
        data_dir.mkdir(parents=True, exist_ok=True)
        test_file = data_dir / ".pyramid_write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
    except Exception as perm_exc:
        log(f"PYRAMID_STORE_PERMISSION_FAIL: data/ yazılabilir değil ({perm_exc})")
        try:
            from price_action.orchestrator.notifications import push_critical

            push_critical(
                f"PyramidStore: data/ permission denied — "
                f"in-memory mode, restart = state KAYIP. "
                f"Permission'ları düzelt + daemon restart. ({perm_exc})",
                source="futures_daemon_pyramid",
            )
        except Exception:
            pass
        _pyramid_store = None
        return None

    try:
        from price_action.execution.pyramid_store import PyramidStore

        _pyramid_store = PyramidStore(db_path=PYRAMID_STORE_DB)
        log(f"PYRAMID_STORE: başlatıldı → {_pyramid_store._path}")
    except Exception as exc:
        log(f"PYRAMID_STORE_INIT_FAIL: {exc} — in-memory only (restart = state lost)")
        # FIX 2026-05-26 (M3): Silent değil — Principal hemen bilsin
        try:
            from price_action.orchestrator.notifications import push_critical

            push_critical(
                f"PyramidStore INIT FAIL: {str(exc)[:200]} — "
                f"daemon in-memory mode'a düştü. Restart sonrası aktif "
                f"pyramid pozisyonları kaybolur (duplicate layer-up riski).",
                source="futures_daemon_pyramid",
            )
        except Exception:
            pass
        _pyramid_store = None
    return _pyramid_store


def _pyramid_store_load_on_startup() -> None:
    """Daemon başladığında DB'den aktif pozisyonları yükle (SEC58-L2)."""
    global _pyramid_positions
    store = _get_pyramid_store()
    if store is None:
        return
    try:
        recovered = store.load_all()
        if recovered:
            _pyramid_positions.update(recovered)
            log(
                f"PYRAMID_STORE: {len(recovered)} pozisyon restart'tan kurtarıldı: "
                f"{list(recovered.keys())[:5]}"
            )
        else:
            log("PYRAMID_STORE: startup — kayıtlı aktif pozisyon yok")
    except Exception as exc:
        log(f"PYRAMID_STORE_LOAD_FAIL: {exc} — _pyramid_positions boş başladı")


def _rebuild_position_tracking_from_exchange(exchange) -> None:
    """Restart sonrası borsadaki açık pozisyonlar için takip kaydı yeniden kur.

    Kök neden: Daemon restart'ta pyramid_store.duckdb boşsa (ya da pozisyon
    pyramid dışı açılmışsa) _pyramid_positions boş kalır → PROT_WATCHDOG G22
    yolu _intended_sl olarak borsadaki MEVCUT SL'i kullanır → initial_r yanlış
    hesaplanır (SL zaten trailing ile taşınmış olabilir) → trailing donukluk.

    Bu fonksiyon:
      1. Borsadaki açık pozisyonları çeker.
      2. Her pozisyon için _pyramid_positions'da zaten kayıt varsa atlar.
      3. Yoksa: journal'dan orijinal entry + sl_price'ı arar (en son fill eşleşmesi).
         Journal'da bulunamazsa borsanın entry + mevcut algo SL'ini kullanır.
      4. Stub PyramidPosition (legs=[]) oluşturup _pyramid_positions'a ekler.
      5. pyramid_store'a YAZMAZ (pyramid_enabled=false bağımsızlığı korumak için).

    Güvenlik: sadece _pyramid_positions EKSIK kayıtları doldurur; mevcut kayıtlara
    dokunmaz. Strateji/risk config'e hiç dokunmaz. Exception → log + devam.
    """
    global _pyramid_positions
    try:
        from price_action.execution.pyramid_router import PyramidLeg, PyramidPosition
    except ImportError as _imp_err:
        log(f"REBUILD_TRACKING_SKIP: PyramidPosition import fail: {_imp_err}")
        return

    try:
        positions = exchange.fetch_positions()
        active_pos = [p for p in positions if abs(float(p.get("contracts", 0))) > 0]
    except Exception as _fetch_err:
        # KALAN_ISLER #8: sayaç-only (log zaten var) — akış/dönüş birebir aynı.
        record_degraded_read("rebuild_tracking.fetch_positions", _fetch_err, emit_log=False)
        log(f"REBUILD_TRACKING_FAIL: borsa pozisyonları çekilemedi: {_fetch_err}")
        return

    if not active_pos:
        log("REBUILD_TRACKING: borsa'da açık pozisyon yok — atlanıyor")
        return

    # Journal bağlantısı: orijinal entry + sl_price lookup için
    _journal_map: dict[
        str, tuple[float, float, str]
    ] = {}  # "SYM|side" → (fill_price, sl_price, signal_id)
    try:
        _jcon = duckdb.connect(str(JOURNAL))
        try:
            _jrows = _jcon.execute(
                """
                SELECT symbol, side, fill_price, sl_price, signal_id
                FROM futures_signals
                WHERE fill_price > 0 AND status = 'filled'
                ORDER BY ts DESC
                """
            ).fetchall()
            # İlk eşleşmeyi (en yeni) al — sembol 'XLM/USDT' formatında
            for _jr in _jrows:
                _jsym, _jside, _jfill, _jsl, _jsid = _jr
                _key = f"{_jsym}|{_jside}"
                if _key not in _journal_map and _jfill and _jfill > 0 and _jsl and _jsl > 0:
                    _journal_map[_key] = (float(_jfill), float(_jsl), str(_jsid))
        finally:
            _jcon.close()
    except Exception as _jexc:
        log(f"REBUILD_TRACKING: journal okunamadı ({_jexc}) — borsa entry/SL kullanılacak")

    # Borsadaki algo SL'leri al (per-symbol hızlı lookup için)
    _algo_sl_map: dict[str, float] = {}  # "XLMUSDT" → triggerPrice
    try:
        from scripts.futures_trade_daily import _scoped_open_orders

        _algo_ords = _scoped_open_orders(
            exchange,
            method_name="fapiPrivateGetOpenAlgoOrders",
            symbols={
                symbol
                for position in active_pos
                if (symbol := _normalize_pending_symbol(position.get("symbol")))
            },
        )
        for _ao in _algo_ords or []:
            if _ao.get("orderType") == "STOP_MARKET":
                _ao_sym = str(_ao.get("symbol", ""))
                _ao_tp = float(_ao.get("triggerPrice") or 0)
                if _ao_sym and _ao_tp > 0:
                    _algo_sl_map[_ao_sym] = _ao_tp
    except Exception as _algo_err:
        # KALAN_ISLER #8: sayaç-only (log zaten var) — akış/dönüş birebir aynı.
        record_degraded_read("rebuild_tracking.open_algo_orders", _algo_err, emit_log=False)
        log(f"REBUILD_TRACKING: algo SL'ler çekilemedi ({_algo_err}) — borsa entry kullanılacak")

    rebuilt_count = 0
    for pos in active_pos:
        _sym_ccxt = str(pos.get("symbol", ""))  # "XLM/USDT:USDT"
        _side_raw = str(pos.get("side", "")).lower()  # "long" / "short"
        _entry = float(pos.get("entryPrice") or pos.get("info", {}).get("entryPrice") or 0)
        _contracts = float(pos.get("contracts") or 0)

        if not _sym_ccxt or _side_raw not in ("long", "short") or _entry <= 0:
            continue

        # watchdog _sym_ccxt formatı: "XLM/USDT:USDT".split(":")[0] = "XLM/USDT"
        # PyramidPosition.symbol bu formatla uyumlu olmalı.
        _sym_for_check = _sym_ccxt.split(":")[0]

        # Bu pozisyon için zaten _pyramid_positions'da kayıt var mı?
        _already = any(
            getattr(_pp, "symbol", "") == _sym_for_check
            and str(getattr(_pp, "side", "")).lower() == _side_raw
            for _pp in _pyramid_positions.values()
        )
        if _already:
            continue

        # Journal'dan orijinal entry + sl bul
        # Journal formatı: 'XLM/USDT' (ccxt'nin :USDT suffix'i olmadan)
        _sym_journal = _sym_ccxt.split(":")[0]  # "XLM/USDT:USDT" → "XLM/USDT"
        _sym_algo = _sym_ccxt.replace("/", "").replace(":USDT", "").replace(":usdt", "")
        _jkey = f"{_sym_journal}|{_side_raw}"
        _orig_entry, _orig_sl, _orig_sig_id = _journal_map.get(_jkey, (0.0, 0.0, ""))

        # Fallback: journal yoksa borsadaki entry + algo SL
        if _orig_entry <= 0:
            _orig_entry = _entry
        if _orig_sl <= 0:
            # Algo SL map'den (XLMUSDT formatı)
            _orig_sl = _algo_sl_map.get(_sym_algo, 0.0)

        if _orig_sl <= 0:
            log(
                f"REBUILD_TRACKING: {_sym_ccxt} {_side_raw} — sl_price bulunamadı, atlanıyor "
                f"(journal_key={_jkey}, algo_map_keys={list(_algo_sl_map.keys())[:5]})"
            )
            continue

        _initial_r = abs(_orig_entry - _orig_sl)
        if _initial_r <= 0:
            log(f"REBUILD_TRACKING: {_sym_ccxt} {_side_raw} — initial_r=0, atlanıyor")
            continue

        # Stub PyramidPosition: legs boş (pyramid_enabled=false, leg trigger yok)
        # watchdog'un _sym_ccxt'si: _sym_raw.split(":")[0] → "XLM/USDT" (":USDT" yok)
        # PyramidPosition.symbol'ü watchdog ile aynı formatta set et.
        _sym_for_pp = _sym_ccxt.split(":")[0]  # "XLM/USDT:USDT" → "XLM/USDT"
        _stub_leg = PyramidLeg(
            leg_num=1,
            leg_state="FILLED",
            leg_qty=_contracts,
            leg_price=_orig_entry,
            client_order_id=f"rebuild_{_sym_algo}_L1",
            fill_price=_orig_entry,
        )
        _stub_id = _orig_sig_id if _orig_sig_id else f"rebuild_{_sym_algo}_{_side_raw}"
        _pyr_pos = PyramidPosition(
            parent_position_id=_stub_id,
            symbol=_sym_for_pp,
            side=_side_raw.upper(),  # type: ignore[arg-type]
            entry_price=_orig_entry,
            sl_price=_orig_sl,
            initial_R=_initial_r,
            legs=[_stub_leg],
            pyramid_triggers=[],
            pyramid_sizes=[],
        )
        _pyramid_positions[_stub_id] = _pyr_pos
        rebuilt_count += 1
        log(
            f"REBUILD_TRACKING: {_sym_ccxt} {_side_raw} → stub kayıt oluşturuldu "
            f"(entry={_orig_entry}, sl={_orig_sl}, initial_r={_initial_r:.5f}, "
            f"source={'journal' if _orig_sig_id else 'exchange'}, id={_stub_id})"
        )

    if rebuilt_count > 0:
        log(f"REBUILD_TRACKING: {rebuilt_count} pozisyon için takip kaydı yeniden kuruldu")
    else:
        log("REBUILD_TRACKING: tüm pozisyonlar zaten takip kaydına sahip (veya sl bulunamadı)")


def _get_pyramid_router(exchange):
    """PyramidRouter singleton — config'den pyramid_enabled kontrolü."""
    global _pyramid_router_instance
    if _pyramid_router_instance is not None:
        return _pyramid_router_instance
    # FIX 2026-05-26 (Faz 14.9): pyramid_enabled gate.
    # Config'de kapalıysa router'ı hiç init etme — eski PENDING leg'lerin
    # sonsuz submit retry'ı önlenir.
    if not _pyramid_enabled_15m():
        log("PYRAMID_ROUTER: skip init (strategy_portfolio.pyramid_enabled=false)")
        return None
    try:
        import yaml as _yaml_gr

        _gr_yaml_path = _risk_config_15m()
        try:
            with open(_gr_yaml_path, encoding="utf-8") as _gr_f:
                _gr_cfg = _yaml_gr.safe_load(_gr_f) or {}
        except Exception as _gr_load_exc:
            # FIX 2026-05-26 (H1): config eksikliği görünür olsun
            log(
                f"WARN _get_pyramid_router config load fail: {_gr_load_exc} — defaults kullanılıyor"
            )
            _gr_cfg = {}
        _gr_exec = _gr_cfg.get("execution", {})
        _gr_po_enabled = bool(_gr_exec.get("post_only_limit_enabled", False))
        _gr_po_timeout = int(_gr_exec.get("post_only_fallback_seconds", 30))
        _gr_slip_limit = float(_gr_exec.get("slippage_limit_bps", 25.0))
        # pyramid_slippage_limit_bps: entry slippage_limit_bps'den ayrı,
        # pyramid leg market-fallback için daha geniş tolerans (default 50bps).
        _gr_pyr_slip = float(_gr_exec.get("pyramid_slippage_limit_bps", 50.0))
        from price_action.execution.idempotency import IdempotencyStore
        from price_action.execution.pyramid_router import PyramidRouter
        from price_action.execution.slippage_tracker import SlippageTracker

        _pyramid_router_instance = PyramidRouter(
            exchange=exchange,
            idempotency_store=IdempotencyStore(db_path=IDEMPOTENCY_DB),
            slippage_tracker=SlippageTracker(),
            post_only_enabled=_gr_po_enabled,
            fallback_seconds=_gr_po_timeout,
            slippage_limit_bps=_gr_pyr_slip,
            mode=os.environ.get("PA_RUN_MODE", "paper"),
        )
        log(
            f"PYRAMID_ROUTER: başlatıldı (post_only={_gr_po_enabled}, slip_limit={_gr_pyr_slip}bps)"
        )
    except Exception as exc:
        log(f"PYRAMID_ROUTER_INIT_FAIL: {exc} — pyramid devre dışı")
        _pyramid_router_instance = None
    return _pyramid_router_instance


_TRAIL_PCT = 0.04  # TP1 sonrası %4 trailing — backtest doğrulaması bekleniyor (2026-06-01)
# Eski: 0.10 (TP2 sonrası) — açık kâr korunmuyordu (XLM kâr→zarar vakası 2026-05-31)
# Yeni: 0.04 (TP1 sonrası) — backtest sonucuna göre 0.03/0.04/0.05 karşılaştırması yapılacak.

# Runner time-stop — 30-bar forced exit once in runner phase (post-TP1).
# Validated by lab tournament (reports/research/smc/exit_tournament_verdict.md):
#   LIVE_ts30 = same 4% pct-trail + BE-lock + 30-bar runner cap.
#   Collapses the +56%/mo tail artifact → honest +6.43%/mo, Sharpe 1.67, DD -18.7%,
#   top-5% R share 40.9%, 12/12 walk-forward. Driver: scripts/_champ_exit_parity_timestop.py.
# Anchor: bars counted from when runner trail engages (TP1 hit / +1R) — NOT from entry.
#   force_exit_from_entry=False in LIVE_ts30 config; clock starts at TP1 partial fill.
#   In the daemon: runner anchor = ts_close of the first TP1 partial close from the journal
#   (fully restart-safe — derived from DB on every position_check tick, not in-memory counter).
# Bar size: 15 minutes → 30 bars = 7.5 hours max runner hold after TP1.
_RUNNER_MAX_BARS = 30  # ts30 validated value; do not change without re-running lab tournament
_RUNNER_BAR_SECONDS = 15 * 60  # 15m timeframe → seconds per bar


def _update_journal_sl_order_id(sym_ccxt: str, side: str, new_sl_id) -> None:
    """Watchdog SL cancel-replace sonrası journal koruma satırını taze algoId'ye çeker.

    FIX 2026-07-08 (W1-CRIT, dalga-3): watchdog SL'i yenileyince (trailing /
    qty-fix / missing-SL) journal futures_protection_orders.sl_order_id GİRİŞ
    id'sinde kalıyordu → ilk trail'den sonra tüm "SL duruyor mu" kontrolleri
    (heal satır ~1110, fill-detection ~1240) iptal-edilmiş ID'ye bakıp
    "SL yok" sanıyordu (heal false-close'un kök beslemesi).
    Best-effort: journal hatası watchdog tick'ini ÖLDÜRMEZ (log + devam).
    """
    if not new_sl_id:
        return
    try:
        _con = duckdb.connect(str(JOURNAL))
        try:
            _con.execute(
                "UPDATE futures_protection_orders SET sl_order_id=? "
                "WHERE symbol=? AND LOWER(side)=LOWER(?) AND status='placed'",
                [str(new_sl_id), sym_ccxt, side],
            )
            _con.commit()
        finally:
            _con.close()
    except Exception as _uje:
        log(f"  PROT_WATCHDOG_JOURNAL_ERR: {sym_ccxt} sl_order_id güncellenemedi: {str(_uje)[:80]}")


def _runner_timestop_anchor_ts(jcon, sym_ccxt: str, side: str):
    """Runner time-stop çıpası: bu sembol+yönün EN YENİ 'filled' sinyalinin ilk TP1'i.

    FIX 2026-07-08 (W1-HIGH, dalga-3): eski sorgu sembol+yön eşleşen EN ESKİ
    TP1 partial'ı seçiyordu — journal'da zombi kalmış eski bir 'filled' sinyalin
    TP1'i, aynı sembol+yöndeki YENİ pozisyona çıpa oluyordu → taze +1R kazanan
    30-bar dolmuş sayılıp anında market-kapatılıyordu. Çıpa artık trade-scoped:
    yalnız en güncel filled sinyalin kendi partial'ı sayılır.
    """
    row = jcon.execute(
        """
        SELECT pc.ts_close
        FROM futures_partial_closes pc
        JOIN futures_signals fs
          ON pc.trade_id = fs.signal_id
        WHERE fs.symbol = ?
          AND LOWER(fs.side) = LOWER(?)
          AND fs.status = 'filled'
          AND LOWER(pc.close_reason) IN ('tp1', 'tp')
          AND fs.signal_id NOT IN (
              SELECT trade_id FROM futures_trades_closed
          )
          AND fs.signal_id = (
              SELECT signal_id FROM futures_signals
              WHERE symbol = ? AND LOWER(side) = LOWER(?) AND status = 'filled'
              ORDER BY ts DESC
              LIMIT 1
          )
        ORDER BY pc.ts_close ASC
        LIMIT 1
        """,
        [sym_ccxt, side, sym_ccxt, side],
    ).fetchone()
    return row[0] if row and row[0] else None


def _corr_matrix_syms(signals: list, universe: list[str]) -> list[str]:
    """A1-04 FIX (2026-07-10): korelasyon matrisi = TÜM evren ∪ sinyal sembolleri.

    Eski kod matrisi YALNIZ o barda sinyal üreten sembollerle kuruyordu → açık
    pozisyon sembolü matriste yoksa correlation_gate (True, 1.0) dönüyordu =
    yeni sinyal mevcut pozisyonlarla korelasyonu HİÇ ölçülmeden geçiyordu
    (daemon-özel körlük; script yolu zaten tüm-evrenle çalışıyor). Evrenin
    tamamı dahil → açık pozisyonlar (evren üyesi) matriste kalır. sorted() →
    build_returns_df TTL-cache anahtarı barlar arası stabil (cache hit korunur).
    """
    if not signals:
        return []
    return sorted(set(universe) | {s["symbol"] for s in signals})


def _should_check_protection_fills(
    tp_oid, sl_oid, tp_open: bool, sl_open: bool, qty_now: float
) -> bool:
    """Fill-detection history sorgusuna girilmeli mi? (saf karar fonksiyonu)

    FIX 2026-07-10 (dalga-5 A1-01, W1-S1 yan etkisi): eski kapı yalnız
    `(not tp_open and not sl_open) or sl_gone_pos_flat` idi. TP1 kısmi
    dolduğunda SL hâlâ borsada → sl_open=True → iki dal da False → partial
    HİÇ tespit edilmiyordu. W1-S1 öncesi bu KAZAYLA çalışıyordu (watchdog
    trail'i journal sl_order_id'yi bayatlatınca sl_open yanlışlıkla False
    görünüyordu); S1 bayatlamayı kapatınca kazara-tespit de öldü → ts30
    runner time-stop çıpasız kaldı, partial PnL/Telegram/remaining-qty kör.
    YENİ dal: TP izleniyor + açık sette YOK + pozisyonda qty VAR → partial
    şüphesi, history sorgusuna gir (kayıt idempotent; API-stale epsilon-skip
    koruması içeride aynen duruyor).
    """
    if not tp_open and not sl_open:
        return True
    if sl_oid and not sl_open and qty_now <= 1e-6:
        return True  # SL kayıp + flat = tam kapanış (2026-06-11 kuralı)
    # A1-01: TP kayıp + pozisyon açık = partial şüphesi
    return bool(tp_oid and not tp_open and qty_now > 1e-6)


def _should_retire_protection(any_terminal: bool, exchange_qty_now: float) -> bool:
    """Koruma satırı yalnız borsada pozisyon FLAT iken emekli edilir.

    FIX 2026-07-08 (W1-HIGH, dalga-3): eski kod ilk terminal algo olayında
    (TP1 partial dahil!) satırı 'filled' yapıyordu → TP2/SL fill'leri
    fill-detection'a görünmez oluyor, final kapanışı daemon değil heal
    yazıyordu (close_reason=reconcile_orphan, exit fiyatı entry kopyası).
    """
    return bool(any_terminal) and exchange_qty_now <= 1e-6


def _protection_terminal_event_time(order: dict) -> float:
    """Best available actual terminal-update/fill timestamp for an algo order."""
    values: list[float] = []
    for key in ("updateTime", "actualTime", "triggerTime", "timestamp", "time"):
        raw = order.get(key)
        if raw in (None, ""):
            continue
        try:
            numeric = float(raw)
            # Binance uses epoch-ms, while some wrappers expose epoch-seconds.
            if 0 < numeric < 100_000_000_000:
                numeric *= 1000.0
            values.append(numeric)
            continue
        except (TypeError, ValueError):
            pass
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            values.append(parsed.timestamp() * 1000.0)
        except (TypeError, ValueError):
            continue
    return max(values, default=0.0)


def _numeric_order_identity(order: dict) -> int:
    """Monotonic exchange identity used only when terminal timestamps tie/miss."""
    for key in ("actualOrderId", "actual_order_id", "algoId", "algo_id"):
        try:
            return int(str(order.get(key) or ""))
        except (TypeError, ValueError):
            continue
    return 0


def _latest_protection_terminal(
    *,
    sl_order: dict | None,
    tp1_order: dict | None,
    tp2_order: dict | None,
) -> tuple[dict | None, str | None]:
    """Select the newest actual SL/TP fill, never a fixed first-match leg.

    TP1 remains in Binance algo history after its partial fill. A later TP2 (or
    runner SL) must therefore win by terminal ``updateTime``; otherwise every
    subsequent tick replays the historical TP1 and TP2 is never journaled.
    """
    candidates = _protection_terminal_candidates(
        sl_order=sl_order,
        tp1_order=tp1_order,
        tp2_order=tp2_order,
    )
    if not candidates:
        return None, None
    return candidates[-1]


def _protection_terminal_candidates(
    *,
    sl_order: dict | None,
    tp1_order: dict | None,
    tp2_order: dict | None,
) -> list[tuple[dict, str]]:
    """Return every actual protection fill in deterministic event order."""
    terminal_statuses = {"TRIGGERED", "FINISHED"}
    kind_rank = {"TP1": 1, "TP2": 2, "SL": 3}
    candidates = [
        (order, kind)
        for order, kind in (
            (tp1_order, "TP1"),
            (tp2_order, "TP2"),
            (sl_order, "SL"),
        )
        if order is not None
        and str(order.get("algoStatus") or "").upper() in terminal_statuses
    ]
    return sorted(
        candidates,
        key=lambda item: (
            _protection_terminal_event_time(item[0]),
            _numeric_order_identity(item[0]),
            kind_rank[item[1]],
        ),
    )


def _protection_partial_close_id(signal_id: object, order: dict, prot_id: object) -> str:
    """Idempotency key follows the terminal leg actually selected this tick."""
    selected_algo_id = order.get("algoId") or order.get("algo_id") or prot_id
    return f"{signal_id}_{selected_algo_id}"


def _protection_fill_event_id(prot_id: object, order: dict, kind: object) -> str:
    """Stable processed-state identity for one actual conditional-order fill."""
    algo_id = order.get("algoId") or order.get("algo_id")
    if algo_id in (None, ""):
        raise ValueError("terminal protection fill has no algo identity")
    return f"prot_event_{prot_id}_{str(kind).lower()}_{algo_id}"


def _ensure_protection_fill_event_table(con) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS futures_protection_fill_events (
               event_id VARCHAR PRIMARY KEY,
               prot_id VARCHAR NOT NULL,
               signal_id VARCHAR NOT NULL,
               algo_id VARCHAR NOT NULL,
               kind VARCHAR NOT NULL,
               terminal_time_ms DOUBLE,
               execution_fill_id VARCHAR NOT NULL,
               quantity DOUBLE NOT NULL,
               price DOUBLE NOT NULL,
               fee_usdt DOUBLE,
               fee_source VARCHAR NOT NULL,
               journal_record_id VARCHAR NOT NULL,
               processed_at TIMESTAMP NOT NULL
           )"""
    )


def _protection_retirement_ready(
    *,
    position_flat: bool,
    events_ok: bool,
    unprocessed_event_count: int,
    trade_closed: bool,
    has_terminal_state: bool,
) -> bool:
    """A protection row retires only after durable evidence and journal state."""
    return bool(
        position_flat
        and events_ok
        and unprocessed_event_count == 0
        and trade_closed
        and has_terminal_state
    )


def _slip_expected_from_trigger(trigger_px: float, fill_px: float) -> float:
    """Koruma (TP/SL) fill'i için slippage ÖLÇÜM referansı (saf fonksiyon).

    FIX 2026-07-10 (execution paketi, slippage 0.0 bps bug — Fix A): daemon
    koruma-fill slippage'ini `_prot_fill_px`'i HEM expected HEM realized geçerek
    kaydediyordu → fill kendi benchmark'ı → %100 exit fill 0.0 bps (269/303 sıfır).
    Doğru referans: yapılandırılan trigger fiyatı (emrin tetiklenmeye ayarlandığı
    fiyat). avgPrice ile fill arasındaki sapma = gerçek exit slippage'i. trigger
    yoksa (>0 değil) fill'in kendisine döner = dürüst-0 (bilinmiyor, uydurmuyoruz).
    NOT: record_fill sign-konvansiyonu giriş-yönlü; exit bacağı ters işaretli okur
    (magnitude doğru, işaret takip-işi — ayrı semantik değişiklik, kapsam dışı).
    """
    return trigger_px if trigger_px and trigger_px > 0 else fill_px


def _slip_realized_from_order(order_avg, order_price, fetched_avg) -> float | None:
    """Giriş fill'i slippage ölçümü için borsanın raporladığı GERÇEK fill fiyatı.

    FIX 2026-07-10 (execution paketi, slippage 0.0 bps bug — Fix B): giriş
    slippage'i `realized_price=_avg_px` geçiyordu ama `_avg_px` borsa average'ı
    vermezse `_cur_px`'e (arrival) düşüyor → realized==expected → 0.0 (167 market
    girişi). Bu fonksiyon slippage kaydı için AYRI gerçek-fiyat türetir; `_avg_px`
    (journal/idem/notional besler) DOKUNULMAZ = measurement-only, sıfır trade-verisi
    regresyonu. Emir-yanıtı avg/price → yoksa fetch_order avg. Hiçbiri yoksa None
    (ölçülemez → çağıran arrival'a düşer = dürüst-0, sahte değer yazılmaz).
    """
    for cand in (order_avg, order_price, fetched_avg):
        if cand is None:
            continue
        try:
            v = float(cand)
        except (TypeError, ValueError):
            continue
        if v > 0:
            return v
    return None


def _protection_execution_from_user_trades(
    exchange,
    symbol_id: str,
    algo_order: dict,
    *,
    fallback_price: float,
    fallback_quantity: float,
    fallback_price_verified: bool = False,
    fallback_quantity_verified: bool = False,
) -> dict:
    """Algo protection fill'ini matching-engine trade kayıtlarıyla doğrula.

    Binance algo history'deki ``algoId`` koşullu emir kimliğidir; komisyon ve
    maker/taker gerçeği ise tetiklenince oluşan ``actualOrderId`` altındaki
    ``fapi/v1/userTrades`` satırlarındadır. STOP_MARKET/TAKE_PROFIT_MARKET
    protection emirleri takerdır. Exact order id veya USDT commission kanıtı
    yoksa ücret tahmin edilmez; ``None/unavailable`` döner (fail-closed).
    """
    actual_order_id = str(
        algo_order.get("actualOrderId") or algo_order.get("actual_order_id") or ""
    ).strip()
    result = {
        "actual_order_id": actual_order_id,
        "price": float(fallback_price or 0.0),
        "quantity": float(fallback_quantity or 0.0),
        "price_verified": bool(fallback_price_verified and fallback_price > 0),
        "quantity_verified": bool(fallback_quantity_verified and fallback_quantity > 0),
        "price_source": "algo_avg_price" if fallback_price_verified else "unavailable",
        "fee_usdt": None,
        "fee_source": "unavailable",
        # Bu helper yalnız market protection emirleri için çağrılır.
        "is_maker": False,
    }
    if not actual_order_id:
        return result
    try:
        order_id_param = int(actual_order_id)
    except (TypeError, ValueError):
        result["fee_source"] = "invalid_actual_order_id"
        return result

    try:
        rows = (
            exchange.fapiPrivateGetUserTrades(
                {"symbol": symbol_id, "orderId": order_id_param, "limit": 1000}
            )
            or []
        )
    except Exception:
        return result

    matches = [r for r in rows if str(r.get("orderId", "")) == actual_order_id]
    if not matches:
        return result

    total_qty = 0.0
    total_quote = 0.0
    commissions: list[float] = []
    commission_assets: set[str] = set()
    commission_complete = True
    for trade in matches:
        try:
            qty = float(trade.get("qty") or 0.0)
            price = float(trade.get("price") or 0.0)
        except (TypeError, ValueError):
            continue
        if qty <= 0 or price <= 0:
            continue
        try:
            quote = float(trade.get("quoteQty") or 0.0)
        except (TypeError, ValueError):
            quote = 0.0
        total_qty += qty
        total_quote += quote if quote > 0 else price * qty

        asset = str(trade.get("commissionAsset") or "").upper().strip()
        if asset:
            commission_assets.add(asset)
        try:
            commissions.append(float(trade["commission"]))
        except (KeyError, TypeError, ValueError):
            commission_complete = False

    if total_qty <= 0 or total_quote <= 0:
        return result

    result["price"] = total_quote / total_qty
    result["quantity"] = total_qty
    result["price_verified"] = True
    result["quantity_verified"] = True
    result["price_source"] = "exchange_user_trades"
    if commission_assets != {"USDT"}:
        result["fee_source"] = (
            f"unsupported_asset:{','.join(sorted(commission_assets))}"
            if commission_assets
            else "unavailable"
        )
    elif commission_complete and len(commissions) == len(matches):
        result["fee_usdt"] = round(sum(commissions), 12)
        result["fee_source"] = "exchange_user_trades"
    return result


def _record_protection_fill_evidence(
    *,
    prot_id: object,
    triggered_kind: str,
    triggered_order: dict,
    execution: dict,
    trigger_price: float,
    fill_price: float,
    ts: datetime,
    symbol: str,
    strategy: str,
    side: str,
    fallback_quantity: float,
    tracker=None,
) -> bool:
    """Persist one verified protection fill for partial and final exits.

    ``prot_id + leg kind`` is stable across daemon replays, and ``fills.fill_id``
    is a primary key.  A repeated terminal-history observation therefore keeps
    exactly one execution_fills row.  Matching-engine userTrades remains the
    preferred price/quantity/fee source; no synthetic zero-slippage row is
    emitted when price evidence is unavailable.
    """
    if execution.get("price_verified") is not True or execution.get("quantity_verified") is not True:
        log(
            f"  PROT_SLIP_UNVERIFIED: prot_id={prot_id} "
            "exchange fill price/quantity yok — sahte evidence yazılmadı"
        )
        return False

    try:
        verified_price = float(fill_price)
        verified_quantity = float(execution.get("quantity") or fallback_quantity)
    except (TypeError, ValueError):
        return False
    if not (
        math.isfinite(verified_price)
        and verified_price > 0
        and math.isfinite(verified_quantity)
        and verified_quantity > 0
    ):
        return False

    if tracker is None:
        from price_action.execution.slippage_tracker import SlippageTracker

        tracker = SlippageTracker()
    normalized_kind = str(triggered_kind).lower()
    order_type = str(triggered_order.get("orderType") or "market").lower()
    tracker.record_fill(
        fill_id=f"prot_{prot_id}_{normalized_kind}",
        ts=ts,
        symbol=str(symbol),
        strategy=f"{strategy}_{normalized_kind}",
        side=str(side).lower(),
        expected_price=_slip_expected_from_trigger(trigger_price, verified_price),
        realized_price=verified_price,
        quantity=verified_quantity,
        fee_usdt=execution.get("fee_usdt"),
        is_maker=False,
        order_type=f"algo_{order_type}",
        mode=os.environ.get("PA_RUN_MODE", "paper"),
        exchange_order_id=(
            str(execution.get("actual_order_id") or "")
            or str(triggered_order.get("algoId", ""))
        ),
        fill_type=normalized_kind,
        fill_role="exit",
        fee_source=str(execution.get("fee_source") or "unavailable"),
        notes=(
            f"price_source={execution.get('price_source', 'unavailable')} "
            f"algo_id={triggered_order.get('algoId', '')} "
            f"actual_order_id={execution.get('actual_order_id', '')}"
        ),
        tf="15m",
    )
    return True


def _process_protection_terminal_event(
    *,
    con,
    exchange,
    prot_id: object,
    symbol: str,
    symbol_id: str,
    triggered_order: dict,
    triggered_kind: str,
    position_flat: bool,
    is_last_candidate: bool,
    journal_path: Path | str | None = None,
    tracker=None,
    income_fetcher=None,
) -> bool:
    """Persist one algo fill through evidence, journal and processed-state.

    Cross-database atomicity is obtained by ordering plus deterministic IDs:
    execution evidence is written first, the trade journal second, and the
    processed marker last in the journal database.  A crash at either boundary
    replays exact payloads; a mismatch raises instead of being ignored.
    """
    event_id = _protection_fill_event_id(prot_id, triggered_order, triggered_kind)
    _ensure_protection_fill_event_table(con)
    if con.execute(
        "SELECT 1 FROM futures_protection_fill_events WHERE event_id=?",
        [event_id],
    ).fetchone():
        return True

    sig_row = con.execute(
        """SELECT signal_id, ts, symbol, side, strategy, fill_price, fill_qty, sl_price
             FROM futures_signals
            WHERE signal_id = (
                SELECT signal_id FROM futures_protection_orders WHERE prot_id = ?
            )""",
        [prot_id],
    ).fetchone()
    if sig_row is None:
        raise RuntimeError(f"protection event {event_id} has no linked signal")
    (
        sig_id,
        ts_open,
        sym_sig,
        side_sig,
        strategy,
        entry_price,
        fill_qty_sig,
        sl_price,
    ) = sig_row

    trigger_price = float(triggered_order.get("triggerPrice", 0) or 0)
    raw_avg = triggered_order.get("avgPrice") or triggered_order.get("avgExecutedPrice")
    raw_actual = triggered_order.get("actualPrice")
    avg_price = _positive_pending_price(raw_avg)
    actual_price = _positive_pending_price(raw_actual)
    fallback_price = avg_price or actual_price or trigger_price
    raw_quantity = triggered_order.get("actualQuantity") or triggered_order.get("executedQty")
    explicit_quantity = _positive_pending_price(raw_quantity)
    execution = _protection_execution_from_user_trades(
        exchange,
        symbol_id,
        triggered_order,
        fallback_price=fallback_price,
        fallback_quantity=explicit_quantity or 0.0,
        fallback_price_verified=avg_price is not None,
        fallback_quantity_verified=explicit_quantity is not None,
    )
    verified_price = float(execution.get("price") or 0.0)
    verified_quantity = float(execution.get("quantity") or 0.0)
    terminal_ms = _protection_terminal_event_time(triggered_order)
    event_ts = (
        datetime.fromtimestamp(terminal_ms / 1000.0, UTC)
        if terminal_ms > 0
        else datetime.now(UTC)
    )
    evidence_written = _record_protection_fill_evidence(
        prot_id=prot_id,
        triggered_kind=triggered_kind,
        triggered_order=triggered_order,
        execution=execution,
        trigger_price=trigger_price,
        fill_price=verified_price,
        ts=event_ts,
        symbol=str(sym_sig),
        strategy=str(strategy or ""),
        side=str(side_sig),
        fallback_quantity=0.0,
        tracker=tracker,
    )
    if not evidence_written:
        return False

    from price_action.execution.trade_journal import TradeJournal

    resolved_journal = str(journal_path or JOURNAL)
    trade_journal = TradeJournal(db_path=resolved_journal)
    normalized_kind = str(triggered_kind).lower()
    close_reason = "tp" if normalized_kind in {"tp", "tp1", "tp2"} else normalized_kind
    close_id = _protection_partial_close_id(sig_id, triggered_order, prot_id)
    existing_partial = con.execute(
        """SELECT trade_id, sym, side, qty_closed, exit_price, close_reason
             FROM futures_partial_closes WHERE close_id=?""",
        [close_id],
    ).fetchone()
    partial_replay = bool(
        existing_partial is not None
        and str(existing_partial[0]) == str(sig_id)
        and str(existing_partial[1]) == str(sym_sig)
        and str(existing_partial[2]).lower() == str(side_sig).lower()
        and execution_evidence_values_match(existing_partial[3], verified_quantity)
        and execution_evidence_values_match(existing_partial[4], verified_price)
        and str(existing_partial[5]) == normalized_kind
    )
    if existing_partial is not None and not partial_replay:
        raise RuntimeError(f"deterministic partial-close conflict for {event_id}")
    existing_final = con.execute(
        """SELECT sym, side, qty, exit_price, close_reason
             FROM futures_trades_closed WHERE trade_id=?""",
        [str(sig_id)],
    ).fetchone()
    final_replay = bool(
        existing_final is not None
        and position_flat
        and is_last_candidate
        and str(existing_final[0]) == str(sym_sig)
        and str(existing_final[1]).lower() == str(side_sig).lower()
        and execution_evidence_values_match(existing_final[2], verified_quantity)
        and execution_evidence_values_match(existing_final[3], verified_price)
        and str(existing_final[4]) == close_reason
    )

    remaining_before = _remaining_qty_on_con(con, str(sig_id), float(fill_qty_sig or 0.0))
    if (
        not partial_replay
        and not final_replay
        and not execution_evidence_values_match(
            min(verified_quantity, remaining_before), verified_quantity
        )
    ):
        raise RuntimeError(
            f"protection event {event_id} quantity {verified_quantity} exceeds "
            f"remaining {remaining_before}"
        )

    record_as_final = bool(
        final_replay
        or (
            not partial_replay
            and position_flat
            and is_last_candidate
            and execution_evidence_values_match(verified_quantity, remaining_before)
        )
    )
    inserted = False
    if record_as_final:
        pnl_override = None
        try:
            if income_fetcher is None:
                from price_action.execution.exchange_income import (
                    fetch_realized_income as income_fetcher,
                )

            normalized_open = ts_open
            if normalized_open is not None and getattr(normalized_open, "tzinfo", None) is None:
                normalized_open = normalized_open.replace(tzinfo=UTC)
            start_ms = int(normalized_open.timestamp() * 1000) if normalized_open else None
            total_income = income_fetcher(exchange, sym_sig, start_ms)
            if total_income is not None:
                row = con.execute(
                    "SELECT COALESCE(SUM(realized_pnl_usdt),0.0) "
                    "FROM futures_partial_closes WHERE trade_id=?",
                    [str(sig_id)],
                ).fetchone()
                pnl_override = float(total_income) - float(row[0] if row else 0.0)
        except Exception as exc:
            log(f"  PROT_INCOME_ERR sig={sig_id}: {str(exc)[:80]}")

        inserted = trade_journal.record_close(
            trade_id=str(sig_id),
            ts_open=ts_open or event_ts,
            ts_close=event_ts,
            sym=str(sym_sig),
            side=str(side_sig).lower(),
            strategy=str(strategy or ""),
            entry_price=float(entry_price or 0.0),
            exit_price=verified_price,
            qty=verified_quantity,
            sl_price=float(sl_price or 0.0),
            close_reason=close_reason,
            realized_pnl_override=pnl_override,
        )
        if not inserted:
            existing = con.execute(
                """SELECT sym, side, qty, exit_price, close_reason
                     FROM futures_trades_closed WHERE trade_id=?""",
                [str(sig_id)],
            ).fetchone()
            if (
                existing is None
                or str(existing[0]) != str(sym_sig)
                or str(existing[1]).lower() != str(side_sig).lower()
                or not execution_evidence_values_match(existing[2], verified_quantity)
                or not execution_evidence_values_match(existing[3], verified_price)
                or str(existing[4]) != close_reason
            ):
                raise RuntimeError(f"deterministic final-close conflict for {event_id}")
        journal_record_id = str(sig_id)
    else:
        inserted = trade_journal.record_partial_close(
            close_id=close_id,
            trade_id=str(sig_id),
            ts_close=event_ts,
            sym=str(sym_sig),
            side=str(side_sig).lower(),
            strategy=str(strategy or ""),
            entry_price=float(entry_price or 0.0),
            exit_price=verified_price,
            qty_closed=verified_quantity,
            sl_price=float(sl_price or 0.0),
            close_reason=normalized_kind,
        )
        if not inserted:
            existing = con.execute(
                """SELECT trade_id, sym, side, qty_closed, exit_price, close_reason
                     FROM futures_partial_closes WHERE close_id=?""",
                [close_id],
            ).fetchone()
            if (
                existing is None
                or str(existing[0]) != str(sig_id)
                or str(existing[1]) != str(sym_sig)
                or str(existing[2]).lower() != str(side_sig).lower()
                or not execution_evidence_values_match(existing[3], verified_quantity)
                or not execution_evidence_values_match(existing[4], verified_price)
                or str(existing[5]) != normalized_kind
            ):
                raise RuntimeError(f"deterministic partial-close conflict for {event_id}")
        journal_record_id = close_id

    algo_id = str(triggered_order.get("algoId") or triggered_order.get("algo_id") or "")
    execution_fill_id = f"prot_{prot_id}_{normalized_kind}"
    fee = execution.get("fee_usdt")
    insert_result = con.execute(
        """INSERT OR IGNORE INTO futures_protection_fill_events
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING event_id""",
        [
            event_id,
            str(prot_id),
            str(sig_id),
            algo_id,
            normalized_kind,
            terminal_ms,
            execution_fill_id,
            verified_quantity,
            verified_price,
            float(fee) if fee is not None else None,
            str(execution.get("fee_source") or "unavailable"),
            journal_record_id,
            _utc_naive_timestamp(datetime.now(UTC)),
        ],
    ).fetchone()
    if insert_result is None:
        existing_event = con.execute(
            """SELECT quantity, price, fee_usdt, fee_source, journal_record_id
                 FROM futures_protection_fill_events WHERE event_id=?""",
            [event_id],
        ).fetchone()
        fee_matches = (
            existing_event is not None
            and (
                (existing_event[2] is None and fee is None)
                or (
                    existing_event[2] is not None
                    and fee is not None
                    and math.isclose(
                        float(existing_event[2]),
                        float(fee),
                        rel_tol=1e-8,
                        abs_tol=1e-10,
                    )
                )
            )
        )
        if (
            existing_event is None
            or not execution_evidence_values_match(existing_event[0], verified_quantity)
            or not execution_evidence_values_match(existing_event[1], verified_price)
            or not fee_matches
            or str(existing_event[3]) != str(execution.get("fee_source") or "unavailable")
            or str(existing_event[4]) != journal_record_id
        ):
            raise RuntimeError(f"deterministic processed-event conflict for {event_id}")

    log(
        f"  PROT_EVENT_COMMITTED: {symbol} {triggered_kind} event_id={event_id} "
        f"qty={verified_quantity:.8f} price={verified_price:.8f} inserted={inserted}"
    )
    return True


def _entry_execution_from_user_trades(exchange, symbol_id: str, order: dict) -> dict:
    """Entry'nin tüm maker/market leglerini exact userTrades ile birleştir.

    Mixed fallback iki ayrı matching-engine order id üretir. KPI/fee/qty ancak
    istenen TÜM leg id'leri USDT commission ile bulunursa tamam sayılır; tek leg
    bile eksikse kısmi sonucu gerçek toplam gibi döndürmeyiz.
    """
    result = {
        "complete": False,
        "order_ids": [],
        "price": None,
        "quantity": None,
        "notional_usdt": None,
        "fee_usdt": None,
        "fee_source": "unavailable",
        "maker_quantity": None,
        "maker_notional_usdt": None,
    }
    raw_ids = [
        order.get("partial_limit_order_id"),
        order.get("market_fallback_order_id"),
    ]
    if not any(raw_ids):
        raw_ids.append(order.get("id"))
    order_ids: list[str] = []
    for raw_id in raw_ids:
        order_id = str(raw_id or "").strip()
        if order_id and order_id not in order_ids:
            order_ids.append(order_id)
    result["order_ids"] = order_ids
    if not order_ids:
        return result

    total_qty = 0.0
    total_notional = 0.0
    total_fee = 0.0
    maker_qty = 0.0
    maker_notional = 0.0
    for order_id in order_ids:
        try:
            order_id_param = int(order_id)
            rows = (
                exchange.fapiPrivateGetUserTrades(
                    {"symbol": symbol_id, "orderId": order_id_param, "limit": 1000}
                )
                or []
            )
        except Exception:
            return result
        matches = [row for row in rows if str(row.get("orderId", "")) == order_id]
        if not matches:
            return result
        for trade in matches:
            try:
                qty = float(trade["qty"])
                price = float(trade["price"])
                quote = float(trade.get("quoteQty") or 0.0)
                commission = float(trade["commission"])
            except (KeyError, TypeError, ValueError):
                return result
            asset = str(trade.get("commissionAsset") or "").upper().strip()
            if asset != "USDT":
                result["fee_source"] = f"unsupported_asset:{asset or '?'}"
                return result
            if qty <= 0 or price <= 0:
                return result
            notional = quote if quote > 0 else price * qty
            maker_raw = trade.get("maker", False)
            is_maker = (
                maker_raw.strip().lower() == "true"
                if isinstance(maker_raw, str)
                else bool(maker_raw)
            )
            total_qty += qty
            total_notional += notional
            total_fee += commission
            if is_maker:
                maker_qty += qty
                maker_notional += notional

    if total_qty <= 0 or total_notional <= 0:
        return result
    result.update(
        {
            "complete": True,
            "price": total_notional / total_qty,
            "quantity": total_qty,
            "notional_usdt": total_notional,
            "fee_usdt": round(total_fee, 12),
            "fee_source": "exchange_user_trades",
            "maker_quantity": maker_qty,
            "maker_notional_usdt": maker_notional,
        }
    )
    return result


def _entry_position_delta_evidence(
    before_state: dict,
    after_state: dict,
    symbol: str,
    side: str,
) -> dict:
    """userTrades yoksa pre/post borsa pozisyonundan yeni fill delta'sını çöz."""
    empty = {
        "complete": False,
        "quantity": None,
        "price": None,
        "notional_usdt": None,
        "source": "unavailable",
    }
    if before_state.get("positions_ok") is not True or after_state.get("positions_ok") is not True:
        return empty

    symbol_id = str(symbol).upper().replace(":USDT", "").replace("/", "")
    wanted_side = str(side).lower()

    def _position(state: dict) -> tuple[float, float, bool]:
        qty = 0.0
        entry_price = 0.0
        conflicting_side = False
        for position in state.get("positions", []) or []:
            pos_symbol = (
                str(position.get("symbol") or "").upper().replace(":USDT", "").replace("/", "")
            )
            if pos_symbol != symbol_id:
                continue
            pos_qty = abs(float(position.get("contracts") or 0.0))
            if pos_qty <= 0:
                continue
            if str(position.get("side") or "").lower() != wanted_side:
                conflicting_side = True
                continue
            qty += pos_qty
            entry_price = float(position.get("entryPrice") or 0.0)
        return qty, entry_price, conflicting_side

    try:
        before_qty, before_price, before_conflict = _position(before_state)
        after_qty, after_price, after_conflict = _position(after_state)
    except (TypeError, ValueError):
        return empty
    if (
        before_conflict
        or after_conflict
        or (before_qty > 0 and before_price <= 0)
        or after_price <= 0
        or after_qty <= before_qty
    ):
        return empty
    fill_qty = after_qty - before_qty
    after_notional = after_qty * after_price
    before_notional = before_qty * before_price if before_qty > 0 and before_price > 0 else 0.0
    fill_notional = round(after_notional - before_notional, 12)
    if fill_notional <= 0 or fill_qty <= 0:
        return empty
    return {
        "complete": True,
        "quantity": fill_qty,
        "price": round(fill_notional / fill_qty, 12),
        "notional_usdt": fill_notional,
        "source": "exchange_position_delta",
    }


def _entry_position_baseline(state: dict, symbol: str) -> tuple[float | None, float | None]:
    """Return signed pre-submit qty + entry price from a trusted account snapshot.

    The retry process may use this only as a baseline for a later measured
    position delta. Missing/stale/conflicting state therefore returns
    ``(None, None)`` instead of manufacturing a flat position.
    """
    if state.get("positions_ok") is not True:
        return None, None

    symbol_id = str(symbol).upper().replace(":USDT", "").replace("/", "")
    matches: list[tuple[float, float]] = []
    try:
        for position in state.get("positions", []) or []:
            pos_symbol = (
                str(position.get("symbol") or "").upper().replace(":USDT", "").replace("/", "")
            )
            if pos_symbol != symbol_id:
                continue
            info = position.get("info") if isinstance(position.get("info"), dict) else {}
            raw_amt = info.get("positionAmt")
            if raw_amt is not None:
                signed_qty = float(raw_amt)
            else:
                contracts = abs(float(position.get("contracts") or 0.0))
                side = str(position.get("side") or "").lower()
                signed_qty = -contracts if side == "short" else contracts
            if abs(signed_qty) <= 1e-12:
                continue
            entry_price = float(position.get("entryPrice") or info.get("entryPrice") or 0.0)
            if entry_price <= 0:
                return None, None
            matches.append((signed_qty, entry_price))
    except (TypeError, ValueError):
        return None, None

    if not matches:
        return 0.0, None
    signs = {1 if qty > 0 else -1 for qty, _ in matches}
    if len(signs) != 1:
        return None, None
    total_qty = sum(qty for qty, _ in matches)
    total_abs = sum(abs(qty) for qty, _ in matches)
    weighted_entry = sum(abs(qty) * px for qty, px in matches) / total_abs
    return total_qty, weighted_entry


def _desired_sl_price(
    side: str,
    entry: float,
    intended_sl: float,
    mark: float,
    pyramid_leg_filled: bool = False,
    trail_pct: float | None = None,
) -> float:
    """Bir pozisyon için olması gereken stop-loss fiyatı.

    Yeni kural (2026-06-01) — breakeven kilidi + erken trailing:
      1) BREAKEVEN KİLİDİ: mark +1R'yi (TP1) geçtiği anda SL tabanı entry'ye çekilir.
         LONG: max(entry, intended_sl) — pozisyon artık asla zarara dönemez.
         SHORT: min(entry, intended_sl)
      2) TRAIL ERKEN BAŞLAR: +1R'den (TP1) itibaren hem BE kilidi hem trailing aktif.
         (Eski davranış: trail yalnız TP2 = 1.5R sonrası başlıyordu → kâr korunmuyordu.)
      3) TRAIL SIKLIĞI: varsayılan _TRAIL_PCT = 0.04 (%4).
         LONG : max(entry, mark * (1 - trail_pct))
         SHORT: min(entry, mark * (1 + trail_pct))
      4) RATCHET: SL yalnız lehe hareket eder. Bu fonksiyon istenen SL'i döner;
         gerçek ratchet çağıran bekçide uygulanır (current >= desired → güncelleme yok).

    Seçenek-D / BE-protect (pyramid_leg_filled, 2026-05-20 davranışı korundu):
      pyramid_leg_filled=True → pyramid leg-2+ FILLED iken +1R altında BE taban.
      pyramid_leg_filled=False (default) → backward-compat, davranış aynı.

    Parametre:
      trail_pct: None → _TRAIL_PCT global default kullanılır. Explicit verilirse override.

    Örnek (LONG: entry=511.65, intended_sl=499.0, mark=571.0):
      initial_r = 12.65, tp1 = 524.30
      mark(571) > tp1(524.30) → trail aktif
      trail_sl = max(entry=511.65, 571*(1-0.04)) = max(511.65, 548.16) = 548.16
      → SL = 548.16  (eski %10: max(524.30, 571*0.90=513.90) = 524.30 — çok gevşek)
    """
    pct = trail_pct if trail_pct is not None else _TRAIL_PCT
    initial_r = abs(entry - intended_sl)
    if initial_r <= 0 or mark <= 0:
        return intended_sl
    if side == "long":
        tp1 = entry + initial_r
        if mark < tp1:
            # TP1 altında: BE kilidi yok, orijinal SL (pyramid ise BE taban)
            if pyramid_leg_filled:
                return max(entry, intended_sl)
            return intended_sl
        # mark >= tp1: BE kilidi + trailing (TP1'den itibaren)
        trail_sl = mark * (1.0 - pct)
        return max(entry, trail_sl)
    # short
    tp1 = entry - initial_r
    if mark > tp1:
        # TP1 altında (short yönde): BE kilidi yok
        if pyramid_leg_filled:
            return min(entry, intended_sl)
        return intended_sl
    # mark <= tp1: BE kilidi + trailing
    trail_sl = mark * (1.0 + pct)
    return min(entry, trail_sl)


def _remaining_qty_on_con(con, trade_id: str, fill_qty: float) -> float:
    """TradeJournal.get_remaining_qty mantığı ama AÇIK (rw) con üzerinde hesaplar.

    FIX 2026-06-16: kapanış-yolunda con (rw) açıkken tj.get_remaining_qty (read_only
    bağlantı açar) DuckDB "different configuration" çakışması veriyordu
    (TRADE_CLOSED_LOOKUP_FAIL → in-daemon kapanış kaydı başarısız, heal backstop'a
    düşüyordu). Aynı sonuç, YENİ bağlantı yok. fill_qty − SUM(partials); trade
    trades_closed'da ise 0; tablo yoksa fill_qty (get_remaining_qty ile birebir).
    """
    try:
        if con.execute(
            "SELECT 1 FROM futures_trades_closed WHERE trade_id=?", [trade_id]
        ).fetchone():
            return 0.0
        row = con.execute(
            "SELECT COALESCE(SUM(qty_closed),0.0) FROM futures_partial_closes WHERE trade_id=?",
            [trade_id],
        ).fetchone()
        partial_sum = float(row[0]) if row and row[0] is not None else 0.0
        return max(0.0, float(fill_qty) - partial_sum)
    except Exception:
        return float(fill_qty)


_POS_CHECK_DEG_SNAPSHOT: int = 0  # KALAN_ISLER #8: önceki POS_CHECK'teki toplam sayaç


def _orphan_confirmation_candidates(
    algo_orders: object,
    active_position_symbols: set[str],
    journal_open_symbols: set[str],
) -> set[str]:
    """Return symbols that can actually reach orphan cancellation this tick.

    ``positionRisk`` is a second private REST read used only as stale-read
    confirmation.  Calling it when every algo order is already owned by an
    active exchange position or an open journal row adds load without changing
    a decision.  Invalid/identity-less rows are ignored because the cleanup
    loop cannot mutate them either.
    """
    candidates: set[str] = set()
    if not isinstance(algo_orders, list):
        return candidates
    for order in algo_orders:
        if not isinstance(order, dict):
            continue
        symbol = _normalize_pending_symbol(order.get("symbol"))
        algo_id = order.get("algoId") or order.get("algo_id")
        if (
            symbol
            and algo_id
            and symbol not in active_position_symbols
            and symbol not in journal_open_symbols
        ):
            candidates.add(symbol)
    return candidates


def _fresh_orphan_position_symbols(
    exchange,
    candidate_symbols: set[str],
    active_position_symbols: set[str],
) -> set[str] | None:
    """Confirm only actionable orphan candidates through positionRisk.

    No candidate means no endpoint call.  A failed confirmation returns None,
    which is the cleanup loop's fail-closed "do not cancel" state.
    """
    confirmed = set(active_position_symbols)
    if not candidate_symbols:
        return confirmed
    try:
        for position in exchange.fapiPrivateV2GetPositionRisk():
            if abs(float(position.get("positionAmt", 0) or 0)) > 0.0001:
                symbol = _normalize_pending_symbol(position.get("symbol"))
                if symbol:
                    confirmed.add(symbol)
    except Exception as exc:
        record_degraded_read("pos_check.position_risk_confirm", exc, log_fn=log)
        return None
    return confirmed


def position_check():
    """Açık pozisyonları + algo (TP/SL) protection order durumu."""
    from scripts.futures_trade_daily import fetch_futures_state

    global _POS_CHECK_DEG_SNAPSHOT, _pending_queue_read_fail_ticks
    try:
        ex = _get_daemon_exchange()
        state = fetch_futures_state(ex)
        positions = state["positions"]

        # A3: rate-limit/network bilgi etiketi
        algo_ok = state.get("algo_orders_ok", True)
        pos_ok = state.get("positions_ok", True)
        state_complete = state.get("exchange_state_complete") is True
        rate_limit_suffix = "" if state_complete else " [API_STALE]"
        algo_count_display = state["n_algo_orders"] if algo_ok else "UNKNOWN"

        # KALAN_ISLER #8 (2026-07-10): son tick'ten bu yana DEGRADED_READ olduysa
        # özet satırına [DEGRADED:n] eki — '0 pozisyon' ile 'okuma çöktü' loglarda
        # ayrışsın. Görünürlük-only: akış/dönüş değişmez, hata ekleri boş kalır.
        degraded_suffix = ""
        try:
            _deg_total_now = total_degraded_reads()
            _deg_delta = _deg_total_now - _POS_CHECK_DEG_SNAPSHOT
            _POS_CHECK_DEG_SNAPSHOT = _deg_total_now
            if _deg_delta > 0:
                degraded_suffix = f" [DEGRADED:{_deg_delta}]"
        except Exception:
            degraded_suffix = ""

        if positions:
            pos_summary = []
            for p in positions:
                sym = p.get("symbol", "?")
                # FIX 2026-06-18 (CT-OPS-05): None-safe — ccxt testnet bazen
                # markPrice/unrealizedPnl'i None döndürüyor; float(None) tüm tick
                # korumasını (SL ratchet/orphan reconcile) atlatıyordu.
                contracts = float(p.get("contracts") or 0)
                side = p.get("side", "?")
                entry = float(p.get("entryPrice") or 0)
                mark = float(p.get("markPrice") or 0)
                pnl = float(p.get("unrealizedPnl") or 0)
                # FIX 2026-05-26 (Faz 14.9): 4-digit fiyat format (Principal isteği).
                # Düşük-fiyatlı coinler (DOGE, AVAX) $.2f'te aynı görünüyordu —
                # gerçek hareket gizleniyordu. $.4f ile $0.1014 vs $0.1023 ayırt edilir.
                pos_summary.append(
                    f"{sym.replace('/USDT:USDT', '').replace('/USDT', '')}={side[0].upper()}{abs(contracts):.3f}@${entry:.4f}->{mark:.4f}({pnl:+.2f})"
                )
            log(
                f"POS_CHECK: {len(positions)} pos, {algo_count_display} algo (TP+SL){rate_limit_suffix}{degraded_suffix} | "
                + " | ".join(pos_summary[:6])
            )
        else:
            log(
                f"POS_CHECK: 0 pozisyon, {algo_count_display} algo orders"
                f"{rate_limit_suffix}{degraded_suffix}"
            )

        # SEC-#3C: Fill-sonrası konsantrasyon watchdog (sadece alarm).
        # Sorun: mevcut concentration_gate PRE-trade çalışır; FILL SONRASI gerçek
        # piyasa hareketi sembolü beklenenin üzerine taşıyabilir. Bu watchdog
        # post-fill durumu kontrol eder ve konfigürasyondaki max_per_symbol_pct
        # (default 0.15) eşiğini aşanları WARN log + Telegram ile bildirir.
        # Önemli: TRADE YAPILMAZ / KESİLMEZ — sadece pasif uyarı.
        # Dedup: aynı sembol 12 saat içinde tekrar bildirilmez (state dosyası).
        if positions and pos_ok:
            try:
                import yaml as _conc_yaml

                _conc_cfg_path = _risk_config_15m()
                with open(_conc_cfg_path, encoding="utf-8") as _cf:
                    _conc_cfg = _conc_yaml.safe_load(_cf) or {}
                _max_per_sym_pct = float(
                    _conc_cfg.get("concentration_limits", {}).get("max_per_symbol_pct", 0.15)
                )
                # Equity tahmini: margin_balance (pozisyon kaybı dahil)
                _watchdog_equity = float(state.get("margin_balance", 0)) or float(
                    state.get("wallet_balance", 1)
                )
                if _watchdog_equity > 0:
                    # Dedup state dosyası
                    _conc_dedup_path = LOGS_DIR / "risk" / "conc_watchdog_dedup.json"
                    _conc_dedup_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        import json as _json_conc

                        _dedup_state = (
                            _json_conc.loads(_conc_dedup_path.read_text(encoding="utf-8"))
                            if _conc_dedup_path.exists()
                            else {}
                        )
                    except Exception:
                        _dedup_state = {}

                    _now_iso = datetime.now(UTC).isoformat()
                    _dedup_changed = False
                    for _p in positions:
                        _psym = _p.get("symbol", "?")
                        _pcontracts = abs(
                            float(_p.get("contracts") or 0)
                        )  # FIX CT-OPS-05 None-safe
                        _pmark = float(_p.get("markPrice") or 0)
                        _pnotional = _pcontracts * _pmark
                        _ppct = _pnotional / _watchdog_equity
                        if _ppct > _max_per_sym_pct:
                            # Dedup: son 12h içinde bildirildi mi?
                            _last_alert = _dedup_state.get(_psym)
                            _skip_dedup = False
                            if _last_alert:
                                try:
                                    from datetime import timedelta as _td

                                    _last_dt = datetime.fromisoformat(_last_alert)
                                    if _last_dt.tzinfo is None:
                                        _last_dt = _last_dt.replace(tzinfo=UTC)
                                    if (datetime.now(UTC) - _last_dt) < _td(hours=12):
                                        _skip_dedup = True
                                except Exception as _e:
                                    # log-only: _skip_dedup False kalır (eski davranış)
                                    log(f"  CONC_DEDUP_TS_PARSE_FAIL {_psym}: {str(_e)[:60]}")
                            if not _skip_dedup:
                                log(
                                    f"  CONCENTRATION_BREACH: {_psym} "
                                    f"{_ppct * 100:.1f}% > {_max_per_sym_pct * 100:.0f}% "
                                    f"(notional=${_pnotional:.0f}, equity=${_watchdog_equity:.0f})"
                                )
                                try:
                                    from price_action.orchestrator.notifications import (
                                        push_critical,
                                    )

                                    push_critical(
                                        f"CONCENTRATION_BREACH: {_psym} "
                                        f"{_ppct * 100:.1f}% > {_max_per_sym_pct * 100:.0f}% "
                                        f"(notional=${_pnotional:.0f})",
                                        source="pos_check_watchdog",
                                    )
                                except Exception:
                                    pass
                                _dedup_state[_psym] = _now_iso
                                _dedup_changed = True
                    if _dedup_changed:
                        try:
                            import json as _json_conc

                            _conc_dedup_path.write_text(
                                _json_conc.dumps(_dedup_state, indent=2), encoding="utf-8"
                            )
                        except Exception as _e:
                            log(f"  CONC_DEDUP_WRITE_FAIL: {str(_e)[:60]}")  # log-only
            except Exception as _conc_ex:
                log(f"  CONC_WATCHDOG_ERR: {str(_conc_ex)[:80]}")

        # A3: API stale ise — orphan cleanup + prot_check SKIP (false-close yazımı önle)
        if not state_complete:
            log(
                "POS_CHECK SKIP: orphan+prot_check passed "
                f"(positions_ok={pos_ok}, algo_ok={algo_ok}, "
                f"order_scope_ok={state.get('order_scope_ok')}, "
                f"scope_err={state.get('order_scope_error') or '-'}) "
                "— exchange state UNKNOWN"
            )
            return state

        # Orphan algo cleanup — TP fill sonrası SL kalıntısı (veya tersi) iptal.
        # reduceOnly tek başına whipsaw'da yetersiz: TP doldu → fiyat geri döner →
        # yeni pozisyon (farklı qty) açılırsa eski SL yanlış miktar kapatır.
        # Bu yüzden "pozisyon yok ama algo var" durumunu deterministik temizle.
        #
        # FIX 2026-05-30 (INC1-orphan-fp): Yanlış-pozitif orphan cancel.
        # Kök neden: fetch_positions() geçici olarak boş dönebilir (testnet API
        # stale / rate-limit 418, no exception, empty list). Bu durumda pozisyon
        # HÂLÂ AÇIKKEN algo order'ı "orphan" sanıp iptal ediyorduk — XLM vakası.
        # Düzeltme: algo_sym journal'daki açık futures_signals kaydıyla çapraz kontrol.
        # Journal'da açık kayıt varsa pozisyon borsada açık varsayılır; API stale
        # sanılır; bu tick'te orphan cancel ATLA + warning log.
        try:
            active_pos_syms = set()
            for p in positions:
                qty = abs(float(p.get("contracts") or 0))  # FIX CT-OPS-05 None-safe
                if qty > 0.0001:
                    sym_raw = p.get("symbol", "")
                    # "BTC/USDT:USDT" → "BTCUSDT" (algo endpoint sym format)
                    active_pos_syms.add(sym_raw.split(":")[0].replace("/", ""))

            # fetch_futures_state bu journal/queue kapsamını order endpoint'inden
            # ÖNCE ve fail-closed okudu. Aynı DuckDB sorgusunu burada tekrarlama;
            # kapsam eksik olsaydı yukarıdaki state_complete kapısı dönerdi.
            _journal_open_syms = {
                _normalize_pending_symbol(symbol)
                for symbol in state.get("journal_open_position_symbols", []) or []
                if _normalize_pending_symbol(symbol)
            }
            _journal_read_ok = state.get("order_scope_ok") is True

            # FIX 2026-06-07 (XRP/LINK çıplak döngüsü): İKİNCİ TAZE POZİSYON TEYİDİ.
            # Tek fetch_positions stale dönebilir (testnet): pozisyon AÇIKKEN positions[]
            # boş → SL "orphan" sanılıp iptal → çıplak → heal koyuyor → orphan tekrar
            # iptal (sonsuz döngü; XRP +$66 korumasız, LINK -$224). Journal cross-check
            # de drift'te kurtarmıyor. Çözüm: silmeden önce 2. bağımsız okuma. Sembol İKİ
            # okumada da yoksa gerçekten orphan; biri görürse / teyit alınamazsa İPTAL ETME.
            # FIX 2026-06-10 (v14 audit MAJOR-1b): 2. teyit FARKLI endpoint'ten —
            # fetch_positions ile aynı endpoint'in stale pencereleri korele
            # (02:15Z'de iki okuma da boş geldi). positionRisk ayrı endpoint,
            # sembol formatı zaten ham "BTCUSDT".
            _orphan_candidates = _orphan_confirmation_candidates(
                state.get("algo_orders", []),
                active_pos_syms,
                _journal_open_syms,
            )
            _confirm_syms = _fresh_orphan_position_symbols(
                ex,
                _orphan_candidates,
                active_pos_syms,
            )

            # FIX 2026-06-10 (XRP 02:15Z olayı): N-ARDIŞIK-TİCK STATEFUL TEYİT.
            # Double-read fix (d513795) DELİNDİ: 4. tick'te İKİ okuma da stale geldi
            # → açık pozisyonun SL'i iptal edildi (çıplak 30dk, HEAL kurtardı).
            # Tek-tick içi okuma sayısını artırmak yetmez (stale pencereleri korele).
            # Çözüm: cancel noktasına gelen emir _ORPHAN_SUSPECT_TICKS'te sayaç
            # biriktirir; ancak ORPHAN_CONFIRM_TICKS ardışık tick'te (~45dk) hep
            # orphan görünürse iptal edilir. Pozisyon TEK tick'te bile görünse sayaç
            # sıfırlanır. Gerçek orphan'lar ~45dk gecikmeyle temizlenir — kabul
            # edilebilir: SL'ler reduceOnly (pozisyonsuz tetik reddedilir); aynı
            # sembolde 45dk içinde yeni pozisyon whipsaw'ı PROT_WATCHDOG "fazla SL
            # temizle" adımıyla sınırlı.
            orphan_cnt = 0
            _seen_suspects: set[str] = set()
            # MAJOR-1a fail-closed: journal okunamadıysa hiçbir emri orphan sayma
            _orphan_scan_list = (state.get("algo_orders", []) or []) if _journal_read_ok else []
            for o in _orphan_scan_list:
                algo_sym = o.get("symbol", "")  # "BTCUSDT"
                if not algo_sym:
                    continue
                algo_id = o.get("algoId") or o.get("algo_id")
                if not algo_id:
                    continue
                _skey = f"{algo_sym}|{algo_id}"
                if algo_sym in active_pos_syms:
                    _ORPHAN_SUSPECT_TICKS.pop(_skey, None)
                    continue
                # FIX INC1: journal'da açık kayıt varsa → API stale olabilir, iptal ETME
                if algo_sym in _journal_open_syms:
                    _ORPHAN_SUSPECT_TICKS.pop(_skey, None)
                    log(
                        f"ORPHAN_SKIP: {algo_sym} algoId={algo_id} — "
                        f"journal'da açık kayıt var, pos API stale olabilir; bu tick skip"
                    )
                    continue
                # FIX 2026-06-07: 2. taze teyit. İkinci okuma pozisyonu görüyorsa VEYA
                # teyit alınamadıysa → orphan DEĞİL, iptal etme (stale-read'den çıplak bırakma).
                if _confirm_syms is None or algo_sym in _confirm_syms:
                    _ORPHAN_SUSPECT_TICKS.pop(_skey, None)
                    log(
                        f"ORPHAN_SKIP: {algo_sym} algoId={algo_id} — 2. taze teyitte "
                        f"pozisyon açık/teyit-yok; iptal edilmedi (stale-read koruması)"
                    )
                    continue
                # Bu tick'te orphan görünüyor → sayaç artır, eşiğe gelmeden iptal ETME.
                _streak = _ORPHAN_SUSPECT_TICKS.get(_skey, 0) + 1
                _ORPHAN_SUSPECT_TICKS[_skey] = _streak
                _seen_suspects.add(_skey)
                if _streak < ORPHAN_CONFIRM_TICKS:
                    log(
                        f"ORPHAN_PENDING: {algo_sym} algoId={algo_id} — "
                        f"{_streak}/{ORPHAN_CONFIRM_TICKS} ardışık tick; iptal bekletildi"
                    )
                    continue
                try:
                    ex.fapiPrivateDeleteAlgoOrder({"symbol": algo_sym, "algoId": algo_id})
                    orphan_cnt += 1
                    _ORPHAN_SUSPECT_TICKS.pop(_skey, None)
                    log(
                        f"ORPHAN_CANCEL: {algo_sym} algoId={algo_id} type={o.get('type', '?')} "
                        f"({ORPHAN_CONFIRM_TICKS} ardışık tick teyitli orphan)"
                    )
                except Exception as cancel_err:
                    log(
                        f"ORPHAN_CANCEL_FAIL: {algo_sym} algoId={algo_id} err={str(cancel_err)[:80]}"
                    )
            # Bu tick'te görünmeyen şüpheli kayıtlarını temizle (emir doldu/iptal oldu)
            for _stale_key in [k for k in _ORPHAN_SUSPECT_TICKS if k not in _seen_suspects]:
                _ORPHAN_SUSPECT_TICKS.pop(_stale_key, None)
            if orphan_cnt > 0:
                log(f"ORPHAN_CLEANUP: {orphan_cnt} algo orders cancelled (whipsaw protection)")
        except Exception as cleanup_err:
            log(f"ORPHAN_CLEANUP_ERR: {str(cleanup_err)[:120]}")

        # JOURNAL SELF-HEAL (2026-06-12, INC5 devamı — ATOM 9287aed7 vakası):
        # Fill-detection tek-atımlık yarışlara açık (örn. 429 rate-limit anına
        # denk gelirse kapanış yazımı yarıda kalıyor, protection row 'filled'e
        # geçtiyse bir daha denenmiyor) → journal kaydı sonsuza dek 'filled'
        # kalır, artık emirler orphan-skip'e takılır. Yarışları tek tek kovalamak
        # yerine catch-all: journal'da 'filled' görünen sembolün borsada NE
        # pozisyonu NE SL algo emri varsa (çift kanıt + HEAL_CONFIRM_TICKS
        # ardışık tick teyit) kaydı 'closed' yap (PnL ölçümü zaten income API —
        # journal sadece durum).
        try:
            _heal_con = duckdb.connect(str(JOURNAL))
            # FIX 2026-06-12b (deadlock): önceki şart "sembolde HİÇ algo emri
            # olmasın" idi — artık-TP'ler heal'i, heal'in kapatmadığı journal da
            # orphan-temizliği blokluyordu (karşılıklı bekleme, ATOM 9287aed7).
            # Yeni şart: pozisyon yok + bu sinyalin SL order-id'si açık emirlerde
            # yok (TP artıkları heal'i bloklamaz; SL hâlâ borsadaysa pozisyon
            # stale-read olabilir → heal bekler, çıplaklaştırma riski yok).
            _open_sigs = _heal_con.execute("""
                SELECT s.signal_id, s.symbol, p.sl_order_id,
                       s.ts, s.side, s.strategy, s.fill_price, s.fill_qty, s.sl_price
                FROM futures_signals s
                LEFT JOIN futures_protection_orders p ON p.signal_id = s.signal_id
                WHERE s.status='filled'
                  -- Aktif protection kaydi durable terminal-event replay hattinin
                  -- sorumlulugundadir. Self-heal kesin fill kaniti journal'a
                  -- yazilmadan once sentetik reconcile_orphan uretemez.
                  AND NOT EXISTS (
                      SELECT 1
                      FROM futures_protection_orders ap
                      WHERE ap.signal_id = s.signal_id
                        AND ap.status = 'placed'
                  )
            """).fetchall()
            _algo_ids_now = set(
                str(o.get("algoId", "")) for o in (state.get("algo_orders", []) or [])
            )
            _pos_syms_now = set()
            for _p in positions:
                if abs(float(_p.get("contracts", 0) or 0)) > 1e-9:
                    _pos_syms_now.add(_p.get("symbol", "").split(":")[0].replace("/", ""))
            _seen_heal: set[str] = set()
            _heal_pnl_todo: list = []  # CT-EXE-02 PnL yazımı _heal_con kapandıktan SONRA
            for (
                _sid,
                _ssym,
                _sl_oid,
                _h_ts,
                _h_side,
                _h_strat,
                _h_entry,
                _h_qty,
                _h_sl,
            ) in _open_sigs:
                _sym_raw = str(_ssym).replace("/", "").replace(":USDT", "")
                _sl_still_open = bool(_sl_oid) and str(_sl_oid) in _algo_ids_now
                if _sym_raw in _pos_syms_now or _sl_still_open:
                    _JOURNAL_HEAL_TICKS.pop(_sid, None)
                    continue
                _seen_heal.add(_sid)
                _streak = _JOURNAL_HEAL_TICKS.get(_sid, 0) + 1
                _JOURNAL_HEAL_TICKS[_sid] = _streak
                if _streak < HEAL_CONFIRM_TICKS:
                    log(
                        f"JOURNAL_HEAL_PENDING: {_ssym} signal={_sid} — "
                        f"{_streak}/{HEAL_CONFIRM_TICKS} ardışık tick; heal bekletildi"
                    )
                    continue
                # CT-EXE-02 (2026-06-15): heal'de GERÇEK borsa realized PnL'i yazılmalı —
                # eskiden heal yalnız status='closed' yapardı → kayıplar gizlenirdi
                # (AF-EXE-20260531-001; ATOM/ZEC −80 görünmezdi).
                # FIX 2026-06-15b (REGRESYON): PnL yazımı buradan ÇIKARILDI. Burada açık
                # rw _heal_con varken TradeJournal'ın read_only bağlantısı (get_partial_
                # pnl_sum) DuckDB "different configuration" hatası veriyordu → income asla
                # yazılamıyordu. Çözüm: sinyali kuyruğa al, PnL'i _heal_con KAPANDIKTAN
                # SONRA yaz (eşzamanlı bağlantı yok).
                _heal_pnl_todo.append(
                    (_sid, _ssym, _h_ts, _h_side, _h_strat, _h_entry, _h_qty, _h_sl)
                )
                _heal_con.execute(
                    "UPDATE futures_signals SET status='closed' WHERE signal_id=?",
                    [_sid],
                )
                _JOURNAL_HEAL_TICKS.pop(_sid, None)
                log(
                    f"JOURNAL_HEAL: {_ssym} signal={_sid} — borsada pozisyon+SL yok "
                    f"({HEAL_CONFIRM_TICKS} ardışık tick) → journal 'closed' yapıldı "
                    f"(kaçan kapanış telafisi)"
                )
            for _stale in [k for k in _JOURNAL_HEAL_TICKS if k not in _seen_heal]:
                _JOURNAL_HEAL_TICKS.pop(_stale, None)
            _heal_con.commit()
            _heal_con.close()
            # CT-EXE-02 PnL yazımı — _heal_con KAPALI olduğu için artık DuckDB
            # bağlantı çakışması yok. Her sinyal kendi try'ında: income oku → record_close.
            # Best-effort: income yok → MISS (PnL satırı yazılmaz), hata → ERR (heal bozulmaz).
            for (
                _sid,
                _ssym,
                _h_ts,
                _h_side,
                _h_strat,
                _h_entry,
                _h_qty,
                _h_sl,
            ) in _heal_pnl_todo:
                try:
                    from datetime import UTC as _UTC
                    from datetime import datetime as _dtheal

                    from price_action.execution.exchange_income import (
                        fetch_realized_income as _fetch_income,
                    )
                    from price_action.execution.trade_journal import (
                        TradeJournal as _TJheal,
                    )

                    _h_ts_open = _h_ts
                    if _h_ts_open is not None and getattr(_h_ts_open, "tzinfo", None) is None:
                        _h_ts_open = _h_ts_open.replace(tzinfo=_UTC)
                    _h_start_ms = int(_h_ts_open.timestamp() * 1000) if _h_ts_open else None
                    _h_income = _fetch_income(ex, _ssym, _h_start_ms)
                    if _h_income is None:
                        log(
                            f"JOURNAL_HEAL_PNL_MISS: {_ssym} sig={_sid} — borsa income "
                            f"alınamadı, PnL satırı yazılmadı (eski davranış)"
                        )
                        continue
                    _tj_heal = _TJheal(db_path=str(JOURNAL))
                    # FULL income − önceki partial'lar = runner dilimi (çift-sayma yok)
                    _h_runner = _h_income - _tj_heal.get_partial_pnl_sum(str(_sid))
                    _tj_heal.record_close(
                        trade_id=str(_sid),
                        ts_open=_h_ts_open or _dtheal.now(_UTC),
                        ts_close=_dtheal.now(_UTC),
                        sym=str(_ssym),
                        side=str(_h_side or "long").lower(),
                        strategy=str(_h_strat or ""),
                        entry_price=float(_h_entry or 0.0),
                        exit_price=float(_h_entry or 0.0),  # exit bilinmiyor; PnL override'dan
                        qty=float(_h_qty or 0.0),
                        sl_price=float(_h_sl or 0.0),
                        close_reason="reconcile_orphan",
                        realized_pnl_override=_h_runner,
                    )
                    log(
                        f"JOURNAL_HEAL_PNL: {_ssym} sig={_sid} "
                        f"income=${_h_runner:+.2f} (borsa REALIZED) → trades_closed"
                    )
                except Exception as _hp_err:
                    log(f"JOURNAL_HEAL_PNL_ERR: {_ssym} {str(_hp_err)[:100]}")
        except Exception as _heal_err:
            log(f"JOURNAL_HEAL_ERR: {str(_heal_err)[:100]}")

        # Algo order fill detection (Binance algo endpoint)
        # PARTIAL-CLOSE AWARE (2026-05-31):
        # Winner-let-run: TP1(%25) + TP2(%25) partial + SL(%50 runner).
        # TP1 kısmi dolup trailing SL cancel-replace yarışında "ikisi de yok"
        # görünürdü → TÜM kaydı 'tp' ile kapatıyordu → runner borsada AÇIK
        # kalırken journal'da kapalı → phantom + sahte PnL.
        # Yeni mantık: borsa güncel pozisyon qty'sini çek; karşılaştır:
        #   borsa_qty > epsilon → KISMİ: partial_closes'a yaz, signal açık kal.
        #   borsa_qty ≈ 0      → TAM: record_close(kalan_qty).
        try:
            con = duckdb.connect(str(JOURNAL))
            our_active_prot = con.execute("""
                SELECT prot_id, symbol, tp_order_id, sl_order_id
                FROM futures_protection_orders WHERE status = 'placed'
            """).fetchall()
            # Mevcut algo IDs
            algo_open_ids = set(str(o.get("algoId", "")) for o in state["algo_orders"])
            # Borsa güncel pozisyon qtyleri (sym_ccxt → qty) — partial-aware için
            _exchange_pos_qty: dict[str, float] = {}
            for _pos in positions:
                _psym = _pos.get("symbol", "")  # "AVAX/USDT:USDT" formatı
                _pqty = abs(float(_pos.get("contracts", 0) or 0))
                if _pqty > 1e-9:
                    _exchange_pos_qty[_psym] = _pqty
            # Kısa sem map: "AVAX/USDT:USDT" → "AVAX/USDT" (journal sym formatı)
            _exchange_pos_qty_j: dict[str, float] = {}
            for _sym_raw, _qty_raw in _exchange_pos_qty.items():
                _sym_j = _sym_raw.split(":")[0]  # "AVAX/USDT"
                _exchange_pos_qty_j[_sym_j] = _qty_raw

            for prot_id, sym, tp_oid, sl_oid in our_active_prot:
                tp_open = tp_oid in algo_open_ids if tp_oid else False
                sl_open = sl_oid in algo_open_ids if sl_oid else False
                # FIX 2026-06-11 (görev #11, ZEC+ATOM vakaları): eski şart yalnız
                # "TP VE SL ikisi de kayıp" idi — 2026-05-31 varsayımı "SL dolunca
                # Binance kardeş TP'leri otomatik iptal eder" testnet ALGO
                # emirlerinde TUTMUYOR: SL tam-kapanışta TP'ler AÇIK kalıyor →
                # tp_open=True → kapanış tespiti sonsuza dek beklemede, journal
                # 'filled' kalır, artık TP'ler orphan-skip korumasına takılırdı.
                # Yeni: SL kayıp + borsada pozisyon qty≈0 (çift kanıt) da tam
                # kapanış sayılır; kalan TP'leri journal kapanınca orphan-temizlik
                # N-tick teyidiyle süpürür.
                # FIX 2026-07-10 (A1-01): karar saf fonksiyonda — TP-kayıp+pozisyon-açık
                # (partial şüphesi) dalı eklendi; W1-S1 sonrası ölen partial tespiti
                # ve ts30 çıpası geri geldi. Bkz _should_check_protection_fills docstring.
                if _should_check_protection_fills(
                    tp_oid, sl_oid, tp_open, sl_open, _exchange_pos_qty_j.get(sym, 0.0)
                ):
                    # TP1 ve SL ikisi de algo_open_ids'de yok.
                    # UYARI: TP2 order_id'si notes'ta saklanıyor (tp2_id=...).
                    # notes parse et — TP2 hâlâ açıksa bu sadece TP1 filldir.
                    _notes_str = ""
                    try:
                        _nr = con.execute(
                            "SELECT notes FROM futures_protection_orders WHERE prot_id=?",
                            [prot_id],
                        ).fetchone()
                        _notes_str = str(_nr[0] or "") if _nr else ""
                    except Exception as _e:
                        # log-only: _notes_str "" kalır → TP2-suz akış (eski davranış)
                        log(f"  TP2_NOTES_READ_FAIL prot_id={prot_id}: {str(_e)[:60]}")
                    _tp2_oid = None
                    if "tp2_id=" in _notes_str:
                        try:
                            _tp2_oid = _notes_str.split("tp2_id=")[-1].strip().split()[0]
                            if not _tp2_oid:
                                _tp2_oid = None
                        except Exception:
                            _tp2_oid = None
                    sym_id = sym.replace("/USDT:USDT", "USDT").replace("/USDT", "USDT")
                    try:
                        hist = ex.fapiPrivateGetAllAlgoOrders({"symbol": sym_id, "limit": 30})
                        # Bug 3 fix: ilk eşleşmede kırma. SL tetiklenince Binance
                        # kardeş TP order'ını otomatik CANCELED yapar; eski döngü
                        # CANCELED order'ı önce yakalarsa gerçek kapanışı kaçırır
                        # ve record_close hiç çağrılmazdı. Çözüm: TP+SL order'ını
                        # ayrı bul, TRIGGERED/FINISHED olana öncelik ver.
                        tp_order = sl_order = tp2_order = None
                        for o in hist:
                            algo_id_str = str(o.get("algoId", ""))
                            if tp_oid and algo_id_str == str(tp_oid):
                                tp_order = o
                            elif sl_oid and algo_id_str == str(sl_oid):
                                sl_order = o
                            elif _tp2_oid and algo_id_str == str(_tp2_oid):
                                tp2_order = o
                        terminal_candidates = _protection_terminal_candidates(
                            sl_order=sl_order,
                            tp1_order=tp_order,
                            tp2_order=tp2_order,
                        )
                        any_terminal = any(
                            o is not None
                            and str(o.get("algoStatus") or "").upper()
                            in (
                                "TRIGGERED",
                                "CANCELED",
                                "CANCELLED",
                                "FINISHED",
                                "EXPIRED",
                            )
                            for o in (tp_order, tp2_order, sl_order)
                        )
                        _prot_qty_now = _exchange_pos_qty_j.get(sym, 0.0)
                        _position_flat = _prot_qty_now <= 1e-6
                        _events_ok = True
                        for _event_index, (_event_order, _event_kind) in enumerate(
                            terminal_candidates
                        ):
                            try:
                                _event_ok = _process_protection_terminal_event(
                                    con=con,
                                    exchange=ex,
                                    prot_id=prot_id,
                                    symbol=sym,
                                    symbol_id=sym_id,
                                    triggered_order=_event_order,
                                    triggered_kind=_event_kind,
                                    position_flat=_position_flat,
                                    is_last_candidate=(
                                        _event_index == len(terminal_candidates) - 1
                                    ),
                                )
                            except Exception as _event_exc:
                                _event_ok = False
                                log(
                                    f"  PROT_EVENT_HELD: {sym} {_event_kind} "
                                    f"{type(_event_exc).__name__}: "
                                    f"{str(_event_exc)[:120]}"
                                )
                            if not _event_ok:
                                _events_ok = False
                                break

                        _ensure_protection_fill_event_table(con)
                        _unprocessed_events = []
                        for _candidate_order, _candidate_kind in terminal_candidates:
                            _candidate_event_id = _protection_fill_event_id(
                                prot_id,
                                _candidate_order,
                                _candidate_kind,
                            )
                            if not con.execute(
                                "SELECT 1 FROM futures_protection_fill_events "
                                "WHERE event_id=?",
                                [_candidate_event_id],
                            ).fetchone():
                                _unprocessed_events.append(_candidate_event_id)

                        _linked_signal_row = con.execute(
                            "SELECT signal_id FROM futures_protection_orders WHERE prot_id=?",
                            [prot_id],
                        ).fetchone()
                        _trade_closed = bool(
                            _linked_signal_row
                            and con.execute(
                                "SELECT 1 FROM futures_trades_closed WHERE trade_id=?",
                                [str(_linked_signal_row[0])],
                            ).fetchone()
                        )
                        if _protection_retirement_ready(
                            position_flat=_position_flat,
                            events_ok=_events_ok,
                            unprocessed_event_count=len(_unprocessed_events),
                            trade_closed=_trade_closed,
                            has_terminal_state=bool(terminal_candidates or any_terminal),
                        ):
                            con.execute(
                                """UPDATE futures_protection_orders SET status='filled' WHERE prot_id=?""",
                                [prot_id],
                            )
                            log(
                                f"PROT_RETIRED_DURABLE: {sym} prot_id={prot_id} "
                                f"events={len(terminal_candidates)}"
                            )
                        elif _position_flat and (terminal_candidates or any_terminal):
                            log(
                                f"PROT_RETIRE_HELD: {sym} prot_id={prot_id} "
                                f"events_ok={_events_ok} pending={len(_unprocessed_events)} "
                                f"trade_closed={_trade_closed}"
                            )

                        # All terminal fills were handled by the durable event loop.
                        continue
                    except Exception as e:
                        # KALAN_ISLER #8: sayaç-only (log zaten var) — akış aynı.
                        record_degraded_read("prot_check.algo_history", e, emit_log=False)
                        log(f"  algo hist err {sym_id}: {str(e)[:80]}")
            con.commit()
            con.close()
        except Exception as e:
            log(f"PROT_CHECK ERROR: {e}")

        # ── Koruma Bekçisi + Trailing Stop (Protection Watchdog) ──────
        # Her açık pozisyonun SL'ini _desired_sl_price() hedefine hizalar:
        #  • SL eksikse → koyar (Madde 1)
        #  • SL varsa ama hedef daha iyiyse → yukarı taşır (FAZ 2a trailing)
        #  • SL yok + kayıtlı SL ihlal → pozisyonu market kapatır (kaçan stop)
        # SL tespiti orderType=STOP_MARKET (SL breakeven'e çıksa da doğru
        # tanınır). Ratchet: SL yalnız lehe taşınır. Kaynak: pyramid_store.
        _pending_retry_entries, _pending_queue_err = _read_pending_retry_entries()
        _pending_queue_fail_closed = False
        if _pending_queue_err is None:
            _pending_queue_read_fail_ticks = 0
        else:
            _pending_queue_read_fail_ticks += 1
            _pending_queue_fail_closed = (
                _pending_queue_read_fail_ticks <= _PENDING_QUEUE_READ_FAIL_CLOSED_TICKS
            )
            log(
                "  PROT_WATCHDOG_PENDING_READ_ERR: "
                f"{_pending_queue_err} — fail-closed="
                f"{_pending_queue_read_fail_ticks}/"
                f"{_PENDING_QUEUE_READ_FAIL_CLOSED_TICKS}"
            )
        try:
            for p in positions:
                _contracts = abs(float(p.get("contracts", 0) or 0))
                if _contracts <= 1e-9:
                    continue
                _sym_raw = p.get("symbol", "")
                _sym_ccxt = _sym_raw.split(":")[0]
                _sym_algo = _sym_ccxt.replace("/", "")
                _side = (p.get("side") or "").lower()
                _entry = float(p.get("entryPrice", 0) or 0)
                _mark = float(p.get("markPrice", 0) or 0)
                _position_info = p.get("info") if isinstance(p.get("info"), dict) else {}
                try:
                    _position_update_ms = float(
                        p.get("updateTime") or _position_info.get("updateTime") or 0
                    )
                except (TypeError, ValueError):
                    _position_update_ms = 0.0
                if _entry <= 0 or _side not in ("long", "short"):
                    continue
                _pending_intent = _pending_retry_intent_for_position(
                    _pending_retry_entries,
                    _sym_ccxt,
                    _side,
                    position_contracts=_contracts,
                    position_entry_price=_entry,
                    position_update_time_ms=(
                        _position_update_ms if _position_update_ms > 0 else None
                    ),
                )
                _pending_watchdog_action = _pending_retry_watchdog_action(
                    _pending_intent,
                    queue_read_fail_closed=_pending_queue_fail_closed,
                )
                # Queue read belirsizliği tek tick'te entry-price fallback veya
                # market-close izni değildir. Fakat kalıcı bozuk queue watchdog'u
                # sonsuza dek susturmasın: yalnız sabit sayıda tick fail-closed.
                if _pending_watchdog_action == "hold_queue_uncertain":
                    log(
                        f"  PROT_WATCHDOG_PENDING_READ_HOLD: {_sym_algo} {_side} — "
                        "queue ownership belirsiz; bu tick koruma mutation atlandı"
                    )
                    continue

                if _pending_watchdog_action == "hold_processor_owned":
                    # Retry processor bu intent'in tek protection writer'ıdır.
                    # Watchdog burada entry-price SL koyarsa veya market kapatırsa
                    # processor'ün orijinal SL/TP finalize'ıyla yarışır; aynı
                    # pozisyona duplicate leg / erken BE kapanışı üretir.
                    log(
                        f"  PROT_WATCHDOG_PENDING_OWNER: {_sym_algo} {_side} "
                        f"intent={_pending_intent['owner_id']} "
                        f"until={_pending_intent['lease_deadline'].isoformat()} — "
                        "retry processor owns original SL/TP; this tick skipped"
                    )
                    continue
                if _pending_watchdog_action == "watchdog_normal_ignore_intent":
                    log(
                        f"  PROT_WATCHDOG_GENERATION_UNVERIFIABLE: "
                        f"{_sym_algo} {_side} intent={_pending_intent['owner_id']} — "
                        "lease expired; old WAL levels ignored"
                    )
                    _pending_intent = None
                    _pending_watchdog_action = "watchdog_normal"
                if _pending_watchdog_action == "watchdog_takeover_original_levels":
                    log(
                        f"  PROT_WATCHDOG_PENDING_LEASE_EXPIRED: {_sym_algo} {_side} "
                        f"intent={_pending_intent['owner_id']} — watchdog takeover uses "
                        f"original SL=${_pending_intent['sl_price']}"
                    )
                # FIX 2026-05-28 (Faz 14.27): SL emir filtresine SIDE eklendi.
                # Önceki bug: STOP_MARKET emirleri yön bağımsız toplanıyordu →
                # pozisyon SHORT'tan LONG'a döndüğünde eski BUY STOP emri "LONG'un
                # SL'i" sanılıyordu (ters yön = işe yaramaz). Doğrusu:
                #   LONG  pozisyon → SL emri SELL side'da (pozisyonu kapatır)
                #   SHORT pozisyon → SL emri BUY  side'da (pozisyonu kapatır)
                _expected_sl_side = "SELL" if _side == "long" else "BUY"
                _sl_orders = []  # (trigger, algoId, qty)
                _orphan_wrong_side = []  # eski yön — iptal edilecek
                for o in state.get("algo_orders", []) or []:
                    if (
                        o.get("symbol") == _sym_algo
                        and str(o.get("orderType", "")).upper() == "STOP_MARKET"
                    ):
                        _t = o.get("triggerPrice") or o.get("stopPrice")
                        _a = o.get("algoId") or o.get("algo_id")
                        _o_side = str(o.get("side", "")).upper()
                        if _t and _a is not None:
                            try:
                                _q = float(o.get("quantity") or o.get("origQty") or 0)
                            except (TypeError, ValueError):
                                _q = 0.0
                            if _o_side == _expected_sl_side:
                                _sl_orders.append((float(_t), _a, _q))
                            else:
                                # Yön mismatch → eski/orphan SL, iptal et
                                _orphan_wrong_side.append((float(_t), _a, _o_side))

                # Yön mismatch SL'leri temizle (defansif)
                for _t, _a, _wrong_side in _orphan_wrong_side:
                    try:
                        ex.fapiPrivateDeleteAlgoOrder({"symbol": _sym_algo, "algoId": _a})
                        log(
                            f"  PROT_WATCHDOG: {_sym_algo} ters-yön SL iptal "
                            f"(algoId={_a}, side={_wrong_side}, pos={_side}, trigger=${_t})"
                        )
                    except Exception as _cx:
                        log(
                            f"  PROT_WATCHDOG: {_sym_algo} ters-yön SL iptal "
                            f"FAIL ({_cx}); algoId={_a}"
                        )
                # En iyi mevcut SL (long→en yüksek, short→en düşük trigger)
                _cur_sl = _cur_aid = None
                _cur_sl_qty = 0.0
                if _sl_orders:
                    _cur_sl, _cur_aid, _cur_sl_qty = (max if _side == "long" else min)(
                        _sl_orders, key=lambda t: t[0]
                    )
                # Fazla SL'leri temizle (en iyinin dışındakiler)
                for _t, _a, _q in _sl_orders:
                    if _a != _cur_aid:
                        try:
                            ex.fapiPrivateDeleteAlgoOrder({"symbol": _sym_algo, "algoId": _a})
                            log(f"  PROT_WATCHDOG: {_sym_algo} fazla SL iptal (algoId={_a})")
                        except Exception as _e:
                            # log-only: iptal edilemeyen fazla-SL sonraki tick'te tekrar denenir
                            log(f"  EXCESS_SL_CANCEL_FAIL {_sym_algo} algoId={_a}: {str(_e)[:60]}")
                # pyramid_store'dan orijinal SL + leg-1 entry.
                # ÖNEMLİ: TP1/TP2/R hesabı leg-1 (orijinal) entry ile yapılmalı.
                # Borsa entryPrice'ı pyramid ADD sonrası ortalama → şişer →
                # TP2 yanlış hesaplanır, trailing hiç tetiklenmez.
                # Lease bittiyse entry-price fallback yerine queue'daki orijinal
                # risk seviyesiyle devral. Bu, bounded lease sonrasında watchdog'u
                # tekrar etkinleştirir ama BE'de yanlış close/SL üretmez.
                _intended_sl = (
                    float(_pending_intent["sl_price"]) if _pending_intent is not None else None
                )
                _pyr_entry = None
                _pyr_pos_obj = None
                for _pp in (_pyramid_positions or {}).values():
                    if (
                        getattr(_pp, "symbol", "") == _sym_ccxt
                        and str(getattr(_pp, "side", "")).lower() == _side
                    ):
                        _intended_sl = float(getattr(_pp, "sl_price", 0) or 0)
                        _pyr_entry = float(getattr(_pp, "entry_price", 0) or 0)
                        _pyr_pos_obj = _pp
                        break
                if not _intended_sl or _intended_sl <= 0:
                    # FIX 2026-06-05: ÖNCE girişte saklanan STABİL orijinal SL'i dene.
                    # v13'te pyramid KAPALI → _pyramid_positions kaydı yok → eskiden hareketli
                    # borsa SL'i (G22) intended_sl olurdu; SL ratchet'le taşındıkça initial_r
                    # küçülüp tp1 kayar → trailing DONAR (XRP +$64→$0 kapandı). Orijinal SL
                    # sabit olduğu için BE-lock + %4 trailing doğru hesaplanır.
                    _orig_sl = _ORIG_INTENDED_SL.get(f"{_sym_algo}|{_side}", 0.0)
                    if _orig_sl and _orig_sl > 0:
                        _intended_sl = _orig_sl
                    # G22 (orijinal SL de yok): borsadaki mevcut SL'i taban al. Restart sonrası
                    # _pyramid_positions boş; borsadaki SL zaten yerleştirilmiş → onu kullan.
                    elif _cur_sl is not None and _cur_sl > 0:
                        _intended_sl = _cur_sl
                        log(
                            f"  PROT_WATCHDOG_G22: {_sym_algo} pyramid kaydı yok — "
                            f"exchange SL ${_cur_sl} intended_sl olarak kullanılıyor"
                        )
                    elif _entry > 0:
                        # PROT_WATCHDOG_HEAL (2026-06-03): çıplak pozisyon — pyramid
                        # kaydı YOK ve borsada SL de YOK. Sebep: TP1 fill cancel-replace
                        # yarışı (satır ~933 "ikisi de yok" penceresi) veya restart
                        # rebuild'inin stub kaydı pyramid metadata'sını kaybetmesi.
                        # ESKİ davranış: "manuel müdahale gerek" + continue → pozisyon
                        # korumasız kalıyordu (ZEC/DOT 2026-06-03'te 4+ saat çıplak).
                        # YENİ: intended_sl=entry → _desired_sl_price breakeven (entry)
                        # döner → aşağıdaki "SL eksikti → kondu" bloğu BE stop yerleştirir.
                        #   • karda pozisyon (long: entry<mark): geçerli breakeven stop.
                        #   • zararda çıplak (entry>=mark): _breached → market close
                        #     (korumasız zarar pozisyonu güvenle düzleştirilir).
                        _intended_sl = _entry
                        log(
                            f"  PROT_WATCHDOG_HEAL: {_sym_algo} çıplak (pyramid+SL yok) "
                            f"→ breakeven SL @ ${_entry} yerleştiriliyor"
                        )
                        # continue YOK — SL yerleştirme bloğuna düş.
                    else:
                        log(
                            f"  PROT_WATCHDOG_ALARM: {_sym_algo} SL YOK + pyramid kaydı yok "
                            f"+ entry geçersiz ({_entry}) — manuel müdahale gerek"
                        )
                        continue
                # R/TP hesabı için leg-1 entry; yoksa borsa entry'ye düş
                _calc_entry = _pyr_entry if (_pyr_entry and _pyr_entry > 0) else _entry
                # Seçenek-D BE-protect: pyramid leg-2+ FILLED ise SL tabanı entry.
                # PyramidPosition.legs içinde leg_num >= 2 ve leg_state == "FILLED"
                # olan var mı kontrol et. Default False → backward-compat.
                _pyr_leg_filled = False
                if _pyr_pos_obj is not None:
                    for _lg in getattr(_pyr_pos_obj, "legs", []):
                        if (
                            getattr(_lg, "leg_num", 0) >= 2
                            and getattr(_lg, "leg_state", "") == "FILLED"
                        ):
                            _pyr_leg_filled = True
                            break
                # Hedef SL (TP2 sonrası trailing — kullanıcı kuralı; BE-protect ile birlikte)
                _sl_price = _desired_sl_price(
                    _side, _calc_entry, _intended_sl, _mark, pyramid_leg_filled=_pyr_leg_filled
                )
                _close_side = "SELL" if _side == "long" else "BUY"

                # ── RUNNER TIME-STOP (ts30) ───────────────────────────────
                # Force-exit if runner phase has been active ≥ _RUNNER_MAX_BARS bars.
                # Anchor: ts_close of the first TP1 partial close for this position
                # (from futures_partial_closes journal table).  Restart-safe: derived
                # from DB each tick — no in-memory counter.  Fires BEFORE the trailing
                # SL block; BE-lock + 4% trail remain active and whichever triggers
                # first (trail hit OR time-stop) closes the runner.
                # Ref: exit_tournament_verdict.md §6 fallback params.
                try:
                    _runner_ts_fired = False
                    # Only relevant when position is in runner phase (mark >= TP1).
                    _initial_r_ts = abs(_calc_entry - _intended_sl)
                    _in_runner = (
                        _initial_r_ts > 0
                        and _mark > 0
                        and (
                            (_side == "long" and _mark >= _calc_entry + _initial_r_ts)
                            or (_side == "short" and _mark <= _calc_entry - _initial_r_ts)
                        )
                    )
                    if _in_runner:
                        # İlk TP1 partial ts'i — TRADE-scoped (W1 fix 2026-07-08):
                        # yalnız bu sembol+yönün EN YENİ 'filled' sinyalinin kendi
                        # partial'ı çıpa olur (zombi sinyal çıpası yeni kazananı
                        # kapattıramaz). Sorgu: _runner_timestop_anchor_ts().
                        _runner_anchor_ts: datetime | None = None
                        try:
                            _jcon_ts = duckdb.connect(str(JOURNAL), read_only=True)
                            try:
                                _anchor_raw = _runner_timestop_anchor_ts(_jcon_ts, _sym_ccxt, _side)
                                if _anchor_raw is not None:
                                    _runner_anchor_ts = _anchor_raw
                                    if (
                                        hasattr(_runner_anchor_ts, "tzinfo")
                                        and _runner_anchor_ts.tzinfo is None
                                    ):
                                        _runner_anchor_ts = _runner_anchor_ts.replace(tzinfo=UTC)
                            finally:
                                _jcon_ts.close()
                        except Exception as _ts_db_err:
                            log(f"  RUNNER_TS_LOOKUP_ERR: {_sym_algo}: {str(_ts_db_err)[:80]}")

                        if _runner_anchor_ts is not None:
                            _bars_in_runner = (
                                datetime.now(UTC) - _runner_anchor_ts
                            ).total_seconds() / _RUNNER_BAR_SECONDS
                            if _bars_in_runner >= _RUNNER_MAX_BARS:
                                _runner_ts_fired = True
                                log(
                                    f"  RUNNER_TIMESTOP: {_sym_algo} {_side} "
                                    f"runner={_bars_in_runner:.1f} bars >= {_RUNNER_MAX_BARS} "
                                    f"(anchor={_runner_anchor_ts.strftime('%H:%MZ')}) "
                                    f"→ force-close at market"
                                )

                    if _runner_ts_fired:
                        try:
                            _qty_str_ts = ex.amount_to_precision(_sym_ccxt, _contracts)
                            ex.create_order(
                                symbol=_sym_ccxt,
                                type="MARKET",
                                side=_close_side,
                                amount=float(_qty_str_ts),
                                params={"reduceOnly": True},
                            )
                            log(
                                f"  RUNNER_TIMESTOP_FILLED: {_sym_algo} market close sent "
                                f"qty={_qty_str_ts} mark=${_mark:.4f} "
                                f"(reconcile_orphan will record close on next tick)"
                            )
                        except Exception as _ts_close_err:
                            log(
                                f"  RUNNER_TIMESTOP_CLOSE_ERR: {_sym_algo}: "
                                f"{str(_ts_close_err)[:110]}"
                            )
                        continue  # skip SL ratchet for this position this tick
                except Exception as _ts_outer_err:
                    log(f"  RUNNER_TIMESTOP_ERR: {_sym_algo}: {str(_ts_outer_err)[:110]}")
                # ── END RUNNER TIME-STOP ──────────────────────────────────

                try:
                    _qty_str = ex.amount_to_precision(_sym_ccxt, _contracts)
                    if _cur_sl is None:
                        # SL hiç yok
                        _breached = _mark > 0 and (
                            (_side == "long" and _sl_price >= _mark)
                            or (_side == "short" and _sl_price <= _mark)
                        )
                        if _breached:
                            # Çıplak + SL seviyesi ihlal → kapat. Önce reduceOnly
                            # market; testnet -2022 "ReduceOnly rejected" alırsa
                            # reduceOnly'siz plain-market'e düş (TAZE qty ile —
                            # stale qty ters pozisyon açmasın). Böylece çıplak
                            # zarar pozisyonu HER ZAMAN kapanır (asla naked kalmaz).
                            # FIX 2026-06-04: AVAX -2022 olayı (manuel kapatma gerekmişti).
                            try:
                                ex.create_order(
                                    symbol=_sym_ccxt,
                                    type="MARKET",
                                    side=_close_side,
                                    amount=float(_qty_str),
                                    params={"reduceOnly": True},
                                )
                                log(
                                    f"  PROT_WATCHDOG: {_sym_algo} SL yok + ${_sl_price} "
                                    f"ihlal — market(reduceOnly) kapatıldı qty={_qty_str}"
                                )
                            except Exception as _ro_err:
                                _fresh_amt = 0.0
                                try:
                                    for _fp in ex.fetch_positions([_sym_ccxt]):
                                        _pa = abs(float(_fp["info"].get("positionAmt", 0) or 0))
                                        if _pa > 0:
                                            _fresh_amt = _pa
                                            break
                                except Exception as _fq_exc:
                                    # KALAN_ISLER #8: önceden sessizdi (stale qty'ye
                                    # düşülüyordu) — sayaç + marker; dönüş aynı.
                                    record_degraded_read(
                                        "prot_watchdog.fetch_positions_fresh",
                                        _fq_exc,
                                        log_fn=log,
                                    )
                                    _fresh_amt = _contracts
                                if _fresh_amt > 0:
                                    _fresh_qty = ex.amount_to_precision(_sym_ccxt, _fresh_amt)
                                    ex.create_order(
                                        symbol=_sym_ccxt,
                                        type="MARKET",
                                        side=_close_side,
                                        amount=float(_fresh_qty),
                                    )
                                    log(
                                        f"  PROT_WATCHDOG_HEAL: {_sym_algo} reduceOnly "
                                        f"reddedildi ({str(_ro_err)[:40]}) → plain-market "
                                        f"kapatıldı qty={_fresh_qty}"
                                    )
                                else:
                                    log(
                                        f"  PROT_WATCHDOG: {_sym_algo} kapatma atlandı "
                                        f"— pozisyon zaten kapanmış"
                                    )
                        else:
                            _sl_str = ex.price_to_precision(_sym_ccxt, _sl_price)
                            _new_sl_ord = ex.create_order(
                                symbol=_sym_ccxt,
                                type="STOP_MARKET",
                                side=_close_side,
                                amount=float(_qty_str),
                                params={
                                    "stopPrice": _sl_str,
                                    "reduceOnly": True,
                                    "workingType": "MARK_PRICE",
                                },
                            )
                            # W1 fix 2026-07-08: journal sl_order_id senkronu
                            _update_journal_sl_order_id(
                                _sym_ccxt, _side, (_new_sl_ord or {}).get("id")
                            )
                            log(
                                f"  PROT_WATCHDOG: {_sym_algo} SL eksikti → "
                                f"kondu @ ${_sl_str} qty={_qty_str}"
                            )
                    else:
                        # B-2 fix (CEO 2026-05-20): SL qty pozisyonu tam
                        # kapsamıyorsa (pyramid leg / re-arm pozisyonu
                        # büyüttü, eski SL küçük kaldı) tam qty'ye çek.
                        # reduceOnly → güvenli; mevcut trigger fiyatı korunur.
                        # Önce tam qty yeni SL, sonra eski kısmi SL iptal.
                        if _cur_sl_qty > 0 and _cur_sl_qty < _contracts * 0.99:
                            _sl_str = ex.price_to_precision(_sym_ccxt, _cur_sl)
                            _new_sl_ord = ex.create_order(
                                symbol=_sym_ccxt,
                                type="STOP_MARKET",
                                side=_close_side,
                                amount=float(_qty_str),
                                params={
                                    "stopPrice": _sl_str,
                                    "reduceOnly": True,
                                    "workingType": "MARK_PRICE",
                                },
                            )
                            # W1 fix 2026-07-08: journal sl_order_id senkronu
                            _update_journal_sl_order_id(
                                _sym_ccxt, _side, (_new_sl_ord or {}).get("id")
                            )
                            try:
                                ex.fapiPrivateDeleteAlgoOrder(
                                    {"symbol": _sym_algo, "algoId": _cur_aid}
                                )
                            except Exception as _cx:
                                log(
                                    f"  PROT_WATCHDOG: {_sym_algo} eski "
                                    f"kısmi SL iptal edilemedi: "
                                    f"{str(_cx)[:60]}"
                                )
                            log(
                                f"  PROT_WATCHDOG: {_sym_algo} SL qty "
                                f"eksik ({_cur_sl_qty}/{_contracts}) → "
                                f"tam qty'ye çekildi @ ${_sl_str}"
                            )
                            continue
                        # SL var → ratchet: hedef daha iyiyse taşı
                        _tol = _mark * 0.0005 if _mark > 0 else 0.0
                        _better = (
                            (_sl_price > _cur_sl + _tol)
                            if _side == "long"
                            else (_sl_price < _cur_sl - _tol)
                        )
                        if not _better:
                            continue
                        _sl_str = ex.price_to_precision(_sym_ccxt, _sl_price)
                        # Önce yeni koy, sonra eskiyi iptal (asla çıplak kalmaz)
                        _new_sl_ord = ex.create_order(
                            symbol=_sym_ccxt,
                            type="STOP_MARKET",
                            side=_close_side,
                            amount=float(_qty_str),
                            params={
                                "stopPrice": _sl_str,
                                "reduceOnly": True,
                                "workingType": "MARK_PRICE",
                            },
                        )
                        # W1 fix 2026-07-08: journal sl_order_id senkronu — bundan
                        # sonra heal/fill-detection taze ID'ye bakar (bayat-ID
                        # false-close kaskadının kök beslemesi kapandı)
                        _update_journal_sl_order_id(_sym_ccxt, _side, (_new_sl_ord or {}).get("id"))
                        try:
                            ex.fapiPrivateDeleteAlgoOrder({"symbol": _sym_algo, "algoId": _cur_aid})
                        except Exception as _cx:
                            log(
                                f"  PROT_WATCHDOG: {_sym_algo} eski SL iptal "
                                f"edilemedi: {str(_cx)[:60]}"
                            )
                        log(
                            f"  PROT_WATCHDOG: {_sym_algo} SL taşındı "
                            f"${_cur_sl} → ${_sl_str} (trailing)"
                        )
                except Exception as _wd_place_err:
                    log(f"  PROT_WATCHDOG_FAIL: {_sym_algo}: {str(_wd_place_err)[:110]}")
        except Exception as _wd_err:
            log(f"  PROT_WATCHDOG_ERR: {str(_wd_err)[:120]}")

        # ── SEC54.3: PyramidRouter hook (60s tick) ────────────────────
        # Aktif pyramid pozisyonlarını kontrol et.
        # _pyramid_positions dict'i futures_trade_daily.py'deki
        # submit_to_futures() fill sonrası doldurulmalı (SEC54.4 bağlantısı).
        # Şimdi: mevcut exchange pozisyonlarından mark price oku, PyramidRouter'a ilet.
        try:
            if _pyramid_positions:
                pr = _get_pyramid_router(ex)
                if pr is not None:
                    now_ts = datetime.now(UTC)
                    for pos_id, pyr_pos in list(_pyramid_positions.items()):
                        sym = getattr(pyr_pos, "symbol", None)
                        if not sym:
                            continue
                        # Mark price: exchange pozisyonlarından al
                        mark_px = None
                        for p in positions:
                            if p.get("symbol", "").replace(":USDT", "") == sym.replace(":", ""):
                                mark_px = float(p.get("markPrice") or p.get("entryPrice") or 0)
                                break
                        if not mark_px or mark_px <= 0:
                            continue
                        try:
                            pr.on_position_check(pyr_pos, mark_px, now_ts)
                            # SEC58-L2: leg state değişmiş olabilir → persist
                            try:
                                _ps = _get_pyramid_store()
                                if _ps is not None:
                                    _ps.upsert_position(pyr_pos)
                            except Exception as _ps_upd_err:
                                log(f"PYRAMID_STORE_UPSERT_ERR pos={pos_id}: {_ps_upd_err}")
                        except Exception as pyr_exc:
                            log(f"PYRAMID_CHECK_ERR pos={pos_id}: {str(pyr_exc)[:120]}")
        except Exception as pyr_loop_err:
            log(f"PYRAMID_LOOP_ERR: {str(pyr_loop_err)[:120]}")

        return state

    except Exception as e:
        log(f"POS_CHECK ERROR: {e}")
        # P2-#11 minimal-güvenli varyant (2026-07-10): HEAL/PROT dev-bloklarında
        # exception anında açık kalmış journal bağlantılarını best-effort kapat
        # (leak → DuckDB single-writer lock contention). Tam try/finally dönüşümü
        # (70/430 satır re-indent) bilinçli yapılmadı — bu handler tüm blokların
        # ortak çatısı olduğundan sızıntıyı aynı güvenceyle kapatır.
        import contextlib as _ctx

        for _leak_name in ("con", "_heal_con", "_jcon"):
            _leak_con = locals().get(_leak_name)
            if _leak_con is not None and hasattr(_leak_con, "close"):
                with _ctx.suppress(Exception):
                    _leak_con.close()
        return None


# =====================================================================
# 15m helpers (SEC54.4)
# =====================================================================


def next_15m_boundary() -> datetime:
    """Bir sonraki 15 dakikalık bar kapanış anını (UTC, sekunde sıfır) döner.

    Örnekler:
      14:07 UTC → 14:15 UTC
      14:45 UTC → 15:00 UTC
      14:59 UTC → 15:00 UTC
    """
    return next_tf_boundary(15)


def next_5m_boundary() -> datetime:
    """Bir sonraki 5 dakikalık bar kapanış anını (UTC, sekunde sıfır) döner.

    Örnekler:
      14:07 UTC → 14:10 UTC
      14:13 UTC → 14:15 UTC
      14:58 UTC → 15:00 UTC
    """
    return next_tf_boundary(5)


def next_tf_boundary(tf_minutes: int) -> datetime:
    """Generic: bir sonraki tf-dakikalık bar boundary'sini döner."""
    now = datetime.now(UTC)
    minute = now.minute
    next_min = ((minute // tf_minutes) + 1) * tf_minutes
    if next_min >= 60:
        new_hour = now.hour + 1
        if new_hour >= 24:
            tomorrow = now + timedelta(days=1)
            return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        return now.replace(hour=new_hour, minute=0, second=0, microsecond=0)
    return now.replace(minute=next_min, second=0, microsecond=0)


def sleep_until(target: datetime) -> None:
    """target UTC anına kadar bekle. Geçmiş ise anında döner."""
    now = datetime.now(UTC)
    delta = (target - now).total_seconds()
    if delta > 0:
        time.sleep(delta)


def _scan_signals_15m(target_dt: datetime) -> list:
    """15m tarama: futures_trade_15m.scan_signals_15m wrapper (P-04 fix).

    futures_trade_15m.scan_signals_15m(target_bar_close) → 15m signal list.
    Bu fonksiyon TOP-4 15m stratejilerini (C2 champion) çalıştırır.
    """
    try:
        from scripts.futures_trade_15m import scan_signals_15m

        sigs = scan_signals_15m(target_dt)
        return sigs
    except Exception as e:
        log(
            f"15M_SCAN_FAILED: {e} — bu tick'in '0 sinyal' görünümü GEÇERSİZ "
            f"(tarama hatası, piyasa-sinyalsizliği değil)"
        )
        return []


def run_15m_mode(once: bool = False) -> None:
    """15 dakikalık intraday daemon loop.

    Bar-close detect: UTC :00/:15/:30/:45 + 5s buffer
    DMS: TF_DMS_PARAMS["15m"] (heartbeat=20s, timeout=1800s)
    Stale signal guard: >30 dk → REJECT (DQ-02)
    Pyramid hook: SEC54.3 pyramid_router.on_position_check (graceful if not yet present)
    """
    global _DAEMON_PRIVATE_EXCHANGE

    # FIX 2026-05-28 (audit-A1): SIGTERM/SIGHUP handler kur.
    # PID 17267 sessiz öldü çünkü signal handler yoktu — Python interpreter
    # cleanup yaptı (stderr'e resource_tracker warning düştü) ama futures_daemon.log'a
    # "shutdown" satırı yazılmadı. Şimdi handler "SIGNAL_RECEIVED: SIGTERM" log'layıp
    # _stop_flag set ediyor; main loop bunu kontrol edip clean exit yapacak.
    _install_signal_handlers()

    # WIRE-widestop fix (2026-05-22): 15m daemon journal-tablo init.
    # run_15m_mode init_futures_journal()'i HİÇ çağırmıyordu → taze
    # futures_journal.duckdb'de futures_protection_orders / futures_signals vb.
    # tablolar yoktu (PROT_CHECK ERROR + ilk pozisyonda INSERT patlardı). 1d yolu
    # (_init_dead_mans_switch) bunu yapıyor; 15m yolu atlamıştı. CREATE TABLE IF
    # NOT EXISTS → idempotent, mevcut DB'ye zarar vermez.
    try:
        from scripts.futures_trade_daily import init_futures_journal

        init_futures_journal()
        log("15M_JOURNAL_INIT: futures_journal tabloları hazır")
    except Exception as _ji_err:
        log(f"15M_JOURNAL_INIT_ERR: {_ji_err} — journal tabloları eksik kalabilir")

    try:
        from price_action.execution.dead_mans_switch import DeadMansSwitch
        from scripts.futures_trade_daily import (
            get_binance_ban_until as _get_binance_ban_until_dms,
        )
        from scripts.futures_trade_daily import get_futures_exchange as _get_fx_dms

        # G21 fix (hard review 2026-05-21): DMS'e gerçek exchange ver — eskiden
        # exchange=None idi → _emergency_flatten pozisyon kapatamıyordu (sahte
        # güvenlik). Ayrı instance: DMS watchdog thread'i ana loop ile çakışmasın.
        _dms_exchange = _get_fx_dms()
        dms_15m = DeadMansSwitch(
            exchange=_dms_exchange,
            service_name="futures_daemon_15m",
            tf="15m",
            db_path=IDEMPOTENCY_DB,
            # Main-loop liveness is the heartbeat. The DMS must not mask a
            # stalled scan loop or poll two private REST endpoints every 20s.
            # Its exchange handle remains available only for stale-triggered
            # emergency flatten.
            external_heartbeat=True,
            # Shared 418 state closes the local HTTP gate. Preserve the finite
            # emergency retry budget until that deadline, then resume flatten.
            retry_not_before_reader=_get_binance_ban_until_dms,
        )
        dms_15m.start()
        log(
            "15M_DMS: başlatıldı (tf=15m, heartbeat=external-main-loop, "
            "timeout=1800s, background REST poll=OFF, flatten AKTİF)"
        )
    except Exception as e:
        # FAIL-CLOSED (2026-07-10 Principal onayı): DMS kurulamadıysa KORUMASIZ
        # koşmayı REDDET (eski: switch'siz devam = fail-open). launchd yeniden
        # dener; ardışık başarısızlıkta DR9 crash-loop alarmı Principal'e gider.
        log(f"15M_DMS_INIT_FATAL: {e} — DMS'siz koşmak reddedildi (fail-closed)")
        raise SystemExit(f"15M_DMS_INIT_FATAL: {e}") from e

    # Prometheus metrics — lazy import (metrics yoksa graceful)
    try:
        from price_action.api.prometheus_metrics import (
            missed_bars_total,
            position_monitor_duration_seconds,
            scan_latency_seconds,
            signal_to_order_latency_seconds,
        )

        _metrics_ok = True
    except Exception:
        _metrics_ok = False

    # Pyramid router — SEC54.3 (P-04/P-05 fix: build_position_from_signal + pop on close)
    # Post-only flag 15m YAML'den okunur (2026-05-21: paper fill rate %87.5 → enabled)
    _pyramid_router_15m = None
    # FIX 2026-05-26 (Faz 14.9): pyramid_enabled gate.
    # Config kapalıysa init etme → eski store'daki PENDING leg'ler tetiklenmez.
    if not _pyramid_enabled_15m():
        log("15M_PYRAMID: skip init (strategy_portfolio.pyramid_enabled=false)")
    else:
        try:
            import yaml as _yaml_pr

            _pr_yaml_path = _risk_config_15m()
            with open(_pr_yaml_path, encoding="utf-8") as _pr_f:
                _pr_cfg = _yaml_pr.safe_load(_pr_f) or {}
            _pr_exec = _pr_cfg.get("execution", {})
            _pr_po_enabled = bool(_pr_exec.get("post_only_limit_enabled", False))
            _pr_po_timeout = int(_pr_exec.get("post_only_fallback_seconds", 30))
            _pr_slip_limit = float(_pr_exec.get("slippage_limit_bps", 25.0))
            # pyramid_slippage_limit_bps: pyramid leg için ayrı market-fallback cap (default 50bps)
            _pr_pyr_slip = float(_pr_exec.get("pyramid_slippage_limit_bps", 50.0))
            from price_action.execution.idempotency import IdempotencyStore
            from price_action.execution.pyramid_router import PyramidRouter
            from price_action.execution.slippage_tracker import SlippageTracker

            _pyramid_router_15m = PyramidRouter(
                exchange=None,  # başlangıçta None; exchange signal submit sonrası set edilir
                idempotency_store=IdempotencyStore(db_path=IDEMPOTENCY_DB),
                slippage_tracker=SlippageTracker(),
                post_only_enabled=_pr_po_enabled,
                fallback_seconds=_pr_po_timeout,
                slippage_limit_bps=_pr_pyr_slip,
                mode=os.environ.get("PA_RUN_MODE", "paper"),
            )
            log(
                f"15M_PYRAMID: PyramidRouter başlatıldı (SEC54.3, post_only={_pr_po_enabled}, "
                f"timeout={_pr_po_timeout}s, slip={_pr_pyr_slip}bps)"
            )
        except Exception as e:
            log(f"15M_PYRAMID_WARN: {e} — pyramid hook atlanıyor")

    # WIRE-widestop (2026-05-22): 15m wide-stop deploy filter threshold.
    # Reject signals whose entry sl_pct = |entry - sl| / entry < sl_pct_min.
    # Read once at startup from the active 15m config's execution block.
    # Default 0.0 = OFF → no signal is rejected → byte-identical to pre-WIRE
    # behavior. Deploy value (0.025) lives in the wide-stop config; activate
    # via PA_15M_CONFIG. See DEPLOY_widestop_15m.md.
    # FIX 2026-05-26 (H4): config load fail → SAFE DEFAULT + CRIT alert
    # Önceden _sl_pct_min_15m=0.0 fallback → widestop filter KAPALI → TÜM
    # sinyaller geçer (catastrophic). Yeni: fail safe (1.0 = %100, hiçbir
    # sinyal geçemez) + push_critical.
    _sl_pct_min_15m = 0.0
    _sl_cfg_load_ok = False
    # T2-02: kaldıraç tek-kaynak tutarlılık kontrolü (aşağıdaki yaml-load'ı paylaşır)
    _yaml_lev_max = None
    try:
        import yaml as _yaml_sl

        with open(_risk_config_15m(), encoding="utf-8") as _sl_f:
            _sl_cfg_raw = _yaml_sl.safe_load(_sl_f) or {}
        _sl_raw_val = (_sl_cfg_raw.get("execution", {}) or {}).get("sl_pct_min")
        if _sl_raw_val is None:
            # FAIL-CLOSED (E7, 2026-07-10 Principal onayı): anahtar YOKSA filtre
            # sessizce kapanıyordu (0.0 default = tüm sinyaller geçer, fee-kalkanı
            # yok). Artık exception-yoluyla AYNI: 1.0 = hiçbir sinyal geçemez.
            log(
                "15M_WIDESTOP_KEY_MISSING: execution.sl_pct_min anahtarı yok — "
                "FAIL-CLOSED sl_pct_min=1.0 (TÜM sinyaller reddedilecek)"
            )
            _sl_pct_min_15m = 1.0
        else:
            _sl_pct_min_15m = float(_sl_raw_val)
        _sl_cfg_load_ok = True
        _yaml_lev_max = (_sl_cfg_raw.get("leverage") or {}).get("max_leverage_per_symbol")
        if _yaml_lev_max is not None and int(_yaml_lev_max) != _LEV_HARD_CAP:
            log(
                f"LEV_CAP_MISMATCH: yaml max_leverage_per_symbol={_yaml_lev_max} != "
                f"hard-cap {_LEV_HARD_CAP} — min(ikisi) uygulanır (T2-02 hiyerarşi)"
            )
    except Exception as _sl_err:
        log(
            f"15M_WIDESTOP_CFG_FAIL: {_sl_err} — SAFE DEFAULT sl_pct_min=1.0 (TÜM sinyaller reddedilecek)"
        )
        _sl_pct_min_15m = 1.0  # %100 — hiçbir sinyal bunu geçemez
        # Telegram alert: config eksikse Principal HEMEN bilsin
        try:
            from price_action.orchestrator.notifications import push_critical as _pc_h4

            _pc_h4(
                f"15m risk config LOAD FAIL — daemon SAFE MODE'da "
                f"(sl_pct_min=1.0, tüm sinyaller reddedilir). "
                f"Path: {_risk_config_15m()} | Err: {str(_sl_err)[:120]}",
                source="futures15m_startup",
            )
        except Exception:
            pass
    if _sl_cfg_load_ok and _sl_pct_min_15m > 0.0:
        log(
            f"15M_WIDESTOP: sl_pct_min={_sl_pct_min_15m:.4f} AKTİF — "
            f"dar-stop sinyaller REJECT edilecek"
        )
    elif not _sl_cfg_load_ok:
        log(
            f"15M_WIDESTOP_SAFE_MODE: sl_pct_min={_sl_pct_min_15m:.4f} "
            f"(config load fail — tüm sinyaller reddedilir; config'i düzelt + daemon restart)"
        )

    # SEC58-L2: startup'ta DB'den aktif pyramid pozisyonlarını yükle (restart recovery)
    _pyramid_store_load_on_startup()

    # FIX 2026-05-31 (Faz restart-rebuild): pyramid_store boşsa borsadaki açık
    # pozisyonlar için takip kaydını yeniden kur (trailing donukluğunu önler).
    # G22 yolu (_cur_sl → intended_sl) initial_r'yi yanlış hesaplıyor çünkü
    # exchange SL'i trailing sonrası taşınmış olabilir → bu rebuild orijinal
    # entry + sl_price'ı journal'dan alarak _desired_sl_price() hesabını doğru yapar.
    try:
        from scripts.futures_trade_daily import get_futures_exchange as _get_fx_rb

        _DAEMON_PRIVATE_EXCHANGE = _get_fx_rb()
        _rebuild_position_tracking_from_exchange(_DAEMON_PRIVATE_EXCHANGE)
        log("15M_EXCHANGE_CLIENT: process-long main client hazır (DMS ayrı instance)")
    except Exception as _rb_err:
        log(
            f"REBUILD_TRACKING_INIT_ERR: {_rb_err} — takip kaydı yeniden kurulamadı, G22 fallback devam"
        )

    log("=" * 60)
    log("FUTURES 15M DAEMON STARTED")
    log("  - Signal scan: her 15 dakikada (bar-close + 5s buffer)")
    log("  - Position monitor: her bar (pyramid trigger detection)")
    log("  - DMS heartbeat: ana-loop bar tick'i (tf=15m, timeout=30dk, background REST yok)")
    log("  - Stale guard: >30 dk sinyal REJECT")
    log("  - Pyramid DB persist: pyramid_store.duckdb (SEC58-L2)")
    log("=" * 60)

    # FIX 2026-05-26 (Faz 14.1): Provenance banner — config açıkça beyan
    try:
        from price_action.ops.provenance import config_provenance, format_banner

        _prov = config_provenance(_risk_config_15m())
        for _line in format_banner(_prov, component="FUTURES 15M").splitlines():
            log(_line)
    except Exception as _prov_exc:
        log(f"PROVENANCE_BANNER_FAIL: {_prov_exc}")

    last_bar_boundary: datetime | None = None
    # FIX 2026-05-28 (audit-A1): hata-bazlı exponential backoff sayacı.
    # Önceki bug: `15M_LOOP_ERROR` log'lanıyor sonra hemen sıradaki bar'ı
    # bekliyordu — kalıcı bir hata (ör. DuckDB lock) varsa her tick'te aynı
    # hata, log spam'i, CPU spin. Şimdi ardışık hata sayısına göre 2-60s
    # bekliyoruz; 10+ ardışık hatada daemon abort ediyor (launchd restart eder).
    _err_count = 0
    _ERR_ABORT_THRESHOLD = 10

    try:
        while True:
            # FIX 2026-05-28 (audit-A1): graceful shutdown bayrağı.
            if _stop_flag:
                log("15M_STOP_FLAG aktif — graceful exit (signal handler tetikledi)")
                break

            # Kill-switch kontrolü
            halted, reason = _kill_switch_active()
            if halted:
                log(f"15M_KILL_SWITCH ACTIVE — daemon exiting. Reason: {reason}")
                break

            # FIX 2026-05-28 (audit-Y1): DMS thread health check.
            # DMS heartbeat/watchdog thread'leri ayrı log dosyasına (futures_daemon_15m_dms.log)
            # yazıyor; bu thread'ler sessiz ölürse main loop fark etmiyordu (audit
            # bulgusu: DMS log'unda 25+ "started" satırı, hiç heartbeat satırı yok =
            # restart spam). Şimdi her tick başında is_alive() check; ölü ise abort.
            if dms_15m is not None:
                _hb = getattr(dms_15m, "_heartbeat_thread", None)
                _wd = getattr(dms_15m, "_watchdog_thread", None)
                _external_hb = bool(getattr(dms_15m, "external_heartbeat", False))
                _hb_dead = (not _external_hb) and (_hb is None or not _hb.is_alive())
                _wd_dead = _wd is None or not _wd.is_alive()
                if _hb_dead or _wd_dead:
                    log(
                        f"15M_DMS_THREAD_DEAD: heartbeat_mode="
                        f"{'external' if _external_hb else 'thread'} "
                        f"heartbeat_alive={not _hb_dead} "
                        f"watchdog_alive={not _wd_dead} — emergency shutdown"
                    )
                    try:
                        from price_action.orchestrator.notifications import push_critical

                        push_critical(
                            "⚠️ 15m DMS thread ÖLDÜ (heartbeat veya watchdog) — "
                            "bot acil durduruluyor. launchd KeepAlive restart eder."
                        )
                    except Exception:
                        pass
                    break

            # FIX 2026-05-28 (audit-A1): sleep_until + boundary detect + scan'i
            # tek try'a aldık. Önceden sleep_until (1138) try DIŞINDAYDI →
            # uyku sırasında atılan herhangi bir exception (signal-related,
            # OS interrupt, vb.) hiçbir log yazmadan process'i öldürebiliyordu.
            try:
                # Sonraki bar kapanışını hesapla + 5s buffer ekle
                next_close = next_15m_boundary() + timedelta(seconds=5)
                log(f"15M_WAIT: sonraki bar kapanış {next_close.strftime('%H:%M:%S')} UTC")
                sleep_until(next_close)

                # Sleep sonrası signal geldi mi?
                if _stop_flag:
                    log("15M_STOP_FLAG: uyku sonrası tespit — graceful exit")
                    break

                # Missed bar detect: önceki boundary'den 2+ bar geçti mi?
                current_boundary = next_close - timedelta(seconds=5)
                if last_bar_boundary is not None:
                    bars_elapsed = int((current_boundary - last_bar_boundary).total_seconds() / 900)
                    if bars_elapsed > 1:
                        log(
                            f"15M_MISSED_BARS: {bars_elapsed - 1} bar kaçırıldı "
                            f"(son={last_bar_boundary.strftime('%H:%M')}, "
                            f"şimdi={current_boundary.strftime('%H:%M')})"
                        )
                        if _metrics_ok:
                            try:
                                missed_bars_total.labels(tf="15m").inc(bars_elapsed - 1)
                            except Exception as _m_err:
                                log(f"METRIC_EMIT_ERR: {str(_m_err)[:80]}")  # log-only
                last_bar_boundary = current_boundary

                scan_start = datetime.now(UTC)
                # ------ SIGNAL SCAN ------
                # SEC56 FIX: current_boundary = son kapanan barın close timestamp'i.
                # scan_start = datetime.now() → birkaç saniye sonra olduğu için
                # semantik olarak yanlıştı; current_boundary daha doğru.
                signals = _scan_signals_15m(current_boundary)

                scan_elapsed = (datetime.now(UTC) - scan_start).total_seconds()
                log(f"15M_SCAN: {len(signals)} sinyal, latency={scan_elapsed:.1f}s")
                if _metrics_ok:
                    try:
                        scan_latency_seconds.labels(tf="15m").observe(scan_elapsed)
                    except Exception as _m_err:
                        log(f"METRIC_EMIT_ERR: {str(_m_err)[:80]}")  # log-only

                # ------ SIGNAL FILTER + ORDER SUBMIT (P-04 fix) ------
                # futures_trade_15m.run_15m() tüm filtre + RiskOfficer + submit döngüsünü
                # zaten içeriyor. Ancak daemon flow'unda sinyaller zaten tarandı;
                # burada tekil sinyal başına submit + pyramid build hook yapılıyor.
                # Stale guard futures_trade_15m.filter_stale_signals ile halihazırda uygulandı.
                # Daemon'da ek stale check (DQ-02 defensive double-check):

                # SEC58 CRIT-2 FIX: returns_df loop dışında tek seferlik hesapla.
                # Eski kod her sinyal için build_returns_df() çağırıyordu →
                # Windows DuckDB exclusive lock conflict (read_only=True vs R/W singleton).
                # 90 günlük 1d log-return matrix 15 dakikada değişmez → bar başına 1 çekiş yeterli.
                # A1-04 FIX: matris tüm evrenle kurulur (yalnız sinyal sembolleri
                # DEĞİL) — açık pozisyon sembolleri matriste kalsın, gate kör olmasın.
                from scripts.futures_trade_15m import SYMBOLS as _universe_15m
                from scripts.lib.risk_integration import build_returns_df as _build_returns_df

                _all_scan_syms = _corr_matrix_syms(signals, _universe_15m)
                try:
                    _shared_returns_df = _build_returns_df(
                        _all_scan_syms,
                        days=90,
                        market_db=MARKET_DB,
                    )
                except Exception as _rdf_err:
                    # A1-04: dürüst log — boş DF'te gate KONSERVATIF değil KÖRDÜR
                    log(
                        f"15M_RETURNS_DF_WARN: {_rdf_err} — correlation gate KÖR (fail-open) bu bar"
                    )
                    import pandas as _pd_rdf

                    _shared_returns_df = _pd_rdf.DataFrame()

                import pandas as _pd

                for sig in signals:
                    try:
                        bar_close = sig.get("bar_close_ts") or sig.get("ts")
                        if bar_close is not None:
                            _bc = _pd.Timestamp(bar_close)
                            if _bc.tzinfo is None:
                                _bc = _bc.tz_localize("UTC")
                            age_min = (datetime.now(UTC) - _bc.to_pydatetime()).total_seconds() / 60
                            if age_min > 30:
                                log(
                                    f"  15M_REJECT_STALE(daemon-guard): {sig.get('symbol', '?')} age={age_min:.1f}min"
                                )
                                continue
                    except Exception as age_err:
                        log(f"  15M_STALE_CHECK_ERR: {age_err}")

                    # WIRE-widestop (2026-05-22): wide-stop deploy filter.
                    # Reject narrow-stop signals — entry sl_pct < threshold.
                    # sl_pct is known here from the scan (entry_price + sl_price,
                    # both ATR-derived at bar close → causal, no look-ahead).
                    # _sl_pct_min_15m=0.0 (default) → this block never rejects.
                    # See DEPLOY_widestop_15m.md.
                    if _sl_pct_min_15m > 0.0:
                        _ws_entry = float(sig.get("entry_price") or 0.0)
                        _ws_sl = float(sig.get("sl_price") or 0.0)
                        _ws_sl_pct = abs(_ws_entry - _ws_sl) / _ws_entry if _ws_entry > 0 else 0.0
                        if _ws_sl_pct < _sl_pct_min_15m:
                            log(
                                f"  15M_REJECT_WIDESTOP: {sig.get('symbol', '?')} "
                                f"sl_pct={_ws_sl_pct:.4f} < {_sl_pct_min_15m:.4f}"
                            )
                            continue

                    order_start = datetime.now(UTC)
                    try:
                        import uuid as _uuid

                        import yaml as _yaml

                        from scripts.futures_trade_daily import (
                            _futures_state_entry_trusted,
                            build_protection_plan,
                            ensure_original_level_sl,
                            fetch_futures_state,
                            setup_leverage,
                        )
                        from scripts.lib.risk_integration import (
                            build_futures_account_state,
                            build_signal_from_scan,
                            load_risk_officer,
                        )

                        _ex_submit = _get_daemon_exchange()
                        _state_submit = fetch_futures_state(_ex_submit)

                        # SEC-#3A: Konsantrasyon fail-safe — stale pozisyon dedektörü.
                        # fetch_positions() bazen boş dönebilir (rate-limit 418, API stale)
                        # ama borsada hala açık pozisyon bulunabilir. Bu durumda
                        # concentration_gate "pozisyon yok" sanıp yeni emri geçirir →
                        # ALGO sembolünde yığılma (gözlemlenen: %15→%27).
                        # Stale koşul: positions_ok=False VEYA (positions boş AMA initialMargin>0)
                        # İkinci koşul: fetch_positions() boş döndü ama raw account
                        # totalInitialMargin > 0 → borsada pozisyon var ama liste gelmedi.
                        _pos_ok_15m = _state_submit.get("positions_ok", True)
                        _init_margin_15m = float(_state_submit.get("total_initial_margin", 0))
                        _pos_list_15m = _state_submit.get("positions", [])
                        _exchange_complete_15m = (
                            _state_submit.get("exchange_state_complete") is True
                        )
                        _stale_positions_15m = not _futures_state_entry_trusted(_state_submit)
                        if _stale_positions_15m:
                            log(
                                f"  ENTRY_SKIP_STALE_POS: {sig.get('symbol', '?')} — "
                                f"exchange state güvenilmez "
                                f"(complete={_exchange_complete_15m}, "
                                f"positions_ok={_pos_ok_15m}, "
                                f"order_scope_ok={_state_submit.get('order_scope_ok')}, "
                                f"pos_list_len={len(_pos_list_15m)}, "
                                f"initialMargin={_init_margin_15m:.2f}), giriş atlandı"
                            )
                            continue

                        # New strategy signals never add to an existing net
                        # symbol position.  Pyramids have their own explicit
                        # router/state machine; allowing this path to add would
                        # merge exchange generations and make protection replay
                        # unable to distinguish the old weighted position.
                        _same_symbol_open = _has_existing_symbol_position(
                            _pos_list_15m,
                            sig.get("symbol"),
                        )
                        if _same_symbol_open:
                            log(
                                f"  15M_REJECT_EXISTING_SYMBOL: {sig.get('symbol', '?')} "
                                "— new signal cannot merge with an existing net position"
                            )
                            continue

                        _risk_yaml_path = _risk_config_15m()
                        # FIX 2026-06-10 (BLOCKER-2): bot-bazlı breaker state
                        _breaker_state_path = BREAKER_STATE_15M
                        _breaker_state_path.parent.mkdir(parents=True, exist_ok=True)
                        _risk_officer = load_risk_officer(
                            yaml_path=_risk_yaml_path,
                            breaker_state_path=_breaker_state_path,
                        )
                        with open(_risk_yaml_path, encoding="utf-8") as _f:
                            _risk_cfg = _yaml.safe_load(_f) or {}

                        _account = build_futures_account_state(
                            _state_submit,
                            journal_path=JOURNAL,
                        )
                        # SEC58 CRIT-2: _shared_returns_df loop dışında hazırlandı (no-lock conflict)
                        _returns_df = _shared_returns_df
                        # A1-04 Parça-B (UNI-cut emsali): evrenden çıkarılmış sembolde
                        # açık pozisyon kalırsa matris onu kapsamaz → rebuild dene;
                        # hâlâ yoksa KALICI görünür log (CT-OPS log-pattern yakalar).
                        _missing_pos_syms = [
                            p.symbol
                            for p in _account.open_positions
                            if p.symbol not in _returns_df.columns
                        ]
                        if _missing_pos_syms:
                            try:
                                _returns_df = _build_returns_df(
                                    sorted(set(_all_scan_syms) | set(_missing_pos_syms)),
                                    days=90,
                                    market_db=MARKET_DB,
                                )
                            except Exception as _rdf_err2:
                                log(f"  15M_RETURNS_DF_WARN: pos-sym rebuild fail {_rdf_err2}")
                            _still_blind = [
                                s for s in _missing_pos_syms if s not in _returns_df.columns
                            ]
                            if _still_blind:
                                log(
                                    f"  15M_CORR_GATE_BLIND: {_still_blind} 1d return "
                                    f"matrisinde yok — gate bu pozisyonlara kör"
                                )
                        _ticker = _ex_submit.fetch_ticker(sig["symbol"])
                        _cur_px = float(_ticker["last"])
                        _signal_obj = build_signal_from_scan(sig, venue="binance", timeframe="15m")
                        _decision = _risk_officer.evaluate(
                            _signal_obj,
                            _account,
                            market_price=_cur_px,
                            returns_df=_returns_df,
                        )

                        if not hasattr(_decision, "quantity"):
                            log(
                                f"  15M_REJECT_RISK: {sig['symbol']} {sig.get('strategy', '')} "
                                f"reason={getattr(_decision, 'reason', 'unknown')}"
                            )
                        else:
                            _qty = float(_decision.quantity)
                            _notional = float(_decision.notional_usdt)
                            # Kaldıraç hiyerarşisi (T2-02, 2026-07-10): TEK KAYNAK =
                            # RiskOfficer kararı (yaml leverage.max_leverage_per_symbol
                            # üzerinden); _LEV_HARD_CAP = mutlak son-savunma tavanı
                            # (yaml ne derse desin aşılamaz). yaml>cap ise startup'ta
                            # LEV_CAP_MISMATCH uyarısı düşer.
                            _lev = max(1, min(_LEV_HARD_CAP, round(_decision.leverage))) or 1
                            _margin = _notional / _lev if _lev > 0 else _notional

                            if _margin > _state_submit["available_balance"] * 0.9:
                                log(f"  15M_SKIP_MARGIN: {sig['symbol']} need=${_margin:.2f}")
                            else:
                                setup_leverage(_ex_submit, sig["symbol"], _lev)
                                _order_side = "buy" if sig["side"] == "long" else "sell"

                                # G20: Deterministik fingerprint → idempotency guard
                                # Sinyal parmak izi: symbol + side + strategy + bar_close_ts
                                # Format: PA_{fp[:16]} (Binance max 36 char → 19 char, güvenli)
                                import hashlib as _hashlib

                                _fp_src = (
                                    f"{sig['symbol']}|{sig.get('side', '')}|"
                                    f"{sig.get('strategy', '')}|"
                                    f"{sig.get('bar_close_ts') or sig.get('ts', '')!s}"
                                )
                                _fp = _hashlib.sha256(_fp_src.encode()).hexdigest()[:16]
                                _coid = f"PA_{_fp}"  # max 19 char (< 36 limit)

                                from price_action.execution.idempotency import (
                                    IdempotencyStore as _IdemStore,
                                )

                                _idem = _IdemStore(db_path=IDEMPOTENCY_DB)
                                if _idem.is_seen(_fp):
                                    log(
                                        f"  15M_IDEM_SKIP: {sig['symbol']} {sig.get('strategy', '')} "
                                        f"fp={_fp} — zaten gönderildi (restart/duplicate scan)"
                                    )
                                    continue

                                # FIX 2026-06-10 (v14 audit MAJOR-2): borsa minQty/stepSize/
                                # minNotional ön-kontrolü. 19-sembol evreninde (ALGO/XLM gibi
                                # düşük fiyatlılar) precision yuvarlaması sonrası qty minQty
                                # altına düşebilir veya MIN_NOTIONAL (-4164) reddi gelir —
                                # önceden bu genel 15M_ENTRY_ERR'e düşüp sinyal sessizce
                                # kayboluyordu. Şimdi temiz reject + idempotency'e YAZILMAZ.
                                try:
                                    _mkt = _ex_submit.market(sig["symbol"])
                                    _lim = _mkt.get("limits", {}) or {}
                                    _min_amt = float((_lim.get("amount", {}) or {}).get("min") or 0)
                                    _min_cost = float((_lim.get("cost", {}) or {}).get("min") or 0)
                                    _qty_prec = float(
                                        _ex_submit.amount_to_precision(sig["symbol"], _qty)
                                    )
                                    _notional_prec = _qty_prec * float(_cur_px or 0)
                                    if (
                                        _qty_prec <= 0
                                        or (_min_amt and _qty_prec < _min_amt)
                                        or (_min_cost and _notional_prec < _min_cost)
                                    ):
                                        log(
                                            f"  15M_BELOW_EXCHANGE_MIN: {sig['symbol']} "
                                            f"qty={_qty_prec} notional={_notional_prec:.2f} "
                                            f"(minQty={_min_amt}, minNotional={_min_cost}) — reject"
                                        )
                                        continue
                                    _qty = _qty_prec
                                except Exception as _lim_err:
                                    log(
                                        f"  15M_EXCHANGE_MIN_CHECK_ERR: "
                                        f"{str(_lim_err)[:80]} — kontrol atlandı (fail-open)"
                                    )

                                (
                                    _pre_submit_position_qty,
                                    _pre_submit_position_entry_price,
                                ) = _entry_position_baseline(_state_submit, sig["symbol"])

                                # First-entry write-ahead intent.  This fsync happens before
                                # both post-only and market HTTP submits.  A restart can
                                # reconcile the exact deterministic COID; if the WAL cannot
                                # be written, sending an entry is forbidden.
                                _pending_path = DATA_DIR / "pending_retries.jsonl"
                                _existing_work, _existing_work_err = _read_pending_retry_entries()
                                if _existing_work_err:
                                    log(
                                        f"  15M_ENTRY_WAL_READ_FAIL_CLOSED: "
                                        f"{sig['symbol']} {_existing_work_err}"
                                    )
                                    continue
                                if any(
                                    str(item.get("client_order_id") or item.get("work_id") or "")
                                    == _coid
                                    for item in _existing_work
                                ):
                                    log(
                                        f"  15M_ENTRY_WAL_SKIP: {sig['symbol']} coid={_coid} "
                                        "— durable work already owns this signal"
                                    )
                                    continue

                                _entry_journal_signal_id = _uuid.uuid5(
                                    _uuid.NAMESPACE_URL, f"15m-signal|{_coid}"
                                ).hex[:16]
                                _entry_journal_protection_id = _uuid.uuid5(
                                    _uuid.NAMESPACE_URL, f"15m-protection|{_coid}"
                                ).hex[:16]
                                _entry_wal = _build_pending_retry_entry(
                                    sig,
                                    qty=_qty,
                                    entry_px=_cur_px,
                                    leverage=_lev,
                                    client_order_id=_coid,
                                    orig_error="EntrySubmitPrepared: no HTTP side effect yet",
                                    pre_submit_position_qty=_pre_submit_position_qty,
                                    pre_submit_position_entry_price=(
                                        _pre_submit_position_entry_price
                                    ),
                                )
                                _entry_wal.update(
                                    {
                                        "schema_version": 1,
                                        "work_type": "entry_submit_intent_v1",
                                        "signal_fingerprint": _fp,
                                        "entry_submit_allowed": True,
                                        "journal_signal_id": _entry_journal_signal_id,
                                        "journal_protection_id": (_entry_journal_protection_id),
                                        "direct_submit_lease_until": (
                                            datetime.now(UTC) + timedelta(seconds=90)
                                        ).isoformat(),
                                        "submit_uncertainty": {
                                            "stage": "initial_submit_prepared",
                                            "main_client_order_id": _coid,
                                            "fallback_client_order_id": None,
                                            "partial_order_id": None,
                                            "partial_qty": 0.0,
                                            "remaining_qty": _qty,
                                        },
                                        "uncertain_client_order_ids": [_coid],
                                    }
                                )
                                try:
                                    _entry_wal_line = _enqueue_pending_retry(
                                        _entry_wal, _pending_path
                                    )
                                except Exception as _entry_wal_exc:
                                    log(
                                        f"  15M_ENTRY_WAL_FAIL_CLOSED: {sig['symbol']} "
                                        f"{type(_entry_wal_exc).__name__}: "
                                        f"{str(_entry_wal_exc)[:120]} — order NOT sent"
                                    )
                                    continue
                                _idem.mark_submitted(_fp, symbol=sig["symbol"], side=_order_side)

                                # ── POST-ONLY ENTRY PATH (2026-05-21) ──────────────────────────
                                # Config-gated: post_only_limit_enabled (default False → backward-compat)
                                # 1d pattern (futures_trade_daily.py:331-343) birebir izlendi.
                                # Idempotency: _coid her iki yolda da geçilir.
                                # High-slippage fills keep ownership and continue into the
                                # same durable SL-first protection path as every other fill.
                                _15m_po_enabled = bool(
                                    _risk_cfg.get("execution", {}).get(
                                        "post_only_limit_enabled", False
                                    )
                                )
                                _15m_po_timeout = int(
                                    _risk_cfg.get("execution", {}).get(
                                        "post_only_fallback_seconds", 30
                                    )
                                )
                                _15m_slip_limit = float(
                                    _risk_cfg.get("execution", {}).get("slippage_limit_bps", 25.0)
                                )
                                _fill_method = "market_only"
                                try:
                                    if _15m_po_enabled:
                                        from price_action.execution.post_only_router import (
                                            place_post_only_with_fallback as _po_place,
                                        )

                                        _order, _fill_method = _po_place(
                                            _ex_submit,
                                            symbol=sig["symbol"],
                                            side=_order_side,
                                            qty=_qty,
                                            target_price=_cur_px,
                                            # maker kalibrasyonu: passive bid/ask ile
                                            # post-only cross etmesin (target_price
                                            # slippage baseline olarak kalır)
                                            best_bid=_ticker.get("bid"),
                                            best_ask=_ticker.get("ask"),
                                            fallback_after_sec=_15m_po_timeout,
                                            slippage_limit_bps=_15m_slip_limit,
                                            client_order_id=_coid,
                                        )
                                        log(
                                            f"  15M_PO_ENTRY: {sig['symbol']} method={_fill_method} "
                                            f"coid={_coid}"
                                        )
                                    else:
                                        _order = _ex_submit.create_market_order(
                                            sig["symbol"],
                                            _order_side,
                                            _qty,
                                            params={"newClientOrderId": _coid},
                                        )
                                        _fill_method = "market_only"
                                except Exception as _entry_exc:
                                    _exc_name = type(_entry_exc).__name__
                                    _err_str = str(_entry_exc)
                                    try:
                                        from price_action.execution.post_only_router import (
                                            OrderSubmissionUncertainError as _OrderSubmissionUncertainError,
                                        )
                                        from price_action.execution.post_only_router import (
                                            _is_definitive_submit_rejection,
                                        )

                                        _is_submit_uncertain = isinstance(
                                            _entry_exc, _OrderSubmissionUncertainError
                                        )
                                    except ImportError:
                                        _is_submit_uncertain = False
                                        _is_definitive_submit_rejection = lambda _exc: False
                                    _is_timeout = (
                                        "RequestTimeout" in _exc_name
                                        or "-1007" in _err_str
                                        or "timeout" in _err_str.lower()
                                        or "Timeout" in _err_str
                                    )

                                    # The pre-submit row already exists.  Persist additional
                                    # ACK/uncertainty facts on that exact row; never append a
                                    # second submit-capable copy after an ambiguous response.
                                    _entry_wal["orig_error"] = (
                                        f"{_exc_name}: {str(_entry_exc)[:200]}"
                                    )
                                    _entry_wal["direct_submit_lease_until"] = datetime.now(
                                        UTC
                                    ).isoformat()
                                    if hasattr(_entry_exc, "to_queue_fields"):
                                        _entry_wal.update(_entry_exc.to_queue_fields())
                                    else:
                                        _entry_wal["submit_uncertainty"]["stage"] = (
                                            "initial_submit_response_uncertain"
                                        )
                                        _entry_wal["submit_uncertainty"]["error_type"] = _exc_name
                                    try:
                                        _entry_wal_line = _replace_pending_retry(
                                            _entry_wal, _entry_wal_line, _pending_path
                                        )
                                    except Exception as _transition_exc:
                                        # The original pre-submit WAL remains durable and is
                                        # sufficient to reconcile main/fallback COIDs.
                                        log(
                                            f"  15M_ENTRY_WAL_TRANSITION_FAIL: "
                                            f"{sig['symbol']} {str(_transition_exc)[:120]}"
                                        )

                                    if "SlippageExceeded" in _exc_name:
                                        log(
                                            f"  15M_SLIP_EXCEEDED_RECONCILE: "
                                            f"{sig['symbol']} {_entry_exc} — durable WAL held"
                                        )
                                        continue
                                    if (
                                        _is_submit_uncertain
                                        or _is_timeout
                                        or not (_is_definitive_submit_rejection(_entry_exc))
                                    ):
                                        log(
                                            f"  15M_ENTRY_DEFERRED: {sig['symbol']} "
                                            f"coid={_coid} — existing WAL will reconcile async"
                                        )
                                        continue

                                    # Only an explicit exchange rejection can terminate the
                                    # entry.  Persist no-submit first: deletion is cleanup and
                                    # may race a processor rewrite/crash.
                                    try:
                                        _entry_wal_line = _transition_pending_retry_to_no_submit(
                                            _entry_wal,
                                            _entry_wal_line,
                                            path=_pending_path,
                                            reason="definitive_exchange_rejection",
                                            updates={
                                                "terminal_rejection": True,
                                                "terminal_rejection_type": _exc_name,
                                            },
                                        )
                                        _remove_pending_retry(_entry_wal_line, _pending_path)
                                    except Exception as _remove_exc:
                                        log(
                                            f"  15M_ENTRY_WAL_TERMINALIZE_FAIL: "
                                            f"{sig['symbol']} {str(_remove_exc)[:100]}"
                                        )
                                    log(
                                        f"  15M_ENTRY_ERR: {sig['symbol']} {_exc_name}: {str(_entry_exc)[:120]}"
                                    )
                                    try:
                                        _missed_path = DATA_DIR / "missed_signals.jsonl"
                                        _missed_path.parent.mkdir(parents=True, exist_ok=True)
                                        _missed_entry = {
                                            "ts": datetime.now(UTC).isoformat(),
                                            "tf": "15m",
                                            "symbol": sig["symbol"],
                                            "strategy": sig.get("strategy", ""),
                                            "side": sig["side"],
                                            "entry_px": _cur_px,
                                            "sl_px": sig.get("sl_price"),
                                            "error": f"{_exc_name}: {str(_entry_exc)[:200]}",
                                            "retried": False,
                                        }
                                        with open(_missed_path, "a", encoding="utf-8") as _mf:
                                            _mf.write(json.dumps(_missed_entry, default=str) + "\n")
                                    except Exception as _e:
                                        log(
                                            f"  MISSED_ENTRY_WRITE_FAIL: {str(_e)[:60]}"
                                        )  # log-only
                                    try:
                                        from price_action.orchestrator.notifications import (
                                            push_critical,
                                        )

                                        push_critical(
                                            f"15m ENTRY MISSED: {sig['symbol']} {sig['side']} "
                                            f"{sig.get('strategy', '')} — {_exc_name} "
                                            f"({str(_entry_exc)[:80]})",
                                            source="futures15m",
                                        )
                                    except Exception:
                                        pass
                                    _idem.mark_filled(_fp, "", 0.0, 0.0)
                                    continue  # bu sinyali atla, daemon devam et

                                # Entry truth sırası:
                                #   1) matching-engine userTrades (tüm mixed leg order id'leri),
                                #   2) router'ın explicit verified qty+price contract'i,
                                #   3) pre/post exchange-position delta.
                                # Hiçbiri yoksa intended qty/arrival price ASLA fill kanıtı olmaz.
                                _entry_symbol_id = (
                                    sig["symbol"].replace("/", "").replace(":USDT", "")
                                )
                                _entry_trade_exec = _entry_execution_from_user_trades(
                                    _ex_submit, _entry_symbol_id, _order
                                )
                                _entry_fee_usdt = _entry_trade_exec["fee_usdt"]
                                _entry_fee_source = _entry_trade_exec["fee_source"]
                                _entry_truth_source = ""
                                _fill_qty = 0.0
                                _avg_px = 0.0
                                _filled_notional = 0.0

                                if _entry_trade_exec["complete"]:
                                    _fill_qty = float(_entry_trade_exec["quantity"] or 0.0)
                                    _avg_px = float(_entry_trade_exec["price"] or 0.0)
                                    _filled_notional = float(
                                        _entry_trade_exec["notional_usdt"] or 0.0
                                    )
                                    _entry_truth_source = "exchange_user_trades"
                                elif (
                                    _order.get("fill_quantity_verified") is True
                                    and _order.get("fill_price_verified") is True
                                ):
                                    _fill_qty = float(_order.get("filled") or 0.0)
                                    _avg_px = float(_order.get("average") or 0.0)
                                    _filled_notional = float(
                                        _order.get("cost") or (_fill_qty * _avg_px)
                                    )
                                    _entry_truth_source = "router_verified"
                                else:
                                    try:
                                        _post_fill_state = fetch_futures_state(_ex_submit)
                                        _position_truth = _entry_position_delta_evidence(
                                            _state_submit,
                                            _post_fill_state,
                                            sig["symbol"],
                                            sig["side"],
                                        )
                                        if _position_truth["complete"]:
                                            _fill_qty = float(_position_truth["quantity"] or 0.0)
                                            _avg_px = float(_position_truth["price"] or 0.0)
                                            _filled_notional = float(
                                                _position_truth["notional_usdt"] or 0.0
                                            )
                                            _entry_truth_source = str(_position_truth["source"])
                                    except Exception as _pos_reconcile_err:
                                        record_degraded_read(
                                            "entry_submit.position_reconcile",
                                            _pos_reconcile_err,
                                            emit_log=False,
                                        )

                                if (
                                    not _entry_truth_source
                                    or _fill_qty <= 0
                                    or _avg_px <= 0
                                    or _filled_notional <= 0
                                ):
                                    log(
                                        f"  15M_FILL_UNVERIFIED_CRITICAL: {sig['symbol']} "
                                        f"order_ids={_entry_trade_exec['order_ids']} — "
                                        "intended qty journal/protection'a yazılmadı; "
                                        "owned-position reconcile tetiklendi"
                                    )
                                    try:
                                        from price_action.orchestrator.notifications import (
                                            push_critical,
                                        )

                                        push_critical(
                                            f"🚨 15m FILL UNVERIFIED — {sig['symbol']} "
                                            f"order_ids={_entry_trade_exec['order_ids']}. "
                                            "Journal/protection için sahte qty kullanılmadı; "
                                            "exchange position reconcile gerekiyor.",
                                            source="futures15m_fill_unverified",
                                        )
                                    except Exception:
                                        pass
                                    # Transition the pre-submit WAL to reconcile-only.  The
                                    # original row is replaced durably; a second submit-capable
                                    # queue copy is never appended.
                                    try:
                                        _known_fill_ids = _known_order_ids_from_ack(_order)
                                        for _known_fill_id in list(
                                            _entry_trade_exec.get("order_ids") or []
                                        ):
                                            if _known_fill_id not in _known_fill_ids:
                                                _known_fill_ids.append(_known_fill_id)
                                        _entry_wal.update(
                                            {
                                                "orig_error": (
                                                    "FillEvidenceUnverified: immediate submit "
                                                    "ACK received; exchange fill facts delayed"
                                                ),
                                                "known_order_ids": _known_fill_ids,
                                                "submitted_order_id": (
                                                    _known_fill_ids[0] if _known_fill_ids else None
                                                ),
                                                "reconcile_only": True,
                                                "entry_submit_allowed": False,
                                                "direct_submit_lease_until": (
                                                    datetime.now(UTC).isoformat()
                                                ),
                                                "terminal_no_fill_confirmations_required": 2,
                                            }
                                        )
                                        _entry_wal["submit_uncertainty"]["stage"] = (
                                            "immediate_submit_fill_unverified"
                                        )
                                        _entry_wal_line = _replace_pending_retry(
                                            _entry_wal,
                                            _entry_wal_line,
                                            _pending_path,
                                        )
                                        log(
                                            f"  15M_FILL_RECONCILE_QUEUED: {sig['symbol']} "
                                            f"order_ids={_known_fill_ids}"
                                        )
                                    except Exception as _fill_q_exc:
                                        log(
                                            f"  15M_FILL_RECONCILE_QUEUE_FAIL: {sig['symbol']} "
                                            f"{str(_fill_q_exc)[:120]}"
                                        )
                                    try:
                                        position_check()
                                    except Exception as _owned_reconcile_err:
                                        log(
                                            f"  15M_OWNED_RECONCILE_ERR: "
                                            f"{str(_owned_reconcile_err)[:100]}"
                                        )
                                    continue

                                _slip_realized_px = _avg_px
                                _filled_margin = _filled_notional / max(int(_lev or 1), 1)
                                _sig_id = _entry_journal_signal_id
                                _journal_prot_id = _entry_journal_protection_id
                                _entry_notional = _filled_notional
                                if _entry_trade_exec["complete"]:
                                    _entry_maker_qty = float(
                                        _entry_trade_exec["maker_quantity"] or 0.0
                                    )
                                    _entry_maker_notional = float(
                                        _entry_trade_exec["maker_notional_usdt"] or 0.0
                                    )
                                else:
                                    _method_is_maker = _fill_method.startswith("post_only_filled")
                                    _entry_maker_qty = float(
                                        _order.get("partial_limit_qty")
                                        or (_fill_qty if _method_is_maker else 0.0)
                                    )
                                    _entry_maker_notional = float(
                                        _order.get("partial_limit_notional")
                                        or (_entry_notional if _method_is_maker else 0.0)
                                    )
                                _entry_maker_qty = min(max(_entry_maker_qty, 0.0), _fill_qty)
                                _entry_maker_notional = min(
                                    max(_entry_maker_notional, 0.0), _entry_notional
                                )
                                _is_maker = _entry_maker_qty >= (
                                    _fill_qty - max(1e-9, _fill_qty * 1e-9)
                                )
                                _entry_order_type = (
                                    "limit"
                                    if _is_maker
                                    else (
                                        "mixed_limit_market" if _entry_maker_qty > 0 else "market"
                                    )
                                )
                                _entry_execution_evidence = {
                                    "schema_version": 1,
                                    "expected_price": float(_cur_px),
                                    "realized_price": float(_slip_realized_px),
                                    "quantity": float(_fill_qty),
                                    "notional_usdt": float(_filled_notional),
                                    "fee_usdt": (
                                        float(_entry_fee_usdt)
                                        if _entry_fee_usdt is not None
                                        else None
                                    ),
                                    "fee_source": str(_entry_fee_source),
                                    "is_maker": bool(_is_maker),
                                    "order_type": _entry_order_type,
                                    "maker_quantity": float(_entry_maker_qty),
                                    "maker_notional_usdt": float(_entry_maker_notional),
                                    "fill_method": str(_fill_method),
                                    "exchange_order_id": str(_order.get("id", "")),
                                    "order_ids": list(_entry_trade_exec.get("order_ids") or []),
                                }

                                # A verified exchange fill first transitions its original
                                # submit WAL to reconcile-only/no-submit.  Only then may the
                                # dedicated protection WAL or an SL/TP side effect happen.
                                # A crash at every boundary therefore leaves at least one
                                # durable owner that cannot create another entry.
                                _protection_plan = None
                                _protection_work = None
                                _protection_wal_persisted = False
                                _protection_wal_error = None
                                _entry_no_submit_persisted = False
                                try:
                                    _protection_plan = build_protection_plan(
                                        _ex_submit,
                                        symbol=sig["symbol"],
                                        side=sig["side"],
                                        qty=_fill_qty,
                                        tp_price=float(sig["tp_price"]),
                                        sl_price=float(sig["sl_price"]),
                                        entry_price=_avg_px,
                                        protection_key=_coid,
                                    )
                                    _protection_work = _build_protection_finalize_entry(
                                        sig,
                                        exchange=_ex_submit,
                                        client_order_id=_coid,
                                        order=_order,
                                        fill_method=_fill_method,
                                        entry_execution_evidence=(_entry_execution_evidence),
                                        fill_qty=_fill_qty,
                                        fill_price=_avg_px,
                                        fill_notional=_filled_notional,
                                        fill_source=_entry_truth_source,
                                        leverage=_lev,
                                        signal_id=_sig_id,
                                        protection_id=_journal_prot_id,
                                        protection_plan=_protection_plan,
                                        known_order_ids=list(
                                            _entry_trade_exec.get("order_ids") or []
                                        ),
                                    )
                                    _entry_wal_line = _transition_pending_retry_to_no_submit(
                                        _entry_wal,
                                        _entry_wal_line,
                                        path=_pending_path,
                                        reason="verified_fill_protection_handoff",
                                        updates={
                                            "known_order_ids": _known_order_ids_from_ack(_order),
                                            "submitted_order_id": str(_order.get("id") or ""),
                                            "last_verified_fill_qty": _fill_qty,
                                            "last_verified_fill_price": _avg_px,
                                            "last_verified_fill_notional": _filled_notional,
                                            "protection_plan": _protection_plan,
                                            "protection_binding_sha256": (
                                                _protection_work.get(
                                                    "protection_binding_sha256"
                                                )
                                            ),
                                            "entry_fill_method": _fill_method,
                                            "entry_execution_outcome": _order.get(
                                                "slippage_breach"
                                            ),
                                            "entry_execution_evidence": (
                                                _entry_execution_evidence
                                            ),
                                        },
                                    )
                                    _entry_no_submit_persisted = True
                                    (
                                        _prot,
                                        _protection_wal_persisted,
                                        _protection_wal_error,
                                    ) = _execute_protection_with_wal(_ex_submit, _protection_work)
                                except Exception as _plan_exc:
                                    _protection_wal_error = (
                                        f"plan_build:{type(_plan_exc).__name__}: "
                                        f"{str(_plan_exc)[:160]}"
                                    )
                                    if not _entry_no_submit_persisted:
                                        try:
                                            _entry_wal_line = (
                                                _transition_pending_retry_to_no_submit(
                                                    _entry_wal,
                                                    _entry_wal_line,
                                                    path=_pending_path,
                                                    reason="verified_fill_emergency_sl",
                                                    updates={
                                                        "known_order_ids": (
                                                            _known_order_ids_from_ack(_order)
                                                        ),
                                                        "submitted_order_id": str(
                                                            _order.get("id") or ""
                                                        ),
                                                        "last_verified_fill_qty": _fill_qty,
                                                        "last_verified_fill_price": _avg_px,
                                                        "last_verified_fill_notional": (
                                                            _filled_notional
                                                        ),
                                                        "entry_fill_method": _fill_method,
                                                        "entry_execution_outcome": _order.get(
                                                            "slippage_breach"
                                                        ),
                                                        "entry_execution_evidence": (
                                                            _entry_execution_evidence
                                                        ),
                                                    },
                                                )
                                            )
                                            _entry_no_submit_persisted = True
                                        except Exception as _no_submit_exc:
                                            _protection_wal_error += (
                                                "; no_submit_transition:"
                                                f"{type(_no_submit_exc).__name__}: "
                                                f"{str(_no_submit_exc)[:100]}"
                                            )
                                    _prot = ensure_original_level_sl(
                                        _ex_submit,
                                        symbol=sig["symbol"],
                                        side=sig["side"],
                                        qty=_fill_qty,
                                        sl_price=float(sig["sl_price"]),
                                        protection_key=_coid,
                                    )

                                # Once the dedicated finalize WAL is durable it owns replay,
                                # so remove the already-no-submit original intent.  If cleanup
                                # fails, the surviving row remains reconcile-only and harmless.
                                if _protection_wal_persisted:
                                    try:
                                        _remove_pending_retry(_entry_wal_line, _pending_path)
                                    except Exception as _entry_remove_exc:
                                        log(
                                            f"  15M_ENTRY_WAL_HANDOFF_REMOVE_FAIL: "
                                            f"{sig['symbol']} "
                                            f"{str(_entry_remove_exc)[:120]}"
                                        )
                                if not _protection_wal_persisted:
                                    log(
                                        f"  15M_PROTECTION_WAL_CRITICAL: {sig['symbol']} "
                                        f"{_protection_wal_error}; emergency_sl="
                                        f"{_prot.get('status')}"
                                    )
                                    try:
                                        from price_action.orchestrator.notifications import (
                                            push_critical,
                                        )

                                        push_critical(
                                            f"🚨 15m PROTECTION WAL FAILED — {sig['symbol']} "
                                            f"coid={_coid}; only deterministic emergency SL "
                                            f"was attempted ({_prot.get('status')}).",
                                            source="futures15m_protection_wal",
                                        )
                                    except Exception:
                                        pass
                                _idem.mark_filled(
                                    _fp, str(_order.get("id", "")), _avg_px, _fill_qty
                                )

                                log(
                                    f"  15M_FILL: [{sig['side'].upper()}] {sig['symbol']} "
                                    f"{sig.get('strategy', '')} qty={_fill_qty:.4f} "
                                    f"px=${_avg_px:.4f} lev={_lev}x id={_order.get('id', '?')} "
                                    f"coid={_coid} method={_fill_method}"
                                )

                                # FIX 2026-05-26 (Faz 14.5): Telegram position-open bildirimi
                                try:
                                    from price_action.orchestrator.notifications import (
                                        notify_position_open,
                                    )

                                    _entry_notional_telegram = _fill_qty * _avg_px
                                    _margin_telegram = _entry_notional_telegram / max(
                                        int(_lev or 1), 1
                                    )
                                    notify_position_open(
                                        bot="futures15m",
                                        symbol=sig["symbol"],
                                        side=sig["side"],
                                        strategy=sig.get("strategy", ""),
                                        entry_price=_avg_px,
                                        qty=_fill_qty,
                                        notional_usdt=_entry_notional_telegram,
                                        margin_usdt=_margin_telegram,
                                        leverage=int(_lev or 1),
                                        sl_price=sig.get("sl_price"),
                                        tp_price=sig.get("tp_price"),
                                    )
                                except Exception as _notify_exc:
                                    log(f"  TELEGRAM_OPEN_FAIL: {_notify_exc}")

                                # G14: Entry fill slippage kaydı — maker/taker fee method'a göre
                                try:
                                    from price_action.execution.slippage_tracker import (
                                        SlippageTracker as _ST,
                                    )

                                    _st = _ST()
                                    _st.record_fill(
                                        fill_id=f"entry_{_sig_id}",
                                        ts=datetime.now(UTC),
                                        symbol=sig["symbol"],
                                        strategy=sig.get("strategy", ""),
                                        side=sig["side"],
                                        expected_price=_cur_px,
                                        realized_price=_slip_realized_px,
                                        quantity=_fill_qty,
                                        # userTrades eksikse tahmin YOK: NULL/unavailable.
                                        fee_usdt=_entry_fee_usdt,
                                        is_maker=_is_maker,
                                        order_type=_entry_order_type,
                                        mode=os.environ.get("PA_RUN_MODE", "paper"),
                                        exchange_order_id=str(_order.get("id", "")),
                                        client_order_id=_coid,
                                        fill_type="entry",
                                        fill_role="entry",
                                        fee_source=_entry_fee_source,
                                        maker_quantity=_entry_maker_qty,
                                        maker_notional_usdt=_entry_maker_notional,
                                        notes=(
                                            f"truth_source={_entry_truth_source} "
                                            f"order_ids={','.join(_entry_trade_exec['order_ids'])}"
                                        ),
                                        tf="15m",
                                    )
                                except Exception as _st_err:
                                    log(f"    15M_SLIP_ENTRY_ERR: {str(_st_err)[:100]}")

                                # A2: futures_signals INSERT (1d daemon parity) — prot_check + TradeJournal akışı
                                # bu kayıtlar olmadan tetiklenemiyordu (Signal Chief + Analyst convergence).
                                try:
                                    _jcon = duckdb.connect(str(JOURNAL))
                                    try:
                                        _jcon.execute(
                                            """
                                            INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """,
                                            (
                                                _sig_id,
                                                _utc_naive_timestamp(
                                                    sig.get("bar_close_ts") or sig.get("ts")
                                                ),
                                                sig["symbol"],
                                                sig.get("strategy", ""),
                                                sig["side"],
                                                float(sig["sl_price"]),
                                                float(sig["tp_price"]),
                                                float(sig.get("confluence", 0.0)),
                                                _lev,
                                                "filled",
                                                str(_order.get("id", "")),
                                                _avg_px,
                                                _fill_qty,
                                                _filled_notional,
                                                _filled_margin,
                                                (
                                                    f"protection_wal="
                                                    f"{_protection_wal_persisted} "
                                                    f"protection_key="
                                                    f"{(_protection_plan or {}).get('protection_key', '')} "
                                                    f"plan_sha256="
                                                    f"{(_protection_plan or {}).get('plan_sha256', '')}"
                                                ),
                                            ),
                                        )
                                        _jcon.commit()
                                    finally:
                                        _jcon.close()
                                except Exception as _je_sig:
                                    log(f"    15M_JOURNAL_SIG_ERR: {str(_je_sig)[:120]}")

                                # FIX 2026-06-05: orijinal SL'i stabil sakla → watchdog
                                # trailing'i hareketli SL yerine bunu kullanır (XRP +$64→$0 fix).
                                try:
                                    _ORIG_INTENDED_SL[
                                        f"{sig['symbol'].replace('/', '').replace(':USDT', '')}"
                                        f"|{str(sig['side']).lower()}"
                                    ] = float(sig["sl_price"])
                                except Exception as _e:
                                    # log-only: store başarısızsa watchdog G22 fallback'i devrede
                                    log(
                                        f"    ORIG_SL_STORE_FAIL {sig.get('symbol', '?')}: {str(_e)[:60]}"
                                    )
                                if _prot["status"] == "placed":
                                    log(
                                        f"    15M_PROTECT: tp=${_prot['tp_price']:.4f} sl=${_prot['sl_price']:.4f}"
                                    )
                                    # A2: futures_protection_orders INSERT (1d parity)
                                    try:
                                        _jcon = duckdb.connect(str(JOURNAL))
                                        try:
                                            _prot_id = _journal_prot_id
                                            _notes = (
                                                f"protection_key={_prot.get('protection_key', '')} "
                                                f"plan_sha256={_prot.get('plan_sha256', '')} "
                                                f"client_order_ids="
                                                f"{json.dumps(_prot.get('client_order_ids', {}), sort_keys=True)}"
                                            )
                                            if _prot.get("mode") == "multi_target":
                                                _notes += f" mode=multi_target tp2={_prot.get('tp2_price', 0):.4f} tp2_id={_prot.get('tp2_order_id', '')}"
                                            _jcon.execute(
                                                """
                                                INSERT INTO futures_protection_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                            """,
                                                (
                                                    _prot_id,
                                                    _utc_naive_timestamp(datetime.now(UTC)),
                                                    _sig_id,
                                                    sig["symbol"],
                                                    sig["side"],
                                                    _fill_qty,
                                                    _prot["tp_price"],
                                                    _prot["sl_price"],
                                                    _prot.get("tp_order_id"),
                                                    _prot.get("sl_order_id"),
                                                    "placed",
                                                    _notes,
                                                ),
                                            )
                                            _jcon.commit()
                                        finally:
                                            _jcon.close()
                                    except Exception as _je_prot:
                                        log(f"    15M_JOURNAL_PROT_ERR: {str(_je_prot)[:120]}")
                                else:
                                    log(f"    15M_PROTECT_ERR: {_prot.get('reason')}")

                                # P-04: PyramidPosition build + register (P-05 cleanup ready)
                                if _pyramid_router_15m is not None:
                                    try:
                                        from price_action.execution.pyramid_router import (
                                            build_position_from_signal,
                                        )

                                        _pyr_cfg = _risk_cfg.get("strategy_portfolio", {})
                                        _pyr_triggers = _pyr_cfg.get("pyramid_triggers", [])
                                        _pyr_sizes = _pyr_cfg.get("pyramid_sizes", [])
                                        if _pyr_triggers and _pyr_sizes:
                                            _pyr_pos = build_position_from_signal(
                                                signal_dict=sig,
                                                fill_price=_avg_px,
                                                fill_qty=_fill_qty,
                                                sl_price=float(sig["sl_price"]),
                                                parent_position_id=_sig_id,
                                                pyramid_triggers=list(_pyr_triggers),
                                                pyramid_sizes=list(_pyr_sizes),
                                            )
                                            _pyramid_positions[_sig_id] = _pyr_pos
                                            # Exchange'i router'a ilet (ilk fill sonrası)
                                            _pyramid_router_15m.exchange = _ex_submit
                                            log(
                                                f"    15M_PYRAMID_REGISTERED: pos_id={_sig_id} "
                                                f"triggers={_pyr_triggers}"
                                            )
                                            # SEC58-L2: DB persist
                                            try:
                                                _ps = _get_pyramid_store()
                                                if _ps is not None:
                                                    _ps.upsert_position(_pyr_pos)
                                            except Exception as _ps_err:
                                                log(f"    15M_PYRAMID_STORE_WRITE_ERR: {_ps_err}")
                                    except Exception as pyr_build_err:
                                        log(f"    15M_PYRAMID_BUILD_ERR: {pyr_build_err}")

                    except Exception as sub_err:
                        log(f"  15M_ORDER_ERR: {sig.get('symbol', '?')}: {str(sub_err)[:120]}")

                    order_elapsed = (datetime.now(UTC) - order_start).total_seconds()
                    if _metrics_ok:
                        try:
                            signal_to_order_latency_seconds.observe(order_elapsed)
                        except Exception as _m_err:
                            log(f"METRIC_EMIT_ERR: {str(_m_err)[:80]}")  # log-only

                # ------ POSITION MONITOR (pyramid hook + P-05 TP/SL pop) ------
                pos_monitor_start = datetime.now(UTC)
                _pos_check_state = None
                try:
                    # Bu state aynı barın breaker/equity kanıtında yeniden
                    # kullanılır; ikinci bir account/positions/orders turu atılmaz.
                    _pos_check_state = position_check()

                    # P-04/P-05: PyramidRouter hook — aktif pyramid pozisyonları kontrol et
                    if _pyramid_router_15m is not None and _pyramid_positions:
                        try:
                            from scripts.futures_trade_daily import (
                                fetch_futures_state,
                            )

                            _ex_mon = _get_daemon_exchange()
                            # Restart-recovered pyramid pozisyonları için exchange set et
                            # (router exchange=None ile init edilir, yeni signal fill yoksa
                            # boş kalır → create_market_order'da NoneType crash).
                            if _pyramid_router_15m.exchange is None:
                                _pyramid_router_15m.exchange = _ex_mon
                            _state_mon = fetch_futures_state(_ex_mon)
                            if _state_mon.get("exchange_state_complete") is not True:
                                raise RuntimeError(
                                    "pyramid monitor exchange state UNKNOWN; mutation skipped"
                                )
                            _pyr_now = datetime.now(UTC)
                            # Aktif exchange pozisyonlarından mark price haritası
                            _mark_map: dict[str, float] = {}
                            for _ep in _state_mon.get("positions", []):
                                _sym_raw = _ep.get("symbol", "")
                                _sym_clean = _sym_raw.replace(":USDT", "").replace("/", "")
                                _mark_map[_sym_clean] = float(
                                    _ep.get("markPrice") or _ep.get("entryPrice") or 0
                                )

                            # P-05: exchange'de artık açık olmayan pozisyonları _pyramid_positions'dan çıkar
                            _active_ex_syms: set[str] = set()
                            for _ep in _state_mon.get("positions", []):
                                if abs(float(_ep.get("contracts", 0) or 0)) > 1e-6:
                                    _active_ex_syms.add(
                                        _ep.get("symbol", "").replace(":USDT", "").replace("/", "")
                                    )
                            _to_pop: list[str] = []
                            for _fp, _pyr_pos in list(_pyramid_positions.items()):
                                _pos_sym_clean = (
                                    getattr(_pyr_pos, "symbol", "")
                                    .replace("/", "")
                                    .replace(":USDT", "")
                                )
                                if _pos_sym_clean not in _active_ex_syms:
                                    _to_pop.append(_fp)
                                    log(
                                        f"  15M_PYRAMID_POP: {_fp} {_pos_sym_clean} TP/SL hit — removing"
                                    )
                            for _fp in _to_pop:
                                _pyramid_positions.pop(_fp, None)
                                # SEC58-L2: DB'den de sil
                                try:
                                    _ps = _get_pyramid_store()
                                    if _ps is not None:
                                        _ps.delete_position(_fp)
                                except Exception as _ps_del_err:
                                    log(f"  15M_PYRAMID_STORE_DEL_ERR: {_fp}: {_ps_del_err}")

                            # Kalan aktif pyramid pozisyonlarını router'a ilet
                            for _fp, _pyr_pos in list(_pyramid_positions.items()):
                                _sym_clean = (
                                    getattr(_pyr_pos, "symbol", "")
                                    .replace("/", "")
                                    .replace(":USDT", "")
                                )
                                _mark = _mark_map.get(_sym_clean, 0.0)
                                if _mark > 0:
                                    try:
                                        _pyramid_router_15m.on_position_check(
                                            _pyr_pos, _mark, _pyr_now
                                        )
                                    except Exception as _pyr_chk_err:
                                        log(
                                            f"  15M_PYRAMID_CHECK_ERR pos={_fp}: {str(_pyr_chk_err)[:100]}"
                                        )
                        except Exception as pyr_mon_err:
                            log(f"  15M_PYRAMID_MONITOR_ERR: {str(pyr_mon_err)[:120]}")
                except Exception as pm_err:
                    log(f"  15M_POS_MONITOR_ERR: {pm_err}")

                pos_monitor_elapsed = (datetime.now(UTC) - pos_monitor_start).total_seconds()
                if _metrics_ok:
                    try:
                        position_monitor_duration_seconds.observe(pos_monitor_elapsed)
                    except Exception:
                        pass

                # ------ G19: DDBreaker standalone tick (bar-close, sinyal-bağımsız) ------
                # Breaker sadece evaluate() sırasında güncelleniyordu → sinyal gelmediğinde
                # (düşük volatilite saatleri) DD breaker sessizce geç tetikleniyordu.
                # Çözüm: her bar-close'da hesap durumunu breaker'a bildir.
                try:
                    from scripts.futures_trade_daily import (
                        fetch_futures_state,
                    )
                    from scripts.lib.risk_integration import (
                        build_futures_account_state,
                        load_risk_officer,
                    )

                    _g19_risk_yaml = _risk_config_15m()
                    # FIX 2026-06-10 (BLOCKER-2): bot-bazlı breaker state
                    _g19_state_path = BREAKER_STATE_15M
                    _g19_ro = load_risk_officer(
                        yaml_path=_g19_risk_yaml,
                        breaker_state_path=_g19_state_path,
                    )
                    if _pos_check_state is not None:
                        _g19_state = _pos_check_state
                    else:
                        _g19_ex = _get_daemon_exchange()
                        _g19_state = fetch_futures_state(_g19_ex)
                    if _g19_state.get("exchange_state_complete") is not True:
                        log(
                            "15M_BREAKER_TICK_SKIP_UNKNOWN: exchange state incomplete; "
                            "breaker/equity mutation atlandı"
                        )
                        raise RuntimeError("G19 exchange state UNKNOWN")
                    _g19_acct = build_futures_account_state(_g19_state, journal_path=JOURNAL)
                    _g19_snap = _g19_ro.breaker.update_from_account(_g19_acct)
                    if any(_g19_snap.values()):
                        log(f"15M_BREAKER_TICK: triggered={_g19_snap}")
                    # Aynı G19 API sonucunu ayrıca equity kanıtı olarak yaz; yeni
                    # borsa çağrısı yok. Bar-boundary ID aynı bar retry/restart'ında
                    # duplicate üretmez. Snapshot hatası breaker akışını bloklamaz.
                    try:
                        _g19_snapshot_id = (
                            f"{_BOT_NAME or 'default'}_15m_"
                            f"{current_boundary.strftime('%Y%m%dT%H%MZ')}"
                        )
                        _write_equity_snapshot(
                            _g19_state,
                            snapshot_id=_g19_snapshot_id,
                            snapshot_ts=current_boundary,
                            notes="15m_bar_g19",
                        )
                        log(
                            f"15M_EQUITY_SNAPSHOT: id={_g19_snapshot_id} "
                            f"wallet=${float(_g19_state['wallet_balance']):.2f}"
                        )
                    except Exception as _g19_snap_err:
                        log(f"15M_EQUITY_SNAPSHOT_ERR: {str(_g19_snap_err)[:120]}")
                except Exception as _g19_err:
                    log(f"15M_BREAKER_TICK_ERR: {str(_g19_err)[:120]}")

                # ------ DMS HEARTBEAT ------
                if dms_15m is not None:
                    try:
                        _dms_equity = 0.0
                        _dms_positions = 0
                        if isinstance(_pos_check_state, dict):
                            _dms_equity = float(
                                _pos_check_state.get("margin_balance")
                                or _pos_check_state.get("wallet_balance")
                                or 0.0
                            )
                            _dms_positions = int(_pos_check_state.get("n_positions") or 0)
                        dms_15m.ping(
                            equity_usdt=_dms_equity,
                            n_open_positions=_dms_positions,
                        )
                    except Exception as _e:
                        log(f"DMS_15M_PING_FAIL: {_e}")  # log-only: akış değişmez

                # Evidence-only: CCXT'nin son response header snapshot'ı.
                # Yalnız rate-limit whitelist'i loglanır; header yok/bozuksa
                # UNKNOWN. Bu telemetri karar veya request akışını değiştirmez.
                log(_rate_budget_log_line(_DAEMON_PRIVATE_EXCHANGE))
                log(
                    f"15M_TICK_DONE: scan={scan_elapsed:.1f}s pos_monitor={pos_monitor_elapsed:.1f}s"
                )
                # FIX 2026-05-28 (audit-A1): tick başarılı, backoff sayacını sıfırla.
                _err_count = 0

            except KeyboardInterrupt:
                raise
            except Exception as loop_err:
                # FIX 2026-05-28 (audit-A1): traceback ekle + exponential backoff +
                # abort threshold. Önceden hata sadece tek satır log'lanıp anında
                # devam ediyordu → kalıcı hatada CPU spin ve log spam riski.
                _err_count += 1
                _tb_snippet = _traceback.format_exc()
                log(f"15M_LOOP_ERROR #{_err_count}: {type(loop_err).__name__}: {loop_err}")
                # traceback'i kısalt (log dosyasını şişirmemek için ilk 600 char)
                for _tb_line in _tb_snippet.splitlines()[-12:]:
                    log(f"  TB: {_tb_line[:180]}")
                if _err_count >= _ERR_ABORT_THRESHOLD:
                    log(
                        f"15M_ABORT: {_err_count} ardışık hata → daemon exit "
                        f"(launchd KeepAlive restart eder)"
                    )
                    break
                _backoff = min(2 * (2 ** (_err_count - 1)), 60)
                log(f"15M_BACKOFF: {_backoff}s bekleyip devam (ardışık hata={_err_count})")
                time.sleep(_backoff)

            if once:
                log("15M_ONCE: tek seferlik mod, çıkılıyor")
                break

    except KeyboardInterrupt:
        log("15M_DAEMON STOPPED (Ctrl+C)")
    finally:
        if dms_15m is not None:
            try:
                dms_15m.stop()
            except Exception as _ds_err:
                log(f"15M_DMS_STOP_ERR: {str(_ds_err)[:120]}")  # log-only
        _DAEMON_PRIVATE_EXCHANGE = None


def signal_scan_if_new_day(now: datetime | None = None):
    """Retire the unsafe legacy 1d submit loop without a minute error storm."""
    global _last_signal_scan_date
    now = now or datetime.now(UTC)
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    today = now.date()
    if _last_signal_scan_date == today:
        return
    if now.hour == 0 and now.minute < 10:
        return
    # futures_trade_daily.daily_run(non-dry) is intentionally fail-closed because
    # it has no crash-complete entry/protection WAL. Calling it here every minute
    # could only raise forever; the supported live scanner is run_15m_mode.
    _last_signal_scan_date = today
    _save_last_scan_date(today)
    log(
        f"DAILY_SCAN_RETIRED: {today} legacy 1d execution disabled; "
        "scan/order/network I/O yapılmadı (use 15m mode)"
    )


def main_loop():
    # FIX 2026-05-28 (audit-Y9): 1d daemon mode'u için signal handler — 5m/15m
    # ile aynı pattern. SIGTERM/SIGHUP'ta graceful exit, sessiz ölüm yok.
    _install_signal_handlers()

    # SEC58-L2: startup recovery — pyramid pozisyonlarını DB'den yükle
    _pyramid_store_load_on_startup()

    # FIX 2026-05-31 (Faz restart-rebuild): borsadaki açık pozisyonlar için
    # takip kaydını yeniden kur (1d daemon için de aynı rebuild mantığı).
    try:
        from scripts.futures_trade_daily import get_futures_exchange as _get_fx_rb1d

        _rb_exchange_1d = _get_fx_rb1d()
        _rebuild_position_tracking_from_exchange(_rb_exchange_1d)
    except Exception as _rb_err_1d:
        log(f"REBUILD_TRACKING_INIT_ERR_1D: {_rb_err_1d} — G22 fallback devam")

    log("=" * 60)
    log("FUTURES DAEMON STARTED (USDM Futures Testnet)")
    log("  - Position check: every 60 seconds")
    log("  - Equity snapshot: every 5 minutes")
    log("  - Signal scan: günde 1 kez (yeni 1d bar)")
    log("  - Dead Man's Switch: 5dk heartbeat kesilirse emergency flatten")
    log("  LONG + SHORT ikisi de calisir, leverage 3x, TP/SL otomatik")
    log("  Dashboard: http://localhost:8501")
    log("=" * 60)

    last_pos_check = 0
    last_equity_snap = 0
    last_signal_check = 0
    last_slippage_summary = 0

    # Dead Man's Switch başlat
    try:
        from scripts.futures_trade_daily import get_futures_exchange

        _ex_for_dms = get_futures_exchange()
        _init_dead_mans_switch(_ex_for_dms)
    except Exception as e:
        # FAIL-CLOSED (2026-07-10): DMS'siz koşma yok — 15m/1d yollarıyla tutarlı.
        log(f"DMS_INIT_FATAL: {e} — DMS'siz koşmak reddedildi (fail-closed)")
        raise SystemExit(f"DMS_INIT_FATAL: {e}") from e

    try:
        while True:
            # FIX 2026-05-28 (audit-Y9): _stop_flag check (graceful shutdown).
            if _stop_flag:
                log("STOP_FLAG aktif — graceful exit (signal handler)")
                break

            # Kill-switch (her tick = 5sn — acil durdurma kapısı)
            halted, reason = _kill_switch_active()
            if halted:
                log(f"KILL_SWITCH ACTIVE — daemon exiting. Reason: {reason}")
                break
            now = time.time()
            try:
                if now - last_signal_check >= 60:
                    signal_scan_if_new_day()
                    last_signal_check = now
                if now - last_pos_check >= 60:
                    position_check()
                    last_pos_check = now
                if now - last_equity_snap >= 300:
                    equity_snapshot()
                    last_equity_snap = now
                # Günlük slippage özeti (her 6 saatte bir kontrol)
                if now - last_slippage_summary >= 21600:
                    try:
                        from price_action.execution.slippage_tracker import SlippageTracker

                        summary = SlippageTracker().daily_summary()
                        log(
                            f"SLIPPAGE_SUMMARY: n={summary['n_fills']} "
                            f"avg={summary['avg_slippage_bps']:.1f}bps "
                            f"max={summary['max_slippage_bps']:.1f}bps "
                            f"maker={summary['maker_fill_pct']:.0f}% "
                            f"alarm={summary['alarm_level']}"
                        )
                        last_slippage_summary = now
                    except Exception as slip_err:
                        log(f"SLIPPAGE_SUMMARY_ERR: {slip_err}")
                time.sleep(5)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                log(f"LOOP ERROR: {e}")
                time.sleep(30)
    except KeyboardInterrupt:
        log("DAEMON STOPPED (Ctrl+C)")
    finally:
        # Dead Man's Switch'i kapat
        global _dms
        if _dms is not None:
            try:
                _dms.stop()
            except Exception as _ds_err:
                log(f"DMS_STOP_ERR: {str(_ds_err)[:120]}")  # log-only


# =============================================================================
# Faz 5 — 5m P1c daemon mode (paper-only, P1c walker delege)
# =============================================================================


def run_5m_mode(once: bool = False) -> None:
    """5 dakikalık intraday daemon — P1c walker paper-deploy.

    Tasarım: 15m'in MİNİMAL kopyası değil — temiz P1c-spesifik loop:
    - Bar timing: UTC :00/:05/.../:55 + 5s buffer
    - Signal scan: vsa_climax_test only (config: drop_strategies)
    - WIDESTOP filter: sl_pct >= 0.030
    - P1c walker delege: monthly halt + 3-loss + rolling DD + vol_z sizing
    - Journal: data/futures_journal_5m.duckdb (15m'den AYRI PnL)
    - Log: logs/futures_daemon_5m.log
    - DMS: service_name=futures_daemon_5m (15m DMS'le ayrı)

    HARDLIMIT: paper-only (PA_RUN_MODE=paper); live için Principal sign-off.
    """
    log_5m = lambda msg: _log_5m(msg)

    # FIX 2026-05-28 (audit-Y9): A1 pattern 5m'e extend.
    # 15m'de sleep_until + signal handler eksikliği PID 17267'yi sessiz
    # öldürmüştü. 5m daemon henüz canlı değil ama aynı bug burada da var.
    # Şu an deploy edilmedi; aktif edilirse bu fix sayesinde sessiz ölüm yok.
    _install_signal_handlers()

    log_5m("============================================================")
    log_5m("FUTURES 5M P1C DAEMON STARTED")
    log_5m("  - Signal scan: her 5 dakikada (bar-close + 5s buffer)")
    log_5m("  - Strategy: vsa_climax_test (P1c W1 base)")
    log_5m("  - sl_pct_min: 0.030 (wide-stop)")
    log_5m("  - Walker: P1c (monthly halt + 3-loss + rolling 14d DD + vol_z)")
    log_5m("  - Journal: data/futures_journal_5m.duckdb (15m'den AYRI)")
    log_5m("============================================================")

    # FIX 2026-05-26 (Faz 14.1): Provenance banner
    try:
        from price_action.ops.provenance import config_provenance, format_banner

        _prov_5m = config_provenance(_risk_config_5m())
        for _line in format_banner(_prov_5m, component="FUTURES 5M P1C").splitlines():
            log_5m(_line)
    except Exception as _prov_exc:
        log_5m(f"PROVENANCE_BANNER_FAIL: {_prov_exc}")

    # P1c walker init
    p1c_walker = None
    try:
        from price_action.execution.p1c_walker import P1cWalker

        p1c_walker = P1cWalker(config_path=_risk_config_5m())
        log_5m(f"5M_P1C_WALKER: initialized (state={p1c_walker.state_summary()})")
    except Exception as e:
        log_5m(f"5M_P1C_WALKER_ERR: {e} — walker olmadan devam (sadece tarama)")

    # FIX 2026-05-28 (Faz 14.27): 5m bot DMS — kritik güvenlik.
    # Önceden 5m bot DMS başlatmıyordu — 5m bot eğer trade açıp donsa,
    # 30dk timeout flatten YOK = pozisyon açıkta kalır.
    # 5m TF için TF_DMS_PARAMS: heartbeat=10s, timeout=600s (10dk).
    dms_5m = None
    try:
        from price_action.execution.dead_mans_switch import DeadMansSwitch
        from scripts.futures_trade_daily import get_futures_exchange as _get_fx_dms_5m

        _dms_5m_ex = _get_fx_dms_5m()
        dms_5m = DeadMansSwitch(
            exchange=_dms_5m_ex,
            service_name="futures_daemon_5m",
            tf="5m",
            db_path=IDEMPOTENCY_DB,
        )
        dms_5m.start()
        log_5m("5M_DMS: başlatıldı (tf=5m, heartbeat=10s, timeout=600s, flatten AKTİF)")
    except Exception as e:
        log_5m(f"5M_DMS_INIT_ERROR: {e} — DMS devre dışı, devam ediyor (RİSK!)")

    # SL pct min config'den oku
    # FIX 2026-05-26 (H4): config load fail → SAFE DEFAULT 1.0 (tüm sinyaller red)
    # + push_critical alert. Önceden 0.030 fallback'i bot'u "açık" mod'da çalıştırıyordu.
    _sl_pct_min_5m = 0.030
    _cfg_load_ok_5m = False
    try:
        import yaml as _yaml

        with open(_risk_config_5m(), encoding="utf-8") as f:
            _cfg = _yaml.safe_load(f) or {}
        _sl_pct_min_5m = float(_cfg.get("execution", {}).get("sl_pct_min", 0.030))
        _cfg_load_ok_5m = True
        log_5m(f"5M_WIDESTOP: sl_pct_min={_sl_pct_min_5m:.4f}")
    except Exception as e:
        log_5m(f"5M_CONFIG_FAIL: {e} — SAFE DEFAULT sl_pct_min=1.0 (TÜM sinyaller red)")
        _sl_pct_min_5m = 1.0  # %100 — hiçbir sinyal geçemez
        try:
            from price_action.orchestrator.notifications import push_critical as _pc_h4_5m

            _pc_h4_5m(
                f"5m risk config LOAD FAIL — daemon SAFE MODE "
                f"(sl_pct_min=1.0). Path: {_risk_config_5m()} | Err: {str(e)[:120]}",
                source="futures5m_startup",
            )
        except Exception:
            pass

    last_bar_boundary = None
    log_5m("5M_DAEMON_RUN_START")
    # FIX 2026-05-28 (audit-Y9): 15m'dekiyle simetrik backoff counter.
    _err_count_5m = 0
    _ERR_ABORT_5M = 10

    try:
        while True:
            # FIX 2026-05-28 (audit-Y9): _stop_flag (SIGTERM/SIGHUP) check.
            if _stop_flag:
                log_5m("5M_STOP_FLAG aktif — graceful exit")
                break

            # Kill switch
            halted, reason = _kill_switch_active()
            if halted:
                log_5m(f"5M_KILL_SWITCH ACTIVE — daemon exiting. Reason: {reason}")
                break

            # FIX 2026-05-28 (audit-Y9): DMS thread health check (15m simetri).
            if dms_5m is not None:
                _hb5 = getattr(dms_5m, "_heartbeat_thread", None)
                _wd5 = getattr(dms_5m, "_watchdog_thread", None)
                if (_hb5 is not None and not _hb5.is_alive()) or (
                    _wd5 is not None and not _wd5.is_alive()
                ):
                    log_5m("5M_DMS_THREAD_DEAD: emergency shutdown (launchd restart eder)")
                    try:
                        from price_action.orchestrator.notifications import push_critical

                        push_critical("⚠️ 5m DMS thread ÖLDÜ — bot acil durduruluyor")
                    except Exception:
                        pass
                    break

            # Sonraki 5m bar kapanışı + 5s buffer
            next_close = next_5m_boundary() + timedelta(seconds=5)
            log_5m(f"5M_WAIT: sonraki bar kapanış {next_close.strftime('%H:%M:%S')} UTC")
            sleep_until(next_close)
            if _stop_flag:
                log_5m("5M_STOP_FLAG: uyku sonrası tespit — graceful exit")
                break

            current_boundary = next_close - timedelta(seconds=5)
            if last_bar_boundary is not None:
                bars_elapsed = int((current_boundary - last_bar_boundary).total_seconds() / 300)
                if bars_elapsed > 1:
                    log_5m(
                        f"5M_MISSED_BARS: {bars_elapsed - 1} bar kaçırıldı "
                        f"(son={last_bar_boundary.strftime('%H:%M')}, "
                        f"şimdi={current_boundary.strftime('%H:%M')})"
                    )
            last_bar_boundary = current_boundary

            # P1c walker halt check
            if p1c_walker is not None:
                halt_status = p1c_walker.check_halts()
                if halt_status.get("halted"):
                    log_5m(
                        f"5M_HALT_ACTIVE: {halt_status.get('reason')} "
                        f"(until={halt_status.get('release_at')})"
                    )
                    if once:
                        break
                    continue

            # Signal scan — vsa_climax_test only (P1c W1 base)
            scan_start = time.time()
            try:
                sigs = _scan_signals_5m(current_boundary)
            except Exception as e:
                log_5m(f"5M_SCAN_ERR: {e}")
                sigs = []

            scan_dur = time.time() - scan_start
            n_sig = len(sigs)
            log_5m(f"5M_SCAN: {n_sig} sinyal, latency={scan_dur:.1f}s")

            # WIDESTOP + P1c walker filter
            n_widestop = 0
            n_accept = 0
            for sig in sigs:
                sym = sig.get("symbol", "?")
                entry = float(sig.get("entry_price", 0))
                sl = float(sig.get("sl_price", 0))
                if entry > 0 and sl > 0:
                    sl_pct = abs(entry - sl) / entry
                    if sl_pct < _sl_pct_min_5m:
                        log_5m(
                            f"  5M_REJECT_WIDESTOP: {sym} sl_pct={sl_pct:.4f} < {_sl_pct_min_5m:.4f}"
                        )
                        n_widestop += 1
                        continue

                # P1c walker karar verir (sizing, halt re-check)
                if p1c_walker is not None:
                    decision = p1c_walker.evaluate_signal(sig)
                    if not decision.get("accept", False):
                        log_5m(f"  5M_REJECT_P1C: {sym} reason={decision.get('reason', '?')}")
                        continue

                n_accept += 1
                log_5m(
                    f"  5M_ACCEPT: {sym} sl_pct={sl_pct:.4f} risk_pct={decision.get('risk_pct', 0):.4f}"
                )

                # Faz 5.3: walker.record_open_position + paper journal entry
                if p1c_walker is not None:
                    try:
                        from datetime import datetime as _dt

                        position = {
                            "symbol": sym,
                            "side": sig.get("side", "?"),
                            "entry_price": entry,
                            "sl_price": sl,
                            "tp_price": float(sig.get("tp_price", 0)),
                            "strategy": sig.get("strategy", "?"),
                            "risk_pct": decision.get("risk_pct", 0),
                            "risk_usdt": decision.get("risk_usdt", 0),
                            "tier": decision.get("tier", "?"),
                            "vol_z": sig.get("vol_z", 0),
                            "entry_ts": _dt.now(UTC).isoformat(),
                        }
                        p1c_walker.record_open_position(position)
                        log_5m(
                            f"  5M_POSITION_OPENED: {sym} {sig.get('side')} risk=${decision.get('risk_usdt', 0):.2f} tier={decision.get('tier')}"
                        )

                        # Paper journal entry (futures_journal_5m.duckdb)
                        _write_5m_journal_signal(sig, decision)

                        # FIX 2026-05-26 (Faz 14.5): Telegram position-open bildirimi
                        try:
                            from price_action.orchestrator.notifications import notify_position_open

                            _qty = float(decision.get("qty", position.get("qty", 0.0)))
                            _notional = _qty * float(entry)
                            # 5m P1c walker margin = notional (1x leverage paper)
                            notify_position_open(
                                bot="futures5m",
                                symbol=sym,
                                side=sig.get("side", "?"),
                                strategy=sig.get("strategy", "?"),
                                entry_price=float(entry),
                                qty=_qty,
                                notional_usdt=_notional,
                                margin_usdt=_notional,  # 1x paper
                                leverage=1,
                                sl_price=float(sl),
                                tp_price=float(sig.get("tp_price", 0)) or None,
                            )
                        except Exception as _tn_exc:
                            log_5m(f"  TELEGRAM_OPEN_FAIL: {_tn_exc}")
                    except Exception as e:
                        log_5m(f"  5M_POSITION_RECORD_ERR: {e}")

                # NOTE: real ccxt order submit Faz 5.3.2 — şu an walker state + journal yeterli

            # Faz 5.3: Position monitor — BE-protect + close trigger
            if p1c_walker is not None:
                try:
                    n_be, n_closed = _monitor_5m_positions(p1c_walker)
                    if n_be > 0:
                        log_5m(f"5M_BE_PROTECTED: {n_be} pozisyon SL → entry")
                    if n_closed > 0:
                        log_5m(f"5M_POSITIONS_CLOSED: {n_closed}")
                except Exception as e:
                    log_5m(f"5M_POSITION_MONITOR_ERR: {e}")

            log_5m(f"5M_TICK_DONE: scan={scan_dur:.1f}s widestop={n_widestop} accept={n_accept}")
            # FIX 2026-05-28 (audit-Y9): tick başarılı → backoff sayacı sıfırla.
            _err_count_5m = 0

            if once:
                log_5m("5M_ONCE_DONE")
                break
    except KeyboardInterrupt:
        log_5m("5M_DAEMON STOPPED (Ctrl+C)")
    except Exception as e:
        # FIX 2026-05-28 (audit-Y9): fatal exception → backoff + retry, loop break ETME.
        # Önceki davranış: tek bir exception bot'u kalıcı kapatıyordu (sonra
        # launchd KeepAlive restart edebilirdi ama in-process recovery yoktu).
        _err_count_5m += 1
        log_5m(f"5M_LOOP_ERROR #{_err_count_5m}: {type(e).__name__}: {e}")
        import traceback as _tb

        for _l in _tb.format_exc().splitlines()[-12:]:
            log_5m(f"  TB: {_l[:180]}")
        if _err_count_5m >= _ERR_ABORT_5M:
            log_5m(f"5M_ABORT: {_err_count_5m} ardışık hata, daemon exit (launchd restart eder)")
        else:
            _bk = min(2 * (2 ** (_err_count_5m - 1)), 60)
            log_5m(f"5M_BACKOFF: {_bk}s — sonraki tick'te tekrar dene")
            time.sleep(_bk)
            # Not: bu basit pattern outer try sonrası bir kerelik fail için —
            # geniş retry-loop refactor sonraki turda. Şu an 5m daemon canlı değil.


def _log_5m(msg: str) -> None:
    """5m daemon log — ayrı dosya (futures_daemon_5m.log)."""
    # FIX 2026-05-28 (audit-D2): Z suffix — UTC olduğu net.
    ts = datetime.now(UTC).strftime("%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_path = LOGS_DIR / "futures_daemon_5m.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _monitor_5m_positions(walker) -> tuple[int, int]:
    """Faz 5.3: Open 5m positions için BE-protect + SL/TP hit kontrolü.

    Her bar sonunda:
    1. Open positions için ccxt'ten current price çek
    2. walker.check_be_protect() — peak_R >= 0.5 → SL → entry
    3. SL veya TP hit ise walker.close_position() çağır (paper journal)

    Returns: (n_be_triggered, n_closed)
    """
    n_be = 0
    n_closed = 0

    positions = walker._state.get("open_positions", {})
    if not positions:
        return (0, 0)

    # ccxt'ten current prices çek
    try:
        import ccxt

        ex = ccxt.binance(
            {
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
                "timeout": 10000,
            }
        )
        current_prices: dict[str, float] = {}
        for sym in positions.keys():
            try:
                ticker = ex.fetch_ticker(sym)
                current_prices[sym] = float(ticker.get("last", 0))
            except Exception:
                pass
    except Exception as e:
        _log_5m(f"5M_PRICE_FETCH_ERR: {e}")
        return (0, 0)

    # BE-protect
    be_triggered = walker.check_be_protect(current_prices)
    for be in be_triggered:
        n_be += 1
        _log_5m(
            f"  5M_BE: {be['symbol']} {be['side']} peak_R={be['peak_R']} "
            f"SL {be['old_sl']:.4f} → {be['new_sl']:.4f}"
        )

    # SL/TP hit check (paper close)
    for symbol, pos in list(positions.items()):
        current = current_prices.get(symbol)
        if current is None or current <= 0:
            continue

        side = pos.get("side", "")
        entry = float(pos.get("entry_price", 0))
        sl = float(pos.get("sl_price", 0))
        tp = float(pos.get("tp_price", 0))

        close_reason = None
        if side == "long":
            if sl > 0 and current <= sl:
                close_reason = "be_hit" if pos.get("be_protected") else "sl_hit"
            elif tp > 0 and current >= tp:
                close_reason = "tp_hit"
        elif side == "short":
            if sl > 0 and current >= sl:
                close_reason = "be_hit" if pos.get("be_protected") else "sl_hit"
            elif tp > 0 and current <= tp:
                close_reason = "tp_hit"

        if close_reason:
            outcome = walker.close_position(symbol, close_price=current, reason=close_reason)
            if outcome:
                n_closed += 1
                _log_5m(
                    f"  5M_CLOSE: {symbol} {side} reason={close_reason} "
                    f"price={current:.4f} pnl=${outcome['pnl_usdt']:+.2f} R={outcome['r_multiple']:+.2f}"
                )
                # Journal'a closed trade yaz
                _write_5m_journal_trade_close(outcome)
                # FIX 2026-05-26 (Faz 14.5): Telegram position-close bildirimi
                try:
                    from price_action.orchestrator.notifications import notify_position_close

                    _entry = float(outcome.get("entry_price", entry))
                    _exit = float(outcome.get("close_price", current))
                    _qty = float(outcome.get("qty", pos.get("qty", 0.0)))
                    _notional = _qty * _entry
                    _hold_s = None
                    if outcome.get("open_ts") and outcome.get("close_ts"):
                        try:
                            from datetime import datetime as _dt

                            _ot = _dt.fromisoformat(str(outcome["open_ts"]))
                            _ct = _dt.fromisoformat(str(outcome["close_ts"]))
                            _hold_s = (_ct - _ot).total_seconds()
                        except Exception:
                            pass
                    notify_position_close(
                        bot="futures5m",
                        symbol=symbol,
                        side=side,
                        strategy=str(pos.get("strategy", "")),
                        entry_price=_entry,
                        exit_price=_exit,
                        qty=_qty,
                        notional_usdt=_notional,
                        realized_pnl_usdt=float(outcome["pnl_usdt"]),
                        realized_r=float(outcome["r_multiple"]),
                        close_reason=close_reason,
                        hold_seconds=_hold_s,
                    )
                except Exception as _tn_exc:
                    _log_5m(f"  TELEGRAM_CLOSE_FAIL: {_tn_exc}")

    return (n_be, n_closed)


def _write_5m_journal_trade_close(outcome: dict) -> None:
    """Closed trade'i futures_journal_5m.duckdb'ye yaz."""
    try:
        import uuid

        import duckdb

        journal_path = DATA_DIR / "futures_journal_5m.duckdb"
        if not journal_path.exists():
            return

        con = duckdb.connect(str(journal_path))
        try:
            con.execute(
                """
                INSERT INTO futures_trades_closed
                (trade_id, ts_open, ts_close, sym, side, strategy,
                 entry_price, exit_price, qty, realized_pnl_usdt, realized_r,
                 win, close_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    str(uuid.uuid4()),
                    outcome.get("entry_ts", ""),
                    outcome["close_ts"],
                    outcome["symbol"],
                    outcome["side"],
                    outcome.get("strategy", "?"),
                    outcome["entry_price"],
                    outcome["close_price"],
                    0.0,  # qty placeholder (Faz 5.3.2 real submit'ta)
                    outcome["pnl_usdt"],
                    outcome["r_multiple"],
                    outcome["pnl_usdt"] > 0,
                    outcome["reason"],
                ),
            )
            con.commit()
        finally:
            con.close()
    except Exception as e:
        _log_5m(f"  5M_JOURNAL_CLOSE_ERR: {e}")


def _write_5m_journal_signal(sig: dict, decision: dict) -> None:
    """Faz 5.3: futures_journal_5m.duckdb'ye signal entry yaz.

    Mevcut 15m futures_journal'ın schema'sını kullanır — ayrı PnL track için.
    """
    try:
        import uuid

        import duckdb

        journal_path = DATA_DIR / "futures_journal_5m.duckdb"
        if not journal_path.exists():
            _log_5m(f"5M_JOURNAL_MISSING: {journal_path}")
            return

        con = duckdb.connect(str(journal_path))
        try:
            signal_id = str(uuid.uuid4())
            bar_close = sig.get("bar_close_ts") or sig.get("ts")
            if hasattr(bar_close, "to_pydatetime"):
                bar_close = bar_close.to_pydatetime()

            con.execute(
                """
                INSERT INTO futures_signals
                (signal_id, ts, symbol, strategy, side, sl_price, tp_price,
                 confluence, leverage, status, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    signal_id,
                    bar_close,
                    sig.get("symbol", "?"),
                    sig.get("strategy", "?"),
                    sig.get("side", "?"),
                    float(sig.get("sl_price", 0)),
                    float(sig.get("tp_price", 0)),
                    float(sig.get("confluence", 0)),
                    1,  # leverage placeholder
                    "ACCEPTED_PAPER",
                    f"tier={decision.get('tier', '?')} risk_pct={decision.get('risk_pct', 0):.4f} risk_usdt={decision.get('risk_usdt', 0):.2f} vol_z={sig.get('vol_z', 0):+.2f}",
                ),
            )
            con.commit()
        finally:
            con.close()
        _log_5m(f"  5M_JOURNAL_WRITE: {signal_id[:8]} → futures_journal_5m.duckdb")
    except Exception as e:
        _log_5m(f"  5M_JOURNAL_ERR: {e}")


def _scan_signals_5m(target_dt: datetime) -> list:
    """5m tarama: scripts.futures_trade_5m.scan_signals_5m delege.

    Faz 5.2 fix (2026-05-25): scripts/futures_trade_5m.py oluşturuldu,
    artık gerçek 5m signal pipeline çalışıyor. P1c W1 base: vsa_climax_test
    only (engulfing_continuation drop_strategies'de). vol_z signal dict'inde
    döner — P1c walker M3a sizing için.
    """
    try:
        from scripts.futures_trade_5m import scan_signals_5m

        return scan_signals_5m(target_dt)
    except Exception as e:
        _log_5m(f"5M_SCAN_IMPORT_ERR: {e}")
        import traceback

        _log_5m(traceback.format_exc()[:1500])
        return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Futures Daemon — 1d, 15m veya 5m intraday mode")
    parser.add_argument("--once", action="store_true", help="Tek seferlik test (1d mode için)")
    parser.add_argument(
        "--timeframe",
        choices=["1d", "15m", "5m"],
        default="1d",
        help="Daemon timeframe: '1d' (default), '15m' (intraday), '5m' (P1c)",
    )
    args = parser.parse_args()

    if args.timeframe == "15m":
        run_15m_mode(once=args.once)
    elif args.timeframe == "5m":
        run_5m_mode(once=args.once)
    elif args.once:
        equity_snapshot()
        position_check()
        signal_scan_if_new_day()
    else:
        main_loop()
