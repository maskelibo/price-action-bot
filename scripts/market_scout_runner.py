"""Market Scout CLI runner (Faz 11).

Kullanım:
    .venv/bin/python scripts/market_scout_runner.py --market forex_majors
    .venv/bin/python scripts/market_scout_runner.py --next
    .venv/bin/python scripts/market_scout_runner.py --month 3
    .venv/bin/python scripts/market_scout_runner.py --arb-scan binance,bybit

Sadece async runner — `MarketScoutAgent().monthly_feasibility_study()` veya
`quick_opportunity_scan()` çağırır. Mevcut crypto pipeline'a dokunmaz.

DRY-RUN: `PA_LLM_DRY_RUN=true` ile gerçek LLM/WebSearch çağrısı atlanır;
sadece akış + dosya yazımı test edilir.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from price_action.agents.market_scout import MarketScoutAgent  # noqa: E402


async def _run_feasibility(
    market: str | None, month: int | None
) -> int:
    agent = MarketScoutAgent()
    path = await agent.monthly_feasibility_study(
        target_market=market, target_month=month
    )
    if path is None:
        print("[market_scout] feasibility study üretilmedi (slot yok / market eşleşmedi).", file=sys.stderr)
        return 1
    print(f"[market_scout] feasibility written: {path}")
    return 0


async def _run_arb_scan(pair_str: str, symbol: str) -> int:
    parts = [p.strip() for p in pair_str.split(",") if p.strip()]
    if len(parts) != 2:
        print(
            f"[market_scout] --arb-scan iki borsa istiyor (örn. 'binance,bybit'); aldım: {pair_str!r}",
            file=sys.stderr,
        )
        return 2
    agent = MarketScoutAgent()
    path = await agent.quick_opportunity_scan(
        (parts[0], parts[1]), symbol=symbol
    )
    if path is None:
        print("[market_scout] arb scan üretilmedi.", file=sys.stderr)
        return 1
    print(f"[market_scout] arb scan written: {path}")
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="market_scout_runner",
        description="Market Scout CLI — aylık feasibility study + cross-exchange arb scan.",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--market",
        help="Hedef pazar adı (forex_majors|bist_xu100|bybit_perp|okx_perp|binance_spot).",
    )
    g.add_argument(
        "--next",
        action="store_true",
        help="Rotation'dan bu ay sırada olan pazarı seç ve feasibility üret.",
    )
    g.add_argument(
        "--arb-scan",
        metavar="EX_A,EX_B",
        help="Cross-exchange arb scan (örn. 'binance,bybit').",
    )
    p.add_argument(
        "--month",
        type=int,
        default=None,
        help="Rotation seçimi için ay (1..12). --next ile birlikte kullanılır.",
    )
    p.add_argument(
        "--symbol",
        default="BTC/USDT:USDT",
        help="Arb scan sembolü (default BTC/USDT:USDT).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.arb_scan:
        return asyncio.run(_run_arb_scan(args.arb_scan, args.symbol))
    market = None if args.next else args.market
    return asyncio.run(_run_feasibility(market, args.month))


if __name__ == "__main__":
    raise SystemExit(main())
