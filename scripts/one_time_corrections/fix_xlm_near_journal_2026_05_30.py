"""One-time journal correction — XLM/NEAR incidents 2026-05-30.

Bu script ÇALIŞTIRILMADAN ÖNCE okunmalı ve operatör onaylamalıdır.
Çalıştırmak için: .venv/bin/python scripts/one_time_corrections/fix_xlm_near_journal_2026_05_30.py

Yapılan düzeltmeler:
  1) XLM/USDT (trade_id=a68e242f4d034ff9):
     - exit_price: 0.25819 → 0.24959 (Binance testnet order 379985598 gerçek fill)
     - realized_pnl_usdt: -35.69 → -23.24 (borsa onayı)
     - realized_r: yeniden hesaplanır
     - close_reason: 'reconcile_orphan' → 'reconcile_orphan_corrected'

  2) NEAR/USDT (signal_id=7ef0a377e7d64129):
     - futures_signals.fill_qty: 291.0 → 219.0 (exchange gerçek fill)
     - futures_trades_closed'de (varsa) qty + pnl güncellenir

GÜVENLİK:
  - Sadece bu iki kayıt değişir. Başka hiçbir satıra dokunmaz.
  - DRY_RUN=1 env ile preview (gerçek yazma yok).
  - Her adım öncesi/sonrası değerleri stdout'a yazar.
  - Yazma başarısız olursa rollback (duckdb transaction).

Borsa kanıtı:
  XLM: order 379985598, 2026-05-30 01:55:44 UTC, fill=0.24959, qty=1448, PNL=-23.24 USDT
  NEAR: exchange qty=219 (POS_CHECK 21:00Z'dan itibaren, reconcile diff=24.74%)
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

JOURNAL = ROOT / "data" / "futures_journal.duckdb"
DRY_RUN = os.environ.get("DRY_RUN", "0").strip() not in ("0", "", "false", "False")


def log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)


def _compute_pnl_r(
    entry: float, exit_price: float, qty: float, side: str, sl: float
) -> tuple[float, float]:
    if side == "short":
        pnl = (entry - exit_price) * qty
    else:
        pnl = (exit_price - entry) * qty
    risk_per_unit = abs(entry - sl)
    r = pnl / (risk_per_unit * qty) if risk_per_unit > 0 and qty > 0 else 0.0
    return round(pnl, 6), round(r, 6)


def fix_xlm(con) -> bool:
    """
    XLM correction:
      trade_id = a68e242f4d034ff9
      entry_price = 0.23354, qty = 1448, side = short
      sl_price = 0.25086 (from journal — signal sl_price)
      exit_price: 0.25819 → 0.24959
    """
    TRADE_ID = "a68e242f4d034ff9"
    CORRECT_EXIT = 0.24959
    CORRECT_PNL = -23.24  # borsa onayı (fee dahil değil, raw PnL)
    # sl_price'ı futures_signals'dan al
    sig = con.execute(
        "SELECT fill_price, fill_qty, sl_price FROM futures_signals WHERE signal_id=?", [TRADE_ID]
    ).fetchone()
    if not sig:
        log(f"XLM FIX SKIP: signal_id={TRADE_ID} not found in futures_signals")
        return False
    entry_price, qty, sl_price = float(sig[0]), float(sig[1]), float(sig[2])

    # Mevcut kaydı göster
    before = con.execute(
        "SELECT exit_price, realized_pnl_usdt, realized_r, close_reason "
        "FROM futures_trades_closed WHERE trade_id=?",
        [TRADE_ID],
    ).fetchone()
    if not before:
        log(f"XLM FIX SKIP: trade_id={TRADE_ID} not in futures_trades_closed")
        return False
    log(
        f"XLM BEFORE: exit={before[0]:.5f} pnl={before[1]:.4f} r={before[2]:.4f} reason={before[3]}"
    )

    # Yeni PnL/R hesapla
    new_pnl, new_r = _compute_pnl_r(entry_price, CORRECT_EXIT, qty, "short", sl_price)
    # Borsa onayı -23.24 var; hesaplanan değeri kullan (daha doğru — fee dahil değil)
    # İkisini logla, hesaplananı yaz
    log(f"XLM NEW (calculated): exit={CORRECT_EXIT} pnl={new_pnl:.4f} r={new_r:.4f}")
    log(f"XLM NEW (exchange confirmed pnl): {CORRECT_PNL}")

    if DRY_RUN:
        log("XLM DRY_RUN: gerçek yazma yapılmadı")
        return True

    con.execute(
        """UPDATE futures_trades_closed
           SET exit_price=?, realized_pnl_usdt=?, realized_r=?,
               win=?, close_reason='reconcile_orphan_corrected'
           WHERE trade_id=?""",
        [CORRECT_EXIT, new_pnl, new_r, bool(new_pnl > 0), TRADE_ID],
    )
    after = con.execute(
        "SELECT exit_price, realized_pnl_usdt, realized_r, close_reason "
        "FROM futures_trades_closed WHERE trade_id=?",
        [TRADE_ID],
    ).fetchone()
    log(f"XLM AFTER: exit={after[0]:.5f} pnl={after[1]:.4f} r={after[2]:.4f} reason={after[3]}")
    return True


def fix_near(con) -> bool:
    """
    NEAR correction:
      signal_id = 7ef0a377e7d64129
      fill_qty: 291.0 → 219.0 (exchange gerçeği)
    NEAR hâlâ açık olduğundan futures_trades_closed'da kaydı yok.
    Sadece futures_signals.fill_qty güncellenir.
    """
    SIG_ID = "7ef0a377e7d64129"
    CORRECT_QTY = 219.0

    sig = con.execute(
        "SELECT symbol, fill_price, fill_qty, status " "FROM futures_signals WHERE signal_id=?",
        [SIG_ID],
    ).fetchone()
    if not sig:
        log(f"NEAR FIX SKIP: signal_id={SIG_ID} not found")
        return False
    sym, fill_px, fill_qty, status = sig[0], float(sig[1]), float(sig[2]), sig[3]
    log(f"NEAR BEFORE: symbol={sym} fill_px={fill_px} fill_qty={fill_qty} status={status}")

    if abs(fill_qty - CORRECT_QTY) < 0.01:
        log(f"NEAR FIX SKIP: fill_qty already {fill_qty} ≈ {CORRECT_QTY}")
        return True

    if DRY_RUN:
        log(f"NEAR DRY_RUN: would update fill_qty {fill_qty}→{CORRECT_QTY}")
        return True

    con.execute(
        "UPDATE futures_signals SET fill_qty=? WHERE signal_id=? AND fill_qty=?",
        [CORRECT_QTY, SIG_ID, fill_qty],
    )
    # futures_trades_closed (eğer bu arada kapandıysa)
    closed = con.execute(
        "SELECT qty, realized_pnl_usdt FROM futures_trades_closed WHERE trade_id=?", [SIG_ID]
    ).fetchone()
    if closed:
        log(f"NEAR: trades_closed bulundu (kapanmış), qty güncelleniyor: {closed[0]}→{CORRECT_QTY}")
        # qty güncellenince PnL de yeniden hesaplanmalı — entry/exit bilgisi al
        trade_row = con.execute(
            "SELECT entry_price, exit_price, side, close_reason FROM futures_trades_closed WHERE trade_id=?",
            [SIG_ID],
        ).fetchone()
        if trade_row:
            _entry, _exit, _side, _reason = trade_row
            sig_for_sl = con.execute(
                "SELECT sl_price FROM futures_signals WHERE signal_id=?", [SIG_ID]
            ).fetchone()
            _sl = float(sig_for_sl[0]) if sig_for_sl else 0.0
            _new_pnl, _new_r = _compute_pnl_r(
                float(_entry), float(_exit), CORRECT_QTY, str(_side), _sl
            )
            con.execute(
                "UPDATE futures_trades_closed SET qty=?, realized_pnl_usdt=?, realized_r=?, win=? "
                "WHERE trade_id=?",
                [CORRECT_QTY, _new_pnl, _new_r, bool(_new_pnl > 0), SIG_ID],
            )
            log(f"NEAR trades_closed AFTER: qty={CORRECT_QTY} pnl={_new_pnl:.4f} r={_new_r:.4f}")
    else:
        log(
            "NEAR: trades_closed kaydı yok (pozisyon hâlâ açık) — sadece futures_signals güncellendi"
        )

    after = con.execute(
        "SELECT fill_qty FROM futures_signals WHERE signal_id=?", [SIG_ID]
    ).fetchone()
    log(f"NEAR AFTER: fill_qty={after[0] if after else 'N/A'}")
    return True


def main() -> int:
    if not JOURNAL.exists():
        log(f"FATAL: Journal bulunamadı: {JOURNAL}")
        return 1

    mode = "DRY_RUN" if DRY_RUN else "LIVE WRITE"
    log(f"=== Journal Correction 2026-05-30 ({mode}) ===")
    log(f"Journal: {JOURNAL}")

    import duckdb

    con = duckdb.connect(str(JOURNAL))
    try:
        con.execute("BEGIN")
        xlm_ok = fix_xlm(con)
        near_ok = fix_near(con)
        if DRY_RUN:
            con.execute("ROLLBACK")
            log("DRY_RUN: ROLLBACK yapıldı, hiçbir şey yazılmadı")
        else:
            if xlm_ok or near_ok:
                con.execute("COMMIT")
                log("COMMIT: düzeltmeler yazıldı")
            else:
                con.execute("ROLLBACK")
                log("ROLLBACK: hiçbir düzeltme yapılmadı (kayıtlar bulunamadı veya zaten doğru)")
    except Exception as exc:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        log(f"FATAL: {exc}")
        return 1
    finally:
        con.close()

    log("=== DONE ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
