"""Futures Trade 15m — Binance USDM Futures, 15m intraday scalp.

SEC54.5 (DQ-02): 15m stale signal guard — sinyal 30 dakikadan (2 bar) eskiyse REJECT.
SEC55.A: Paralel symbol scan — ThreadPoolExecutor ile her sembol bağımsız thread'de.

Usage:
    python scripts/futures_trade_15m.py [--dry-run]

Schedule (production):
    */5 * * * *  python scripts/futures_trade_15m.py
    (Her 5 dakikada bir; 15m bar kapanışından sonra max 5dk gecikme ile çalışır.)

Signal staleness policy (DQ-02):
    15m bar lifecycle = 15 dakika.
    SIGNAL_MAX_AGE_MIN = 30 dakika (2 bar tolerans).
    Sinyal 30 dakikadan eskiyse: REJECT + log + metric increment.
    Sessizce devam etme YOK.

Paralel scan policy (SEC55.A):
    PA_SCAN_PARALLEL_WORKERS env var ile max_workers override edilir (default 8).
    max_workers=1 → sequential (byte-identical sonuç).
    Her thread kendi read-only DuckDB connection açar (concurrent read safe).
    Sembol bazlı timeout: 180 saniye (AVWAP worst-case budget).
    1 sembol başarısız → degraded mode, diğerleri devam eder.
    Çıktı sırası: sort(ts, symbol) ile deterministik.

Davranış:
    - Binance USDM Futures (defaultType=future — DQ-04).
    - RiskOfficer entegrasyonu (YAML breaker, consecutive loss, side-cond DD).
    - Quality checks: stale guard, cooldown, capital cap.
    - 15m OHLCV: ingest_15m_live.py cron'u tarafından zaten yazılmış olmalı.
    - NaN forward-fill YOK. Eksik bar NaN olarak kalır.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings

warnings.filterwarnings("ignore")

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)

from price_action.logging_config import logger

# ── DQ-02: Stale signal threshold ─────────────────────────────────────────────
SIGNAL_MAX_AGE_MIN = 30  # 2 × 15m bar — bu süreden eskisi REJECT

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOLS: list[str] = [
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
    # DEPLOY 2026-05-29: sembol evreni genişletme (likit, +%41 pozisyon backtest).
    # ZEC/NEAR/FIL/XLM — 15m verisi market.duckdb'de taze (ingest15m + snapshot).
    "ZEC/USDT",
    "NEAR/USDT",
    "FIL/USDT",
    "XLM/USDT",
    # DEPLOY 2026-05-30: yerleşik likit genişletme (14→19). vsa+brooks backtest
    # 5y: hepsi mean_R baseline'a yakın/üstü, totR pozitif (TRX +0.378, UNI/ATOM/
    # AAVE/ALGO +0.29..+0.34). Meme/hisse/emtia değil, gerçek-kullanım coinleri.
    "TRX/USDT",
    "UNI/USDT",
    "ATOM/USDT",
    "AAVE/USDT",
    "ALGO/USDT",
]

TF = "15m"

# ── Paralel scan config (SEC55.A) ─────────────────────────────────────────────
_DEFAULT_PARALLEL_WORKERS = 8
_SCAN_SYMBOL_TIMEOUT_SEC = 180  # AVWAP worst-case budget

# FIX 2026-05-28 (audit-FIX-VER3-2): per-scan read_fail counter (thread-safe).
# scan_signals_15m başında reset, _scan_symbol fail'lerinde artar, sonunda
# sayım stderr'e yansır (launchd futures15m.stderr.log → operatör görür).
import threading as _thr

_READ_FAIL_LOCK = _thr.Lock()
_READ_FAIL_COUNT: int = 0
_READ_FAIL_SAMPLES: list[str] = []


def _record_read_fail(sym: str, exc: Exception) -> None:
    """Thread-safe: read_fail sayım + ilk 3 örneği topla."""
    global _READ_FAIL_COUNT
    with _READ_FAIL_LOCK:
        _READ_FAIL_COUNT += 1
        if len(_READ_FAIL_SAMPLES) < 3:
            _READ_FAIL_SAMPLES.append(f"{sym}: {type(exc).__name__}: {str(exc)[:120]}")


def _reset_read_fail_state() -> None:
    """scan_signals_15m başlangıcında çağrılır."""
    global _READ_FAIL_COUNT
    with _READ_FAIL_LOCK:
        _READ_FAIL_COUNT = 0
        _READ_FAIL_SAMPLES.clear()


def _emit_read_fail_summary(n_syms: int) -> None:
    """scan_signals_15m sonunda — fail varsa stderr'e özet yaz."""
    with _READ_FAIL_LOCK:
        if _READ_FAIL_COUNT == 0:
            return
        msg = (
            f"[SCAN15M_READ_FAIL] {_READ_FAIL_COUNT}/{n_syms} sembol DB read fail "
            f"(silent — sinyaller kayıp olabilir)"
        )
        if _READ_FAIL_SAMPLES:
            msg += " | örnekler: " + " || ".join(_READ_FAIL_SAMPLES[:2])
    try:
        import sys as _sys

        _sys.stderr.write(msg + "\n")
        _sys.stderr.flush()
    except Exception:
        pass


