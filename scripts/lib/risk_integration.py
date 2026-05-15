"""Canlı daemon'lar için RiskOfficer entegrasyon helper'ları.

scripts/futures_trade_daily.py ve scripts/testnet_trade_daily.py kullanır.
src/price_action/risk/* katmanını canlıda da çalıştırır → backtest parity.

Helpers:
    load_risk_officer(yaml_path)            → RiskOfficer + DDBreaker
    build_signal_from_scan(s, venue)        → Signal (Pydantic contract)
    build_returns_df(symbols, days)         → 90g daily log-return matrix
    build_futures_account_state(...)        → AccountState futures için
    build_spot_account_state(...)           → AccountState spot için
    realized_pnl_today_futures(journal)     → bugünkü realized PnL ($)
    realized_pnl_today_spot(journal)        → spot için
    count_consecutive_losses(journal, ...)  → son N trade'de ardışık loss
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from price_action.contracts import Position, Signal
from price_action.risk.breaker import DDBreaker
from price_action.risk.sizing import AccountState, RiskOfficer


# =====================================================================
# RiskOfficer loader
# =====================================================================

def load_risk_officer(
    yaml_path: str | Path = "configs/risk_balanced.yaml",
    breaker_state_path: Path | None = None,
) -> RiskOfficer:
    """RiskOfficer + DDBreaker'ı YAML'dan yükle.

    breaker_state_path verilirse breaker state ayrı dosyada persist edilir
    (futures + spot farklı state tutar).
    """
    import yaml as _yaml

    with Path(yaml_path).open("r", encoding="utf-8") as f:
        raw = _yaml.safe_load(f) or {}
    dd_cfg = raw.get("drawdown_breakers", {})
    if breaker_state_path is not None:
        breaker = DDBreaker(dd_cfg, state_path=Path(breaker_state_path))
    else:
        breaker = DDBreaker(dd_cfg)
    return RiskOfficer(raw, breaker=breaker)


# =====================================================================
# Signal builder
# =====================================================================

def build_signal_from_scan(s: dict, *, venue: str = "binance") -> Signal:
    """scan_signals()'tan dönen dict → Pydantic Signal contract.

    scan_signals çıktısı:
        {ts: pd.Timestamp, symbol, strategy, side, entry_price, sl_price, tp_price,
         confluence, signal_obj}

    entry_price scan_signals'da metadata.atr14 (yanlış kullanım), biz ayrı
    market_price geçeceğiz RiskOfficer'a — metadata'ya raw bırak.
    """
    ts = s["ts"]
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    md: dict[str, Any] = {
        "strategy_id": s.get("strategy", ""),
        "scan_entry_atr14": float(s.get("entry_price", 0) or 0),
    }
    # Orijinal signal obj'den metadata varsa kopyala
    sig_obj = s.get("signal_obj")
    if sig_obj is not None and getattr(sig_obj, "metadata", None):
        md.update(sig_obj.metadata)

    return Signal(
        ts=ts,
        venue=venue,
        symbol=s["symbol"],
        timeframe="1d",
        direction=s["side"],
        pattern_id=s.get("strategy", "unknown"),
        confluence_score=float(s.get("confluence", 0)),
        sl_price=float(s["sl_price"]),
        tp_price=float(s["tp_price"]),
        suggested_size_atr=0.0,
        metadata=md,
    )


# =====================================================================
# Returns DataFrame (korelasyon gate için)
# =====================================================================

def build_returns_df(
    symbols: list[str],
    *,
    days: int = 90,
    market_db: str | Path = "data/market.duckdb",
    timeframe: str = "1d",
    venue: str = "binance",
) -> pd.DataFrame:
    """Açık pozisyonlar + adayı için son N gün daily log-return matrix.

    Boş DataFrame dönerse correlation_gate konservatif (factor=1.0) davranır.
    """
    if not symbols:
        return pd.DataFrame()
    con = duckdb.connect(str(market_db), read_only=True)
    try:
        ph = ", ".join(["?"] * len(symbols))
        rows = con.execute(
            f"""
            SELECT symbol, ts, close
            FROM ohlcv
            WHERE venue = ? AND timeframe = ? AND symbol IN ({ph})
              AND ts >= now() - INTERVAL {int(days) + 5} DAY
            ORDER BY symbol, ts
            """,
            [venue, timeframe, *symbols],
        ).fetchall()
    except Exception:
        con.close()
        return pd.DataFrame()
    con.close()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["symbol", "ts", "close"])
    df = df.pivot(index="ts", columns="symbol", values="close").sort_index()
    if df.empty:
        return df
    rets = np.log(df / df.shift(1)).dropna(how="all")
    return rets.tail(days)


# =====================================================================
# Realized PnL today (DD breaker için)
# =====================================================================

def realized_pnl_today_futures(journal_path: str | Path) -> float:
    """futures_journal'dan bugün için realized PnL (USDT).

    SEC26.B-4 (E1 RISK fix):
    Önce `futures_trades_closed` (TradeJournal) tablosundan SUM oku — gerçek
    kapanan trade'lerin toplamı. Açık pozisyon unrealized dalgalanması daily
    PnL'i kirletmez → DD breaker doğru tetiklenir.

    Tablo yok / boş ise LEGACY fallback: equity_snapshots delta (yanlış ama
    backward-compat — henüz hiç trade kapatılmadıysa eski davranış).
    """
    p = Path(journal_path)
    if not p.exists():
        return 0.0

    # === Primary: futures_trades_closed (SEC26.B-4) ===
    try:
        from price_action.execution.trade_journal import TradeJournal
        # Schema ensure (idempotent CREATE IF NOT EXISTS)
        tj = TradeJournal(db_path=str(p))
        # Bugün için en az 1 kapanmış trade var mı?
        con = duckdb.connect(str(p), read_only=True)
        try:
            cnt_row = con.execute(
                "SELECT COUNT(*) FROM futures_trades_closed WHERE ts_close::DATE = CURRENT_DATE"
            ).fetchone()
            cnt_today = int(cnt_row[0]) if cnt_row else 0
        except Exception:
            cnt_today = 0
        finally:
            con.close()
        if cnt_today > 0:
            return tj.get_realized_pnl_today()
        # cnt_today == 0 → bugün hiç trade kapanmadı, legacy fallback'a düş
    except Exception:
        pass  # TradeJournal load fail → legacy

    # === Legacy fallback: equity_snapshots delta ===
    try:
        con = duckdb.connect(str(p), read_only=True)
        rows = con.execute(
            """
            SELECT MIN(wallet_balance), MAX(wallet_balance), wallet_balance,
                   FIRST_VALUE(wallet_balance) OVER (ORDER BY ts)
            FROM futures_equity_snapshots
            WHERE ts::DATE = CURRENT_DATE
            """
        ).fetchone()
        con.close()
    except Exception:
        return 0.0
    if not rows:
        return 0.0
    try:
        con = duckdb.connect(str(p), read_only=True)
        first_last = con.execute(
            """
            WITH t AS (
                SELECT wallet_balance, ts FROM futures_equity_snapshots
                WHERE ts::DATE = CURRENT_DATE ORDER BY ts
            )
            SELECT (SELECT wallet_balance FROM t ORDER BY ts DESC LIMIT 1)
                 - (SELECT wallet_balance FROM t ORDER BY ts ASC LIMIT 1)
            """
        ).fetchone()
        con.close()
        return float(first_last[0]) if first_last and first_last[0] is not None else 0.0
    except Exception:
        return 0.0


def realized_pnl_today_spot(journal_path: str | Path) -> float:
    """spot testnet bugün realized PnL — equity snapshot delta."""
    p = Path(journal_path)
    if not p.exists():
        return 0.0
    try:
        con = duckdb.connect(str(p), read_only=True)
        row = con.execute(
            """
            WITH t AS (
                SELECT total_value_usdt, ts FROM testnet_equity_snapshots
                WHERE ts::DATE = CURRENT_DATE ORDER BY ts
            )
            SELECT (SELECT total_value_usdt FROM t ORDER BY ts DESC LIMIT 1)
                 - (SELECT total_value_usdt FROM t ORDER BY ts ASC LIMIT 1)
            """
        ).fetchone()
        con.close()
        return float(row[0]) if row and row[0] is not None else 0.0
    except Exception:
        return 0.0


def count_consecutive_losses(
    journal_path: str | Path,
    *,
    lookback_days: int = 30,
    n_max: int = 20,
) -> int:
    """Son N kapanmış trade'in ardışık loss sayısı.

    SEC26.B-3 (2026-05-15): Lab.py semantik parity — `futures_trades_closed`
    tablosunu sorgular. Lab.py mantığı:
      - En son trade'den geriye doğru say
      - Win bulunca dur (streak kırılır)
      - Yalnızca son `lookback_days` günü dikkate al (eski loss'lar saymaz)

    Tablo yoksa veya boşsa 0 döner (backward compat: yeni journal eklenmemiş
    eski daemon kurulumları için).

    Args:
        journal_path: futures_journal.duckdb yolu
        lookback_days: maks geriye bakış penceresi (default 30g)
        n_max: query LIMIT (default 20, lab.py'da counter <=3 hızla resetlenir)

    Returns:
        Ardışık loss sayısı (0 = streak yok veya tablo boş).
    """
    p = Path(journal_path)
    if not p.exists():
        return 0
    try:
        con = duckdb.connect(str(p), read_only=True)
        # Tablo var mı? (eski daemon kurulumları için graceful fallback)
        tbl_exists = con.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = 'futures_trades_closed'
        """).fetchone()
        if not tbl_exists or tbl_exists[0] == 0:
            con.close()
            return 0
        rows = con.execute(
            f"""
            SELECT win FROM futures_trades_closed
            WHERE ts_close >= now() - INTERVAL '{int(lookback_days)} DAY'
            ORDER BY ts_close DESC
            LIMIT {int(n_max)}
            """
        ).fetchall()
        con.close()
    except Exception:
        return 0

    counter = 0
    for row in rows:
        win = row[0]
        if win is False:
            counter += 1
        else:
            break  # win → streak kırılır
    return counter


# =====================================================================
# AccountState builders
# =====================================================================

def build_futures_account_state(
    exchange_state: dict,
    *,
    journal_path: str | Path,
    open_position_records: list[dict] | None = None,
) -> AccountState:
    """Futures exchange state → AccountState.

    exchange_state: fetch_futures_state() çıktısı (wallet/margin/positions...)
    journal_path: futures_journal.duckdb (bugünkü realized PnL için)
    """
    equity = float(exchange_state.get("wallet_balance", 0.0))
    free = float(exchange_state.get("available_balance", equity))
    raw_positions = exchange_state.get("positions", []) or []

    open_positions: list[Position] = []
    now = datetime.now(timezone.utc)
    for p in raw_positions:
        try:
            qty = abs(float(p.get("contracts") or 0.0))
            if qty <= 0:
                continue
            sym_raw = p.get("symbol", "")
            # Normalize perp format "BTC/USDT:USDT" → "BTC/USDT" ki concentration
            # + correlation gate'leri returns_df ve sinyal sym formatıyla eşleşsin.
            sym = sym_raw.split(":")[0] if ":" in sym_raw else sym_raw
            side_raw = p.get("side") or ("long" if float(p.get("contracts", 0)) > 0 else "short")
            side = "long" if side_raw in ("long", "buy") else "short"
            entry = float(p.get("entryPrice") or 0.0)
            mark = float(p.get("markPrice") or entry)
            upnl = float(p.get("unrealizedPnl") or 0.0)
            open_positions.append(
                Position(
                    venue="binance",
                    symbol=sym,
                    side=side,  # type: ignore[arg-type]
                    quantity=qty,
                    entry_price=entry,
                    current_price=mark,
                    unrealized_pnl_usdt=upnl,
                    realized_pnl_usdt=0.0,
                    opened_at=now,
                    strategy_id="",
                    last_updated=now,
                )
            )
        except Exception:
            continue

    pnl_today = realized_pnl_today_futures(journal_path)
    consec = count_consecutive_losses(journal_path)

    return AccountState(
        equity_usdt=equity,
        free_margin_usdt=free,
        open_positions=open_positions,
        realized_pnl_today=pnl_today,
        consecutive_losses=consec,
    )


def build_spot_account_state(
    exchange,
    *,
    journal_path: str | Path,
    traded_currencies: list[str] | None = None,
) -> AccountState:
    """Spot exchange instance → AccountState.

    Spot'ta "free margin" = USDT cash. Pozisyonlar = balance'ta sıfırdan büyük
    ccy'ler (USDT hariç).
    """
    try:
        bal = exchange.fetch_balance()
    except Exception:
        return AccountState(equity_usdt=0.0, free_margin_usdt=0.0)

    usdt = float(bal.get("USDT", {}).get("total", 0.0) or 0.0)
    total = usdt
    open_positions: list[Position] = []
    now = datetime.now(timezone.utc)
    traded = set(traded_currencies or ["BTC", "ETH", "SOL", "BNB", "ADA",
                                       "AVAX", "LINK", "DOT", "DOGE", "XRP"])

    for ccy, info in (bal.get("total") or {}).items():
        try:
            amt = float(info or 0.0)
        except Exception:
            continue
        if amt <= 0.0001 or ccy == "USDT" or ccy not in traded:
            continue
        try:
            ticker = exchange.fetch_ticker(f"{ccy}/USDT")
            px = float(ticker.get("last") or 0.0)
        except Exception:
            continue
        if px <= 0:
            continue
        notional = amt * px
        total += notional
        open_positions.append(
            Position(
                venue="binance",
                symbol=f"{ccy}/USDT",
                side="long",
                quantity=amt,
                entry_price=px,  # spot'ta gerçek entry bilinmiyor, mark kullan
                current_price=px,
                unrealized_pnl_usdt=0.0,
                realized_pnl_usdt=0.0,
                opened_at=now,
                strategy_id="",
                last_updated=now,
            )
        )

    pnl_today = realized_pnl_today_spot(journal_path)
    consec = count_consecutive_losses(journal_path)

    return AccountState(
        equity_usdt=total,
        free_margin_usdt=usdt,  # spot için "free" = USDT cash
        open_positions=open_positions,
        realized_pnl_today=pnl_today,
        consecutive_losses=consec,
    )


__all__ = [
    "load_risk_officer",
    "build_signal_from_scan",
    "build_returns_df",
    "build_futures_account_state",
    "build_spot_account_state",
    "realized_pnl_today_futures",
    "realized_pnl_today_spot",
    "count_consecutive_losses",
]
