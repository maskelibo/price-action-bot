"""Legacy daily futures scanner — execution is disabled; dry-run only.

Spot testnet'in (testnet.binance.vision) tam tersi:
  - testnet.binancefuture.com hesabi
  - LONG + SHORT (margin var)
  - Leverage 1-125x (biz 3x kullaniyoruz, balanced preset)
  - TP/SL ayri ayri yerlestirilir (TAKE_PROFIT_MARKET + STOP_MARKET)
  - reduceOnly=True → sadece pozisyonu kapatir
  - Backtest mantiginin %100'u burada calisir

The old daily submit path predates the crash-complete entry/protection WAL used
by the 15m daemon.  It must not place orders: an exchange timeout or a filled
order whose average is not yet visible cannot be safely finalized here.

Usage:
    python scripts/futures_trade_daily.py --dry-run [--days 1]
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import io
import json
import logging
import math
import os
import re
import stat
import sys
import tempfile
import threading
import time
import uuid
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MethodType

_MOD_LOG = logging.getLogger(__name__)

# sys.stdout wrapping sadece __main__'de (import durumunda Streamlit'i bozar)
if __name__ == "__main__":
    with contextlib.suppress(Exception):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

os.environ["PA_LOG_QUIET"] = "1"
warnings.filterwarnings("ignore")

import duckdb  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# .env load (python-dotenv: quote+comment trim, mevcut env korunur)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from price_action.runtime_paths import resolve_runtime_root  # noqa: E402

RUNTIME_ROOT = resolve_runtime_root(ROOT)
DATA_DIR = RUNTIME_ROOT / "data"
LOGS_DIR = RUNTIME_ROOT / "logs"
MARKET_DB = (
    Path(os.environ.get("DUCKDB_PATH", str(DATA_DIR / "market.duckdb"))).expanduser().resolve()
)

import ccxt  # noqa: E402
import yaml  # noqa: E402

from price_action.contracts import Position  # noqa: E402
from price_action.execution.capital_cap import load_capital_cap  # noqa: E402
from price_action.execution.post_only_router import (  # noqa: E402
    SlippageExceededError,
    place_post_only_with_fallback,
)
from scripts.lib.cooldown import filter_signals_by_cooldown  # noqa: E402
from scripts.lib.degraded_reads import record_degraded_read  # noqa: E402
from scripts.lib.risk_integration import (  # noqa: E402
    build_futures_account_state,
    build_returns_df,
    build_signal_from_scan,
    load_risk_officer,
)
from scripts.paper_trade_daily import init_journal, scan_signals  # noqa: E402


class LegacyDailyExecutionDisabledError(RuntimeError):
    """Raised before any exchange/order I/O on the non-durable daily path."""


class PrivateExchangeAccessDisabledError(RuntimeError):
    """Raised before credentials/client creation in read-only orchestrators."""


_LEGACY_DAILY_EXECUTION_DISABLED_REASON = (
    "legacy daily futures execution is disabled: it has no crash-complete "
    "entry/protection WAL; use the v15p2 15m daemon or --dry-run"
)

# Multi-bot futures support — PA_BOT_NAME env var (atlas | phoenix | rsi2 | vwap | …)
# FIX 2026-05-27 (Faz 14.26): generic — herhangi bir bot adı per-bot journal alır.
# Önceki bug: rsi2/vwap (ve diğer yeni bot'lar) else dalına düşüp LIVE journal'a
# yazıyordu → DuckDB lock conflict, journal init fail, kritik veri kaybı riski.
_BOT_NAME = os.environ.get("PA_BOT_NAME", "").lower().strip()
if _BOT_NAME == "atlas":
    JOURNAL = DATA_DIR / "futures_journal_atlas.duckdb"
    RISK_YAML = ROOT / "configs" / "risk_atlas_v203.yaml"
    BREAKER_STATE = LOGS_DIR / "risk" / "futures_breaker_state_atlas.json"
elif _BOT_NAME == "phoenix":
    JOURNAL = DATA_DIR / "futures_journal_phoenix.duckdb"
    RISK_YAML = ROOT / "configs" / "risk_phoenix_v204.yaml"
    BREAKER_STATE = LOGS_DIR / "risk" / "futures_breaker_state_phoenix.json"
elif _BOT_NAME and _BOT_NAME not in ("default", ""):
    # Generic: PA_BOT_NAME=rsi2 → futures_journal_rsi2.duckdb
    # RISK_YAML burada placeholder (15m daemon PA_15M_CONFIG'ten okuyor, bu sadece 1d için)
    JOURNAL = DATA_DIR / f"futures_journal_{_BOT_NAME}.duckdb"
    RISK_YAML = ROOT / "configs" / "risk_balanced.yaml"
    BREAKER_STATE = LOGS_DIR / "risk" / f"futures_breaker_state_{_BOT_NAME}.json"
else:
    JOURNAL = DATA_DIR / "futures_journal.duckdb"
    RISK_YAML = ROOT / "configs" / "risk_balanced.yaml"
    BREAKER_STATE = LOGS_DIR / "risk" / "futures_breaker_state.json"
BREAKER_STATE.parent.mkdir(parents=True, exist_ok=True)
print(
    f"[futures_trade_daily] BOT={_BOT_NAME or 'default'} | journal={JOURNAL.name} | risk={RISK_YAML.name}"
)

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "DOT/USDT",
    "DOGE/USDT",
    "XRP/USDT",
]
# Fallback sabitler — artık RiskOfficer/risk_balanced.yaml'dan okunuyor.
# Sadece dry-run printlerinde gösterilmek için tutuluyor.
LEVERAGE = 3
RISK_PCT = 0.04
MAX_NOTIONAL_PCT = 0.30

_BINANCE_BAN_RE = re.compile(r"banned until\s+(\d{10,16})", re.IGNORECASE)
_BINANCE_BAN_UNTIL_MS = 0
_BINANCE_BAN_LOCK = threading.Lock()
_BINANCE_BAN_STATE_PATH = DATA_DIR / "state" / "binance_rest_ban_until_ms"
_BINANCE_BAN_STATE_LOCK_PATH = DATA_DIR / "state" / "binance_rest_ban_until_ms.lock"
_TIME_DIFFERENCE_MS: float | None = None
_TIME_DIFFERENCE_SYNCED_MONO = 0.0
_TIME_DIFFERENCE_TTL_SEC = 3600.0


def _validate_binance_ban_state_dir() -> Path:
    """Return the private state dir without following a symlink alias."""
    state_dir = _BINANCE_BAN_STATE_PATH.parent
    state_dir.mkdir(parents=True, exist_ok=True)
    info = state_dir.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"unsafe Binance ban state directory: {state_dir}")
    if _BINANCE_BAN_STATE_LOCK_PATH.parent != state_dir:
        raise ValueError("Binance ban state and lock must share one directory")
    return state_dir


def _validate_binance_ban_file(path: Path, *, field: str) -> os.stat_result | None:
    """Reject aliases: shared cooldown metadata must be a single-link file."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"unsafe {field}: {path}")
    if info.st_nlink != 1:
        raise ValueError(f"hard-linked {field} is not allowed: {path}")
    return info


def _extract_binance_ban_until_ms(exc: BaseException | str) -> int | None:
    """Binance ``-1003`` metnindeki epoch-ms ban sonunu ayıkla."""
    match = _BINANCE_BAN_RE.search(str(exc))
    if not match:
        return None
    try:
        value = int(match.group(1))
    except ValueError:
        return None
    return value if value > 0 else None


def _fsync_binance_ban_state_dir() -> None:
    """Persist state-file rename/unlink metadata before releasing the lock."""
    state_dir = _validate_binance_ban_state_dir()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(state_dir, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _remove_binance_ban_state_unlocked() -> None:
    """Remove invalid/expired state while the stable file lock is held."""
    if _validate_binance_ban_file(_BINANCE_BAN_STATE_PATH, field="Binance ban state") is None:
        return
    _BINANCE_BAN_STATE_PATH.unlink(missing_ok=True)
    _fsync_binance_ban_state_dir()


def _read_binance_ban_state_unlocked(now_ms: int) -> int:
    """Read active shared state; corruption blocks requests fail-closed."""
    expected = _validate_binance_ban_file(_BINANCE_BAN_STATE_PATH, field="Binance ban state")
    if expected is None:
        return 0
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(_BINANCE_BAN_STATE_PATH, flags)
    except FileNotFoundError:
        return 0
    try:
        opened = os.fstat(fd)
        current = _BINANCE_BAN_STATE_PATH.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise ValueError("Binance ban state changed while opening")
        with os.fdopen(fd, "r", encoding="ascii") as handle:
            fd = -1
            raw = handle.read().strip()
    finally:
        if fd >= 0:
            os.close(fd)
    try:
        until_ms = int(raw)
    except (TypeError, ValueError):
        raise ValueError("invalid Binance ban state; refusing private REST request") from None
    if until_ms <= now_ms:
        _remove_binance_ban_state_unlocked()
        return 0
    return until_ms


def _write_binance_ban_state_unlocked(until_ms: int) -> None:
    """Atomically persist one non-secret epoch-ms value under the file lock."""
    state_dir = _validate_binance_ban_state_dir()
    _validate_binance_ban_file(_BINANCE_BAN_STATE_PATH, field="Binance ban state")
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed before atomic replace
        mode="w",
        encoding="ascii",
        prefix=f".{_BINANCE_BAN_STATE_PATH.name}.",
        dir=state_dir,
        delete=False,
    )
    try:
        tmp.write(f"{int(until_ms)}\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, _BINANCE_BAN_STATE_PATH)
        _fsync_binance_ban_state_dir()
    except Exception:
        tmp.close()
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp.name)
        raise