def _get_parallel_workers() -> int:
    """PA_SCAN_PARALLEL_WORKERS env var ile override; default 8."""
    try:
        val = int(os.environ.get("PA_SCAN_PARALLEL_WORKERS", _DEFAULT_PARALLEL_WORKERS))
        return max(1, val)
    except (ValueError, TypeError):
        return _DEFAULT_PARALLEL_WORKERS


_BOT_NAME = os.environ.get("PA_BOT_NAME", "phoenix").lower()
if _BOT_NAME == "phoenix":
    JOURNAL = ROOT / "data" / "futures_journal_15m_phoenix.duckdb"
    # G4 fix (hard review 2026-05-21): 15m bot 15m config kullanmalı —
    # eskiden risk_phoenix_v204.yaml (1d config) yükleniyordu.
    RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"
    BREAKER_STATE = ROOT / "logs" / "risk" / "futures_breaker_state_15m_phoenix.json"
else:
    JOURNAL = ROOT / "data" / "futures_journal_15m.duckdb"
    RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2_champion.yaml"
    BREAKER_STATE = ROOT / "logs" / "risk" / "futures_breaker_state_15m.json"

BREAKER_STATE.parent.mkdir(parents=True, exist_ok=True)
print(f"[futures_trade_15m] BOT={_BOT_NAME} | journal={JOURNAL.name} | risk={RISK_YAML.name}")


# ── Journal init ───────────────────────────────────────────────────────────────


def init_15m_journal() -> None:
    con = duckdb.connect(str(JOURNAL))
    con.execute("""
        CREATE TABLE IF NOT EXISTS futures_15m_signals (
            signal_id    VARCHAR PRIMARY KEY,
            ts           TIMESTAMP,
            bar_close_ts TIMESTAMP,
            symbol       VARCHAR,
            strategy     VARCHAR,
            side         VARCHAR,
            sl_price     DOUBLE,
            tp_price     DOUBLE,
            confluence   DOUBLE,
            leverage     INTEGER,
            status       VARCHAR,
            order_id     VARCHAR,
            fill_price   DOUBLE,
            fill_qty     DOUBLE,
            notional_usdt DOUBLE,
            margin_usdt  DOUBLE,
            age_min      DOUBLE,
            notes        VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS futures_15m_equity_snapshots (
            snapshot_id  VARCHAR PRIMARY KEY,
            ts           TIMESTAMP,
            wallet_balance DOUBLE,
            unrealized_pnl DOUBLE,
            notes        VARCHAR
        )
    """)
    con.commit()
    con.close()


# ── Signal scan (15m) ─────────────────────────────────────────────────────────

# Strategy registry — config-driven (Faz 14.25, 2026-05-27).
# strategies_enabled: [...] config'de varsa onu kullan, yoksa default 4 (vsa+top3).
# Bu sayede aynı daemon farklı PA_15M_CONFIG ile farklı strateji subset koşturur.

