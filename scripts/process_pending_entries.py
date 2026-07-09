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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# PYTHONPATH
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
# F4 FIX 2026-07-10 (A1-03 dersi): script-direct koşumda repo kökü sys.path'te
# YOK → `from scripts.futures_trade_daily import ...` çözülmez. Reconcile'da
# yaşanan "test-yeşil, üretim-ölü" sınıfının önlemi.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
# .env: get_futures_exchange BINANCE_FUTURES_TESTNET_API_KEY okur
try:
    from dotenv import load_dotenv

    load_dotenv(_REPO / ".env", override=False)
except Exception:  # pragma: no cover — dotenv yoksa env'den devam
    pass

_QUEUE_PATH = Path("data/pending_retries.jsonl")
_MISSED_PATH = Path("data/missed_signals.jsonl")

# F4: kuyruk 'side' alanı sinyal formatında (long/short); borsa emri buy/sell ister.
_SIDE_TO_ORDER = {"long": "buy", "short": "sell", "buy": "buy", "sell": "sell"}


def _log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _push_missed(entry: dict[str, Any], reason: str) -> None:
    """Audit + Telegram alert for permanently failed entry."""
    try:
        _MISSED_PATH.parent.mkdir(parents=True, exist_ok=True)
        missed = dict(entry)
        missed["dropped_reason"] = reason
        missed["dropped_at"] = datetime.now(UTC).isoformat()
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
        try:  # noqa: SIM105
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=".tmp_pending_",
        suffix=".jsonl",
    )
    try:
        tmp.write("".join(lines))
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, str(path))
    except Exception as exc:
        try:  # noqa: SIM105
            os.unlink(tmp.name)
        except Exception:
            pass
        raise exc


def _check_existing_fill(ex, entry: dict[str, Any]) -> dict[str, Any] | None:
    """F4 ÇİFT-GİRİŞ KALKANI: submit ÖNCESİ orijinal + önceki retry emirlerinin
    akıbetini sorgula. -1007 timeout BELİRSİZLİKTİR — emir dolmuş olabilir;
    yeni market order katlama üretir. Dolmuş/kısmi-dolmuş emir bulunursa onu
    döndür (yeni emir YOK); açık NEW bulunursa iptal dener; hiçbiri yoksa None.
    """
    base_coid = str(entry.get("client_order_id", "") or "")
    if not base_coid:
        return None
    attempts = int(entry.get("attempts", 0))
    candidates = [base_coid] + [f"{base_coid}-r{k}" for k in range(1, attempts + 1)]
    for coid in candidates:
        try:
            order = ex.fetch_order(None, entry["symbol"], params={"origClientOrderId": coid})
        except Exception:
            continue  # OrderNotFound / geçici hata → sıradaki aday
        if not order:
            continue
        status = str(order.get("status", "")).lower()
        filled = float(order.get("filled") or 0)
        if status in ("closed", "filled") or filled > 0:
            _log(f"EXISTING_FILL: {entry['symbol']} coid={coid} filled={filled} — yeni emir YOK")
            return order
        if status in ("open", "new"):
            try:
                ex.cancel_order(order.get("id"), entry["symbol"])
                _log(f"EXISTING_OPEN_CANCELLED: {entry['symbol']} coid={coid}")
            except Exception as cexc:
                _log(f"EXISTING_CANCEL_FAIL: {coid} {str(cexc)[:80]}")
    return None