@contextlib.contextmanager
def _binance_ban_state_lock():
    """Cross-process lock with a stable inode; the lock file is never replaced."""
    import fcntl

    _validate_binance_ban_state_dir()
    expected = _validate_binance_ban_file(_BINANCE_BAN_STATE_LOCK_PATH, field="Binance ban lock")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(_BINANCE_BAN_STATE_LOCK_PATH, flags, 0o600)
    with os.fdopen(fd, "a+", encoding="ascii") as lock_file:
        opened = os.fstat(lock_file.fileno())
        current = _BINANCE_BAN_STATE_LOCK_PATH.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise ValueError("Binance ban lock changed while opening")
        if expected is None:
            _fsync_binance_ban_state_dir()
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _effective_binance_ban_until_ms(*, now_ms: int | None = None) -> int:
    """Return max(local, shared) and clear expired state safely."""
    global _BINANCE_BAN_UNTIL_MS
    current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    with _BINANCE_BAN_LOCK:
        local_until_ms = _BINANCE_BAN_UNTIL_MS
        if local_until_ms <= current_ms:
            local_until_ms = 0
        with _binance_ban_state_lock():
            shared_until_ms = _read_binance_ban_state_unlocked(current_ms)
        effective_until_ms = max(local_until_ms, shared_until_ms)
        _BINANCE_BAN_UNTIL_MS = effective_until_ms
        return effective_until_ms


def _record_binance_ban_until_ms(until_ms: int, *, now_ms: int | None = None) -> int:
    """Persist the monotonic max ban deadline for all local bot processes."""
    global _BINANCE_BAN_UNTIL_MS
    current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    candidate_ms = int(until_ms)
    with _BINANCE_BAN_LOCK:
        local_until_ms = _BINANCE_BAN_UNTIL_MS
        if local_until_ms <= current_ms:
            local_until_ms = 0
        # Install the process-local circuit breaker before any filesystem I/O.
        # A full/read-only disk may prevent cross-process persistence, but must
        # not permit this process to issue a second request during the ban.
        local_candidate_ms = max(local_until_ms, candidate_ms)
        _BINANCE_BAN_UNTIL_MS = local_candidate_ms if local_candidate_ms > current_ms else 0
        with _binance_ban_state_lock():
            shared_until_ms = _read_binance_ban_state_unlocked(current_ms)
            effective_until_ms = max(local_until_ms, shared_until_ms, candidate_ms)
            _BINANCE_BAN_UNTIL_MS = effective_until_ms if effective_until_ms > current_ms else 0
            if effective_until_ms > current_ms and effective_until_ms != shared_until_ms:
                _write_binance_ban_state_unlocked(effective_until_ms)
        return _BINANCE_BAN_UNTIL_MS


def _binance_cooldown_remaining_seconds(*, now_ms: int | None = None) -> float:
    """Yerel ve paylaşılan REST banının kalan süresi."""
    current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    until_ms = _effective_binance_ban_until_ms(now_ms=current_ms)
    return max((until_ms - current_ms) / 1000.0, 0.0)


def get_binance_ban_until() -> float:
    """Return the active shared Binance ban deadline as Unix epoch seconds."""
    return _effective_binance_ban_until_ms() / 1000.0


def _install_binance_cooldown_guard(exchange):
    """İlk 418'den sonra ban dolana kadar yeni HTTP isteğini yerelde kes.

    Binance, ban sürerken gelen her yeni istekte pencereyi uzatabiliyor. Daemon
    aynı bar içinde birden çok hesap endpoint'i kullandığı için tek 418'in
    ardından kalan çağrılar ağa çıkmamalı. CCXT'nin dinamik endpoint'leri
    ``self.request`` çağırdığından instance-seviyesi sarmal yeterlidir.
    """
    original_request = exchange.request

    def _guarded_request(
        self,
        path,
        api="public",
        method="GET",
        params=None,
        headers=None,
        body=None,
        config=None,
    ):
        del self
        remaining = _binance_cooldown_remaining_seconds()
        if remaining > 0:
            with _BINANCE_BAN_LOCK:
                until_ms = _BINANCE_BAN_UNTIL_MS
            raise ccxt.RateLimitExceeded(
                f"binance local cooldown active for {remaining:.1f}s (banned until {until_ms})"
            )
        try:
            return original_request(
                path,
                api,
                method,
                params or {},
                headers,
                body,
                config or {},
            )
        except Exception as exc:
            until_ms = _extract_binance_ban_until_ms(exc)
            if until_ms is not None:
                try:
                    _record_binance_ban_until_ms(until_ms)
                except Exception as persist_exc:
                    _MOD_LOG.error(
                        "binance cooldown shared-state persistence failed; "
                        "process-local ban remains active: %s",
                        str(persist_exc)[:160],
                    )
            raise

    exchange.request = MethodType(_guarded_request, exchange)
    return exchange