_STRATEGY_CATALOG = {
    "vsa_climax_test": "VSAClimaxTestStrategy",
    "brooks_failed_breakout": "BrooksFailedBreakoutStrategy",
    "anchored_vwap_reversal": "AnchoredVWAPReversalStrategy",
    "engulfing_continuation": "EngulfingContinuationStrategy",
    "rsi2_extreme_fade": "RSI2ExtremeFadeStrategy",
    "session_vwap_mean_reversion": "SessionVWAPMeanReversionStrategy",
    # FAZ-3 (2026-06-11): Grimes ABC two-leg pullback — pre-reg PASS diversifier
    # (standalone +8.94/ay, korr +0.12; 5-strateji backtest +26.1/ay 0 neg ay).
    "grimes_abc_pullback": "GrimesABCPullbackStrategy",
}

_DEFAULT_4 = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
]


def _resolve_strategies_15m() -> list[tuple[str, str]]:
    """Config'den `strategies_enabled` oku → (module, class) list döndür.

    Default: 4'lü top set (vsa+brooks+anchored+engulfing).
    """
    import os

    cfg_path = os.environ.get("PA_15M_CONFIG", "")
    if not cfg_path:
        return _DEFAULT_4
    try:
        from pathlib import Path as _P

        import yaml

        path = _P(cfg_path)
        if not path.is_absolute():
            path = _P(__file__).resolve().parents[1] / cfg_path
        if not path.exists():
            return _DEFAULT_4
        cfg = yaml.safe_load(path.read_text()) or {}
        enabled = cfg.get("strategies_enabled") or []
        if not enabled:
            return _DEFAULT_4
        out = []
        for mod_name in enabled:
            cls = _STRATEGY_CATALOG.get(mod_name)
            if cls:
                out.append((mod_name, cls))
        return out or _DEFAULT_4
    except Exception:
        return _DEFAULT_4


_TOP_4_15M = _resolve_strategies_15m()


