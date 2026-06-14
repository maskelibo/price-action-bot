"""One-time correction (2026-05-31): XLM runner sahte 'tp' kapanışını geri al.

DURUM: futures_signals d37abcd4 (XLM/USDT SHORT 666 @ $0.28385) defterde
2026-05-30 08:00'de close_reason='tp' ile +$18.81 KÂR olarak kapatılmış —
ANCAK borsada hâlâ AÇIK (POS_CHECK: XLM=S666 @ $0.2838, +$37 unrealized,
daemon trailing SL ile koruyor). Yani:
  - Phantom alarm kök-nedeni: defter pozisyonu kaybetti (yanlış kapandı).
  - Kâr şişmesi: olmayan +$18.81 realized PnL deftere yazıldı.

DÜZELTME: trades_closed'den SADECE d37abcd4 satırını sil → signal tekrar
'filled & açık' olur → borsayla eşleşir (phantom biter) + sahte realized PnL
temizlenir. Pozisyona / borsaya DOKUNMAZ. Diğer iki XLM kapanışı (1448, 2291)
gerçek (borsada yok) — onlara dokunulmaz.

Idempotent: satır yoksa no-op. read-only doğrulama önce + sonra.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb

JOURNAL = Path(__file__).resolve().parents[2] / "data" / "futures_journal.duckdb"
TRADE_ID = "d37abcd4392f4e39"


def _connect_write_retry(path: str, *, attempts: int = 8, delay: float = 1.5):
    last = None
    for i in range(attempts):
        try:
            return duckdb.connect(path, read_only=False)
        except Exception as exc:  # daemon kısa kilit tutuyor olabilir
            last = exc
            print(f"  [retry {i+1}/{attempts}] kilit/çakışma: {str(exc)[:80]}")
            time.sleep(delay)
    raise RuntimeError(f"write-lock alınamadı: {last}")


def _show(con, label: str) -> None:
    rows = con.execute(
        "SELECT trade_id, sym, side, entry_price, exit_price, qty, "
        "realized_pnl_usdt, close_reason FROM futures_trades_closed "
        "WHERE trade_id = ?",
        [TRADE_ID],
    ).fetchall()
    print(f"  [{label}] trades_closed[{TRADE_ID}]: {rows if rows else 'YOK (açık)'}")
    sig = con.execute(
        "SELECT signal_id, symbol, side, status, fill_qty, fill_price "
        "FROM futures_signals WHERE signal_id = ?",
        [TRADE_ID],
    ).fetchall()
    print(f"  [{label}] futures_signals[{TRADE_ID}]: {sig}")


def main() -> int:
    if not JOURNAL.exists():
        print(f"HATA: journal yok: {JOURNAL}")
        return 1

    # 1) Önce read-only doğrula
    ro = duckdb.connect(str(JOURNAL), read_only=True)
    try:
        print("== ÖNCE ==")
        _show(ro, "before")
        pre = ro.execute(
            "SELECT realized_pnl_usdt FROM futures_trades_closed WHERE trade_id = ?",
            [TRADE_ID],
        ).fetchall()
    finally:
        ro.close()

    if not pre:
        print("\nNo-op: sahte kapanış zaten yok (signal açık). Bir şey yapılmadı.")
        return 0

    falsely_recorded = float(pre[0][0] or 0.0)
    print(f"\nSilinecek sahte realized PnL: ${falsely_recorded:+.2f}")

    # 2) Yazma penceresinde sil
    con = _connect_write_retry(str(JOURNAL))
    try:
        con.execute("DELETE FROM futures_trades_closed WHERE trade_id = ?", [TRADE_ID])
        con.commit()
    finally:
        con.close()

    # 3) Sonra read-only doğrula
    ro = duckdb.connect(str(JOURNAL), read_only=True)
    try:
        print("\n== SONRA ==")
        _show(ro, "after")
    finally:
        ro.close()

    print(
        f"\nTAMAM: XLM 666 runner tekrar 'açık' (borsayla eşleşir → phantom biter). "
        f"Sahte +${falsely_recorded:.2f} realized PnL temizlendi."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
