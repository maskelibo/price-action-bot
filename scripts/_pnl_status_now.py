"""Ad-hoc borsa-truth PnL status for the v15p2 testnet account.

Güncelleme 2026-07-10 (Principal): ``pnl durum nedir`` v15p2 performansıdır.
Anchor, v15p2'nin 2 Temmuz 13:07 UTC'deki 4,963 USDT cüzdanıdır. Temiz pencere,
P1 canlı-para-yolu paketinin 9 Temmuz 23:13 UTC restartıdır; F2 öncesi rakamlar
doğrudan kıyaslanmaz.

Bu script özel borsa API'si çağırır; otomatik testlerde çalıştırılmaz.
"""

from __future__ import annotations

import os
import sys
import warnings
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ANCHOR_MS = int(datetime(2026, 7, 2, 13, 7, tzinfo=UTC).timestamp() * 1000)
CLEAN_MS = int(datetime(2026, 7, 9, 23, 13, tzinfo=UTC).timestamp() * 1000)
BASELINE = 4_963.0


def _tr(ts_ms: int) -> str:
    return (datetime.fromtimestamp(ts_ms / 1000, UTC) + timedelta(hours=3)).strftime(
        "%d %b %H:%M"
    )


def _fetch_income(exchange: Any, *, start_ms: int, now_ms: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = start_ms
    while cursor < now_ms:
        batch = exchange.fapiPrivateGetIncome(
            {"startTime": cursor, "endTime": now_ms, "limit": 1_000}
        )
        if not batch:
            break
        rows.extend(batch)
        last = int(batch[-1]["time"])
        if len(batch) < 1_000:
            break
        cursor = last + 1

    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = (row.get("tranId"), row.get("time"), row.get("incomeType"), row.get("income"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _summarize(rows: list[dict[str, Any]]) -> tuple[float, float, float]:
    realized = sum(float(row["income"]) for row in rows if row["incomeType"] == "REALIZED_PNL")
    commission = sum(float(row["income"]) for row in rows if row["incomeType"] == "COMMISSION")
    funding = sum(float(row["income"]) for row in rows if row["incomeType"] == "FUNDING_FEE")
    return realized, commission, funding


def main() -> int:
    os.environ["PA_LOG_QUIET"] = "1"
    warnings.filterwarnings("ignore")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    load_dotenv(ROOT / ".env", override=False)

    from scripts.futures_trade_daily import get_futures_exchange

    exchange = get_futures_exchange()
    now_ms = int(datetime.now(UTC).timestamp() * 1_000)
    income = _fetch_income(exchange, start_ms=ANCHOR_MS, now_ms=now_ms)
    realized, commission, funding = _summarize(income)

    clean = [row for row in income if int(row["time"]) >= CLEAN_MS]
    clean_realized, clean_commission, clean_funding = _summarize(clean)
    closes = [
        row
        for row in income
        if row["incomeType"] == "REALIZED_PNL" and float(row["income"]) != 0.0
    ]
    clean_closes = [row for row in closes if int(row["time"]) >= CLEAN_MS]

    symbol_net: defaultdict[str, float] = defaultdict(float)
    symbol_count: defaultdict[str, int] = defaultdict(int)
    for row in clean_closes:
        symbol = str(row["symbol"])
        symbol_net[symbol] += float(row["income"])
        symbol_count[symbol] += 1

    positions = [
        position
        for position in exchange.fetch_positions()
        if abs(float(position["info"].get("positionAmt", 0))) > 0
    ]
    rows_pos: list[tuple[str, str, float, float, float, float]] = []
    for position in positions:
        symbol = str(position["symbol"])
        amount = float(position["info"]["positionAmt"])
        entry = float(position["info"]["entryPrice"])
        try:
            last_price = float(exchange.fetch_ticker(symbol)["last"])
        except Exception:
            last_price = float(position["info"].get("markPrice", entry))
        side = "LONG" if amount > 0 else "SHORT"
        unrealized = (last_price - entry) * amount
        rows_pos.append((symbol, side, abs(amount), entry, last_price, unrealized))
    rows_pos.sort(key=lambda item: -item[5])

    balance = exchange.fetch_balance()
    wallet = float(balance["info"]["totalWalletBalance"])
    margin = float(balance["info"]["totalMarginBalance"])
    unrealized_total = sum(item[5] for item in rows_pos)

    print("=" * 62)
    print(f"BORSA-TRUTH PnL  ·  {_tr(now_ms)} TR")
    print("=" * 62)
    print(f"NET realized (TÜM v15p2, {len(closes)} kapanış, anchor {_tr(ANCHOR_MS)}):")
    print(
        f"   REALIZED {realized:+.2f}  COMMISSION {commission:+.2f}  "
        f"FUNDING {funding:+.2f}  => NET {realized + commission + funding:+.2f}"
    )
    print(f"└ TEMİZ dönem (P1-fix sonrası {_tr(CLEAN_MS)}, {len(clean_closes)} kapanış):")
    print(
        f"   REALIZED {clean_realized:+.2f}  COMMISSION {clean_commission:+.2f}  "
        f"FUNDING {clean_funding:+.2f}  "
        f"=> NET {clean_realized + clean_commission + clean_funding:+.2f}"
    )
    print(f"UNREALIZED (LAST): {unrealized_total:+.2f}")
    print(f"TOPLAM equity vs $4963 anchor: {wallet + unrealized_total - BASELINE:+.2f}")
    print(f"Cüzdan(wallet) {wallet:.2f} | Margin(equity) {margin:.2f}")
    print("=" * 62)
    print(f"AÇIK POZİSYONLAR ({len(rows_pos)}):")
    for symbol, side, quantity, entry, last_price, unrealized in rows_pos:
        print(
            f"   {symbol:<12} {side:<5} qty={quantity:<10g} entry={entry:<10g} "
            f"last={last_price:<10g} uPnL {unrealized:+.2f}"
        )
    print("=" * 62)
    print("KAPANANLAR — TEMİZ dönem sembol-bazlı (realized, fee hariç):")
    for symbol in sorted(symbol_net, key=lambda item: -symbol_net[item]):
        print(f"   {symbol:<12} {symbol_net[symbol]:+.2f}  ({symbol_count[symbol]} kapanış)")
    print("-" * 62)
    print("Son ~10 kapanış (kronolojik, realized):")
    for row in sorted(clean_closes, key=lambda item: int(item["time"]))[-10:]:
        print(f"   {_tr(int(row['time']))} TR  {row['symbol']:<12} {float(row['income']):+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
