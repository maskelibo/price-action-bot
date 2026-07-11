"""Pending entry retry processor (Faz 13.1 — H6 deferred queue).

FIX 2026-05-26: Önceden futures_daemon entry timeout durumunda
time.sleep(30+60)=90s ile ana döngüyü bloke ediyordu. Yeni:
timeout sinyali data/pending_retries.jsonl'e yazıyor, daemon devam.
Bu script scheduler tarafından her 60s'de çağrılır, queue'yu işler.

Akış:
1. pending_retries.jsonl oku
2. Her giriş için:
   - main, `_fb`, onceki `-rN` ve explicit uncertain coid'leri reconcile et
   - transient/OPEN/UNKNOWN ise yeni emir yok; queue'da tut
   - yalniz hepsi terminal-not-found/canceled ise age/attempt gate uygula
   - Aksi: fresh ticker → slip kontrol → deterministik-coid market retry
     - Exchange qty+average dogrulanirsa protection+journal, queue'dan drop
     - Submit belirsizse coid metadata ile queue'ya geri yaz
3. Queue dosyasını yeniden yaz (atomic rename)

Single-shot mode: bir kez çalış, çık. Re-entry scheduler ile.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Callable
from contextlib import contextmanager, suppress
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
_PROTECTION_QUEUE_PATH = Path("data/protection_finalizations.jsonl")
_MISSED_PATH = Path("data/missed_signals.jsonl")

# F4: kuyruk 'side' alanı sinyal formatında (long/short); borsa emri buy/sell ister.
_SIDE_TO_ORDER = {"long": "buy", "short": "sell", "buy": "buy", "sell": "sell"}

from price_action.execution.post_only_router import (  # noqa: E402
    _extract_fill_evidence,
    _fallback_client_order_id,
    _is_definitive_submit_rejection,
)
from price_action.execution.slippage_tracker import (  # noqa: E402
    execution_evidence_values_match,
)

_TERMINAL_NO_FILL = {"canceled", "cancelled", "expired", "rejected"}
_FILLED_STATUS = {"closed", "filled"}
_OPEN_STATUS = {"open", "new", "partially_filled", "partially-filled"}
_CLIENT_ORDER_ID_MAX_LEN = 36


class ExistingOrderStateUncertainError(RuntimeError):
    """A prior submit cannot yet be proven filled or terminal-no-fill."""

    def __init__(
        self,
        *,
        stage: str,
        symbol: str,
        client_order_id: str,
        order_id: str = "",
        cause: BaseException | None = None,
        detail: str = "",
    ) -> None:
        self.stage = stage
        self.symbol = symbol
        self.client_order_id = client_order_id
        self.order_id = order_id
        self.cause = cause
        self.detail = detail
        cause_text = f"{type(cause).__name__}: {str(cause)[:120]}" if cause else detail
        super().__init__(
            f"existing order uncertain stage={stage} symbol={symbol} "
            f"coid={client_order_id or '?'} order_id={order_id or '?'} {cause_text}"
        )


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
            f"{entry.get('strategy', '')} — {reason} "
            f"(attempts={entry.get('attempts', 0)})",
            source="pending_retry_processor",
        )
    except Exception as exc:
        _log(f"telegram_push_fail: {exc}")


def _queue_lock_path(path: Path) -> Path:
    """Stable advisory-lock inode shared by appenders and atomic replacers."""
    return path.with_name(f"{path.name}.lock")


def _processor_lease_path(path: Path) -> Path:
    """Separate lease inode; queue appenders never acquire this lock."""
    return path.with_name(f"{path.name}.processor.lock")


@contextmanager
def _queue_lock(path: Path):
    """Serialize short queue I/O without blocking during exchange calls."""
    import fcntl

    lock_path = _queue_lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def _processor_lease(path: Path):
    """Allow at most one retry processor while keeping daemon appends free."""
    import fcntl

    lease_path = _processor_lease_path(path)
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lease_path, "a+", encoding="utf-8") as lease_file:
        try:
            fcntl.flock(lease_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lease_file.fileno(), fcntl.LOCK_UN)


def _fsync_parent(path: Path) -> None:
    """Persist rename/unlink metadata, not only temporary-file contents."""
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomic_rewrite_unlocked(path: Path, lines: list[str]) -> None:
    """Atomic rewrite; caller must hold ``_queue_lock(path)``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not lines:
        path.unlink(missing_ok=True)
        _fsync_parent(path)
        return
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed before atomic os.replace
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
        _fsync_parent(path)
    except Exception as exc:
        try:  # noqa: SIM105
            os.unlink(tmp.name)
        except Exception:
            pass
        raise exc


def _atomic_rewrite(path: Path, lines: list[str]) -> None:
    """Atomic file rewrite protected by the stable queue lock."""
    with _queue_lock(path):
        _atomic_rewrite_unlocked(path, lines)


def append_pending_entry(path: Path, entry: dict[str, Any]) -> str:
    """Durably append one queue record without racing processor replacement."""
    line = json.dumps(entry, default=str) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _queue_lock(path):
        existed = path.exists()
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        if not existed:
            _fsync_parent(path)
    return line.rstrip("\n")


def remove_pending_entry(path: Path, exact_line: str) -> None:
    """Durably remove one WAL row, or raise when neither bytes nor identity exist.

    A daemon/processor race may rewrite the JSON bytes after the caller captured
    them.  In that case the stable ``client_order_id + ts`` identity is accepted;
    silently succeeding with no consumed row would leave a submit-capable intent
    behind while the caller believes hand-off/retirement completed.
    """
    try:
        wanted = json.loads(exact_line)
    except Exception as exc:
        raise RuntimeError("pending WAL removal requires a valid JSON row") from exc
    wanted_identity = (
        str(wanted.get("client_order_id") or wanted.get("work_id") or ""),
        str(wanted.get("ts") or ""),
    )
    if not all(wanted_identity):
        raise RuntimeError("pending WAL removal identity is incomplete")

    with _queue_lock(path):
        current_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        matches = [index for index, line in enumerate(current_lines) if line == exact_line]
        if not matches:
            for index, line in enumerate(current_lines):
                try:
                    candidate = json.loads(line)
                except Exception:
                    continue
                identity = (
                    str(candidate.get("client_order_id") or candidate.get("work_id") or ""),
                    str(candidate.get("ts") or ""),
                )
                if identity == wanted_identity:
                    matches.append(index)
        if len(matches) != 1:
            raise RuntimeError(
                "pending WAL removal identity missing or ambiguous: "
                f"identity={wanted_identity!r} matches={len(matches)}"
            )
        del current_lines[matches[0]]
        _atomic_rewrite_unlocked(
            path,
            [line + "\n" for line in current_lines if line.strip()],
        )


def _read_queue_snapshot(path: Path) -> list[str]:
    """Read an exact snapshot under the append/replace lock."""
    # Avoid creating a lock artifact for a queue that has never existed. An
    # append racing this fast path is safely picked up on the next scheduled
    # run; append itself remains fsync+lock protected.
    if not path.exists():
        return []
    with _queue_lock(path):
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines()


def _commit_processed_snapshot(
    path: Path,
    snapshot_lines: list[str],
    keep_lines: list[str],
) -> None:
    """Remove the processed snapshot and merge records appended meanwhile.

    The processor intentionally releases the lock while calling the exchange.
    On commit, a multiset subtraction removes only the exact occurrences it
    read. Any daemon append after the snapshot remains in ``survivors`` and is
    carried into the atomic replacement.
    """
    with _queue_lock(path):
        current_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        consumed = Counter(snapshot_lines)
        survivors: list[str] = []
        for line in current_lines:
            if consumed[line] > 0:
                consumed[line] -= 1
            elif line.strip():
                survivors.append(line + "\n")
        _atomic_rewrite_unlocked(path, survivors + keep_lines)


def _persist_ack_transition(path: Path, old_line: str, entry: dict[str, Any]) -> str:
    """Durably replace one queue snapshot row with acknowledged order identity."""
    new_line = json.dumps(entry, default=str)
    with _queue_lock(path):
        current_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        replacement_index: int | None = None
        for index, line in enumerate(current_lines):
            if line == old_line:
                replacement_index = index
                break

        # Exact bytes should exist while the processor lease is held. If an
        # external tool reformatted the line, fall back to the intent identity
        # rather than appending a second, submit-capable copy.
        if replacement_index is None:
            wanted_coid = str(entry.get("client_order_id") or "")
            wanted_ts = str(entry.get("ts") or "")
            for index, line in enumerate(current_lines):
                try:
                    candidate = json.loads(line)
                except Exception:
                    continue
                if (
                    str(candidate.get("client_order_id") or "") == wanted_coid
                    and str(candidate.get("ts") or "") == wanted_ts
                ):
                    replacement_index = index
                    break
        if replacement_index is None:
            raise RuntimeError("ACK queue row disappeared before durable transition")

        current_lines[replacement_index] = new_line
        _atomic_rewrite_unlocked(path, [line + "\n" for line in current_lines if line.strip()])
    return new_line


def _retry_client_order_id(base_coid: str, attempt: int) -> str:
    """Deterministic retry id that also respects Binance's 36-char limit."""
    suffix = f"-r{attempt}"
    direct = f"{base_coid}{suffix}"
    if len(direct) <= _CLIENT_ORDER_ID_MAX_LEN:
        return direct
    digest = hashlib.sha256(base_coid.encode("utf-8")).hexdigest()[:6]
    prefix_len = _CLIENT_ORDER_ID_MAX_LEN - len(suffix) - len(digest) - 1
    return f"{base_coid[:prefix_len]}_{digest}{suffix}"


def _coid_candidates(entry: dict[str, Any]) -> list[str]:
    """All main/fallback/retry client ids that could own this intent."""
    candidates: list[str] = []

    def _add(value: Any) -> None:
        coid = str(value or "").strip()
        if coid and coid not in candidates:
            candidates.append(coid)

    explicit = entry.get("uncertain_client_order_ids")
    if isinstance(explicit, list):
        for value in explicit:
            _add(value)

    uncertainty = entry.get("submit_uncertainty")
    if isinstance(uncertainty, dict):
        _add(uncertainty.get("main_client_order_id"))
        _add(uncertainty.get("fallback_client_order_id"))

    base_coid = str(entry.get("client_order_id", "") or "").strip()
    _add(base_coid)
    if base_coid:
        _add(_fallback_client_order_id(base_coid))
        attempts = max(int(entry.get("attempts", 0)), 0)
        for attempt in range(1, attempts + 1):
            retry_coid = _retry_client_order_id(base_coid, attempt)
            _add(retry_coid)
            _add(_fallback_client_order_id(retry_coid))
    return candidates


