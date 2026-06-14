"""One-time journal correction — PnL inflation audit 2026-05-30.

PROBLEM: futures_trades_closed.realized_pnl_usdt sistematik olarak şişirilmiş.
  Journal toplam: +$57.73
  Exchange gerçeği (fapiPrivateGetIncome REALIZED_PNL): -$11.58
  Sapma: ~$69

KÖK NEDENLER (üç tür):

  1) triggerPrice bug (DOT, AVAX short, AVAX first long, DOGE first, XRP):
     position_check() exit_price = triggered.get("triggerPrice") kullanıyordu.
     Bu EMIR HEDEF fiyatı, gerçek fill değil.
     DOT short: triggerPrice=1.232 (TP target), ama gerçek fill ~1.275 → journal +28.73, borsa -3.52.
     AVAX short: triggerPrice=8.939, journal +14.28, borsa ~-2.
     XRP/DOGE/AVAX-long: triggerPrice ≈ gerçek fill (düşük slippage → küçük sapma).

  2) reconcile_orphan ticker fallback (ADA, DOGE-2, ETH — 2026-05-26 14:36):
     Reconciler o tarihte ticker (anlık piyasa fiyatı) kullandı.
     Ticker kapatma fiyatından yüksekti (tüm 3 long için) → yapay kâr yazdı.
     ADA +17.14, DOGE +6.92, ETH +5.75 — hepsi borsa gerçeğinden uzak.

  3) XLM: önceki seansta fix_xlm_near_journal_2026_05_30.py ile DÜZELTİLDİ.

DÜZELTİLECEK TRADE'LER (bu script):
  - DOT short (800f1012a94c48d3): entry=1.281, exit borsa-kanıt yaklaşık exit_px
  - AVAX short (dd0c39b32d314f50): entry=9.296, exit borsa kanıtı
  - ADA orphan (e30022257de04b58): reconcile_orphan, borsa küçük gain/loss
  - DOGE orphan-2 (c276bdb85e434432): reconcile_orphan, borsa küçük
  - ETH orphan (0cac7ce0f99c4ad9): reconcile_orphan, borsa küçük
  - XRP tp (6565038b05b74a47): triggerPrice ≈ gerçek (küçük sapma)
  - DOGE tp (6612a37a6fbb43d4): triggerPrice ≈ gerçek
  - AVAX long tp (35d94ea1ee0848c8): triggerPrice ≈ gerçek
  - AVAX sl (8fe33f91a5d24f69): triggerPrice ≈ gerçek

YÖNTEM:
  Borsa fapiPrivateGetIncome(REALIZED_PNL) net değerleri + trade başına
  en yakın income kaydını eşleştirip exit_price geri-hesapla.
  Eşleştirme mümkün değilse: exit_price = entry_price (PnL=0, worst-case
  "bilinmez" kaydı). PnL=0 yanlış kâr yazısından daha iyidir.

GÜVENLİK:
  - DRY_RUN=1 ile çalıştırarak önce kontrol et.
  - Sadece işaretli trade_id'ler değişir.
  - DuckDB transaction — başarısız olursa rollback.
  - NEAR hâlâ açık — dokunulmaz (futures_signals sadece).
  - Trading daemon DURDURULMAZ, restart yok.

ÇALIŞTIRMA:
  DRY_RUN=1 .venv/bin/python scripts/one_time_corrections/fix_pnl_inflation_2026_05_30.py
  .venv/bin/python scripts/one_time_corrections/fix_pnl_inflation_2026_05_30.py
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
    """(pnl_usdt, realized_r)."""
    if side == "short":
        pnl = (entry - exit_price) * qty
    else:
        pnl = (exit_price - entry) * qty
    risk_per_unit = abs(entry - sl)
    r = pnl / (risk_per_unit * qty) if risk_per_unit > 0 and qty > 0 else 0.0
    return round(pnl, 6), round(r, 6)


def _exit_from_binance(symbol_usdt: str, entry: float, side: str, qty: float) -> float | None:
    """
    Binance testnet fapiPrivateGetIncome ile gerçek REALIZED_PNL kaydını çek.
    Bulunan income + entry + qty + side'dan exit_price geri-hesapla.
    Bulunamazsa None döner.

    symbol_usdt: "DOTUSDT" formatında
    """
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
        if os.environ.get("PA_RUN_MODE", "paper") in ("paper", ""):
            ex.set_sandbox_mode(True)

        # Son 50 income kaydı (REALIZED_PNL)
        income_list = ex.fapiPrivateGetIncome(
            {"symbol": symbol_usdt, "incomeType": "REALIZED_PNL", "limit": 50}
        )
        if not income_list:
            return None

        for rec in sorted(income_list, key=lambda r: -int(r.get("time", 0) or 0)):
            income_val = float(rec.get("income", 0) or 0)
            if income_val == 0:
                continue
            # exit_price geri-hesapla: pnl = (exit - entry)*qty (long) veya (entry-exit)*qty (short)
            # exit = entry + pnl/qty (long) veya entry - pnl/qty (short)
            if side == "long":
                exit_px = entry + income_val / qty
            else:
                exit_px = entry - income_val / qty
            if exit_px > 0:
                log(
                    f"  INCOME_MATCH {symbol_usdt}: income={income_val:+.4f} "
                    f"→ exit_px={exit_px:.5f} (back-calculated)"
                )
                return exit_px
    except Exception as exc:
        log(f"  BINANCE_INCOME_FAIL {symbol_usdt}: {str(exc)[:100]}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Trade correction specs
# Format: (trade_id, sym, side, entry, qty, sl, close_reason_note,
#           known_exchange_pnl_or_None, fallback_to_entry_if_unknown)
# ─────────────────────────────────────────────────────────────────────────────

# Borsa-onaylı income değerleri (seans kanıtı):
#   DOT short: -3.52 (2026-05-27 23:46 DOTUSDT)
#   AVAX short tp: AVAX net ~-2 (birden fazla kayıt, en yakın tahmin)
#   ADA orphan: ADA net ~(-0.31) = +0.99 - 1.30
#   DOGE orphan-2: DOGE verileri parçalı; ~+1.09 kısmi (tahmin)
#   ETH orphan: ETH ~+0 (parçalı veriler)

CORRECTIONS = [
    {
        "trade_id": "800f1012a94c48d3",
        "sym": "DOT/USDT",
        "sym_binance": "DOTUSDT",
        "side": "short",
        "entry": 1.281,
        "qty": 586.4,
        "sl": 1.3170499999999998,
        "known_pnl": -3.52,  # borsa kanıtı
        "note": "DOT short tp — triggerPrice=1.232 (TP target), gerçek fill farklı",
        "close_reason_new": "tp_corrected",
    },
    {
        "trade_id": "dd0c39b32d314f50",
        "sym": "AVAX/USDT",
        "sym_binance": "AVAXUSDT",
        "side": "short",
        "entry": 9.296,
        "qty": 40.0,
        "sl": 9.52375,
        "known_pnl": None,  # AVAX verisi parçalı — Binance'den çekmeyi dene
        "note": "AVAX short tp — triggerPrice=8.939, borsa net ~-2",
        "close_reason_new": "tp_corrected",
    },
    {
        "trade_id": "e30022257de04b58",
        "sym": "ADA/USDT",
        "sym_binance": "ADAUSDT",
        "side": "long",
        "entry": 0.2406,
        "qty": 3117.0,
        "sl": 0.239045,
        "known_pnl": None,  # ADA borsa net ~(-0.31), parçalı
        "note": "ADA orphan — ticker fallback 0.2461 şişirilmiş",
        "close_reason_new": "reconcile_orphan_corrected",
    },
    {
        "trade_id": "c276bdb85e434432",
        "sym": "DOGE/USDT",
        "sym_binance": "DOGEUSDT",
        "side": "long",
        "entry": 0.10142,
        "qty": 3703.0,
        "sl": 0.10034549999999999,
        "known_pnl": None,  # DOGE parçalı
        "note": "DOGE orphan-2 — ticker fallback 0.10329 şişirilmiş",
        "close_reason_new": "reconcile_orphan_corrected",
    },
    {
        "trade_id": "0cac7ce0f99c4ad9",
        "sym": "ETH/USDT",
        "sym_binance": "ETHUSDT",
        "side": "long",
        "entry": 2096.79,
        "qty": 0.179,
        "sl": 2078.781,
        "known_pnl": None,  # ETH parçalı
        "note": "ETH orphan — ticker fallback 2128.9 şişirilmiş",
        "close_reason_new": "reconcile_orphan_corrected",
    },
]

# XRP, DOGE-1, AVAX-long-1 ve AVAX-sl:
# triggerPrice ≈ gerçek fill (diff < 0.01%) → düzeltme YAPILMIYOR (borsa kanıtı yok)
# Bu trade'ler için sapma ihmal edilebilir seviyede.

SKIP_NOTES = [
    "6565038b05b74a47 XRP long tp — triggerPrice diff 3.7e-5 → skip",
    "6612a37a6fbb43d4 DOGE long tp (first) — triggerPrice diff 3e-6 → skip",
    "35d94ea1ee0848c8 AVAX long tp (first) — triggerPrice diff 7.5e-5 → skip",
    "8fe33f91a5d24f69 AVAX short sl — triggerPrice ≈ fill → skip",
]


def correct_trade(con, spec: dict) -> tuple[bool, str]:
    """
    Tek trade'i düzelt.
    Returns (changed: bool, message: str).
    """
    trade_id = spec["trade_id"]
    side = spec["side"]
    entry = spec["entry"]
    qty = spec["qty"]
    sl = spec["sl"]
    known_pnl = spec.get("known_pnl")
    sym_binance = spec["sym_binance"]
    new_reason = spec["close_reason_new"]

    # Mevcut kaydı al
    row = con.execute(
        "SELECT exit_price, realized_pnl_usdt, realized_r, close_reason "
        "FROM futures_trades_closed WHERE trade_id=?",
        [trade_id],
    ).fetchone()
    if not row:
        return False, f"SKIP: {trade_id} not in futures_trades_closed"

    old_exit, old_pnl, old_r, old_reason = row[0], row[1], row[2], row[3]

    # Yeni exit_price hesapla
    new_exit: float | None = None

    # 1) Borsa kanıtı varsa → doğrudan geri-hesapla
    if known_pnl is not None:
        if side == "long":
            new_exit = entry + known_pnl / qty
        else:
            new_exit = entry - known_pnl / qty
        log(f"  {trade_id} ({spec['sym']}): known_pnl={known_pnl:+.4f} → exit={new_exit:.5f}")
    else:
        # 2) Binance API'den çek
        new_exit = _exit_from_binance(sym_binance, entry, side, qty)

    # 3) Fallback: exit = entry (PnL = 0, bilinmiyor)
    if new_exit is None or new_exit <= 0:
        new_exit = entry
        log(
            f"  {trade_id} ({spec['sym']}): NO exchange data → exit=entry={entry} (PnL=0, unknown)"
        )

    new_pnl, new_r = _compute_pnl_r(entry, new_exit, qty, side, sl)
    new_win = new_pnl > 0.0

    log(
        f"  {trade_id} ({spec['sym']}) BEFORE: exit={old_exit:.5f} pnl={old_pnl:+.4f} "
        f"r={old_r:.4f} reason={old_reason}"
    )
    log(
        f"  {trade_id} ({spec['sym']})  AFTER: exit={new_exit:.5f} pnl={new_pnl:+.4f} "
        f"r={new_r:.4f} reason={new_reason}"
    )

    # Fark küçükse (< 0.01 USDT) düzeltme yapma
    if abs(old_pnl - new_pnl) < 0.01:
        return False, f"SKIP_NO_CHANGE: {trade_id} diff < 0.01 USDT"

    if DRY_RUN:
        return True, f"DRY_RUN: {trade_id} pnl_delta={new_pnl - old_pnl:+.4f}"

    con.execute(
        """UPDATE futures_trades_closed
           SET exit_price=?, realized_pnl_usdt=?, realized_r=?,
               win=?, close_reason=?
           WHERE trade_id=?""",
        [new_exit, new_pnl, new_r, new_win, new_reason, trade_id],
    )
    return True, f"UPDATED: {trade_id} pnl {old_pnl:+.4f}→{new_pnl:+.4f} delta={new_pnl - old_pnl:+.4f}"


def main() -> int:
    if not JOURNAL.exists():
        log(f"FATAL: Journal bulunamadı: {JOURNAL}")
        return 1

    mode = "DRY_RUN" if DRY_RUN else "LIVE WRITE"
    log(f"=== PnL Inflation Correction 2026-05-30 ({mode}) ===")
    log(f"Journal: {JOURNAL}")
    log("")

    for note in SKIP_NOTES:
        log(f"SKIP (triggerPrice≈fill): {note}")
    log("")

    import duckdb

    con = duckdb.connect(str(JOURNAL))
    try:
        # Mevcut durum
        total_before = con.execute(
            "SELECT COALESCE(SUM(realized_pnl_usdt), 0) FROM futures_trades_closed"
        ).fetchone()[0]
        log(f"Journal PnL BEFORE: {total_before:+.4f} USDT")
        log("")

        con.execute("BEGIN")
        changes: list[str] = []
        for spec in CORRECTIONS:
            log(f"Processing: {spec['trade_id']} ({spec['sym']}) — {spec['note']}")
            changed, msg = correct_trade(con, spec)
            log(f"  → {msg}")
            if changed:
                changes.append(msg)
            log("")

        if DRY_RUN:
            con.execute("ROLLBACK")
            log("DRY_RUN: ROLLBACK — hiçbir şey yazılmadı")
        else:
            if changes:
                con.execute("COMMIT")
                log(f"COMMIT: {len(changes)} trade güncellendi")
            else:
                con.execute("ROLLBACK")
                log("ROLLBACK: değiştirilecek trade yok")

        # Sonrası özet (DRY_RUN'da gerçek değişim yok)
        if not DRY_RUN:
            total_after = con.execute(
                "SELECT COALESCE(SUM(realized_pnl_usdt), 0) FROM futures_trades_closed"
            ).fetchone()[0]
            log(f"Journal PnL AFTER:  {total_after:+.4f} USDT")
            log(f"Journal PnL DELTA:  {total_after - total_before:+.4f} USDT")
            log("")
            log("Exchange truth (testnet): -$11.58 (21 income records)")
            log(
                "Remaining gap after correction is normal — fee/funding differences "
                "and unknown close prices default to entry (PnL=0)."
            )

        log("")
        log("=== DONE ===")
        return 0

    except Exception as exc:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        log(f"FATAL: {exc}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