def _fetch_fresh_bars_ccxt(sym: str, n_bars: int = 50) -> pd.DataFrame | None:
    """SEC56 FIX: ccxt'ten doğrudan 15m bar çek (ingest bypass).

    DuckDB'deki veri stale olduğunda kullanılır. OHLCVStore'a yazmaz —
    sadece bu scan turu için kullanılır; kalıcı ingest ingest_15m_live.py'nin görevi.

    Returns: OHLCV DataFrame (ts UTC-aware) veya None (hata durumunda).
    """
    try:
        import ccxt as _ccxt

        ex = _ccxt.binance(
            {
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            }
        )
        since_ms = int((datetime.now(UTC) - timedelta(minutes=n_bars * 15)).timestamp() * 1000)
        raw = ex.fetch_ohlcv(sym, timeframe=TF, since=since_ms, limit=n_bars)
        if not raw:
            return None
        df = pd.DataFrame(raw, columns=["ts_ms", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["venue"] = "binance"
        df["symbol"] = sym
        df["timeframe"] = TF
        df = df[["venue", "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"]]
        return df.sort_values("ts").reset_index(drop=True)
    except Exception as exc:
        logger.bind(symbol=sym, err=str(exc)).warning("scan15m.fresh_fetch_fail")
        return None


# SEC56: Data freshness threshold — ingest stale'i için otomatik refresh
# 2 bar = 30 dakika. Son barın bu süreden eski olması = ingest kesintisi.
_DATA_FRESHNESS_MAX_MIN = 30  # dakika


def _scan_symbol(sym: str, target_bar_close: pd.Timestamp) -> list[dict]:
    """Per-symbol scan — thread-safe.

    Thread-safety notları (SEC55.A):
      - Her çağrı kendi strategy instance'larını yaratır (shared state yok).
      - OHLCVStore singleton RLock (global _CONN_POOL) kullanır — Windows DuckDB
        exclusive-lock uyumlu, serialize ederek okur. Paralel thread'ler RLock'ta
        sıralanır (I/O serialize) ama CPU computation (prepare_features, numpy)
        GIL-release yaptığı ölçüde paralel çalışır.
      - logger thread-safe (Python logging stdlib).
      - target_bar_close immutable pd.Timestamp — shared access OK.

    DuckDB thread-safety notu:
      Windows'ta daemon market.duckdb'yi exclusive lock ile tutabilir. read_only=True
      concurrent open WAL modunda teorik olarak çalışır ama Windows IPC'de unreliable.
      OHLCVStore._conn() → RLock ile serialize → daha güvenli.

    SEC56 FIX: Data freshness guard.
      Son bar > _DATA_FRESHNESS_MAX_MIN dakika eski ise ingest cron durmuş demektir.
      ccxt'ten 50 bar fresh fetch yapılır, DuckDB'ye merge edilir.
      Bu sayede sinyal üretimi ingest kesintisinde de çalışır.

    Returns: bu sembol için emit edilen sinyal dict listesi (boş olabilir).
    """
    from price_action.data.store import OHLCVStore

    sym_signals: list[dict] = []

    # OHLCVStore: singleton pooled connection, RLock-guarded (Windows-safe)
    try:
        store = OHLCVStore()
        df = store.read(sym, TF, venue="binance")
    except Exception as exc:
        logger.bind(symbol=sym, err=str(exc)).error("scan15m._scan_symbol.read_fail")
        # FIX 2026-05-28 (audit-FIX-VER3-2): silent fail visibility.
        # Önceki bug: read_fail sadece app.log'a düşüyordu, futures_daemon.log
        # temiz görünüyordu → operatör "0 sinyal, latency=0.0s" görüyor
        # "piyasa darı" sanıyordu. Gerçekte 50 sembol × her tick read fail.
        # Şimdi: thread-safe counter, scan_signals_15m sonunda stderr'e özet
        # (launchd futures15m.stderr.log'a düşer, operatör görür).
        try:
            _record_read_fail(sym, exc)
        except Exception:
            pass
        return sym_signals

    if df is None or df.empty:
        return sym_signals

    df = df.sort_values("ts").reset_index(drop=True)

    # === SEC57 FIX (2026-05-18 15:00 IST): warm-up window slicing — 100x speedup ===
    # Daemon her tick'te 5y tüm 175K bar tarıyordu (31.7s/sym × 10 sym = 317s sequential)
    # Sadece son bar sinyali için 500 bar yeterli (EMA200 + AVWAP60 + S/R200 lookback
    # max ~200, 1.5× buffer = 300, güvenli = 500). %99.8 hesap boşa gidiyordu.
    # Beklenen: per-sym 31.7s → 0.3s, total bar_close → pozisyon ~9s (hedef 5-10s).
    # Kill criteria: sinyal sayısı %30+ saparsa STRATEGY_WARMUP_BARS=1000'e yükselt.
    STRATEGY_WARMUP_BARS = 500
    if len(df) > STRATEGY_WARMUP_BARS:
        df = df.tail(STRATEGY_WARMUP_BARS).reset_index(drop=True)
    # === END SEC57 FIX ===

    df["symbol"] = sym
    df["venue"] = "binance"
    df["timeframe"] = TF
    df["vol_z_pre"] = 0

    # SEC56 FIX: data freshness guard — ingest cron durmuşsa ccxt'ten taze bar çek
    now_utc = datetime.now(UTC)
    last_store_ts = df["ts"].iloc[-1]
    if last_store_ts.tzinfo is None:
        last_store_ts = last_store_ts.tz_localize("UTC")
    data_age_min = (now_utc - last_store_ts.to_pydatetime()).total_seconds() / 60

    if data_age_min > _DATA_FRESHNESS_MAX_MIN:
        logger.bind(
            symbol=sym,
            last_bar=str(last_store_ts),
            age_min=round(data_age_min, 1),
            threshold_min=_DATA_FRESHNESS_MAX_MIN,
        ).warning("scan15m.data_stale_auto_refresh")
        fresh_df = _fetch_fresh_bars_ccxt(sym, n_bars=50)
        if fresh_df is not None and not fresh_df.empty:
            # SEC56-FIX (2026-05-18 17:00 IST): DB'ye upsert YAPMA.
            # Sebep: DuckDB Windows aynı DB'ye farklı config ile 2 connection
            # tutamaz. Scan thread upsert ederken main thread order_submit için
            # read açınca "Connection Error: Can't open a connection to same DB
            # file with a different configuration" hatası → 8 sinyal hep fail
            # (logs/futures_daemon.log 13:52-13:53 UTC). Fix: in-memory only
            # refresh — DB write işi ingest_15m_live.py cron'una bırakıldı.
            # Eğer cron çalışmazsa, scan kendi RAM'inde taze veri tutar ama
            # restart sonrası DB stale kalır → ingest manuel/cron şart kalır.
            df = pd.concat([df, fresh_df], ignore_index=True)
            df = df.drop_duplicates(subset=["ts"], keep="last")
            df = df.sort_values("ts").reset_index(drop=True)
            logger.bind(symbol=sym, n_bars=len(fresh_df)).info("scan15m.auto_refresh_memory_only")
            new_last = df["ts"].iloc[-1]
            logger.bind(
                symbol=sym,
                old_last=str(last_store_ts),
                new_last=str(new_last),
            ).info("scan15m.data_refreshed")
        else:
            logger.bind(symbol=sym).error("scan15m.auto_refresh_fail_no_data")

    # Causal: sadece target_bar_close'a kadar olan barlar
    df_filtered = df[df["ts"] <= target_bar_close]
    if df_filtered.empty:
        return sym_signals

    last_bar_ts = df_filtered["ts"].iloc[-1]
    last_close = float(df_filtered.iloc[-1]["close"])

    for module_name, class_name in _TOP_4_15M:
        try:
            mod = __import__(
                f"price_action.strategies.{module_name}",
                fromlist=[class_name, "_default_manifest"],
            )
            cls = getattr(mod, class_name)
            manifest_fn = getattr(mod, "_default_manifest", None)
            if not manifest_fn:
                continue
            # Per-call strategy instance — thread-safe (no shared mutable state)
            strategy = cls(manifest_fn())
        except Exception as exc:
            logger.bind(module=module_name, symbol=sym, err=str(exc)).warning(
                "scan15m.strategy_load_fail"
            )
            continue

        try:
            df_prep = strategy.prepare_features(df_filtered.copy())
            sigs = strategy.generate_signals(df_prep)

            for sig in sigs:
                sig_ts = pd.Timestamp(sig.ts)
                if sig_ts.tzinfo is None:
                    sig_ts = sig_ts.tz_localize("UTC")
                # Sadece son bar kapanışında emit edilenleri al
                if abs((sig_ts - last_bar_ts).total_seconds()) < 60:
                    sym_signals.append(
                        {
                            "ts": sig_ts,
                            "bar_close_ts": last_bar_ts,
                            "symbol": sym,
                            "strategy": module_name,
                            "side": sig.direction,
                            "entry_price": last_close,
                            "sl_price": sig.sl_price,
                            "tp_price": sig.tp_price,
                            "confluence": sig.confluence_score,
                            "signal_obj": sig,
                        }
                    )
        except Exception as exc:
            logger.bind(module=module_name, symbol=sym, err=str(exc)).warning(
                "scan15m.symbol_strategy_fail"
            )

    return sym_signals


def scan_signals_15m(
    target_bar_close: datetime,
    max_workers: int | None = None,
) -> list[dict]:
    """target_bar_close öncesindeki 15m barları tara, sinyal üret.

    target_bar_close: son kapanan 15m bar'ın kapanış zamanı (UTC).
    Sadece o bar'da emit edilen sinyaller döner.

    max_workers: ThreadPool worker sayısı.
        None  → PA_SCAN_PARALLEL_WORKERS env var (default 8).
        1     → sequential (byte-identical sonuç, test/debug).
        8+    → paralel (4-8× speedup hedefi — SEC55.A).

    Strategies: C2 champion — vsa_climax_test + brooks_failed_breakout +
                anchored_vwap_reversal + engulfing_continuation (SEC54.1 TOP-4).

    Thread-safety: _scan_symbol() per-thread strategy instantiation +
    read-only DuckDB connection (concurrent reads safe).
    Exception isolation: 1 sembol crash → diğerleri devam (degraded mode).
    Output order: sort(ts, symbol) — deterministik.
    """
    workers = max_workers if max_workers is not None else _get_parallel_workers()

    # FIX 2026-05-28 (audit-FIX-VER3-2): read_fail counter reset her scan başında.
    _reset_read_fail_state()

    # target_bar_close'u pd.Timestamp UTC'ye normalize et (comparison için)
    tbc = pd.Timestamp(target_bar_close)
    if tbc.tzinfo is None:
        tbc = tbc.tz_localize("UTC")

    all_signals: list[dict] = []

    if workers == 1:
        # Sequential path — byte-identical referans (test + debug)
        for sym in SYMBOLS:
            try:
                sym_sigs = _scan_symbol(sym, tbc)
                all_signals.extend(sym_sigs)
            except Exception as exc:
                logger.bind(symbol=sym, err=str(exc)).error("scan15m.sequential_fail")
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {pool.submit(_scan_symbol, sym, tbc): sym for sym in SYMBOLS}
            for fut in as_completed(future_map):
                sym = future_map[fut]
                try:
                    sym_sigs = fut.result(timeout=_SCAN_SYMBOL_TIMEOUT_SEC)
                    all_signals.extend(sym_sigs)
                except TimeoutError:
                    logger.bind(
                        symbol=sym,
                        timeout_sec=_SCAN_SYMBOL_TIMEOUT_SEC,
                    ).error("scan15m.symbol_timeout")
                except Exception as exc:
                    logger.bind(symbol=sym, err=str(exc)).error("scan15m.symbol_fail")

    # Deterministik sıra: ts, sonra sembol alfabetik (max_workers bağımsız)
    all_signals.sort(key=lambda s: (s["ts"], s["symbol"]))

    # FIX 2026-05-28 (audit-FIX-VER3-2): read_fail summary stderr → operatör görür.
    _emit_read_fail_summary(n_syms=len(SYMBOLS))

    logger.bind(
        tf=TF,
        bar=tbc.isoformat(),
        n_signals=len(all_signals),
        workers=workers,
    ).info("scan15m.done")
    return all_signals


# ── Stale signal guard (DQ-02) ────────────────────────────────────────────────


def filter_stale_signals(signals: list[dict], now_utc: datetime) -> tuple[list[dict], int]:
    """SIGNAL_MAX_AGE_MIN aşan sinyalleri REJECT et.

    Returns: (fresh_signals, rejected_count)

    DQ-02 Hard Limit:
        15m bar lifecycle = 15 dakika.
        Tolerans: 2 bar = 30 dakika.
        Sinyalin bar_close_ts'inden itibaren 30 dakika geçmişse REJECT.
        Sessizce devam etme YOK: log + metric.
    """
    try:
        from price_action.api.prometheus_metrics import stale_signal_reject_total

        has_metric = True
    except Exception:
        has_metric = False

    fresh: list[dict] = []
    rejected = 0

    for sig in signals:
        bar_close = sig.get("bar_close_ts")
        if bar_close is None:
            bar_close = sig.get("ts")

        if bar_close is not None:
            if hasattr(bar_close, "tzinfo") and bar_close.tzinfo is None:
                bar_close = pd.Timestamp(bar_close).tz_localize("UTC")
            elif isinstance(bar_close, pd.Timestamp) and bar_close.tzinfo is None:
                bar_close = bar_close.tz_localize("UTC")

            age_min = (now_utc - pd.Timestamp(bar_close).to_pydatetime()).total_seconds() / 60
            if age_min > SIGNAL_MAX_AGE_MIN:
                rejected += 1
                logger.bind(
                    tf=TF,
                    symbol=sig.get("symbol"),
                    strategy=sig.get("strategy"),
                    age_min=round(age_min, 1),
                    max_age_min=SIGNAL_MAX_AGE_MIN,
                ).warning("DQ-02 REJECT stale signal")
                if has_metric:
                    try:
                        stale_signal_reject_total.labels(tf=TF).inc()
                    except Exception:
                        pass
                continue

        fresh.append(sig)

    return fresh, rejected


# ── Main run ──────────────────────────────────────────────────────────────────


def run_15m(dry_run: bool = False) -> None:
    init_15m_journal()

    now_utc = datetime.now(UTC)

    # Son kapanan 15m bar (floor to 15m boundary)
    minutes_since_epoch = int(now_utc.timestamp() // 60)
    bar_floor_min = (minutes_since_epoch // 15) * 15
    last_bar_close = datetime.fromtimestamp(bar_floor_min * 60, tz=UTC)

    print(
        f"[15m] now={now_utc.strftime('%H:%M:%S')} UTC  last_bar_close={last_bar_close.strftime('%H:%M')} UTC"
    )

    # 1. Sinyal tara
    signals = scan_signals_15m(last_bar_close)
    print(f"[15m] {len(signals)} sinyal üretildi")

    # 2. DQ-02: Stale guard
    signals, n_stale = filter_stale_signals(signals, now_utc)
    if n_stale > 0:
        print(f"[DQ-02] {n_stale} stale sinyal REJECT edildi (age > {SIGNAL_MAX_AGE_MIN}min)")

    if not signals:
        print("[15m] Taze sinyal yok, çıkış.")
        return

    if dry_run:
        print(f"\n[DRY-RUN] {len(signals)} taze sinyal:")
        for s in signals:
            age_s = int((now_utc - pd.Timestamp(s["bar_close_ts"]).to_pydatetime()).total_seconds())
            print(
                f"  {s['ts'].strftime('%H:%M')} {s['symbol']:<12} "
                f"{s['strategy']:<35} {s['side']:<5} conf={s['confluence']:.2f} "
                f"age={age_s}s"
            )
        return

    # 3. RiskOfficer evaluate + order submit
    # Delegating to futures_trade_daily.submit_to_futures (same exchange setup,
    # same journal pattern) to avoid code duplication — 15m specific journal path.
    import yaml

    from scripts.futures_trade_daily import (
        fetch_futures_state,
        get_futures_exchange,
        place_protection_orders,
        setup_leverage,
    )
    from scripts.lib.cooldown import filter_signals_by_cooldown
    from scripts.lib.risk_integration import (
        build_futures_account_state,
        build_returns_df,
        build_signal_from_scan,
        load_risk_officer,
    )

    risk_officer = load_risk_officer(yaml_path=RISK_YAML, breaker_state_path=BREAKER_STATE)

    with open(RISK_YAML, encoding="utf-8") as f:
        risk_cfg = yaml.safe_load(f) or {}

    exchange = get_futures_exchange()
    state = fetch_futures_state(exchange)

    # SEC-#3A: Konsantrasyon fail-safe — stale pozisyon dedektörü.
    # fetch_positions() bazen boş dönebilir (rate-limit 418, API stale)
    # ama borsada hala açık pozisyon bulunabilir. Bu durumda
    # concentration_gate "pozisyon yok" sanıp yeni emri geçirir →
    # ALGO sembolünde yığılma (gözlemlenen: %15→%27).
    # Stale koşul: positions_ok=False VEYA (positions boş AMA initialMargin>0)
    # İkinci koşul: fetch_positions() boş döndü ama raw account
    # totalInitialMargin > 0 → borsada pozisyon var ama liste gelmedi.
    _pos_ok = state.get("positions_ok", True)
    _init_margin = float(state.get("total_initial_margin", 0))
    _pos_list = state.get("positions", [])
    _stale_positions = (
        not _pos_ok
        or (len(_pos_list) == 0 and _init_margin > 0)
    )
    if _stale_positions:
        print(
            f"[ENTRY_SKIP_STALE_POS] pozisyon verisi güvenilmez "
            f"(positions_ok={_pos_ok}, pos_list_len={len(_pos_list)}, "
            f"initialMargin={_init_margin:.2f}) — bu çalışmadaki tüm "
            f"girişler atlandı"
        )
        return

    returns_df = build_returns_df(SYMBOLS, days=90, market_db=ROOT / "data" / "market.duckdb")
    account = build_futures_account_state(state, journal_path=JOURNAL)

    # Cooldown filter
    # G3 fix (hard review 2026-05-21): float — int() cast 0.010 günü (15dk) 0'a
    # yuvarlayıp cooldown'u tamamen bypass ediyordu; lab.py float semantiği.
    cooldown_days = float(
        risk_cfg.get("strategy_portfolio", {}).get("same_symbol_side_cooldown_days", 1)
    )
    if cooldown_days > 0:
        n_before = len(signals)
        signals = filter_signals_by_cooldown(
            signals,
            cooldown_days=cooldown_days,
            journal_path=JOURNAL,
            table="futures_15m_signals",
        )
        if len(signals) < n_before:
            print(f"[COOLDOWN] {n_before - len(signals)} sinyal cooldown reject")

    con = duckdb.connect(str(JOURNAL))
    submitted = 0
    rejected = 0

    for s in signals:
        sig_id = uuid.uuid4().hex[:16]
        sym = s["symbol"]

        age_min = (now_utc - pd.Timestamp(s["bar_close_ts"]).to_pydatetime()).total_seconds() / 60

        try:
            ticker = exchange.fetch_ticker(sym)
            cur_px = ticker["last"]

            signal_obj = build_signal_from_scan(s, venue="binance", timeframe="15m")
            decision = risk_officer.evaluate(
                signal_obj,
                account,
                market_price=cur_px,
                returns_df=returns_df,
            )

            if not hasattr(decision, "quantity"):
                reject_reason = getattr(decision, "reason", "unknown")
                rejected += 1
                print(f"  [REJECT-RISK] {sym:<12} {s['strategy']:<30} {reject_reason}")
                con.execute(
                    "INSERT INTO futures_15m_signals VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        sig_id,
                        s["ts"],
                        s["bar_close_ts"],
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
                        round(age_min, 1),
                        None,
                    ),
                )
                continue

            risked = decision
            qty = float(risked.quantity)
            notional = float(risked.notional_usdt)
            leverage_used = max(1, min(5, int(round(risked.leverage)))) or 1
            margin = notional / leverage_used if leverage_used > 0 else notional

            if margin > state["available_balance"] * 0.9:
                rejected += 1
                print(
                    f"  [SKIP-MARGIN] {sym} need=${margin:.2f}, have=${state['available_balance']:.2f}"
                )
                con.execute(
                    "INSERT INTO futures_15m_signals VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        sig_id,
                        s["ts"],
                        s["bar_close_ts"],
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
                        round(age_min, 1),
                        None,
                    ),
                )
                continue

            setup_leverage(exchange, sym, leverage_used)
            order_side = "buy" if s["side"] == "long" else "sell"
            order = exchange.create_market_order(sym, order_side, qty)

            submitted += 1
            filled_qty = float(order.get("filled", qty))
            avg_px = float(order.get("average", cur_px))

            print(
                f"  [{s['side'].upper()}] {sym:<12} {s['strategy']:<30} "
                f"qty={filled_qty:.4f} notional=${notional:.2f} fill=${avg_px:.4f} "
                f"lev={leverage_used}x age={age_min:.1f}min id={order['id']}"
            )

            con.execute(
                "INSERT INTO futures_15m_signals VALUES " "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sig_id,
                    s["ts"],
                    s["bar_close_ts"],
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
                    round(age_min, 1),
                    None,
                ),
            )

            # Protection orders
            prot = place_protection_orders(
                exchange,
                sym,
                s["side"],
                filled_qty,
                float(s["tp_price"]),
                float(s["sl_price"]),
                entry_price=avg_px,
            )
            if prot["status"] == "placed":
                mode = prot.get("mode", "single_target")
                print(
                    f"    [PROTECT-{mode.upper()}] tp=${prot['tp_price']:.4f} sl=${prot['sl_price']:.4f}"
                )
            else:
                print(f"    [PROTECT-ERR] {prot.get('reason')}")

        except Exception as exc:
            rejected += 1
            print(f"  [ERR] {sym}: {type(exc).__name__}: {str(exc)[:100]}")
            con.execute(
                "INSERT INTO futures_15m_signals VALUES " "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sig_id,
                    s["ts"],
                    s["bar_close_ts"],
                    sym,
                    s["strategy"],
                    s["side"],
                    float(s["sl_price"]),
                    float(s["tp_price"]),
                    float(s["confluence"]),
                    3,
                    "error",
                    None,
                    None,
                    None,
                    None,
                    None,
                    round(age_min, 1),
                    str(exc)[:200],
                ),
            )

    con.commit()
    con.close()
    print(
        f"\n[15m RESULT] submitted={submitted}  rejected={rejected}  total={len(signals) + n_stale}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("=" * 80)
    print("FUTURES TRADE 15M (Binance USDM Futures Testnet)")
    print(f"DQ-02: stale_max={SIGNAL_MAX_AGE_MIN}min | TF={TF}")
    print("=" * 80)
    run_15m(dry_run=args.dry_run)