def _order_id_candidates(entry: dict[str, Any]) -> list[str]:
    """Exchange order ids persisted after an acknowledged but unverified fill."""
    candidates: list[str] = []

    def _add(value: Any) -> None:
        order_id = str(value or "").strip()
        if order_id and order_id not in candidates:
            candidates.append(order_id)

    explicit = entry.get("known_order_ids")
    if isinstance(explicit, list):
        for value in explicit:
            _add(value)
    _add(entry.get("submitted_order_id"))
    uncertainty = entry.get("submit_uncertainty")
    if isinstance(uncertainty, dict):
        _add(uncertainty.get("partial_order_id"))
    return candidates


def _remember_acknowledged_order(
    entry: dict[str, Any],
    order: dict[str, Any],
    *,
    client_order_id: str | None = None,
    attempt: int | None = None,
) -> None:
    """Persist ACK ownership before any finalization step can fail."""
    known = _order_id_candidates(entry)

    def _add_order_id(value: Any) -> None:
        order_id = str(value or "").strip()
        if order_id and order_id not in known:
            known.append(order_id)

    resolved = order.get("resolved_order_ids")
    if isinstance(resolved, list):
        for value in resolved:
            _add_order_id(value)
    else:
        _add_order_id(order.get("id"))
    for key in ("partial_limit_order_id", "market_fallback_order_id"):
        _add_order_id(order.get(key))
    legs = order.get("fill_legs")
    if isinstance(legs, list):
        for leg in legs:
            if isinstance(leg, dict):
                _add_order_id(leg.get("id"))

    if known:
        entry["known_order_ids"] = known
        entry["submitted_order_id"] = known[0]
    if client_order_id:
        coids = entry.setdefault("uncertain_client_order_ids", [])
        if client_order_id not in coids:
            coids.append(client_order_id)
        entry["last_submitted_client_order_id"] = client_order_id
    if attempt is not None:
        entry["attempts"] = attempt
    entry["reconcile_only"] = True
    entry.pop("terminal_no_fill_confirmations", None)


def _prepare_retry_submit_identity(
    entry: dict[str, Any],
    *,
    base_client_order_id: str,
    retry_client_order_id: str,
    attempt: int,
) -> None:
    """Write-ahead metadata for a submit whose response may never arrive.

    The transition is persisted *before* the HTTP side effect.  Therefore a
    process/host crash during ``create_market_order`` still leaves the exact
    deterministic client id that the next processor must reconcile.
    """
    uncertain_ids = entry.setdefault("uncertain_client_order_ids", [])
    if retry_client_order_id not in uncertain_ids:
        uncertain_ids.append(retry_client_order_id)
    entry["attempts"] = attempt
    entry["terminal_no_fill_confirmations"] = 0
    entry["last_submitted_client_order_id"] = retry_client_order_id
    entry["submit_uncertainty"] = {
        "stage": "retry_market_submit_prepared",
        "main_client_order_id": base_client_order_id,
        "fallback_client_order_id": retry_client_order_id,
        "partial_order_id": None,
        "partial_qty": 0.0,
        "remaining_qty": float(entry["qty"]),
    }


def _is_terminal_order_not_found(exc: BaseException) -> bool:
    """Classify only an explicit exchange OrderNotFound as terminal absence."""
    names = {cls.__name__ for cls in type(exc).__mro__}
    if "OrderNotFound" in names:
        return True
    for value in (getattr(exc, "code", None), getattr(exc, "error_code", None)):
        try:
            if int(value) == -2013:  # Binance: Order does not exist.
                return True
        except (TypeError, ValueError):
            pass
    # Backward-compatible with the minimal offline FakeExchange; deliberately
    # exact so a transient message merely containing the phrase is not trusted.
    return str(exc).strip().lower() in {"ordernotfound", "order not found"}


def _status(order: dict[str, Any]) -> str:
    return str(order.get("status", "") or "").strip().lower()


def _cancel_and_verify_terminal(ex, entry: dict[str, Any], coid: str, order: dict[str, Any]):
    """Cancel an OPEN order, then require a fresh terminal exchange snapshot."""
    symbol = entry["symbol"]
    order_id = str(order.get("id") or "")
    if not order_id:
        raise ExistingOrderStateUncertainError(
            stage="open_missing_order_id",
            symbol=symbol,
            client_order_id=coid,
            detail="OPEN order has no exchange order id",
        )
    try:
        ex.cancel_order(order_id, symbol)
    except Exception as exc:
        _log(f"EXISTING_CANCEL_FAIL: {coid} {str(exc)[:80]}")
    try:
        verified = ex.fetch_order(order_id, symbol)
    except Exception as exc:
        raise ExistingOrderStateUncertainError(
            stage="cancel_verify",
            symbol=symbol,
            client_order_id=coid,
            order_id=order_id,
            cause=exc,
        ) from exc
    if not isinstance(verified, dict):
        raise ExistingOrderStateUncertainError(
            stage="cancel_verify",
            symbol=symbol,
            client_order_id=coid,
            order_id=order_id,
            detail="empty/non-dict verify response",
        )
    verified_status = _status(verified)
    if verified_status not in (_TERMINAL_NO_FILL | _FILLED_STATUS):
        raise ExistingOrderStateUncertainError(
            stage="cancel_verify",
            symbol=symbol,
            client_order_id=coid,
            order_id=order_id,
            detail=f"non-terminal status={verified_status or 'missing'}",
        )
    _log(f"EXISTING_OPEN_TERMINAL: {symbol} coid={coid} status={verified_status}")
    return verified


