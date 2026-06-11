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
from datetime import UTC, datetime
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_REPO = Path(__file__).resolve().parent.parent
# FIX 2026-06-04: champion (futures_journal.duckdb) EMEKLİ — donmuş journal'ında
# dangling ZEC short kalmıştı → her döngüde phantom/drift alarmı. Canlı 15m bot
# artık v13 (futures_journal_v13.duckdb). PA_BOT_NAME ile override edilebilir;
# default canlı bota işaret eder.
# FIX 2026-06-11: v13 EMEKLİ → canlı bot v14 (futures_journal_v14.duckdb).
# Reconciler donmuş v13 journal'ına bakıp v14'ü kör bırakıyordu. (5m ayrı hesap paylaşımı: nadir poz →
# kabul edilebilir kısıt.)
_BOT = os.environ.get("PA_BOT_NAME", "v14").strip()
_JOURNAL = _REPO / "data" / (
    f"futures_journal_{_BOT}.duckdb" if _BOT and _BOT not in ("default", "") else "futures_journal.duckdb"
)
_REPORT_DIR = _REPO / "reports" / "reconcile"


def _log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
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

        ex = ccxt.binance(
            {
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
                "apiKey": os.environ.get("PA_BINANCE_API_KEY", ""),
                "secret": os.environ.get("PA_BINANCE_SECRET", ""),
            }
        )
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
    """Journal'da status='filled' olan ama trades_closed'de olmayan signal'ler.

    PARTIAL-AWARE (2026-05-31): Her açık signal için kalan qty hesaplanır:
    remaining_qty = fill_qty - SUM(futures_partial_closes.qty_closed)
    Sonuç dict'e 'remaining_qty' alanı eklenir; qty-drift kontrolü bunu kullanır.
    """
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
            # Partial closes toplamını al (tablo yoksa 0)
            try:
                partial_df = con.execute("""
                    SELECT trade_id, COALESCE(SUM(qty_closed), 0.0) AS partial_sum
                      FROM futures_partial_closes
                     WHERE trade_id IN (
                         SELECT signal_id FROM futures_signals
                          WHERE status = 'filled'
                            AND signal_id NOT IN (SELECT trade_id FROM futures_trades_closed)
                     )
                     GROUP BY trade_id
                """).fetchdf()
                partial_map = dict(
                    zip(partial_df["trade_id"], partial_df["partial_sum"])
                ) if not partial_df.empty else {}
            except Exception:
                partial_map = {}
        finally:
            con.close()
    except Exception as exc:
        _log(f"journal_read_fail: {exc}")
        return []
    records = df.to_dict("records")
    for r in records:
        fill_qty = float(r.get("fill_qty") or 0.0)
        partial_sum = float(partial_map.get(str(r["signal_id"]), 0.0))
        r["remaining_qty"] = max(0.0, fill_qty - partial_sum)
    return records


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
            ts_open = ts_open.replace(tzinfo=UTC)
        # PARTIAL-CLOSE FIX (2026-05-31): kalan (runner) qty ile kapat, TAM fill_qty
        # DEĞİL. Aksi halde kısmi TP'ler (futures_partial_closes) zaten yazılmışken
        # final orphan kapanışı tüm qty'yi tekrar yazar → realized PnL ÇİFT SAYIM.
        # remaining_qty = fill_qty − SUM(partials); legacy (partial yok) için == fill_qty.
        _remaining = orphan.get("remaining_qty")
        if _remaining is None:
            _remaining = float(orphan.get("fill_qty") or 0.0)
        return tj.record_close(
            trade_id=str(orphan["signal_id"]),
            ts_open=ts_open,
            ts_close=datetime.now(UTC),
            sym=str(orphan["symbol"]),
            side=str(orphan["side"]).lower(),  # type: ignore[arg-type]
            strategy=str(orphan["strategy"] or ""),
            entry_price=float(orphan["fill_price"] or 0.0),
            exit_price=float(exit_price),
            qty=float(_remaining),
            sl_price=float(orphan["sl_price"] or 0.0),
            close_reason="reconcile_orphan",  # type: ignore[arg-type]
        )
    except Exception as exc:
        _log(f"close_orphan_fail({orphan.get('signal_id')}): {exc}")
        return False


