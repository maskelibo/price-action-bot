"""Journal/Exchange state reconciler (Faz 14.6 — 2026-05-26).

Problem: futures_signals tablosunda status='filled' olan trade'ler bazen
trade_journal.record_close çağrılmadan kapanıyor (DMS flatten, manual,
veya code path açığı). Sonuç: journal "açık" der ama borsada yok.

Bu script:
1. Borsadan açık pozisyon listesini çek (ccxt).
2. Journal'da status='filled' AND signal_id NOT IN trades_closed olanları çek.
3. Mismatch:
   - Journal'da açık ama borsada yok → "orphan", close olarak kayıt et
     (close_reason='reconcile_orphan', exit_price=current_market_price)
   - Borsada var ama journal'da yok → "phantom", LOG + Telegram alert
     (otomatik kapatma yok — Principal incelemeli)

Cron: her 15dk (15M bar close ile aynı pencere).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_REPO = Path(__file__).resolve().parent.parent
_JOURNAL = _REPO / "data" / "futures_journal.duckdb"
_REPORT_DIR = _REPO / "reports" / "reconcile"


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _fetch_exchange_positions() -> dict[str, dict]:
    """Borsadan açık pozisyon listesi (symbol → {qty, side, entry, mark})."""
    try:
        import ccxt
        ex = ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
            "apiKey": os.environ.get("PA_BINANCE_API_KEY", ""),
            "secret": os.environ.get("PA_BINANCE_SECRET", ""),
        })
        if os.environ.get("PA_RUN_MODE", "paper") == "paper":
            ex.set_sandbox_mode(True)
        raw = ex.fetch_positions()
    except Exception as exc:
        _log(f"exchange_fetch_fail: {exc}")
        return {}
    out: dict[str, dict] = {}
    for r in raw or []:
        qty = float(r.get("contracts") or r.get("amount") or 0.0)
        if qty <= 0:
            continue
        sym = r.get("symbol", "")
        out[sym] = {
            "symbol": sym,
            "side": "long" if r.get("side") in ("long", "buy") else "short",
            "qty": qty,
            "entry_price": float(r.get("entryPrice") or 0.0),
            "mark_price": float(r.get("markPrice") or 0.0),
            "unrealized_pnl": float(r.get("unrealizedPnl") or 0.0),
        }
    return out


def _fetch_journal_open_positions() -> list[dict]:
    """Journal'da status='filled' olan ama trades_closed'de olmayan signal'ler."""
    if not _JOURNAL.exists():
        return []
    try:
        import duckdb
        con = duckdb.connect(str(_JOURNAL), read_only=True)
        try:
            df = con.execute("""
                SELECT s.signal_id, s.ts, s.symbol, s.strategy, s.side,
                       s.fill_price, s.fill_qty, s.notional_usdt, s.sl_price, s.tp_price
                  FROM futures_signals s
                 WHERE s.status = 'filled'
                   AND s.signal_id NOT IN (SELECT trade_id FROM futures_trades_closed)
                 ORDER BY s.ts
            """).fetchdf()
        finally:
            con.close()
    except Exception as exc:
        _log(f"journal_read_fail: {exc}")
        return []
    return df.to_dict("records")


def _close_orphan(orphan: dict, exit_price: float) -> bool:
    """Journal'da orphan trade'i close olarak kaydet."""
    try:
        from price_action.execution.trade_journal import TradeJournal
        tj = TradeJournal(db_path=str(_JOURNAL))
        ts_open = orphan["ts"]
        if hasattr(ts_open, "to_pydatetime"):
            ts_open = ts_open.to_pydatetime()
        # tz-naive → UTC ata
        if ts_open.tzinfo is None:
            ts_open = ts_open.replace(tzinfo=timezone.utc)
        return tj.record_close(
            trade_id=str(orphan["signal_id"]),
            ts_open=ts_open,
            ts_close=datetime.now(timezone.utc),
            sym=str(orphan["symbol"]),
            side=str(orphan["side"]).lower(),  # type: ignore[arg-type]
            strategy=str(orphan["strategy"] or ""),
            entry_price=float(orphan["fill_price"] or 0.0),
            exit_price=float(exit_price),
            qty=float(orphan["fill_qty"] or 0.0),
            sl_price=float(orphan["sl_price"] or 0.0),
            close_reason="reconcile_orphan",  # type: ignore[arg-type]
        )
    except Exception as exc:
        _log(f"close_orphan_fail({orphan.get('signal_id')}): {exc}")
        return False