def _aggregate_existing_fills(orders: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Aggregate all main/fallback legs; never lose a known partial fill."""
    fill_legs: list[dict[str, Any]] = []
    seen_order_ids: set[str] = set()
    for order in orders:
        order_id = str(order.get("id") or "")
        if order_id and order_id in seen_order_ids:
            continue
        if order_id:
            seen_order_ids.add(order_id)
        evidence = _extract_fill_evidence(order)
        qty = evidence.get("qty")
        if qty is not None and float(qty) > 0:
            fill_legs.append(dict(order))
        elif _status(order) in _FILLED_STATUS:
            # Terminal-filled but delayed qty evidence: finalizer must reconcile
            # it; importantly this is not permission for another submit.
            fill_legs.append(dict(order))

    if not fill_legs:
        return None

    total_qty = 0.0
    total_notional = 0.0
    qty_verified = True
    price_verified = True
    order_ids: list[str] = []
    for leg in fill_legs:
        evidence = _extract_fill_evidence(leg)
        qty = evidence.get("qty")
        notional = evidence.get("notional")
        if qty is None:
            qty_verified = False
        else:
            total_qty += float(qty)
        if qty is None or notional is None or not evidence.get("price_verified"):
            price_verified = False
        else:
            total_notional += float(notional)
        if leg.get("id") is not None:
            order_ids.append(str(leg["id"]))

    average = total_notional / total_qty if price_verified and total_qty > 0 else None
    return {
        "id": ",".join(order_ids),
        "status": "closed",
        "filled": total_qty if qty_verified else None,
        "average": average,
        "cost": total_notional if price_verified else None,
        "fill_legs": fill_legs,
        "fill_quantity_verified": qty_verified,
        "fill_price_verified": price_verified,
        "resolved_order_ids": order_ids,
    }


def _check_existing_fill(ex, entry: dict[str, Any]) -> dict[str, Any] | None:
    """Reconcile every possible prior submit before allowing a new order.

    ``None`` now has one strict meaning: every candidate was explicitly
    OrderNotFound or terminal-no-fill. Transient lookup errors, empty replies,
    OPEN/UNKNOWN state, and unverified cancellation raise fail-closed.
    """
    symbol = str(entry.get("symbol") or "")
    candidates = _coid_candidates(entry)
    order_id_candidates = _order_id_candidates(entry)
    if not candidates and not order_id_candidates:
        raise ExistingOrderStateUncertainError(
            stage="candidate_build",
            symbol=symbol,
            client_order_id="",
            detail="missing deterministic client_order_id",
        )

    terminal_orders: list[dict[str, Any]] = []
    for order_id in order_id_candidates:
        try:
            order = ex.fetch_order(order_id, symbol)
        except Exception as exc:
            if _is_terminal_order_not_found(exc):
                continue
            raise ExistingOrderStateUncertainError(
                stage="lookup_order_id",
                symbol=symbol,
                client_order_id="",
                order_id=order_id,
                cause=exc,
            ) from exc
        if not isinstance(order, dict):
            raise ExistingOrderStateUncertainError(
                stage="lookup_order_id",
                symbol=symbol,
                client_order_id="",
                order_id=order_id,
                detail="empty/non-dict order response",
            )
        status = _status(order)
        if status in _OPEN_STATUS:
            order = _cancel_and_verify_terminal(ex, entry, f"order_id:{order_id}", order)
            status = _status(order)
        if status not in (_TERMINAL_NO_FILL | _FILLED_STATUS):
            raise ExistingOrderStateUncertainError(
                stage="status_order_id",
                symbol=symbol,
                client_order_id="",
                order_id=order_id,
                detail=f"unknown status={status or 'missing'}",
            )
        terminal_orders.append(order)

    for coid in candidates:
        try:
            order = ex.fetch_order(None, symbol, params={"origClientOrderId": coid})
        except Exception as exc:
            if _is_terminal_order_not_found(exc):
                continue
            raise ExistingOrderStateUncertainError(
                stage="lookup",
                symbol=symbol,
                client_order_id=coid,
                cause=exc,
            ) from exc
        if not isinstance(order, dict):
            raise ExistingOrderStateUncertainError(
                stage="lookup",
                symbol=symbol,
                client_order_id=coid,
                detail="empty/non-dict order response",
            )

        status = _status(order)
        if status in _OPEN_STATUS:
            order = _cancel_and_verify_terminal(ex, entry, coid, order)
            status = _status(order)
        if status not in (_TERMINAL_NO_FILL | _FILLED_STATUS):
            raise ExistingOrderStateUncertainError(
                stage="status",
                symbol=symbol,
                client_order_id=coid,
                order_id=str(order.get("id") or ""),
                detail=f"unknown status={status or 'missing'}",
            )
        terminal_orders.append(order)

    aggregate = _aggregate_existing_fills(terminal_orders)
    if aggregate is not None:
        _log(
            f"EXISTING_FILL: {symbol} order_ids={aggregate.get('id') or '?'} "
            f"filled={aggregate.get('filled')} — yeni emir YOK"
        )
    return aggregate


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _reconcile_fill_legs(ex, symbol: str, order: dict[str, Any]) -> dict[str, float] | None:
    """Bounded order/raw-info reconciliation for every known fill leg."""
    aggregate_evidence = _extract_fill_evidence(order)
    if aggregate_evidence.get("qty_verified") and aggregate_evidence.get("price_verified"):
        return {
            "qty": float(aggregate_evidence["qty"]),
            "average": float(aggregate_evidence["average"]),
            "notional": float(aggregate_evidence["notional"]),
        }

    raw_legs = order.get("fill_legs")
    legs = list(raw_legs) if isinstance(raw_legs, list) and raw_legs else [dict(order)]
    total_qty = 0.0
    total_notional = 0.0
    for raw_leg in legs:
        if not isinstance(raw_leg, dict):
            return None
        leg = dict(raw_leg)
        evidence = _extract_fill_evidence(leg)
        order_id = str(leg.get("id") or "")
        if not (evidence.get("qty_verified") and evidence.get("price_verified")) and order_id:
            # Immediate bounded refresh only; scheduler provides later retries.
            for _ in range(2):
                try:
                    fresh = ex.fetch_order(order_id, symbol)
                except Exception:
                    continue
                if isinstance(fresh, dict):
                    leg.update(fresh)
                    evidence = _extract_fill_evidence(leg)
                    if evidence.get("qty_verified") and evidence.get("price_verified"):
                        break
        if not (evidence.get("qty_verified") and evidence.get("price_verified")):
            return None
        total_qty += float(evidence["qty"])
        total_notional += float(evidence["notional"])

    if total_qty <= 0 or total_notional <= 0:
        return None
    return {"qty": total_qty, "average": total_notional / total_qty, "notional": total_notional}


def _trade_order_identity(trade: dict[str, Any]) -> tuple[str, str]:
    info = trade.get("info") if isinstance(trade.get("info"), dict) else {}
    order_id = str(
        trade.get("order")
        or trade.get("orderId")
        or info.get("orderId")
        or info.get("order_id")
        or ""
    )
    coid = str(
        trade.get("clientOrderId") or info.get("clientOrderId") or info.get("client_order_id") or ""
    )
    return order_id, coid


def _trade_qty_notional(trade: dict[str, Any]) -> tuple[float | None, float | None]:
    info = trade.get("info") if isinstance(trade.get("info"), dict) else {}
    qty = None
    for value in (
        trade.get("amount"),
        trade.get("qty"),
        info.get("qty"),
        info.get("executedQty"),
    ):
        qty = _positive_float(value)
        if qty is not None:
            break
    notional = None
    for value in (
        trade.get("cost"),
        trade.get("quoteQty"),
        info.get("quoteQty"),
        info.get("quoteQuantity"),
    ):
        notional = _positive_float(value)
        if notional is not None:
            break
    if notional is None and qty is not None:
        price = _positive_float(trade.get("price") or info.get("price"))
        if price is not None:
            notional = qty * price
    return qty, notional


def _resolve_from_user_trades(
    ex,
    symbol: str,
    order: dict[str, Any],
    candidate_coids: list[str],
) -> dict[str, float] | None:
    """Resolve delayed fills from exchange user-trade facts, filtered by id."""
    legs = order.get("fill_legs") if isinstance(order.get("fill_legs"), list) else [order]
    order_ids = {str(leg.get("id")) for leg in legs if isinstance(leg, dict) and leg.get("id")}
    coids = {str(value) for value in candidate_coids if value}
    if not order_ids and not coids:
        return None

    trade_batches: list[list[dict[str, Any]]] = []
    fetch_my_trades = getattr(ex, "fetch_my_trades", None)
    if callable(fetch_my_trades):
        try:
            trades = fetch_my_trades(symbol)
            if isinstance(trades, list):
                trade_batches.append(trades)
        except Exception:
            pass
    raw_fetch = getattr(ex, "fapiPrivateGetUserTrades", None)
    if callable(raw_fetch):
        try:
            trades = raw_fetch({"symbol": symbol.replace("/", "").replace(":USDT", "")})
            if isinstance(trades, list):
                trade_batches.append(trades)
        except Exception:
            pass

    seen: set[tuple[str, str, str, str, str]] = set()
    total_qty = 0.0
    total_notional = 0.0
    for batch in trade_batches:
        for trade in batch:
            if not isinstance(trade, dict):
                continue
            order_id, coid = _trade_order_identity(trade)
            if order_id not in order_ids and coid not in coids:
                continue
            info = trade.get("info") if isinstance(trade.get("info"), dict) else {}
            trade_id = str(trade.get("id") or info.get("id") or info.get("tradeId") or "")
            key = (
                trade_id,
                order_id,
                "" if trade_id else str(trade.get("timestamp") or info.get("time") or ""),
                "" if trade_id else str(trade.get("amount") or info.get("qty") or ""),
                "" if trade_id else str(trade.get("price") or info.get("price") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            qty, notional = _trade_qty_notional(trade)
            if qty is None or notional is None:
                return None
            total_qty += qty
            total_notional += notional

    expected_qty = _extract_fill_evidence(order).get("qty")
    if expected_qty is not None and not math.isclose(
        total_qty, float(expected_qty), rel_tol=1e-7, abs_tol=1e-10
    ):
        return None
    if total_qty <= 0 or total_notional <= 0:
        return None
    return {"qty": total_qty, "average": total_notional / total_qty, "notional": total_notional}


def _position_signed_qty(position: dict[str, Any]) -> float | None:
    info = position.get("info") if isinstance(position.get("info"), dict) else {}
    raw_amt = position.get("positionAmt", info.get("positionAmt"))
    if raw_amt is not None:
        try:
            return float(raw_amt)
        except (TypeError, ValueError):
            return None
    contracts = _positive_float(position.get("contracts"))
    if contracts is None:
        return None
    side = str(position.get("side") or "").lower()
    return -contracts if side == "short" else contracts


def _resolve_from_position_delta(
    ex, entry: dict[str, Any], expected_qty: float | None = None
) -> dict[str, float] | None:
    """Last-resort positionRisk proof, only with an explicit pre-submit baseline."""
    before_raw = entry.get("pre_submit_position_qty", entry.get("position_qty_before"))
    if before_raw is None:
        return None
    try:
        before_qty = float(before_raw)
    except (TypeError, ValueError):
        return None

    symbol = str(entry["symbol"])
    positions: list[dict[str, Any]] = []
    fetch_positions = getattr(ex, "fetch_positions", None)
    if callable(fetch_positions):
        try:
            fetched = fetch_positions([symbol])
            if isinstance(fetched, list):
                positions.extend(pos for pos in fetched if isinstance(pos, dict))
        except Exception:
            pass
    raw_fetch = getattr(ex, "fapiPrivateGetPositionRisk", None)
    if not positions and callable(raw_fetch):
        try:
            fetched = raw_fetch({"symbol": symbol.replace("/", "").replace(":USDT", "")})
            if isinstance(fetched, dict):
                fetched = [fetched]
            if isinstance(fetched, list):
                positions.extend(pos for pos in fetched if isinstance(pos, dict))
        except Exception:
            pass

    normalized = symbol.replace("/", "").replace(":USDT", "").upper()
    wanted_sign = 1.0 if _SIDE_TO_ORDER.get(str(entry.get("side", "")).lower()) == "buy" else -1.0
    for position in positions:
        info = position.get("info") if isinstance(position.get("info"), dict) else {}
        pos_symbol = str(position.get("symbol") or info.get("symbol") or "")
        if pos_symbol.replace("/", "").replace(":USDT", "").upper() != normalized:
            continue
        after_qty = _position_signed_qty(position)
        if after_qty is None:
            continue
        delta = after_qty - before_qty
        if delta * wanted_sign <= 0:
            continue
        qty = abs(delta)
        if expected_qty is not None and not math.isclose(
            qty, expected_qty, rel_tol=1e-7, abs_tol=1e-10
        ):
            continue
        entry_px = _positive_float(position.get("entryPrice") or info.get("entryPrice"))
        if entry_px is None:
            continue
        if not math.isclose(before_qty, 0.0, abs_tol=1e-12):
            before_px = _positive_float(entry.get("pre_submit_position_entry_price"))
            if before_px is None or before_qty * after_qty <= 0:
                continue
            new_notional = abs(after_qty) * entry_px - abs(before_qty) * before_px
            if new_notional <= 0:
                continue
            entry_px = new_notional / qty
        return {"qty": qty, "average": entry_px, "notional": qty * entry_px}
    return None


def _resolve_verified_fill(
    entry: dict[str, Any], order: dict[str, Any], ex
) -> dict[str, float] | None:
    symbol = str(entry["symbol"])
    resolved = _reconcile_fill_legs(ex, symbol, order)
    if resolved is not None:
        return resolved
    resolved = _resolve_from_user_trades(ex, symbol, order, _coid_candidates(entry))
    if resolved is not None:
        return resolved
    expected_qty = _extract_fill_evidence(order).get("qty")
    return _resolve_from_position_delta(
        ex,
        entry,
        float(expected_qty) if expected_qty is not None else None,
    )


def _audit_unverified_fill(entry: dict[str, Any], order: dict[str, Any], reason: str) -> None:
    """Durable audit + CRIT; never substitutes intended qty/price."""
    try:
        _MISSED_PATH.parent.mkdir(parents=True, exist_ok=True)
        audit = dict(entry)
        audit.update(
            {
                "status": "CRITICAL_FILL_EVIDENCE_UNVERIFIED",
                "audit_at": datetime.now(UTC).isoformat(),
                "reason": reason,
                "resolved_order_ids": order.get("resolved_order_ids")
                or [str(order.get("id") or "")],
            }
        )
        with open(_MISSED_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(audit, default=str) + "\n")
    except Exception as exc:
        _log(f"unverified_fill_audit_fail: {exc}")
    try:
        from price_action.orchestrator.notifications import push_critical

        push_critical(
            f"15m RETRY FILL UNVERIFIED: {entry.get('symbol')} {entry.get('side')} "
            f"order_ids={order.get('id') or '?'} — journal/protection SKIPPED; "
            "exchange fill qty+average reconcile required.",
            source="pending_retry_processor",
        )
    except Exception as exc:
        _log(f"telegram_push_fail: {exc}")


def _finalize_fill(
    entry: dict[str, Any],
    order: dict[str, Any],
    ex,
    journal_db: str,
    idempotency_db: str,
    *,
    protection_side_effects_allowed: bool = True,
    retired_reason: str | None = None,
    retired_protection_status: str = "retired_flat",
) -> dict[str, Any]:
    """F4 FIX 2026-07-10: retry-fill'i NORMAL giriş zincirine bağla.

    Eski davranış (kod yorumu itiraf ediyordu: 'journal yazma daemonun işi'):
    retry başarısı KORUMASIZ (SL/TP'siz) + JOURNAL'SIZ pozisyon bırakıyordu —
    daemon timeout dalında fill'den habersiz, kimse koruma koymuyordu.

    SIRA (koruma ÖNCE — pozisyon zaten >60s gecikmiş, çıplak saniyeler kritik):
    (a) exchange-backed fill_qty/avg_px çöz → (b) place_protection_orders → (c) journal INSERT
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
        "execution_evidence": False,
        "idempotency": False,
        "fill_qty": None,
        "avg_px": None,
        "sig_id": "",
        "verified": False,
        "finalized": False,
        "retryable": True,
    }
    symbol = entry["symbol"]
    side_norm = "long" if _SIDE_TO_ORDER.get(str(entry["side"]).lower()) == "buy" else "short"

    # (a) fill çöz. Intended qty/entry_px ASLA fill kanıtı değildir.  The
    # protection-finalize queue is different: its immutable fill_evidence was
    # written only after the daemon had already verified matching-engine facts,
    # and is hash/identity checked by its dedicated processor before arriving
    # here.  Reusing that durable evidence avoids turning a finalize-only replay
    # into a fresh entry reconciliation/submission workflow.
    durable_fill = entry.get("fill_evidence")
    if entry.get("work_type") == "finalize_verified_fill_v1" and isinstance(durable_fill, dict):
        try:
            evidence = {
                "qty": float(durable_fill["qty"]),
                "average": float(durable_fill["average"]),
                "notional": float(durable_fill["notional_usdt"]),
            }
        except (KeyError, TypeError, ValueError):
            evidence = None
    else:
        evidence = _resolve_verified_fill(entry, order, ex)
    if evidence is None:
        reason = "exchange qty+average unavailable after order/userTrades/positionRisk reconcile"
        result["failure_reason"] = reason
        _log(f"CRIT RETRY_FILL_UNVERIFIED: {symbol} order_ids={order.get('id') or '?'}")
        _audit_unverified_fill(entry, order, reason)
        return result
    fill_qty = float(evidence["qty"])
    avg_px = float(evidence["average"])
    if fill_qty <= 0 or avg_px <= 0:
        reason = "exchange evidence returned non-positive qty/average"
        result["failure_reason"] = reason
        _audit_unverified_fill(entry, order, reason)
        return result
    result["fill_qty"], result["avg_px"] = fill_qty, avg_px
    result["verified"] = True

    # (b) KORUMA ÖNCE.  A generation-proven flat position is the sole
    # journal-only path: no old SL/TP may be reattached, but the durable entry
    # fill and idempotency transition still have to be committed.
    if protection_side_effects_allowed:
        try:
            try:
                from scripts.futures_trade_daily import (
                    execute_protection_plan,
                    place_protection_orders,
                    protection_plan_intent_binding_sha256,
                )
            except ImportError:  # script-direct koşum (sys.path[0]=scripts/)
                from futures_trade_daily import (
                    execute_protection_plan,
                    place_protection_orders,
                    protection_plan_intent_binding_sha256,
                )
            if entry.get("work_type") == "finalize_verified_fill_v1":
                # Creation-time precision was validated before fsync; replay
                # verifies the external semantic binding and executes the
                # exact pinned legs even if later strategy/precision changes.
                _validated_protection_finalize_work(entry)
                prot = execute_protection_plan(ex, entry["protection_plan"])
            else:
                pending_plan = entry.get("protection_plan")
                if pending_plan is not None:
                    expected_binding = protection_plan_intent_binding_sha256(
                        pending_plan,
                        entry_client_order_id=str(entry["client_order_id"]),
                        symbol=str(symbol),
                        side=str(side_norm),
                        qty=fill_qty,
                        entry_price=avg_px,
                        tp_price=float(entry["tp_price"]),
                        sl_price=float(entry["sl_price"]),
                    )
                    if str(entry.get("protection_binding_sha256") or "") != expected_binding:
                        raise ValueError("pending protection plan semantic binding mismatch")
                prot = place_protection_orders(
                    ex,
                    symbol,
                    side_norm,
                    fill_qty,
                    float(entry["tp_price"]),
                    float(entry["sl_price"]),
                    entry_price=avg_px,
                    # Queue retry'ları aynı entry niyetini uzlaştırsın; aynı
                    # symbol/qty/levels ile ilerideki ayrı trade eski leg'i devralmasın.
                    protection_key=str(entry["client_order_id"]),
                    protection_plan=pending_plan,
                )
            result["protection"] = prot.get("status")
            _log(f"RETRY_PROTECT: {symbol} status={prot.get('status')} sl={entry['sl_price']}")
        except Exception as pexc:
            prot = {"status": "error", "reason": str(pexc)[:120]}
            result["protection"] = "error"
            _log(f"RETRY_PROTECT_FAIL: {symbol} {str(pexc)[:120]}")
    else:
        try:
            if entry.get("work_type") == "finalize_verified_fill_v1":
                _validated_protection_finalize_work(entry)
            try:
                from scripts.futures_trade_daily import _validated_protection_plan
            except ImportError:  # pragma: no cover - script-direct execution
                from futures_trade_daily import _validated_protection_plan

            plan = _validated_protection_plan(entry.get("protection_plan"))
            outputs = dict(plan["outputs"])
            prot = {
                "status": retired_protection_status,
                "mode": plan["mode"],
                "protection_key": plan["protection_key"],
                "plan_sha256": plan["plan_sha256"],
                "client_order_ids": {leg["name"]: leg["client_order_id"] for leg in plan["legs"]},
                "tp_order_id": None,
                "tp2_order_id": None,
                "sl_order_id": None,
                **outputs,
            }
            result["protection"] = retired_protection_status
        except Exception as pexc:
            prot = {"status": "error", "reason": str(pexc)[:120]}
            result["protection"] = "error"

    if result["protection"] not in {
        "placed",
        "retired_flat",
        "retired_generation_mismatch",
    }:
        reason = f"protection_not_placed: {prot.get('reason') or prot.get('status') or 'unknown'}"
        result["failure_reason"] = reason
        _log(
            f"CRIT RETRY_FILL_UNPROTECTED: {symbol} order_ids={order.get('id') or '?'} "
            "— queue kaydı terminal başarı sayılmayacak"
        )
        return result

    # (c) journal — 3 deneme backoff; ASLA raise
    # Stable ids make the journal transition replay-safe when the scheduler
    # kills the process after COMMIT but before the queue row is removed.
    journal_seed = "|".join(
        (
            "pending-retry-journal-v1",
            str(entry.get("client_order_id") or ""),
            str(entry.get("ts") or ""),
            str(symbol),
        )
    )
    sig_id = (
        str(entry.get("journal_signal_id") or "").strip()
        or _uuid.uuid5(_uuid.NAMESPACE_URL, journal_seed).hex[:16]
    )
    prot_id = (
        str(entry.get("journal_protection_id") or "").strip()
        or _uuid.uuid5(_uuid.NAMESPACE_URL, f"{journal_seed}|protection").hex[:16]
    )
    resolution_notes = (
        "resolved_by_protection_finalize_wal"
        if entry.get("work_type") == "finalize_verified_fill_v1"
        else "resolved_by_retry"
    )
    execution_outcome = entry.get("entry_execution_outcome")
    if isinstance(execution_outcome, dict):
        resolution_notes += (
            f" entry_fill_method={entry.get('entry_fill_method', '')}"
            f" slippage_breach_bps={float(execution_outcome.get('slippage_bps')):.6f}"
            f" slippage_limit_bps={float(execution_outcome.get('limit_bps')):.6f}"
            f" disposition={execution_outcome.get('disposition')}"
            " position_owned=true protection_required=true unwind_attempted=false"
        )
    result["sig_id"] = sig_id
    for attempt in range(3):
        try:
            jcon = duckdb.connect(journal_db)
            try:
                jcon.execute("BEGIN TRANSACTION")
                expected_signal = (
                    str(symbol),
                    side_norm,
                    str(order.get("id", "")),
                    avg_px,
                    fill_qty,
                )
                existing_signal = jcon.execute(
                    """SELECT symbol, side, order_id, fill_price, fill_qty
                         FROM futures_signals WHERE signal_id=?""",
                    [sig_id],
                ).fetchone()
                if existing_signal is None:
                    jcon.execute(
                        "INSERT INTO futures_signals VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            sig_id,
                            entry.get("signal_ts") or entry.get("ts"),
                            symbol,
                            entry.get("strategy", ""),
                            side_norm,
                            float(entry.get("sl_price") or 0),
                            float(entry.get("tp_price") or 0),
                            float(entry.get("confluence") or 0.0),
                            int(entry.get("leverage") or 1),
                            "filled",
                            str(order.get("id", "")),
                            avg_px,
                            fill_qty,
                            fill_qty * avg_px,
                            (fill_qty * avg_px) / max(int(entry.get("leverage") or 1), 1),
                            resolution_notes,
                        ),
                    )
                else:
                    existing_signal_normalized = (
                        str(existing_signal[0]),
                        str(existing_signal[1]),
                        str(existing_signal[2]),
                        float(existing_signal[3]),
                        float(existing_signal[4]),
                    )
                    if (
                        existing_signal_normalized[:3] != expected_signal[:3]
                        or not math.isclose(
                            existing_signal_normalized[3], expected_signal[3], rel_tol=1e-9
                        )
                        or not math.isclose(
                            existing_signal_normalized[4], expected_signal[4], rel_tol=1e-9
                        )
                    ):
                        raise RuntimeError("deterministic retry signal_id collision/mismatch")

                notes = resolution_notes
                if result["protection"].startswith("retired_"):
                    notes += f" retired_reason={retired_reason or 'position_flat'}"
                if prot.get("protection_key"):
                    notes += (
                        f" protection_key={prot.get('protection_key')}"
                        f" plan_sha256={prot.get('plan_sha256', '')}"
                        f" client_order_ids="
                        f"{json.dumps(prot.get('client_order_ids', {}), sort_keys=True)}"
                    )
                if prot.get("mode") == "multi_target":
                    notes += (
                        f" mode=multi_target tp2={prot.get('tp2_price', 0):.4f}"
                        f" tp2_id={prot.get('tp2_order_id', '')}"
                    )
                expected_protection = (
                    str(symbol),
                    side_norm,
                    fill_qty,
                    float(prot.get("tp_price") or 0),
                    float(prot.get("sl_price") or 0),
                    str(prot.get("tp_order_id") or ""),
                    str(prot.get("sl_order_id") or ""),
                )
                existing_protection = jcon.execute(
                    """SELECT symbol, side, qty, tp_price, sl_price,
                              tp_order_id, sl_order_id
                         FROM futures_protection_orders WHERE prot_id=?""",
                    [prot_id],
                ).fetchone()
                if existing_protection is None:
                    jcon.execute(
                        "INSERT INTO futures_protection_orders VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            prot_id,
                            datetime.now(UTC),
                            sig_id,
                            symbol,
                            side_norm,
                            fill_qty,
                            prot.get("tp_price"),
                            prot.get("sl_price"),
                            prot.get("tp_order_id"),
                            prot.get("sl_order_id"),
                            result["protection"],
                            notes,
                        ),
                    )
                else:
                    existing_protection_normalized = (
                        str(existing_protection[0]),
                        str(existing_protection[1]),
                        float(existing_protection[2]),
                        float(existing_protection[3]),
                        float(existing_protection[4]),
                        str(existing_protection[5] or ""),
                        str(existing_protection[6] or ""),
                    )
                    if (
                        existing_protection_normalized[:2] != expected_protection[:2]
                        or any(
                            not math.isclose(
                                existing_protection_normalized[index],
                                expected_protection[index],
                                rel_tol=1e-9,
                            )
                            for index in (2, 3, 4)
                        )
                        or (
                            not result["protection"].startswith("retired_")
                            and existing_protection_normalized[5:] != expected_protection[5:]
                        )
                    ):
                        raise RuntimeError("deterministic retry protection_id collision/mismatch")
                jcon.commit()
            except Exception:
                with suppress(Exception):
                    jcon.rollback()
                raise
            finally:
                jcon.close()
            result["journal"] = True
            break
        except Exception as jexc:
            _log(f"RETRY_JOURNAL_ERR (deneme {attempt + 1}/3): {str(jexc)[:100]}")
            _time.sleep(2)
    if not result["journal"]:
        result["failure_reason"] = "journal_write_failed_after_protection"
        _log(
            f"CRIT RETRY_JOURNAL_HELD: {symbol} order_ids={order.get('id') or '?'} "
            "— protection var, queue journal başarılı olana kadar tutulacak"
        )
        return result

    # (d) Crash-complete execution evidence.  The daemon may die immediately
    # after fsync/protection; replay the exact arrival/fill/fee/maker facts with
    # the same stable fill_id before declaring the WAL terminal.
    execution = entry.get("entry_execution_evidence")
    if not isinstance(execution, dict) and entry.get("slippage_db"):
        # Async retry fills were not known when their entry WAL was created.
        # Once exchange reconciliation proves the fill, persist the honest
        # minimal market/unknown-fee evidence instead of omitting the trade.
        execution = {
            "schema_version": 1,
            "expected_price": float(entry.get("entry_px") or avg_px),
            "realized_price": avg_px,
            "quantity": fill_qty,
            "notional_usdt": fill_qty * avg_px,
            "fee_usdt": None,
            "fee_source": "unavailable",
            "is_maker": False,
            "order_type": "deferred_reconcile_unknown",
            "maker_quantity": 0.0,
            "maker_notional_usdt": 0.0,
            "exchange_order_id": str(order.get("id") or ""),
        }
    if isinstance(execution, dict) and execution.get("schema_version") == 1:
        try:
            from price_action.execution.slippage_tracker import SlippageTracker

            verified_at = str((entry.get("fill_evidence") or {}).get("verified_at") or "")
            execution_ts = (
                datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
                if verified_at
                else datetime.now(UTC)
            )
            if execution_ts.tzinfo is None:
                execution_ts = execution_ts.replace(tzinfo=UTC)
            SlippageTracker(entry["slippage_db"]).record_fill(
                fill_id=f"entry_{sig_id}",
                ts=execution_ts,
                symbol=symbol,
                strategy=str(entry.get("strategy") or ""),
                side=side_norm,
                expected_price=float(execution["expected_price"]),
                realized_price=float(execution["realized_price"]),
                quantity=float(execution["quantity"]),
                fee_usdt=(
                    float(execution["fee_usdt"]) if execution.get("fee_usdt") is not None else None
                ),
                is_maker=bool(execution["is_maker"]),
                order_type=str(execution["order_type"]),
                mode=os.environ.get("PA_RUN_MODE", "paper"),
                exchange_order_id=str(execution.get("exchange_order_id") or ""),
                client_order_id=str(entry.get("client_order_id") or ""),
                notes=(
                    f"replayed_from_protection_wal truth_source="
                    f"{(entry.get('fill_evidence') or {}).get('source', '')}"
                ),
                tf=str(entry.get("tf") or "15m"),
                fill_type="entry",
                fill_role="entry",
                fee_source=str(execution.get("fee_source") or "unavailable"),
                maker_quantity=float(execution["maker_quantity"]),
                maker_notional_usdt=float(execution["maker_notional_usdt"]),
            )
            result["execution_evidence"] = True
        except Exception as execution_exc:
            result["failure_reason"] = (
                f"execution_evidence_write_failed_after_journal: "
                f"{type(execution_exc).__name__}: {str(execution_exc)[:120]}"
            )
            _log(f"RETRY_EXECUTION_EVIDENCE_ERR: {result['failure_reason']}")
            return result
    else:
        result["execution_evidence"] = True

    # (e) idempotency
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

    # A committed journal without a committed idempotency transition is not a
    # terminal queue success.  Stable journal IDs make replay harmless; keeping
    # the WAL is the only way to repair the idempotency store after restart.
    if not result["idempotency"]:
        result["failure_reason"] = "idempotency_write_failed_after_journal"
        return result

    result["finalized"] = True
    result["retryable"] = False
    return result