def _phantom_dedup(phantoms: list[dict], *, ttl_hours: float = 12.0) -> list[dict]:
    """FIX 2026-05-30: aynı phantom her döngüde (15dk) tekrar alarm basıyordu —
    spam. Dedup: phantom imzası (symbol+side+qty) state dosyasında; aynı imza
    ttl_hours içinde tekrar bildirilmez. Yeni/değişen phantom hemen geçer.
    Stuck-doc dedup deseninin reconciler-paraleli."""
    import json
    import time
    from pathlib import Path

    state_p = Path(__file__).resolve().parents[1] / "logs" / "state" / "phantom_alerts.json"
    state_p.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    try:
        seen = json.loads(state_p.read_text())
    except Exception:
        seen = {}
    fresh: list[dict] = []
    for p in phantoms:
        sig = f"{p['symbol']}:{p['side']}:{round(float(p['qty']), 2)}"
        last = float(seen.get(sig, 0) or 0)
        if now - last >= ttl_hours * 3600:
            fresh.append(p)
            seen[sig] = now
    # eski imzaları temizle (ttl×2'den eski)
    seen = {k: v for k, v in seen.items() if now - float(v or 0) < ttl_hours * 7200}
    try:
        state_p.write_text(json.dumps(seen))
    except Exception:
        pass
    return fresh


def _qty_drift_dedup(mismatches: list[dict], *, ttl_hours: float = 12.0) -> list[dict]:
    """FIX 2026-05-31: qty-drift alarmı dedup'suzdu → aynı drift her reconcile
    döngüsünde (15dk) tekrar alarm basıyordu (ALGO 30% vakası). İmza: symbol +
    drift bucket (5%'lik kova) state dosyasında; aynı imza ttl_hours içinde tekrar
    bildirilmez. Drift büyürse (yeni kova) hemen geçer. _phantom_dedup paraleli."""
    import json
    import time
    from pathlib import Path

    state_p = Path(__file__).resolve().parents[1] / "logs" / "state" / "qty_drift_alerts.json"
    state_p.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    try:
        seen = json.loads(state_p.read_text())
    except Exception:
        seen = {}
    fresh: list[dict] = []
    for m in mismatches:
        # bucket: 5%'lik dilim → drift büyüyünce (örn %30→%40) yeni imza, hemen geçer
        bucket = int(float(m.get("diff_pct", 0)) // 5)
        sig = f"{m['symbol']}:{bucket}"
        last = float(seen.get(sig, 0) or 0)
        if now - last >= ttl_hours * 3600:
            fresh.append(m)
            seen[sig] = now
    # eski imzaları temizle (ttl×2'den eski)
    seen = {k: v for k, v in seen.items() if now - float(v or 0) < ttl_hours * 7200}
    try:
        state_p.write_text(json.dumps(seen))
    except Exception:
        pass
    return fresh


def _push_phantom_alert(phantoms: list[dict]) -> None:
    """Borsada var, journal'da yok → Principal incelemeli. Dedup'lı (12h/imza)."""
    if not phantoms:
        return
    phantoms = _phantom_dedup(phantoms)
    if not phantoms:
        return  # hepsi son 12h'de zaten bildirildi → spam yapma
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
            "Otomatik kapatılmadı — gözden geçir. (Aynı phantom 12h tekrar bildirilmez.)"
        )
        push_critical("\n".join(lines), source="reconciler")
    except Exception as exc:
        _log(f"phantom_push_fail: {exc}")


