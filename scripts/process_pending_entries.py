"""Pending entry retry processor (Faz 13.1 — H6 deferred queue).

FIX 2026-05-26: Önceden futures_daemon entry timeout durumunda
time.sleep(30+60)=90s ile ana döngüyü bloke ediyordu. Yeni:
timeout sinyali data/pending_retries.jsonl'e yazıyor, daemon devam.
Bu script scheduler tarafından her 60s'de çağrılır, queue'yu işler.

Akış:
1. pending_retries.jsonl oku
2. Her giriş için:
   - max_age_seconds aşılmışsa: missed_signals.jsonl + push_critical, drop
   - attempts >= max_attempts: missed_signals.jsonl + push_critical, drop
   - Aksi: fresh ticker → slip kontrol → market order retry
     - Success: journal yaz, drop from queue
     - Fail: attempts++ , queue'ya geri yaz
3. Queue dosyasını yeniden yaz (atomic rename)

Single-shot mode: bir kez çalış, çık. Re-entry scheduler ile.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# PYTHONPATH
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_QUEUE_PATH = Path("data/pending_retries.jsonl")
_MISSED_PATH = Path("data/missed_signals.jsonl")


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _push_missed(entry: dict[str, Any], reason: str) -> None:
    """Audit + Telegram alert for permanently failed entry."""
    try:
        _MISSED_PATH.parent.mkdir(parents=True, exist_ok=True)
        missed = dict(entry)
        missed["dropped_reason"] = reason
        missed["dropped_at"] = datetime.now(timezone.utc).isoformat()
        with open(_MISSED_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(missed, default=str) + "\n")
    except Exception as exc:
        _log(f"missed_audit_fail: {exc}")
    try:
        from price_action.orchestrator.notifications import push_critical
        push_critical(
            f"15m ENTRY MISSED (queue): {entry.get('symbol')} {entry.get('side')} "
            f"{entry.get('strategy','')} — {reason} "
            f"(attempts={entry.get('attempts',0)})",
            source="pending_retry_processor",
        )
    except Exception as exc:
        _log(f"telegram_push_fail: {exc}")


def _atomic_rewrite(path: Path, lines: list[str]) -> None:
    """Atomic file rewrite to avoid corruption on crash."""
    if not lines:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False,
        dir=str(path.parent), prefix=".tmp_pending_", suffix=".jsonl",
    )
    try:
        tmp.write("".join(lines))
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, str(path))
    except Exception as exc:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        raise exc


def _try_retry(entry: dict[str, Any]) -> tuple[bool, dict[str, Any] | None, str]:
    """Tek bir entry için retry. Returns (success, order_dict, reason)."""
    try:
        import ccxt
    except Exception as exc:
        return False, None, f"ccxt_import_fail: {exc}"

    # Exchange instance — paper/testnet için PA_RUN_MODE'a göre seç
    try:
        from price_action.settings import get_settings
        s = get_settings()
        # Paper modda spot/testnet'e gitmeyiz, gerçek futures market'i kullan
        # (testnet hesaba zaten paper trades)
        ex_class = ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
            "apiKey": os.environ.get("PA_BINANCE_API_KEY", ""),
            "secret": os.environ.get("PA_BINANCE_SECRET", ""),
        })
        if s.pa_run_mode == "paper":
            ex_class.set_sandbox_mode(True)
    except Exception as exc:
        return False, None, f"exchange_init_fail: {exc}"

    # Fresh ticker
    try:
        ticker = ex_class.fetch_ticker(entry["symbol"])
        fresh_px = float(ticker.get("last") or entry["entry_px"])
    except Exception as exc:
        return False, None, f"ticker_fail: {exc}"

    # Slip kontrolü (%1)
    orig_px = float(entry["entry_px"])
    slip_pct = abs(fresh_px - orig_px) / orig_px * 100.0
    if slip_pct > 1.0:
        return False, None, f"slip_too_high: %{slip_pct:.2f} > %1.0"

    # Market order submit
    try:
        attempt = int(entry.get("attempts", 0)) + 1
        coid = f"{entry.get('client_order_id','')}-r{attempt}"
        order = ex_class.create_market_order(
            entry["symbol"],
            entry["side"],
            float(entry["qty"]),
            params={"newClientOrderId": coid},
        )
        return True, order, f"retry_attempt_{attempt}"
    except Exception as exc:
        return False, None, f"order_fail: {type(exc).__name__}: {str(exc)[:120]}"


def process_pending() -> dict[str, int]:
    """Main entry point. Returns stats dict."""
    stats = {"read": 0, "success": 0, "retry_again": 0, "dropped_age": 0, "dropped_attempts": 0}

    if not _QUEUE_PATH.exists():
        return stats

    try:
        raw_lines = _QUEUE_PATH.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        _log(f"queue_read_fail: {exc}")
        return stats

    now = datetime.now(timezone.utc)
    keep_lines: list[str] = []

    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except Exception:
            _log(f"queue_parse_fail: {raw[:100]}")
            continue
        stats["read"] += 1

        # Age check
        try:
            ts = datetime.fromisoformat(entry["ts"])
            age_s = (now - ts).total_seconds()
            max_age = float(entry.get("max_age_seconds", 120))
            if age_s > max_age:
                _log(f"DROPPED_AGE: {entry['symbol']} age={age_s:.0f}s > {max_age:.0f}s")
                _push_missed(entry, f"max_age_exceeded ({age_s:.0f}s > {max_age:.0f}s)")
                stats["dropped_age"] += 1
                continue
        except Exception as exc:
            _log(f"age_check_fail: {exc}")

        # Attempts check
        attempts = int(entry.get("attempts", 0))
        max_attempts = int(entry.get("max_attempts", 2))
        if attempts >= max_attempts:
            _log(f"DROPPED_ATTEMPTS: {entry['symbol']} attempts={attempts}")
            _push_missed(entry, f"max_attempts_reached ({attempts})")
            stats["dropped_attempts"] += 1
            continue

        # Try retry
        success, order, reason = _try_retry(entry)
        if success:
            _log(f"RETRY_SUCCESS: {entry['symbol']} {reason} order_id={order.get('id','?')}")
            stats["success"] += 1
            # NOT: journal yazma daemon'un işi (ayrı bir component).
            # Şimdilik order ID'yi missed_signals dosyasına audit olarak yaz
            # ki manuel reconcile yapılabilsin.
            try:
                _MISSED_PATH.parent.mkdir(parents=True, exist_ok=True)
                audit = dict(entry)
                audit["retry_resolved_at"] = datetime.now(timezone.utc).isoformat()
                audit["resolved_order_id"] = str(order.get("id", ""))
                audit["resolved_fill_price"] = float(order.get("average") or order.get("price") or 0.0)
                audit["status"] = "RESOLVED_BY_RETRY"
                # Aynı dosya — 'RESOLVED' status'lü kayıtlar successful retry'ları gösterir
                with open(_MISSED_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps(audit, default=str) + "\n")
            except Exception:
                pass
            try:
                from price_action.orchestrator.notifications import push_critical
                push_critical(
                    f"15m ENTRY RESOLVED via retry: {entry['symbol']} {entry['side']} "
                    f"order_id={order.get('id','?')} (orig timeout, retry başarılı)",
                    source="pending_retry_processor",
                )
            except Exception:
                pass
            continue
        else:
            # Re-queue with incremented attempts
            entry["attempts"] = attempts + 1
            entry["last_retry_reason"] = reason
            keep_lines.append(json.dumps(entry, default=str) + "\n")
            _log(f"RETRY_AGAIN: {entry['symbol']} attempts={attempts+1} reason={reason}")
            stats["retry_again"] += 1

    _atomic_rewrite(_QUEUE_PATH, keep_lines)
    return stats


def main() -> int:
    stats = process_pending()
    _log(f"DONE: {json.dumps(stats)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