def _try_retry(
    entry: dict[str, Any],
    *,
    allow_submit: bool = True,
    on_ack: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
) -> tuple[bool, dict[str, Any] | None, str, Any]:
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
        return False, None, f"reconcile_uncertain: exchange_init_fail: {exc}", None

    # F4: -1007 belirsizliği — önce eski emirlerin akıbeti
    try:
        existing = _check_existing_fill(ex_class, entry)
    except ExistingOrderStateUncertainError as exc:
        return False, None, f"reconcile_uncertain: {exc}", ex_class
    if existing is not None:
        _remember_acknowledged_order(entry, existing)
        if on_ack is not None:
            try:
                on_ack(entry, existing)
            except Exception as exc:
                return (
                    False,
                    None,
                    f"reconcile_uncertain: ack_persist_fail: {type(exc).__name__}: {exc}",
                    ex_class,
                )
        return True, existing, "resolved_from_existing_fill", ex_class
    if not allow_submit:
        return False, None, "submit_disabled_after_terminal_reconcile", ex_class

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

    # Market order submit. Persist the exact deterministic retry identity
    # before the HTTP request; a SIGKILL/host crash during the request must not
    # make the next run forget which client id may already own a fill.
    try:
        attempt = int(entry.get("attempts", 0)) + 1
        base_coid = str(entry.get("client_order_id", "") or "")
        coid = _retry_client_order_id(base_coid, attempt)
        order_side = _SIDE_TO_ORDER.get(str(entry["side"]).lower())
        if order_side is None:
            return False, None, f"invalid_side: {entry['side']}", ex_class
        quantity = float(entry["qty"])
        _prepare_retry_submit_identity(
            entry,
            base_client_order_id=base_coid,
            retry_client_order_id=coid,
            attempt=attempt,
        )
    except Exception as exc:
        return False, None, f"invalid_submit_metadata: {type(exc).__name__}: {exc}", ex_class

    if on_ack is not None:
        try:
            on_ack(entry, {})
        except Exception as exc:
            return (
                False,
                None,
                f"reconcile_uncertain: submit_intent_persist_fail: {type(exc).__name__}: {exc}",
                ex_class,
            )

    try:
        order = ex_class.create_market_order(
            entry["symbol"],
            order_side,
            quantity,
            params={"newClientOrderId": coid},
        )
        if not isinstance(order, dict) or not order.get("id"):
            entry["submit_uncertainty"]["stage"] = "retry_market_submit_ack_missing"
            return False, None, "order_submit_uncertain: missing market ACK/order id", ex_class
        _remember_acknowledged_order(
            entry,
            order,
            client_order_id=coid,
            attempt=attempt,
        )
        if on_ack is not None:
            try:
                on_ack(entry, order)
            except Exception as exc:
                return (
                    False,
                    None,
                    f"reconcile_uncertain: ack_persist_fail: {type(exc).__name__}: {exc}",
                    ex_class,
                )
        return True, order, f"retry_attempt_{attempt}", ex_class
    except Exception as exc:
        entry["submit_uncertainty"]["stage"] = "retry_market_submit_response_uncertain"
        entry["submit_uncertainty"]["error_type"] = type(exc).__name__
        if _is_definitive_submit_rejection(exc):
            entry["submit_uncertainty"]["stage"] = "retry_market_submit_rejected"
            return False, None, f"order_rejected: {type(exc).__name__}: {str(exc)[:120]}", ex_class
        return (
            False,
            None,
            f"order_submit_uncertain: {type(exc).__name__}: {str(exc)[:120]}",
            ex_class,
        )