def reconcile() -> dict:
    """Ana reconcile fonksiyonu."""
    stats = {
        "exchange_pos": 0,
        "journal_open": 0,
        "orphans_closed": 0,
        "phantoms": 0,
        "in_sync": 0,
        "exchange_fetch_ok": False,
    }

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
        _log(
            f"SAFE_MODE: exchange empty but journal has {len(journal)} open — "
            f"reconcile SKIPPED (API key veya fetch fail muhtemel)"
        )
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
    # PARTIAL-AWARE (2026-05-31): Orphan sadece remaining_qty > epsilon ise geçerli.
    # remaining_qty=0 olan trade zaten tüm partial'ları kapanmış demektir → orphan değil.
    # FIX 2026-05-30 (INC1-reconcile-exit-px): exit_price daha önce fetch_ticker
    # (anlık piyasa fiyatı) kullanıyordu. Bu GERÇEĞİ yansıtmaz —
    # pozisyon farklı bir fiyatta kapandıysa PnL yanlış yazılır (XLM vakası:
    # 0.25819 ticker vs 0.24959 gerçek fill). Düzeltme öncelik sırası:
    #   1) fapiPrivateGetAllOrders (kapanış tarihi yakın, reduceOnly fill)
    #   2) ticker (son çare)
    #   3) entry_price (en kötü durum — PnL=0 yazmak yanlış kayıptan iyidir)
    _ORPHAN_QTY_EPSILON = 1e-6
    orphans = [
        j for j in journal
        if j["symbol"] not in exchange_symbols
        and float(j.get("remaining_qty", j.get("fill_qty", 0))) > _ORPHAN_QTY_EPSILON
    ]
    for o in orphans:
        exit_px = float(o["fill_price"] or 0.0)  # fallback = entry (PnL=0)
        try:
            import ccxt

            ex = ccxt.binance(
                {
                    "enableRateLimit": True,
                    "options": {"defaultType": "future"},
                    "apiKey": os.environ.get("PA_BINANCE_API_KEY", ""),
                    "secret": os.environ.get("PA_BINANCE_SECRET", ""),
                }
            )
            if os.environ.get("PA_RUN_MODE", "paper") == "paper":
                ex.set_sandbox_mode(True)
            _sym_id = (
                str(o["symbol"])
                .replace("/USDT:USDT", "USDT")
                .replace("/USDT", "USDT")
                .replace("/", "")
            )
            _actual_exit: float | None = None
            # 1) Son 50 closed order içinden en güncel reduceOnly fill'i bul
            try:
                _hist = ex.fapiPrivateGetAllOrders(
                    {
                        "symbol": _sym_id,
                        "limit": 50,
                    }
                )
                # reduceOnly=True ve status=FILLED olan en son order
                _reduce_fills = [
                    _h
                    for _h in (_hist or [])
                    if str(_h.get("status", "")).upper() == "FILLED"
                    and (
                        str(_h.get("reduceOnly", "false")).lower() == "true"
                        or bool(_h.get("reduceOnly"))
                    )
                ]
                if _reduce_fills:
                    # En yeni (updateTime büyük olan)
                    _latest = max(_reduce_fills, key=lambda h: int(h.get("updateTime", 0) or 0))
                    _ap = _latest.get("avgPrice") or _latest.get("price")
                    if _ap and float(_ap) > 0:
                        _actual_exit = float(_ap)
                        _log(
                            f"ORPHAN_EXIT_FROM_ORDER: {o['symbol']} "
                            f"exit=${_actual_exit:.5f} (reduceOnly fill)"
                        )
            except Exception as _hist_err:
                _log(f"ORPHAN_HIST_FAIL {o['symbol']}: {str(_hist_err)[:80]}")
            # 2) Algo order history (TP/SL hit)
            if _actual_exit is None:
                try:
                    _algo_hist = ex.fapiPrivateGetAllAlgoOrders({"symbol": _sym_id, "limit": 30})
                    _triggered = [
                        _a
                        for _a in (_algo_hist or [])
                        if str(_a.get("algoStatus", "")).upper() in ("TRIGGERED", "FINISHED")
                    ]
                    if _triggered:
                        _latest_algo = max(
                            _triggered, key=lambda h: int(h.get("updateTime", 0) or 0)
                        )
                        _tp = _latest_algo.get("triggerPrice")
                        if _tp and float(_tp) > 0:
                            _actual_exit = float(_tp)
                            _log(
                                f"ORPHAN_EXIT_FROM_ALGO: {o['symbol']} "
                                f"exit=${_actual_exit:.5f} (algo trigger)"
                            )
                except Exception as _algo_err:
                    _log(f"ORPHAN_ALGO_HIST_FAIL {o['symbol']}: {str(_algo_err)[:80]}")
            # 3) ticker fallback
            if _actual_exit is None:
                try:
                    ticker = ex.fetch_ticker(o["symbol"])
                    _ticker_px = float(ticker.get("last") or 0.0)
                    if _ticker_px > 0:
                        _actual_exit = _ticker_px
                        _log(
                            f"ORPHAN_EXIT_TICKER_FALLBACK: {o['symbol']} "
                            f"exit=${_actual_exit:.5f} (WARNING: may not be actual fill)"
                        )
                except Exception:
                    pass
            if _actual_exit is not None and _actual_exit > 0:
                exit_px = _actual_exit
        except Exception as _ex_err:
            _log(f"ORPHAN_EXIT_FETCH_ERR {o['symbol']}: {str(_ex_err)[:80]}")
        if _close_orphan(o, exit_px):
            stats["orphans_closed"] += 1
            _log(
                f"ORPHAN_CLOSED: {o['symbol']} {o['side']} sig={o['signal_id']} "
                f"entry=${o['fill_price']:.4f} exit=${exit_px:.4f}"
            )

    # 2. Phantom: borsada var, journal'da yok → alert
    # PARTIAL-AWARE (2026-05-31): journal_symbols'u remaining_qty>epsilon olan
    # trade'lerden üret. remaining_qty=0 olan trade "journal'da açık" sayılmaz.
    # FIX 2026-05-28 (Faz 14.27): phantom alert push_critical çalışıyor
    # (P0-1 test ile doğrulandı, Telegram zinciri sağlam). Açık her tetikte
    # alert tekrarlanır (idempotent). Manuel kapatma gerekli — otomatik close
    # YOK çünkü borsadaki kullanıcı manuel pozisyon olabilir.
    journal_symbols_active = {
        j["symbol"]
        for j in journal
        if float(j.get("remaining_qty", j.get("fill_qty", 0))) > _ORPHAN_QTY_EPSILON
    }
    phantoms = [exchange[s] for s in exchange_symbols if s not in journal_symbols_active]
    stats["phantoms"] = len(phantoms)
    if phantoms:
        _push_phantom_alert(phantoms)
        for p in phantoms:
            _log(f"PHANTOM: {p['symbol']} {p['side']} qty={p['qty']} " f"@${p['entry_price']:.4f}")
        # Defansif: phantom sayısı > 0 her zaman ek stats field — Bot Monitor okusun
        stats["phantom_symbols"] = [p["symbol"] for p in phantoms]
        stats["phantom_total_notional"] = round(
            sum(abs(float(p.get("qty", 0)) * float(p.get("entry_price", 0))) for p in phantoms), 2
        )

    # 3. In-sync: ikisinde de var (partial-aware: remaining_qty>epsilon olan journal kayıtları)
    stats["in_sync"] = len(exchange_symbols & journal_symbols_active)

    # 4. FIX 2026-05-28 (Faz 14.27 C5): Open trades count sanity check.
    # PARTIAL-AWARE (2026-05-31): qty karşılaştırması fill_qty DEĞİL remaining_qty
    # kullanır. remaining_qty = fill_qty - SUM(partial_closes). Örn: fill_qty=100,
    # TP1 %25 fill → remaining=75. Exchange de 75 gösteriyorsa — senkron.
    # Önceki: fill_qty=100 vs exchange_qty=75 → %25 drift alarmı (yanlış-pozitif).
    sync_mismatches = []
    for sym in exchange_symbols & journal_symbols:
        # Aynı sembol için qty doğrula
        ex_qty = abs(float(exchange[sym].get("qty", 0)))
        # Journal'da bu sembol için açık olan tek bir trade olmalı
        j_match = [j for j in journal if j["symbol"] == sym]
        if not j_match:
            continue
        # PARTIAL-AWARE: remaining_qty varsa onu kullan, yoksa fill_qty fallback
        j_remaining = float(j_match[0].get("remaining_qty", j_match[0].get("fill_qty", 0)))
        j_qty_display = float(j_match[0].get("fill_qty", 0))  # log'da göster
        if ex_qty > 0 and j_remaining > 0:
            diff_pct = abs(ex_qty - j_remaining) / max(ex_qty, j_remaining)
            if diff_pct > 0.05:  # >%5 qty drift
                sync_mismatches.append(
                    {
                        "symbol": sym,
                        "exchange_qty": ex_qty,
                        "journal_qty": j_remaining,
                        "journal_fill_qty": j_qty_display,
                        "diff_pct": round(diff_pct * 100, 2),
                    }
                )
    stats["sync_mismatches"] = sync_mismatches
    if sync_mismatches:
        # FIX 2026-05-31: qty-drift alarmı dedup'suzdu → aynı drift her döngüde
        # (15dk) tekrar basıyordu (ALGO vakası). _phantom_dedup deseni: imza
        # symbol + drift bucket; aynı imza 12h tekrar bildirilmez.
        _fresh_mismatches = _qty_drift_dedup(sync_mismatches)
        if _fresh_mismatches:
            try:
                from price_action.orchestrator.notifications import push_critical

                push_critical(
                    f"⚠️ JOURNAL/EXCHANGE QTY DRIFT — {len(_fresh_mismatches)} sembol "
                    f">5% qty fark: {_fresh_mismatches[:3]} "
                    f"(aynı drift 12h tekrar bildirilmez)",
                    source="reconciler_qty_drift",
                )
            except Exception:
                pass

        # FIX 2026-05-30 (INC2-reconcile-qty-heal): Güvenli auto-heal.
        # PARTIAL-AWARE (2026-05-31): journal_qty artık remaining_qty.
        # Partial close tablosu zaten kalan qty'yi doğru yönetiyor.
        # Auto-heal sadece partial tablosunda da açıklanamayan gerçek drift
        # durumunda fill_qty'yi günceller.
        # GÜVENLİK KISITLARI:
        #   - Exchange qty < remaining_qty: partial tablosunda kayıt olmayan ek fill.
        #     Drift alarm → fill_qty GÜNCELLEME YAPMA (partial tablo kaynağı —
        #     fill_qty dokunulmaz). Sadece alarm.
        #   - Exchange qty > remaining_qty: phantom benzeri. Otomatik artırma YOK.
        #   - diff >50%: agresif sapma, auto-heal YAPILMAZ, sadece alarm.
        _healed: list[dict] = []
        try:
            import duckdb as _ddb

            _jcon_heal = _ddb.connect(str(_JOURNAL))
            try:
                for _mm in sync_mismatches:
                    _sym = _mm["symbol"]
                    _ex_qty = float(_mm["exchange_qty"])
                    _j_qty = float(_mm["journal_qty"])  # remaining_qty
                    _j_fill_qty = float(_mm.get("journal_fill_qty", _j_qty))
                    _diff_pct = float(_mm["diff_pct"])
                    # Sadece exchange < remaining_qty durumunda düzelt
                    if _ex_qty >= _j_qty:
                        _log(
                            f"QTY_HEAL_SKIP: {_sym} exchange_qty={_ex_qty} >= remaining_qty={_j_qty} — phantom yolu"
                        )
                        continue
                    if _diff_pct > 50.0:
                        _log(
                            f"QTY_HEAL_SKIP: {_sym} diff={_diff_pct:.1f}% >50% — too aggressive, manual review"
                        )
                        continue
                    # PARTIAL-AWARE: partial tablosunda ek bir closed_qty yaz (heal olarak)
                    # fill_qty'yi DEĞİŞTİRME — kaynak-of-truth olarak kalır.
                    # Sadece partial tablosunda kaydı olmayan kısım için partial kayıt ekle.
                    _j_rows = [j for j in journal if j["symbol"] == _sym]
                    for _jr in _j_rows:
                        _sig_id = str(_jr["signal_id"])
                        _partial_sum_row = _jcon_heal.execute(
                            "SELECT COALESCE(SUM(qty_closed),0) FROM futures_partial_closes WHERE trade_id=?",
                            [_sig_id],
                        ).fetchone()
                        _partial_sum = float(_partial_sum_row[0] if _partial_sum_row else 0)
                        _expected_remaining = _j_fill_qty - _partial_sum
                        if abs(_expected_remaining - _ex_qty) < 1e-6:
                            # Zaten senkron (remaining doğru)
                            continue
                        # Gerçek drift var — NOT: fill_qty güncellemesi yerine
                        # eski mantığı koru (backward compat) ama sadece partial tablosu
                        # yoksa (legacy trade) fill_qty güncelle
                        if _partial_sum < 1e-9:
                            # Legacy (partial tablosu yok) — eski heal mantığı
                            try:
                                _jcon_heal.execute(
                                    "UPDATE futures_signals SET fill_qty=? WHERE signal_id=? AND fill_qty=?",
                                    [_ex_qty, _sig_id, _j_fill_qty],
                                )
                                _log(
                                    f"QTY_HEAL (legacy): futures_signals {_sym} sig={_sig_id} "
                                    f"{_j_fill_qty}→{_ex_qty}"
                                )
                                _healed.append(
                                    {"symbol": _sym, "sig_id": _sig_id, "from": _j_fill_qty, "to": _ex_qty}
                                )
                            except Exception as _hu_err:
                                _log(f"QTY_HEAL_ERR futures_signals {_sym}: {str(_hu_err)[:80]}")
                        else:
                            # Partial tablosu var ama hâlâ drift → alarm, dokunma
                            _log(
                                f"QTY_HEAL_SKIP (partial-aware): {_sym} sig={_sig_id} "
                                f"fill_qty={_j_fill_qty} partial_sum={_partial_sum:.6f} "
                                f"expected_remaining={_expected_remaining:.6f} exchange={_ex_qty:.6f} "
                                f"— partial tablosu açıklayamıyor, manuel inceleme gerek"
                            )
                _jcon_heal.commit()
            finally:
                _jcon_heal.close()
        except Exception as _heal_err:
            _log(f"QTY_HEAL_GLOBAL_ERR: {str(_heal_err)[:120]}")
        stats["qty_healed"] = _healed

    return stats


def write_report(stats: dict, *, orphans: int = 0, phantoms: int = 0) -> Path:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
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