def get_futures_exchange():
    """Binance USDM Futures Testnet ccxt instance.

    NOT: ccxt 4.5+ set_sandbox_mode futures icin deprecated, manuel URL override.
    """
    if os.getenv("PA_DISABLE_PRIVATE_EXCHANGE_API", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        # CEO/research orchestrators must not compete with the sole live-trade
        # owner for private REST quota.  Fail before reading credentials,
        # constructing CCXT (which may load markets/time), or touching network.
        raise PrivateExchangeAccessDisabledError(
            "private Binance exchange access disabled for this process "
            "(PA_DISABLE_PRIVATE_EXCHANGE_API=1)"
        )
    api_key = os.getenv("BINANCE_FUTURES_TESTNET_API_KEY")
    api_secret = os.getenv("BINANCE_FUTURES_TESTNET_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError(".env'de BINANCE_FUTURES_TESTNET_API_KEY/SECRET yok")
    ex = ccxt.binance(
        {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "future",
                "warnOnFetchOpenOrdersWithoutSymbol": False,
                "adjustForTimeDifference": True,
                "recvWindow": 10000,
                "fetchMarkets": ["linear"],  # sadece USDM futures, sapi/spot atla
            },
        }
    )
    _install_binance_cooldown_guard(ex)

    # Manuel testnet URL override (sandbox mode futures icin deprecated)
    testnet_fapi = "https://testnet.binancefuture.com/fapi"
    for ver, suffix in [
        ("fapiPublic", "/v1"),
        ("fapiPublicV2", "/v2"),
        ("fapiPublicV3", "/v3"),
        ("fapiPrivate", "/v1"),
        ("fapiPrivateV2", "/v2"),
        ("fapiPrivateV3", "/v3"),
    ]:
        ex.urls["api"][ver] = testnet_fapi + suffix
    # ccxt fetch_currencies sapi.binance.com (mainnet) cagiriyor — testnet key reject ediliyor
    ex.has["fetchCurrencies"] = False
    # Time sync cache: daemon her bar birden çok exchange instance'ı açabilir;
    # her instance için server-time endpoint'ine vurmak gereksiz REST ağırlığıdır.
    global _TIME_DIFFERENCE_MS, _TIME_DIFFERENCE_SYNCED_MONO
    now_mono = time.monotonic()
    if (
        _TIME_DIFFERENCE_MS is not None
        and now_mono - _TIME_DIFFERENCE_SYNCED_MONO < _TIME_DIFFERENCE_TTL_SEC
    ):
        ex.options["timeDifference"] = _TIME_DIFFERENCE_MS
    else:
        with contextlib.suppress(Exception):
            diff = ex.load_time_difference()
            _TIME_DIFFERENCE_MS = float(diff)
            _TIME_DIFFERENCE_SYNCED_MONO = time.monotonic()
    return ex


# FIX 2026-05-28 (Faz 14.27 ORTA C5): Explicit schema versioning.
# Önceki bug: schema migration implicit (CREATE TABLE IF NOT EXISTS) →
# yeni kolon eklenmesi sessizce başarısız oluyordu eski DB'lerde.
# Şimdi: schema_version tablosu + migration kayıt.
_JOURNAL_SCHEMA_VERSION = 3  # 2026-05-31 — futures_partial_closes + partial-aware PnL


def init_futures_journal():
    con = duckdb.connect(str(JOURNAL))
    # Schema version meta tablosu
    con.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            migrated_at TIMESTAMP,
            notes VARCHAR
        )
    """)
    # Mevcut version oku
    try:
        cur_ver = con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    except Exception:
        cur_ver = None
    if cur_ver is None or cur_ver < _JOURNAL_SCHEMA_VERSION:
        # Migration kayıt — INSERT OR IGNORE: eski version satırları PK çakışır
        from datetime import datetime as _dt

        with contextlib.suppress(Exception):
            con.execute(
                "INSERT OR IGNORE INTO schema_version VALUES (?, ?, ?)",
                [
                    _JOURNAL_SCHEMA_VERSION,
                    _dt.now(UTC),
                    f"2026-05-31 partial-closes schema v{_JOURNAL_SCHEMA_VERSION}",
                ],
            )
    con.execute("""
        CREATE TABLE IF NOT EXISTS futures_signals (
            signal_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            symbol VARCHAR,
            strategy VARCHAR,
            side VARCHAR,
            sl_price DOUBLE,
            tp_price DOUBLE,
            confluence DOUBLE,
            leverage INTEGER,
            status VARCHAR,
            order_id VARCHAR,
            fill_price DOUBLE,
            fill_qty DOUBLE,
            notional_usdt DOUBLE,
            margin_usdt DOUBLE,
            notes VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS futures_protection_orders (
            prot_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            signal_id VARCHAR,
            symbol VARCHAR,
            side VARCHAR,
            qty DOUBLE,
            tp_price DOUBLE,
            sl_price DOUBLE,
            tp_order_id VARCHAR,
            sl_order_id VARCHAR,
            status VARCHAR,
            notes VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS futures_equity_snapshots (
            snapshot_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            wallet_balance DOUBLE,
            unrealized_pnl DOUBLE,
            margin_balance DOUBLE,
            available_balance DOUBLE,
            n_positions INTEGER,
            n_open_orders INTEGER,
            notes VARCHAR
        )
    """)
    # SEC26.B-3 + SEC26.B-4: Closed-trade journal (consecutive loss counter + realized PnL).
    # Canonical writer: src/price_action/execution/trade_journal.TradeJournal.
    # Schema buradaki CREATE TradeJournal._ensure_schema() ile birebir tutuluyor.
    # CREATE IF NOT EXISTS idempotent — TradeJournal init aynı tabloyu yaratırsa konflikt yok.
    con.execute("""
        CREATE TABLE IF NOT EXISTS futures_trades_closed (
            trade_id TEXT PRIMARY KEY,
            ts_open TIMESTAMP,
            ts_close TIMESTAMP,
            sym TEXT,
            side TEXT,
            strategy TEXT,
            entry_price DOUBLE,
            exit_price DOUBLE,
            qty DOUBLE,
            realized_pnl_usdt DOUBLE,
            realized_r DOUBLE,
            win BOOLEAN,
            close_reason TEXT
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_ftc_close_ts ON futures_trades_closed (ts_close)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ftc_sym ON futures_trades_closed (sym)")
    # 2026-05-31: Kısmi TP dilimleri için yeni tablo (partial-aware close model).
    # Semantik: TP1/TP2 partial fill → buraya yaz. Final runner kapanışı → trades_closed.
    # PnL sorguları her iki tabloyu toplar (çift sayım yok).
    con.execute("""
        CREATE TABLE IF NOT EXISTS futures_partial_closes (
            close_id TEXT PRIMARY KEY,
            trade_id TEXT NOT NULL,
            ts_close TIMESTAMP,
            sym TEXT,
            side TEXT,
            strategy TEXT,
            qty_closed DOUBLE,
            exit_price DOUBLE,
            realized_pnl_usdt DOUBLE,
            realized_r DOUBLE,
            close_reason TEXT
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_fpc_trade_id ON futures_partial_closes (trade_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_fpc_ts_close ON futures_partial_closes (ts_close)")
    con.commit()
    con.close()


def _binance_order_scope_symbol(value: object) -> str:
    """Normalize CCXT/journal spellings to Binance's ``BTCUSDT`` form."""
    symbol = str(value or "").strip().upper()
    if ":" in symbol:
        symbol = symbol.split(":", 1)[0]
    return symbol.replace("/", "").replace("-", "")


def _read_live_order_scope(
    *,
    journal_path: Path,
    pending_queue_path: Path,
    protection_queue_path: Path,
) -> dict[str, object]:
    """Read the complete local ownership scope before querying open orders.

    The global Binance ``openOrders`` and ``openAlgoOrders`` endpoints cost 40
    request-weight each when called without a symbol.  The daemon already owns
    exact symbol evidence in its journal and crash-recovery queues, so steady
    state queries only those symbols.  A missing queue means "no queued work";
    an unreadable/malformed queue or journal means UNKNOWN and must prevent
    order-state-dependent entry/mutation for that tick.
    """
    if not journal_path.is_file():
        raise FileNotFoundError(f"journal scope source missing: {journal_path}")

    con = duckdb.connect(str(journal_path), read_only=True)
    try:
        protection_rows = con.execute(
            """SELECT DISTINCT symbol
                 FROM futures_protection_orders
                WHERE status = 'placed'"""
        ).fetchall()
        open_signal_rows = con.execute(
            """SELECT DISTINCT symbol
                 FROM futures_signals
                WHERE status = 'filled'
                  AND signal_id NOT IN (
                      SELECT trade_id FROM futures_trades_closed
                  )"""
        ).fetchall()
    finally:
        con.close()

    protection_symbols = {
        normalized
        for (raw_symbol,) in protection_rows
        if (normalized := _binance_order_scope_symbol(raw_symbol))
    }
    journal_open_symbols = {
        normalized
        for (raw_symbol,) in open_signal_rows
        if (normalized := _binance_order_scope_symbol(raw_symbol))
    }

    from scripts.process_pending_entries import _read_queue_snapshot

    pending_symbols: set[str] = set()
    protection_queue_symbols: set[str] = set()
    for queue_path, destination in (
        (pending_queue_path, pending_symbols),
        (protection_queue_path, protection_queue_symbols),
    ):
        for line_no, raw_line in enumerate(_read_queue_snapshot(queue_path), start=1):
            try:
                row = json.loads(raw_line)
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"malformed order-scope queue {queue_path.name}:{line_no}"
                ) from exc
            if not isinstance(row, dict):
                raise ValueError(f"non-object order-scope queue {queue_path.name}:{line_no}")
            symbol = _binance_order_scope_symbol(row.get("symbol"))
            if not symbol:
                raise ValueError(f"missing order-scope symbol {queue_path.name}:{line_no}")
            destination.add(symbol)

    return {
        "protection_symbols": protection_symbols,
        "journal_open_symbols": journal_open_symbols,
        "pending_symbols": pending_symbols,
        "protection_queue_symbols": protection_queue_symbols,
    }


def _scoped_open_orders(
    exchange,
    *,
    method_name: str,
    symbols: set[str],
) -> list[dict]:
    """Fetch one-weight symbol-scoped order lists; partial results are invalid."""
    if not symbols:
        return []
    method = getattr(exchange, method_name)
    collected: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for symbol in sorted(symbols):
        response = method({"symbol": symbol})
        rows = response.get("orders") if isinstance(response, dict) else response
        if not isinstance(rows, list):
            raise TypeError(f"{method_name}({symbol}) did not return a list")
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError(f"{method_name}({symbol}) returned a non-object order")
            primary_id = str(
                row.get("algoId") or row.get("orderId") or row.get("id") or ""
            )
            client_id = str(row.get("clientOrderId") or row.get("clientAlgoId") or "")
            if not primary_id and not client_id:
                raise ValueError(f"{method_name}({symbol}) returned an identity-less order")
            identity = (
                str(row.get("symbol") or symbol),
                primary_id,
                client_id,
            )
            if identity in seen:
                continue
            seen.add(identity)
            collected.append(row)
    return collected


def fetch_futures_state(
    exchange,
    *,
    journal_path: Path | str | None = None,
    pending_queue_path: Path | str | None = None,
    protection_queue_path: Path | str | None = None,
):
    """Futures testnet account state with symbol-scoped, fail-closed order reads."""
    raw = exchange.fapiPrivateV2GetAccount()
    wallet = float(raw.get("totalWalletBalance", 0))
    unrealized = float(raw.get("totalUnrealizedProfit", 0))
    margin_bal = float(raw.get("totalMarginBalance", wallet))
    available = float(raw.get("availableBalance", 0))

    # A3 fix: rate-limit ban'de (binance 418) silently boş liste dönerse pos_check
    # "tüm pozisyonlar kapanmış" sanıp journal'a yanlış 'filled' yazıyordu.
    # Şimdi her endpoint için 'ok' flag tutuyoruz; consumer rate-limit'te skip eder.
    positions_ok = True
    try:
        positions = exchange.fetch_positions()
        active_pos = [p for p in positions if abs(float(p.get("contracts", 0))) > 0]
    except Exception as _pos_exc:
        # KALAN_ISLER #8 (2026-07-10): görünürlük-only — dönüş birebir aynı ([]).
        record_degraded_read("fetch_futures_state.fetch_positions", _pos_exc)
        active_pos = []
        positions_ok = False

    scope_journal = Path(journal_path) if journal_path is not None else JOURNAL
    scope_pending = (
        Path(pending_queue_path)
        if pending_queue_path is not None
        else DATA_DIR / "pending_retries.jsonl"
    )
    scope_protection_queue = (
        Path(protection_queue_path)
        if protection_queue_path is not None
        else DATA_DIR / "protection_finalizations.jsonl"
    )
    order_scope_ok = positions_ok
    order_scope_error: str | None = None
    order_scope: dict[str, object] = {
        "protection_symbols": set(),
        "journal_open_symbols": set(),
        "pending_symbols": set(),
        "protection_queue_symbols": set(),
    }
    if positions_ok:
        try:
            order_scope = _read_live_order_scope(
                journal_path=scope_journal,
                pending_queue_path=scope_pending,
                protection_queue_path=scope_protection_queue,
            )
        except Exception as _scope_exc:
            order_scope_ok = False
            order_scope_error = f"{type(_scope_exc).__name__}: {str(_scope_exc)[:180]}"
            record_degraded_read("fetch_futures_state.order_scope", _scope_exc)

    active_position_symbols = {
        normalized
        for position in active_pos
        if (normalized := _binance_order_scope_symbol(position.get("symbol")))
    }
    pending_symbols = set(order_scope["pending_symbols"])
    regular_scope_symbols = set(pending_symbols)
    algo_scope_symbols = (
        active_position_symbols
        | set(order_scope["protection_symbols"])
        | set(order_scope["journal_open_symbols"])
        | pending_symbols
        | set(order_scope["protection_queue_symbols"])
    )

    # There is no steady-state global regular-order query.  Only a durable
    # pending-entry owner can justify symbol-scoped regular openOrders reads.
    regular_orders: list[dict] = []
    regular_orders_ok = order_scope_ok
    if regular_orders_ok:
        try:
            regular_orders = _scoped_open_orders(
                exchange,
                method_name="fapiPrivateGetOpenOrders",
                symbols=regular_scope_symbols,
            )
        except Exception as _oo_exc:
            record_degraded_read("fetch_futures_state.open_orders", _oo_exc)
            regular_orders = []
            regular_orders_ok = False

    algo_orders: list[dict] = []
    algo_orders_ok = order_scope_ok
    if algo_orders_ok:
        try:
            algo_orders = _scoped_open_orders(
                exchange,
                method_name="fapiPrivateGetOpenAlgoOrders",
                symbols=algo_scope_symbols,
            )
        except Exception as _ao_exc:
            record_degraded_read("fetch_futures_state.open_algo_orders", _ao_exc)
            algo_orders = []
            algo_orders_ok = False

    # SEC-#3A: totalInitialMargin — pozisyon stale dedektörü için gerekli.
    # fetch_positions() boş dönse bile borsada açık pozisyon varsa bu değer > 0.
    # "pozisyonlar boş AMA initialMargin > 0" = stale veri, giriş atlanmalı.
    total_initial_margin = float(raw.get("totalInitialMargin", 0))

    exchange_state_complete = bool(
        positions_ok and order_scope_ok and regular_orders_ok and algo_orders_ok
    )
    return {
        "wallet_balance": wallet,
        "unrealized_pnl": unrealized,
        "margin_balance": margin_bal,
        "available_balance": available,
        "total_initial_margin": total_initial_margin,
        "n_positions": len(active_pos),
        "n_open_orders": len(regular_orders) + len(algo_orders),
        "n_regular_orders": len(regular_orders),
        "n_algo_orders": len(algo_orders),
        "positions": active_pos,
        "algo_orders": algo_orders,
        "positions_ok": positions_ok,
        "regular_orders_ok": regular_orders_ok,
        "algo_orders_ok": algo_orders_ok,
        "order_scope_ok": order_scope_ok,
        "order_scope_error": order_scope_error,
        "orders_state": "ok" if exchange_state_complete else "unknown",
        "exchange_state_complete": exchange_state_complete,
        "regular_order_scope_symbols": sorted(regular_scope_symbols),
        "algo_order_scope_symbols": sorted(algo_scope_symbols),
        "journal_open_position_symbols": sorted(order_scope["journal_open_symbols"]),
    }


def _futures_state_entry_trusted(state: object) -> bool:
    """Return true only for a complete, internally consistent entry snapshot."""
    if not isinstance(state, dict):
        return False
    if state.get("exchange_state_complete") is not True:
        return False
    if state.get("positions_ok") is not True:
        return False
    positions = state.get("positions")
    if not isinstance(positions, list):
        return False
    try:
        initial_margin = float(state.get("total_initial_margin", 0))
    except (TypeError, ValueError):
        return False
    if not math.isfinite(initial_margin) or initial_margin < 0:
        return False
    # Account says margin is in use while the position list says flat: stale.
    return bool(positions) or initial_margin == 0


def setup_leverage(exchange, symbol: str, leverage: int):
    """Sym icin leverage set et (idempotent)."""
    try:
        exchange.set_leverage(leverage, symbol)
        return True
    except Exception as e:
        # Already set ise OK
        if "No need to change" in str(e) or "leverage not modified" in str(e).lower():
            return True
        print(f"    [LEV] {symbol} set_leverage fail: {str(e)[:100]}")
        return False


def _is_margin_error(exc: Exception) -> bool:
    """Borsa hatasının margin/yetersiz fon kaynakli olup olmadığını kontrol et.

    SEC58-M6: ccxt InsufficientFunds + Binance -2019 (margin insufficient) +
    -1100 (invalid qty at lower leverage) yakalanir.
    """
    msg = str(exc).lower()
    margin_keywords = (
        "insufficient",
        "margin",
        "balance",
        "-2019",  # binance: insufficient margin
        "-1100",  # binance: qty precision / margin at lower leverage
        "notional must be no smaller",
        "not enough",
    )
    return any(kw in msg for kw in margin_keywords)


def _submit_order_with_adaptive_leverage(
    exchange,
    symbol: str,
    order_side: str,
    qty: float,
    base_leverage: int,
    *,
    post_only_enabled: bool = False,
    post_only_timeout_sec: int = 30,
    slippage_limit_bps: float = 25.0,
    target_price: float | None = None,
    client_order_id: str | None = None,
) -> tuple[dict, int, str]:
    """Market/post-only emir gönder; margin hatası varsa leverage düşür ve yeniden dene.

    SEC58-M6: Cascade: base_leverage → 2x → 1x (3 deneme max).
    Her denemede setup_leverage() + emir. Başarıda (order, kullanılan_lev, method) döner.
    Hiçbiri başaramadıysa son exception raise.

    Args:
        exchange: ccxt exchange instance.
        symbol: "BTC/USDT"
        order_side: "buy" | "sell"
        qty: base miktarı (leverage'dan bağımsız — notional değişmez).
        base_leverage: RiskOfficer'dan gelen ilk leverage teklifi.
        post_only_enabled: SEC26.B-5 flag.
        post_only_timeout_sec: post-only timeout.
        slippage_limit_bps: market fallback slip cap.
        target_price: post-only için hedef fiyat (None → caller'ın cur_px'i kullanılır).
        client_order_id: deterministic exchange identity; post-only için zorunlu.

    Returns:
        (order_dict, leverage_used, order_method)

    Raises:
        Exception: tüm cascade başarısız oldu.
    """
    # Cascade dizisi: istenen leverage'dan geriye doğru 1x'e kadar
    # Örnek: base=3 → [3, 2, 1]; base=1 → [1]
    cascade = list(dict.fromkeys([base_leverage, 2, 1]))  # deduped, sıralı azalan
    cascade = [lv for lv in cascade if 1 <= lv <= base_leverage]

    last_exc: Exception | None = None
    for attempt_lev in cascade:
        setup_leverage(exchange, symbol, attempt_lev)
        try:
            if post_only_enabled and target_price is not None:
                if not client_order_id:
                    raise ValueError(
                        "post-only daily submit requires deterministic client_order_id"
                    )
                order, method = place_post_only_with_fallback(
                    exchange,
                    symbol=symbol,
                    side=order_side,
                    qty=qty,
                    target_price=target_price,
                    fallback_after_sec=post_only_timeout_sec,
                    slippage_limit_bps=slippage_limit_bps,
                    client_order_id=client_order_id,
                )
            else:
                order = exchange.create_market_order(symbol, order_side, qty)
                method = "market_only"

            if attempt_lev != base_leverage:
                print(
                    f"    [LEV_CASCADE] {symbol} leverage {base_leverage}x→{attempt_lev}x "
                    f"(margin insufficient retry #{cascade.index(attempt_lev) + 1})"
                )
            return order, attempt_lev, method
        except SlippageExceededError:
            # Slippage aşımı — leverage cascade değil, direkt raise
            raise
        except Exception as exc:
            last_exc = exc
            if _is_margin_error(exc) and attempt_lev > 1:
                print(
                    f"    [LEV_CASCADE] {symbol} margin err at {attempt_lev}x, "
                    f"trying lower... ({str(exc)[:80]})"
                )
                continue
            # Margin dışı hata — direkt raise, cascade yok
            raise

    # Tüm cascade tükendi
    assert last_exc is not None
    raise last_exc


# F2 FIX 2026-07-10 (DERIN_DENETIM F2 CRIT): TP merdiveni doğrulanan kanona
# sabitlendi. KAYNAK-PIN: backtest engine default'ları (engine.py:75-78
# tp1_R=1.0/tp2_R=1.5/close_pct=0.30) + exit_tournament_verdict §6 primary reco
# + v15p2'nin 2 Tem robustness doğrulaması AYNI merdivenle koştu. Eski canlı
# kurulum (%25 qty sig.tp_price'a[2-2.5R!] + %25 1.5R'ye + %50 runner) hiçbir
# modelde backtest'lenmemişti — 'TP1' etiketi uzak emirdeydi, merdiven tersti,
# ts30 çıpası ('tp1' fill'i) fiilen hiç başlamıyordu.
TP1_R = 1.0
TP2_R = 1.5
TP1_FRAC = 0.30
TP2_FRAC = 0.30  # kalan %40 runner: trailing (daemon position_check)


def compute_partial_tp_prices(
    side: str,
    entry_price: float,
    sl_price: float,
    tp1_r: float = TP1_R,
    tp2_r: float = TP2_R,
) -> tuple[float, float]:
    """Doğrulanmış TP merdiveni: (TP1, TP2) = entry ± (1R, 1.5R).

    R = |entry − SL|. Strateji ham hedefi (sig.tp_price) BURADA KULLANILMAZ —
    o yalnız legacy single-TP modda ve observability'de (strategy_tp_price) yaşar.
    """
    sl_dist = abs(entry_price - sl_price)
    if side == "long":
        return (entry_price + tp1_r * sl_dist, entry_price + tp2_r * sl_dist)
    return (entry_price - tp1_r * sl_dist, entry_price - tp2_r * sl_dist)


_PROTECTION_KEY_RE = re.compile(r"PAp[0-9a-f]{24}")
_PROTECTION_TERMINAL_FAILURES = {"CANCELED", "CANCELLED", "EXPIRED", "REJECTED"}
_PROTECTION_TERMINAL_FILLS = {"CLOSED", "FILLED", "FINISHED", "TRIGGERED"}


def _make_protection_key(
    *,
    symbol: str,
    side: str,
    mode: str,
    legs: list[tuple[str, str, str, str]],
    protection_key: str | None,
) -> str:
    """Build a Binance-safe replay key without exposing caller-owned IDs.

    A returned key can be persisted and passed back verbatim.  Callers that have
    a stable entry intent/order ID should pass it on the first call; legacy
    callers fall back to a fingerprint of the precision-normalized protection
    intent, which still makes an immediate finalize retry deterministic.
    """
    supplied = str(protection_key or "").strip()
    if _PROTECTION_KEY_RE.fullmatch(supplied):
        return supplied
    if supplied:
        seed = ("protection-intent-v1", supplied)
    else:
        seed = ("protection-semantic-v1", symbol, side, mode, *legs)
    digest = uuid.uuid5(uuid.NAMESPACE_URL, repr(seed)).hex[:24]
    return f"PAp{digest}"


def _is_protection_order_not_found(exc: BaseException) -> bool:
    """Only a definitive missing-order result permits a new leg submission."""
    if isinstance(exc, ccxt.OrderNotFound):
        return True
    message = " ".join(str(exc).lower().split())
    compact = message.replace("_", "").replace(" ", "")
    return (
        "ordernotfound" in compact
        or "order does not exist" in message
        or "unknown order sent" in message
        or "-2013" in message
    )


def _protection_order_value(order: dict, *names: str):
    info = order.get("info") if isinstance(order.get("info"), dict) else {}
    for name in names:
        if order.get(name) is not None:
            return order[name]
        if info.get(name) is not None:
            return info[name]
    return None


def _protection_order_id(order: dict) -> str:
    value = _protection_order_value(order, "id", "algoId", "orderId")
    return "" if value is None else str(value)


def _validate_protection_order(
    order: dict,
    *,
    client_order_id: str,
    order_type: str,
    close_side: str,
    amount: str,
    stop_price: str,
) -> str:
    """Validate available exchange fields before reusing a reconciled leg."""
    order_id = _protection_order_id(order)
    if not order_id:
        raise RuntimeError(f"protection reconcile returned no order id for {client_order_id}")

    existing_client_id = _protection_order_value(
        order, "clientOrderId", "clientAlgoId", "origClientOrderId"
    )
    if existing_client_id is not None and str(existing_client_id) != client_order_id:
        raise RuntimeError(f"protection client id mismatch for {client_order_id}")

    status = str(_protection_order_value(order, "status", "algoStatus") or "").upper()
    if status in _PROTECTION_TERMINAL_FAILURES:
        raise RuntimeError(f"protection leg {client_order_id} is terminal status={status.lower()}")
    if status in _PROTECTION_TERMINAL_FILLS:
        raise RuntimeError(
            f"protection leg {client_order_id} already executed status={status.lower()}"
        )

    existing_type = _protection_order_value(order, "type", "orderType")
    if existing_type is not None and str(existing_type).upper() != order_type.upper():
        raise RuntimeError(f"protection type mismatch for {client_order_id}")
    existing_side = _protection_order_value(order, "side")
    if existing_side is not None and str(existing_side).upper() != close_side.upper():
        raise RuntimeError(f"protection side mismatch for {client_order_id}")

    existing_amount = _protection_order_value(order, "amount", "quantity")
    if existing_amount is not None and float(existing_amount) != float(amount):
        raise RuntimeError(f"protection amount mismatch for {client_order_id}")
    existing_stop = _protection_order_value(order, "triggerPrice", "stopPrice")
    if existing_stop is not None and float(existing_stop) != float(stop_price):
        raise RuntimeError(f"protection trigger mismatch for {client_order_id}")
    existing_reduce_only = _protection_order_value(order, "reduceOnly")
    if existing_reduce_only is not None and str(existing_reduce_only).lower() not in {
        "1",
        "true",
    }:
        raise RuntimeError(f"protection reduceOnly mismatch for {client_order_id}")
    return order_id


def _fetch_protection_order(exchange, symbol: str, client_order_id: str) -> dict | None:
    """Reconcile a Binance conditional order by its deterministic client ID."""
    fetch_order = getattr(exchange, "fetch_order", None)
    if not callable(fetch_order):
        # Backward-compatible for simple paper/stub exchanges. Real CCXT
        # exchanges expose fetch_order and therefore always reconcile first.
        return None
    try:
        order = fetch_order(
            None,
            symbol,
            params={
                "conditional": True,
                "clientAlgoId": client_order_id,
                # Compatibility alias; CCXT maps this to clientAlgoId when
                # ``conditional`` is true, while older adapters key on it.
                "origClientOrderId": client_order_id,
            },
        )
    except Exception as exc:
        if _is_protection_order_not_found(exc):
            return None
        raise RuntimeError(
            f"protection reconcile uncertain for {client_order_id}: "
            f"{type(exc).__name__}: {str(exc)[:120]}"
        ) from exc
    if not isinstance(order, dict):
        raise RuntimeError(f"protection reconcile returned invalid order for {client_order_id}")
    return order


def _ensure_protection_leg(
    exchange,
    *,
    symbol: str,
    close_side: str,
    leg_name: str,
    order_type: str,
    amount: str,
    stop_price: str,
    client_order_id: str,
) -> dict:
    """Return one existing/created leg; never create after uncertain lookup."""

    def _reconciled(order: dict, source: str) -> dict:
        order_id = _validate_protection_order(
            order,
            client_order_id=client_order_id,
            order_type=order_type,
            close_side=close_side,
            amount=amount,
            stop_price=stop_price,
        )
        return {
            "client_order_id": client_order_id,
            "order_id": order_id,
            "source": source,
        }

    existing = _fetch_protection_order(exchange, symbol, client_order_id)
    if existing is not None:
        return _reconciled(existing, "reconciled")

    params = {
        "stopPrice": stop_price,
        "reduceOnly": True,
        "workingType": "MARK_PRICE",
        "newClientOrderId": client_order_id,
    }
    try:
        created = exchange.create_order(
            symbol=symbol,
            type=order_type,
            side=close_side,
            amount=float(amount),
            params=params,
        )
    except Exception as create_exc:
        # The submit may have reached Binance before a timeout. Reconcile the
        # same deterministic ID once before reporting failure; never resubmit.
        try:
            existing = _fetch_protection_order(exchange, symbol, client_order_id)
        except Exception as reconcile_exc:
            raise RuntimeError(
                f"{leg_name} submit/reconcile uncertain: {type(create_exc).__name__}: "
                f"{str(create_exc)[:80]}; {str(reconcile_exc)[:100]}"
            ) from create_exc
        if existing is not None:
            return _reconciled(existing, "reconciled_after_submit_error")
        raise create_exc

    if not isinstance(created, dict) or not _protection_order_id(created):
        existing = _fetch_protection_order(exchange, symbol, client_order_id)
        if existing is None:
            raise RuntimeError(f"{leg_name} submit returned no durable order identity")
        return _reconciled(existing, "reconciled_after_submit")
    return _reconciled(created, "created")


def ensure_original_level_sl(
    exchange,
    *,
    symbol: str,
    side: str,
    qty: float,
    sl_price: float,
    protection_key: str,
) -> dict:
    """Best-effort deterministic SL when the full plan cannot be constructed.

    The supplied entry key resolves to the same protection key used by the full
    plan, so a later WAL replay reconciles this SL instead of creating another.
    No TP side effect is attempted here.
    """
    try:
        normalized_side = str(side).strip().lower()
        if normalized_side not in {"long", "short"}:
            raise ValueError("emergency SL side must be long or short")
        amount = str(exchange.amount_to_precision(symbol, float(qty)))
        stop_price = str(exchange.price_to_precision(symbol, float(sl_price)))
        if not math.isfinite(float(amount)) or float(amount) <= 0:
            raise ValueError("emergency SL quantity is invalid")
        if not math.isfinite(float(stop_price)) or float(stop_price) <= 0:
            raise ValueError("emergency SL price is invalid")
        resolved_key = _make_protection_key(
            symbol=str(symbol),
            side=normalized_side,
            mode="multi_target",
            legs=[],
            protection_key=protection_key,
        )
        state = _ensure_protection_leg(
            exchange,
            symbol=str(symbol),
            close_side="SELL" if normalized_side == "long" else "BUY",
            leg_name="sl",
            order_type="STOP_MARKET",
            amount=amount,
            stop_price=stop_price,
            client_order_id=f"{resolved_key}sl",
        )
        return {
            "status": "sl_placed_only",
            "protection_key": resolved_key,
            "client_order_ids": {"sl": f"{resolved_key}sl"},
            "sl_order_id": state["order_id"],
            "sl_price": float(stop_price),
            "qty_sl": float(amount),
        }
    except Exception as exc:
        return {
            "status": "error",
            "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
            "failed_leg": "sl",
        }


def _protection_plan_hash(plan: dict) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_protection_plan(
    exchange,
    *,
    symbol: str,
    side: str,
    qty: float,
    tp_price: float,
    sl_price: float,
    entry_price: float | None = None,
    protection_key: str | None = None,
) -> dict:
    """Freeze one precision-normalized, replay-safe protection intent.

    The plan contains no credentials and performs no exchange submit/fetch.  It
    is safe to fsync before any protection side effect and replay after restart.
    SL is deliberately the first leg; TP creation cannot precede a durable stop.
    """
    normalized_side = str(side).strip().lower()
    if normalized_side not in {"long", "short"}:
        raise ValueError("protection side must be long or short")
    values = {"qty": qty, "tp_price": tp_price, "sl_price": sl_price}
    if entry_price is not None:
        values["entry_price"] = entry_price
    for field, value in values.items():
        parsed = float(value)
        if not math.isfinite(parsed) or parsed <= 0:
            raise ValueError(f"protection {field} must be finite and > 0")

    normalized_symbol = str(symbol).strip()
    if not normalized_symbol:
        raise ValueError("protection symbol must be non-empty")
    close_side = "SELL" if normalized_side == "long" else "BUY"
    mode = "multi_target" if entry_price is not None and float(entry_price) > 0 else "single_target"
    qty_full = str(exchange.amount_to_precision(normalized_symbol, float(qty)))
    sl_stop = str(exchange.price_to_precision(normalized_symbol, float(sl_price)))
    if float(qty_full) <= 0 or float(sl_stop) <= 0:
        raise ValueError("precision-normalized full SL quantity/price is zero")
    if mode == "multi_target":
        assert entry_price is not None
        tp1_price, tp2_price = compute_partial_tp_prices(
            normalized_side, float(entry_price), float(sl_price)
        )
        qty_tp1 = str(exchange.amount_to_precision(normalized_symbol, float(qty) * TP1_FRAC))
        qty_tp2 = str(exchange.amount_to_precision(normalized_symbol, float(qty) * TP2_FRAC))
        tp1_stop = str(exchange.price_to_precision(normalized_symbol, tp1_price))
        tp2_stop = str(exchange.price_to_precision(normalized_symbol, tp2_price))
        if all(float(value) > 0 for value in (qty_tp1, qty_tp2, tp1_stop, tp2_stop)):
            leg_specs = [
                ("sl", "STOP_MARKET", qty_full, sl_stop),
                ("tp1", "TAKE_PROFIT_MARKET", qty_tp1, tp1_stop),
                ("tp2", "TAKE_PROFIT_MARKET", qty_tp2, tp2_stop),
            ]
            outputs = {
                "tp_price": float(tp1_stop),
                "tp2_price": float(tp2_stop),
                "sl_price": float(sl_stop),
                "qty_tp1": float(qty_tp1),
                "qty_tp2": float(qty_tp2),
                "qty_sl": float(qty_full),
                "strategy_tp_price": float(tp_price),
            }
        else:
            # Small positions can have valid full quantity while 30% rounds to
            # zero.  Downgrade deterministically to a full-qty single TP; a
            # zero partial leg must never block the valid SL.
            mode = "single_target"
            tp_stop = str(exchange.price_to_precision(normalized_symbol, float(tp_price)))
            if float(tp_stop) <= 0:
                raise ValueError("precision-normalized fallback TP price is zero")
            leg_specs = [
                ("sl", "STOP_MARKET", qty_full, sl_stop),
                ("tp", "TAKE_PROFIT_MARKET", qty_full, tp_stop),
            ]
            outputs = {
                "tp_price": float(tp_stop),
                "sl_price": float(sl_stop),
                "qty_sl": float(qty_full),
                "strategy_tp_price": float(tp_price),
                "precision_fallback": "single_target",
            }
    else:
        tp_stop = str(exchange.price_to_precision(normalized_symbol, float(tp_price)))
        leg_specs = [
            ("sl", "STOP_MARKET", qty_full, sl_stop),
            ("tp", "TAKE_PROFIT_MARKET", qty_full, tp_stop),
        ]
        outputs = {
            "tp_price": float(tp_stop),
            "sl_price": float(sl_stop),
            "qty_sl": float(qty_full),
            "strategy_tp_price": float(tp_price),
        }

    resolved_key = _make_protection_key(
        symbol=normalized_symbol,
        side=normalized_side,
        mode=mode,
        legs=leg_specs,
        protection_key=protection_key,
    )
    legs = [
        {
            "name": name,
            "order_type": order_type,
            "amount": amount,
            "stop_price": stop,
            "client_order_id": f"{resolved_key}{name}",
        }
        for name, order_type, amount, stop in leg_specs
    ]
    plan = {
        "schema_version": 1,
        "mode": mode,
        "symbol": normalized_symbol,
        "side": normalized_side,
        "close_side": close_side,
        "quantity": float(qty),
        "entry_price": float(entry_price) if entry_price is not None else None,
        "strategy_tp_price": float(tp_price),
        "original_sl_price": float(sl_price),
        "protection_key": resolved_key,
        "legs": legs,
        "outputs": outputs,
    }
    plan["plan_sha256"] = _protection_plan_hash(plan)
    return _validated_protection_plan(plan)


def _validated_protection_plan(plan: dict) -> dict:
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        raise ValueError("invalid protection plan schema")
    if plan.get("plan_sha256") != _protection_plan_hash(plan):
        raise ValueError("protection plan hash mismatch")
    mode = plan.get("mode")
    expected_names = ["sl", "tp1", "tp2"] if mode == "multi_target" else ["sl", "tp"]
    if mode not in {"multi_target", "single_target"}:
        raise ValueError("invalid protection plan mode")
    side = plan.get("side")
    if side not in {"long", "short"}:
        raise ValueError("invalid protection plan side")
    expected_close = "SELL" if side == "long" else "BUY"
    if plan.get("close_side") != expected_close:
        raise ValueError("protection plan close side mismatch")
    key = str(plan.get("protection_key") or "")
    if not _PROTECTION_KEY_RE.fullmatch(key):
        raise ValueError("invalid protection plan key")
    legs = plan.get("legs")
    if (
        not isinstance(legs, list)
        or [leg.get("name") for leg in legs if isinstance(leg, dict)] != expected_names
    ):
        raise ValueError("invalid protection plan leg order")
    expected_types = {
        "sl": "STOP_MARKET",
        "tp": "TAKE_PROFIT_MARKET",
        "tp1": "TAKE_PROFIT_MARKET",
        "tp2": "TAKE_PROFIT_MARKET",
    }
    for leg in legs:
        if not isinstance(leg, dict):
            raise ValueError("invalid protection plan leg")
        name = str(leg["name"])
        if leg.get("order_type") != expected_types[name]:
            raise ValueError(f"protection plan type mismatch for {name}")
        if leg.get("client_order_id") != f"{key}{name}":
            raise ValueError(f"protection plan client id mismatch for {name}")
        for field in ("amount", "stop_price"):
            value = float(leg[field])
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"protection plan {name}.{field} must be finite and > 0")
    if not isinstance(plan.get("outputs"), dict) or not str(plan.get("symbol") or "").strip():
        raise ValueError("invalid protection plan outputs/symbol")
    return plan


def validate_protection_plan_for_intent(
    exchange,
    protection_plan: dict,
    *,
    symbol: str,
    side: str,
    qty: float,
    tp_price: float,
    sl_price: float,
    entry_price: float | None,
    protection_key: str | None,
) -> dict:
    """Bind a stored plan to its external entry intent and canonical legs.

    ``plan_sha256`` only detects accidental mutation: anyone able to edit a WAL
    row could otherwise change a leg and recompute that self-hash.  Rebuilding
    from independently stored fill/strategy facts plus the entry client-order
    id proves quantities, prices, order types, leg order and every protection
    client id are the canonical values before an exchange side effect.
    """
    plan = _validated_protection_plan(protection_plan)
    expected = build_protection_plan(
        exchange,
        symbol=symbol,
        side=side,
        qty=qty,
        tp_price=tp_price,
        sl_price=sl_price,
        entry_price=entry_price,
        protection_key=protection_key,
    )
    canonical_plan = json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False)
    canonical_expected = json.dumps(
        expected,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if not hmac.compare_digest(canonical_plan, canonical_expected):
        raise ValueError("protection plan semantic intent mismatch")
    return plan


def protection_plan_intent_binding_sha256(
    protection_plan: dict,
    *,
    entry_client_order_id: str,
    symbol: str,
    side: str,
    qty: float,
    entry_price: float,
    tp_price: float,
    sl_price: float,
) -> str:
    """Bind every canonical leg to independent WAL entry/fill facts.

    The plan is precision-validated once before its first fsync.  Replay then
    verifies this binding instead of rebuilding with potentially changed
    exchange precision or strategy constants.
    """
    plan = _validated_protection_plan(protection_plan)
    normalized_coid = str(entry_client_order_id).strip()
    normalized_symbol = str(symbol).strip()
    normalized_side = str(side).strip().lower()
    if not normalized_coid or not normalized_symbol or normalized_side not in {"long", "short"}:
        raise ValueError("invalid protection binding identity")
    intent_values = {
        "qty": float(qty),
        "entry_price": float(entry_price),
        "tp_price": float(tp_price),
        "sl_price": float(sl_price),
    }
    if any(not math.isfinite(value) or value <= 0 for value in intent_values.values()):
        raise ValueError("invalid protection binding numeric intent")
    payload = {
        "schema_version": 1,
        "entry_client_order_id": normalized_coid,
        "symbol": normalized_symbol,
        "side": normalized_side,
        **intent_values,
        # Includes plan hash, canonical amounts/prices/order types, outputs and
        # deterministic leg client IDs. A recomputed plan self-hash alone can
        # therefore never authorize changed side effects.
        "protection_plan": plan,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _protection_result(plan: dict, states: dict[str, dict], *, status: str) -> dict:
    partial_ids = {
        name: state.get("order_id") for name, state in states.items() if state.get("order_id")
    }
    outputs = dict(plan["outputs"])
    result = {
        "status": status,
        "mode": plan["mode"],
        "protection_key": plan["protection_key"],
        "plan_sha256": plan["plan_sha256"],
        "client_order_ids": {leg["name"]: leg["client_order_id"] for leg in plan["legs"]},
        "legs": states,
        "leg_order_ids": partial_ids,
        "tp_order_id": partial_ids.get("tp1") or partial_ids.get("tp"),
        "tp2_order_id": partial_ids.get("tp2"),
        "sl_order_id": partial_ids.get("sl"),
        **outputs,
    }
    return result


def execute_protection_plan(exchange, protection_plan: dict) -> dict:
    """Execute/reconcile one pinned plan, always SL before any TP leg."""
    states: dict[str, dict] = {}
    failed_leg: str | None = None
    try:
        plan = _validated_protection_plan(protection_plan)
        states = {
            leg["name"]: {
                "client_order_id": leg["client_order_id"],
                "order_id": None,
                "source": "pending",
            }
            for leg in plan["legs"]
        }
        for leg in plan["legs"]:
            failed_leg = str(leg["name"])
            states[failed_leg] = _ensure_protection_leg(
                exchange,
                symbol=str(plan["symbol"]),
                close_side=str(plan["close_side"]),
                leg_name=failed_leg,
                order_type=str(leg["order_type"]),
                amount=str(leg["amount"]),
                stop_price=str(leg["stop_price"]),
                client_order_id=str(leg["client_order_id"]),
            )
        return _protection_result(plan, states, status="placed")
    except Exception as exc:
        if failed_leg is not None and failed_leg in states:
            states[failed_leg]["source"] = "error"
        if "plan" not in locals():
            return {
                "status": "error",
                "mode": "unknown",
                "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
                "failed_leg": failed_leg,
                "legs": states,
            }
        result = _protection_result(plan, states, status="error")
        result.update(
            {
                "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
                "failed_leg": failed_leg,
            }
        )
        return result


def ensure_protection_plan_sl(exchange, protection_plan: dict) -> dict:
    """Emergency path used only when the durable WAL cannot be written."""
    try:
        plan = _validated_protection_plan(protection_plan)
        leg = plan["legs"][0]
        if leg["name"] != "sl":
            raise ValueError("protection plan is not SL-first")
        state = _ensure_protection_leg(
            exchange,
            symbol=str(plan["symbol"]),
            close_side=str(plan["close_side"]),
            leg_name="sl",
            order_type=str(leg["order_type"]),
            amount=str(leg["amount"]),
            stop_price=str(leg["stop_price"]),
            client_order_id=str(leg["client_order_id"]),
        )
        states = {
            candidate["name"]: {
                "client_order_id": candidate["client_order_id"],
                "order_id": state["order_id"] if candidate["name"] == "sl" else None,
                "source": state["source"] if candidate["name"] == "sl" else "not_attempted",
            }
            for candidate in plan["legs"]
        }
        return _protection_result(plan, states, status="sl_placed_only")
    except Exception as exc:
        return {
            "status": "error",
            "mode": "unknown",
            "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
            "failed_leg": "sl",
            "legs": {},
        }


def place_protection_orders(
    exchange,
    symbol: str,
    side: str,
    qty: float,
    tp_price: float,
    sl_price: float,
    entry_price: float | None = None,
    protection_key: str | None = None,
    protection_plan: dict | None = None,
) -> dict:
    """Build or replay the canonical SL-first TP/SL plan."""
    try:
        if protection_plan is None:
            plan = build_protection_plan(
                exchange,
                symbol=symbol,
                side=side,
                qty=qty,
                tp_price=tp_price,
                sl_price=sl_price,
                entry_price=entry_price,
                protection_key=protection_key,
            )
        else:
            # A persisted plan is immutable replay input.  Validate schema/hash
            # and bind it to independently stored intent facts, but never
            # recompute with current TP constants or exchange precision.
            plan = _validated_protection_plan(protection_plan)
            normalized_side = str(side).lower()
            if str(plan["symbol"]) != str(symbol) or plan["side"] != normalized_side:
                raise ValueError("pinned protection plan identity mismatch")
            if not math.isclose(float(plan["quantity"]), float(qty), rel_tol=1e-12):
                raise ValueError("pinned protection plan quantity mismatch")
            if not math.isclose(float(plan["strategy_tp_price"]), float(tp_price), rel_tol=1e-12):
                raise ValueError("pinned protection plan strategy TP mismatch")
            if not math.isclose(float(plan["original_sl_price"]), float(sl_price), rel_tol=1e-12):
                raise ValueError("pinned protection plan SL mismatch")
            expected_entry = float(entry_price) if entry_price is not None else None
            if plan["entry_price"] != expected_entry:
                raise ValueError("pinned protection plan entry mismatch")
            expected_key = _make_protection_key(
                symbol=str(symbol),
                side=normalized_side,
                mode=str(plan["mode"]),
                legs=[],
                protection_key=protection_key,
            )
            if plan["protection_key"] != expected_key:
                raise ValueError("pinned protection plan key mismatch")
        return execute_protection_plan(exchange, plan)
    except Exception as exc:
        return {
            "status": "error",
            "mode": "unknown",
            "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
            "failed_leg": None,
            "legs": {},
        }


def submit_to_futures(
    signals: list[dict],
    dry_run: bool = False,
    max_pos_usdt: float | None = None,
    execution_cfg: dict | None = None,
) -> int:
    """Sinyalleri Binance USDM Futures Testnet'e gönder.

    LONG ve SHORT ikisi de calisir (margin var).
    Risk-based sizing: notional = (equity * RISK_PCT) / sl_distance_pct
    Cap: notional <= equity * MAX_NOTIONAL_PCT

    Args:
        execution_cfg: configs/risk_balanced.yaml -> execution: bolumu.
                       SEC26.B-5 post-only limit gate (default DISABLED).
                       {
                         'post_only_limit_enabled': bool (default False),
                         'post_only_fallback_seconds': int (default 30),
                         'slippage_limit_bps': float (default 25.0),
                       }
    """
    # This legacy surface has no durable submit-intent/finalize queue.  Refuse
    # before exchange construction, balance reads, leverage changes or order
    # HTTP calls.  Environment flags and an empty batch cannot bypass this
    # safety boundary or make a non-dry invocation appear supported.
    if not dry_run:
        raise LegacyDailyExecutionDisabledError(_LEGACY_DAILY_EXECUTION_DISABLED_REASON)

    if not signals:
        print("[SUBMIT] Sinyal yok, atlandı.")
        return 0

    # SEC26.B-5 — execution config (default OFF, replay etkisi sifir)
    execution_cfg = execution_cfg or {}
    post_only_enabled = bool(execution_cfg.get("post_only_limit_enabled", False))
    post_only_timeout_sec = int(
        execution_cfg.get(
            "post_only_fallback_seconds",
            execution_cfg.get("fallback_to_market_after_sec", 30),
        )
    )
    slippage_limit_bps = float(
        execution_cfg.get(
            "slippage_limit_bps",
            execution_cfg.get("max_slippage_bps", 25.0),
        )
    )
    if post_only_enabled:
        print(
            f"[EXECUTION] POST-ONLY enabled: timeout={post_only_timeout_sec}s, "
            f"slippage_limit={slippage_limit_bps:.1f}bps"
        )
    else:
        print("[EXECUTION] MARKET-ONLY (post-only disabled, sec26.b-5 paper test pending)")

    exchange = get_futures_exchange()
    state = fetch_futures_state(exchange)
    print(
        f"\n[SUBMIT] Futures hesap: wallet=${state['wallet_balance']:.2f}, "
        f"available=${state['available_balance']:.2f}, "
        f"unrealized={state['unrealized_pnl']:+.2f}, "
        f"pozisyon={state['n_positions']}, açik order={state['n_open_orders']}"
    )

    if dry_run:
        print(f"\n[DRY-RUN] {len(signals)} sinyal LOG ONLY:")
        for s in signals:
            print(
                f"  {s['ts'].strftime('%Y-%m-%d')} {s['symbol']:<10} {s['strategy']:<35} {s['side']:<5}"
            )
        if max_pos_usdt is not None:
            print(
                f"[DRY-RUN][CAPITAL_CAP] enabled=True max={max_pos_usdt:.1f} USDT — "
                f"live'da bu sınır her emir için kontrol edilir"
            )
        return 0

    # ===== RiskOfficer entegrasyonu =====
    # Backtest +canlı parity: aynı YAML, aynı gate'ler, aynı breaker.
    risk_officer = load_risk_officer(yaml_path=RISK_YAML, breaker_state_path=BREAKER_STATE)
    open_sym_names = [p.get("symbol", "") for p in state.get("positions", []) or []]
    return_universe = sorted({*SYMBOLS, *(s for s in open_sym_names if s)})
    returns_df = build_returns_df(return_universe, days=90, market_db=MARKET_DB)
    account = build_futures_account_state(state, journal_path=JOURNAL)
    breaker_snap = risk_officer.breaker.snapshot(account)
    print(
        f"[RISK] equity=${account.equity_usdt:.2f}, free=${account.free_margin_usdt:.2f}, "
        f"open_pos={len(account.open_positions)}, pnl_today=${account.realized_pnl_today:+.2f}, "
        f"breakers={ {k: v for k, v in breaker_snap.items() if v} or 'clear' }"
    )

    submitted = 0
    rejected = 0
    con = duckdb.connect(str(JOURNAL))

    for s in signals:
        sig_id = uuid.uuid4().hex[:16]
        sym = s["symbol"]

        if sym not in SYMBOLS:
            print(f"  [SKIP] {sym} symbol list'te yok")
            continue

        # SEC26.A FIX — Stale signal guard
        # Sinyal bar tarihi bugünden 2 günden eskiyse REJECT.
        # Backtest bar_ts = bar kapanış günü (UTC). Paper scan = dünkü gün (target_date = now - 1d).
        # Tolerans: 2 gün (1 gün bar close lag + 1 gün buffer).
        # 7 gün eski sinyal: piyasa o tarihten bu yana hareket etmiş → entry/SL anlamını yitirdi.
        try:
            sig_ts = s.get("ts")
            if sig_ts is not None:
                if hasattr(sig_ts, "tzinfo"):
                    sig_date = (
                        sig_ts.date() if hasattr(sig_ts, "date") else sig_ts.to_pydatetime().date()
                    )
                else:
                    sig_date = pd.Timestamp(sig_ts).date()
                today_utc = datetime.now(UTC).date()
                stale_days = (today_utc - sig_date).days
                if stale_days > 2:
                    rejected += 1
                    print(
                        f"  [REJECT-STALE] {sym:<10} {s['strategy']:<25} "
                        f"signal_age={stale_days}d (sig_ts={sig_date}, today={today_utc})"
                    )
                    con.execute(
                        """
                        INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            sig_id,
                            s["ts"],
                            sym,
                            s["strategy"],
                            s["side"],
                            float(s["sl_price"]),
                            float(s["tp_price"]),
                            float(s["confluence"]),
                            0,
                            "reject:stale_signal",
                            None,
                            None,
                            None,
                            None,
                            None,
                            f"age={stale_days}d>2d",
                        ),
                    )
                    continue
        except Exception as stale_err:
            print(f"  [WARN] stale check err {sym}: {stale_err}")

        try:
            ticker = exchange.fetch_ticker(sym)
            cur_px = ticker["last"]

            # 1) Signal contract + RiskOfficer.evaluate
            try:
                signal_obj = build_signal_from_scan(s, venue="binance")
            except Exception as build_err:
                print(f"  [SKIP-CONTRACT] {sym} signal_build_fail: {build_err}")
                continue

            decision = risk_officer.evaluate(
                signal_obj,
                account,
                market_price=cur_px,
                returns_df=returns_df,
            )

            if not hasattr(decision, "quantity"):
                # Reject — Risk Officer reddetti
                reject_reason = getattr(decision, "reason", "unknown")
                reject_detail = getattr(decision, "detail", {}) or {}
                rejected += 1
                print(
                    f"  [REJECT-RISK] {sym:<10} {s['strategy']:<25} {reject_reason} {reject_detail}"
                )
                con.execute(
                    """
                    INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        sig_id,
                        s["ts"],
                        sym,
                        s["strategy"],
                        s["side"],
                        float(s["sl_price"]),
                        float(s["tp_price"]),
                        float(s["confluence"]),
                        0,
                        f"reject:{reject_reason}",
                        None,
                        None,
                        None,
                        None,
                        None,
                        str(reject_detail)[:200],
                    ),
                )
                continue

            # 2) RiskedOrder — quantity ve leverage RiskOfficer'dan
            risked = decision
            qty = float(risked.quantity)
            notional = float(risked.notional_usdt)
            leverage_used = max(1, min(5, round(risked.leverage))) or 1
            margin = notional / leverage_used if leverage_used > 0 else notional

            # 2b) Capital cap kontrolü — kısmi gönderme YOK, tamamen reddet
            if max_pos_usdt is not None and notional > max_pos_usdt:
                rejected += 1
                print(
                    f"  [REJECT-CAP] {sym:<10} {s['strategy']:<25} "
                    f"notional=${notional:.2f} > cap=${max_pos_usdt:.2f} USDT"
                )
                con.execute(
                    """
                    INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        sig_id,
                        s["ts"],
                        sym,
                        s["strategy"],
                        s["side"],
                        float(s["sl_price"]),
                        float(s["tp_price"]),
                        float(s["confluence"]),
                        leverage_used,
                        "reject:capital_cap_exceeded",
                        None,
                        None,
                        None,
                        notional,
                        margin,
                        f"cap={max_pos_usdt:.2f}",
                    ),
                )
                continue

            # 3) Margin check (RiskOfficer free_margin'i hesapladı ama broker side ek check)
            if margin > state["available_balance"] * 0.9:
                rejected += 1
                print(
                    f"  [SKIP-MARGIN] {sym} need=${margin:.2f}, have=${state['available_balance']:.2f}"
                )
                con.execute(
                    """
                    INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        sig_id,
                        s["ts"],
                        sym,
                        s["strategy"],
                        s["side"],
                        float(s["sl_price"]),
                        float(s["tp_price"]),
                        float(s["confluence"]),
                        leverage_used,
                        "reject:broker_margin",
                        None,
                        None,
                        None,
                        notional,
                        margin,
                        None,
                    ),
                )
                continue

            # 4) Leverage + order
            # SEC58-M6: setup_leverage artık _submit_order_with_adaptive_leverage
            # içinde yapılıyor. Adaptive cascade: base_lev → 2x → 1x on margin error.
            order_side = "buy" if s["side"] == "long" else "sell"
            order_method = "market_only"

            try:
                order, leverage_used, order_method = _submit_order_with_adaptive_leverage(
                    exchange,
                    sym,
                    order_side,
                    qty,
                    leverage_used,
                    post_only_enabled=post_only_enabled,
                    post_only_timeout_sec=post_only_timeout_sec,
                    slippage_limit_bps=slippage_limit_bps,
                    target_price=cur_px,
                    client_order_id=f"PA1D_{sig_id}",
                )
                # leverage_used cascade sonrası güncellenmiş olabilir → notional / margin yeniden
                margin = notional / leverage_used if leverage_used > 0 else notional
            except SlippageExceededError as slip_err:
                rejected += 1
                print(f"  [REJECT-SLIPPAGE] {sym:<10} {s['strategy']:<25} {slip_err}")
                con.execute(
                    """
                    INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sig_id,
                        s["ts"],
                        sym,
                        s["strategy"],
                        s["side"],
                        float(s["sl_price"]),
                        float(s["tp_price"]),
                        float(s["confluence"]),
                        leverage_used,
                        f"reject:slippage_exceeded:{slip_err.slippage_bps:.1f}bps",
                        None,
                        None,
                        None,
                        notional,
                        margin,
                        f"limit={slippage_limit_bps:.1f}bps,actual={slip_err.slippage_bps:.1f}bps",
                    ),
                )
                continue

            submitted += 1
            filled_qty = float(order.get("filled", qty))
            avg_px = float(order.get("average", cur_px))
            slippage_breach = order.get("slippage_breach")
            execution_notes = None
            if isinstance(slippage_breach, dict):
                execution_notes = (
                    f"entry_fill_method={order_method}"
                    f" slippage_breach_bps={float(slippage_breach['slippage_bps']):.6f}"
                    f" slippage_limit_bps={float(slippage_breach['limit_bps']):.6f}"
                    " disposition=protect_position position_owned=true"
                    " protection_required=true unwind_attempted=false"
                )

            print(
                f"  [{s['side'].upper()}] {sym:<10} {s['strategy']:<25} "
                f"qty={filled_qty:.4f} notional=${notional:.2f} margin=${margin:.2f} "
                f"fill=${avg_px:.4f} lev={leverage_used}x conf={s['confluence']:.2f} id={order['id']} "
                f"method={order_method}"
            )

            con.execute(
                """
                INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    sig_id,
                    s["ts"],
                    sym,
                    s["strategy"],
                    s["side"],
                    float(s["sl_price"]),
                    float(s["tp_price"]),
                    float(s["confluence"]),
                    leverage_used,
                    "filled",
                    str(order["id"]),
                    avg_px,
                    filled_qty,
                    notional,
                    margin,
                    execution_notes,
                ),
            )

            # 5) Protection orders (SEC26.A: multi-target TP — backtest engine parity)
            # entry_price=avg_px geçildiğinde TP1+TP2+SL mode aktif olur.
            prot = place_protection_orders(
                exchange,
                sym,
                s["side"],
                filled_qty,
                float(s["tp_price"]),
                float(s["sl_price"]),
                entry_price=avg_px,
                protection_key=f"{sym}:{order.get('id', '')}",
            )
            if prot["status"] == "placed":
                mode = prot.get("mode", "single_target")
                if mode == "multi_target":
                    print(
                        f"    [PROTECT-MULTI] tp1=${prot['tp_price']:.4f} "
                        f"tp2=${prot.get('tp2_price', 0):.4f} sl=${prot['sl_price']:.4f} "
                        f"tp1_id={prot['tp_order_id']} tp2_id={prot.get('tp2_order_id', '?')} "
                        f"sl_id={prot['sl_order_id']}"
                    )
                    notes = f"mode=multi_target tp2={prot.get('tp2_price', 0):.4f} tp2_id={prot.get('tp2_order_id', '')}"
                else:
                    print(
                        f"    [PROTECT] tp=${prot['tp_price']:.4f} sl=${prot['sl_price']:.4f} "
                        f"tp_id={prot['tp_order_id']} sl_id={prot['sl_order_id']}"
                    )
                    notes = None
                if execution_notes:
                    notes = f"{notes} {execution_notes}" if notes else execution_notes
                con.execute(
                    """
                    INSERT INTO futures_protection_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        uuid.uuid4().hex[:16],
                        datetime.now(UTC),
                        sig_id,
                        sym,
                        s["side"],
                        filled_qty,
                        prot["tp_price"],
                        prot["sl_price"],
                        prot["tp_order_id"],
                        prot["sl_order_id"],
                        "placed",
                        notes,
                    ),
                )
            else:
                print(f"    [PROTECT] ERROR: {prot.get('reason')}")
                con.execute(
                    """
                    INSERT INTO futures_protection_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        uuid.uuid4().hex[:16],
                        datetime.now(UTC),
                        sig_id,
                        sym,
                        s["side"],
                        filled_qty,
                        float(s["tp_price"]),
                        float(s["sl_price"]),
                        None,
                        None,
                        "error",
                        prot.get("reason"),
                    ),
                )

            # 6) In-memory state update — sonraki sinyalin RiskOfficer kararı için
            try:
                account.open_positions.append(
                    Position(
                        venue="binance",
                        symbol=sym,
                        side=s["side"],  # type: ignore[arg-type]
                        quantity=filled_qty,
                        entry_price=avg_px,
                        current_price=avg_px,
                        unrealized_pnl_usdt=0.0,
                        realized_pnl_usdt=0.0,
                        opened_at=datetime.now(UTC),
                        strategy_id=s["strategy"],
                        last_updated=datetime.now(UTC),
                    )
                )
                account.free_margin_usdt = max(0.0, account.free_margin_usdt - margin)
            except Exception:
                pass
            state["available_balance"] -= margin
        except Exception as e:
            rejected += 1
            print(f"  [ERR] {sym:<10} {type(e).__name__}: {str(e)[:100]}")
            con.execute(
                """
                INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    sig_id,
                    s["ts"],
                    sym,
                    s["strategy"],
                    s["side"],
                    float(s["sl_price"]),
                    float(s["tp_price"]),
                    float(s["confluence"]),
                    LEVERAGE,
                    "error",
                    None,
                    None,
                    None,
                    None,
                    None,
                    str(e)[:200],
                ),
            )

    con.commit()
    con.close()

    state_after = fetch_futures_state(exchange)
    print(f"\n[RESULT] Submitted: {submitted}, Rejected: {rejected}, Total: {len(signals)}")
    print(
        f"[STATE] Wallet=${state_after['wallet_balance']:.2f}, "
        f"available=${state_after['available_balance']:.2f}, "
        f"pozisyon={state_after['n_positions']}, açik order={state_after['n_open_orders']}"
    )
    return submitted


def load_risk_yaml() -> dict:
    """risk_balanced.yaml'ı parse et (raw dict döndür)."""
    with open(RISK_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def daily_run(target_date: datetime, dry_run: bool = False):
    if not dry_run:
        raise LegacyDailyExecutionDisabledError(_LEGACY_DAILY_EXECUTION_DISABLED_REASON)
    init_journal()
    init_futures_journal()

    # Capital cap — YAML'dan oku, PA_RUN_MODE=live değilse None
    risk_cfg = load_risk_yaml()
    cap_usdt = load_capital_cap(risk_cfg)
    if cap_usdt is not None:
        print(
            f"[CAPITAL_CAP] enabled=True max={cap_usdt:.1f} USDT "
            f"expires={risk_cfg.get('live_capital_cap', {}).get('cap_expires_at', 'N/A')}"
        )
    else:
        print("[CAPITAL_CAP] inactive (paper/backtest mode veya disabled/expired)")

    signals = scan_signals(target_date)

    # Cooldown filter — lab.py semantik parity (same_symbol_side_cooldown_days)
    # Key: (symbol, side) — strategy farkı gözetilmez (lab.py birebir aynı kural)
    cooldown_days = int(
        risk_cfg.get("strategy_portfolio", {}).get("same_symbol_side_cooldown_days", 3)
    )
    if cooldown_days > 0:
        n_before = len(signals)
        signals = filter_signals_by_cooldown(
            signals,
            cooldown_days=cooldown_days,
            journal_path=JOURNAL,
            table="futures_signals",
        )
        n_after = len(signals)
        if n_before != n_after:
            print(
                f"[COOLDOWN] {n_before - n_after}/{n_before} signal rejected "
                f"(cooldown={cooldown_days}d, key=sym+side)"
            )
        else:
            print(f"[COOLDOWN] No signals in cooldown (cooldown={cooldown_days}d)")
    else:
        print("[COOLDOWN] Disabled (cooldown_days=0)")

    # SEC26.B-5 — execution config (post-only limit + slippage gate, default OFF)
    execution_cfg = risk_cfg.get("execution", {}) or {}
    submit_to_futures(signals, dry_run=dry_run, max_pos_usdt=cap_usdt, execution_cfg=execution_cfg)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, default=1)
    args = parser.parse_args()

    if not args.dry_run:
        parser.error(_LEGACY_DAILY_EXECUTION_DISABLED_REASON)

    print("=" * 80)
    print("FUTURES TRADE DAILY (Binance USDM Futures Testnet)")
    print("=" * 80)
    print("Mode: DRY-RUN (legacy daily execution permanently disabled)")
    print(
        f"Leverage: {LEVERAGE}x | Risk: {RISK_PCT * 100:.1f}% | Max notional: {MAX_NOTIONAL_PCT * 100:.0f}% wallet"
    )
    print("LONG + SHORT ikisi de calisir, TP+SL Binance tarafinda otomatik")

    today = datetime.now(UTC)
    for d in range(args.days, 0, -1):
        target = today - timedelta(days=d)
        print(f"\n{'=' * 80}\nDay {target.date()}\n{'=' * 80}", flush=True)
        daily_run(target, dry_run=args.dry_run)
        sys.stdout.flush()