def _validated_protection_finalize_work(entry: dict[str, Any]) -> dict[str, Any]:
    """Validate a finalize-only WAL row without performing exchange I/O."""
    if entry.get("schema_version") != 1:
        raise ValueError("invalid protection-finalize schema")
    if entry.get("work_type") != "finalize_verified_fill_v1":
        raise ValueError("invalid protection-finalize work type")
    if entry.get("entry_submit_allowed") is not False or not entry.get("reconcile_only"):
        raise ValueError("protection-finalize work must forbid entry submit")
    for field in (
        "work_id",
        "client_order_id",
        "journal_signal_id",
        "journal_protection_id",
        "journal_order_id",
        "journal_db",
        "idempotency_db",
        "slippage_db",
        "symbol",
    ):
        if not str(entry.get(field) or "").strip():
            raise ValueError(f"missing protection-finalize {field}")
    if str(entry["work_id"]) != str(entry["client_order_id"]):
        raise ValueError("protection-finalize work identity mismatch")

    fill = entry.get("fill_evidence")
    if not isinstance(fill, dict) or fill.get("verified") is not True:
        raise ValueError("protection-finalize fill evidence is not verified")
    numeric = {
        "qty": fill.get("qty"),
        "average": fill.get("average"),
        "notional_usdt": fill.get("notional_usdt"),
    }
    values: dict[str, float] = {}
    for field, raw in numeric.items():
        value = float(raw)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"invalid protection-finalize fill {field}")
        values[field] = value
    if not math.isclose(
        values["notional_usdt"],
        values["qty"] * values["average"],
        rel_tol=1e-6,
        abs_tol=1e-8,
    ):
        raise ValueError("protection-finalize fill notional mismatch")
    if not math.isclose(float(entry.get("qty")), values["qty"], rel_tol=1e-12):
        raise ValueError("protection-finalize top-level quantity mismatch")
    if not math.isclose(float(entry.get("entry_px")), values["average"], rel_tol=1e-12):
        raise ValueError("protection-finalize top-level price mismatch")

    try:
        from scripts.futures_trade_daily import _validated_protection_plan
    except ImportError:  # pragma: no cover - script-direct execution
        from futures_trade_daily import _validated_protection_plan

    plan = _validated_protection_plan(entry.get("protection_plan"))
    raw_side = str(entry.get("side", "")).lower()
    if raw_side not in _SIDE_TO_ORDER:
        raise ValueError("invalid protection-finalize side")
    normalized_side = "long" if _SIDE_TO_ORDER[raw_side] == "buy" else "short"
    if str(plan["symbol"]) != str(entry["symbol"]) or plan["side"] != normalized_side:
        raise ValueError("protection-finalize plan identity mismatch")
    if not math.isclose(float(plan["quantity"]), values["qty"], rel_tol=1e-12):
        raise ValueError("protection-finalize plan quantity mismatch")
    if not math.isclose(float(plan["entry_price"]), values["average"], rel_tol=1e-12):
        raise ValueError("protection-finalize plan entry price mismatch")
    if not math.isclose(
        float(plan["strategy_tp_price"]),
        float(entry.get("tp_price")),
        rel_tol=1e-12,
    ):
        raise ValueError("protection-finalize plan strategy TP mismatch")
    if not math.isclose(
        float(plan["original_sl_price"]),
        float(entry.get("sl_price")),
        rel_tol=1e-12,
    ):
        raise ValueError("protection-finalize plan SL mismatch")
    if str(plan["protection_key"]) != str(entry.get("protection_intent_id")):
        raise ValueError("protection-finalize plan key mismatch")
    expected_binding = _protection_finalize_binding_sha256(entry)
    if str(entry.get("protection_binding_sha256") or "") != expected_binding:
        raise ValueError("protection-finalize semantic binding mismatch")

    execution_outcome = entry.get("entry_execution_outcome")
    breach_method = str(entry.get("entry_fill_method") or "") == (
        "market_fallback_slippage_breach_protect"
    )
    if breach_method and not isinstance(execution_outcome, dict):
        raise ValueError("slippage breach fill is missing ownership outcome")
    if execution_outcome is not None:
        if not isinstance(execution_outcome, dict):
            raise ValueError("invalid entry execution outcome")
        expected_entry_side = "buy" if normalized_side == "long" else "sell"
        try:
            outcome_matches = (
                execution_outcome.get("schema_version") == 1
                and execution_outcome.get("outcome_type") == "slippage_breach"
                and execution_outcome.get("disposition") == "protect_position"
                and execution_outcome.get("position_owned") is True
                and execution_outcome.get("protection_required") is True
                and execution_outcome.get("unwind_attempted") is False
                and execution_outcome.get("fill_evidence_verified") is True
                and str(execution_outcome.get("symbol")) == str(entry["symbol"])
                and str(execution_outcome.get("entry_side")).lower() == expected_entry_side
                and math.isfinite(float(execution_outcome.get("slippage_bps")))
                and math.isfinite(float(execution_outcome.get("limit_bps")))
                and float(execution_outcome.get("slippage_bps"))
                > float(execution_outcome.get("limit_bps"))
                and execution_evidence_values_match(
                    execution_outcome.get("owned_quantity"), values["qty"]
                )
                and execution_evidence_values_match(
                    execution_outcome.get("owned_average"), values["average"]
                )
            )
        except (TypeError, ValueError):
            outcome_matches = False
        if not outcome_matches:
            raise ValueError("slippage breach ownership/fill mismatch")
    execution = entry.get("entry_execution_evidence")
    if not isinstance(execution, dict) or execution.get("schema_version") != 1:
        raise ValueError("missing entry execution evidence")
    try:
        execution_qty = float(execution["quantity"])
        execution_notional = float(execution["notional_usdt"])
        expected_price = float(execution["expected_price"])
        realized_price = float(execution["realized_price"])
        maker_qty = float(execution["maker_quantity"])
        maker_notional = float(execution["maker_notional_usdt"])
        fee = execution.get("fee_usdt")
        fee = float(fee) if fee is not None else None
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid entry execution evidence numerics") from exc
    if (
        not all(
            math.isfinite(value) and value > 0
            for value in (
                execution_qty,
                execution_notional,
                expected_price,
                realized_price,
            )
        )
        or not math.isclose(execution_qty, values["qty"], rel_tol=1e-12)
        or not math.isclose(execution_notional, values["notional_usdt"], rel_tol=1e-12)
        or not math.isclose(realized_price, values["average"], rel_tol=1e-12)
        or not (0 <= maker_qty <= execution_qty)
        or not (0 <= maker_notional <= execution_notional)
        or (fee is not None and not math.isfinite(fee))
        or str(execution.get("fill_method")) != str(entry.get("entry_fill_method"))
        or not isinstance(execution.get("is_maker"), bool)
        or not str(execution.get("fee_source") or "").strip()
        or not str(execution.get("order_type") or "").strip()
    ):
        raise ValueError("entry execution evidence/fill mismatch")
    generation = entry.get("position_generation")
    if not isinstance(generation, dict) or generation.get("schema_version") != 1:
        raise ValueError("missing protection-finalize position generation")
    if str(generation.get("symbol")) != str(entry["symbol"]):
        raise ValueError("protection-finalize generation symbol mismatch")
    if str(generation.get("side")).lower() != normalized_side:
        raise ValueError("protection-finalize generation side mismatch")
    for field in ("initial_quantity", "initial_entry_price", "verified_at_ms"):
        value = float(generation.get(field))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"invalid protection-finalize generation {field}")
    if not math.isclose(float(generation["initial_quantity"]), values["qty"], rel_tol=1e-12):
        raise ValueError("protection-finalize generation quantity mismatch")
    if not math.isclose(float(generation["initial_entry_price"]), values["average"], rel_tol=1e-12):
        raise ValueError("protection-finalize generation entry mismatch")
    if not math.isclose(
        float(generation["verified_at_ms"]),
        float(fill.get("verified_at_ms")),
        rel_tol=0.0,
        abs_tol=0.5,
    ):
        raise ValueError("protection-finalize generation timestamp mismatch")
    return entry


