"""Instruments tablosunu ccxt'ten doldur — SEC54.5 (DQ-01 / DQ-04).

Usage:
    python scripts/populate_instruments.py [--dry-run]

Davranış:
    - Binance USDM Futures markets'tan 10 sembolün metadata'sını çeker.
    - DuckDB instruments tablosuna upsert eder (idempotent).
    - Delisted semboller silinmez; delisting_date ile etiketlenir.
    - Tick_size ve lot_step ccxt precision bloğundan alınır; None varsa NaN bırakır.
    - Hiçbir değer forward-fill / default-fill edilmez.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from price_action.data.store import OHLCVStore
from price_action.logging_config import logger

# 10 canonical sembol — futures_trade_daily.py / backfill_5y.py ile aynı.
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
]

VENUE = "binance"
MARKET_TYPE = "linear_perp"  # USDM perpetual


def _build_exchange() -> Any:  # pragma: no cover - integration
    """DQ-04: futures endpoint zorunlu."""
    import ccxt
    return ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })


def _extract_instrument_row(
    venue: str,
    symbol: str,
    market: dict[str, Any],
) -> dict[str, Any]:
    """ccxt market dict → instruments tablo satırı.

    Eksik alanlar None olarak bırakılır (forward-fill YOK).
    """
    info = market.get("info") or {}
    precision = market.get("precision") or {}
    limits = market.get("limits") or {}

    # Listing date
    listing_ts = info.get("onboardDate") or info.get("launchTime")
    listing_date = None
    if listing_ts:
        try:
            ms = int(listing_ts)
            listing_date = datetime.fromtimestamp(ms / 1000 if ms > 1e12 else ms, tz=timezone.utc)
        except (TypeError, ValueError):
            listing_date = None

    # Tick size (price precision)
    tick_size_raw = precision.get("price")
    tick_size = Decimal(str(tick_size_raw)) if tick_size_raw is not None else None

    # Lot step (amount precision)
    lot_step_raw = precision.get("amount")
    lot_step = Decimal(str(lot_step_raw)) if lot_step_raw is not None else None

    # Min notional
    cost_min = (limits.get("cost") or {}).get("min")
    min_notional = Decimal(str(cost_min)) if cost_min is not None else None

    # Delisting: ccxt active=False → delisted
    is_active = bool(market.get("active", True))
    delisting_date = None if is_active else datetime.now(timezone.utc)

    return {
        "venue": venue,
        "symbol": symbol,
        "market_type": MARKET_TYPE,
        "base": (market.get("base") or "").upper() or None,
        "quote": (market.get("quote") or "").upper() or None,
        "listing_date": listing_date,
        "delisting_date": delisting_date,
        "tick_size": float(tick_size) if tick_size is not None else None,
        "lot_step": float(lot_step) if lot_step is not None else None,
        "min_notional_usdt": float(min_notional) if min_notional is not None else None,
        "is_active": is_active,
    }


def populate(dry_run: bool = False) -> int:
    """instruments tablosunu doldur.

    Dönen değer: upsert edilen satır sayısı.
    """
    print(f"[populate_instruments] venue={VENUE} market_type={MARKET_TYPE} dry_run={dry_run}")
    print(f"  Symbols ({len(SYMBOLS)}): {SYMBOLS}")

    exchange = _build_exchange()
    print("  Loading markets from ccxt (futures endpoint)...")
    markets: dict[str, Any] = exchange.load_markets()

    rows: list[dict[str, Any]] = []
    missing: list[str] = []

    for sym in SYMBOLS:
        market = markets.get(sym)
        if market is None:
            logger.bind(venue=VENUE, symbol=sym).warning("populate_instruments.symbol_not_found")
            missing.append(sym)
            continue
        row = _extract_instrument_row(VENUE, sym, market)
        rows.append(row)
        tick = row["tick_size"]
        lot = row["lot_step"]
        notional = row["min_notional_usdt"]
        listing = row["listing_date"].date() if row["listing_date"] else "N/A"
        active_str = "ACTIVE" if row["is_active"] else "DELISTED"
        print(
            f"  {sym:<15} tick={tick}  lot={lot}  min_notional={notional}  "
            f"listing={listing}  {active_str}"
        )

    if missing:
        print(f"\n  [WARN] {len(missing)} sembol futures markets'ta bulunamadı: {missing}")
        print("  Bu semboller instruments tablosuna eklenmeyecek.")

    if dry_run:
        print(f"\n[DRY-RUN] {len(rows)} satır upsert EDİLMEYECEK.")
        return 0

    store = OHLCVStore()
    written = store.upsert_instruments(rows)
    print(f"\n[OK] {written} satır instruments tablosuna upsert edildi.")
    logger.bind(venue=VENUE, written=written, missing=len(missing)).info(
        "populate_instruments.done"
    )
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Instruments tablosunu ccxt'ten doldur")
    parser.add_argument("--dry-run", action="store_true", help="Sadece göster, yazma")
    args = parser.parse_args()

    written = populate(dry_run=args.dry_run)
    print(f"\nDone. written={written}")


if __name__ == "__main__":
    main()
