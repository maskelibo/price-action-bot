"""Cooldown enforcement — lab.py semantik paritesi.

Lab.py'de uygulanan kural:
  key = (symbol, side)   # strategy farkı YOK — aynı (sym, side) cooldown kapsar
  Check: son ACCEPTED fill'den bu yana gün sayısı < cooldown_days → reject

Bu modül paper/futures daily trade script'lerinin scan_signals() çıktısına
uygulanır. Backtest ile birebir parity: aynı kural, aynı semantik.

Public API:
  filter_signals_by_cooldown(signals, cooldown_days, journal_path, table) -> list[dict]
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)


def _query_recent_fills(
    journal_path: Path,
    table: str,
    cooldown_days: int,
) -> list[dict]:
    """journal_path/table'dan son cooldown_days içindeki 'filled' kayıtları döner.

    Dönen dict keys: symbol, side, ts (datetime, UTC-aware)

    Returns [] if table doesn't exist or db is unreachable.
    """
    if not journal_path.exists():
        return []
    try:
        con = duckdb.connect(str(journal_path), read_only=True)
        cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)
        try:
            rows = con.execute(
                f"""
                SELECT symbol, side, ts
                FROM {table}
                WHERE status = 'filled'
                  AND ts >= ?
                ORDER BY ts DESC
                """,
                [cutoff],
            ).fetchall()
        except duckdb.CatalogException:
            # Table henüz yok (ilk çalıştırma)
            rows = []
        finally:
            con.close()

        result = []
        for sym, side, ts in rows:
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            else:
                # DuckDB bazı durumlarda string dönebilir
                ts = datetime.fromisoformat(str(ts)).replace(tzinfo=timezone.utc)
            result.append({"symbol": sym, "side": side, "ts": ts})
        return result
    except Exception as exc:
        log.warning("cooldown: recent_fills query failed: %s", exc)
        return []


def _build_last_entry(recent_fills: list[dict]) -> dict[tuple, datetime]:
    """(symbol, side) -> en son fill ts mapping'i oluşturur."""
    last: dict[tuple, datetime] = {}
    for row in sorted(recent_fills, key=lambda r: r["ts"]):
        key = (row["symbol"], row["side"])
        last[key] = row["ts"]
    return last


def is_in_cooldown(
    signal: dict,
    last_entry: dict[tuple, datetime],
    cooldown_days: int,
) -> bool:
    """Sinyal cooldown altında mı? Lab.py semantiği:
      key = (symbol, side)  — strategy farketmez
      (signal_ts - last_fill_ts).days < cooldown_days → True (reject)
    """
    key = (signal["symbol"], signal["side"])
    prev = last_entry.get(key)
    if prev is None:
        return False
    sig_ts: datetime = signal["ts"]
    if sig_ts.tzinfo is None:
        sig_ts = sig_ts.replace(tzinfo=timezone.utc)
    delta_days = (sig_ts - prev).days
    return delta_days < cooldown_days


def filter_signals_by_cooldown(
    signals: list[dict],
    cooldown_days: int,
    journal_path: Path,
    table: str = "futures_signals",
) -> list[dict]:
    """scan_signals() çıktısını cooldown filtresinden geçirir.

    Args:
        signals: scan_signals()'dan gelen raw sinyal listesi
        cooldown_days: YAML same_symbol_side_cooldown_days değeri
        journal_path: DuckDB journal dosyası
        table: kontrol edilecek tablo adı ('futures_signals' veya 'paper_signals')

    Returns:
        cooldown dışında kalan sinyaller (filtered list, orijinal sıra korunur)

    Semantik (lab.py parity):
        key = (symbol, side)  — farklı strategy aynı (sym,side) cooldown kapsar
        cooldown_days <= 0 ise no-op (filter bypass)
    """
    if cooldown_days <= 0:
        return list(signals)

    recent_fills = _query_recent_fills(journal_path, table, cooldown_days)
    last_entry = _build_last_entry(recent_fills)

    filtered: list[dict] = []
    for sig in signals:
        if is_in_cooldown(sig, last_entry, cooldown_days):
            log.info(
                "COOLDOWN_REJECT: sym=%s side=%s strategy=%s "
                "(last_fill=%s, cooldown=%dd)",
                sig["symbol"],
                sig["side"],
                sig.get("strategy", "?"),
                last_entry.get((sig["symbol"], sig["side"])),
                cooldown_days,
            )
            print(
                f"  [COOLDOWN_REJECT] sym={sig['symbol']:<10} side={sig['side']:<5} "
                f"strategy={sig.get('strategy','?')}"
            )
        else:
            filtered.append(sig)

    n_rejected = len(signals) - len(filtered)
    if n_rejected > 0:
        pct = n_rejected / len(signals) * 100
        log.info(
            "cooldown: %d/%d signals rejected (%.0f%%) cooldown_days=%d",
            n_rejected, len(signals), pct, cooldown_days,
        )
        if pct >= 50:
            log.warning(
                "cooldown: %.0f%% signals rejected — max_open_positions veya "
                "cooldown_days ayarını kontrol et",
                pct,
            )
    return filtered
