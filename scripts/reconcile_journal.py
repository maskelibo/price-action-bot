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
    """Borsadan açık pozisyon listesi.

    FIX 2026-05-26 (Faz 14.8): 2 yol önce dene:
    1) ccxt fetch_positions (gerçek, ama API key gerek)
    2) Fallback: futures15m daemon POS_CHECK log'unu parse et
       (her 15dk bot zaten fetch_positions yapıyor, log'a yazıyor)

    POS_CHECK format:
      "[HH:MM:SS] POS_CHECK: N pos, M algo (TP+SL) | SYM=L0.179@$X->Y(+Z) | ..."
    """
    out: dict[str, dict] = {}

    # 1) ccxt try
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
                "source": "ccxt",
            }
        if out:
            return out
    except Exception as exc:
        _log(f"ccxt_fetch_fail (POS_CHECK log fallback'a geçiliyor): {exc}")

    # 2) Fallback — POS_CHECK log parse
    import re
    log_path = _REPO / "logs" / "launchd" / "futures15m.stderr.log"
    if not log_path.exists():
        return out
    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-200:]  # son ~200 satır yeter (15dk × ~13 = 3h)
        # En son POS_CHECK satırını bul
        last_poscheck = None
        for line in reversed(lines):
            if "POS_CHECK:" in line and "|" in line:
                last_poscheck = line.strip()
                break
        if not last_poscheck:
            return out
        # Parse: "SYM=L0.179@$X->Y(+Z)" — L/S = long/short, qty, entry, mark, pnl
        # Log'da sembol "/USDT" suffix'siz yazılıyor (örn. "DOGE=L5554...")
        # → /USDT suffix'i biz ekleyeceğiz (binance futures default).
        pos_pattern = re.compile(
            r"([A-Z]{2,10})=([LS])([\d.]+)@\$([\d.]+)->([\d.]+)\(([+\-]?[\d.]+)\)"
        )
        for m in pos_pattern.finditer(last_poscheck):
            sym_raw, side_ch, qty, entry, mark, pnl = m.groups()
            sym = f"{sym_raw}/USDT" if "/" not in sym_raw else sym_raw
            out[sym] = {
                "symbol": sym,
                "side": "long" if side_ch == "L" else "short",
                "qty": float(qty),
                "entry_price": float(entry),
                "mark_price": float(mark),
                "unrealized_pnl": float(pnl),
                "source": "log_parse",
            }
        if out:
            _log(f"POS_CHECK_FALLBACK: {len(out)} pozisyon log'dan okundu")
    except Exception as exc:
        _log(f"log_parse_fail: {exc}")

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
        # FIX 2026-05-26 (Faz 14.8): throttle (1h) — her 15dk spam etmesin
        try:
            from price_action.ops.telegram_throttle import get_telegram_throttle
            get_telegram_throttle().send_throttled(
                alert_type="reconciler_safe_mode",
                message=(
                    f"⚠️ Reconciler güvenli mod — exchange bağlantısı yok.\n"
                    f"Journal'da {len(journal)} açık pozisyon var ama borsadan "
                    f"liste çekilemedi (API key eksik veya log parse fail). "
                    f"Otomatik kapanış DURDURULDU (yanlış kayıp önleme). "
                    f"Bot trade etmeye devam ediyor; sadece journal sync gecikiyor."
                ),
                level="WARNING",
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
    # FIX 2026-05-28 (Faz 14.27): phantom alert push_critical çalışıyor
    # (P0-1 test ile doğrulandı, Telegram zinciri sağlam). Açık her tetikte
    # alert tekrarlanır (idempotent). Manuel kapatma gerekli — otomatik close
    # YOK çünkü borsadaki kullanıcı manuel pozisyon olabilir.
    phantoms = [exchange[s] for s in exchange_symbols if s not in journal_symbols]
    stats["phantoms"] = len(phantoms)
    if phantoms:
        _push_phantom_alert(phantoms)
        for p in phantoms:
            _log(f"PHANTOM: {p['symbol']} {p['side']} qty={p['qty']} "
                 f"@${p['entry_price']:.4f}")
        # Defansif: phantom sayısı > 0 her zaman ek stats field — Bot Monitor okusun
        stats["phantom_symbols"] = [p["symbol"] for p in phantoms]
        stats["phantom_total_notional"] = round(
            sum(abs(float(p.get("qty", 0)) * float(p.get("entry_price", 0)))
                for p in phantoms), 2)

    # 3. In-sync: ikisinde de var
    stats["in_sync"] = len(exchange_symbols & journal_symbols)

    # 4. FIX 2026-05-28 (Faz 14.27 C5): Open trades count sanity check.
    # Önceki bug: bot'un journal'daki open count vs exchange position count
    # karşılaştırılmıyordu. Her ikisini aynı sembol için karşılaştırmak
    # journal staleness'i yakalar.
    sync_mismatches = []
    for sym in exchange_symbols & journal_symbols:
        # Aynı sembol için qty doğrula
        ex_qty = abs(float(exchange[sym].get("qty", 0)))
        # Journal'da bu sembol için açık olan tek bir trade olmalı
        j_match = [j for j in journal if j["symbol"] == sym]
        if not j_match:
            continue
        j_qty = abs(float(j_match[0].get("fill_qty", 0)))
        if ex_qty > 0 and j_qty > 0:
            diff_pct = abs(ex_qty - j_qty) / max(ex_qty, j_qty)
            if diff_pct > 0.05:  # >%5 qty drift
                sync_mismatches.append({
                    "symbol": sym,
                    "exchange_qty": ex_qty,
                    "journal_qty": j_qty,
                    "diff_pct": round(diff_pct * 100, 2),
                })
    stats["sync_mismatches"] = sync_mismatches
    if sync_mismatches:
        try:
            from price_action.orchestrator.notifications import push_critical
            push_critical(
                f"⚠️ JOURNAL/EXCHANGE QTY DRIFT — {len(sync_mismatches)} sembol "
                f">5% qty fark: {sync_mismatches[:3]}",
                source="reconciler_qty_drift",
            )
        except Exception:
            pass

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
