"""5m signal scan pipeline — P1c paper bot.

scan_signals_5m(target_bar_close) → 5m sinyal listesi.

P1c W1 base: SADECE vsa_climax_test (15m'in 4-strateji TOP_4'üne karşılık).
Strategy class otomatik 5m manifest (vsa_climax_test_5m.yaml, vm=2.0) yükler
(apply_tf_manifest df["timeframe"]="5m" ile).

Bu modül futures_daemon.py run_5m_mode tarafından çağrılır.
"""
from __future__ import annotations

import os
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from price_action.logging_config import logger

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOLS: list[str] = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
    "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT",
]

TF = "5m"
SIGNAL_MAX_AGE_MIN = 10   # 2 × 5m bar

_DEFAULT_PARALLEL_WORKERS = 8
_SCAN_SYMBOL_TIMEOUT_SEC = 120


def _get_parallel_workers() -> int:
    try:
        val = int(os.environ.get("PA_SCAN_PARALLEL_WORKERS", _DEFAULT_PARALLEL_WORKERS))
        return max(1, val)
    except (ValueError, TypeError):
        return _DEFAULT_PARALLEL_WORKERS


# ── Strategy registry — P1c W1 base (vsa_climax_test only) ────────────────────
_P1C_5M: list[tuple[str, str]] = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
]


def _fetch_bars_ccxt(sym: str, n_bars: int = 500) -> pd.DataFrame:
    """ccxt'ten 5m bar çek — DuckDB'ye dokunma (lock conflict önle).

    futures15m daemon market.duckdb'yi write-mode tutuyor; aynı anda
    okumak imkansız. ccxt direct fetch hem lock-free hem fresh data.
    """
    import ccxt  # type: ignore[import-not-found]
    ex = ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
        "timeout": 20000,
    })
    try:
        raw = ex.fetch_ohlcv(sym, timeframe=TF, limit=n_bars)
        df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df
    except Exception as exc:
        logger.bind(symbol=sym, err=str(exc)).warning("scan5m.ccxt_fetch_fail")
        return pd.DataFrame()


def _scan_symbol(sym: str, target_bar_close: pd.Timestamp) -> list[dict]:
    """Per-symbol 5m scan — thread-safe.

    OHLCV ccxt'ten DOĞRUDAN okunur (DuckDB lock-free).
    Strategy class otomatik 5m manifest yükler (df["timeframe"]="5m"
    ile apply_tf_manifest tetikler).
    """
    sym_signals: list[dict] = []

    df = _fetch_bars_ccxt(sym, n_bars=500)
    if df is None or df.empty:
        return sym_signals

    df = df.sort_values("ts").reset_index(drop=True)

    # SEC57 warm-up: son 500 bar yeterli (5m × 500 = ~42 saat lookback)
    STRATEGY_WARMUP_BARS = 500
    if len(df) > STRATEGY_WARMUP_BARS:
        df = df.tail(STRATEGY_WARMUP_BARS).reset_index(drop=True)

    df["symbol"] = sym
    df["venue"] = "binance"
    df["timeframe"] = TF      # KRİTİK: apply_tf_manifest 5m yaml yükler
    df["vol_z_pre"] = 0

    df_filtered = df[df["ts"] <= target_bar_close]
    if df_filtered.empty:
        return sym_signals

    last_bar_ts = df_filtered["ts"].iloc[-1]
    last_close = float(df_filtered.iloc[-1]["close"])

    for module_name, class_name in _P1C_5M:
        try:
            mod = __import__(
                f"price_action.strategies.{module_name}",
                fromlist=[class_name, "_default_manifest"],
            )
            cls = getattr(mod, class_name)
            manifest_fn = getattr(mod, "_default_manifest", None)
            if not manifest_fn:
                continue
            strategy = cls(manifest_fn())
        except Exception as exc:
            logger.bind(module=module_name, symbol=sym, err=str(exc)).warning(
                "scan5m.strategy_load_fail"
            )
            continue

        try:
            df_prep = strategy.prepare_features(df_filtered.copy())
            sigs = strategy.generate_signals(df_prep)

            # vol_z hesabı (P1c walker M3a sizing için)
            vol_z_val = 0.0
            if "vol_z" in df_prep.columns and len(df_prep) > 0:
                try:
                    vol_z_val = float(df_prep["vol_z"].iloc[-1])
                except (ValueError, IndexError):
                    pass

            for sig in sigs:
                sig_ts = pd.Timestamp(sig.ts)
                if sig_ts.tzinfo is None:
                    sig_ts = sig_ts.tz_localize("UTC")
                if abs((sig_ts - last_bar_ts).total_seconds()) < 60:
                    sym_signals.append({
                        "ts": sig_ts,
                        "bar_close_ts": last_bar_ts,
                        "symbol": sym,
                        "strategy": module_name,
                        "side": sig.direction,
                        "entry_price": last_close,
                        "sl_price": sig.sl_price,
                        "tp_price": sig.tp_price,
                        "confluence": sig.confluence_score,
                        "vol_z": vol_z_val,
                        "signal_obj": sig,
                    })
        except Exception as exc:
            logger.bind(module=module_name, symbol=sym, err=str(exc)).warning(
                "scan5m.symbol_strategy_fail"
            )

    return sym_signals


def scan_signals_5m(
    target_bar_close: datetime,
    max_workers: Optional[int] = None,
) -> list[dict]:
    """target_bar_close öncesindeki 5m barları tara, sinyal üret.

    Strategies: P1c W1 base = vsa_climax_test only.
    P1c walker engulfing_continuation'ı drop_strategies'de ayrıca kapatır
    (zaten _P1C_5M'de yok).
    """
    workers = max_workers if max_workers is not None else _get_parallel_workers()
    tbc = pd.Timestamp(target_bar_close)
    if tbc.tzinfo is None:
        tbc = tbc.tz_localize("UTC")

    all_signals: list[dict] = []

    if workers == 1:
        for sym in SYMBOLS:
            try:
                sym_sigs = _scan_symbol(sym, tbc)
                all_signals.extend(sym_sigs)
            except Exception as exc:
                logger.bind(symbol=sym, err=str(exc)).error("scan5m.sequential_fail")
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(_scan_symbol, sym, tbc): sym
                for sym in SYMBOLS
            }
            for fut in as_completed(future_map):
                sym = future_map[fut]
                try:
                    sym_sigs = fut.result(timeout=_SCAN_SYMBOL_TIMEOUT_SEC)
                    all_signals.extend(sym_sigs)
                except TimeoutError:
                    logger.bind(
                        symbol=sym, timeout_sec=_SCAN_SYMBOL_TIMEOUT_SEC,
                    ).error("scan5m.symbol_timeout")
                except Exception as exc:
                    logger.bind(symbol=sym, err=str(exc)).error("scan5m.symbol_fail")

    all_signals.sort(key=lambda s: (s["ts"], s["symbol"]))

    logger.bind(
        tf=TF, bar=tbc.isoformat(), n_signals=len(all_signals), workers=workers,
    ).info("scan5m.done")
    return all_signals