def _protection_finalize_binding_sha256(entry: dict[str, Any]) -> str:
    try:
        from scripts.futures_trade_daily import protection_plan_intent_binding_sha256
    except ImportError:  # pragma: no cover - script-direct execution
        from futures_trade_daily import protection_plan_intent_binding_sha256

    fill = entry["fill_evidence"]
    return protection_plan_intent_binding_sha256(
        entry["protection_plan"],
        entry_client_order_id=str(entry["client_order_id"]),
        symbol=str(entry["symbol"]),
        side=str(entry["side"]),
        qty=float(fill["qty"]),
        entry_price=float(fill["average"]),
        tp_price=float(entry["tp_price"]),
        sl_price=float(entry["sl_price"]),
    )


def _protection_finalize_order(entry: dict[str, Any]) -> dict[str, Any]:
    """Build a synthetic ACK solely from already-verified, durable fill facts."""
    fill = entry["fill_evidence"]
    order_ids = [str(value) for value in fill.get("order_ids", []) if str(value)]
    return {
        "id": str(entry["journal_order_id"]),
        "status": "closed",
        "filled": float(fill["qty"]),
        "average": float(fill["average"]),
        "cost": float(fill["notional_usdt"]),
        "fill_quantity_verified": True,
        "fill_price_verified": True,
        "resolved_order_ids": order_ids,
    }


def _normalize_exchange_symbol(value: Any) -> str:
    symbol = str(value or "").upper().strip()
    if ":" in symbol:
        symbol = symbol.split(":", 1)[0]
    return symbol.replace("/", "").replace("-", "")