def _finalize_fill(
    entry: dict[str, Any],
    order: dict[str, Any],
    ex,
    journal_db: str,
    idempotency_db: str,
) -> dict[str, Any]:
    """F4 FIX 2026-07-10: retry-fill'i NORMAL giriş zincirine bağla.

    Eski davranış (kod yorumu itiraf ediyordu: 'journal yazma daemonun işi'):
    retry başarısı KORUMASIZ (SL/TP'siz) + JOURNAL'SIZ pozisyon bırakıyordu —
    daemon timeout dalında fill'den habersiz, kimse koruma koymuyordu.

    SIRA (koruma ÖNCE — pozisyon zaten >60s gecikmiş, çıplak saniyeler kritik):
    (a) fill_qty/avg_px çöz → (b) place_protection_orders → (c) journal INSERT
    (signals + protection; 3-deneme backoff, ASLA raise — koruma zaten kondu)
    → (d) idempotency mark_filled.

    NOT: _ORIG_INTENDED_SL daemon-process belleği, cross-process güncellenemez —
    KABUL: watchdog G22 dalı borsadaki SL'i intended taban alır; retry'ın
    koyduğu SL orijinal sinyal SL'i olduğundan trailing tabanı doğru ve stabil.
    """
    import time as _time
    import uuid as _uuid

    import duckdb

    result: dict[str, Any] = {
        "protection": None,
        "journal": False,
        "idempotency": False,
        "fill_qty": 0.0,
        "avg_px": 0.0,
        "sig_id": "",
    }
    symbol = entry["symbol"]
    side_norm = "long" if _SIDE_TO_ORDER.get(str(entry["side"]).lower()) == "buy" else "short"

    # (a) fill çöz — order.filled falsy ise fetch_order (daemon deseni)
    fill_qty = float(order.get("filled") or 0)
    avg_px = float(order.get("average") or order.get("price") or 0)
    if fill_qty <= 0 or avg_px <= 0:
        try:
            fresh = ex.fetch_order(order.get("id"), symbol)
            fill_qty = float(fresh.get("filled") or fill_qty) or float(entry["qty"])
            avg_px = float(fresh.get("average") or fresh.get("price") or avg_px) or float(
                entry["entry_px"]
            )
        except Exception:
            fill_qty = fill_qty or float(entry["qty"])
            avg_px = avg_px or float(entry["entry_px"])
    result["fill_qty"], result["avg_px"] = fill_qty, avg_px

    # (b) KORUMA ÖNCE
    try:
        try:
            from scripts.futures_trade_daily import place_protection_orders
        except ImportError:  # script-direct koşum (sys.path[0]=scripts/)
            from futures_trade_daily import place_protection_orders
        prot = place_protection_orders(
            ex,
            symbol,
            side_norm,
            fill_qty,
            float(entry["tp_price"]),
            float(entry["sl_price"]),
            entry_price=avg_px,
        )
        result["protection"] = prot.get("status")
        _log(f"RETRY_PROTECT: {symbol} status={prot.get('status')} sl={entry['sl_price']}")
    except Exception as pexc:
        prot = {"status": "error", "reason": str(pexc)[:120]}
        result["protection"] = "error"
        _log(f"RETRY_PROTECT_FAIL: {symbol} {str(pexc)[:120]}")

    # (c) journal — 3 deneme backoff; ASLA raise
    sig_id = _uuid.uuid4().hex[:16]
    result["sig_id"] = sig_id
    for attempt in range(3):
        try:
            jcon = duckdb.connect(journal_db)
            try:
                jcon.execute(
                    "INSERT INTO futures_signals VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        sig_id,
                        entry.get("ts"),
                        symbol,
                        entry.get("strategy", ""),
                        side_norm,
                        float(entry.get("sl_price") or 0),
                        float(entry.get("tp_price") or 0),
                        0.0,
                        int(entry.get("leverage") or 1),
                        "filled",
                        str(order.get("id", "")),
                        avg_px,
                        fill_qty,
                        fill_qty * avg_px,
                        (fill_qty * avg_px) / max(int(entry.get("leverage") or 1), 1),
                        "resolved_by_retry",
                    ),
                )
                if prot.get("status") == "placed":
                    notes = "resolved_by_retry"
                    if prot.get("mode") == "multi_target":
                        notes += (
                            f" mode=multi_target tp2={prot.get('tp2_price', 0):.4f}"
                            f" tp2_id={prot.get('tp2_order_id', '')}"
                        )
                    jcon.execute(
                        "INSERT INTO futures_protection_orders VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            _uuid.uuid4().hex[:16],
                            datetime.now(UTC),
                            sig_id,
                            symbol,
                            side_norm,
                            fill_qty,
                            prot.get("tp_price"),
                            prot.get("sl_price"),
                            prot.get("tp_order_id"),
                            prot.get("sl_order_id"),
                            "placed",
                            notes,
                        ),
                    )
                jcon.commit()
            finally:
                jcon.close()
            result["journal"] = True
            break
        except Exception as jexc:
            _log(f"RETRY_JOURNAL_ERR (deneme {attempt + 1}/3): {str(jexc)[:100]}")
            _time.sleep(2)
    if not result["journal"]:
        _push_missed(dict(entry), "JOURNAL_WRITE_FAILED (koruma kondu, journal yazılamadı)")

    # (d) idempotency
    try:
        coid = str(entry.get("client_order_id", "") or "")
        if coid.startswith("PA_"):
            from price_action.execution.idempotency import IdempotencyStore

            IdempotencyStore(db_path=idempotency_db).mark_filled(
                coid[3:], str(order.get("id", "")), avg_px, fill_qty
            )
            result["idempotency"] = True
    except Exception as iexc:
        _log(f"RETRY_IDEM_ERR: {str(iexc)[:100]}")

    return result