def _push_phantom_alert(phantoms: list[dict]) -> None:
    """Borsada var, journal'da yok → Principal incelemeli."""
    if not phantoms:
        return
    try:
        from price_action.orchestrator.notifications import push_critical
        lines = [
            f"⚠️ JOURNAL DRIFT — {len(phantoms)} 'phantom' pozisyon",
            "Borsada var, journal'da kayıt yok:",
        ]
        for p in phantoms:
            lines.append(
                f"  - {p['symbol']} {p['side'].upper()} qty={p['qty']:g} "
                f"@${p['entry_price']:.4f} (unrealized ${p['unrealized_pnl']:+.2f})"
            )
        lines.append(
            "Olası sebep: restart anomalisi, manuel order, code path açığı. "
            "Otomatik kapatılmadı — gözden geçir."
        )
        push_critical("\n".join(lines), source="reconciler")
    except Exception as exc:
        _log(f"phantom_push_fail: {exc}")


def reconcile() -> dict:
    """Ana reconcile fonksiyonu."""
    stats = {"exchange_pos": 0, "journal_open": 0,
             "orphans_closed": 0, "phantoms": 0, "in_sync": 0,
             "exchange_fetch_ok": False}

    exchange = _fetch_exchange_positions()
    journal = _fetch_journal_open_positions()
    stats["exchange_pos"] = len(exchange)
    stats["journal_open"] = len(journal)
    stats["exchange_fetch_ok"] = True  # placeholder

    # FIX 2026-05-26: SAFE MODE — exchange fetch fail + journal'da açık varsa
    # tümünü orphan sanma (yanlış kapanış riski). Önce kontrol et:
    # Eğer ccxt fetch_positions boş döndü AMA journal'da açık varsa,
    # API key eksikliği veya geçici hata olabilir → reconcile ETME, alert at.
    if len(exchange) == 0 and len(journal) > 0:
        _log(f"SAFE_MODE: exchange empty but journal has {len(journal)} open — "
             f"reconcile SKIPPED (API key veya fetch fail muhtemel)")
        stats["exchange_fetch_ok"] = False
        try:
            from price_action.orchestrator.notifications import push_critical
            push_critical(
                f"Reconciler SAFE_MODE — exchange fetch_positions boş döndü "
                f"({len(journal)} journal açık). API key eksik veya fetch fail. "
                f"Orphan close yapılmadı (yanlış kapanış riski).",
                source="reconciler",
            )
        except Exception:
            pass
        return stats

    # Symbol bazlı eşleştirme
    exchange_symbols = set(exchange.keys())
    journal_symbols = {j["symbol"] for j in journal}

    # 1. Orphan: journal'da var, borsada yok → close
    orphans = [j for j in journal if j["symbol"] not in exchange_symbols]
    for o in orphans:
        # Exit price = current market price (mark)
        try:
            import ccxt
            ex = ccxt.binance({
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            })
            if os.environ.get("PA_RUN_MODE", "paper") == "paper":
                ex.set_sandbox_mode(True)
            ticker = ex.fetch_ticker(o["symbol"])
            exit_px = float(ticker.get("last") or o["fill_price"])
        except Exception:
            exit_px = float(o["fill_price"] or 0.0)
        if _close_orphan(o, exit_px):
            stats["orphans_closed"] += 1
            _log(f"ORPHAN_CLOSED: {o['symbol']} {o['side']} sig={o['signal_id']} "
                 f"entry=${o['fill_price']:.4f} exit=${exit_px:.4f}")

    # 2. Phantom: borsada var, journal'da yok → alert
    phantoms = [exchange[s] for s in exchange_symbols if s not in journal_symbols]
    stats["phantoms"] = len(phantoms)
    if phantoms:
        _push_phantom_alert(phantoms)
        for p in phantoms:
            _log(f"PHANTOM: {p['symbol']} {p['side']} qty={p['qty']} "
                 f"@${p['entry_price']:.4f}")

    # 3. In-sync: ikisinde de var
    stats["in_sync"] = len(exchange_symbols & journal_symbols)

    return stats


def write_report(stats: dict, *, orphans: int = 0, phantoms: int = 0) -> Path:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    path = _REPORT_DIR / f"reconcile-{now.strftime('%Y-%m-%d-%H%M')}.json"
    payload = {
        "ts": now.isoformat(),
        "stats": stats,
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def main() -> int:
    stats = reconcile()
    write_report(stats)
    _log(f"DONE: {json.dumps(stats)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