def _position_update_time_ms(position: dict[str, Any]) -> float | None:
    info = position.get("info") if isinstance(position.get("info"), dict) else {}
    # Binance positionRisk's updateTime is a mutation clock.  CCXT's generic
    # ``timestamp`` may instead be fetch time and must not bind generations.
    for key in ("updateTime", "update_time"):
        raw = position.get(key, info.get(key))
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if 0 < value < 100_000_000_000:
            value *= 1000.0
        if math.isfinite(value) and value > 0:
            return value
    return None


def _protection_position_generation_state(exchange, entry: dict[str, Any]) -> tuple[str, str]:
    """Prove replay still targets the same net-position generation."""
    symbol = str(entry["symbol"])
    wanted_symbol = _normalize_exchange_symbol(symbol)
    generation = entry["position_generation"]
    wanted_side = str(generation["side"]).lower()
    original_qty = float(generation["initial_quantity"])
    original_entry = float(generation["initial_entry_price"])
    verified_at_ms = float(generation["verified_at_ms"])

    positions: list[dict[str, Any]] = []
    had_authoritative_response = False
    fetch_positions = getattr(exchange, "fetch_positions", None)
    if callable(fetch_positions):
        try:
            fetched = fetch_positions([symbol])
            if isinstance(fetched, list):
                candidates = [item for item in fetched if isinstance(item, dict)]
                if any(
                    _normalize_exchange_symbol(
                        item.get("symbol")
                        or (
                            item.get("info", {}).get("symbol")
                            if isinstance(item.get("info"), dict)
                            else None
                        )
                    )
                    == wanted_symbol
                    for item in candidates
                ):
                    had_authoritative_response = True
                    positions = candidates
        except Exception:
            pass
    raw_fetch = getattr(exchange, "fapiPrivateGetPositionRisk", None)
    if not had_authoritative_response and callable(raw_fetch):
        try:
            fetched = raw_fetch({"symbol": wanted_symbol})
            if isinstance(fetched, dict):
                fetched = [fetched]
            if isinstance(fetched, list):
                had_authoritative_response = True
                positions.extend(item for item in fetched if isinstance(item, dict))
        except Exception:
            pass
    if not had_authoritative_response:
        return "unverifiable", "position API unavailable"

    matching: list[dict[str, Any]] = []
    for position in positions:
        info = position.get("info") if isinstance(position.get("info"), dict) else {}
        pos_symbol = position.get("symbol") or info.get("symbol")
        if _normalize_exchange_symbol(pos_symbol) == wanted_symbol:
            matching.append(position)
    if not matching:
        return "unverifiable", "position API did not return the requested symbol"

    nonzero: list[tuple[dict[str, Any], float]] = []
    for position in matching:
        signed_qty = _position_signed_qty(position)
        if signed_qty is None:
            return "unverifiable", "position quantity missing"
        if not math.isclose(signed_qty, 0.0, abs_tol=1e-12):
            nonzero.append((position, signed_qty))
    if not nonzero:
        return "flat", "original position is explicitly flat"
    if len(nonzero) != 1:
        return "mismatch", "multiple nonzero position rows"

    position, signed_qty = nonzero[0]
    current_side = "long" if signed_qty > 0 else "short"
    current_qty = abs(signed_qty)
    if current_side != wanted_side:
        return "mismatch", f"side changed to {current_side}"
    if current_qty > original_qty * (1.0 + 1e-7):
        return "mismatch", f"quantity increased {current_qty} > {original_qty}"
    info = position.get("info") if isinstance(position.get("info"), dict) else {}
    try:
        current_entry = float(position.get("entryPrice") or info.get("entryPrice"))
    except (TypeError, ValueError):
        return "unverifiable", "position entry price missing"
    if not math.isfinite(current_entry) or current_entry <= 0:
        return "unverifiable", "position entry price invalid"
    if not math.isclose(current_entry, original_entry, rel_tol=1e-7, abs_tol=1e-10):
        return "mismatch", f"entry changed {current_entry} != {original_entry}"

    update_ms = _position_update_time_ms(position)
    if update_ms is None:
        return "unverifiable", "position generation timestamp missing"
    if update_ms > verified_at_ms + 2_000:
        return "mismatch", f"position updated after fill generation ({update_ms:.0f})"
    return "match", "same position generation"


