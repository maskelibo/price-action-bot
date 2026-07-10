"""V13 Testnet Daemon — VSA-WIDESTOP + HTF-1d-aligned (BASELINE exit).

PURPOSE
-------
Thin execution wrapper around the battle-tested futures_daemon.py 15m/5m loops.
Sets the correct env vars for V13, patches the two hardcoded exit constants to
BASELINE values, and injects the HTF 1d EMA50 filter at signal-scan time.

WHAT CHANGED vs CHAMPION
-------------------------
1. TP fractions: 25/25/50 → 30/30/40 (BASELINE from v12 OOS research)
2. Trail pct   : 0.04 (4%) → 0.015 (1.5% approx of ATR-chandelier BASELINE)
   ATR-chandelier full wiring is Phase 2; this is the validated closest pct.
3. HTF filter  : 1d EMA50 — skip LONG when close(t-1) < EMA50_50(t-1);
                             skip SHORT when close(t-1) > EMA50_50(t-1).
   Source: v12_entry_quality.py OOS delta > 0, BH-FDR significant.
4. Sizing      : fixed-fraction (RISK_PCT * starting equity, non-compounding).
5. Config      : configs/risk_v13_testnet.yaml (bot_name=PHOENIX-V13-TESTNET)
6. Journals    : data/futures_journal_v13.duckdb (separate from champion)
7. Timeframes  : 5m + 15m ONLY.  30m/45m DISABLED (B1: feed parity unverified).

WHAT IS NOT CHANGED
-------------------
- Signal scan: same futures_trade_15m.scan_signals_15m + futures_trade_5m.scan_signals_5m
- Risk officer: same RiskOfficer evaluation path
- Order routing: same post-only limit → market fallback
- DMS / kill-switch / idempotency: all inherited, DB-isolated by PA_BOT_NAME=v13
- Champion (PID 53708) is NOT touched — runs in parallel on separate journals

SAFETY CONFIRMATIONS
--------------------
- PA_LIVE_CONFIRM is NEVER set — testnet/paper only
- Champion PID 53708 is NOT stopped by this script
- Real money is NOT touched
- 30m/45m are DISABLED (B1 blocker)

ACTIVATION (testnet only)
-----------
    PA_RUN_MODE=paper PA_BOT_NAME=v13 \\
        python scripts/futures_daemon_v13.py --timeframe 15m

KILL SWITCH (inherited)
    logs/kill_switch.json  halted: true

PID FILE
    logs/v13_daemon.pid

DB SEPARATION (no lock conflict with champion):
    journal        : data/futures_journal_v13.duckdb
    idempotency    : data/idempotency_v13.duckdb
    pyramid_store  : data/pyramid_store_v13.duckdb
    log            : logs/futures_daemon_v13.log
    equity tracker : data/v13_exchange_truth.duckdb
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# ── Environment must be set BEFORE futures_daemon is imported ─────────────────
# PA_BOT_NAME isolates all per-bot DBs (journal, idempotency, pyramid_store, logs).
os.environ.setdefault("PA_BOT_NAME", "v13")
os.environ.setdefault("PA_RUN_MODE", "paper")
os.environ.setdefault("PA_15M_CONFIG", "configs/risk_v13_testnet.yaml")
os.environ.setdefault(
    "PA_5M_CONFIG",
    "configs/risk_phoenix_scalp_5m_p1c.yaml",  # 5m keeps p1c with sl_pct_min=0.030
)
# FIX 2026-06-03: market.duckdb READ-ONLY default. Scan yalnızca okur (journal
# ayrı DB: futures_journal_v13). RO açılınca HTF _load_htf_1d'nin read_only=True
# connect'i config'le eşleşir + ingest cron'un yazma kilidi serbest kalır.
os.environ.setdefault("PA_DUCKDB_READ_ONLY", "true")

# SAFETY GATE: v13 never enables live mode.
if os.environ.get("PA_LIVE_CONFIRM", "").strip():
    raise SystemExit(
        "[V13 SAFETY] PA_LIVE_CONFIRM is set — v13 daemon refuses to run with live mode. "
        "Unset PA_LIVE_CONFIRM to run testnet/paper."
    )

os.environ["PA_LOG_QUIET"] = "1"
import warnings

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# FIX 2026-06-03: daemon doğrudan (swap script'siz) restart edilebilsin diye .env'i
# kendi yükle — testnet API anahtarları buradan gelir. override=False: açıkça set
# edilmiş env (launch komutu / setdefault) kazanır.
if os.environ.get("PA_TESTING", "").strip().lower() not in {"1", "true", "yes", "on"}:
    try:
        from dotenv import load_dotenv as _load_dotenv

        _load_dotenv(ROOT / ".env", override=False)
    except Exception:
        pass

from price_action.runtime_paths import resolve_runtime_root  # noqa: E402

RUNTIME_ROOT = resolve_runtime_root(ROOT)
MARKET_DB = (
    Path(os.environ.get("DUCKDB_PATH", str(RUNTIME_ROOT / "data" / "market.duckdb")))
    .expanduser()
    .resolve()
)

# ── Logging (before daemon import) ───────────────────────────────────────────
LOG_FILE = RUNTIME_ROOT / "logs" / "futures_daemon_v13.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
PID_FILE = RUNTIME_ROOT / "logs" / "v13_daemon.pid"


def _vlog(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%SZ")
    line = f"[{ts}] [V13] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
    except Exception:
        pass
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:
        pass


_vlog("V13 env set: PA_BOT_NAME=v13 PA_RUN_MODE=paper PA_15M_CONFIG=configs/risk_v13_testnet.yaml")

# ── Import daemon + patch BASELINE constants ──────────────────────────────────
# The daemon module sets _TRAIL_PCT = 0.04 and TP1_FRAC/TP2_FRAC = 0.25/0.25
# at import time.  We patch them here AFTER import so they apply to the v13 run.
try:
    import scripts.futures_daemon as _daemon
    import scripts.futures_trade_daily as _ftd

    # Patch 1: trail pct → BASELINE 1.5% (nearest pct to ATR-chandelier mult=1.5)
    _BASELINE_TRAIL_PCT = float(os.environ.get("PA_V13_TRAIL_PCT", "0.015"))
    _old_trail = _daemon._TRAIL_PCT
    _daemon._TRAIL_PCT = _BASELINE_TRAIL_PCT
    _vlog(f"PATCHED _TRAIL_PCT: {_old_trail} → {_daemon._TRAIL_PCT} (BASELINE 1.5% trail)")

    # Patch 2: TP fractions → BASELINE 30/30/40
    # futures_trade_daily.place_protection_orders uses module-level constants inside
    # the function body — we need to monkey-patch place_protection_orders itself.
    _original_place_protection_orders = _ftd.place_protection_orders

    def _v13_place_protection_orders(
        exchange, symbol, side, qty, tp_price, sl_price, entry_price=None
    ):
        """BASELINE exit wrapper: TP1=30%, TP2=30%, runner=40% (vs champion 25/25/50)."""
        import ccxt  # noqa: F401

        # Replicate original logic with BASELINE fractions
        close_side = "SELL" if side == "long" else "BUY"

        # BASELINE fractions
        tp1_frac = 0.30  # BASELINE: 30% at TP1 (was 25%)
        tp2_frac = 0.30  # BASELINE: 30% at TP2 (was 25%)
        # Runner 40% = remaining (was 50%)

        qty_tp1 = qty * tp1_frac
        qty_tp2 = qty * tp2_frac

        try:
            if entry_price is not None and entry_price > 0:
                sl_dist = abs(entry_price - sl_price)
                tp2_r = 1.5
                if side == "long":
                    tp2_price = entry_price + tp2_r * sl_dist
                else:
                    tp2_price = entry_price - tp2_r * sl_dist

                qty1_str = exchange.amount_to_precision(symbol, qty_tp1)
                qty2_str = exchange.amount_to_precision(symbol, qty_tp2)
                tp1_str = exchange.price_to_precision(symbol, tp_price)
                tp2_str = exchange.price_to_precision(symbol, tp2_price)
                sl_str = exchange.price_to_precision(symbol, sl_price)

                tp1_order = exchange.create_order(
                    symbol=symbol,
                    type="TAKE_PROFIT_MARKET",
                    side=close_side,
                    amount=float(qty1_str),
                    params={"stopPrice": tp1_str, "reduceOnly": True, "workingType": "MARK_PRICE"},
                )
                tp2_order = exchange.create_order(
                    symbol=symbol,
                    type="TAKE_PROFIT_MARKET",
                    side=close_side,
                    amount=float(qty2_str),
                    params={"stopPrice": tp2_str, "reduceOnly": True, "workingType": "MARK_PRICE"},
                )
                qty_full_str = exchange.amount_to_precision(symbol, qty)
                sl_order = exchange.create_order(
                    symbol=symbol,
                    type="STOP_MARKET",
                    side=close_side,
                    amount=float(qty_full_str),
                    params={"stopPrice": sl_str, "reduceOnly": True, "workingType": "MARK_PRICE"},
                )
                return {
                    "status": "placed",
                    "mode": "multi_target",
                    "tp_order_id": str(tp1_order.get("id")),
                    "tp2_order_id": str(tp2_order.get("id")),
                    "sl_order_id": str(sl_order.get("id")),
                    "tp_price": float(tp1_str),
                    "tp2_price": float(tp2_str),
                    "sl_price": float(sl_str),
                    "qty_tp1": float(qty1_str),
                    "qty_tp2": float(qty2_str),
                    "qty_sl": float(qty_full_str),
                    "v13_fractions": "30/30/40",
                }
            else:
                # Legacy single-TP fallback (no entry_price)
                return _original_place_protection_orders(
                    exchange, symbol, side, qty, tp_price, sl_price, entry_price
                )
        except Exception as exc:
            return {"status": "error", "reason": str(exc)[:200]}

    _ftd.place_protection_orders = _v13_place_protection_orders
    _vlog("PATCHED place_protection_orders → BASELINE 30/30/40 fractions")

except Exception as _patch_err:
    _vlog(f"PATCH_FAIL: {_patch_err} — daemon NOT patched, ABORT")
    raise SystemExit(f"V13 daemon patch failed: {_patch_err}") from _patch_err


# ── HTF 1d EMA50 filter ───────────────────────────────────────────────────────
# Validated in v12_entry_quality.py: OOS delta > 0, BH-FDR significant.
# Filter: skip LONG when 1d close(t-1) < EMA50(t-1); skip SHORT vice versa.
# Lookahead-free: uses only fully-closed bars before bar_close_ts.

_HTF_CACHE: dict[str, object] = {}  # symbol → pd.DataFrame with ema50 column
_HTF_CACHE_TS: dict[str, datetime] = {}  # last refresh time
_HTF_REFRESH_SECS = 4 * 3600  # refresh cache every 4h (1d bars barely change)
_HTF_EMA_PERIOD = 50


def _load_htf_1d(sym: str):
    """Load 1d OHLCV from market.duckdb and compute EMA50.

    Returns DataFrame with columns [ts, close, ema50] indexed by ts.
    Returns None on any failure (fail-open: allow signal through).
    """
    now = datetime.now(UTC)
    cached_ts = _HTF_CACHE_TS.get(sym)
    if (
        sym in _HTF_CACHE
        and cached_ts is not None
        and (now - cached_ts).total_seconds() < _HTF_REFRESH_SECS
    ):
        return _HTF_CACHE[sym]

    try:
        import duckdb
        import pandas as pd

        db_path = MARKET_DB
        if not db_path.exists():
            return None
        # FIX 2026-06-03 (HTF fail-open kök neden): iki bug üst üste binmişti.
        # (1) In-process RO/RW config mismatch: store market.duckdb'yi RW açar
        #     (PA_DUCKDB_READ_ONLY unset) → read_only=True connect "different
        #     configuration than existing connections" hatası verir. Çözüm:
        #     önce RO dene, çakışırsa flag'siz (mevcut in-process instance'a
        #     attach) retry. Sadece SELECT yaptığımız için RW handle zararsız.
        # (2) Şema kolonu `timeframe`, `resample_rule` DEĞİL → Binder Error
        #     bağlantı düzelse bile fail-open'a düşürüyordu.
        con = None
        for _ro in (True, False):
            try:
                con = duckdb.connect(str(db_path), read_only=_ro)
                break
            except Exception:
                con = None
                continue
        if con is None:
            return None
        try:
            df = con.execute(
                """
                SELECT ts, close
                FROM ohlcv
                WHERE symbol = ? AND timeframe = '1d'
                ORDER BY ts ASC
                """,
                [sym],
            ).df()
        finally:
            con.close()

        if df.empty or len(df) < _HTF_EMA_PERIOD:
            return None

        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df.set_index("ts", inplace=True)
        df["ema50"] = df["close"].ewm(span=_HTF_EMA_PERIOD, adjust=False).mean()

        _HTF_CACHE[sym] = df
        _HTF_CACHE_TS[sym] = now
        return df
    except Exception as _htf_err:
        _vlog(f"HTF_LOAD_ERR: {sym}: {str(_htf_err)[:120]} — fail-open")
        return None


def _htf_filter_ok(sig: dict) -> bool:
    """Return True if signal passes the HTF 1d EMA50 alignment filter.

    Fail-open: returns True (allow) if data is unavailable or stale.
    This matches the v12 OOS test: -1.0 (no data) was treated as allow.
    """
    import pandas as pd

    sym = sig.get("symbol", "")
    side = str(sig.get("side", "")).lower()
    # Use bar_close_ts or ts as the signal timestamp
    raw_ts = sig.get("bar_close_ts") or sig.get("ts")
    if not sym or side not in ("long", "short") or raw_ts is None:
        return True  # fail-open

    try:
        signal_ts = (
            pd.Timestamp(raw_ts, tz="UTC") if not isinstance(raw_ts, pd.Timestamp) else raw_ts
        )
        if signal_ts.tzinfo is None:
            signal_ts = signal_ts.tz_localize("UTC")
    except Exception:
        return True  # can't parse ts → allow

    df = _load_htf_1d(sym)
    if df is None:
        return True  # no data → fail-open

    try:
        # Use bar strictly BEFORE the signal (causal: t-1 close)
        # We want the last fully-closed 1d bar whose ts < signal_ts
        # signal_ts is typically 15m bar close; nearest 1d bar is the prior day.
        before = df.loc[df.index < signal_ts]
        if before.empty:
            return True  # not enough history → allow

        last_row = before.iloc[-1]
        close = float(last_row["close"])
        ema50 = float(last_row["ema50"])

        aligned = close > ema50 if side == "long" else close < ema50

        return aligned
    except Exception as _f_err:
        _vlog(f"HTF_FILTER_ERR: {sym} {side}: {str(_f_err)[:80]} — fail-open")
        return True


# ── Patch _scan_signals_15m to inject HTF filter ─────────────────────────────
_original_scan_15m = _daemon._scan_signals_15m


def _v13_scan_signals_15m(target_dt):
    """15m scan with HTF 1d EMA50 filter applied (V13 lever)."""
    signals = _original_scan_15m(target_dt)
    if not signals:
        return signals

    filtered = []
    rejected = 0
    for sig in signals:
        if _htf_filter_ok(sig):
            filtered.append(sig)
        else:
            rejected += 1
            _vlog(
                f"HTF_REJECT: {sig.get('symbol','?')} {sig.get('side','?')} "
                f"strat={sig.get('strategy','?')} — 1d EMA50 counter-trend"
            )

    if rejected:
        _vlog(f"HTF_FILTER: {len(signals)} sigs → {len(filtered)} passed ({rejected} HTF-rejected)")

    return filtered


_daemon._scan_signals_15m = _v13_scan_signals_15m
_vlog("PATCHED _scan_signals_15m → HTF 1d EMA50 filter injected")

# 5m signals: also apply HTF filter
if hasattr(_daemon, "_scan_signals_5m"):
    _original_scan_5m = _daemon._scan_signals_5m

    def _v13_scan_signals_5m(target_dt):
        signals = _original_scan_5m(target_dt)
        if not signals:
            return signals
        filtered = []
        rejected = 0
        for sig in signals:
            if _htf_filter_ok(sig):
                filtered.append(sig)
            else:
                rejected += 1
                _vlog(
                    f"HTF_REJECT_5M: {sig.get('symbol','?')} {sig.get('side','?')} — 1d EMA50 counter"
                )
        if rejected:
            _vlog(
                f"HTF_FILTER_5M: {len(signals)} sigs → {len(filtered)} passed ({rejected} rejected)"
            )
        return filtered

    _daemon._scan_signals_5m = _v13_scan_signals_5m
    _vlog("PATCHED _scan_signals_5m → HTF 1d EMA50 filter injected")


# ── PID file ──────────────────────────────────────────────────────────────────
def _write_pid() -> None:
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
        _vlog(f"PID file written: {PID_FILE} (pid={os.getpid()})")
    except Exception as _pid_err:
        _vlog(f"PID file write fail: {_pid_err} — non-fatal")


# ── Exchange-truth equity tracker bootstrap ───────────────────────────────────
def _init_exchange_truth_db() -> None:
    """Initialize data/v13_exchange_truth.duckdb for clean exchange-source PnL tracking.

    Schema: v13_equity_snapshots — daily snapshots from fapiPrivateGetIncome +
    fetch_positions.  Journal is NOT the source of truth (drifts due to phantom/
    qty-drift/double-count history).  Exchange income is.
    """
    try:
        import duckdb

        db_path = RUNTIME_ROOT / "data" / "v13_exchange_truth.duckdb"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(db_path))
        con.execute("""
            CREATE TABLE IF NOT EXISTS v13_equity_snapshots (
                snap_id         VARCHAR PRIMARY KEY,
                ts              TIMESTAMP,
                wallet_balance  DOUBLE,   -- from fetch_balance USDT total
                realized_pnl    DOUBLE,   -- from fapiPrivateGetIncome REALIZED_PNL (since v13_start_ts)
                commission      DOUBLE,   -- from fapiPrivateGetIncome COMMISSION (since v13_start_ts)
                unrealized_pnl  DOUBLE,   -- from fetch_positions sum unrealizedPnl
                total_net       DOUBLE,   -- realized + unrealized + commission (net)
                n_positions     INTEGER,
                notes           VARCHAR
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS v13_meta (
                key   VARCHAR PRIMARY KEY,
                value VARCHAR
            )
        """)
        # Record v13 start timestamp (first time we run — used as income query startTime)
        existing = con.execute("SELECT value FROM v13_meta WHERE key = 'v13_start_ts'").fetchone()
        if existing is None:
            start_ts = datetime.now(UTC).isoformat()
            con.execute("INSERT INTO v13_meta VALUES ('v13_start_ts', ?)", [start_ts])
            _vlog(f"EXCHANGE_TRUTH_DB: v13_start_ts recorded: {start_ts}")
        else:
            _vlog(f"EXCHANGE_TRUTH_DB: v13_start_ts exists: {existing[0]}")
        con.commit()
        con.close()
        _vlog(f"EXCHANGE_TRUTH_DB: initialized at {db_path}")
    except Exception as _db_err:
        _vlog(f"EXCHANGE_TRUTH_DB_INIT_ERR: {_db_err} — non-fatal, tracker unavailable")


# ── Banner ────────────────────────────────────────────────────────────────────
def _print_v13_banner() -> None:
    _vlog("=" * 65)
    _vlog("V13 TESTNET DAEMON — VSA-WIDESTOP + HTF-1d-ALIGNED")
    _vlog("  Config      : configs/risk_v13_testnet.yaml")
    _vlog("  Bot name    : PHOENIX-V13-TESTNET")
    _vlog("  Journal     : data/futures_journal_v13.duckdb")
    _vlog("  TFs active  : 5m + 15m  (30m/45m OFF — B1 blocker)")
    _vlog("  Entry gates : WIDESTOP sl>=0.025 + HTF 1d EMA50 aligned")
    _vlog("  Exit        : BASELINE trail=1.5% / TP1=30%@1R / TP2=30%@1.5R / runner=40%")
    _vlog("  Runner cap  : 30-bar time-stop (force_exit_from_entry=False)")
    _vlog("  Sizing      : FIXED-FRACTION 0.5% risk (non-compounding)")
    _vlog("  Measurement : exchange income (fapiPrivateGetIncome) — NOT journal")
    _vlog("  Champion    : PID 53708 INTACT — swap script staged, NOT executed")
    _vlog("  PA_LIVE_CONFIRM: NOT SET — testnet only")
    _vlog("=" * 65)


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V13 Testnet Daemon — BASELINE exit + HTF filter")
    parser.add_argument("--once", action="store_true", help="Single bar cycle (test)")
    parser.add_argument(
        "--timeframe",
        choices=["15m", "5m"],
        default="15m",
        help="Timeframe: 15m (default) or 5m",
    )
    args = parser.parse_args()

    _write_pid()
    _init_exchange_truth_db()
    _print_v13_banner()

    _vlog(f"Delegating to futures_daemon.run_{args.timeframe}_mode(once={args.once})")

    if args.timeframe == "15m":
        _daemon.run_15m_mode(once=args.once)
    elif args.timeframe == "5m":
        _daemon.run_5m_mode(once=args.once)
    else:
        _vlog(f"Unknown timeframe: {args.timeframe}")
        raise SystemExit(1)