def _try_retry(entry: dict[str, Any]) -> tuple[bool, dict[str, Any] | None, str, Any]:
    """Tek bir entry için retry. Returns (success, order_dict, reason, exchange).

    F4 FIX 2026-07-10: (1) exchange init hayalet-env ccxt yerine daemon'ın
    get_futures_exchange factory'si (doğru auth+testnet URL — eski PA_BINANCE_*
    boştu, retry HİÇ auth olamıyordu); (2) 'side' long/short→buy/sell haritası
    (eski kod sinyal side'ını ccxt'ye ham geçiyordu — geçersiz emir);
    (3) submit ÖNCESİ çift-giriş kalkanı (_check_existing_fill); (4) exchange
    dönüşte — _finalize_fill (koruma+journal) aynı bağlantıyı kullanır.
    """
    try:
        try:
            from scripts.futures_trade_daily import get_futures_exchange
        except ImportError:  # script-direct koşum
            from futures_trade_daily import get_futures_exchange

        ex_class = get_futures_exchange()
    except Exception as exc:
        return False, None, f"exchange_init_fail: {exc}", None

    # F4: -1007 belirsizliği — önce eski emirlerin akıbeti
    existing = _check_existing_fill(ex_class, entry)
    if existing is not None:
        return True, existing, "resolved_from_existing_fill", ex_class

    # Fresh ticker
    try:
        ticker = ex_class.fetch_ticker(entry["symbol"])
        fresh_px = float(ticker.get("last") or entry["entry_px"])
    except Exception as exc:
        return False, None, f"ticker_fail: {exc}", ex_class

    # Slip kontrolü (%1)
    orig_px = float(entry["entry_px"])
    slip_pct = abs(fresh_px - orig_px) / orig_px * 100.0
    if slip_pct > 1.0:
        return False, None, f"slip_too_high: %{slip_pct:.2f} > %1.0", ex_class

    # Market order submit
    try:
        attempt = int(entry.get("attempts", 0)) + 1
        coid = f"{entry.get('client_order_id','')}-r{attempt}"
        order_side = _SIDE_TO_ORDER.get(str(entry["side"]).lower())
        if order_side is None:
            return False, None, f"invalid_side: {entry['side']}", ex_class
        order = ex_class.create_market_order(
            entry["symbol"],
            order_side,
            float(entry["qty"]),
            params={"newClientOrderId": coid},
        )
        return True, order, f"retry_attempt_{attempt}", ex_class
    except Exception as exc:
        return False, None, f"order_fail: {type(exc).__name__}: {str(exc)[:120]}", ex_class


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

    now = datetime.now(UTC)
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
        success, order, reason, ex_used = _try_retry(entry)
        if success:
            _log(f"RETRY_SUCCESS: {entry['symbol']} {reason} order_id={order.get('id','?')}")
            stats["success"] += 1
            # F4 FIX 2026-07-10: retry-fill artık normal giriş zincirine bağlı —
            # koruma (SL/TP) + journal + idempotency. Eski yorum ('journal yazma
            # daemonun işi') yalan çıkmıştı: daemon timeout dalında fill'den
            # habersiz, pozisyon KORUMASIZ kalıyordu.
            _journal_db = str(
                entry.get("journal_db") or (_REPO / "data" / "futures_journal.duckdb")
            )
            _idem_db = str(entry.get("idempotency_db") or (_REPO / "data" / "idempotency.duckdb"))
            try:
                _fin = _finalize_fill(entry, order, ex_used, _journal_db, _idem_db)
            except Exception as _fexc:
                _fin = {"protection": "error", "journal": False}
                _log(f"RETRY_FINALIZE_FAIL: {entry['symbol']} {str(_fexc)[:120]}")
            try:
                _MISSED_PATH.parent.mkdir(parents=True, exist_ok=True)
                audit = dict(entry)
                audit["retry_resolved_at"] = datetime.now(UTC).isoformat()
                audit["resolved_order_id"] = str(order.get("id", ""))
                audit["resolved_fill_price"] = float(
                    order.get("average") or order.get("price") or 0.0
                )
                audit["status"] = "RESOLVED_BY_RETRY"
                audit["protection"] = _fin.get("protection")
                audit["journal_written"] = _fin.get("journal")
                # Aynı dosya — 'RESOLVED' status'lü kayıtlar successful retry'ları gösterir
                with open(_MISSED_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps(audit, default=str) + "\n")
            except Exception:
                pass
            try:
                from price_action.orchestrator.notifications import push_critical

                push_critical(
                    f"15m ENTRY RESOLVED via retry: {entry['symbol']} {entry['side']} "
                    f"order_id={order.get('id','?')} — SL/TP={_fin.get('protection')} "
                    f"journal={_fin.get('journal')}",
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