def _audit_protection_generation(entry: dict[str, Any], status: str, detail: str) -> None:
    """Durably record why stale protection work was retired/quarantined."""
    _MISSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    audit = {
        "ts": datetime.now(UTC).isoformat(),
        "status": f"PROTECTION_GENERATION_{status.upper()}",
        "work_id": entry.get("work_id"),
        "symbol": entry.get("symbol"),
        "side": entry.get("side"),
        "detail": detail,
        "position_generation": entry.get("position_generation"),
        "protection_plan_sha256": (entry.get("protection_plan") or {}).get("plan_sha256"),
    }
    with open(_MISSED_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(audit, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _new_stats() -> dict[str, int]:
    return {
        "read": 0,
        "success": 0,
        "retry_again": 0,
        "dropped_age": 0,
        "dropped_attempts": 0,
        "dropped_terminal": 0,
        "busy": 0,
        "malformed": 0,
    }


def _merge_stats(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + int(value)


def _process_protection_finalizations_leased() -> dict[str, int]:
    """Replay protection/journal only; this branch has no entry-submit call."""
    stats = _new_stats()
    try:
        raw_lines = _read_queue_snapshot(_PROTECTION_QUEUE_PATH)
    except Exception as exc:
        _log(f"protection_queue_read_fail: {exc}")
        return stats
    if not raw_lines:
        return stats

    parsed_entries: list[dict[str, Any]] = []
    for index, line in enumerate(raw_lines):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
            if not isinstance(parsed, dict):
                raise ValueError("row is not an object")
            parsed_entries.append(_validated_protection_finalize_work(parsed))
        except Exception as exc:
            stats["malformed"] += 1
            _log(
                f"PROTECTION_QUEUE_MALFORMED_FAIL_CLOSED: line={index + 1} "
                f"err={type(exc).__name__}: {str(exc)[:120]}"
            )
            return stats

    keep_lines: list[str] = []
    for entry in parsed_entries:
        stats["read"] += 1
        entry["finalize_attempts"] = int(entry.get("finalize_attempts", 0)) + 1
        try:
            try:
                from scripts.futures_trade_daily import get_futures_exchange
            except ImportError:  # pragma: no cover - script-direct execution
                from futures_trade_daily import get_futures_exchange

            exchange = get_futures_exchange()
            generation_status, generation_detail = _protection_position_generation_state(
                exchange, entry
            )
            if generation_status == "flat":
                _audit_protection_generation(entry, generation_status, generation_detail)
                _log(
                    f"PROTECTION_FINALIZE_RETIRED_FLAT: {entry['symbol']} "
                    f"work_id={entry['work_id']}"
                )
            elif generation_status == "unverifiable":
                _audit_protection_generation(entry, generation_status, generation_detail)
                entry["last_retry_reason"] = (
                    f"position_generation_{generation_status}: {generation_detail}"
                )
                keep_lines.append(json.dumps(entry, default=str) + "\n")
                stats["retry_again"] += 1
                _log(
                    f"PROTECTION_FINALIZE_QUARANTINED: {entry['symbol']} "
                    f"work_id={entry['work_id']} reason={entry['last_retry_reason']}"
                )
                continue
            elif generation_status == "mismatch":
                # Proven stale generation: archive/journal the old fill without
                # protection side effects, then remove it from the active queue.
                # Keeping it would let the watchdog apply old levels after the
                # bounded lease expires.
                _audit_protection_generation(entry, generation_status, generation_detail)
                _log(
                    f"PROTECTION_FINALIZE_RETIRED_MISMATCH: {entry['symbol']} "
                    f"work_id={entry['work_id']} detail={generation_detail}"
                )
            order = _protection_finalize_order(entry)
            finalized = _finalize_fill(
                entry,
                order,
                exchange,
                str(entry["journal_db"]),
                str(entry["idempotency_db"]),
                protection_side_effects_allowed=(generation_status == "match"),
                retired_reason=(
                    generation_detail if generation_status in {"flat", "mismatch"} else None
                ),
                retired_protection_status=(
                    "retired_generation_mismatch"
                    if generation_status == "mismatch"
                    else "retired_flat"
                ),
            )
        except Exception as exc:
            finalized = {
                "finalized": False,
                "failure_reason": f"{type(exc).__name__}: {str(exc)[:160]}",
            }

        if finalized.get("finalized") and finalized.get("protection") in {
            "placed",
            "retired_flat",
            "retired_generation_mismatch",
        }:
            stats["success"] += 1
            _log(
                f"PROTECTION_FINALIZED: {entry['symbol']} work_id={entry['work_id']} "
                f"attempts={entry['finalize_attempts']}"
            )
            continue

        entry["last_retry_reason"] = str(
            finalized.get("failure_reason") or "protection_finalize_incomplete"
        )
        keep_lines.append(json.dumps(entry, default=str) + "\n")
        stats["retry_again"] += 1
        _log(
            f"PROTECTION_FINALIZE_HELD: {entry['symbol']} work_id={entry['work_id']} "
            f"reason={entry['last_retry_reason']}"
        )

    _commit_processed_snapshot(_PROTECTION_QUEUE_PATH, raw_lines, keep_lines)
    return stats


def _process_pending_leased() -> dict[str, int]:
    """Process one snapshot while the caller owns the processor lease."""
    stats = _new_stats()

    try:
        raw_lines = _read_queue_snapshot(_QUEUE_PATH)
    except Exception as exc:
        _log(f"queue_read_fail: {exc}")
        return stats
    if not raw_lines:
        return stats

    now = datetime.now(UTC)
    keep_lines: list[str] = []
    parsed_entries: list[tuple[int, dict[str, Any]]] = []

    # Fail the entire snapshot closed before any exchange side effect. A bad
    # line must never disappear merely because the valid neighbors committed.
    for snapshot_index, snapshot_line in enumerate(raw_lines):
        if not snapshot_line.strip():
            continue
        try:
            parsed = json.loads(snapshot_line)
        except Exception as exc:
            stats["malformed"] += 1
            _log(
                f"QUEUE_MALFORMED_FAIL_CLOSED: line={snapshot_index + 1} "
                f"err={type(exc).__name__}: {str(exc)[:100]}"
            )
            return stats
        if not isinstance(parsed, dict):
            stats["malformed"] += 1
            _log(f"QUEUE_MALFORMED_FAIL_CLOSED: line={snapshot_index + 1} not an object")
            return stats
        parsed_entries.append((snapshot_index, parsed))

    for snapshot_index, entry in parsed_entries:
        stats["read"] += 1

        if entry.get("entry_submit_allowed") is False and not bool(
            entry.get("reconcile_only", False)
        ):
            entry["last_retry_reason"] = (
                "invalid_schema: entry_submit_allowed=false requires reconcile_only=true"
            )
            keep_lines.append(json.dumps(entry, default=str) + "\n")
            stats["retry_again"] += 1
            _log(f"ENTRY_QUEUE_SCHEMA_FAIL_CLOSED: {entry.get('symbol')}")
            continue

        # The daemon writes the entry intent before its own HTTP request.  A
        # short, explicit lease prevents the minute scheduler racing that live
        # request; after the deadline, a crashed daemon can no longer strand
        # the intent.  No exchange call is made while the lease is active.
        lease_raw = entry.get("direct_submit_lease_until")
        if lease_raw:
            try:
                lease_until = datetime.fromisoformat(str(lease_raw).replace("Z", "+00:00"))
                if lease_until.tzinfo is None:
                    lease_until = lease_until.replace(tzinfo=UTC)
                else:
                    lease_until = lease_until.astimezone(UTC)
            except (TypeError, ValueError):
                entry["last_retry_reason"] = "invalid_direct_submit_lease_until"
                keep_lines.append(json.dumps(entry, default=str) + "\n")
                stats["retry_again"] += 1
                _log(f"ENTRY_WAL_INVALID_LEASE_FAIL_CLOSED: {entry.get('symbol')}")
                continue
            if lease_until is not None and now < lease_until:
                keep_lines.append(json.dumps(entry, default=str) + "\n")
                stats["retry_again"] += 1
                _log(
                    f"ENTRY_WAL_OWNER_LEASE: {entry.get('symbol')} until={lease_until.isoformat()}"
                )
                continue

        # Age/attempt gates no longer drop before reconciliation: the last
        # timed-out submit may have filled even when the queue item is stale.
        age_block_reason: str | None = None
        age_s = 0.0
        max_age = float(entry.get("max_age_seconds", 120))
        try:
            ts = datetime.fromisoformat(entry["ts"])
            age_s = (now - ts).total_seconds()
            if age_s > max_age:
                age_block_reason = f"max_age_exceeded ({age_s:.0f}s > {max_age:.0f}s)"
        except Exception as exc:
            _log(f"age_check_fail: {exc}")
            age_block_reason = f"invalid_age_metadata: {str(exc)[:100]}"

        attempts = int(entry.get("attempts", 0))
        max_attempts = int(entry.get("max_attempts", 2))
        attempts_exhausted = attempts >= max_attempts

        # Always reconcile first; only the submit portion is gated.
        reconcile_only = bool(entry.get("reconcile_only", False))
        terminal_confirmations = int(entry.get("terminal_no_fill_confirmations", 0))
        terminal_confirmations_required = max(
            int(entry.get("terminal_no_fill_confirmations_required", 2)), 2
        )
        # `_try_retry` always reconciles before it considers submit. With one
        # durable prior terminal observation, that in-call reconcile is the
        # required second confirmation and may safely precede the new -rN.
        confirmation_ready_to_submit = terminal_confirmations >= terminal_confirmations_required - 1
        allow_submit = (
            age_block_reason is None
            and not attempts_exhausted
            and not reconcile_only
            and entry.get("entry_submit_allowed", True) is not False
            and confirmation_ready_to_submit
        )

        def _durable_ack(
            acknowledged_entry: dict[str, Any],
            _acknowledged_order: dict[str, Any],
            *,
            _snapshot_index: int = snapshot_index,
        ) -> None:
            old_snapshot_line = raw_lines[_snapshot_index]
            raw_lines[_snapshot_index] = _persist_ack_transition(
                _QUEUE_PATH,
                old_snapshot_line,
                acknowledged_entry,
            )

        success, order, reason, ex_used = _try_retry(
            entry,
            allow_submit=allow_submit,
            on_ack=_durable_ack,
        )
        if success:
            assert order is not None
            _log(f"RETRY_SUCCESS: {entry['symbol']} {reason} order_id={order.get('id', '?')}")
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
                _fin = {"protection": None, "journal": False, "verified": False}
                _log(f"RETRY_FINALIZE_FAIL: {entry['symbol']} {str(_fexc)[:120]}")
                _audit_unverified_fill(entry, order, f"finalizer exception: {str(_fexc)[:120]}")
            if not _fin.get("verified"):
                entry["last_retry_reason"] = "fill_evidence_unverified"
                keep_lines.append(json.dumps(entry, default=str) + "\n")
                stats["retry_again"] += 1
                _log(
                    f"RETRY_HELD_UNVERIFIED: {entry['symbol']} attempts={attempts} "
                    "journal/protection YOK"
                )
                continue

            if not _fin.get("finalized") or _fin.get("protection") != "placed":
                finalize_attempts = int(entry.get("finalize_attempts", 0)) + 1
                entry["finalize_attempts"] = finalize_attempts
                entry["last_retry_reason"] = str(
                    _fin.get("failure_reason") or "protection_not_placed"
                )
                entry["last_verified_fill_qty"] = _fin.get("fill_qty")
                entry["last_verified_fill_price"] = _fin.get("avg_px")
                keep_lines.append(json.dumps(entry, default=str) + "\n")
                stats["retry_again"] += 1
                _log(
                    f"RETRY_HELD_UNPROTECTED: {entry['symbol']} "
                    f"finalize_attempts={finalize_attempts} reason={entry['last_retry_reason']}"
                )
                continue

            stats["success"] += 1
            try:
                _MISSED_PATH.parent.mkdir(parents=True, exist_ok=True)
                audit = dict(entry)
                audit["retry_resolved_at"] = datetime.now(UTC).isoformat()
                audit["resolved_order_id"] = str(order.get("id", ""))
                audit["resolved_fill_price"] = float(_fin["avg_px"])
                audit["resolved_fill_qty"] = float(_fin["fill_qty"])
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
                    f"order_id={order.get('id', '?')} — SL/TP={_fin.get('protection')} "
                    f"journal={_fin.get('journal')}",
                    source="pending_retry_processor",
                )
            except Exception:
                pass
            continue
        else:
            # Transient/OPEN/UNKNOWN reconciliation is never permission to
            # drop or increment into a fresh order. Hold the same intent.
            if reason.startswith("reconcile_uncertain"):
                entry["terminal_no_fill_confirmations"] = 0
                entry["last_retry_reason"] = reason
                keep_lines.append(json.dumps(entry, default=str) + "\n")
                _log(f"RETRY_HELD_UNCERTAIN: {entry['symbol']} reason={reason}")
                stats["retry_again"] += 1
                continue

            if reason == "submit_disabled_after_terminal_reconcile":
                required = terminal_confirmations_required
                confirmations = terminal_confirmations
                if confirmations < required:
                    confirmations += 1
                entry["terminal_no_fill_confirmations"] = confirmations
                entry["last_retry_reason"] = reason
                if confirmations < required:
                    keep_lines.append(json.dumps(entry, default=str) + "\n")
                    stats["retry_again"] += 1
                    _log(
                        f"RECONCILE_ONLY_TERMINAL_CONFIRM: {entry['symbol']} "
                        f"{confirmations}/{required}"
                    )
                    continue
                if not reconcile_only and terminal_confirmations < required:
                    # Persist the second terminal observation. A possible new
                    # -rN submit happens only on a later run, which reconciles
                    # once more before submitting.
                    keep_lines.append(json.dumps(entry, default=str) + "\n")
                    stats["retry_again"] += 1
                    _log(
                        f"TERMINAL_CONFIRM_READY: {entry['symbol']} "
                        f"{confirmations}/{required} — next run may submit"
                    )
                    continue
                if reconcile_only:
                    terminal_reason = (
                        "acknowledged_submit_terminal_no_fill "
                        f"({confirmations}/{required} confirmations)"
                    )
                    _push_missed(entry, terminal_reason)
                    stats["dropped_terminal"] += 1
                    _log(f"DROPPED_TERMINAL_NO_FILL: {entry['symbol']} {terminal_reason}")
                    continue

            # Once all candidate ids are proven absent/terminal, normal stale
            # and max-attempt policies may finally drop the intent.
            if age_block_reason is not None:
                _log(f"DROPPED_AGE: {entry['symbol']} {age_block_reason}")
                _push_missed(entry, age_block_reason)
                stats["dropped_age"] += 1
                continue
            if attempts_exhausted:
                _log(f"DROPPED_ATTEMPTS: {entry['symbol']} attempts={attempts}")
                _push_missed(entry, f"max_attempts_reached ({attempts})")
                stats["dropped_attempts"] += 1
                continue

            # A submit timeout consumed an attempt and its coid was persisted;
            # the next scheduler run must discover it before any new submit.
            next_attempts = attempts + 1
            entry["attempts"] = next_attempts
            if reason.startswith("order_submit_uncertain"):
                entry["terminal_no_fill_confirmations"] = 0
            entry["last_retry_reason"] = reason
            keep_lines.append(json.dumps(entry, default=str) + "\n")
            _log(f"RETRY_AGAIN: {entry['symbol']} attempts={next_attempts} reason={reason}")
            stats["retry_again"] += 1

    _commit_processed_snapshot(_QUEUE_PATH, raw_lines, keep_lines)
    return stats


def process_pending() -> dict[str, int]:
    """Own one whole-process lease across both finalization and entry queues."""
    with _processor_lease(_QUEUE_PATH) as acquired:
        if not acquired:
            combined = _new_stats()
            combined["busy"] = 1
            _log("PROCESSOR_BUSY: another pending-retry processor owns the lease")
            return combined
        combined = _new_stats()
        _merge_stats(combined, _process_protection_finalizations_leased())
        _merge_stats(combined, _process_pending_leased())
    return combined


def main() -> int:
    stats = process_pending()
    _log(f"DONE: {json.dumps(stats)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
